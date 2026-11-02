import Foundation
import CoreGraphics

struct StrokePoint: Hashable {
    var x: Double
    var y: Double
}

struct StrokeDrawStyle {
    var color: String = "#000000"
    var width: Double = 8
    var opacity: Double = 1
    var mode: String = "line"
}

enum CanvasStrokeFactory {
    static func makeObjectId() -> String {
        "obj_\(Int(Date().timeIntervalSince1970 * 1000))_\(UUID().uuidString.prefix(6))"
    }

    static func createStrokeObject(
        objectId: String,
        spaceId: String,
        points: [StrokePoint],
        style: StrokeDrawStyle = StrokeDrawStyle()
    ) -> CanvasObject {
        var minX = Double.infinity
        var minY = Double.infinity
        var maxX = -Double.infinity
        var maxY = -Double.infinity
        if points.isEmpty {
            minX = 0; minY = 0; maxX = 1; maxY = 1
        } else {
            for p in points {
                minX = min(minX, p.x)
                minY = min(minY, p.y)
                maxX = max(maxX, p.x)
                maxY = max(maxY, p.y)
            }
        }
        let w = max(ceil(maxX - minX), 1)
        let h = max(ceil(maxY - minY), 1)
        let pointValues: [JSONValue] = points.map { .object(["x": .number($0.x), "y": .number($0.y)]) }
        let data: [String: JSONValue] = [
            "format": .string("stroke_points_v1"),
            "points": .array(pointValues),
            "style": .object([
                "color": .string(style.color),
                "width": .number(style.width),
                "opacity": .number(style.opacity),
                "mode": .string(style.mode),
            ]),
        ]
        return CanvasObject(
            id: objectId,
            kind: "stroke",
            space_id: spaceId,
            x: minX,
            y: minY,
            width: w,
            height: h,
            transform_matrix: [1, 0, 0, 1, 0, 0],
            data: data,
            metadata: [:]
        )
    }
}

enum CanvasStrokeGeometry {
    static func points(from object: CanvasObject) -> [StrokePoint]? {
        guard case .string(let format)? = object.data["format"], format == "stroke_points_v1" else { return nil }
        guard case .array(let rawPoints)? = object.data["points"] else { return nil }
        let points = rawPoints.compactMap { value -> StrokePoint? in
            guard case .object(let dict) = value,
                  case .number(let x)? = dict["x"],
                  case .number(let y)? = dict["y"] else { return nil }
            return StrokePoint(x: x, y: y)
        }
        return points.count >= 1 ? points : nil
    }

    static func strokeWidth(from object: CanvasObject) -> Double {
        guard case .object(let style)? = object.data["style"],
              case .number(let width)? = style["width"] else { return 3 }
        return width
    }

    static func strokeColor(from object: CanvasObject) -> String {
        guard case .object(let style)? = object.data["style"],
              case .string(let color)? = style["color"] else { return "#000000" }
        return color
    }

    static func strokeOpacity(from object: CanvasObject) -> Double {
        guard case .object(let style)? = object.data["style"],
              case .number(let opacity)? = style["opacity"] else { return 1 }
        return opacity
    }

    static func isHit(object: CanvasObject, localX: Double, localY: Double, radius: Double) -> Bool {
        if let points = points(from: object) {
            let hitRadius = radius + strokeWidth(from: object) / 2
            return isPointNearStrokePoints(points, localX: localX, localY: localY, radius: hitRadius)
        }
        return distanceToBoundingBox(
            px: localX, py: localY,
            x: object.x, y: object.y, width: object.width, height: object.height
        ) <= radius
    }

    static func eraseObject(
        project: inout Project,
        spaceId: String,
        localX: Double,
        localY: Double,
        radius: Double = 12
    ) -> Bool {
        guard var space = project.spaces[spaceId] else { return false }
        var changed = false
        var nextObjectIds: [String] = []

        for objectId in space.object_ids {
            guard let object = project.objects[objectId], object.kind == "stroke" else {
                if project.objects[objectId] != nil { nextObjectIds.append(objectId) }
                continue
            }
            if isHit(object: object, localX: localX, localY: localY, radius: radius) {
                project.objects.removeValue(forKey: objectId)
                changed = true
            } else {
                nextObjectIds.append(objectId)
            }
        }

        if changed {
            space.object_ids = nextObjectIds
            project.spaces[spaceId] = space
        }
        return changed
    }

