import SwiftUI

struct ConnectionView: View {
    @EnvironmentObject private var appModel: AppModel
    @State private var origin: String = ""
    @State private var token: String = ""
    @State private var isTesting = false

    var body: some View {
        VStack(alignment: .leading, spacing: 16) {
            Text("Connect to AstroNote")
                .font(.largeTitle.bold())
            Text("Use your Tailscale server origin (port 5173) and a device token minted on the server.")
                .foregroundStyle(.secondary)

            TextField("Server origin (https://host:5173)", text: $origin)
                .textFieldStyle(.roundedBorder)

            SecureField("API token (an_…)", text: $token)
                .textFieldStyle(.roundedBorder)

            HStack {
                Button(isTesting ? "Connecting…" : "Connect") {
                    Task {
                        isTesting = true
                        await appModel.connect(origin: origin, token: token)
                        isTesting = false
                    }
                }
                .disabled(origin.trimmingCharacters(in: .whitespaces).isEmpty || token.isEmpty || isTesting)

                Button("Use Saved") {
                    Task { await appModel.bootstrap() }
                }
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
        .onAppear {
            if origin.isEmpty, let profile = KeychainStore.loadProfile() {
                origin = profile.origin
            }
        }
    }
}
