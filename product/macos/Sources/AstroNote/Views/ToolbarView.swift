import SwiftUI
import UniformTypeIdentifiers

struct ToolbarView: View {
    @EnvironmentObject private var appModel: AppModel
    @State private var showImporter = false

    var body: some View {
        HStack(spacing: 10) {
            Picker("Tool", selection: $appModel.selectedTool) {
                Text("Pointer").tag(AppModel.CanvasTool.pointer)
                Text("Text").tag(AppModel.CanvasTool.text)
                Text("Image").tag(AppModel.CanvasTool.image)
                Text("PDF").tag(AppModel.CanvasTool.pdf)
                Text("Box").tag(AppModel.CanvasTool.generic)
            }
            .pickerStyle(.segmented)
            .frame(maxWidth: 420)

            Button("Upload…") { showImporter = true }

            Button("Save") { Task { await appModel.saveNow() } }
                .disabled(!appModel.isDirty || !appModel.canWritePage)

            Button("Group→Photo") { Task { await appModel.convertSelectedGroupToPhoto() } }
            Button("Photo→Group") { Task { await appModel.restoreSelectedPhotoToGroup() } }

            Spacer()
            Text("Zoom")
            Slider(value: $appModel.canvasZoom, in: 0.25...2.5)
                .frame(width: 140)
        }
        .padding(.horizontal, 12)
        .padding(.vertical, 8)
        .background(Color(nsColor: .controlBackgroundColor))
        .fileImporter(isPresented: $showImporter, allowedContentTypes: [.image, .pdf], allowsMultipleSelection: false) { result in
            guard case .success(let urls) = result, let url = urls.first else { return }
            Task {
                let data = (try? Data(contentsOf: url)) ?? Data()
                let mime = url.pathExtension.lowercased() == "pdf" ? "application/pdf" : "image/png"
                await appModel.uploadMedia(data: data, filename: url.lastPathComponent, mimeType: mime)
            }
        }
    }
}
