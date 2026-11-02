import SwiftUI
import PDFKit
import AppKit

struct CanvasView: View {
    @EnvironmentObject private var appModel: AppModel
    let project: Project

    var body: some View {
        GeometryReader { geo in
            ZStack(alignment: .topLeading) {
                Color(nsColor: .textBackgroundColor)
                ZStack(alignment: .topLeading) {
                    ForEach(project.visibleSpaces()) { space in
                        SpaceCardView(project: project, space: space)
                            .scaleEffect(appModel.canvasCamera.scale)
                            .offset(
                                x: appModel.canvasCamera.offsetX + space.x * appModel.canvasCamera.scale,
                                y: appModel.canvasCamera.offsetY + space.y * appModel.canvasCamera.scale
                            )
                            .gesture(dragGesture(for: space))
                            .onTapGesture { handleTap(on: space) }
                    }
                    SnapGuidesOverlay()
                    StrokeCanvasOverlay()
                }
                .frame(width: canvasSize.width, height: canvasSize.height)
                CanvasGestureOverlay { delta in
                    var camera = appModel.canvasCamera
                    camera.zoomAround(point: CGPoint(x: geo.size.width / 2, y: geo.size.height / 2), deltaScale: CanvasCamera.scaleFromWheelDelta(delta))
                    appModel.canvasCamera = camera
                }
                ProbeResultsPanel()
            }
        }
    }

    private func dragGesture(for space: Space) -> some Gesture {
        DragGesture()
            .onChanged { value in
                guard appModel.selectedTool == .pointer, appModel.selectedSpaceId == space.id else { return }
                appModel.updateSelectedSpacePosition(
                    dx: value.translation.width / appModel.canvasCamera.scale,
                    dy: value.translation.height / appModel.canvasCamera.scale
                )
            }
    }

    private func handleTap(on space: Space) {
        switch appModel.selectedTool {
        case .pointer:
            appModel.selectSpace(space.id)
        case .deleteSpace:
            appModel.selectSpace(space.id)
            appModel.deleteSelectedSpace()
        case .createText:
            Task { await appModel.createTextSpaceAt(x: space.x + 40, y: space.y + 40) }
        case .insertVerticalSpace:
            appModel.insertVerticalGap(at: space.y)
        default:
            appModel.selectSpace(space.id)
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
        let selected = appModel.selectedSpaceIds.contains(space.id)
        VStack(alignment: .leading, spacing: 0) {
            Text(space.kind)
                .font(.caption.weight(.semibold))
                .padding(6)
                .frame(maxWidth: .infinity, alignment: .leading)
                .background(Color(nsColor: .controlBackgroundColor))
            spaceBody
        }
        .frame(width: space.width, height: space.height)
        .background(Color(hex: space.background_color) ?? Color.clear)
        .clipShape(RoundedRectangle(cornerRadius: 8))
        .overlay(SpaceChromeView(space: space, selected: selected))
        .shadow(radius: selected ? 4 : 1)
    }

    @ViewBuilder
    private var spaceBody: some View {
        switch space.kind {
        case "TextSpace":
            TextSpaceArea(project: project, space: space)
        case "ImageSpace", "PhotoSpace", "GroupPhotoSpace":
            RemoteAssetImage(project: project, space: space)
        case "PDFSpace":
            RemotePDFView(project: project, space: space)
        case "GroupSpace":
            GroupSpaceView(project: project, space: space)
        default:
            GenericSpaceView(space: space)
        }
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
        .frame(maxWidth: .infinity, maxHeight: .infinity)
        .task(id: space.id) {
            guard let client = appModel.client,
                  let assetId = space.reference_asset_id ?? space.asset_ids.first else { return }
            if let data = try? await client.fetchAssetData(assetId: assetId) {
                image = NSImage(data: data)
            }
        }
    }
}

struct RemotePDFView: View {
    @EnvironmentObject private var appModel: AppModel
    let project: Project
    let space: Space
    @State private var document: PDFDocument?
    @State private var pageIndex = 0

    var body: some View {
        VStack(spacing: 0) {
            HStack {
                Button("<") { pageIndex = max(0, pageIndex - 1) }
                Text("Page \(pageIndex + 1) / \(max(document?.pageCount ?? 1, 1))")
                    .font(.caption)
                Button(">") { pageIndex = min((document?.pageCount ?? 1) - 1, pageIndex + 1) }
            }
            if let document {
                PDFKitRepresentable(document: document, pageIndex: pageIndex)
            } else {
                ProgressView()
            }
        }
        .task(id: space.id) {
            guard let client = appModel.client,
                  let assetId = space.reference_asset_id ?? space.asset_ids.first else { return }
            if let data = try? await client.fetchAssetData(assetId: assetId) {
                document = PDFDocument(data: data)
            }
        }
    }

    func goToPage(_ index: Int) {
        pageIndex = index
    }
}

struct PDFKitRepresentable: NSViewRepresentable {
    let document: PDFDocument
    var pageIndex: Int = 0

    func makeNSView(context: Context) -> PDFView {
        let view = PDFView()
        view.autoScales = true
        view.document = document
        return view
    }

    func updateNSView(_ pdfView: PDFView, context: Context) {
        pdfView.document = document
        if let page = document.page(at: pageIndex) {
            pdfView.go(to: page)
        }
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

private extension Color {
    init?(hex: String?) {
        guard let hex, hex.hasPrefix("#"), hex.count >= 7 else { return nil }
        let start = hex.index(hex.startIndex, offsetBy: 1)
        let r = Int(hex[start..<hex.index(start, offsetBy: 2)], radix: 16) ?? 0
        let g = Int(hex[hex.index(start, offsetBy: 2)..<hex.index(start, offsetBy: 4)], radix: 16) ?? 0
        let b = Int(hex[hex.index(start, offsetBy: 4)..<hex.index(start, offsetBy: 6)], radix: 16) ?? 0
        self.init(red: Double(r) / 255, green: Double(g) / 255, blue: Double(b) / 255)
    }
}
