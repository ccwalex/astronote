import SwiftUI

struct InspectorPanel: View {
    @EnvironmentObject private var appModel: AppModel

    var body: some View {
        VStack(alignment: .leading, spacing: 12) {
            HStack {
                Text("Inspector").font(.headline)
                Spacer()
                Button("Hide") {
                    appModel.inspectorVisible = false
                }
                .font(.caption)
                .buttonStyle(.bordered)
                .controlSize(.small)
            }
            zoomSection()
            if appModel.selectedTool == .probe {
                ProbeResultsPanel()
            }
            if let project = appModel.hydratedProject {
                List(selection: Binding(get: { appModel.selectedSpaceId }, set: { appModel.selectSpace($0) })) {
                    ForEach(spaceTree(project: project), id: \.self) { spaceId in
                        if let space = project.spaces[spaceId] {
                            HStack {
                                Text("\(space.kind)")
                                Spacer()
                                Text("#\(Int(space.z))").foregroundStyle(.secondary)
                            }
                            .tag(Optional(space.id))
                        }
                    }
                }
                if appModel.selectedSpaceIds.count > 1 {
                    Button {
                        appModel.groupCheckedSpaces()
                    } label: {
                        Label("Group selection", systemImage: "rectangle.3.group")
                            .labelStyle(.titleAndIcon)
                    }
                    .disabled(!appModel.canWritePage)
                }
                if appModel.probeCheckedSpaceIds.count >= 2 {
                    Button {
                        appModel.groupCheckedSpaces()
                    } label: {
                        Label("Group checked spaces", systemImage: "checkmark.rectangle.stack")
                            .labelStyle(.titleAndIcon)
                    }
                    .disabled(!appModel.canWritePage)
                }
                if appModel.selectedSpaceId != nil {
                    Button {
                        reorderSelectedSpace(delta: 1)
                    } label: {
                        Label("Move up z", systemImage: "arrow.up")
                            .labelStyle(.titleAndIcon)
                    }
                    Button {
                        reorderSelectedSpace(delta: -1)
                    } label: {
                        Label("Move down z", systemImage: "arrow.down")
                            .labelStyle(.titleAndIcon)
                    }
                }
            } else {
                Text("No page open").foregroundStyle(.secondary)
            }
            Spacer()
        }
        .padding(12)
    }

    private func zoomSection() -> some View {
        VStack(alignment: .leading, spacing: 6) {
            Text("Zoom").font(.subheadline.weight(.semibold))
            HStack {
                Button("Zoom In") { appModel.adjustCanvasZoom(multiplier: 1.05) }
                Button("Zoom Out") { appModel.adjustCanvasZoom(multiplier: 1 / 1.05) }
                Button("Reset 100%") { appModel.resetCanvasCamera() }
            }
            .font(.caption)
            Text(String(format: "%.0f%%", appModel.canvasCamera.scale * 100))
                .font(.caption.monospacedDigit())
                .foregroundStyle(.secondary)
            Slider(value: $appModel.canvasCamera.scale, in: CanvasCamera.minScale...CanvasCamera.maxScale)
        }
    }

    private func reorderSelectedSpace(delta: Double) {
        guard var project = appModel.hydratedProject, let spaceId = appModel.selectedSpaceId,
              var space = project.spaces[spaceId] else { return }
        space.z += delta
        project.spaces[spaceId] = space
        appModel.hydratedProject = project
        appModel.markDirty(coalesceKey: "z:\(spaceId)")
        appModel.scheduleSave()
    }

    private func spaceTree(project: Project) -> [String] {
        guard let rootId = project.root_space_id else {
            return project.visibleSpaces().sorted { $0.z < $1.z }.map(\.id)
        }
        var ordered: [String] = []
        func walk(_ id: String) {
            guard let space = project.spaces[id] else { return }
            if !LayerSpaceKinds.hidden.contains(space.kind) {
                ordered.append(id)
            }
            for child in space.child_space_ids {
                walk(child)
            }
        }
        walk(rootId)
        return ordered
    }
}
