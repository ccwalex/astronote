import SwiftUI
import PDFKit
import AppKit
import WebKit

struct CanvasView: View {
    @EnvironmentObject private var appModel: AppModel
    let project: Project
    @State private var gapDragStartY: Double?
    @State private var gapDragEndY: Double?

    var body: some View {
        GeometryReader { geo in
            ZStack(alignment: .topLeading) {
                canvasBackdropColor
                    .frame(width: geo.size.width, height: geo.size.height)
                transformedWorldLayer(in: geo.size)
                verticalGapPreview
                CanvasGestureOverlay(
                    selectedTool: appModel.selectedTool,
                    camera: appModel.canvasCamera,
                    project: project,
                    onScroll: { lineDelta, scrollDelta, point in
                        handleCanvasScroll(
                            lineDelta: lineDelta,
                            scrollDelta: scrollDelta,
                            zoomAnchor: point,
                            viewport: geo.size,
                            commandZoom: true
                        )
                    },
                    onPan: { dx, dy in
                        handleCanvasScroll(deltaX: dx, deltaY: dy, viewport: geo.size, commandZoom: false)
                    },
                    onProbe: { x, y in
                        appModel.runProbe(atX: x, y: y)
                    },
                    onCanvasToolTap: { x, y, groupId in
                        appModel.handleCanvasToolTap(atX: x, y: y, onSpaceId: groupId)
                    }
                )
                .frame(width: geo.size.width, height: geo.size.height)
                ProbeResultsPanel()
                    .frame(width: geo.size.width, height: geo.size.height, alignment: .bottomLeading)
                CanvasTextFormatToolbar(project: project, viewport: geo.size)
                CanvasScrollBars(viewport: geo.size, contentSize: canvasSize)
            }
            .onAppear {
                clampCamera(viewport: geo.size)
            }
            .onChange(of: geo.size) { _, size in
                clampCamera(viewport: size)
            }
        }
        .frame(maxWidth: .infinity, maxHeight: .infinity)
    }

    private func transformedWorldLayer(in viewport: CGSize) -> some View {
        worldLayer
            .scaleEffect(appModel.canvasCamera.scale, anchor: .topLeading)
            .offset(x: appModel.canvasCamera.offsetX, y: appModel.canvasCamera.offsetY)
            .frame(width: canvasSize.width, height: canvasSize.height, alignment: .topLeading)
            .contentShape(Rectangle())
            .simultaneousGesture(insertGapDragGesture(in: viewport))
            .clipped()
    }

    private var worldLayer: some View {
        ZStack(alignment: .topLeading) {
            Color.clear
                .frame(width: canvasSize.width, height: canvasSize.height)
                .contentShape(Rectangle())
                .onTapGesture {
                    guard appModel.selectedTool == .pointer else { return }
                    appModel.selectSpace(nil)
                }
            ForEach(project.canvasRootSpaces()) { space in
                let origin = SpaceLayout.absolutePosition(space: space, spaces: project.spaces)
                SpaceCardView(project: project, space: space)
                    .offset(x: origin.x, y: origin.y)
            }
            SnapGuidesOverlay()
            StrokeCanvasOverlay()
        }
    }

    @ViewBuilder
    private var verticalGapPreview: some View {
        if let startY = gapDragStartY, let endY = gapDragEndY, endY > startY {
            let screenY = startY * appModel.canvasCamera.scale + appModel.canvasCamera.offsetY
            let height = (endY - startY) * appModel.canvasCamera.scale
            Rectangle()
                .stroke(style: StrokeStyle(lineWidth: 1, dash: [6, 4]))
                .foregroundStyle(Color.blue)
                .frame(height: height)
                .offset(x: appModel.canvasCamera.offsetX, y: screenY)
                .allowsHitTesting(false)
        }
    }

    private var canvasBackdropColor: Color {
        appModel.appearance == .dark ? Color(red: 0.12, green: 0.12, blue: 0.12) : Color.white
    }

