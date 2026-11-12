import XCTest
import CoreGraphics
@testable import AstroNote

final class CanvasCameraTests: XCTestCase {
    func testPanDownDecreasesOffsetY() {
        var camera = CanvasCamera()
        camera.pan(by: 0, deltaY: -40)
        XCTAssertEqual(camera.offsetY, -40)
    }

    func testClampReachesBottomWhenContentIsTaller() {
        var camera = CanvasCamera(offsetY: 0)
        let viewport = CGSize(width: 800, height: 600)
        let content = CGSize(width: 1200, height: 2400)
        camera.pan(by: 0, deltaY: -5000)
        camera.clampOffset(viewport: viewport, contentSize: content)
        XCTAssertEqual(camera.offsetY, viewport.height - content.height * camera.scale, accuracy: 0.001)
    }

    func testClampLocksOffsetWhenContentFitsViewport() {
        var camera = CanvasCamera(offsetY: -120)
        let viewport = CGSize(width: 1200, height: 900)
        let content = CGSize(width: 800, height: 600)
        camera.clampOffset(viewport: viewport, contentSize: content)
        XCTAssertEqual(camera.offsetY, 0)
        XCTAssertEqual(camera.offsetX, 0)
    }

    func testEffectiveFrameUsesAbsolutePositionAndScale() {
        let parent = Space(
            id: "parent",
            kind: "group",
            x: 100,
            y: 200,
            width: 400,
            height: 300
        )
        let child = Space(
            id: "child",
            kind: "text",
            x: 50,
            y: 60,
            width: 100,
            height: 80,
            parent_space_id: "parent",
            scale_x: 2,
            scale_y: 1.5
        )
        let spaces = ["parent": parent, "child": child]
        let frame = CanvasWorldBounds.effectiveFrame(space: child, spaces: spaces)
        XCTAssertEqual(frame.origin.x, 150, accuracy: 0.001)
        XCTAssertEqual(frame.origin.y, 260, accuracy: 0.001)
        XCTAssertEqual(frame.width, 200, accuracy: 0.001)
        XCTAssertEqual(frame.height, 120, accuracy: 0.001)
    }

    func testContentSizeIncludesNestedSpaceExtents() {
        let parent = Space(
            id: "parent",
            kind: "group",
            x: 100,
            y: 200,
            width: 400,
            height: 300
        )
        let child = Space(
            id: "child",
            kind: "text",
            x: 900,
            y: 700,
            width: 100,
            height: 80,
            parent_space_id: "parent",
            scale_x: 2,
            scale_y: 1.5
        )
        let spaces = ["parent": parent, "child": child]
        let withChild = CanvasWorldBounds.contentSize(visibleSpaces: [parent, child], spaces: spaces)
        let parentOnly = CanvasWorldBounds.contentSize(visibleSpaces: [parent], spaces: spaces)
        XCTAssertGreaterThan(withChild.width, parentOnly.width)
        XCTAssertGreaterThan(withChild.height, parentOnly.height)
        XCTAssertEqual(withChild.width, 1600, accuracy: 0.001)
        XCTAssertEqual(withChild.height, 1420, accuracy: 0.001)
    }
}
