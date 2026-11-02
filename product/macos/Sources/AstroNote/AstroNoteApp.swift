import SwiftUI

@main
struct AstroNoteApp: App {
    @NSApplicationDelegateAdaptor(AppDelegate.self) private var appDelegate
    @StateObject private var appModel = AppModel()

    var body: some Scene {
        WindowGroup {
            RootView()
                .environmentObject(appModel)
                .onAppear { AppTerminationBridge.appModel = appModel }
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
                Button("Undo") { appModel.undo() }
                    .keyboardShortcut("z", modifiers: .command)
                Button("Redo") { appModel.redo() }
                    .keyboardShortcut("z", modifiers: [.command, .shift])
                Button("Commit checkpoint") { Task { await appModel.commitCheckpoint() } }
                Button("Revert to baseline") { Task { await appModel.revertToBaseline() } }
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
        .onAppear {
            KeyboardShortcutMonitor.install(handlers: .init(
                isEditableTarget: { EditableKeyboardTarget.isActive() },
                onUndo: { appModel.undo() },
                onRedo: { appModel.redo() }
            ))
        }
    }
}
