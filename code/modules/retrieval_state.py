from __future__ import annotations

from typing import Any


def append_query_history(*, workspace_id: str, query: str, mode: str, payload: list[dict[str, Any]], data_dir: str = "data") -> dict[str, Any]:
    return {
        "workspace_id": str(workspace_id or "").strip(),
        "query": str(query or "").strip(),
        "mode": str(mode or "").strip(),
        "result_count": len(payload or []),
        "data_dir": data_dir,
    }


def load_query_history(data_dir: str = "data", limit: int | None = None) -> list[dict[str, Any]]:
    _ = (data_dir, limit)
    return []
