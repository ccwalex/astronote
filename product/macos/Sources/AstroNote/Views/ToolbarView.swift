import SwiftUI
import AppKit

struct ToolbarView: View {
    @EnvironmentObject private var appModel: AppModel
    @State private var showImporter = false
    @State private var showPDFImport = false
    @State private var showZipImport = false
    @State private var pendingPDFData: Data?
    @State private var pendingTransparentApply = false

    var body: some View {
        VStack(spacing: 6) {
            strokeStyleBar()
            ScrollView(.horizontal, showsIndicators: false) {
                HStack(spacing: 8) {
                    ForEach(AppModel.CanvasTool.allCases.filter(\.enabledInCurrentPhase)) { tool in
                        toolButton(tool: tool)
                        if tool == .probe {
                            probeModePicker()
                        }
                    }
                    readOnlyBadge()
                    conversionButtons()
                    historyButtons()
                    backgroundControls()
                    appearanceToggle()

                    labeledButton("Import Zip", systemImage: "square.and.arrow.down") { showZipImport = true }
                    labeledButton("Export Zip", systemImage: "square.and.arrow.up") {
                        Task { await appModel.exportWorkspaceZip() }
                    }

                    labeledButton("Upload…", systemImage: "arrow.up.doc") { showImporter = true }
                    labeledButton("Paste Image", systemImage: "doc.on.clipboard") {
                        Task { await appModel.handlePasteImage() }
                    }

                    Spacer(minLength: 12)
                    Text(appModel.persistStatus.label)
                        .font(.caption.weight(.semibold))
                        .foregroundStyle(persistColor)
                    zoomControls()
                }
                .padding(.vertical, 2)
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
        .onChange(of: appModel.spaceBackgroundColor) { _, newValue in
            if pendingTransparentApply, newValue == "transparent" {
                pendingTransparentApply = false
                appModel.applySpaceBackgroundColor("transparent")
            }
        }
    }

    @ViewBuilder
    private func strokeStyleBar() -> some View {
        if appModel.selectedTool == .createStroke {
            HStack(spacing: 10) {
                Text("Stroke").font(.caption.weight(.semibold))
                Picker("Mode", selection: strokeModeBinding) {
                    Text("Line").tag("line")
                    Text("Highlighter").tag("highlighter")
                }
                .pickerStyle(.segmented)
                .frame(width: 200)
                ColorPicker("Color", selection: strokeColorBinding)
                    .labelsHidden()
                Text("Width")
                Slider(value: strokeWidthBinding, in: 1...24)
                    .frame(width: 100)
                Text("Opacity")
                Slider(value: strokeOpacityBinding, in: 0.1...1)
                    .frame(width: 100)
            }
            .font(.caption)
        }
    }

    private var strokeModeBinding: Binding<String> {
        Binding(
            get: { appModel.strokeDrawStyle.mode },
            set: { newValue in
                var style = appModel.strokeDrawStyle
                style.mode = newValue
                if newValue == "highlighter", style.opacity > 0.5 {
                    style.opacity = 0.35
                    style.width = max(style.width, 12)
                }
                appModel.strokeDrawStyle = style
            }
        )
    }

    private var strokeWidthBinding: Binding<Double> {
        Binding(
            get: { appModel.strokeDrawStyle.width },
            set: { newValue in
                var style = appModel.strokeDrawStyle
                style.width = newValue
                appModel.strokeDrawStyle = style
            }
        )
    }

    private var strokeOpacityBinding: Binding<Double> {
        Binding(
            get: { appModel.strokeDrawStyle.opacity },
            set: { newValue in
                var style = appModel.strokeDrawStyle
                style.opacity = newValue
                appModel.strokeDrawStyle = style
            }
        )
    }

    private var strokeColorBinding: Binding<Color> {
        Binding(
            get: { Color(hex: appModel.strokeDrawStyle.color) ?? .black },
            set: { color in
                if let hex = color.hexString {
                    appModel.strokeDrawStyle.color = hex
                }
            }
        )
    }

    @ViewBuilder
    private func toolButton(tool: AppModel.CanvasTool) -> some View {
        toolLabeledButton(tool: tool)
        if tool == .eraseStroke {
            eraserModePicker()
        }
    }

    private func toolLabeledButton(tool: AppModel.CanvasTool) -> some View {
        Button {
            appModel.selectedTool = tool
        } label: {
            Label(tool.label, systemImage: tool.symbolName)
                .labelStyle(.titleAndIcon)
        }
        .buttonStyle(ToolbarToolButtonStyle(selected: appModel.selectedTool == tool))
        .disabled(!appModel.canWritePage && toolRequiresWrite(tool))
    }

    private func labeledButton(_ title: String, systemImage: String, action: @escaping () -> Void) -> some View {
        Button(action: action) {
            Label(title, systemImage: systemImage)
                .labelStyle(.titleAndIcon)
        }
        .buttonStyle(ToolbarToolButtonStyle(selected: false))
    }

    private func toolRequiresWrite(_ tool: AppModel.CanvasTool) -> Bool {
        switch tool {
        case .pointer, .probe:
            return false
        default:
            return true
        }
    }

    @ViewBuilder
    private func probeModePicker() -> some View {
        if appModel.selectedTool == .probe {
            Picker("Probe mode", selection: $appModel.probeMode) {
                ForEach(ProbeMode.allCases) { mode in
                    Text(mode.label).tag(mode)
                }
            }
            .pickerStyle(.menu)
            .frame(maxWidth: 140)
        }
    }

    @ViewBuilder
    private func eraserModePicker() -> some View {
        if appModel.selectedTool == .eraseStroke {
            Text("Mode").font(.caption)
            Button {
                appModel.eraserMode = .object
            } label: {
                Label("Object", systemImage: "eraser.line.dashed")
                    .labelStyle(.titleAndIcon)
            }
            .buttonStyle(ToolbarToolButtonStyle(selected: appModel.eraserMode == .object))
            Button {
                appModel.eraserMode = .partial
            } label: {
                Label("Partial", systemImage: "scribble.variable")
                    .labelStyle(.titleAndIcon)
            }
            .buttonStyle(ToolbarToolButtonStyle(selected: appModel.eraserMode == .partial))
        }
    }

    @ViewBuilder
    private func readOnlyBadge() -> some View {
        if !appModel.canWritePage {
            Label("Read-only", systemImage: "lock")
                .labelStyle(.titleAndIcon)
                .font(.caption)
                .foregroundStyle(.orange)
        }
    }

    private func historyButtons() -> some View {
        Group {
            labeledButton("Undo", systemImage: "arrow.uturn.backward") { appModel.undo() }
                .disabled(!appModel.canWritePage || !appModel.localHistoryCanUndo)
            labeledButton("Redo", systemImage: "arrow.uturn.forward") { appModel.redo() }
                .disabled(!appModel.canWritePage || !appModel.localHistoryCanRedo)
            labeledButton("Commit", systemImage: "checkmark.circle") { Task { await appModel.commitCheckpoint() } }
                .disabled(!appModel.canWritePage)
            labeledButton("Revert", systemImage: "arrow.counterclockwise") { Task { await appModel.revertToBaseline() } }
                .disabled(!appModel.canWritePage)
            labeledButton("Save", systemImage: "square.and.arrow.down") { Task { await appModel.saveNow() } }
                .disabled(!appModel.canWritePage || !appModel.isDirty)
        }
    }

    @ViewBuilder
    private func conversionButtons() -> some View {
        if selectedSpaceKind == "GroupSpace" {
            labeledButton("Group → Group Photo", systemImage: "photo.stack") {
                Task { await appModel.convertSelectedGroupToPhoto() }
            }
        }
        if selectedSpaceKind == "GroupPhotoSpace" || selectedSpaceKind == "ImageSpace" {
            labeledButton("Group Photo → Group", systemImage: "rectangle.3.group") {
                Task { await appModel.restoreSelectedPhotoToGroup() }
            }
        }
    }

    private var selectedSpaceKind: String? {
        guard let spaceId = appModel.selectedSpaceId else { return nil }
        return appModel.hydratedProject?.spaces[spaceId]?.kind
    }

    private func backgroundControls() -> some View {
        Group {
            ColorPicker("", selection: backgroundColorBinding)
                .labelsHidden()
            labeledButton("Transparent", systemImage: "square.dashed") {
                appModel.spaceBackgroundColor = "transparent"
                pendingTransparentApply = true
            }
            .disabled(!appModel.canWritePage)
            labeledButton("Set Background", systemImage: "paintbrush") {
                appModel.applySpaceBackgroundColor(appModel.spaceBackgroundColor)
            }
            .disabled(!appModel.canWritePage)
        }
    }

    private var backgroundColorBinding: Binding<Color> {
        Binding(
            get: {
                if appModel.spaceBackgroundColor == "transparent" { return .clear }
                return Color(hex: appModel.spaceBackgroundColor) ?? .white
            },
            set: { newColor in
                if let hex = newColor.hexString {
                    appModel.spaceBackgroundColor = hex
                }
            }
        )
    }

    private func appearanceToggle() -> some View {
        Picker("Appearance", selection: Binding(
            get: { appModel.appearance },
            set: { appModel.setAppearance($0) }
        )) {
            ForEach(AppAppearance.allCases) { mode in
                Text(mode.label).tag(mode)
            }
        }
        .pickerStyle(.segmented)
        .frame(width: 140)
    }

    private func zoomControls() -> some View {
        HStack(spacing: 6) {
            Text("Zoom").font(.caption)
            Button("In") { appModel.adjustCanvasZoom(multiplier: 1.05) }
            Button("Out") { appModel.adjustCanvasZoom(multiplier: 1 / 1.05) }
            Button("100%") { appModel.resetCanvasCamera() }
            Slider(value: $appModel.canvasCamera.scale, in: CanvasCamera.minScale...CanvasCamera.maxScale)
                .frame(width: 100)
        }
        .font(.caption)
    }

    private var persistColor: Color {
        switch appModel.persistStatus {
        case .unsaved, .locked: return .orange
        case .saving: return .yellow
        case .saved, .synced, .idle: return .secondary
        }
    }
}

private struct ToolbarToolButtonStyle: ButtonStyle {
    let selected: Bool

    func makeBody(configuration: Configuration) -> some View {
        configuration.label
            .font(.caption)
            .padding(.horizontal, 8)
            .padding(.vertical, 4)
            .background(selected ? Color(red: 0, green: 0.333, blue: 1) : Color.white)
            .foregroundStyle(selected ? Color.white : Color.primary)
            .clipShape(RoundedRectangle(cornerRadius: 4))
            .overlay(RoundedRectangle(cornerRadius: 4).stroke(Color.secondary.opacity(0.35)))
            .opacity(configuration.isPressed ? 0.85 : 1)
    }
}

private extension Color {
    init?(hex: String) {
        guard hex.hasPrefix("#"), hex.count >= 7 else { return nil }
        let start = hex.index(hex.startIndex, offsetBy: 1)
        let r = Int(hex[start..<hex.index(start, offsetBy: 2)], radix: 16) ?? 0
        let g = Int(hex[hex.index(start, offsetBy: 2)..<hex.index(start, offsetBy: 4)], radix: 16) ?? 0
        let b = Int(hex[hex.index(start, offsetBy: 4)..<hex.index(start, offsetBy: 6)], radix: 16) ?? 0
        self.init(red: Double(r) / 255, green: Double(g) / 255, blue: Double(b) / 255)
    }

    var hexString: String? {
        guard let components = NSColor(self).usingColorSpace(.sRGB) else { return nil }
        let r = Int((components.redComponent * 255).rounded())
        let g = Int((components.greenComponent * 255).rounded())
        let b = Int((components.blueComponent * 255).rounded())
        return String(format: "#%02X%02X%02X", r, g, b)
    }
}
