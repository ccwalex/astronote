import SwiftUI
import PDFKit
import AppKit

struct CanvasView: View {
    @EnvironmentObject private var appModel: AppModel
    let project: Project

    @State private var pan: CGSize = .zero

    var body: some View {
        GeometryReader { geo in
            ScrollView([.horizontal, .vertical]) {
                ZStack(alignment: .topLeading) {
                    Color(nsColor: .textBackgroundColor)
                        .frame(width: canvasSize.width, height: canvasSize.height)
                    ForEach(project.visibleSpaces()) { space in
                        SpaceCardView(project: project, space: space)
                            .scaleEffect(appModel.canvasZoom)
                            .offset(x: pan.width + space.x * appModel.canvasZoom, y: pan.height + space.y * appModel.canvasZoom)
                            .onTapGesture {
                                appModel.selectSpace(space.id)
                                if appModel.selectedTool == .text {
                                    Task { await appModel.createTextSpaceAt(x: space.x + 40, y: space.y + 40) }
                                }
                            }
                    }
                }
                .frame(width: canvasSize.width, height: canvasSize.height)
            }
            .gesture(
                DragGesture()
                    .onChanged { value in
                        pan = CGSize(width: value.translation.width, height: value.translation.height)
                    }
            )
        }
    }

    private var canvasSize: CGSize {
        let spaces = project.visibleSpaces()
        let maxX = spaces.map { $0.x + $0.width }.max() ?? 1200
        let maxY = spaces.map { $0.y + $0.height }.max() ?? 900
        return CGSize(width: max(maxX + 200, 1200), height: max(maxY + 200, 900))
    }
}

struct SpaceCardView: View {
    @EnvironmentObject private var appModel: AppModel
    let project: Project
    let space: Space

    var body: some View {
        let selected = appModel.selectedSpaceId == space.id
        VStack(alignment: .leading, spacing: 0) {
            Text(space.kind)
                .font(.caption.weight(.semibold))
                .padding(6)
                .frame(maxWidth: .infinity, alignment: .leading)
                .background(Color(nsColor: .controlBackgroundColor))
            spaceBody
        }
        .frame(width: space.width, height: space.height)
        .clipShape(RoundedRectangle(cornerRadius: 8))
        .overlay(
            RoundedRectangle(cornerRadius: 8)
                .stroke(selected ? Color.accentColor : Color.secondary.opacity(0.4), lineWidth: selected ? 2 : 1)
        )
        .shadow(radius: selected ? 4 : 1)
    }

    @ViewBuilder
    private var spaceBody: some View {
        switch space.kind {
        case "TextSpace":
            TextSpaceView(project: project, space: space)
        case "ImageSpace", "PhotoSpace", "GroupPhotoSpace":
            ImageSpaceView(project: project, space: space)
        case "PDFSpace":
            PDFSpaceView(project: project, space: space)
        case "GroupSpace":
            GroupSpaceView(project: project, space: space)
        default:
            GenericSpaceView(space: space)
        }
    }
}

struct TextSpaceView: View {
    @EnvironmentObject private var appModel: AppModel
    let project: Project
    let space: Space
    @State private var text: String = ""
    @State private var loaded = false

    var body: some View {
        Group {
            if appModel.canWritePage {
                TextEditor(text: $text)
                    .font(.body)
                    .onChange(of: text) { _, newValue in
                        guard let assetId = space.reference_asset_id ?? space.asset_ids.first else { return }
                        appModel.updateTextAsset(assetId: assetId, markdown: newValue)
                    }
            } else {
                ScrollView {
                    Text(text).frame(maxWidth: .infinity, alignment: .leading)
                }
            }
        }
        .padding(8)
        .task(id: space.id) {
            guard let assetId = space.reference_asset_id ?? space.asset_ids.first else { return }
            text = await appModel.assetText(for: assetId)
            loaded = true
        }
    }
}

struct ImageSpaceView: View {
    @EnvironmentObject private var appModel: AppModel
    let project: Project
    let space: Space

    var body: some View {
        RemoteAssetImage(project: project, space: space)
            .frame(maxWidth: .infinity, maxHeight: .infinity)
    }
}

struct RemoteAssetImage: View {
    @EnvironmentObject private var appModel: AppModel
    let project: Project
    let space: Space
    @State private var image: NSImage?

    var body: some View {
        Group {
            if let image {
                Image(nsImage: image)
                    .resizable()
                    .scaledToFit()
            } else {
                ProgressView()
            }
        }
        .task(id: space.id) {
            guard let assetId = space.reference_asset_id ?? space.asset_ids.first,
                  let asset = project.assets[assetId] else { return }
            let path = asset.path.isEmpty ? "/api/assets/\(assetId)" : asset.path
            guard let url = URL(string: path, relativeTo: URL(string: appModel.connection.origin + "/"))?.absoluteURL else { return }
            var request = URLRequest(url: url)
            request.setValue("Bearer \(appModel.connection.token)", forHTTPHeaderField: "Authorization")
            if let data = try? await URLSession.shared.data(for: request).0 {
                image = NSImage(data: data)
            }
        }
    }
}

struct PDFSpaceView: View {
    @EnvironmentObject private var appModel: AppModel
    let project: Project
    let space: Space

    var body: some View {
        RemotePDFView(project: project, space: space)
    }
}

struct RemotePDFView: View {
    @EnvironmentObject private var appModel: AppModel
    let project: Project
    let space: Space
    @State private var document: PDFDocument?

    var body: some View {
        Group {
            if let document {
                PDFKitRepresentable(document: document)
            } else {
                ProgressView()
            }
        }
        .task(id: space.id) {
            guard let assetId = space.reference_asset_id ?? space.asset_ids.first else { return }
            let path = "/api/assets/\(assetId)"
            guard let url = URL(string: appModel.connection.origin + path) else { return }
            var request = URLRequest(url: url)
            request.setValue("Bearer \(appModel.connection.token)", forHTTPHeaderField: "Authorization")
            if let data = try? await URLSession.shared.data(for: request).0 {
                document = PDFDocument(data: data)
            }
        }
    }
}

struct PDFKitRepresentable: NSViewRepresentable {
    let document: PDFDocument

    func makeNSView(context: Context) -> PDFView {
        let view = PDFView()
        view.autoScales = true
        view.document = document
        return view
    }

    func updateNSView(_ pdfView: PDFView, context: Context) {
        pdfView.document = document
    }
}

struct GroupSpaceView: View {
    let project: Project
    let space: Space

    var body: some View {
        ZStack(alignment: .topLeading) {
            Color(nsColor: .controlBackgroundColor).opacity(0.2)
            ForEach(space.child_space_ids, id: \.self) { childId in
                if let child = project.spaces[childId], !LayerSpaceKinds.hidden.contains(child.kind) {
                    SpaceCardView(project: project, space: child)
                        .offset(x: child.x, y: child.y)
                }
            }
        }
    }
}

struct GenericSpaceView: View {
    let space: Space

    var body: some View {
        ZStack {
            Color(nsColor: .controlBackgroundColor).opacity(0.15)
            Text(space.kind).foregroundStyle(.secondary)
        }
    }
}
