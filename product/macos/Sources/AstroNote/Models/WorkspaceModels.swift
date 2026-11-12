import Foundation

struct Asset: Codable, Identifiable, Hashable {
    var id: String
    var kind: String
    var path: String
    var filename: String
    var content: String?
    var mime_type: String?
    var metadata: [String: JSONValue]

    init(from decoder: Decoder) throws {
        let c = try decoder.container(keyedBy: CodingKeys.self)
        id = try c.decode(String.self, forKey: .id)
        kind = try c.decodeIfPresent(String.self, forKey: .kind) ?? "markdown"
        path = try c.decodeIfPresent(String.self, forKey: .path) ?? ""
        filename = try c.decodeIfPresent(String.self, forKey: .filename) ?? id
        content = try c.decodeIfPresent(String.self, forKey: .content)
        mime_type = try c.decodeIfPresent(String.self, forKey: .mime_type)
        metadata = try c.decodeIfPresent([String: JSONValue].self, forKey: .metadata) ?? [:]
    }

    init(
        id: String,
        kind: String,
        path: String = "",
        filename: String? = nil,
        content: String? = nil,
        mime_type: String? = nil,
        metadata: [String: JSONValue] = [:]
    ) {
        self.id = id
        self.kind = kind
        self.path = path.isEmpty ? "\(id).md" : path
        self.filename = filename ?? id
        self.content = content
        self.mime_type = mime_type
        self.metadata = metadata
    }
}

struct CanvasObject: Codable, Identifiable, Hashable {
    var id: String
    var kind: String
    var space_id: String?
    var x: Double
    var y: Double
    var width: Double
    var height: Double
    var transform_matrix: [Double]
    var data: [String: JSONValue]
    var metadata: [String: JSONValue]
}

struct Space: Codable, Identifiable, Hashable {
    var id: String
    var kind: String
    var x: Double
    var y: Double
    var z: Double
    var width: Double
    var height: Double
    var parent_space_id: String?
    var child_space_ids: [String]
    var object_ids: [String]
    var asset_ids: [String]
    var scale_x: Double
    var scale_y: Double
    var reference_asset_id: String?
    var reference_mode: String
    var transform_matrix: [Double]?
    var background_color: String?

    init(from decoder: Decoder) throws {
        let c = try decoder.container(keyedBy: CodingKeys.self)
        id = try c.decode(String.self, forKey: .id)
        kind = try c.decode(String.self, forKey: .kind)
        x = try c.decodeIfPresent(Double.self, forKey: .x) ?? 0
        y = try c.decodeIfPresent(Double.self, forKey: .y) ?? 0
        z = try c.decodeIfPresent(Double.self, forKey: .z) ?? 0
        width = try c.decodeIfPresent(Double.self, forKey: .width) ?? 320
        height = try c.decodeIfPresent(Double.self, forKey: .height) ?? 240
        parent_space_id = try c.decodeIfPresent(String.self, forKey: .parent_space_id)
        child_space_ids = try c.decodeIfPresent([String].self, forKey: .child_space_ids) ?? []
        object_ids = try c.decodeIfPresent([String].self, forKey: .object_ids) ?? []
        asset_ids = try c.decodeIfPresent([String].self, forKey: .asset_ids) ?? []
        scale_x = try c.decodeIfPresent(Double.self, forKey: .scale_x) ?? 1
        scale_y = try c.decodeIfPresent(Double.self, forKey: .scale_y) ?? 1
        reference_asset_id = try c.decodeIfPresent(String.self, forKey: .reference_asset_id)
        reference_mode = try c.decodeIfPresent(String.self, forKey: .reference_mode) ?? ""
        transform_matrix = try c.decodeIfPresent([Double].self, forKey: .transform_matrix)
        background_color = try c.decodeIfPresent(String.self, forKey: .background_color)
    }

    init(
        id: String,
        kind: String,
        x: Double,
        y: Double,
        z: Double = 1,
        width: Double,
        height: Double,
        parent_space_id: String? = nil,
        child_space_ids: [String] = [],
        object_ids: [String] = [],
        asset_ids: [String] = [],
        scale_x: Double = 1,
        scale_y: Double = 1,
        reference_asset_id: String? = nil,
        reference_mode: String = "",
        transform_matrix: [Double]? = [1, 0, 0, 1, 0, 0],
        background_color: String? = nil
    ) {
        self.id = id
        self.kind = kind
        self.x = x
        self.y = y
        self.z = z
        self.width = width
        self.height = height
        self.parent_space_id = parent_space_id
        self.child_space_ids = child_space_ids
        self.object_ids = object_ids
        self.asset_ids = asset_ids
        self.scale_x = scale_x
        self.scale_y = scale_y
        self.reference_asset_id = reference_asset_id
        self.reference_mode = reference_mode
        self.transform_matrix = transform_matrix
        self.background_color = background_color
    }
}

