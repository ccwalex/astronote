# Distributing the macOS client (no backend)

The Mac app is a **thin client**. It does not ship Python, SQLite, or the AstroNote server. All data lives on your server; the app connects over the network using:

1. **Tailscale** (or any route) to reach the machine running AstroNote.
2. A **device API token** (`an_…`) minted on that server.

## Build a release locally

```bash
cd product/macos
chmod +x scripts/package.sh
./scripts/package.sh 0.1.0
```

Outputs under `dist/`:

| Artifact | Purpose |
|----------|---------|
| `AstroNote.app` | Universal (Apple Silicon + Intel) application bundle |
| `AstroNote-0.1.0-macOS-universal.zip` | Zip for sharing |
| `AstroNote-0.1.0-macOS-universal.dmg` | Disk image with Applications symlink |

Requires Xcode command-line tools / Swift 5.9+ on macOS 14+.

## Publish via GitHub Releases

Tag and push:

```bash
git tag astronote-macos-v0.1.0
git push origin astronote-macos-v0.1.0
```

The workflow `.github/workflows/macos-client-release.yml` builds the app and attaches the zip and DMG to a release.

Manual run: **Actions → macOS client release → Run workflow**, set the version string.

## Server setup (reminder)

On the **server** host (where the repo runs):

```bash
cd code
python3 astronote_token_cli.py mint --label "MacBook"
```

Ensure Tailscale is on both machines and the server listens on a port reachable from the Mac (typically Vite on `:5173` proxying `/api`).

## Code signing

Local `package.sh` applies **ad-hoc** signing (`codesign -`). That is enough for personal use; other users may need **Right click → Open** once.

For wider distribution, sign with a **Developer ID** and notarize with Apple (`notarytool`), then staple the ticket before shipping the DMG.
