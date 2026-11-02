import Foundation
import CoreGraphics

struct CanvasCamera: Equatable {
    var scale: Double = 1
    var offsetX: Double = 0
    var offsetY: Double = 0

    static let minScale: Double = 0.25
    static let maxScale: Double = 4

    mutating func clampScale() {
        scale = min(max(scale, Self.minScale), Self.maxScale)
    }

    mutating func zoomAround(point: CGPoint, deltaScale: Double) {
        let oldScale = scale
        scale = min(max(scale * deltaScale, Self.minScale), Self.maxScale)
        let factor = scale / oldScale
        offsetX = point.x - factor * (point.x - offsetX)
        offsetY = point.y - factor * (point.y - offsetY)
    }

    static func scaleFromWheelDelta(_ delta: Double) -> Double {
        pow(1.0015, delta)
    }
}

enum SpaceLayout {
    static func pointerToWorld(point: CGPoint, camera: CanvasCamera) -> CGPoint {
        CGPoint(
            x: (point.x - camera.offsetX) / camera.scale,
            y: (point.y - camera.offsetY) / camera.scale
        )
    }

    static func absolutePosition(space: Space, spaces: [String: Space]) -> CGPoint {
        var x = space.x
        var y = space.y
        var parentId = space.parent_space_id
        while let pid = parentId, let parent = spaces[pid] {
            x += parent.x
            y += parent.y
            parentId = parent.parent_space_id
        }
        return CGPoint(x: x, y: y)
    }
}

enum SpaceSnap {
    static func snapTranslation(_ value: Double, grid: Double = 8) -> Double {
        (value / grid).rounded() * grid
    }
}

enum SpaceTransform {
    static func safeMatrix(_ raw: [Double]?) -> [Double] {
        guard let raw, raw.count == 6 else { return [1, 0, 0, 1, 0, 0] }
        return raw
    }
}

enum CanvasVisibility {
    static func isVisible(space: Space, viewport: CGRect, camera: CanvasCamera) -> Bool {
        let origin = SpaceLayout.absolutePosition(space: space, spaces: [:])
        let rect = CGRect(x: origin.x * camera.scale + camera.offsetX, y: origin.y * camera.scale + camera.offsetY,
                          width: space.width * camera.scale, height: space.height * camera.scale)
        return rect.intersects(viewport)
    }
}

enum DeferredSpaceSelection {
    static var pendingSpaceId: String?
}
