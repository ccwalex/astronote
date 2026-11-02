import SwiftUI

struct ToolbarView: View {
    @EnvironmentObject private var appModel: AppModel
    @State private var showImporter = false
    @State private var showPDFImport = false
    @State private var showZipImport = false
    @State private var pendingPDFData: Data?

    var body: some View {
        VStack(spacing: 6) {
            HStack(spacing: 8) {
                Menu("Tools") {
                    ForEach(AppModel.CanvasTool.allCases) { tool in
                        Button(tool.label) { appModel.selectedTool = tool }
                            .disabled(!tool.enabledInCurrentPhase || !appModel.canWritePage)
                    }
                }
                Text(appModel.selectedTool.label).font(.caption).foregroundStyle(.secondary)

                Button("Undo") { appModel.undo() }.disabled(!appModel.localHistoryCanUndo)
                Button("Redo") { appModel.redo() }.disabled(!appModel.localHistoryCanRedo)
                Button("Commit") { Task { await appModel.commitCheckpoint() } }
                Button("Revert") { Task { await appModel.revertToBaseline() } }

                Button("Upload…") { showImporter = true }
                Button("Paste Image") { Task { await appModel.handlePasteImage() } }

                Button("Save") { Task { await appModel.saveNow() } }
                    .disabled(!appModel.isDirty || !appModel.canWritePage)

                Button("Group→Photo") { Task { await appModel.convertSelectedGroupToPhoto() } }
                Button("Photo→Group") { Task { await appModel.restoreSelectedPhotoToGroup() } }

                if appModel.maintenanceEnabled {
                    Button("Export Zip") { Task { await appModel.exportWorkspaceZip() } }
                    Button("Import Zip") { showZipImport = true }
                }

                Spacer()
                Text(appModel.persistStatus.label)
                    .font(.caption.weight(.semibold))
                    .foregroundStyle(persistColor)
                Text("Zoom")
                Slider(value: $appModel.canvasCamera.scale, in: CanvasCamera.minScale...CanvasCamera.maxScale)
                    .frame(width: 120)
            }
        }
        .padding(.horizontal, 12)
        .padding(.vertical, 8)
        .background(Color(nsColor: .controlBackgroundColor))
        .fileImporter(isPresented: $showImporter, allowedContentTypes: [.image, .pdf], allowsMultipleSelection: false) { result in
            guard case .success(let urls) = result, let url = urls.first else { return }
            Task {
                let data = (try? Data(contentsOf: url)) ?? Data()
                if url.pathExtension.lowercased() == "pdf" {
                    pendingPDFData = data
                    showPDFImport = true
                } else {
                    let mime = "image/\(url.pathExtension.lowercased() == "jpg" ? "jpeg" : url.pathExtension.lowercased())"
                    await appModel.uploadMedia(data: data, filename: url.lastPathComponent, mimeType: mime)
                }
            }
        }
        .fileImporter(isPresented: $showZipImport, allowedContentTypes: [.zip], allowsMultipleSelection: false) { result in
            guard case .success(let urls) = result, let url = urls.first else { return }
            Task { await appModel.importWorkspaceZip(from: url) }
        }
        .sheet(isPresented: $showPDFImport) {
            if let data = pendingPDFData {
                PDFImportSheet(data: data) { pages, mode in
                    Task { await appModel.importPDF(data: data, selectedPages: pages, mode: mode) }
                }
            }
        }
    }

    private var persistColor: Color {
        switch appModel.persistStatus {
        case .unsaved, .locked: return .orange
        case .saving: return .yellow
        case .saved, .synced, .idle: return .secondary
        }
    }
}
