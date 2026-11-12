import SwiftUI

private enum LibraryExpandedStorage {
    static func decode(_ raw: String) -> Set<String> {
        guard !raw.isEmpty else { return [] }
        return Set(raw.split(separator: ",").map(String.init))
    }

    static func encode(_ ids: Set<String>) -> String {
        ids.sorted().joined(separator: ",")
    }
}

struct LibrarySidebar: View {
    @EnvironmentObject private var appModel: AppModel
    @AppStorage("astronote.library.expanded") private var expandedStorage = ""
    @State private var expandedFolderIDs: Set<String> = []
    @State private var didSeedExpansionDefaults = false
    @State private var showCreateFolder = false
    @State private var showCreatePage = false
    @State private var newName = ""

    var body: some View {
        List(selection: Binding(get: { appModel.selectedLibraryNodeId }, set: { appModel.selectedLibraryNodeId = $0 })) {
            if let workspace = appModel.workspace {
                ForEach(workspace.rootLibraryNodes()) { node in
                    LibraryNodeRow(
                        node: node,
                        depth: 0,
                        expandedFolderIDs: $expandedFolderIDs,
                        onExpandedChange: persistExpandedIDs
                    )
                }
            } else {
                Text("No library loaded")
            }
            if appModel.maintenanceEnabled {
                Section("Maintenance") {
                    if let embed = appModel.embedStatusMessage {
                        Text(embed).font(.caption)
                    }
                    Button("Embed all assets") { Task { await appModel.embedAllAssets() } }
                }
            }
        }
        .navigationTitle("Library")
        .onAppear {
            expandedFolderIDs = LibraryExpandedStorage.decode(expandedStorage)
            seedRootFolderExpansionIfNeeded()
        }
        .onChange(of: appModel.workspace?.library_nodes.count) { _, _ in
            seedRootFolderExpansionIfNeeded()
        }
        .onChange(of: appModel.selectedLibraryNodeId) { _, nodeId in
            guard let nodeId, let workspace = appModel.workspace,
                  let node = workspace.library_nodes[nodeId], node.kind == "page" else { return }
            Task { await appModel.openLibraryNode(node) }
        }
        .toolbar {
            ToolbarItem(placement: .primaryAction) {
                Menu {
                    Button {
                        showCreateFolder = true
                    } label: {
                        Label("New Folder", systemImage: "folder.badge.plus")
                    }
                    Button {
                        showCreatePage = true
                    } label: {
                        Label("New Page", systemImage: "doc.badge.plus")
                    }
                    Divider()
                    Button {
                        appModel.disconnect(clearCredentials: false)
                    } label: {
                        Label("Disconnect", systemImage: "link.badge.plus")
                    }
                    Button {
                        appModel.disconnect(clearCredentials: true)
                    } label: {
                        Label("Clear saved login", systemImage: "key.slash")
                    }
                } label: {
                    Label("Library actions", systemImage: "ellipsis.circle")
                }
            }
        }
        .sheet(isPresented: $showCreateFolder) {
            LibraryCreateSheet(name: $newName, kind: "folder") {
                appModel.createFolder(name: newName.isEmpty ? "New Folder" : newName, parentId: appModel.selectedLibraryNodeId)
                newName = ""
            }
        }
        .sheet(isPresented: $showCreatePage) {
            LibraryCreateSheet(name: $newName, kind: "page") {
                appModel.createPage(name: newName.isEmpty ? "New Page" : newName, parentId: appModel.selectedLibraryNodeId)
                newName = ""
            }
        }
    }

    private func seedRootFolderExpansionIfNeeded() {
        guard let workspace = appModel.workspace else { return }
        let hadStoredExpansion = !expandedStorage.isEmpty
        if hadStoredExpansion || didSeedExpansionDefaults { return }
        let roots = workspace.rootLibraryNodes().filter { $0.kind == "folder" }
        guard !roots.isEmpty else { return }
        for folder in roots {
            expandedFolderIDs.insert(folder.id)
        }
        didSeedExpansionDefaults = true
        persistExpandedIDs()
    }

    private func persistExpandedIDs() {
        expandedStorage = LibraryExpandedStorage.encode(expandedFolderIDs)
    }
}

private struct LibraryNodeRow: View {
    @EnvironmentObject private var appModel: AppModel
    let node: LibraryNode
    let depth: Int
    @Binding var expandedFolderIDs: Set<String>
    var onExpandedChange: () -> Void

    private var isExpanded: Bool {
        expandedFolderIDs.contains(node.id)
    }

    private func setExpanded(_ value: Bool) {
        if value {
            expandedFolderIDs.insert(node.id)
        } else {
            expandedFolderIDs.remove(node.id)
        }
        onExpandedChange()
    }

    private func toggleExpanded() {
        setExpanded(!isExpanded)
    }

    var body: some View {
        if node.kind == "folder" {
            DisclosureGroup(
                isExpanded: Binding(
                    get: { isExpanded },
                    set: { setExpanded($0) }
                )
            ) {
                if let workspace = appModel.workspace {
                    ForEach(workspace.children(of: node)) { child in
                        LibraryNodeRow(
                            node: child,
                            depth: depth + 1,
                            expandedFolderIDs: $expandedFolderIDs,
                            onExpandedChange: onExpandedChange
                        )
                    }
                }
            } label: {
                LibraryNodeRowView(node: node, depth: depth, onFolderTap: toggleExpanded)
            }
        } else {
            LibraryNodeRowView(node: node, depth: depth, onFolderTap: nil)
        }
    }
}
