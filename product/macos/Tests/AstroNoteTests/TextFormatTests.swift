import XCTest
@testable import AstroNote

final class TextFormatTests: XCTestCase {
    func testMarkdownRoundTripPreservesHeading() {
        let md = "# Title\n\nHello **world**"
        let html = TextFormat.markdownToHTML(md)
        let back = TextFormat.htmlToMarkdown(html)
        XCTAssertTrue(back.contains("# Title"))
        XCTAssertTrue(back.contains("world"))
    }

    func testNestedListMarkdownToHTML() {
        let md = "- one\n  - nested\n    - deeper\n- two"
        let html = TextFormat.markdownToHTML(md)
        XCTAssertTrue(html.contains("<ul>"))
        XCTAssertTrue(html.contains("nested"))
        XCTAssertTrue(html.contains("deeper"))
        XCTAssertTrue(html.contains("two"))
    }

    func testGFMTableMarkdownToHTML() {
        let md = "| a | b |\n| --- | --- |\n| c | d |"
        let html = TextFormat.markdownToHTML(md)
        XCTAssertTrue(html.lowercased().contains("<table"))
        XCTAssertTrue(html.contains("<td>a</td>") || html.contains(">a<"))
        XCTAssertTrue(html.contains("c"))
        XCTAssertFalse(html.lowercased().contains("<th"))
    }

    func testTableRoundTrip() {
        let md = "| a | b |\n| c | d |"
        let html = TextFormat.markdownToHTML(md)
        let back = TextFormat.htmlToMarkdown(html)
        XCTAssertTrue(back.contains("a"))
        XCTAssertTrue(back.contains("---"))
        XCTAssertTrue(back.contains("c"))
    }

    func testHTMLTablePassthroughInMarkdown() {
        let md = "<table><tbody><tr><td>x</td></tr></tbody></table>"
        let html = TextFormat.markdownToHTML(md)
        XCTAssertTrue(html.lowercased().contains("<table"))
        XCTAssertTrue(html.contains("x"))
    }

    func testNestedListRoundTrip() {
        let md = "- alpha\n    - beta"
        let html = TextFormat.markdownToHTML(md)
        let back = TextFormat.htmlToMarkdown(html)
        XCTAssertTrue(back.contains("- alpha"))
        XCTAssertTrue(back.contains("beta"))
    }

    func testStaleSaveRecoveryDecision() {
        XCTAssertEqual(StaleSaveRecovery.decide(recoveryAlreadyUsed: false, recoveryInFlight: false), .recover)
        XCTAssertEqual(StaleSaveRecovery.decide(recoveryAlreadyUsed: true, recoveryInFlight: false), .surfaceError)
        XCTAssertEqual(StaleSaveRecovery.decide(recoveryAlreadyUsed: false, recoveryInFlight: true), .join)
    }

    func testRevisionPollIdleWhenUpToDate() {
        if case .idle = RevisionPoll.decide(clientRev: 10, serverRev: 9, dirty: false) {
            // ok
        } else {
            XCTFail("expected idle")
        }
    }
}
