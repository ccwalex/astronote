import SwiftUI

struct InspectorPanel: View {
    @EnvironmentObject private var appModel: AppModel

    var body: some View {
        VStack(alignment: .leading, spacing: 12) {
            Text("Inspector").font(.headline)
            if let project = appModel.hydratedProject {
                List(selection: Binding(get: { appModel.selectedSpaceId }, set: { appModel.selectSpace($0) })) {
                    ForEach(spaceTree(project: project), id: \.self) { spaceId in
                        if let space = project.spaces[spaceId] {
                            Text("\(space.kind) · \(space.id)")
                                .tag(Optional(space.id))
                        }
                    }
                }
            } else {
                Text("No page open").foregroundStyle(.secondary)
            }
            Spacer()
        }
        .padding(12)
    }

    private func spaceTree(project: Project) -> [String] {
        guard let rootId = project.root_space_id else {
            return project.visibleSpaces().map(\.id)
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
