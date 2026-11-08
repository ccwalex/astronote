import SwiftUI

struct LibrarySidebar: View {
    @EnvironmentObject private var appModel: AppModel
    @AppStorage("astronote.library.expanded") private var expandedStorage = ""
    @State private var showCreateFolder = false
    @State private var showCreatePage = false
    @State private var newName = ""

    var body: some View {
        List(selection: Binding(get: { appModel.selectedLibraryNodeId }, set: { appModel.selectedLibraryNodeId = $0 })) {
            if let workspace = appModel.workspace {
                ForEach(workspace.rootLibraryNodes()) { node in
                    LibraryNodeRow(node: node, depth: 0)
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
        .onChange(of: appModel.selectedLibraryNodeId) { _, nodeId in
            guard let nodeId, let workspace = appModel.workspace,
                  let node = workspace.library_nodes[nodeId], node.kind == "page" else { return }
            Task { await appModel.openLibraryNode(node) }
        }
        .toolbar {
            ToolbarItemGroup {
                Button { showCreateFolder = true } label: {
                    Label("Folder", systemImage: "folder.badge.plus")
                        .labelStyle(.titleAndIcon)
                }
                Button { showCreatePage = true } label: {
                    Label("Page", systemImage: "doc.badge.plus")
                        .labelStyle(.titleAndIcon)
                }
                Button { appModel.disconnect(clearCredentials: false) } label: {
                    Label("Disconnect", systemImage: "link.badge.plus")
                        .labelStyle(.titleAndIcon)
                }
                Button { appModel.disconnect(clearCredentials: true) } label: {
                    Label("Clear saved login", systemImage: "key.slash")
                        .labelStyle(.titleAndIcon)
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
}

private struct LibraryNodeRow: View {
    @EnvironmentObject private var appModel: AppModel
    let node: LibraryNode
    let depth: Int

    var body: some View {
        if node.kind == "folder" {
            DisclosureGroup {
                if let workspace = appModel.workspace {
                    ForEach(workspace.children(of: node)) { child in
                        LibraryNodeRow(node: child, depth: depth + 1)
                    }
                }
            } label: {
                LibraryNodeRowView(node: node, depth: depth)
            }
        } else {
            LibraryNodeRowView(node: node, depth: depth)
        }
    }
}
