import Foundation
import Combine
import SwiftUI

enum AppAppearance: String, CaseIterable, Identifiable {
    case light
    case dark

    var id: String { rawValue }

    var colorScheme: ColorScheme? {
        switch self {
        case .light: return .light
        case .dark: return .dark
        }
    }

    var label: String {
        switch self {
        case .light: return "Light"
        case .dark: return "Dark"
        }
    }
}

@MainActor
final class AppModel: ObservableObject {
    struct ConnectionState {
        var origin: String = ""
        var token: String = ""
        var isConnected: Bool = false
        var errorMessage: String?
    }

    enum CanvasTool: String, CaseIterable, Identifiable {
        case pointer
        case probe
        case createGeneric
        case createText
        case createImage
        case createPDF
        case createGroup
        case createStroke
        case eraseStroke
        case deleteSpace
        case insertVerticalSpace

        var id: String { rawValue }

        var label: String {
            switch self {
            case .pointer: return "Pointer"
            case .probe: return "Probe"
            case .createGeneric: return "Create Generic"
            case .createText: return "Create Text"
            case .createImage: return "Create Image"
            case .createPDF: return "Create PDF"
            case .createGroup: return "Create Group"
            case .createStroke: return "Create Stroke"
            case .eraseStroke: return "Eraser"
            case .deleteSpace: return "Delete Space"
            case .insertVerticalSpace: return "Insert Vertical Space"
            }
        }

        var symbolName: String {
            switch self {
            case .pointer: return "arrow.up.left.and.arrow.down.right"
            case .probe: return "scope"
            case .createGeneric: return "rectangle.dashed"
            case .createText: return "character.textbox"
            case .createImage: return "photo"
            case .createPDF: return "doc.richtext"
            case .createGroup: return "rectangle.3.group"
            case .createStroke: return "pencil.and.scribble"
            case .eraseStroke: return "eraser"
            case .deleteSpace: return "trash"
            case .insertVerticalSpace: return "arrow.up.and.down"
            }
        }

        var enabledInCurrentPhase: Bool {
            switch self {
            case .probe, .createStroke, .eraseStroke: return true
            default: return true
            }
        }
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
    @Published var canvasCamera = CanvasCamera()
    @Published var selectedTool: CanvasTool = .pointer
    @Published var selectedSpaceIds: Set<String> = []
    @Published var serverAheadNotice: String?
    @Published var persistStatus: WorkspacePersistStatus = .idle
    @Published var ragMode: String = "mixed"
    @Published var ragAnswer: String?
    @Published var ragLLMEnabled = false
    @Published var searchFolderScope: String?
    @Published var searchFolderIds: [String] = []
    @Published var probeResults: [ProbeResult] = []
    @Published var probeMode: ProbeMode = .topHit
    @Published var probeCheckedSpaceIds: Set<String> = []
    @Published var maintenanceEnabled = true
    @Published var embedStatusMessage: String?
    @Published var showAssetMigrationPrompt = false
    @Published var showStorageMigrationPrompt = false
    @Published var canWritePage = true
    @Published var isDirty = false
    @Published var undoState: WorkspaceUndoState?
    @Published var localHistoryCanUndo = false
    @Published var localHistoryCanRedo = false
    @Published var eraserMode: StrokeEraserMode = .partial
    @Published var strokeDrawStyle = StrokeDrawStyle()
    @Published var spaceBackgroundColor: String = "#ffffff"

    @AppStorage("astronote.appearance") var appearanceStorage: String = AppAppearance.light.rawValue

    var appearance: AppAppearance {
        get { AppAppearance(rawValue: appearanceStorage) ?? .light }
        set { appearanceStorage = newValue.rawValue }
    }

    func setAppearance(_ value: AppAppearance) {
        appearance = value
    }

    var client: APIClient?
    var baseRevision: Int?
    var projectRevisions: [String: Int] = [:]
    var dirtyGate = WorkspaceDirtyGate()
    var mutationSignals = WorkspaceMutationSignals()
    var saveCoalesceKey: String?
    var staleRecoveryUsed = false
    var staleRecoveryInFlight = false
    var presenceTask: Task<Void, Never>?
    var saveTask: Task<Void, Never>?
    var revisionPollTask: Task<Void, Never>?
    var embedPollTask: Task<Void, Never>?
    var heartbeatTask: Task<Void, Never>?
    var localHistory = LocalHistory()
    var assetTextCache: [String: String] = [:]
    private var cachedStoredProfile: ConnectionProfile?
    private var didAutoBootstrap = false

