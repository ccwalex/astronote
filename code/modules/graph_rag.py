import heapq
from typing import Dict, List, Optional, Set

from modules.workspace import Workspace

DEFAULT_SPACE_EDGE_COST = 1.0
DEFAULT_PAGE_HOP_COST = 5.0
DEFAULT_FOLDER_HOP_COST = 10.0
DEFAULT_MAX_DISTANCE = 10.0


def build_workspace_graph(
    workspace: Workspace,
    *,
    space_edge_cost: float = DEFAULT_SPACE_EDGE_COST,
    page_hop_cost: float = DEFAULT_PAGE_HOP_COST,
    folder_hop_cost: float = DEFAULT_FOLDER_HOP_COST,
    allowed_project_ids: Optional[Set[str]] = None,
    allowed_library_node_ids: Optional[Set[str]] = None,
) -> Dict[str, Dict[str, float]]:
    """Build an undirected weighted graph over canvas spaces and library nodes.

    Edge costs:
    - Type 1: parent/child Space edges on the canvas tree cost ``space_edge_cost``.
    - Type 2: two pages in the same folder are connected through the folder using
      ``page_hop_cost / 2`` on each page-folder edge, so the page-to-page cost is
      exactly ``page_hop_cost``.
    - Type 3: library folder parent/child edges cost ``folder_hop_cost``.
    - A page node connects to its project's root space at cost 0.
    """
    graph: Dict[str, Dict[str, float]] = {}

    def add_edge(u: str, v: str, w: float) -> None:
        if u not in graph:
            graph[u] = {}
        if v not in graph:
            graph[v] = {}
        prev_uv = graph[u].get(v)
        if prev_uv is None or w < prev_uv:
            graph[u][v] = w
        prev_vu = graph[v].get(u)
        if prev_vu is None or w < prev_vu:
            graph[v][u] = w

    def node_allowed(node_id: str) -> bool:
        return allowed_library_node_ids is None or node_id in allowed_library_node_ids

    def project_allowed(project_id: str) -> bool:
        return allowed_project_ids is None or project_id in allowed_project_ids

    if workspace.library_nodes:
        for node_id, node in workspace.library_nodes.items():
            if not node_allowed(node_id):
                continue
            u = f"node:{node_id}"
            if u not in graph:
                graph[u] = {}

            parent_id = node.parent_id
            if parent_id and node_allowed(parent_id) and parent_id in workspace.library_nodes:
                parent = workspace.library_nodes[parent_id]
                p = f"node:{parent_id}"
                if node.kind == "page":
                    add_edge(u, p, float(page_hop_cost) / 2.0)
                elif node.kind == "folder" and parent.kind == "folder":
                    add_edge(u, p, float(folder_hop_cost))
                elif node.kind == "folder":
                    add_edge(u, p, float(folder_hop_cost))

            if node.kind == "page" and node.target_project_id and project_allowed(node.target_project_id):
                project = workspace.projects.get(node.target_project_id) if workspace.projects else None
                if project and project.root_space_id:
                    add_edge(u, f"space:{project.root_space_id}", 0.0)

    if workspace.projects:
        for project_id, project in workspace.projects.items():
            if not project_allowed(project_id):
                continue
            if not project.spaces:
                continue
            for space_id, space in project.spaces.items():
                u = f"space:{space_id}"
                if u not in graph:
                    graph[u] = {}
                parent_id = space.parent_space_id
                if parent_id and parent_id in project.spaces:
                    add_edge(u, f"space:{parent_id}", float(space_edge_cost))
                for child_id in space.child_space_ids or []:
                    if child_id in project.spaces:
                        add_edge(u, f"space:{child_id}", float(space_edge_cost))

    return graph