struct Project: Codable, Identifiable, Hashable {
    var id: String
    var name: String
    var root_space_id: String?
    var spaces: [String: Space]
    var objects: [String: CanvasObject]
    var assets: [String: Asset]
    var workspace_revision: Int?
    var project_revision: Int?
}

struct LibraryNode: Codable, Identifiable, Hashable {
    var id: String
    var kind: String
    var name: String
    var parent_id: String?
    var child_ids: [String]
    var target_project_id: String?
}

struct Workspace: Codable, Identifiable, Hashable {
    var id: String
    var name: String
    var library_nodes: [String: LibraryNode]
    var projects: [String: Project]
    var workspace_revision: Int?
}

struct PageLoadResponse: Codable {
    var nav: Workspace
    var workspace_revision: Int?
    var project: Project?
    var resolved_project_id: String?
    var resolved_library_node_id: String?
}

struct SearchResponse: Codable {
    var status: String?
    var query: String?
    var search_results: [SearchHit]?
}

struct SearchHit: Codable, Identifiable, Hashable {
    var id: String { "\(project_id ?? "")-\(space_id ?? asset_id ?? UUID().uuidString)" }
    var project_id: String?
    var space_id: String?
    var asset_id: String?
    var label: String?
    var snippet: String?
}

struct RagSearchResponse: Codable {
    var status: String?
    var query: String?
    var master_nodes: [RagMasterNode]?
    var retrieved_entries: [JSONValue]?
    var search_results: [SearchHit]?
}

struct RagMasterNode: Codable, Identifiable, Hashable {
    var id: String
    var label: String?
    var project_id: String?
    var space_id: String?
}

struct PagePresenceStatus: Codable {
    var viewer_count: Int
    var write_holder_session_id: String?
    var can_write: Bool
    var write_holder_label: String?
}

enum JSONValue: Codable, Hashable {
    case string(String)
    case number(Double)
    case bool(Bool)
    case object([String: JSONValue])
    case array([JSONValue])
    case null

    init(from decoder: Decoder) throws {
        let container = try decoder.singleValueContainer()
        if container.decodeNil() { self = .null; return }
        if let value = try? container.decode(Bool.self) { self = .bool(value); return }
        if let value = try? container.decode(Double.self) { self = .number(value); return }
        if let value = try? container.decode(String.self) { self = .string(value); return }
        if let value = try? container.decode([String: JSONValue].self) { self = .object(value); return }
        if let value = try? container.decode([JSONValue].self) { self = .array(value); return }
        throw DecodingError.dataCorruptedError(in: container, debugDescription: "Unsupported JSON")
    }

    func encode(to encoder: Encoder) throws {
        var container = encoder.singleValueContainer()
        switch self {
        case .string(let value): try container.encode(value)
        case .number(let value): try container.encode(value)
        case .bool(let value): try container.encode(value)
        case .object(let value): try container.encode(value)
        case .array(let value): try container.encode(value)
        case .null: try container.encodeNil()
        }
    }
}

enum LayerSpaceKinds {
    static let hidden: Set<String> = [
        "RootSpace",
        "BackgroundSpace",
        "ObjectContainerSpace",
        "FreeAnnotationSpace",
    ]
}

extension Workspace {
    func rootLibraryNodes() -> [LibraryNode] {
        let orphans = library_nodes.values.filter { node in
            if let parentId = node.parent_id {
                return library_nodes[parentId] == nil
            }
            return true
        }
        var primary: [LibraryNode] = []
        var others: [LibraryNode] = []
        for node in orphans {
            if node.parent_id == nil, node.kind == "folder" {
                primary.append(node)
            } else {
                others.append(node)
            }
        }
        primary.sort { $0.id < $1.id }
        others.sort { $0.id < $1.id }
        if primary.count == 1 {
            return primary + others
        }
        return (primary + others).sorted { $0.id < $1.id }
    }

    func children(of node: LibraryNode) -> [LibraryNode] {
        node.child_ids.compactMap { library_nodes[$0] }
    }
}

extension Project {
    func visibleSpaces() -> [Space] {
        spaces.values.filter { !LayerSpaceKinds.hidden.contains($0.kind) }.sorted { $0.z < $1.z }
    }

    /// Spaces drawn on the canvas root layer (matches web `renderableSpaces` for non-layer kinds).
    func canvasRootSpaces() -> [Space] {
        visibleSpaces().filter { space in
            guard let parentId = space.parent_space_id, let parent = spaces[parentId] else { return true }
            return LayerSpaceKinds.hidden.contains(parent.kind)
        }
    }
}
