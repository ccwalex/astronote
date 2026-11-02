// swift-tools-version: 5.9
import PackageDescription

let infoPlistPath = Context.packageDirectory + "/Resources/Info.plist"

let package = Package(
    name: "AstroNote",
    platforms: [.macOS(.v14)],
    products: [
        .executable(name: "AstroNote", targets: ["AstroNote"]),
    ],
    targets: [
        .executableTarget(
            name: "AstroNote",
            path: "Sources/AstroNote",
            linkerSettings: [
                .linkedFramework("WebKit"),
                // Embed Info.plist so `swift run` (no .app bundle) still honors ATS exceptions for HTTP.
                .unsafeFlags([
                    "-Xlinker", "-sectcreate",
                    "-Xlinker", "__TEXT",
                    "-Xlinker", "__info_plist",
                    "-Xlinker", infoPlistPath,
                ]),
            ]
        ),
        .testTarget(
            name: "AstroNoteTests",
            dependencies: ["AstroNote"],
            path: "Tests/AstroNoteTests"
        ),
    ]
)