    func bootstrap(auto: Bool = false) async {
        if auto {
            guard !didAutoBootstrap else { return }
            didAutoBootstrap = true
        }
        connection.errorMessage = nil
        let profile = await Self.loadStoredProfile()
        cachedStoredProfile = profile
        guard let profile else { return }
        connection.origin = APIClient.normalizeOrigin(profile.origin)
        connection.token = profile.apiToken
        await connectUsingStoredProfile()
    }

    func connect(origin: String, token: String) async {
        connection.origin = APIClient.normalizeOrigin(origin)
        connection.token = token.trimmingCharacters(in: .whitespacesAndNewlines)
        connection.errorMessage = nil
        await connectUsingStoredProfile()
    }

    func prepareLocalNetworkAccess(for origin: String) async -> String {
        let normalized = APIClient.normalizeOrigin(origin)
        guard !normalized.isEmpty else {
            return "Enter a server URL first."
        }
        let message = await LocalNetworkAccess.prepare(origin: normalized)
        statusMessage = message
        return message
    }

    private func connectUsingStoredProfile() async {
        guard !connection.origin.isEmpty, !connection.token.isEmpty else { return }
        isLoading = true
        defer { isLoading = false }

        let token = connection.token
        let userId = cachedStoredProfile?.userId
        let normalized = APIClient.normalizeOrigin(connection.origin)
        let candidates = APIClient.connectionOriginCandidates(for: connection.origin)
        var lastError: Error?
        var connectedAPI: APIClient?
        var connectedOrigin = normalized

        for candidate in candidates.isEmpty ? [normalized] : candidates {
            let api = APIClient(origin: candidate, apiToken: token, userId: userId)
            do {
                _ = try await api.createSession(label: "macos")
                try await api.testConnection()
                connectedAPI = api
                connectedOrigin = normalized
                break
            } catch {
                lastError = error
                guard APIClient.isRetryableReachabilityError(error), candidate != candidates.last else { break }
            }
        }

        guard let api = connectedAPI else {
            connection.isConnected = false
            client = nil
            let error = lastError ?? APIClientError.invalidURL
            connection.errorMessage = Self.connectionFailureMessage(
                error: error,
                normalizedOrigin: normalized,
                triedOrigins: candidates
            )
            return
        }

        let profile = ConnectionProfile(origin: connectedOrigin, apiToken: token, userId: api.userId)
        client = api
        connection.isConnected = true
        connection.errorMessage = nil
        do {
            let nav = try await api.fetchWorkspaceNav()
            workspace = nav
            baseRevision = nav.workspace_revision
            startRevisionPollLoop()
            startSessionHeartbeat()
            if api.origin == normalized || api.origin == APIClient.resolveForNetworking(normalized) {
                statusMessage = "Connected to \(normalized)"
            } else {
                statusMessage = "Connected to \(normalized) via \(api.origin)"
            }
            cachedStoredProfile = profile
            ConnectLog.write("Connected via \(api.origin)")
            do {
                try await Self.saveStoredProfile(profile)
            } catch {
                statusMessage = "Connected to \(profile.origin). Could not save credentials: \(error.localizedDescription)"
            }
        } catch {
            connection.isConnected = false
            client = nil
            connection.errorMessage = Self.connectionFailureMessage(
                error: error,
                normalizedOrigin: normalized,
                triedOrigins: candidates
            )
        }
    }

    private static func connectionFailureMessage(
        error: Error,
        normalizedOrigin: String,
        triedOrigins: [String]
    ) -> String {
        var message = error.localizedDescription
        let tried = triedOrigins.filter { !$0.isEmpty }
        if tried.count > 1 {
            message += " Tried: \(tried.joined(separator: ", "))."
        } else if let resolved = tried.first, resolved != normalizedOrigin {
            message += " Resolved server URL: \(resolved)."
        }
        if message.contains("Could not reach the server") || message.contains("timed out") {
            message += " Local Network being on is not enough by itself — confirm Tailscale is connected and try http://100.x.x.x:5173 in the Server field."
        }
        let probe = tried.last ?? APIClient.resolveForNetworking(normalizedOrigin)
        message += " \(AppTransportPolicy.bundleDiagnostic) App \(AppVersion.short) — test: curl -s -o /dev/null -w '%{http_code}' \(probe)/api/workspace/nav"
        ConnectLog.write(message)
        return message
    }

    private static func loadStoredProfile() async -> ConnectionProfile? {
        await Task.detached(priority: .userInitiated) {
            CredentialStore.loadProfile()
        }.value
    }

