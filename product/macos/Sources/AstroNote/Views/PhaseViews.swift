import SwiftUI

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
            .frame(maxWidth: .infinity, maxHeight: .infinity, alignment: .bottomLeading)
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
    let space: Space
    let selected: Bool

    var body: some View {
        RoundedRectangle(cornerRadius: 8)
            .stroke(selected ? Color.accentColor : Color.secondary.opacity(0.35), lineWidth: selected ? 2 : 1)
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
    let onScroll: (Double) -> Void

    func makeNSView(context: Context) -> NSView {
        let view = ScrollCaptureView()
        view.onScroll = onScroll
        return view
    }

    func updateNSView(_ nsView: NSView, context: Context) {
        (nsView as? ScrollCaptureView)?.onScroll = onScroll
    }

    final class ScrollCaptureView: NSView {
        var onScroll: ((Double) -> Void)?

        override func scrollWheel(with event: NSEvent) {
            if event.modifierFlags.contains(.command) {
                onScroll?(event.deltaY)
            } else {
                super.scrollWheel(with: event)
            }
        }
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
