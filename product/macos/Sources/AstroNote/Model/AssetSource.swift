import Foundation

enum AssetSource {
    static func resolvePath(asset: Asset, assetId: String) -> String {
        asset.path.isEmpty ? "/api/assets/\(assetId)" : asset.path
    }
}