    private static func saveStoredProfile(_ profile: ConnectionProfile) async throws {
        try await Task.detached(priority: .userInitiated) {
            try CredentialStore.saveProfile(profile)
        }.value
    }

    func disconnect(clearCredentials: Bool = false) {
        stopRevisionPollLoop()
        stopEmbedPoll()
        Task {
            await client?.endSession()
        }
        stopPresenceLoop()
        saveTask?.cancel()
        saveTask = nil
        client = nil
        connection.isConnected = false
        workspace = nil
        hydratedProject = nil
        if clearCredentials {
            cachedStoredProfile = nil
            Task.detached(priority: .userInitiated) {
                CredentialStore.clearProfile()
            }
        }
    }

    func prepareForTermination() async {
        stopRevisionPollLoop()
        stopEmbedPoll()
        saveTask?.cancel()
        saveTask = nil
        if isDirty {
            await saveNow()
        }
        stopPresenceLoop()
        await client?.endSession()
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
        selectedSpaceIds = spaceId.map { [$0] } ?? []
        syncSpaceBackgroundColorFromSelection()
        if spaceId == nil {
            EditableKeyboardTarget.textEditingActive = false
        }
    }

    private func syncSpaceBackgroundColorFromSelection() {
        if let spaceId = selectedSpaceId, let space = hydratedProject?.spaces[spaceId], let color = space.background_color {
            spaceBackgroundColor = color
        } else if let rootId = hydratedProject?.root_space_id,
                  let root = hydratedProject?.spaces[rootId],
                  let color = root.background_color {
            spaceBackgroundColor = color
        }
    }

    func toggleSpaceSelection(_ spaceId: String, extend: Bool) {
        if extend {
            if selectedSpaceIds.contains(spaceId) { selectedSpaceIds.remove(spaceId) }
            else { selectedSpaceIds.insert(spaceId) }
        } else {
            selectedSpaceIds = [spaceId]
        }
        selectedSpaceId = selectedSpaceIds.first
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
        mutationSignals.editedAssetIds = Array(Set(mutationSignals.editedAssetIds + [assetId]))
        markDirty(coalesceKey: UndoCoalesce.textKey(assetId: assetId))
        scheduleSave()
    }

    func markDirty(coalesceKey: String? = nil) {
        dirtyGate.markUserMutation()
        isDirty = true
        if let coalesceKey { saveCoalesceKey = coalesceKey }
        persistStatus = .unsaved
        pushLocalHistoryIfNeeded()
    }

    func scheduleSave() {
        guard WorkspaceDirtyGateLogic.shouldScheduleSave(
            hasUserMutation: dirtyGate.isDirty,
            suppressPersist: false,
            canWrite: canWritePage
        ) else { return }
        saveTask?.cancel()
        saveTask = Task { [weak self] in
            try? await Task.sleep(nanoseconds: 900_000_000)
            await self?.saveNow()
        }
    }

    func saveNow() async {
        guard let client, var workspace, dirtyGate.isDirty || isDirty else { return }
        persistStatus = .saving
        if let projectId = selectedProjectId, let project = hydratedProject {
            workspace.projects[projectId] = project
            for (_, asset) in project.assets {
                guard asset.kind == "markdown", let content = asset.content else { continue }
                try? await client.putAssetText(assetId: asset.id, content: content, filename: asset.filename)
            }
        }
        let session = client.userId
        var baseRevs: [String: Int] = [:]
        if let selectedProjectId, let rev = projectRevisions[selectedProjectId] ?? hydratedProject?.project_revision {
            baseRevs[selectedProjectId] = rev
        }
        do {
            let saved = try await client.saveWorkspace(
                workspace,
                baseRevision: baseRevision,
                pageWriteSession: session,
                options: APIClient.SaveOptions(
                    coalesceKey: saveCoalesceKey,
                    baseRevisions: baseRevs.isEmpty ? nil : baseRevs,
                    clearedProjectIds: nil,
                    mutationSignals: mutationSignals
                )
            )
            self.workspace = saved
            baseRevision = saved.workspace_revision
            dirtyGate.clear()
            isDirty = false
            mutationSignals = WorkspaceMutationSignals()
            saveCoalesceKey = nil
            staleRecoveryUsed = false
            persistStatus = .saved
            statusMessage = "Saved"
        } catch APIClientError.staleSave(let detail, _) {
            await handleStaleSave(detail: detail)
        } catch {
            persistStatus = .unsaved
            errorMessage = error.localizedDescription
        }
    }

