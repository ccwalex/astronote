import AppKit
import Foundation

struct SVGSnapshotLayer {
    var image: NSImage
    var x: Double
    var y: Double
    var width: Double
    var height: Double
    var fullFrame: Bool
}

struct SVGSnapshot {
    var width: Double
    var height: Double
    var viewBox: String
    var images: [SVGSnapshotLayer]
    var vectorMarkup: String
    var overlayImage: NSImage?

    var hasVisibleContent: Bool {
        !images.isEmpty || overlayImage != nil || !vectorMarkup.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty
    }

    static func raster(_ image: NSImage) -> SVGSnapshot {
        let size = image.size
        return SVGSnapshot(
            width: Double(size.width),
            height: Double(size.height),
            viewBox: "0 0 \(max(1, size.width)) \(max(1, size.height))",
            images: [
                SVGSnapshotLayer(
                    image: image,
                    x: 0,
                    y: 0,
                    width: Double(size.width),
                    height: Double(size.height),
                    fullFrame: true
                )
            ],
            vectorMarkup: "",
            overlayImage: nil
        )
    }
}

enum SVGSnapshotImage {
    static func looksLikeSVG(_ data: Data) -> Bool {
        guard let prefix = String(data: data.prefix(800), encoding: .utf8)?
            .trimmingCharacters(in: .whitespacesAndNewlines)
            .lowercased()
        else { return false }
        if prefix.contains("<svg") { return true }
        return prefix.hasPrefix("<?xml") && data.containsASCII("<svg")
    }

    static func decode(_ data: Data) -> SVGSnapshot? {
        if looksLikeSVG(data) {
            if let parsed = parseSVG(data) { return parsed }
            return decodeEmbeddedRasterFallback(data)
        }
        guard let image = NSImage(data: data), image.size.width > 0, image.size.height > 0 else {
            return nil
        }
        return .raster(image)
    }

    static func parseLength(_ value: String?, fallback: Double = 0) -> Double {
        guard let value else { return fallback }
        let trimmed = value.trimmingCharacters(in: .whitespacesAndNewlines)
        guard let match = trimmed.range(of: #"^[-+]?[0-9]*\.?[0-9]+"#, options: .regularExpression) else {
            return fallback
        }
        return Double(trimmed[match]) ?? fallback
    }

    private static func parseSVG(_ data: Data) -> SVGSnapshot? {
        let document: XMLDocument
        do {
            document = try XMLDocument(data: data, options: [.nodeLoadExternalEntitiesNever])
        } catch {
            return nil
        }
        guard let root = document.rootElement(), root.localName?.lowercased() == "svg" else {
            return nil
        }

        let viewBox = root.attribute(forName: "viewBox")?.stringValue ?? ""
        let vbParts = viewBox.split(whereSeparator: { $0 == " " || $0 == "," }).compactMap { Double($0) }
        let width = parseLength(root.attribute(forName: "width")?.stringValue, fallback: vbParts.count >= 3 ? vbParts[2] : 0)
        let height = parseLength(root.attribute(forName: "height")?.stringValue, fallback: vbParts.count >= 4 ? vbParts[3] : 0)

        var layers: [SVGSnapshotLayer] = []
        let imageNodes = collectImageElements(root)
        for node in imageNodes {
            let href = imageHref(node)
            guard let image = imageFromHref(href) else { continue }
            let xAttr = node.attribute(forName: "x")?.stringValue
            let yAttr = node.attribute(forName: "y")?.stringValue
            let wAttr = node.attribute(forName: "width")?.stringValue
            let hAttr = node.attribute(forName: "height")?.stringValue
            let fullFrame =
                xAttr == nil && yAttr == nil &&
                (wAttr == "100%" || hAttr == "100%" || (wAttr == nil && hAttr == nil))
            layers.append(
                SVGSnapshotLayer(
                    image: image,
                    x: parseLength(xAttr, fallback: 0),
                    y: parseLength(yAttr, fallback: 0),
                    width: wAttr == "100%" ? width : parseLength(wAttr, fallback: width),
                    height: hAttr == "100%" ? height : parseLength(hAttr, fallback: height),
                    fullFrame: fullFrame
                )
            )
            node.detach()
        }

        let leftover = (root.children ?? []).compactMap { child -> String? in
            let xml = child.xmlString
            return xml.isEmpty ? nil : xml
        }.joined()

        let resolvedWidth = width > 0 ? width : 1
        let resolvedHeight = height > 0 ? height : 1
        let resolvedViewBox = viewBox.isEmpty ? "0 0 \(resolvedWidth) \(resolvedHeight)" : viewBox
        let overlay = overlayImage(vectorMarkup: leftover, viewBox: resolvedViewBox, width: resolvedWidth, height: resolvedHeight)

        if layers.isEmpty && leftover.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty {
            return nil
        }

        return SVGSnapshot(
            width: resolvedWidth,
            height: resolvedHeight,
            viewBox: resolvedViewBox,
            images: layers,
            vectorMarkup: leftover,
            overlayImage: overlay
        )
    }