    private func handleCanvasScroll(
        lineDelta: Double = 0,
        scrollDelta: Double = 0,
        deltaX: Double = 0,
        deltaY: Double = 0,
        zoomAnchor: CGPoint? = nil,
        viewport: CGSize,
        commandZoom: Bool
    ) {
        var camera = appModel.canvasCamera
        let contentSize = canvasSize
        if commandZoom {
            let anchor = zoomAnchor ?? CGPoint(x: viewport.width / 2, y: viewport.height / 2)
            camera.zoomAround(
                point: anchor,
                deltaScale: CanvasCamera.scaleFromWheelDelta(lineDelta: lineDelta, scrollingDelta: scrollDelta)
            )
        } else {
            camera.pan(by: deltaX, deltaY: deltaY)
        }
        camera.clampOffset(viewport: viewport, contentSize: contentSize)
        appModel.canvasCamera = camera
    }

    private func clampCamera(viewport: CGSize) {
        var camera = appModel.canvasCamera
        camera.clampOffset(viewport: viewport, contentSize: canvasSize)
        appModel.canvasCamera = camera
    }

    private func insertGapDragGesture(in viewport: CGSize) -> some Gesture {
        DragGesture(minimumDistance: 6)
            .onChanged { value in
                guard appModel.selectedTool == .insertVerticalSpace, appModel.canWritePage else { return }
                let start = canvasWorldPoint(from: value.startLocation, viewport: viewport)
                let current = canvasWorldPoint(from: value.location, viewport: viewport)
                if gapDragStartY == nil { gapDragStartY = start.y }
                gapDragEndY = max(current.y, (gapDragStartY ?? start.y) + 8)
            }
            .onEnded { value in
                defer {
                    gapDragStartY = nil
                    gapDragEndY = nil
                }
                guard appModel.selectedTool == .insertVerticalSpace, appModel.canWritePage else { return }
                let start = canvasWorldPoint(from: value.startLocation, viewport: viewport)
                let end = canvasWorldPoint(from: value.location, viewport: viewport)
                let gap = max(40, end.y - start.y)
                guard gap >= 40 else { return }
                appModel.insertVerticalGap(at: start.y, gap: gap)
            }
    }

    private func canvasWorldPoint(from location: CGPoint, viewport: CGSize) -> CGPoint {
        SpaceLayout.pointerToWorld(point: location, camera: appModel.canvasCamera)
    }

    private var canvasSize: CGSize {
        CanvasWorldBounds.contentSize(visibleSpaces: project.visibleSpaces(), spaces: project.spaces)
    }
}

struct SpaceCardView: View {
    @EnvironmentObject private var appModel: AppModel
    let project: Project
    let space: Space
    @State private var dragAnchor: (x: Double, y: Double)?
    @State private var pendingTextEditAt: CGPoint?

    private var selected: Bool { appModel.selectedSpaceIds.contains(space.id) }
    private var isLayerSpace: Bool { LayerSpaceKinds.hidden.contains(space.kind) }
    private var isPhotoSpace: Bool {
        ["ImageSpace", "PhotoSpace", "GroupPhotoSpace"].contains(space.kind)
    }
    private var cardPadding: EdgeInsets {
        if isLayerSpace || isPhotoSpace { return EdgeInsets() }
        return CanvasDisplayMetrics.contentPadding
    }

    var body: some View {
        ZStack {
            spaceBody
            SpaceStrokeInteractionLayer(project: project, space: space)
        }
        .padding(cardPadding)
        .frame(width: space.width, height: space.height)
        .background(Color(hex: space.background_color) ?? Color.clear)
        .overlay { spaceSelectionBorder }
        .scaleEffect(x: space.scale_x, y: space.scale_y, anchor: .topLeading)
        .rotationEffect(.radians(SpaceTransform.rotationRadians(space.transform_matrix)))
        .overlay(
            SpaceChromeView(space: space, selected: selected) { width, height in
                appModel.updateSelectedSpaceSize(width: Double(width), height: Double(height), spaceId: space.id)
            }
        )
        .contentShape(Rectangle())
        .gesture(dragGesture(for: space))
        .simultaneousGesture(spaceTapGesture(for: space))
        .shadow(radius: selected ? 4 : 1)
    }

