// swift-tools-version: 5.9
import PackageDescription

let infoPlistPath = Context.packageDirectory + "/Resources/Info.plist"
// Packaged .app bundles carry ATS in Contents/Info.plist. Embedding __info_plist in the
// Mach-O can override that on Apple Silicon and re-enable ATS blocks for HTTP.
let embedInfoPlistInBinary = Context.environment["ASTRONOTE_EMBED_PLIST"] != "0"
var astroLinkerSettings: [LinkerSetting] = [
    .linkedFramework("WebKit"),
    .linkedFramework("Network"),
]
if embedInfoPlistInBinary {
    astroLinkerSettings.append(
        .unsafeFlags([
            "-Xlinker", "-sectcreate",
            "-Xlinker", "__TEXT",
            "-Xlinker", "__info_plist",
            "-Xlinker", infoPlistPath,
        ])
    )
}

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
            resources: [
                .process("Resources"),
            ],
            linkerSettings: astroLinkerSettings
        ),
        .testTarget(
            name: "AstroNoteTests",
            dependencies: ["AstroNote"],
            path: "Tests/AstroNoteTests"
        ),
    ]
)
