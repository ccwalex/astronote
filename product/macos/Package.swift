// swift-tools-version: 5.9
import PackageDescription

let package = Package(
    name: "AstroNote",
    platforms: [.macOS(.v14)],
    products: [
        .executable(name: "AstroNote", targets: ["AstroNote"]),
    ],
    targets: [
        .executableTarget(
            name: "AstroNote",
            path: "Sources/AstroNote"
        ),
    ]
)
