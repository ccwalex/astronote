import SwiftUI

struct SearchBarView: View {
    @EnvironmentObject private var appModel: AppModel
    @State private var showRagConfig = false

    var body: some View {
        VStack(alignment: .leading, spacing: 8) {
            HStack {
                TextField("Search workspace…", text: $appModel.searchQuery)
                    .textFieldStyle(.roundedBorder)
                    .onSubmit { Task { await appModel.runSearch(mode: .plain) } }
                Button("Search") { Task { await appModel.runSearch(mode: .plain) } }
                Button("RAG") { Task { await appModel.runSearch(mode: .rag) } }
                Button("Config") { showRagConfig = true }
            }
            RagSearchControlsView()
            SearchResultsPanel()
        }
        .padding(12)
        .sheet(isPresented: $showRagConfig) {
            RagConfigSheet()
        }
    }
}

struct RagSearchControlsView: View {
    @EnvironmentObject private var appModel: AppModel

    var body: some View {
        HStack {
            Picker("Mode", selection: $appModel.ragMode) {
                Text("Mixed").tag("mixed")
                Text("Embedding").tag("embedding")
                Text("Word").tag("word")
            }
            .pickerStyle(.segmented)
            .frame(maxWidth: 320)
            Toggle("LLM answer", isOn: $appModel.ragLLMEnabled)
        }
    }
}

struct SearchResultsPanel: View {
    @EnvironmentObject private var appModel: AppModel

    var body: some View {
        if let answer = appModel.ragAnswer, !answer.isEmpty {
            Text(answer).font(.caption).padding(8).background(.quaternary.opacity(0.4)).cornerRadius(6)
        }
        if !appModel.searchResults.isEmpty || !appModel.ragMasterNodes.isEmpty {
            ScrollView(.horizontal, showsIndicators: false) {
                HStack {
                    ForEach(appModel.ragMasterNodes) { node in
                        Button(node.label ?? node.id) {
                            Task {
                                if let projectId = node.project_id {
                                    await appModel.openProject(projectId)
                                    appModel.selectSpace(node.space_id)
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
}

struct RagConfigSheet: View {
    @EnvironmentObject private var appModel: AppModel
    @Environment(\.dismiss) private var dismiss
    @State private var apiKey = ""

    var body: some View {
        Form {
            SecureField("RAG API key (stored in Keychain)", text: $apiKey)
            Button("Save") {
                Task {
                    try? KeychainStore.saveRagApiKey(apiKey)
                    dismiss()
                }
            }
        }
        .padding()
        .frame(width: 420)
    }
}
