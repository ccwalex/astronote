import Foundation
import PDFKit

extension AppModel {
    func presentOnlyHistory(_ workspace: Workspace?) -> LocalHistory {
        WorkingPeriodHistory.presentOnly(workspace)
    }

    func pushLocalHistoryIfNeeded() {
        guard let workspace else { return }
        let flags = WorkingPeriodHistory.push(&localHistory, next: workspace, coalesceKey: saveCoalesceKey)
        localHistoryCanUndo = flags.canUndo
        localHistoryCanRedo = flags.canRedo
    }

    func undo() {
        guard let previous = WorkingPeriodHistory.undo(&localHistory) else { return }
        workspace = previous
        if let projectId = selectedProjectId { hydratedProject = previous.projects[projectId] }
        dirtyGate.markUserMutation()
        isDirty = true
        persistStatus = .unsaved
        localHistoryCanUndo = !localHistory.past.isEmpty
        localHistoryCanRedo = !localHistory.future.isEmpty
        scheduleSave()
    }

    func redo() {
        guard let next = WorkingPeriodHistory.redo(&localHistory) else { return }
        workspace = next
        if let projectId = selectedProjectId { hydratedProject = next.projects[projectId] }
        dirtyGate.markUserMutation()
        isDirty = true
        persistStatus = .unsaved
        localHistoryCanUndo = !localHistory.past.isEmpty
        localHistoryCanRedo = !localHistory.future.isEmpty
        scheduleSave()
    }

    func commitCheckpoint() async {
        guard let client else { return }
        do {
            undoState = try await client.postCommit()
            statusMessage = CommitCheckpoint.title()
            persistStatus = .synced
        } catch {
            errorMessage = error.localizedDescription
        }
    }

    func revertToBaseline() async {
        guard let client else { return }
        do {
            undoState = try await client.postRevertToBaseline()
            await reloadFromServer()
            statusMessage = "Reverted to baseline"
        } catch {
            errorMessage = error.localizedDescription
        }
    }

    func startSessionHeartbeat() {
        heartbeatTask?.cancel()
        heartbeatTask = Task { [weak self] in
            while !Task.isCancelled {
                try? await Task.sleep(nanoseconds: 30_000_000_000)
                guard let self, let client = self.client else { break }
                try? await client.heartbeatSession()
            }
        }
    }

    func startRevisionPollLoop() {
        stopRevisionPollLoop()
        revisionPollTask = Task { [weak self] in
            var failures = 0
            while !Task.isCancelled {
                guard let self, let client = self.client else { break }
                let delayMs = RevisionPoll.computeDelayMs(consecutiveFailures: failures)
                try? await Task.sleep(nanoseconds: UInt64(delayMs) * 1_000_000)
                do {
                    guard let serverRev = try await client.fetchWorkspaceRevision() else { continue }
                    let decision = RevisionPoll.decide(
                        clientRev: self.baseRevision,
                        serverRev: serverRev,
                        dirty: self.dirtyGate.isDirty
                    )
                    switch decision {
                    case .idle:
                        break
                    case .notice(let message):
                        self.serverAheadNotice = message
                    case .refresh:
                        await self.reloadFromServer()
                    }
                    failures = 0
                } catch {
                    failures += 1
                }
            }
        }
    }

    func stopRevisionPollLoop() {
        revisionPollTask?.cancel()
        revisionPollTask = nil
    }

    func stopEmbedPoll() {
        embedPollTask?.cancel()
        embedPollTask = nil
    }

    func renameLibraryNode(id: String, name: String) {
        guard var workspace else { return }
        guard WorkspaceActionsLibrary.renameNode(workspace: &workspace, nodeId: id, name: name) else { return }
        self.workspace = workspace
        mutationSignals.editedLibraryNodeIds.append(id)
        markDirty(coalesceKey: "library-rename:\(id)")
        scheduleSave()
    }

