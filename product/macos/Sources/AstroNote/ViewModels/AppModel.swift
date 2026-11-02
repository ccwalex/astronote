import Foundation
import Combine

@MainActor
final class AppModel: ObservableObject {
    struct ConnectionState {
        var origin: String = ""
        var token: String = ""
        var isConnected: Bool = false
        var errorMessage: String?
    }

    enum CanvasTool: String, CaseIterable {
        case pointer
        case text
        case image
        case pdf
        case generic
    }

    @Published var connection = ConnectionState()
    @Published var workspace: Workspace?
    @Published var selectedLibraryNodeId: String?
    @Published var selectedProjectId: String?
    @Published var selectedSpaceId: String?
    @Published var hydratedProject: Project?
    @Published var isLoading = false
    @Published var statusMessage: String?
    @Published var errorMessage: String?
    @Published var searchQuery = ""
    @Published var searchResults: [SearchHit] = []
    @Published var ragMasterNodes: [RagMasterNode] = []
    @Published var canvasZoom: Double = 1.0
    @Published var selectedTool: CanvasTool = .pointer
    @Published var canWritePage = true
    @Published var isDirty = false

    private var client: APIClient?
    private var baseRevision: Int?
    private var presenceTask: Task<Void, Never>?
    private var saveTask: Task<Void, Never>?
    private var assetTextCache: [String: String] = [:]

    func bootstrap() async {
        connection.errorMessage = nil
        let profile = await Self.loadKeychainProfile()
        guard let profile else { return }
        connection.origin = profile.origin
        connection.token = profile.apiToken
        await connectUsingStoredProfile()
    }

    func connect(origin: String, token: String) async {
        connection.origin = APIClient.normalizeOrigin(origin)
        connection.token = token.trimmingCharacters(in: .whitespacesAndNewlines)
        connection.errorMessage = nil
        await connectUsingStoredProfile()
    }

    private func connectUsingStoredProfile() async {
        guard !connection.origin.isEmpty, !connection.token.isEmpty else { return }
        isLoading = true
        defer { isLoading = false }
        do {
            let storedUserId = await Self.loadKeychainProfile()?.userId
            var profile = ConnectionProfile(origin: connection.origin, apiToken: connection.token, userId: storedUserId)
            let api = APIClient(origin: profile.origin, apiToken: profile.apiToken, userId: profile.userId)
            _ = try await api.createSession(label: "macos")
            try await api.testConnection()
            profile.userId = api.userId
            try await Self.saveKeychainProfile(profile)
            client = api
            connection.isConnected = true
            connection.errorMessage = nil
            let nav = try await api.fetchWorkspaceNav()
            workspace = nav
            baseRevision = nav.workspace_revision
            statusMessage = "Connected to \(profile.origin)"
        } catch {
            connection.isConnected = false
            client = nil
            connection.errorMessage = error.localizedDescription
        }
    }

    private static func loadKeychainProfile() async -> ConnectionProfile? {
        await Task.detached(priority: .userInitiated) {
            KeychainStore.loadProfile()
        }.value
    }

    private static func saveKeychainProfile(_ profile: ConnectionProfile) async throws {
        try await Task.detached(priority: .userInitiated) {
            try KeychainStore.saveProfile(profile)
        }.value
    }

    func disconnect() {
        Task {
            await client?.endSession()
        }
        stopPresenceLoop()
        client = nil
        connection.isConnected = false
        workspace = nil
        hydratedProject = nil
    }

    func openLibraryNode(_ node: LibraryNode) async {
        guard node.kind == "page", let projectId = node.target_project_id else { return }
        selectedLibraryNodeId = node.id
        await openProject(projectId)
    }

    func openProject(_ projectId: String) async {
        guard let client else { return }
        selectedProjectId = projectId
        selectedSpaceId = nil
        isLoading = true
        errorMessage = nil
        defer { isLoading = false }
        do {
            let pageLoad = try await client.fetchPageLoad(projectId: projectId, libraryNodeId: selectedLibraryNodeId)
            workspace = pageLoad.nav
            baseRevision = pageLoad.workspace_revision ?? pageLoad.nav.workspace_revision
            if let project = pageLoad.project {
                hydratedProject = project
            } else {
                hydratedProject = try await client.fetchProject(projectId)
            }
            if let resolved = pageLoad.resolved_library_node_id {
                selectedLibraryNodeId = resolved
            }
            startPresenceLoop(projectId: projectId)
        } catch {
            errorMessage = error.localizedDescription
        }
    }

    func selectSpace(_ spaceId: String?) {
        selectedSpaceId = spaceId
    }

    func assetText(for assetId: String) async -> String {
        if let cached = assetTextCache[assetId] { return cached }
        guard let client else { return "" }
        if let inline = hydratedProject?.assets[assetId]?.content, !(inline.isEmpty) {
            assetTextCache[assetId] = inline
            return inline
        }
        do {
            let text = try await client.fetchAssetText(assetId: assetId)
            assetTextCache[assetId] = text
            return text
        } catch {
            return ""
        }
    }

    func updateTextAsset(assetId: String, markdown: String) {
        guard var project = hydratedProject, var asset = project.assets[assetId] else { return }
        asset.content = markdown
        project.assets[assetId] = asset
        hydratedProject = project
        if var workspace, let projectId = selectedProjectId, var stored = workspace.projects[projectId] {
            stored.assets[assetId] = asset
            workspace.projects[projectId] = stored
            self.workspace = workspace
        }
        assetTextCache[assetId] = markdown
        isDirty = true
        scheduleSave()
    }

    func scheduleSave() {
        saveTask?.cancel()
        saveTask = Task { [weak self] in
            try? await Task.sleep(nanoseconds: 900_000_000)
            await self?.saveNow()
        }
    }