    @ViewBuilder
    private var spaceSelectionBorder: some View {
        if !isLayerSpace {
            if space.kind == "TextSpace" || selected {
                Rectangle()
                    .strokeBorder(
                        selected ? CanvasDisplayMetrics.selectionBlue : Color.clear,
                        lineWidth: CanvasDisplayMetrics.borderWidth
                    )
            }
        }
    }

    private func dragGesture(for space: Space) -> some Gesture {
        DragGesture()
            .onChanged { value in
                guard appModel.selectedTool == .pointer, appModel.canWritePage else { return }
                if space.kind == "TextSpace", EditableKeyboardTarget.textEditingActive,
                   appModel.selectedSpaceId == space.id {
                    return
                }
                guard appModel.selectedSpaceId == space.id else { return }
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
                let localX = value.location.x
                let localY = value.location.y
                let abs = SpaceLayout.absolutePosition(space: space, spaces: project.spaces)
                let worldX = abs.x + localX
                let worldY = abs.y + localY

                switch appModel.selectedTool {
                case .probe:
                    appModel.runProbe(atX: worldX, y: worldY)
                case .deleteSpace:
                    guard appModel.canWritePage else { return }
                    appModel.selectSpace(space.id)
                    appModel.deleteSelectedSpace()
                case .insertVerticalSpace:
                    break
                case .createGeneric, .createText, .createImage, .createPDF, .createGroup:
                    appModel.handleCanvasToolTap(atX: worldX, y: worldY, onSpaceId: space.id)
                case .pointer:
                    appModel.selectSpace(space.id)
                    if space.kind == "TextSpace", appModel.canWritePage {
                        pendingTextEditAt = CGPoint(x: localX, y: localY)
                    }
                case .createStroke, .eraseStroke:
                    appModel.selectSpace(space.id)
                }
            }
    }

    @ViewBuilder
    private var spaceBody: some View {
        switch space.kind {
        case "TextSpace":
            TextSpaceArea(project: project, space: space, editAtPoint: $pendingTextEditAt)
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
        let style = appModel.strokeDrawStyle
        let color = Color(hex: style.color) ?? .black
        let opacity = style.mode == "highlighter" ? min(style.opacity, 0.45) : style.opacity
        context.stroke(path, with: .color(color.opacity(opacity)), lineWidth: style.width)
    }
}


struct RemoteAssetImage: View {
    @EnvironmentObject private var appModel: AppModel
    let project: Project
    let space: Space
    @State private var snapshot: SVGSnapshot?
    @State private var loadFailed = false
    @State private var showImporter = false
    @State private var imageURL = ""

    private var hasAsset: Bool {
        space.reference_asset_id != nil || !space.asset_ids.isEmpty
    }

    private var assetKey: String {
        "\(space.id)-\(space.reference_asset_id ?? space.asset_ids.first ?? "")"
    }

    var body: some View {
        Group {
            if let snapshot, snapshot.hasVisibleContent {
                snapshotView(snapshot)
            } else if !hasAsset {
                EmptyImageSpaceView(
                    spaceId: space.id,
                    imageURL: $imageURL,
                    showImporter: $showImporter
                )
            } else if loadFailed {
                Text("Could not load image")
                    .font(.caption)
                    .foregroundStyle(.secondary)
            } else {
                ProgressView()
            }
        }
        .frame(maxWidth: .infinity, maxHeight: .infinity)
        .fileImporter(isPresented: $showImporter, allowedContentTypes: [.image], allowsMultipleSelection: false) { result in
            guard case .success(let urls) = result, let url = urls.first else { return }
            Task {
                let data = (try? Data(contentsOf: url)) ?? Data()
                let mime = "image/\(url.pathExtension.lowercased() == "jpg" ? "jpeg" : url.pathExtension.lowercased())"
                await appModel.attachImageToSpace(spaceId: space.id, data: data, filename: url.lastPathComponent, mimeType: mime)
            }
        }
        .task(id: assetKey) {
            guard hasAsset else { return }
            guard let assetId = space.reference_asset_id ?? space.asset_ids.first else { return }
            loadFailed = false
            snapshot = nil
            guard let data = await appModel.assetData(for: assetId) else {
                loadFailed = true
                return
            }
            let decoded = SVGSnapshotImage.decode(data)
            if let decoded, decoded.hasVisibleContent {
                snapshot = decoded
            } else {
                loadFailed = true
            }
        }
    }

