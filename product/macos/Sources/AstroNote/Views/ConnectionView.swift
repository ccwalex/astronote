import SwiftUI

struct ConnectionView: View {
    @EnvironmentObject private var appModel: AppModel
    @State private var origin: String = ""
    @State private var token: String = ""
    @State private var isTesting = false

    private var busy: Bool { isTesting || appModel.isLoading }

    var body: some View {
        VStack(alignment: .leading, spacing: 16) {
            Text("Connect to AstroNote")
                .font(.largeTitle.bold())
            Text("Use http:// (not https://) — e.g. http://alexws.tailfd28ba.ts.net:5173 — and a device token minted on the server.")
                .foregroundStyle(.secondary)

            TextField("Server origin (http://host:5173)", text: $origin)
                .textFieldStyle(.roundedBorder)
                .disabled(busy)

            SecureField("API token (an_…)", text: $token)
                .textFieldStyle(.roundedBorder)
                .disabled(busy)

            HStack {
                Button(busy ? "Connecting…" : "Connect") {
                    Task {
                        isTesting = true
                        await appModel.connect(origin: origin, token: token)
                        isTesting = false
                    }
                }
                .disabled(origin.trimmingCharacters(in: .whitespaces).isEmpty || token.isEmpty || busy)

                Button("Use Saved") {
                    Task { await appModel.bootstrap() }
                }
                .disabled(busy)
            }

            if busy {
                ProgressView("Connecting…")
                    .controlSize(.small)
            }

            if let error = appModel.connection.errorMessage {
                Text(error)
                    .foregroundStyle(.red)
                    .font(.callout)
            }

            GroupBox("Mint a token on the server") {
                Text("python3 code/astronote_token_cli.py mint --label \"MacBook\"")
                    .font(.system(.body, design: .monospaced))
                    .textSelection(.enabled)
            }
        }
        .padding(32)
        .frame(maxWidth: 520)
        .task {
            if origin.isEmpty, let profile = await Task.detached(priority: .userInitiated, operation: {
                KeychainStore.loadProfile()
            }).value {
                origin = profile.origin
            }
        }
    }
}
