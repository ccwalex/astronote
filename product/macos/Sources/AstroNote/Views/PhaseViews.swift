import SwiftUI
import AppKit
import PDFKit
import WebKit

struct PDFImportSheet: View {
    let data: Data
    let onImport: ([Int], String) -> Void
    @Environment(\.dismiss) private var dismiss
    @State private var mode = "all"

    var body: some View {
        VStack(alignment: .leading, spacing: 12) {
            Text("Import PDF").font(.headline)
            Picker("Mode", selection: $mode) {
                Text("All pages").tag("all")
                Text("First page").tag("single")
            }
            .pickerStyle(.segmented)
            HStack {
                Spacer()
                Button("Cancel") { dismiss() }
                Button("Import") {
                    onImport(mode == "all" ? [] : [0], mode)
                    dismiss()
                }
                .keyboardShortcut(.defaultAction)
            }
        }
        .padding()
        .frame(width: 360)
    }
}

struct ImageDrawComposerView: View {
    let imageData: Data
    let onComplete: (Data) -> Void
    @Environment(\.dismiss) private var dismiss

    var body: some View {
        VStack {
            Text("Image composer (crop/draw) — pass-through preview")
            Button("Use image") {
                onComplete(imageData)
                dismiss()
            }
        }
        .padding()
        .frame(width: 480, height: 360)
    }
}

struct AssetTrackingMigrationPrompt: View {
    @EnvironmentObject private var appModel: AppModel
    @Environment(\.dismiss) private var dismiss

    var body: some View {
        migrationPrompt(title: "Asset tracking migration", onMigrate: { dismiss() }, onSkip: { dismiss() })
    }
}

struct WorkspaceStorageMigrationPrompt: View {
    @EnvironmentObject private var appModel: AppModel
    @Environment(\.dismiss) private var dismiss

    var body: some View {
        migrationPrompt(title: "Workspace storage migration", onMigrate: { dismiss() }, onSkip: { dismiss() })
    }
}

private func migrationPrompt(title: String, onMigrate: @escaping () -> Void, onSkip: @escaping () -> Void) -> some View {
    VStack(alignment: .leading, spacing: 12) {
        Text(title).font(.headline)
        Text("The server recommends a one-time migration.")
        HStack {
            Button("Later", role: .cancel, action: onSkip)
            Button("Migrate", action: onMigrate)
        }
    }
    .padding()
    .frame(width: 420)
}

struct ProbeResultsPanel: View {
    @EnvironmentObject private var appModel: AppModel

    var body: some View {
        if appModel.selectedTool == .probe, !appModel.probeResults.isEmpty {
            VStack(alignment: .leading, spacing: 6) {
                Text("Probe results").font(.caption.weight(.semibold))
                if appModel.probeCheckedSpaceIds.count >= 2 {
                    Button {
                        appModel.groupCheckedSpaces()
                    } label: {
                        Label("Group checked spaces", systemImage: "rectangle.3.group")
                            .labelStyle(.titleAndIcon)
                    }
                    .buttonStyle(.borderedProminent)
                    .controlSize(.small)
                }
                ForEach(appModel.probeResults) { result in
                    HStack(alignment: .top, spacing: 8) {
                        if let spaceId = result.spaceId {
                            Toggle("", isOn: Binding(
                                get: { appModel.probeCheckedSpaceIds.contains(spaceId) },
                                set: { _ in appModel.toggleProbeCheck(spaceId) }
                            ))
                            .labelsHidden()
                        }
                        VStack(alignment: .leading, spacing: 2) {
                            Button(result.label) {
                                if let spaceId = result.spaceId {
                                    appModel.selectSpace(spaceId)
                                }
                            }
                            .buttonStyle(.link)
                            Text(result.detail).font(.caption2).foregroundStyle(.secondary)
                            Text(result.zPathLabel).font(.caption2.monospaced())
                        }
                    }
                }
            }
            .padding(10)
            .background(.regularMaterial, in: RoundedRectangle(cornerRadius: 8))
            .padding(12)
            .frame(maxWidth: 380, alignment: .leading)
            .fixedSize(horizontal: false, vertical: true)
            .frame(maxWidth: .infinity, maxHeight: .infinity, alignment: .bottomLeading)
            .allowsHitTesting(true)
        }
    }
}

struct OverlapGroupingSheet: View {
    let onChoice: (String) -> Void
    @Environment(\.dismiss) private var dismiss

    var body: some View {
        VStack(spacing: 12) {
            Text("Overlapping objects detected")
            Button("Group") { onChoice("group"); dismiss() }
            Button("Keep separate") { onChoice("separate"); dismiss() }
        }
        .padding()
    }
}

struct SpaceChromeView: View {
    @EnvironmentObject private var appModel: AppModel
    let space: Space
    let selected: Bool
    var onResize: ((CGFloat, CGFloat) -> Void)?

    private var showTransformChrome: Bool {
        selected
            && appModel.selectedTool == .pointer
            && appModel.selectedSpaceId == space.id
            && appModel.canWritePage
    }