    @ViewBuilder
    private func snapshotView(_ snapshot: SVGSnapshot) -> some View {
        GeometryReader { geo in
            let canvasW = max(1, snapshot.width)
            let canvasH = max(1, snapshot.height)
            ZStack(alignment: .topLeading) {
                ForEach(Array(snapshot.images.enumerated()), id: \.offset) { _, layer in
                    Image(nsImage: layer.image)
                        .resizable()
                        .interpolation(.high)
                        .frame(
                            width: layer.fullFrame ? geo.size.width : geo.size.width * layer.width / canvasW,
                            height: layer.fullFrame ? geo.size.height : geo.size.height * layer.height / canvasH
                        )
                        .offset(
                            x: layer.fullFrame ? 0 : geo.size.width * layer.x / canvasW,
                            y: layer.fullFrame ? 0 : geo.size.height * layer.y / canvasH
                        )
                }
                if let overlay = snapshot.overlayImage {
                    Image(nsImage: overlay)
                        .resizable()
                        .interpolation(.high)
                        .frame(width: geo.size.width, height: geo.size.height)
                } else if !snapshot.vectorMarkup.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty {
                    SVGVectorOverlay(
                        markup: snapshot.vectorMarkup,
                        viewBox: snapshot.viewBox
                    )
                    .frame(width: geo.size.width, height: geo.size.height)
                    .allowsHitTesting(false)
                }
            }
        }
    }
}

private struct SVGVectorOverlay: NSViewRepresentable {
    let markup: String
    let viewBox: String

    func makeNSView(context: Context) -> MouseThroughWebView {
        let config = WKWebViewConfiguration()
        config.websiteDataStore = .nonPersistent()
        config.suppressesIncrementalRendering = true
        let view = MouseThroughWebView(frame: .zero, configuration: config)
        view.setValue(false, forKey: "drawsBackground")
        view.underPageBackgroundColor = .clear
        load(in: view)
        return view
    }

    func updateNSView(_ view: MouseThroughWebView, context: Context) {
        load(in: view)
    }

    private func load(in view: MouseThroughWebView) {
        let html = """
        <!DOCTYPE html><html><head><meta charset="utf-8">
        <style>
        html,body{margin:0;padding:0;background:transparent;overflow:hidden;width:100%;height:100%;}
        svg{width:100%;height:100%;display:block;}
        </style></head><body>
        <svg xmlns="http://www.w3.org/2000/svg" viewBox="\(viewBox)" width="100%" height="100%" preserveAspectRatio="none">\(markup)</svg>
        </body></html>
        """
        guard view.loadedHTML != html else { return }
        view.loadedHTML = html
        view.loadHTMLString(html, baseURL: nil)
    }
}

private final class MouseThroughWebView: WKWebView {
    var loadedHTML: String = ""
    override func hitTest(_ point: NSPoint) -> NSView? { nil }
    override var acceptsFirstResponder: Bool { false }
}

private struct EmptyImageSpaceView: View {
    @EnvironmentObject private var appModel: AppModel
    let spaceId: String
    @Binding var imageURL: String
    @Binding var showImporter: Bool

