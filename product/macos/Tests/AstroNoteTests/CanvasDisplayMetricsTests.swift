import XCTest
import CoreGraphics
@testable import AstroNote

final class CanvasDisplayMetricsTests: XCTestCase {
    func testChromeInsetsMatchWeb() {
        XCTAssertEqual(CanvasDisplayMetrics.horizontalInset, 22, accuracy: 0.001)
        XCTAssertEqual(CanvasDisplayMetrics.verticalInset, 30, accuracy: 0.001)
        XCTAssertEqual(CanvasDisplayMetrics.textSpaceOuterChromeHeight, 30, accuracy: 0.001)
    }

    func testContentSizeFromOuter() {
        let inner = CanvasDisplayMetrics.contentSize(outerWidth: 320, outerHeight: 200)
        XCTAssertEqual(inner.width, 298, accuracy: 0.001)
        XCTAssertEqual(inner.height, 170, accuracy: 0.001)
    }

    func testRequiredTextSpaceHeight() {
        XCTAssertEqual(CanvasDisplayMetrics.requiredTextSpaceHeight(contentHeight: 50), 80)
        XCTAssertEqual(CanvasDisplayMetrics.requiredTextSpaceHeight(contentHeight: 50.2), 81)
    }

    func testMinContentHeight() {
        XCTAssertEqual(CanvasDisplayMetrics.minContentHeight, 18 * 1.4 + 5, accuracy: 0.001)
    }

    func testWorldScreenRoundTripAtZoomOne() {
        var camera = CanvasCamera()
        camera.scale = 1
        camera.offsetX = 10
        camera.offsetY = 20
        let world = CGPoint(x: 100, y: 50)
        let screen = CanvasDisplayMetrics.worldToScreen(world: world, camera: camera)
        XCTAssertEqual(screen.x, 110, accuracy: 0.001)
        XCTAssertEqual(screen.y, 70, accuracy: 0.001)
        let back = CanvasDisplayMetrics.screenToWorld(screen: screen, camera: camera)
        XCTAssertEqual(back.x, world.x, accuracy: 0.001)
        XCTAssertEqual(back.y, world.y, accuracy: 0.001)
    }

    func testWorldScreenAtZoomTwo() {
        var camera = CanvasCamera()
        camera.scale = 2
        camera.offsetX = 0
        camera.offsetY = 0
        let screen = CanvasDisplayMetrics.worldToScreen(world: CGPoint(x: 40, y: 30), camera: camera)
        XCTAssertEqual(screen.x, 80, accuracy: 0.001)
        XCTAssertEqual(screen.y, 60, accuracy: 0.001)
        let back = CanvasDisplayMetrics.screenToWorld(screen: screen, camera: camera)
        XCTAssertEqual(back.x, 40, accuracy: 0.001)
        XCTAssertEqual(back.y, 30, accuracy: 0.001)
    }

    func testSpaceScreenRect() {
        var camera = CanvasCamera()
        camera.scale = 1.5
        camera.offsetX = 5
        camera.offsetY = 5
        let rect = CanvasDisplayMetrics.spaceScreenRect(
            origin: CGPoint(x: 10, y: 20),
            outerSize: CGSize(width: 100, height: 80),
            scaleX: 1,
            scaleY: 1,
            camera: camera
        )
        XCTAssertEqual(rect.origin.x, 20, accuracy: 0.001)
        XCTAssertEqual(rect.origin.y, 35, accuracy: 0.001)
        XCTAssertEqual(rect.width, 150, accuracy: 0.001)
        XCTAssertEqual(rect.height, 120, accuracy: 0.001)
    }
}
