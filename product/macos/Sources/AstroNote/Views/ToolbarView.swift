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
            ScrollView(.horizontal, showsIndicators: false) {
                HStack(spacing: 8) {
                    toolButton("Pointer", tool: .pointer)
                    toolButton("Probe", tool: .probe)
                    probeModePicker()
                    readOnlyBadge()

                    toolButton("Create Generic", tool: .createGeneric)
                    toolButton("Create Text", tool: .createText)
                    toolButton("Create Image", tool: .createImage)
                    toolButton("Create PDF", tool: .createPDF)
                    toolButton("Create Group", tool: .createGroup)
                    toolButton("Create Stroke", tool: .createStroke)
                    toolButton("Eraser", tool: .eraseStroke)
                    eraserModePicker()

                    toolButton("Delete Space", tool: .deleteSpace)
                    toolButton("Insert Vertical Space", tool: .insertVerticalSpace)

                    conversionButtons()
                    historyButtons()
                    backgroundControls()
                    appearanceToggle()

                    Button("Import Zip") { showZipImport = true }
                    Button("Export Zip") { Task { await appModel.exportWorkspaceZip() } }

                    Button("Upload…") { showImporter = true }
                    Button("Paste Image") { Task { await appModel.handlePasteImage() } }

                    Spacer(minLength: 12)
                    Text(appModel.persistStatus.label)
                        .font(.caption.weight(.semibold))
                        .foregroundStyle(persistColor)
                    Text("Zoom")
                    Slider(value: $appModel.canvasCamera.scale, in: CanvasCamera.minScale...CanvasCamera.maxScale)
                        .frame(width: 120)
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

    private func toolButton(_ title: String, tool: AppModel.CanvasTool) -> some View {
        Button(title) { appModel.selectedTool = tool }
            .buttonStyle(ToolbarToolButtonStyle(selected: appModel.selectedTool == tool))
            .disabled(!appModel.canWritePage && toolRequiresWrite(tool))
    }

    private func toolRequiresWrite(_ tool: AppModel.CanvasTool) -> Bool {
        switch tool {
        case .pointer, .probe, .deleteSpace, .insertVerticalSpace, .eraseStroke:
            return false
        default:
            return true
        }
    }

    @ViewBuilder
    private func probeModePicker() -> some View {
        if appModel.selectedTool == .probe {
            Picker("Probe", selection: $appModel.probeMode) {
                ForEach(ProbeMode.allCases) { mode in
                    Text(mode.label).tag(mode)
                }
            }
            .labelsHidden()
            .frame(maxWidth: 160)
        }
    }

    @ViewBuilder
    private func eraserModePicker() -> some View {
        if appModel.selectedTool == .eraseStroke {
            Text("Mode").font(.caption)
            Button("Object") { appModel.eraserMode = .object }
                .buttonStyle(ToolbarToolButtonStyle(selected: appModel.eraserMode == .object))
            Button("Partial") { appModel.eraserMode = .partial }
                .buttonStyle(ToolbarToolButtonStyle(selected: appModel.eraserMode == .partial))
        }
    }

    @ViewBuilder
    private func readOnlyBadge() -> some View {
        if !appModel.canWritePage {
            Text("Read-only")
                .font(.caption)
                .foregroundStyle(.orange)
        }
    }

    private func historyButtons() -> some View {
        Group {
            Button("Undo") { appModel.undo() }
                .disabled(!appModel.canWritePage || !appModel.localHistoryCanUndo)
            Button("Redo") { appModel.redo() }
                .disabled(!appModel.canWritePage || !appModel.localHistoryCanRedo)
            Button("Commit") { Task { await appModel.commitCheckpoint() } }
                .disabled(!appModel.canWritePage)
            Button("Revert") { Task { await appModel.revertToBaseline() } }
                .disabled(!appModel.canWritePage)
            Button("Save") { Task { await appModel.saveNow() } }
                .disabled(!appModel.canWritePage || !appModel.isDirty)
        }
    }

    @ViewBuilder
    private func conversionButtons() -> some View {
        if selectedSpaceKind == "GroupSpace" {
            Button("Group → Group Photo") { Task { await appModel.convertSelectedGroupToPhoto() } }
        }
        if selectedSpaceKind == "GroupPhotoSpace" || selectedSpaceKind == "ImageSpace" {
            Button("Group Photo → Group") { Task { await appModel.restoreSelectedPhotoToGroup() } }
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
            Button("Transparent") {
                appModel.spaceBackgroundColor = "transparent"
                pendingTransparentApply = true
            }
            .disabled(!appModel.canWritePage)
            Button("Set Background") { appModel.applySpaceBackgroundColor(appModel.spaceBackgroundColor) }
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