    var body: some View {
        VStack(alignment: .leading, spacing: 8) {
            Text("Choose an image for this space").font(.caption).foregroundStyle(.secondary)
            HStack {
                Button("Choose Image") { showImporter = true }
                Button("Paste Image") { Task { await appModel.attachImageToSpaceFromPaste(spaceId: spaceId) } }
            }
            HStack {
                TextField("Image URL", text: $imageURL)
                    .textFieldStyle(.roundedBorder)
                Button("Insert") { Task { await appModel.attachImageToSpaceFromURL(spaceId: spaceId, urlString: imageURL) } }
            }
        }
        .padding(8)
    }
}

enum DataURI {
    static func decode(_ value: String) -> Data? {
        guard let comma = value.firstIndex(of: ",") else { return nil }
        let b64 = String(value[value.index(after: comma)...])
        return Data(base64Encoded: b64)
    }
}

struct RemotePDFView: View {
    @EnvironmentObject private var appModel: AppModel
    let project: Project
    let space: Space
    @State private var document: PDFDocument?
    @State private var pageIndex = 0
    @State private var showImporter = false

    private var hasAsset: Bool {
        space.reference_asset_id != nil || !space.asset_ids.isEmpty
    }

    var body: some View {
        VStack(spacing: 0) {
            if let document {
                HStack {
                    Button("Prev") { pageIndex = max(0, pageIndex - 1) }
                    Text("Page \(pageIndex + 1) / \(max(document.pageCount, 1))")
                        .font(.caption)
                    Button("Next") { pageIndex = min(document.pageCount - 1, pageIndex + 1) }
                }
                PDFKitRepresentable(document: document, pageIndex: pageIndex)
            } else if !hasAsset {
                VStack(spacing: 8) {
                    Text("No PDF attached").font(.caption).foregroundStyle(.secondary)
                    Button("Choose PDF") { showImporter = true }
                }
                .frame(maxWidth: .infinity, maxHeight: .infinity)
            } else {
                ProgressView()
            }
        }
        .fileImporter(isPresented: $showImporter, allowedContentTypes: [.pdf], allowsMultipleSelection: false) { result in
            guard case .success(let urls) = result, let url = urls.first else { return }
            Task {
                let data = (try? Data(contentsOf: url)) ?? Data()
                await appModel.attachPDFToSpace(spaceId: space.id, data: data, filename: url.lastPathComponent)
            }
        }
        .task(id: space.id) {
            guard hasAsset else { return }
            guard let assetId = space.reference_asset_id ?? space.asset_ids.first else { return }
            if let data = await appModel.assetData(for: assetId) {
                document = PDFDocument(data: data)
            }
        }
    }
}

struct PDFKitRepresentable: NSViewRepresentable {
    let document: PDFDocument
    var pageIndex: Int = 0

    func makeNSView(context: Context) -> CanvasPDFView {
        let view = CanvasPDFView()
        view.autoScales = false
        view.displayMode = .singlePage
        view.displayDirection = .vertical
        view.document = document
        return view
    }

    func updateNSView(_ pdfView: CanvasPDFView, context: Context) {
        pdfView.document = document
        if let page = document.page(at: pageIndex) {
            pdfView.go(to: page)
        }
    }

    final class CanvasPDFView: PDFView {
        override func scrollWheel(with event: NSEvent) {
            guard !event.modifierFlags.contains(.command) else {
                super.scrollWheel(with: event)
                return
            }
            nextResponder?.scrollWheel(with: event)
        }
    }
}

struct GroupSpaceView: View {
    @EnvironmentObject private var appModel: AppModel
    let project: Project
    let space: Space

    private var fillColor: Color {
        appModel.appearance == .dark ? Color(red: 0.18, green: 0.18, blue: 0.18) : Color(red: 0.94, green: 0.94, blue: 0.94)
    }