    func saveNow() async {
        guard let client, var workspace, isDirty else { return }
        if let projectId = selectedProjectId, let project = hydratedProject {
            workspace.projects[projectId] = project
            for (_, asset) in project.assets {
                guard asset.kind == "markdown", let content = asset.content else { continue }
                try? await client.putAssetText(assetId: asset.id, content: content, filename: asset.filename)
            }
        }
        let session = client.userId
        do {
            let saved = try await client.saveWorkspace(workspace, baseRevision: baseRevision, pageWriteSession: session)
            self.workspace = saved
            baseRevision = saved.workspace_revision
            isDirty = false
            statusMessage = "Saved"
        } catch APIClientError.staleSave(let detail) {
            errorMessage = detail
            statusMessage = "Save conflict — reload the page"
        } catch {
            errorMessage = error.localizedDescription
        }
    }

    func runSearch(mode: SearchMode) async {
        guard let client else { return }
        let query = searchQuery.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !query.isEmpty else { return }
        do {
            switch mode {
            case .plain:
                let response = try await client.search(query: query, libraryNodeId: selectedLibraryNodeId)
                searchResults = response.search_results ?? []
                ragMasterNodes = []
            case .rag:
                let response = try await client.ragSearch(query: query, libraryNodeId: selectedLibraryNodeId)
                searchResults = response.search_results ?? []
                ragMasterNodes = response.master_nodes ?? []
            }
        } catch {
            errorMessage = error.localizedDescription
        }
    }

    enum SearchMode { case plain, rag }

    func openSearchHit(_ hit: SearchHit) async {
        if let projectId = hit.project_id {
            await openProject(projectId)
            if let spaceId = hit.space_id {
                selectedSpaceId = spaceId
            }
        }
    }

    func createFolder() {
        Task { await createLibraryItem(kind: "folder") }
    }

    func createPage() {
        Task { await createLibraryItem(kind: "page") }
    }

    private func createLibraryItem(kind: String) async {
        guard let client else { return }
        let name = kind == "folder" ? "New Folder" : "New Page"
        let path = name
        do {
            if kind == "folder" {
                try await client.createFolder(path: path)
            } else {
                try await client.createPage(path: path)
            }
            workspace = try await client.fetchWorkspaceNav()
            baseRevision = workspace?.workspace_revision
            statusMessage = "Created \(name)"
        } catch {
            errorMessage = error.localizedDescription
        }
    }

    func createTextSpaceAt(x: Double, y: Double) async {
        guard let client, let projectId = selectedProjectId, let pagePath = pagePathForSelectedProject() else { return }
        do {
            try await client.createTextSpace(pagePath: pagePath, markdown: "# New note\n")
            await openProject(projectId)
            statusMessage = "Text space created"
        } catch {
            errorMessage = error.localizedDescription
        }
    }

    func convertSelectedGroupToPhoto() async {
        guard let client, let projectId = selectedProjectId, let spaceId = selectedSpaceId,
              let space = hydratedProject?.spaces[spaceId], space.kind == "GroupSpace" else { return }
        do {
            let updated = try await client.convertGroupToPhoto(projectId: projectId, groupSpaceId: spaceId)
            workspace = updated
            hydratedProject = updated.projects[projectId]
            statusMessage = "Converted group to photo"
        } catch {
            errorMessage = error.localizedDescription
        }
    }

    func restoreSelectedPhotoToGroup() async {
        guard let client, let projectId = selectedProjectId, let spaceId = selectedSpaceId,
              let space = hydratedProject?.spaces[spaceId], space.kind.contains("Photo") else { return }
        do {
            let updated = try await client.restorePhotoToGroup(projectId: projectId, imageSpaceId: spaceId)
            workspace = updated
            hydratedProject = updated.projects[projectId]
            statusMessage = "Restored photo to group"
        } catch {
            errorMessage = error.localizedDescription
        }
    }

    func uploadMedia(data: Data, filename: String, mimeType: String) async {
        guard let client, let pagePath = pagePathForSelectedProject(), let projectId = selectedProjectId else { return }
        do {
            if mimeType.contains("pdf") {
                try await client.createPDFSpace(pagePath: pagePath, filename: filename, data: data)
            } else {
                try await client.createImageSpace(pagePath: pagePath, filename: filename, mimeType: mimeType, data: data)
            }
            await openProject(projectId)
            statusMessage = "Uploaded \(filename)"
        } catch {
            errorMessage = error.localizedDescription
        }
    }

    func libraryPath(for nodeId: String) -> String? {
        guard let workspace, let node = workspace.library_nodes[nodeId] else { return nil }
        var parts = [node.name]
        var parentId = node.parent_id
        while let pid = parentId, let parent = workspace.library_nodes[pid] {
            parts.insert(parent.name, at: 0)
            parentId = parent.parent_id
        }
        return parts.joined(separator: "/")
    }

    func pagePathForSelectedProject() -> String? {
        guard let workspace, let projectId = selectedProjectId else { return nil }
        guard let node = workspace.library_nodes.values.first(where: { $0.target_project_id == projectId }) else { return nil }
        return libraryPath(for: node.id)
    }

    private func startPresenceLoop(projectId: String) {
        stopPresenceLoop()
        presenceTask = Task { [weak self] in
            while !Task.isCancelled {
                guard let self, let client, let session = client.userId else { break }
                do {
                    let status = try await client.postPagePresence(projectId: projectId, sessionId: session)
                    canWritePage = status.can_write
                    if !status.can_write {
                        statusMessage = "Another session holds the write lock"
                    }
                } catch {
                    break
                }
                try? await Task.sleep(nanoseconds: 12_000_000_000)
            }
        }
    }

    private func stopPresenceLoop() {
        presenceTask?.cancel()
        presenceTask = nil
    }
}