    func handleStaleSave(detail: StaleSaveDetail) async {
        let decision = StaleSaveRecovery.decide(recoveryAlreadyUsed: staleRecoveryUsed, recoveryInFlight: staleRecoveryInFlight)
        switch decision {
        case .join:
            return
        case .surfaceError:
            persistStatus = .unsaved
            errorMessage = "Save conflict — reload the page"
            serverAheadNotice = "Server revision \(detail.serverRevision.map(String.init) ?? "?")"
        case .recover:
            staleRecoveryInFlight = true
            staleRecoveryUsed = true
            defer { staleRecoveryInFlight = false }
            do {
                guard let client else { return }
                let (refreshed, project) = try await WorkspaceServerSync.refreshWorkspaceFromServer(
                    client: client,
                    current: workspace,
                    projectId: selectedProjectId
                )
                workspace = refreshed
                baseRevision = refreshed.workspace_revision
                if let project { hydratedProject = project }
                localHistory = presentOnlyHistory(refreshed)
                localHistoryCanUndo = false
                localHistoryCanRedo = false
                await saveNow()
            } catch {
                errorMessage = error.localizedDescription
            }
        }
    }

    func forceUnlockSelectedPage() async {
        guard let client, let projectId = selectedProjectId, let session = client.userId else { return }
        do {
            try await client.forcePageWriteUnlock(projectId: projectId, sessionId: session)
            canWritePage = true
            persistStatus = dirtyGate.isDirty ? .unsaved : .idle
            statusMessage = "Write lock reclaimed"
        } catch {
            errorMessage = error.localizedDescription
        }
    }

    func reloadFromServer() async {
        guard let client else { return }
        isLoading = true
        defer { isLoading = false }
        do {
            let (refreshed, project) = try await WorkspaceServerSync.refreshWorkspaceFromServer(
                client: client,
                current: workspace,
                projectId: selectedProjectId
            )
            workspace = refreshed
            baseRevision = refreshed.workspace_revision
            if let project { hydratedProject = project }
            dirtyGate.clear()
            isDirty = false
            serverAheadNotice = nil
            persistStatus = .synced
            localHistory = presentOnlyHistory(refreshed)
            localHistoryCanUndo = false
            localHistoryCanRedo = false
        } catch {
            errorMessage = error.localizedDescription
        }
    }

    func runSearch(mode: SearchMode) async {
        guard let client else { return }
        let query = searchQuery.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !query.isEmpty else { return }
        do {
            let scopeIds = resolvedSearchFolderIds()
            switch mode {
            case .plain:
                let response = try await client.search(query: query, libraryNodeId: scopeIds.first, libraryNodeIds: scopeIds)
                searchResults = response.search_results ?? []
                ragMasterNodes = []
            case .rag:
                let libraryNodeId = scopeIds.count == 1 ? scopeIds.first : nil
                let response = try await client.searchBackendRAG(
                    query: query,
                    mode: ragMode,
                    libraryNodeId: libraryNodeId ?? searchFolderScope ?? selectedLibraryNodeId,
                    libraryNodeIds: scopeIds.count > 1 ? scopeIds : nil
                )
                searchResults = response.search_results ?? []
                ragMasterNodes = response.master_nodes ?? []
                if ragLLMEnabled {
                    ragAnswer = try await client.callBackendRAGLLM(
                        query: query,
                        libraryNodeId: libraryNodeId ?? searchFolderScope ?? selectedLibraryNodeId,
                        libraryNodeIds: scopeIds.count > 1 ? scopeIds : nil
                    )
                } else {
                    ragAnswer = nil
                }
            }
        } catch {
            errorMessage = error.localizedDescription
        }
    }

    enum SearchMode { case plain, rag }

    func resolvedSearchFolderIds() -> [String] {
        if !searchFolderIds.isEmpty { return searchFolderIds }
        if let searchFolderScope { return [searchFolderScope] }
        if let selectedLibraryNodeId { return [selectedLibraryNodeId] }
        return libraryFolderIds()
    }

    func libraryFolderIds() -> [String] {
        guard let workspace else { return [] }
        return workspace.library_nodes.values.filter { $0.kind == "folder" }.map(\.id).sorted()
    }

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
        await createLibraryItem(kind: kind, name: kind == "folder" ? "New Folder" : "New Page", parentId: selectedLibraryNodeId)
    }

    func createTextSpaceAt(x: Double, y: Double) async {
        createSpace(kind: .createText, atX: x, y: y)
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
