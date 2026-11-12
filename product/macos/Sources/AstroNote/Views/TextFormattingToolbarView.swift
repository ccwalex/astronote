import SwiftUI

struct TextFormattingToolbarView: View {
    let activeFormats: ActiveTextFormats
    let onAction: (TextFormatAction) -> Void

    var body: some View {
        FlowLayout(horizontalSpacing: 6, verticalSpacing: 6) {
            Picker("Style", selection: Binding(
                get: { activeFormats.styleValue },
                set: { value in
                    switch value {
                    case "h1": onAction(.h1)
                    case "h2": onAction(.h2)
                    case "h3": onAction(.h3)
                    case "h4": onAction(.h4)
                    case "h5": onAction(.h5)
                    case "h6": onAction(.h6)
                    default: onAction(.normal)
                    }
                }
            )) {
                Text("Normal").tag("normal")
                Text("H1").tag("h1")
                Text("H2").tag("h2")
                Text("H3").tag("h3")
                Text("H4").tag("h4")
                Text("H5").tag("h5")
                Text("H6").tag("h6")
            }
            .labelsHidden()
            .frame(width: 120)

            formatButton("Bold", systemImage: "bold", active: activeFormats.bold) { onAction(.bold) }
            formatButton("Italic", systemImage: "italic", active: activeFormats.italic) { onAction(.italic) }
            formatButton("Strike", systemImage: "strikethrough", active: activeFormats.strike) { onAction(.strike) }
            formatButton("List", systemImage: "list.bullet", active: activeFormats.bullet) { onAction(.bullet) }
            formatButton("Numbered", systemImage: "list.number", active: activeFormats.number) { onAction(.number) }
            formatButton("Quote", systemImage: "text.quote", active: activeFormats.blockquote) { onAction(.quote) }
            formatButton("Code", systemImage: "chevron.left.forwardslash.chevron.right", active: activeFormats.codeBlock) { onAction(.code) }
        }
        .font(.caption.weight(.semibold))
        .padding(.horizontal, 8)
        .padding(.vertical, 6)
        .background(.regularMaterial, in: RoundedRectangle(cornerRadius: 8))
        .overlay(RoundedRectangle(cornerRadius: 8).stroke(Color.secondary.opacity(0.25)))
        .shadow(radius: 4, y: 2)
    }

    private func formatButton(_ title: String, systemImage: String, active: Bool, action: @escaping () -> Void) -> some View {
        Button(action: action) {
            Label(title, systemImage: systemImage)
                .labelStyle(.titleAndIcon)
                .font(.caption2)
                .padding(.horizontal, 4)
                .padding(.vertical, 2)
                .background(active ? Color.accentColor.opacity(0.25) : Color.clear, in: RoundedRectangle(cornerRadius: 4))
        }
        .buttonStyle(.plain)
    }
}

struct TextSpaceArea: View {
    @EnvironmentObject private var appModel: AppModel
    let project: Project
    let space: Space
    @Binding var editAtPoint: CGPoint?
    @State private var text = ""
    @State private var loaded = false
    @StateObject private var textEditor = FormattedTextEditorController()


    private var isEditing: Bool {
        appModel.canWritePage && appModel.selectedSpaceId == space.id
    }

    var body: some View {
        GeometryReader { geo in
            FormattedTextView(
                markdown: text,
                isEditable: isEditing,
                documentDark: appModel.appearance == .dark,
                spaceId: space.id,
                onMarkdownChange: { newValue in
                    guard loaded, newValue != text else { return }
                    text = newValue
                    guard let assetId = space.reference_asset_id ?? space.asset_ids.first else { return }
                    appModel.updateTextAsset(assetId: assetId, markdown: newValue)
                    syncTextSpaceHeight()
                },
                onContentLayout: {
                    guard loaded else { return }
                    syncTextSpaceHeight()
                },
                controller: textEditor,
                appModel: appModel
            )
            .frame(width: geo.size.width, height: geo.size.height)
        }
        .task(id: space.id) {
            loaded = false
            EditableKeyboardTarget.textEditingActive = false
            guard let assetId = space.reference_asset_id ?? space.asset_ids.first else {
                text = ""
                loaded = true
                return
            }
            text = await appModel.assetText(for: assetId)
            loaded = true
        }
        .onChange(of: loaded) { _, isLoaded in
            guard isLoaded else { return }
            syncTextSpaceHeight()
        }
        .onChange(of: space.height) { _, _ in
            guard loaded else { return }
            syncTextSpaceHeight()
        }
        .onChange(of: isEditing) { _, editing in
            if editing {
                beginEditing(at: nil)
                appModel.setActiveTextFormatEditor(textEditor, spaceId: space.id)
            } else {
                appModel.setActiveTextFormatEditor(nil, spaceId: space.id)
                if appModel.selectedSpaceId != space.id {
                    EditableKeyboardTarget.textEditingActive = false
                }
            }
        }
        .onDisappear {
            appModel.setActiveTextFormatEditor(nil, spaceId: space.id)
        }
        .onChange(of: editAtPoint) { _, point in
            guard let point else { return }
            let paddedX = point.x - CanvasDisplayMetrics.contentPadding.leading
            let paddedY = point.y - CanvasDisplayMetrics.contentPadding.top
            beginEditing(at: CGPoint(x: max(0, paddedX), y: max(0, paddedY)))
            editAtPoint = nil
        }
    }

    func beginEditing(at point: CGPoint?) {
        appModel.selectSpace(space.id)
        EditableKeyboardTarget.textEditingActive = true
        textEditor.focusEditor(at: point)
    }

    private func syncTextSpaceHeight() {
        textEditor.measureContentHeight { height in
            let required = CanvasDisplayMetrics.requiredTextSpaceHeight(contentHeight: height)
            if abs(required - space.height) < 0.5 { return }
            appModel.updateTextSpaceHeight(required, spaceId: space.id)
        }
    }
}
