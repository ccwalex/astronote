import AppKit
import XCTest
@testable import AstroNote

final class SVGSnapshotImageTests: XCTestCase {
    private let png1x1Base64 =
        "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8BQDwAEhQGAhKmMIQAAAABJRU5ErkJggg=="

    func testLooksLikeSVG() {
        let svg = Data("<svg xmlns='http://www.w3.org/2000/svg'></svg>".utf8)
        XCTAssertTrue(SVGSnapshotImage.looksLikeSVG(svg))
        XCTAssertFalse(SVGSnapshotImage.looksLikeSVG(Data([0x89, 0x50, 0x4E, 0x47])))
    }

    func testDecodeExtractsEmbeddedPNG() throws {
        let href = "data:image/png;base64,\(png1x1Base64)"
        let markup = """
        <svg xmlns='http://www.w3.org/2000/svg' xmlns:xlink='http://www.w3.org/1999/xlink' \
        width='40' height='20' viewBox='0 0 40 20'>\
        <image width='100%' height='100%' href='\(href)' xlink:href='\(href)' />\
        <text x='2' y='14'>Hello</text>\
        </svg>
        """
        let snapshot = try XCTUnwrap(SVGSnapshotImage.decode(Data(markup.utf8)))
        XCTAssertEqual(snapshot.width, 40, accuracy: 0.001)
        XCTAssertEqual(snapshot.height, 20, accuracy: 0.001)
        XCTAssertEqual(snapshot.images.count, 1)
        XCTAssertTrue(snapshot.images[0].fullFrame)
        XCTAssertGreaterThan(snapshot.images[0].image.size.width, 0)
        XCTAssertTrue(snapshot.vectorMarkup.contains("Hello"))
        XCTAssertTrue(snapshot.hasVisibleContent)
    }

    func testDecodePlainPNG() throws {
        let png = try XCTUnwrap(Data(base64Encoded: png1x1Base64))
        let snapshot = try XCTUnwrap(SVGSnapshotImage.decode(png))
        XCTAssertEqual(snapshot.images.count, 1)
        XCTAssertTrue(snapshot.vectorMarkup.isEmpty)
    }

    func testParseLength() {
        XCTAssertEqual(SVGSnapshotImage.parseLength("100%", fallback: 0), 100, accuracy: 0.001)
        XCTAssertEqual(SVGSnapshotImage.parseLength("12.5px", fallback: 0), 12.5, accuracy: 0.001)
        XCTAssertEqual(SVGSnapshotImage.parseLength(nil, fallback: 3), 3, accuracy: 0.001)
    }

    func testGroupSnapshotIsTreatedAsSVGNotRawNSImage() {
        let href = "data:image/png;base64,\(png1x1Base64)"
        let markup = """
        <svg xmlns='http://www.w3.org/2000/svg' width='40' height='20' viewBox='0 0 40 20'>\
        <image width='100%' height='100%' href='\(href)' />\
        </svg>
        """
        let data = Data(markup.utf8)
        XCTAssertTrue(SVGSnapshotImage.looksLikeSVG(data))
        XCTAssertEqual(SVGSnapshotImage.decode(data)?.images.count, 1)
    }
}
