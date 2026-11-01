import SwiftUI

struct SearchBarView: View {
    @EnvironmentObject private var appModel: AppModel

    var body: some View {
        VStack(alignment: .leading, spacing: 8) {
            HStack {
                TextField("Search workspace…", text: $appModel.searchQuery)
                    .textFieldStyle(.roundedBorder)
                    .onSubmit { Task { await appModel.runSearch(mode: .plain) } }
                Button("Search") { Task { await appModel.runSearch(mode: .plain) } }
                Button("RAG") { Task { await appModel.runSearch(mode: .rag) } }
            }
            if !appModel.searchResults.isEmpty || !appModel.ragMasterNodes.isEmpty {
                ScrollView(.horizontal, showsIndicators: false) {
                    HStack {
                        ForEach(appModel.ragMasterNodes) { node in
                            Button(node.label ?? node.id) {
                                Task {
                                    if let projectId = node.project_id {
                                        await appModel.openProject(projectId)
                                        appModel.selectedSpaceId = node.space_id
                                    }
                                }
                            }
                            .buttonStyle(.bordered)
                        }
                        ForEach(appModel.searchResults) { hit in
                            Button(hit.label ?? hit.snippet ?? "Result") {
                                Task { await appModel.openSearchHit(hit) }
                            }
                            .buttonStyle(.bordered)
                        }
                    }
                }
            }
        }
        .padding(12)
    }
}
