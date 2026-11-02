import SwiftUI

struct InspectorPanel: View {
    @EnvironmentObject private var appModel: AppModel

    var body: some View {
        VStack(alignment: .leading, spacing: 12) {
            Text("Inspector").font(.headline)
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
                    Button("Group selection") {
                        // Overlap grouping hook — local layout handled in future mutation pass.
                    }
                }
                if appModel.selectedSpaceId != nil {
                    Button("Move up z") { reorderSelectedSpace(delta: 1) }
                    Button("Move down z") { reorderSelectedSpace(delta: -1) }
                }
            } else {
                Text("No page open").foregroundStyle(.secondary)
            }
            Spacer()
        }
        .padding(12)
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