    private static func collectImageElements(_ node: XMLNode) -> [XMLElement] {
        var found: [XMLElement] = []
        if let element = node as? XMLElement, element.localName?.lowercased() == "image" {
            found.append(element)
        }
        for child in node.children ?? [] {
            found.append(contentsOf: collectImageElements(child))
        }
        return found
    }

    private static func decodeEmbeddedRasterFallback(_ data: Data) -> SVGSnapshot? {
        guard let markup = String(data: data, encoding: .utf8) else { return nil }
        guard let regex = try? NSRegularExpression(
            pattern: #"data:image/(png|jpeg|jpg|webp|gif);base64,([A-Za-z0-9+/=\s]+)"#,
            options: .caseInsensitive
        ) else { return nil }
        let nsMarkup = markup as NSString
        let range = NSRange(location: 0, length: nsMarkup.length)
        guard let match = regex.firstMatch(in: markup, range: range), match.numberOfRanges >= 3 else {
            return nil
        }
        let b64 = nsMarkup.substring(with: match.range(at: 2)).filter { !$0.isWhitespace }
        guard let imageData = Data(base64Encoded: b64),
              let image = NSImage(data: imageData),
              image.size.width > 0
        else { return nil }
        return .raster(image)
    }

    private static func imageHref(_ node: XMLElement) -> String {
        if let href = node.attribute(forName: "href")?.stringValue, !href.isEmpty { return href }
        if let href = node.attribute(forLocalName: "href", uri: "http://www.w3.org/1999/xlink")?.stringValue, !href.isEmpty {
            return href
        }
        return node.attribute(forName: "xlink:href")?.stringValue ?? ""
    }

    private static func imageFromHref(_ href: String) -> NSImage? {
        let trimmed = href.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !trimmed.isEmpty else { return nil }
        if trimmed.lowercased().hasPrefix("data:image/") {
            guard let data = DataURI.decode(trimmed), let image = NSImage(data: data), image.size.width > 0 else {
                return nil
            }
            return image
        }
        return nil
    }

    private static func overlayImage(vectorMarkup: String, viewBox: String, width: Double, height: Double) -> NSImage? {
        let leftover = vectorMarkup.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !leftover.isEmpty else { return nil }
        let svg = """
        <svg xmlns="http://www.w3.org/2000/svg" xmlns:xlink="http://www.w3.org/1999/xlink" \
        width="\(max(1, width))" height="\(max(1, height))" viewBox="\(viewBox)">\(leftover)</svg>
        """
        guard let data = svg.data(using: .utf8),
              let image = NSImage(data: data),
              image.size.width > 0,
              image.size.height > 0
        else { return nil }
        return image
    }
}

private extension Data {
    func containsASCII(_ needle: String) -> Bool {
        range(of: Data(needle.utf8)) != nil || range(of: Data(needle.uppercased().utf8)) != nil
    }
}
