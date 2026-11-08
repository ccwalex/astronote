import SwiftUI

struct SearchBarView: View {
    @EnvironmentObject private var appModel: AppModel
    @State private var showRagConfig = false
    @State private var showFolderScope = false

    var body: some View {
        VStack(alignment: .leading, spacing: 8) {
            HStack {
                TextField("Search workspace…", text: $appModel.searchQuery)
                    .textFieldStyle(.roundedBorder)
                    .onSubmit { Task { await appModel.runSearch(mode: .plain) } }
                Button("Folders") { showFolderScope = true }
                Button("Search") { Task { await appModel.runSearch(mode: .plain) } }
                Button("RAG") { Task { await appModel.runSearch(mode: .rag) } }
                Button("Config") { showRagConfig = true }
            }
            if !appModel.searchFolderIds.isEmpty {
                Text("Searching \(appModel.searchFolderIds.count) folder(s)")
                    .font(.caption)
                    .foregroundStyle(.secondary)
            }
            RagSearchControlsView()
            SearchResultsPanel()
        }
        .padding(12)
        .background(Color(nsColor: .windowBackgroundColor))
        .overlay(alignment: .bottom) {
            Divider()
        }
        .sheet(isPresented: $showRagConfig) {
            RagConfigSheet()
        }
        .sheet(isPresented: $showFolderScope) {
            SearchFolderScopeSheet()
        }
    }
}

struct SearchFolderScopeSheet: View {
    @EnvironmentObject private var appModel: AppModel
    @Environment(\.dismiss) private var dismiss
    @State private var selected = Set<String>()

    private var folders: [LibraryNode] {
        guard let workspace = appModel.workspace else { return [] }
        return workspace.library_nodes.values
            .filter { $0.kind == "folder" }
            .sorted { $0.name.localizedCaseInsensitiveCompare($1.name) == .orderedAscending }
    }

    var body: some View {
        VStack(alignment: .leading, spacing: 12) {
            Text("Search folders").font(.headline)
            if folders.isEmpty {
                Text("No library folders available.").foregroundStyle(.secondary)
            } else {
                ScrollView {
                    VStack(alignment: .leading, spacing: 8) {
                        ForEach(folders) { folder in
                            Toggle(isOn: Binding(
                                get: { selected.contains(folder.id) },
                                set: { isOn in
                                    if isOn { selected.insert(folder.id) } else { selected.remove(folder.id) }
                                }
                            )) {
                                VStack(alignment: .leading) {
                                    Text(folder.name).fontWeight(.semibold)
                                }
                            }
                        }
                    }
                }
                .frame(maxHeight: 280)
            }
            HStack {
                Button("All folders") {
                    selected = Set(folders.map(\.id))
                }
                Spacer()
                Button("Cancel", role: .cancel) { dismiss() }
                Button("Apply") {
                    appModel.searchFolderIds = folders.filter { selected.contains($0.id) }.map(\.id)
                    dismiss()
                }
                .disabled(selected.isEmpty)
            }
        }
        .padding()
        .frame(width: 420)
        .onAppear {
            if appModel.searchFolderIds.isEmpty {
                selected = Set(appModel.libraryFolderIds())
            } else {
                selected = Set(appModel.searchFolderIds)
            }
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
            SecureField("RAG API key (stored locally)", text: $apiKey)
            Button("Save") {
                Task {
                    try? CredentialStore.saveRagApiKey(apiKey)
                    dismiss()
                }
            }
        }
        .padding()
        .frame(width: 420)
    }
}