def calculate_graph_distance(
    workspace: Workspace,
    start_space_id: str,
    target_space_id: str,
    *,
    space_edge_cost: float = DEFAULT_SPACE_EDGE_COST,
    page_hop_cost: float = DEFAULT_PAGE_HOP_COST,
    folder_hop_cost: float = DEFAULT_FOLDER_HOP_COST,
    allowed_project_ids: Optional[Set[str]] = None,
    allowed_library_node_ids: Optional[Set[str]] = None,
) -> float:
    """Shortest weighted path cost between two canvas spaces."""
    graph = build_workspace_graph(
        workspace,
        space_edge_cost=space_edge_cost,
        page_hop_cost=page_hop_cost,
        folder_hop_cost=folder_hop_cost,
        allowed_project_ids=allowed_project_ids,
        allowed_library_node_ids=allowed_library_node_ids,
    )
    start_node = f"space:{start_space_id}"
    target_node = f"space:{target_space_id}"

    if start_node not in graph or target_node not in graph:
        return float("inf")

    distances = {start_node: 0.0}
    pq = [(0.0, start_node)]

    while pq:
        dist, current = heapq.heappop(pq)
        if current == target_node:
            return dist
        if dist > distances.get(current, float("inf")):
            continue
        for neighbor, weight in graph.get(current, {}).items():
            new_dist = dist + weight
            if new_dist < distances.get(neighbor, float("inf")):
                distances[neighbor] = new_dist
                heapq.heappush(pq, (new_dist, neighbor))

    return float("inf")


def retrieve_spaces_within_distance_from_starts(
    workspace: Workspace,
    start_space_ids: List[str],
    max_distance: float,
    *,
    space_edge_cost: float = DEFAULT_SPACE_EDGE_COST,
    page_hop_cost: float = DEFAULT_PAGE_HOP_COST,
    folder_hop_cost: float = DEFAULT_FOLDER_HOP_COST,
    allowed_project_ids: Optional[Set[str]] = None,
    allowed_library_node_ids: Optional[Set[str]] = None,
) -> List[str]:
    """Return space ids reachable from any start space with cost <= max_distance."""
    graph = build_workspace_graph(
        workspace,
        space_edge_cost=space_edge_cost,
        page_hop_cost=page_hop_cost,
        folder_hop_cost=folder_hop_cost,
        allowed_project_ids=allowed_project_ids,
        allowed_library_node_ids=allowed_library_node_ids,
    )

    distances: Dict[str, float] = {}
    pq: List[tuple] = []
    for space_id in start_space_ids:
        node = f"space:{space_id}"
        if node not in graph:
            continue
        if 0.0 < distances.get(node, float("inf")):
            distances[node] = 0.0
            heapq.heappush(pq, (0.0, node))

    while pq:
        dist, current = heapq.heappop(pq)
        if dist > distances.get(current, float("inf")):
            continue
        if dist > max_distance:
            continue
        for neighbor, weight in graph.get(current, {}).items():
            new_dist = dist + weight
            if new_dist <= max_distance and new_dist < distances.get(neighbor, float("inf")):
                distances[neighbor] = new_dist
                heapq.heappush(pq, (new_dist, neighbor))

    result = [
        node.split(":", 1)[1]
        for node, dist in distances.items()
        if node.startswith("space:") and dist <= max_distance
    ]
    result.sort(key=lambda space_id: (distances[f"space:{space_id}"], space_id))
    return result


def retrieve_spaces_within_distance(
    workspace: Workspace,
    start_space_id: str,
    max_distance: float,
    *,
    space_edge_cost: float = DEFAULT_SPACE_EDGE_COST,
    page_hop_cost: float = DEFAULT_PAGE_HOP_COST,
    folder_hop_cost: float = DEFAULT_FOLDER_HOP_COST,
    allowed_project_ids: Optional[Set[str]] = None,
    allowed_library_node_ids: Optional[Set[str]] = None,
) -> List[str]:
    """Find all spaces within a weighted distance budget from start_space_id."""
    return retrieve_spaces_within_distance_from_starts(
        workspace,
        [start_space_id],
        max_distance,
        space_edge_cost=space_edge_cost,
        page_hop_cost=page_hop_cost,
        folder_hop_cost=folder_hop_cost,
        allowed_project_ids=allowed_project_ids,
        allowed_library_node_ids=allowed_library_node_ids,
    )
