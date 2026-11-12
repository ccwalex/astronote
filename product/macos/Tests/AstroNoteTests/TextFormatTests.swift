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

    func testExtendedHeadingsMarkdownToHTML() {
        let md = "#### Four\n\n##### Five\n\n###### Six"
        let html = TextFormat.markdownToHTML(md)
        XCTAssertTrue(html.contains("<h4>Four</h4>"))
        XCTAssertTrue(html.contains("<h5>Five</h5>"))
        XCTAssertTrue(html.contains("<h6>Six</h6>"))
        let back = TextFormat.htmlToMarkdown(html)
        XCTAssertTrue(back.contains("#### Four"))
        XCTAssertTrue(back.contains("##### Five"))
        XCTAssertTrue(back.contains("###### Six"))
    }

    func testNbspBlankParagraphLineInMarkdown() {
        let nbsp = "\u{00a0}"
        let md = "Line one\n\n\(nbsp)\n\nLine two"
        let html = TextFormat.markdownToHTML(md)
        XCTAssertTrue(html.contains("Line one"))
        XCTAssertTrue(html.contains("Line two"))
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

    func testJsonJavaScriptStringEncodesMarkdownForEvaluateJavaScript() {
        let md = "# Title\nline \"quote\" \\ backslash"
        let literal = TextFormatScripts.jsonJavaScriptString(md)
        XCTAssertTrue(literal.hasPrefix("\""))
        XCTAssertTrue(literal.hasSuffix("\""))
        let data = Data(literal.utf8)
        let decoded = try? JSONDecoder().decode(String.self, from: data)
        XCTAssertEqual(decoded, md)
    }
}
