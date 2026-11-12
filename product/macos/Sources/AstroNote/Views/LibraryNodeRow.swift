import SwiftUI

struct LibraryNodeRowView: View {
    @EnvironmentObject private var appModel: AppModel
    let node: LibraryNode
    let depth: Int
    var onFolderTap: (() -> Void)?
    @State private var isRenaming = false
    @State private var renameText = ""
    @State private var confirmDelete = false

    var body: some View {
        HStack {
            if isRenaming {
                TextField("Name", text: $renameText, onCommit: commitRename)
                    .textFieldStyle(.roundedBorder)
            } else {
                label
            }
        }
        .padding(.leading, CGFloat(depth) * 10)
        .contextMenu {
            Button("Rename") {
                renameText = node.name
                isRenaming = true
            }
            Button("Delete", role: .destructive) { confirmDelete = true }
        }
        .confirmationDialog("Delete \(node.name)?", isPresented: $confirmDelete) {
            Button("Delete", role: .destructive) { appModel.deleteLibraryNode(id: node.id) }
            Button("Cancel", role: .cancel) {}
        }
    }

    @ViewBuilder
    private var label: some View {
        if node.kind == "folder" {
            Label(node.name, systemImage: "folder")
                .frame(maxWidth: .infinity, alignment: .leading)
                .contentShape(Rectangle())
                .onTapGesture {
                    onFolderTap?()
                }
        } else {
            Button {
                Task { await appModel.openLibraryNode(node) }
            } label: {
                Label(node.name, systemImage: "doc.text")
            }
            .buttonStyle(.plain)
        }
    }

    private func commitRename() {
        appModel.renameLibraryNode(id: node.id, name: renameText)
        isRenaming = false
    }
}