    func deleteLibraryNode(id: String) {
        guard var workspace else { return }
        guard WorkspaceActionsLibrary.deleteNode(workspace: &workspace, nodeId: id) else { return }
        self.workspace = workspace
        mutationSignals.deletedLibraryNodeIds.append(id)
        markDirty(coalesceKey: "library-delete:\(id)")
        scheduleSave()
    }

    func moveLibraryNode(id: String, parentId: String?, index: Int?) {
        guard var workspace else { return }
        guard WorkspaceActionsLibrary.moveNode(workspace: &workspace, nodeId: id, parentId: parentId, index: index) else { return }
        self.workspace = workspace
        mutationSignals.editedLibraryNodeIds.append(id)
        markDirty(coalesceKey: "library-move:\(id)")
        scheduleSave()
    }

    func createFolder(name: String = "New Folder", parentId: String? = nil) {
        Task { await createLibraryItem(kind: "folder", name: name, parentId: parentId ?? selectedLibraryNodeId) }
    }

    func createPage(name: String = "New Page", parentId: String? = nil) {
        Task { await createLibraryItem(kind: "page", name: name, parentId: parentId ?? selectedLibraryNodeId) }
    }

    func createLibraryItem(kind: String, name: String, parentId: String?) async {
        guard let client else { return }
        let path: String
        if let parentId, let workspace, let parentPath = WorkspaceActionsLibrary.libraryPath(workspace: workspace, nodeId: parentId) {
            path = "\(parentPath)/\(name)"
        } else {
            path = name
        }
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

    func updateSelectedSpacePosition(dx: Double, dy: Double) {
        guard var project = hydratedProject, let spaceId = selectedSpaceId,
              let space = project.spaces[spaceId] else { return }
        setSpacePosition(spaceId: spaceId, x: space.x + dx, y: space.y + dy, project: &project)
    }

    func setSelectedSpacePosition(x: Double, y: Double, spaceId: String? = nil) {
        guard var project = hydratedProject else { return }
        let targetId = spaceId ?? selectedSpaceId
        guard let targetId else { return }
        setSpacePosition(spaceId: targetId, x: x, y: y, project: &project)
    }

    private func setSpacePosition(spaceId: String, x: Double, y: Double, project: inout Project) {
        guard var space = project.spaces[spaceId] else { return }
        space.x = x
        space.y = y
        project.spaces[spaceId] = space
        hydratedProject = project
        if var workspace, let projectId = selectedProjectId {
            workspace.projects[projectId] = project
            self.workspace = workspace
        }
        mutationSignals.editedSpaceIds.append(spaceId)
        markDirty(coalesceKey: UndoCoalesce.dragKey(spaceId: spaceId))
        scheduleSave()
    }

    func runProbe(atX x: Double, y: Double) {
        guard let project = hydratedProject else { return }
        probeResults = ProbeCanvas.probe(project: project, x: x, y: y, mode: probeMode)
        if let first = probeResults.first?.spaceId {
            selectSpace(first)
        }
    }

    func toggleProbeCheck(_ spaceId: String) {
        if probeCheckedSpaceIds.contains(spaceId) {
            probeCheckedSpaceIds.remove(spaceId)
        } else {
            probeCheckedSpaceIds.insert(spaceId)
        }
    }

    func createStroke(on spaceId: String, points: [StrokePoint]) {
        guard points.count >= 2, var project = hydratedProject, var space = project.spaces[spaceId] else { return }
        guard !LayerSpaceKinds.hidden.contains(space.kind) else { return }
        let objectId = CanvasStrokeFactory.makeObjectId()
        let object = CanvasStrokeFactory.createStrokeObject(objectId: objectId, spaceId: spaceId, points: points, style: strokeDrawStyle)
        project.objects[objectId] = object
        space.object_ids.append(objectId)
        project.spaces[spaceId] = space
        commitProjectMutation(project, editedObjectIds: [objectId], editedSpaceIds: [spaceId], coalesceKey: "stroke:\(objectId)")
    }

    func eraseStroke(at spaceId: String, localX: Double, localY: Double) {
        guard var project = hydratedProject else { return }
        let changed: Bool
        switch eraserMode {
        case .object:
            changed = CanvasStrokeGeometry.eraseObject(project: &project, spaceId: spaceId, localX: localX, localY: localY)
        case .partial:
            changed = CanvasStrokeGeometry.eraseAtPoint(project: &project, spaceId: spaceId, localX: localX, localY: localY)
        }
        guard changed else { return }
        commitProjectMutation(project, coalesceKey: "erase-stroke:\(spaceId)")
    }

    func handleCanvasToolTap(atX x: Double, y: Double, onSpaceId: String?) {
        switch selectedTool {
        case .createGeneric:
            createSpace(kind: .createGeneric, atX: x, y: y, parentId: onSpaceId)
        case .createText:
            createSpace(kind: .createText, atX: x, y: y, parentId: onSpaceId)
        case .createImage:
            createSpace(kind: .createImage, atX: x, y: y, parentId: onSpaceId)
        case .createPDF:
            createSpace(kind: .createPDF, atX: x, y: y, parentId: onSpaceId)
        case .createGroup:
            createSpace(kind: .createGroup, atX: x, y: y, parentId: onSpaceId)
        default:
            break
        }
    }

    func createSpace(kind: CanvasTool, atX x: Double, y: Double, parentId: String? = nil) {
        guard canWritePage, var project = hydratedProject else { return }
        let createKind: WorkspaceActionsSpaces.CreateSpaceKind
        switch kind {
        case .createGeneric: createKind = .generic
        case .createText: createKind = .text
        case .createImage: createKind = .image
        case .createPDF: createKind = .pdf
        case .createGroup: createKind = .group
        default: return
        }
        let parent = parentId.flatMap { project.spaces[$0]?.kind == "GroupSpace" ? $0 : nil }
        guard let newSpaceId = WorkspaceActionsSpaces.createSpace(
            project: &project,
            kind: createKind,
            x: x,
            y: y,
            parentId: parent
        ) else { return }
        commitProjectMutation(project, editedSpaceIds: [newSpaceId], coalesceKey: "create-space:\(newSpaceId)")
        selectSpace(newSpaceId)
        if createKind == .text {
            EditableKeyboardTarget.textEditingActive = true
        }
        statusMessage = "Created space"
    }

    func applySpaceBackgroundColor(_ color: String) {
        guard canWritePage, var project = hydratedProject else { return }
        let targetId = selectedSpaceId
            ?? project.root_space_id
            ?? WorkspaceActionsSpaces.findObjectContainerSpace(project: project)?.id
        guard let targetId else { return }
        guard WorkspaceActionsSpaces.updateSpaceBackgroundColor(project: &project, spaceId: targetId, color: color) else { return }
        spaceBackgroundColor = color
        commitProjectMutation(project, editedSpaceIds: [targetId], coalesceKey: "space-bg:\(targetId)")
    }

    private func commitProjectMutation(
        _ project: Project,
        editedObjectIds: [String] = [],
        editedSpaceIds: [String] = [],
        coalesceKey: String
    ) {
        hydratedProject = project
        if var workspace, let projectId = selectedProjectId {
            workspace.projects[projectId] = project
            self.workspace = workspace
        }
        mutationSignals.editedObjectIds.append(contentsOf: editedObjectIds)
        mutationSignals.editedSpaceIds.append(contentsOf: editedSpaceIds)
        markDirty(coalesceKey: coalesceKey)
        scheduleSave()
    }

    func deleteSelectedSpace() {
        guard var project = hydratedProject, let spaceId = selectedSpaceId else { return }
        _ = WorkspaceActionsSpaces.deleteSpace(project: &project, spaceId: spaceId)
        hydratedProject = project
        selectedSpaceId = nil
        selectedSpaceIds = []
        if var workspace, let projectId = selectedProjectId {
            workspace.projects[projectId] = project
            self.workspace = workspace
        }
        mutationSignals.deletedSpaceIds.append(spaceId)
        markDirty(coalesceKey: "delete-space:\(spaceId)")
        scheduleSave()
    }

    func insertVerticalGap(at y: Double, gap: Double = 80) {
        guard canWritePage, var project = hydratedProject else { return }
        WorkspaceActionsSpaces.insertVerticalPageGap(project: &project, y: y, gap: gap)
        hydratedProject = project
        if var workspace, let projectId = selectedProjectId {
            workspace.projects[projectId] = project
            self.workspace = workspace
        }
        markDirty(coalesceKey: "insert-gap")
        scheduleSave()
    }

    func groupCheckedSpaces() {
        let ids = probeCheckedSpaceIds.isEmpty ? Set(selectedSpaceIds) : probeCheckedSpaceIds
        guard ids.count >= 2, canWritePage, var project = hydratedProject else { return }
        guard let newGroupId = WorkspaceActionsGroups.createGroupSpace(project: &project, spaceIds: Array(ids)) else {
            errorMessage = "Could not group selected spaces (need same parent)."
            return
        }
        commitProjectMutation(project, editedSpaceIds: [newGroupId] + Array(ids), coalesceKey: "group-spaces")
        selectSpace(newGroupId)
        probeCheckedSpaceIds = []
        statusMessage = "Grouped \(ids.count) spaces"
    }

    func updateSelectedSpaceSize(width: Double, height: Double, spaceId: String? = nil) {
        guard canWritePage, var project = hydratedProject else { return }
        let targetId = spaceId ?? selectedSpaceId
        guard let targetId else { return }
        guard WorkspaceActionsSpaces.updateSpaceSize(project: &project, spaceId: targetId, width: width, height: height) else { return }
        commitProjectMutation(project, editedSpaceIds: [targetId], coalesceKey: "resize:\(targetId)")
    }

    func flipSelectedSpace(horizontal: Bool) {
        guard canWritePage, var project = hydratedProject, let spaceId = selectedSpaceId,
              var space = project.spaces[spaceId] else { return }
        if horizontal {
            space.scale_x = space.scale_x == 0 ? -1 : -space.scale_x
        } else {
            space.scale_y = space.scale_y == 0 ? -1 : -space.scale_y
        }
        project.spaces[spaceId] = space
        commitProjectMutation(project, editedSpaceIds: [spaceId], coalesceKey: "flip:\(spaceId)")
    }

    func resetSelectedSpaceTransform() {
        guard canWritePage, var project = hydratedProject, let spaceId = selectedSpaceId,
              var space = project.spaces[spaceId] else { return }
        space.scale_x = 1
        space.scale_y = 1
        space.transform_matrix = [1, 0, 0, 1, 0, 0]
        project.spaces[spaceId] = space
        commitProjectMutation(project, editedSpaceIds: [spaceId], coalesceKey: "reset-transform:\(spaceId)")
    }

    func adjustCanvasZoom(multiplier: Double) {
        var camera = canvasCamera
        let anchor = CGPoint(x: 0, y: 0)
        camera.zoomAround(point: anchor, deltaScale: multiplier)
        canvasCamera = camera
    }

    func resetCanvasCamera() {
        canvasCamera = CanvasCamera()
    }

    func attachImageToSpace(spaceId: String, data: Data, filename: String, mimeType: String) async {
        guard canWritePage, var project = hydratedProject else { return }
        guard let assetId = WorkspaceActionsMedia.fillImageSpace(
            project: &project,
            spaceId: spaceId,
            filename: filename,
            mimeType: mimeType,
            data: data
        ) else { return }
        commitProjectMutation(project, editedSpaceIds: [spaceId], coalesceKey: "fill-image:\(assetId)")
    }

    func attachImageToSpaceFromPaste(spaceId: String) async {
        guard let data = ClipboardImage.readPNGData() else { return }
        await attachImageToSpace(spaceId: spaceId, data: data, filename: "pasted.png", mimeType: "image/png")
    }

    func attachImageToSpaceFromURL(spaceId: String, urlString: String) async {
        let trimmed = urlString.trimmingCharacters(in: .whitespacesAndNewlines)
        guard let url = URL(string: trimmed), let data = try? Data(contentsOf: url) else {
            errorMessage = "Could not download image."
            return
        }
        let filename = url.lastPathComponent.isEmpty ? "image.png" : url.lastPathComponent
        let ext = url.pathExtension.lowercased()
        let mime = ext == "jpg" || ext == "jpeg" ? "image/jpeg" : "image/png"
        await attachImageToSpace(spaceId: spaceId, data: data, filename: filename, mimeType: mime)
    }

    func attachPDFToSpace(spaceId: String, data: Data, filename: String) async {
        guard canWritePage, var project = hydratedProject else { return }
        guard let assetId = WorkspaceActionsMedia.fillPDFSpace(
            project: &project,
            spaceId: spaceId,
            filename: filename,
            data: data
        ) else { return }
        commitProjectMutation(project, editedSpaceIds: [spaceId], coalesceKey: "fill-pdf:\(assetId)")
    }

    func updateSelectedTextHeight(_ height: Double) {
        guard var project = hydratedProject, let spaceId = selectedSpaceId else { return }
        _ = WorkspaceActionsSpaces.updateSpaceSize(project: &project, spaceId: spaceId, width: project.spaces[spaceId]?.width ?? 320, height: height)
        hydratedProject = project
        mutationSignals.editedSpaceIds.append(spaceId)
        markDirty(coalesceKey: "text-height:\(spaceId)")
        scheduleSave()
    }

    func handlePasteImage() async {
        guard let data = ClipboardImage.readPNGData() else { return }
        await uploadMedia(data: data, filename: "pasted.png", mimeType: "image/png")
    }

    func importPDF(data: Data, selectedPages: [Int], mode: String) async {
        if mode == "single", let doc = PDFDocument(data: data), let page = doc.page(at: selectedPages.first ?? 0) {
            let pageData = doc.dataRepresentation() ?? data
            _ = pageData
            let single = PDFDocument()
            if let copied = page.copy() as? PDFPage {
                single.insert(copied, at: 0)
                if let rendered = single.dataRepresentation() {
                    await uploadMedia(data: rendered, filename: "import-page.pdf", mimeType: "application/pdf")
                    return
                }
            }
        }
        await uploadMedia(data: data, filename: "import.pdf", mimeType: "application/pdf")
    }

    func exportWorkspaceZip() async {
        guard let client else { return }
        do {
            let url = try await WorkspaceZipService.exportWorkspaceZip(client: client)
            statusMessage = "Exported to \(url.lastPathComponent)"
        } catch {
            errorMessage = error.localizedDescription
        }
    }

    func importWorkspaceZip(from url: URL) async {
        guard let client else { return }
        do {
            try await WorkspaceZipService.importWorkspaceZip(client: client, fileURL: url)
            await reloadFromServer()
            statusMessage = "Imported workspace zip"
        } catch {
            errorMessage = error.localizedDescription
        }
    }

    func embedAllAssets() async {
        guard let client else { return }
        do {
            try await EmbeddingJobs.startEmbedAll(client: client)
            startEmbedPoll()
        } catch {
            errorMessage = error.localizedDescription
        }
    }

    func startEmbedPoll() {
        stopEmbedPoll()
        embedPollTask = Task { [weak self] in
            let started = Date()
            while !Task.isCancelled {
                guard let self, let client = self.client else { break }
                if Date().timeIntervalSince(started) > 600 { break }
                if let status = try? await EmbeddingJobs.fetchStatus(client: client) {
                    self.embedStatusMessage = status
                    if status.lowercased().contains("complete") || status.lowercased().contains("idle") { break }
                }
                try? await Task.sleep(nanoseconds: 2_000_000_000)
            }
        }
    }
}