    private var nestedSpaces: [Space] {
        let listed = Set(space.child_space_ids)
        var ordered: [Space] = space.child_space_ids.compactMap { project.spaces[$0] }
        let linked = project.visibleSpaces().filter { child in
            child.parent_space_id == space.id && !listed.contains(child.id)
        }
        ordered.append(contentsOf: linked)
        return ordered.filter { !LayerSpaceKinds.hidden.contains($0.kind) }
    }

    var body: some View {
        ZStack(alignment: .topLeading) {
            fillColor.opacity(0.2)
            ForEach(nestedSpaces) { child in
                SpaceCardView(project: project, space: child)
                    .offset(x: child.x, y: child.y)
            }
        }
    }
}

struct GenericSpaceView: View {
    @EnvironmentObject private var appModel: AppModel
    let space: Space

    private var fillColor: Color {
        appModel.appearance == .dark ? Color(red: 0.18, green: 0.18, blue: 0.18) : Color(red: 0.94, green: 0.94, blue: 0.94)
    }

    var body: some View {
        fillColor.opacity(0.15)
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

private struct CanvasScrollBars: View {
    @EnvironmentObject private var appModel: AppModel
    let viewport: CGSize
    let contentSize: CGSize
    @State private var verticalDragOrigin: Double?
    @State private var horizontalDragOrigin: Double?

    private let thickness: CGFloat = 13
    private let minThumb: CGFloat = 28

    private var scaled: CGSize {
        CGSize(
            width: contentSize.width * appModel.canvasCamera.scale,
            height: contentSize.height * appModel.canvasCamera.scale
        )
    }

    private var showHorizontal: Bool { scaled.width > viewport.width + 0.5 }
    private var showVertical: Bool { scaled.height > viewport.height + 0.5 }

    var body: some View {
        ZStack(alignment: .topLeading) {
            if showVertical {
                verticalBar
                    .frame(width: thickness, height: max(0, viewport.height - (showHorizontal ? thickness : 0)))
                    .offset(x: max(0, viewport.width - thickness), y: 0)
            }
            if showHorizontal {
                horizontalBar
                    .frame(width: max(0, viewport.width - (showVertical ? thickness : 0)), height: thickness)
                    .offset(x: 0, y: max(0, viewport.height - thickness))
            }
        }
        .frame(width: viewport.width, height: viewport.height, alignment: .topLeading)
        .allowsHitTesting(showHorizontal || showVertical)
    }

    private var verticalBar: some View {
        let metrics = barMetrics(
            trackLength: max(0, viewport.height - (showHorizontal ? thickness : 0)),
            viewportLength: viewport.height,
            contentLength: scaled.height,
            offset: appModel.canvasCamera.offsetY
        )
        return barTrack {
            thumb(width: thickness - 4, height: metrics.thumbLength)
                .offset(x: 2, y: metrics.thumbOrigin)
                .gesture(drag(.vertical, metrics: metrics))
        }
    }

    private var horizontalBar: some View {
        let metrics = barMetrics(
            trackLength: max(0, viewport.width - (showVertical ? thickness : 0)),
            viewportLength: viewport.width,
            contentLength: scaled.width,
            offset: appModel.canvasCamera.offsetX
        )
        return barTrack {
            thumb(width: metrics.thumbLength, height: thickness - 4)
                .offset(x: metrics.thumbOrigin, y: 2)
                .gesture(drag(.horizontal, metrics: metrics))
        }
    }

    private func barTrack<Content: View>(@ViewBuilder _ content: () -> Content) -> some View {
        ZStack(alignment: .topLeading) {
            RoundedRectangle(cornerRadius: 6).fill(Color.primary.opacity(0.08))
            content()
        }
        .padding(1)
    }

    private func thumb(width: CGFloat, height: CGFloat) -> some View {
        RoundedRectangle(cornerRadius: 6)
            .fill(Color.primary.opacity(0.38))
            .frame(width: width, height: height)
    }

    private struct BarMetrics {
        var travel: CGFloat
        var thumbLength: CGFloat
        var thumbTravel: CGFloat
        var thumbOrigin: CGFloat
        var scrollPos: Double
    }

    private enum Axis { case horizontal, vertical }

    private func barMetrics(
        trackLength: CGFloat,
        viewportLength: CGFloat,
        contentLength: CGFloat,
        offset: Double
    ) -> BarMetrics {
        let travel = max(contentLength - viewportLength, 1)
        let thumbLength = min(trackLength, max(minThumb, trackLength * viewportLength / max(contentLength, 1)))
        let thumbTravel = max(trackLength - thumbLength, 1)
        let scrollPos = min(Double(travel), max(0, -offset))
        return BarMetrics(
            travel: travel,
            thumbLength: thumbLength,
            thumbTravel: thumbTravel,
            thumbOrigin: CGFloat(scrollPos / Double(travel)) * thumbTravel,
            scrollPos: scrollPos
        )
    }

    private func drag(_ axis: Axis, metrics: BarMetrics) -> some Gesture {
        DragGesture(minimumDistance: 0)
            .onChanged { value in
                if axis == .vertical, verticalDragOrigin == nil {
                    verticalDragOrigin = metrics.scrollPos
                }
                if axis == .horizontal, horizontalDragOrigin == nil {
                    horizontalDragOrigin = metrics.scrollPos
                }
                let origin = (axis == .vertical ? verticalDragOrigin : horizontalDragOrigin) ?? metrics.scrollPos
                let delta = axis == .vertical ? value.translation.height : value.translation.width
                let nextPos = origin + Double(delta / metrics.thumbTravel) * Double(metrics.travel)
                var camera = appModel.canvasCamera
                if axis == .vertical {
                    camera.offsetY = -min(Double(metrics.travel), max(0, nextPos))
                } else {
                    camera.offsetX = -min(Double(metrics.travel), max(0, nextPos))
                }
                camera.clampOffset(viewport: viewport, contentSize: contentSize)
                appModel.canvasCamera = camera
            }
            .onEnded { _ in
                verticalDragOrigin = nil
                horizontalDragOrigin = nil
            }
    }
}

private struct CanvasTextFormatToolbar: View {
    @EnvironmentObject private var appModel: AppModel
    let project: Project
    let viewport: CGSize
    var body: some View {
        if let overlay = appModel.textFormatOverlay,
           appModel.selectedSpaceId == overlay.spaceId,
           appModel.canWritePage,
           let space = project.spaces[overlay.spaceId] {
            let placement = toolbarPlacement(overlay: overlay, space: space)
            TextFormattingToolbarView(activeFormats: overlay.activeFormats) { action in
                appModel.activeTextFormatEditor?.apply(action)
            }
            .frame(maxWidth: placement.maxWidth, alignment: .leading)
            .fixedSize(horizontal: false, vertical: true)
            .offset(x: placement.x, y: placement.y)
            .zIndex(50)
        }
    }

    private struct Placement {
        var x: CGFloat
        var y: CGFloat
        var maxWidth: CGFloat
    }

    private func toolbarPlacement(overlay: TextFormatOverlayState, space: Space) -> Placement {
        let scale = appModel.canvasCamera.scale
        let caret = overlay.caretRectInBody
        let worldX = space.x + Double(caret.minX)
        let screenX = worldX * scale + appModel.canvasCamera.offsetX
        let estimatedBarHeight: CGFloat = 52
        let maxBarWidth = min(viewport.width - 16, 520)
        var screenY = (space.y + Double(caret.maxY) + 6) * scale + appModel.canvasCamera.offsetY
        if screenY + estimatedBarHeight > viewport.height - 8 {
            screenY = (space.y + Double(caret.minY) - 6) * scale + appModel.canvasCamera.offsetY - estimatedBarHeight
        }
        let clampedX = min(max(8, screenX), max(8, viewport.width - maxBarWidth - 8))
        let clampedY = max(8, screenY)
        return Placement(x: clampedX, y: clampedY, maxWidth: maxBarWidth)
    }
}