    static func eraseAtPoint(
        project: inout Project,
        spaceId: String,
        localX: Double,
        localY: Double,
        radius: Double = 12
    ) -> Bool {
        guard var space = project.spaces[spaceId] else { return false }
        var changed = false
        var nextObjectIds: [String] = []

        for objectId in space.object_ids {
            guard var object = project.objects[objectId], object.kind == "stroke" else {
                if project.objects[objectId] != nil { nextObjectIds.append(objectId) }
                continue
            }
            guard isHit(object: object, localX: localX, localY: localY, radius: radius) else {
                nextObjectIds.append(objectId)
                continue
            }
            guard let points = points(from: object), points.count >= 2 else {
                project.objects.removeValue(forKey: objectId)
                changed = true
                continue
            }
            let runs = splitStrokePointRuns(points, localX: localX, localY: localY, radius: radius)
            changed = true
            if runs.isEmpty {
                project.objects.removeValue(forKey: objectId)
                continue
            }
            object = rebuild(object: object, objectId: objectId, points: runs[0])
            project.objects[objectId] = object
            nextObjectIds.append(objectId)
            for index in 1..<runs.count {
                let newId = CanvasStrokeFactory.makeObjectId()
                project.objects[newId] = rebuild(object: object, objectId: newId, points: runs[index])
                nextObjectIds.append(newId)
            }
        }

        if changed {
            space.object_ids = nextObjectIds
            project.spaces[spaceId] = space
        }
        return changed
    }

    private static func rebuild(object: CanvasObject, objectId: String, points: [StrokePoint]) -> CanvasObject {
        var style = StrokeDrawStyle()
        if case .object(let styleDict)? = object.data["style"] {
            if case .string(let color)? = styleDict["color"] { style.color = color }
            if case .number(let width)? = styleDict["width"] { style.width = width }
            if case .number(let opacity)? = styleDict["opacity"] { style.opacity = opacity }
            if case .string(let mode)? = styleDict["mode"] { style.mode = mode }
        }
        return CanvasStrokeFactory.createStrokeObject(objectId: objectId, spaceId: object.space_id ?? "", points: points, style: style)
    }

    private static func isPointNearStrokePoints(_ points: [StrokePoint], localX: Double, localY: Double, radius: Double) -> Bool {
        for p in points where hypot(localX - p.x, localY - p.y) <= radius { return true }
        for index in 1..<points.count {
            let a = points[index - 1]
            let b = points[index]
            if distancePointToSegment(px: localX, py: localY, ax: a.x, ay: a.y, bx: b.x, by: b.y) <= radius {
                return true
            }
        }
        return false
    }

    private static func splitStrokePointRuns(_ points: [StrokePoint], localX: Double, localY: Double, radius: Double) -> [[StrokePoint]] {
        var runs: [[StrokePoint]] = []
        var current: [StrokePoint] = []
        for point in points {
            if hypot(point.x - localX, point.y - localY) > radius {
                current.append(point)
            } else if !current.isEmpty {
                if current.count >= 2 { runs.append(current) }
                current = []
            }
        }
        if current.count >= 2 { runs.append(current) }
        return runs
    }

    private static func distancePointToSegment(px: Double, py: Double, ax: Double, ay: Double, bx: Double, by: Double) -> Double {
        let dx = bx - ax
        let dy = by - ay
        if dx == 0, dy == 0 { return hypot(px - ax, py - ay) }
        let t = max(0, min(1, ((px - ax) * dx + (py - ay) * dy) / (dx * dx + dy * dy)))
        return hypot(px - (ax + t * dx), py - (ay + t * dy))
    }

    private static func distanceToBoundingBox(px: Double, py: Double, x: Double, y: Double, width: Double, height: Double) -> Double {
        let maxX = x + max(width, 0)
        let maxY = y + max(height, 0)
        let dx = px < x ? x - px : (px > maxX ? px - maxX : 0)
        let dy = py < y ? y - py : (py > maxY ? py - maxY : 0)
        return hypot(dx, dy)
    }
}
