import SwiftUI

struct LibrarySidebar: View {
    @EnvironmentObject private var appModel: AppModel

    var body: some View {
        List(selection: Binding(get: { appModel.selectedLibraryNodeId }, set: { appModel.selectedLibraryNodeId = $0 })) {
            if let workspace = appModel.workspace {
                ForEach(workspace.rootLibraryNodes()) { node in
                    LibraryNodeRow(node: node, depth: 0)
                }
            } else {
                Text("No library loaded")
            }
        }
        .navigationTitle("Library")
        .toolbar {
            ToolbarItemGroup {
                Button {
                    appModel.createFolder()
                } label: {
                    Label("Folder", systemImage: "folder.badge.plus")
                }
                Button {
                    appModel.createPage()
                } label: {
                    Label("Page", systemImage: "doc.badge.plus")
                }
                Button {
                    appModel.disconnect()
                } label: {
                    Label("Disconnect", systemImage: "link.badge.plus")
                }
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
                Label(node.name, systemImage: "folder")
            }
        } else {
            Button {
                Task { await appModel.openLibraryNode(node) }
            } label: {
                Label(node.name, systemImage: "doc.text")
                    .padding(.leading, CGFloat(depth) * 12)
            }
            .buttonStyle(.plain)
        }
    }
}
