import SwiftUI

/// Packs subviews left-to-right, wrapping onto the next row when they no longer fit.
struct FlowLayout: Layout {
    var horizontalSpacing: CGFloat = 8
    var verticalSpacing: CGFloat = 8

    func sizeThatFits(proposal: ProposedViewSize, subviews: Subviews, cache: inout ()) -> CGSize {
        let maxWidth = proposal.width ?? .infinity
        guard maxWidth.isFinite else {
            var x: CGFloat = 0
            var rowHeight: CGFloat = 0
            for subview in subviews {
                let size = subview.sizeThatFits(.unspecified)
                if x > 0 { x += horizontalSpacing }
                x += size.width
                rowHeight = max(rowHeight, size.height)
            }
            return CGSize(width: x, height: rowHeight)
        }
        return CGSize(width: maxWidth, height: pack(maxWidth: maxWidth, subviews: subviews).height)
    }

    func placeSubviews(in bounds: CGRect, proposal: ProposedViewSize, subviews: Subviews, cache: inout ()) {
        let lines = pack(maxWidth: bounds.width, subviews: subviews).lines
        var y = bounds.minY
        for line in lines {
            var x = bounds.minX
            for placement in line.placements {
                placement.subview.place(
                    at: CGPoint(x: x, y: y + (line.rowHeight - placement.size.height) / 2),
                    anchor: .topLeading,
                    proposal: ProposedViewSize(placement.size)
                )
                x += placement.size.width + horizontalSpacing
            }
            y += line.rowHeight + verticalSpacing
        }
    }

    private struct Placement {
        var subview: LayoutSubviews.Element
        var size: CGSize
    }

    private struct Line {
        var placements: [Placement]
        var rowHeight: CGFloat
    }

    private struct PackResult {
        var lines: [Line]
        var height: CGFloat
    }

    private func pack(maxWidth: CGFloat, subviews: Subviews) -> PackResult {
        var lines: [Line] = []
        var current: [Placement] = []
        var rowHeight: CGFloat = 0
        var rowWidth: CGFloat = 0

        func finishRow() {
            guard !current.isEmpty else { return }
            lines.append(Line(placements: current, rowHeight: rowHeight))
            current = []
            rowHeight = 0
            rowWidth = 0
        }

        for subview in subviews {
            let size = subview.sizeThatFits(.unspecified)
            let additional = (rowWidth > 0 ? horizontalSpacing : 0) + size.width
            if rowWidth > 0, rowWidth + additional > maxWidth {
                finishRow()
            }
            let spacing = rowWidth > 0 ? horizontalSpacing : 0
            rowWidth += spacing + size.width
            rowHeight = max(rowHeight, size.height)
            current.append(Placement(subview: subview, size: size))
        }
        finishRow()

        let height = lines.reduce(0) { partial, line in
            partial + line.rowHeight
        } + max(0, CGFloat(lines.count - 1)) * verticalSpacing
        return PackResult(lines: lines, height: height)
    }
}
