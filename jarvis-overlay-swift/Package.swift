// swift-tools-version: 5.9
import PackageDescription

let package = Package(
    name: "JarvisOverlay",
    platforms: [.macOS(.v12)],
    targets: [
        .executableTarget(
            name: "JarvisOverlay",
            path: "Sources/JarvisOverlay"
        )
    ]
)
