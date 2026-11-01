import SwiftUI

@main
struct AstroNoteApp: App {
    @StateObject private var appModel = AppModel()

    var body: some Scene {
        WindowGroup {
            RootView()
                .environmentObject(appModel)
                .frame(minWidth: 1100, minHeight: 700)
        }
        .commands {
            CommandGroup(replacing: .newItem) {
                Button("New Page") { appModel.createPage() }
                    .keyboardShortcut("n", modifiers: [.command, .shift])
                Button("New Folder") { appModel.createFolder() }
            }
            CommandGroup(after: .saveItem) {
                Button("Save") { Task { await appModel.saveNow() } }
                    .keyboardShortcut("s", modifiers: .command)
            }
        }
    }
}

struct RootView: View {
    @EnvironmentObject private var appModel: AppModel

    var body: some View {
        Group {
            if appModel.connection.isConnected {
                MainSplitView()
            } else {
                ConnectionView()
            }
        }
        .task {
            await appModel.bootstrap()
        }
    }
}
