import SwiftUI

struct ConnectionView: View {
    @EnvironmentObject private var appModel: AppModel
    @State private var origin: String = ""
    @State private var token: String = ""
    @State private var isTesting = false
    @State private var isPreparingNetwork = false
    @State private var localNetworkMessage: String?

    private var busy: Bool { isTesting || isPreparingNetwork || appModel.isLoading }

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
                    Task { await appModel.bootstrap(auto: false) }
                }
                .disabled(busy)
            }

            HStack(spacing: 12) {
                Button(isPreparingNetwork ? "Preparing…" : "Prepare Local Network Access") {
                    Task {
                        isPreparingNetwork = true
                        localNetworkMessage = nil
                        localNetworkMessage = await appModel.prepareLocalNetworkAccess(for: origin)
                        isPreparingNetwork = false
                    }
                }
                .disabled(origin.trimmingCharacters(in: .whitespaces).isEmpty || busy)

                Button("Open Local Network Settings") {
                    LocalNetworkAccess.openPrivacySettings()
                }
            }
            Text("macOS shows a system alert the first time — click Allow. AstroNote then appears under Privacy → Local Network.")
                .font(.caption)
                .foregroundStyle(.secondary)

            if isPreparingNetwork {
                ProgressView("Requesting Local Network access…")
                    .controlSize(.small)
            }

            if let localNetworkMessage {
                Text(localNetworkMessage)
                    .font(.callout)
                    .foregroundStyle(.secondary)
                    .textSelection(.enabled)
            }

            if let status = appModel.statusMessage, localNetworkMessage == nil {
                Text(status)
                    .font(.callout)
                    .foregroundStyle(.secondary)
            }

            if busy {
                ProgressView("Connecting…")
                    .controlSize(.small)
            }

            if let error = appModel.connection.errorMessage {
                Text(error)
                    .foregroundStyle(.red)
                    .font(.callout)
                    .textSelection(.enabled)
            }

            GroupBox("Mint a token on the server") {
                Text("python3 code/astronote_token_cli.py mint --label \"MacBook\"")
                    .font(.system(.body, design: .monospaced))
                    .textSelection(.enabled)
            }

            Text("AstroNote \(AppVersion.short)")
                .font(.caption2)
                .foregroundStyle(.tertiary)
        }
        .padding(32)
        .frame(maxWidth: 520)
        .onAppear { syncFields() }
        .onChange(of: appModel.connection.origin) { _, _ in syncFields() }
        .onChange(of: appModel.connection.token) { _, _ in syncFields() }
    }

    private func syncFields() {
        if origin.isEmpty, !appModel.connection.origin.isEmpty {
            origin = appModel.connection.origin
        }
        if token.isEmpty, !appModel.connection.token.isEmpty {
            token = appModel.connection.token
        }
    }
}
