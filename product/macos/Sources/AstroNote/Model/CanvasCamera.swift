import Foundation
import CoreGraphics
import AppKit
import PDFKit
import WebKit

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

    mutating func pan(by deltaX: Double, deltaY: Double) {
        offsetX += deltaX
        offsetY += deltaY
    }

    static func scaleFromWheelDelta(lineDelta: Double, scrollingDelta: Double) -> Double {
        let delta = abs(scrollingDelta) > 0.01 ? scrollingDelta : lineDelta
        return pow(1.01, delta)
    }

    static func scrollTargetsEmbeddedSurface(at windowPoint: NSPoint, in window: NSWindow?) -> Bool {
        guard let window, let hit = window.contentView?.hitTest(windowPoint) else { return false }
        var view: NSView? = hit
        while let current = view {
            if current is WKWebView { return true }
            if current is PDFView { return true }
            view = current.superview
        }
        return false
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

    static func rotationRadians(_ raw: [Double]?) -> Double {
        let m = safeMatrix(raw)
        return atan2(m[1], m[0])
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
