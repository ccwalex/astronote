import AppKit
import SwiftUI

/// Applies NSWindow title-bar and toolbar settings for unified compact chrome.
struct WindowConfigurator: NSViewRepresentable {
    func makeNSView(context: Context) -> NSView {
        let view = NSView()
        DispatchQueue.main.async { apply(to: view.window) }
        return view
    }

    func updateNSView(_ nsView: NSView, context: Context) {
        apply(to: nsView.window)
    }

    private func apply(to window: NSWindow?) {
        guard let window else { return }
        window.titleVisibility = .hidden
        window.toolbarStyle = .unifiedCompact
        window.toolbar?.displayMode = .iconOnly
    }
}
