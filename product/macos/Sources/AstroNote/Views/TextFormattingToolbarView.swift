import SwiftUI

struct TextFormattingToolbarView: View {
    let onAction: (TextFormatAction) -> Void

    var body: some View {
        HStack {
            ForEach([TextFormatAction.h1, .h2, .h3, .bold, .italic, .bullet, .quote, .code], id: \.rawValue) { action in
                Button(action.rawValue.uppercased()) { onAction(action) }
                    .buttonStyle(.bordered)
                    .controlSize(.small)
            }
        }
    }
}

struct TextSpaceArea: View {
    @EnvironmentObject private var appModel: AppModel
    let project: Project
    let space: Space
    @State private var text = ""
    @State private var loaded = false

    var body: some View {
        VStack(spacing: 0) {
            if appModel.selectedSpaceId == space.id {
                TextFormattingToolbarView { action in
                    // Toolbar hooks into WKWebView via future bridge; markdown edits still flow through binding.
                    _ = action
                }
            }
            FormattedTextView(
                markdown: text,
                isEditable: appModel.canWritePage && appModel.selectedSpaceId == space.id,
                onMarkdownChange: { newValue in
                    guard loaded, newValue != text else { return }
                    text = newValue
                    guard let assetId = space.reference_asset_id ?? space.asset_ids.first else { return }
                    appModel.updateTextAsset(assetId: assetId, markdown: newValue)
                }
            )
        }
        .task(id: space.id) {
            loaded = false
            guard let assetId = space.reference_asset_id ?? space.asset_ids.first else { return }
            text = await appModel.assetText(for: assetId)
            loaded = true
        }
    }
}
