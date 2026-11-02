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
