import Foundation

/// Weak bridge so AppKit `AppDelegate` can reach the SwiftUI-owned `AppModel`.
enum AppTerminationBridge {
    weak static var appModel: AppModel?
}
