import SwiftUI

struct MainSplitView: View {
    @EnvironmentObject private var appModel: AppModel

    var body: some View {
        NavigationSplitView {
            LibrarySidebar()
                .navigationSplitViewColumnWidth(min: 220, ideal: 260, max: 320)
        } content: {
            VStack(spacing: 0) {
                SearchBarView()
                StatusBannerView()
                ProjectAreaView()
            }
        } detail: {
            InspectorPanel()
                .navigationSplitViewColumnWidth(min: 220, ideal: 260, max: 320)
        }
    }
}

struct StatusBannerView: View {
    @EnvironmentObject private var appModel: AppModel

    var body: some View {
        VStack(alignment: .leading, spacing: 4) {
            if let message = appModel.statusMessage {
                Text(message).font(.caption).foregroundStyle(.secondary)
            }
            if let error = appModel.errorMessage {
                Text(error).font(.caption).foregroundStyle(.red)
            }
            if !appModel.canWritePage {
                Text("Read-only: another client holds the page write lock.")
                    .font(.caption.weight(.semibold))
                    .foregroundStyle(.orange)
            }
            if appModel.isDirty {
                Text("Unsaved changes").font(.caption).foregroundStyle(.yellow)
            }
        }
        .frame(maxWidth: .infinity, alignment: .leading)
        .padding(.horizontal, 12)
        .padding(.vertical, 6)
        .background(Color(nsColor: .windowBackgroundColor))
    }
}

struct ProjectAreaView: View {
    @EnvironmentObject private var appModel: AppModel

    var body: some View {
        if appModel.selectedProjectId == nil {
            ContentUnavailableView("Select a page", systemImage: "doc.text", description: Text("Choose a page from the library."))
        } else if appModel.isLoading && appModel.hydratedProject == nil {
            ProgressView("Loading page…")
                .frame(maxWidth: .infinity, maxHeight: .infinity)
        } else if let project = appModel.hydratedProject {
            VStack(spacing: 0) {
                ProjectHeaderView(project: project)
                ToolbarView()
                CanvasView(project: project)
            }
        } else {
            ContentUnavailableView("Could not load page", systemImage: "exclamationmark.triangle")
        }
    }
}

struct ProjectHeaderView: View {
    let project: Project

    var body: some View {
        HStack {
            Text(project.name).font(.headline)
            Spacer()
        }
        .padding(.horizontal, 12)
        .padding(.vertical, 8)
    }
}