    var body: some View {
        ZStack(alignment: .topLeading) {
            RoundedRectangle(cornerRadius: 8)
                .stroke(selected ? Color.accentColor : Color.secondary.opacity(0.35), lineWidth: selected ? 2 : 1)

            if showTransformChrome {
                HStack(spacing: 4) {
                    Button("Flip H") { appModel.flipSelectedSpace(horizontal: true) }
                        .buttonStyle(.borderless)
                        .font(.caption2)
                    Button("Flip V") { appModel.flipSelectedSpace(horizontal: false) }
                        .buttonStyle(.borderless)
                        .font(.caption2)
                    Button("0°") { appModel.resetSelectedSpaceTransform() }
                        .buttonStyle(.borderless)
                        .font(.caption2)
                }
                .padding(4)
                .background(.ultraThinMaterial, in: RoundedRectangle(cornerRadius: 4))
                .offset(x: 4, y: 4)
            }

            if showTransformChrome, let onResize {
                GeometryReader { geo in
                    Circle()
                        .fill(Color.yellow.opacity(0.9))
                        .frame(width: 12, height: 12)
                        .position(x: geo.size.width - 6, y: geo.size.height - 6)
                        .gesture(
                            DragGesture(minimumDistance: 0)
                                .onChanged { value in
                                    let w = max(40, space.width + value.translation.width / max(appModel.canvasCamera.scale, 0.01))
                                    let h = max(40, space.height + value.translation.height / max(appModel.canvasCamera.scale, 0.01))
                                    onResize(w, h)
                                }
                        )
                }
                .allowsHitTesting(true)
            }
        }
    }
}

struct SnapGuidesOverlay: View {
    var guides: [CGRect] = []

    var body: some View {
        ForEach(Array(guides.enumerated()), id: \.offset) { _, rect in
            Rectangle()
                .stroke(Color.cyan.opacity(0.8), lineWidth: 1)
                .frame(width: rect.width, height: rect.height)
                .position(x: rect.midX, y: rect.midY)
        }
    }
}

struct StrokeCanvasOverlay: View {
    var body: some View {
        Color.clear.allowsHitTesting(false)
    }
}

struct CanvasGestureOverlay: NSViewRepresentable {
    let onScroll: (Double, Double, CGPoint) -> Void
    let onPan: (Double, Double) -> Void

    func makeCoordinator() -> Coordinator { Coordinator() }

    func makeNSView(context: Context) -> ScrollCaptureView {
        let view = ScrollCaptureView()
        view.coordinator = context.coordinator
        context.coordinator.hostView = view
        return view
    }

    func updateNSView(_ nsView: ScrollCaptureView, context: Context) {
        context.coordinator.onScroll = onScroll
        context.coordinator.onPan = onPan
        context.coordinator.hostView = nsView
        if nsView.window != nil {
            context.coordinator.installMonitorIfNeeded()
        }
    }

    static func dismantleNSView(_ nsView: ScrollCaptureView, coordinator: Coordinator) {
        coordinator.removeMonitor()
    }

    final class Coordinator {
        var onScroll: ((Double, Double, CGPoint) -> Void)?
        var onPan: ((Double, Double) -> Void)?
        weak var hostView: ScrollCaptureView?
        private var monitor: Any?

        func installMonitorIfNeeded() {
            guard monitor == nil else { return }
            monitor = NSEvent.addLocalMonitorForEvents(matching: .scrollWheel) { [weak self] event in
                guard let self, let host = self.hostView, let window = host.window else { return event }
                let point = host.convert(event.locationInWindow, from: nil)
                guard host.bounds.contains(point) else { return event }
                if CanvasCamera.scrollTargetsEmbeddedSurface(at: event.locationInWindow, in: window) {
                    return event
                }
                if event.modifierFlags.contains(.command) {
                    self.onScroll?(event.deltaY, event.scrollingDeltaY, point)
                } else {
                    self.onPan?(event.scrollingDeltaX, event.scrollingDeltaY)
                }
                return nil
            }
        }

        func removeMonitor() {
            if let monitor {
                NSEvent.removeMonitor(monitor)
            }
            monitor = nil
        }
    }

    final class ScrollCaptureView: NSView {
        weak var coordinator: Coordinator?

        override var isFlipped: Bool { true }

        override func viewDidMoveToWindow() {
            super.viewDidMoveToWindow()
            if window != nil {
                coordinator?.hostView = self
                coordinator?.installMonitorIfNeeded()
            } else {
                coordinator?.removeMonitor()
            }
        }

        override func hitTest(_ point: NSPoint) -> NSView? { nil }
    }
}

struct LibraryCreateSheet: View {
    @Binding var name: String
    let kind: String
    let onCreate: () -> Void
    @Environment(\.dismiss) private var dismiss

    var body: some View {
        Form {
            TextField("Name", text: $name)
            Button("Create \(kind)") {
                onCreate()
                dismiss()
            }
        }
        .padding()
        .frame(width: 320)
    }
}
