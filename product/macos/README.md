# AstroNote macOS client

Native SwiftUI client for the AstroNote workspace API.

## Requirements

- macOS 14+
- Swift 5.9+
- AstroNote backend reachable at `https://<tailscale-host>:5173` (Vite proxy)

## Mint a device token (on the server machine)

```bash
cd code
python3 astronote_token_cli.py mint --label "MacBook"
```

Store the printed `an_…` token in the Mac app connection screen.

## Build & run

```bash
cd product/macos
swift build
swift run AstroNote
```

Open the package in Xcode:

```bash
open Package.swift
```

## Architecture

- `Services/APIClient.swift` — REST client with Bearer token + `X-User-Id` session headers
- `Services/KeychainStore.swift` — server origin + API token
- `ViewModels/AppModel.swift` — workspace state, save debounce, page presence
- `Views/*` — library sidebar, canvas, inspector, search/RAG toolbar

The app talks to the same `/api/*` surface as the React UI ([product/frontend/src/api.ts](../frontend/src/api.ts)).
