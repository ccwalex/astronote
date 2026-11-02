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
                    }
                    SnapGuidesOverlay()
                    StrokeCanvasOverlay()
                }
                .frame(width: canvasSize.width, height: canvasSize.height)
                .contentShape(Rectangle())
                .gesture(probeCanvasGesture(in: geo.size))
                CanvasGestureOverlay { delta in
                    var camera = appModel.canvasCamera
                    camera.zoomAround(point: CGPoint(x: geo.size.width / 2, y: geo.size.height / 2), deltaScale: CanvasCamera.scaleFromWheelDelta(delta))
                    appModel.canvasCamera = camera
                }
                ProbeResultsPanel()
            }
        }
    }

    private func probeCanvasGesture(in viewport: CGSize) -> some Gesture {
        SpatialTapGesture()
            .onEnded { value in
                guard appModel.selectedTool == .probe else { return }
                let world = canvasWorldPoint(from: value.location, viewport: viewport)
                appModel.runProbe(atX: world.x, y: world.y)
            }
    }

    private func canvasWorldPoint(from location: CGPoint, viewport: CGSize) -> CGPoint {
        let x = (location.x - appModel.canvasCamera.offsetX) / appModel.canvasCamera.scale
        let y = (location.y - appModel.canvasCamera.offsetY) / appModel.canvasCamera.scale
        return CGPoint(x: x, y: y)
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
    @State private var dragAnchor: (x: Double, y: Double)?

    var body: some View {
        let selected = appModel.selectedSpaceIds.contains(space.id)
        VStack(alignment: .leading, spacing: 0) {
            Text(space.kind)
                .font(.caption.weight(.semibold))
                .padding(6)
                .frame(maxWidth: .infinity, alignment: .leading)
                .background(Color(nsColor: .controlBackgroundColor))
            ZStack {
                spaceBody
                SpaceStrokeInteractionLayer(project: project, space: space)
            }
        }
        .frame(width: space.width, height: space.height)
        .background(Color(hex: space.background_color) ?? Color.clear)
        .clipShape(RoundedRectangle(cornerRadius: 8))
        .overlay(SpaceChromeView(space: space, selected: selected))
        .shadow(radius: selected ? 4 : 1)
        .gesture(dragGesture(for: space))
        .simultaneousGesture(spaceTapGesture(for: space))
    }

    private func dragGesture(for space: Space) -> some Gesture {
        DragGesture()
            .onChanged { value in
                guard appModel.selectedTool == .pointer, appModel.selectedSpaceId == space.id else { return }
                if dragAnchor == nil {
                    dragAnchor = (space.x, space.y)
                }
                guard let anchor = dragAnchor else { return }
                let scale = appModel.canvasCamera.scale
                appModel.setSelectedSpacePosition(
                    x: anchor.x + value.translation.width / scale,
                    y: anchor.y + value.translation.height / scale,
                    spaceId: space.id
                )
            }
            .onEnded { _ in
                dragAnchor = nil
            }
    }

    private func spaceTapGesture(for space: Space) -> some Gesture {
        SpatialTapGesture()
            .onEnded { value in
                switch appModel.selectedTool {
                case .probe:
                    let worldX = space.x + value.location.x
                    let worldY = space.y + value.location.y
                    appModel.runProbe(atX: worldX, y: worldY)
                case .deleteSpace:
                    appModel.selectSpace(space.id)
                    appModel.deleteSelectedSpace()
                case .createText:
                    Task { await appModel.createTextSpaceAt(x: space.x + 40, y: space.y + 40) }
                case .insertVerticalSpace:
                    appModel.insertVerticalGap(at: space.y)
                case .pointer, .createGeneric, .createImage, .createPDF, .createGroup, .createStroke, .eraseStroke:
                    appModel.selectSpace(space.id)
                }
            }
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

struct SpaceStrokeInteractionLayer: View {
    @EnvironmentObject private var appModel: AppModel
    let project: Project
    let space: Space
    @State private var currentStroke: [StrokePoint] = []
    @State private var isDrawing = false

    private var isLayerSpace: Bool { LayerSpaceKinds.hidden.contains(space.kind) }

    var body: some View {
        Canvas { context, _ in
            for objectId in space.object_ids {
                guard let object = project.objects[objectId], object.kind == "stroke",
                      let points = CanvasStrokeGeometry.points(from: object) else { continue }
                drawStroke(context: &context, points: points, object: object)
            }
            if currentStroke.count >= 2 {
                drawPreview(context: &context, points: currentStroke)
            }
        }
        .allowsHitTesting(!isLayerSpace && (appModel.selectedTool == .createStroke || appModel.selectedTool == .eraseStroke))
        .gesture(strokeGesture)
    }

    private var strokeGesture: some Gesture {
        DragGesture(minimumDistance: 0)
            .onChanged { value in
                let point = StrokePoint(x: value.location.x, y: value.location.y)
                switch appModel.selectedTool {
                case .createStroke:
                    if !isDrawing {
                        isDrawing = true
                        currentStroke = [point]
                    } else {
                        currentStroke.append(point)
                    }
                case .eraseStroke:
                    appModel.eraseStroke(at: space.id, localX: point.x, localY: point.y)
                default:
                    break
                }
            }
            .onEnded { _ in
                guard appModel.selectedTool == .createStroke, currentStroke.count >= 2 else {
                    currentStroke = []
                    isDrawing = false
                    return
                }
                appModel.createStroke(on: space.id, points: currentStroke)
                currentStroke = []
                isDrawing = false
            }
    }

    private func drawStroke(context: inout GraphicsContext, points: [StrokePoint], object: CanvasObject) {
        var path = Path()
        path.move(to: CGPoint(x: points[0].x, y: points[0].y))
        for point in points.dropFirst() {
            path.addLine(to: CGPoint(x: point.x, y: point.y))
        }
        let color = Color(hex: CanvasStrokeGeometry.strokeColor(from: object)) ?? .black
        let width = CanvasStrokeGeometry.strokeWidth(from: object)
        let opacity = CanvasStrokeGeometry.strokeOpacity(from: object)
        context.stroke(path, with: .color(color.opacity(opacity)), lineWidth: width)
    }

    private func drawPreview(context: inout GraphicsContext, points: [StrokePoint]) {
        var path = Path()
        path.move(to: CGPoint(x: points[0].x, y: points[0].y))
        for point in points.dropFirst() {
            path.addLine(to: CGPoint(x: point.x, y: point.y))
        }
        context.stroke(path, with: .color(.accentColor), lineWidth: 4)
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
