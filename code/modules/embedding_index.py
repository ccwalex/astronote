from __future__ import annotations

import hashlib
import os
import pickle
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from tempfile import NamedTemporaryFile
from typing import Any, Callable, Optional
from urllib.parse import parse_qsl, urlencode, urlparse, urlunparse

import numpy as np
import requests

from modules.pdf_text_extractor import extract_text_from_pdf_asset

# Retrieval-record persistence is intentionally disabled for embedding.


CHUNK_WORD_LIMIT = 6000
MIN_TAIL_WORDS = 30

_PROJECT_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_PERSIST_PATH = str(_PROJECT_ROOT / "data" / "embeddings.pkl")


def _quarantine_corrupt_file(path: Path, label: str) -> Optional[str]:
    if not path.exists():
        return None
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S")
    dest = path.with_name(f"{path.name}.{label}.{stamp}")
    try:
        path.replace(dest)
        return str(dest)
    except Exception:
        return None


def build_asset_lookup_key(project_id: str, asset_id: str) -> str:
    return f"{project_id}:{asset_id}"


def build_asset_chunk_lookup_key(project_id: str, asset_id: str, chunk_index: int) -> str:
    return f"{project_id}:{asset_id}#chunk{chunk_index}"


def split_text_for_embedding(
    text: str,
    *,
    max_words: int = CHUNK_WORD_LIMIT,
    min_tail_words: int = MIN_TAIL_WORDS,
) -> list[str]:
    text = (text or "").strip()
    if not text:
        return []

    words = text.split()
    if len(words) <= max_words:
        return [text]

    chunks: list[list[str]] = [
        words[idx : idx + max_words]
        for idx in range(0, len(words), max_words)
    ]

    if len(chunks) >= 2 and len(chunks[-1]) < min_tail_words:
        merged_tail = chunks[-2] + chunks[-1]
        split_at = len(merged_tail) // 2
        if 0 < split_at < len(merged_tail):
            chunks = chunks[:-2] + [merged_tail[:split_at], merged_tail[split_at:]]

    return [" ".join(chunk).strip() for chunk in chunks if chunk]


def _parse_iso_datetime(value: str) -> Optional[datetime]:
    text = (value or "").strip()
    if not text:
        return None
    if text.endswith("Z"):
        text = f"{text[:-1]}+00:00"
    try:
        return datetime.fromisoformat(text)
    except ValueError:
        return None


@dataclass
class _AssetEmbedPlan:
    action: str  # "skip", "remove", "embed"
    existing_keys: list[str] = field(default_factory=list)
    chunks: list[tuple[str, str, dict[str, Any]]] = field(default_factory=list)


def _tracking_requires_embed(tracking_row: Optional[dict[str, str]]) -> bool:
    if not tracking_row:
        return True

    content_checksum = (tracking_row.get("content_checksum") or "").strip()
    embedded_checksum = (tracking_row.get("embedded_checksum") or "").strip()
    if not embedded_checksum or not content_checksum:
        return True
    return content_checksum != embedded_checksum


class WorkspaceEmbeddingIndex:
    """Embeds workspace assets and maintains UMAP + nearest-neighbor index."""

    def __init__(
        self,
        endpoint: Optional[str] = None,
        api_key: Optional[str] = None,
        *,
        llm_api_key: Optional[str] = None,
        model: str = "text-embedding-3-small",
        embedding_dim: int = 512,
        timeout: int = 30,
        prompt_for_missing: bool = False,
        embed_fn: Optional[Callable[[str, str], np.ndarray]] = None,
        persist_path: str = DEFAULT_PERSIST_PATH,
    ) -> None:
        self.persist_path = persist_path
        self.model = model
        self.embedding_dim = int(embedding_dim)
        self.umap_dim = 64
        self.timeout = int(timeout)
        self._embed_fn = embed_fn

        can_prompt = bool(prompt_for_missing and os.isatty(0))

        self._remote_available = False

        if embed_fn is None:
            endpoint = (
                endpoint
                or os.getenv("AZURE_OPENAI_EMBED_ENDPOINT")
                or os.getenv("AZURE_COHERE_EMBED_ENDPOINT")
                or ""
            ).strip()
            if not endpoint and can_prompt:
                endpoint = input("Enter Azure embedding endpoint: ").strip()

            key = (
                api_key
                or llm_api_key
                or os.getenv("AZURE_OPENAI_API_KEY")
                or os.getenv("AZURE_COHERE_EMBED_KEY")
                or ""
            ).strip()
            if not key and can_prompt:
                key = input("Enter Azure embedding API key: ").strip()

            normalized_endpoint = self._normalize_foundry_project_endpoint(endpoint.rstrip("/")) if endpoint else ""
            self.endpoint = normalized_endpoint
            self.api_key = key
            self._remote_available = bool(self.endpoint and self.api_key)
        else:
            self.endpoint = ""
            self.api_key = ""

        self.raw_embeddings: dict[str, np.ndarray] = {}
        self.reduced_embeddings: dict[str, np.ndarray] = {}
        self.lookup_metadata: dict[str, dict[str, Any]] = {}

        self._lookup_order: list[str] = []
        self._raw_matrix: Optional[np.ndarray] = None
        self._reduced_matrix: Optional[np.ndarray] = None

        self._umap_model = None
        self._nn_model = None
        self._vector_scaler = None
        self._load_error: Optional[str] = None
        self._load_recovered: bool = False

        self.load_from_disk()

    @property
    def load_error(self) -> Optional[str]:
        return self._load_error

    @property
    def load_recovered(self) -> bool:
        return self._load_recovered

    @property
    def is_healthy(self) -> bool:
        return self._load_error is None and self.has_embeddings

    def _reset_index_state(self) -> None:
        self.raw_embeddings = {}
        self.reduced_embeddings = {}
        self.lookup_metadata = {}
        self._lookup_order = []
        self._raw_matrix = None
        self._reduced_matrix = None
        self._umap_model = None
        self._nn_model = None
        self._vector_scaler = None

    def _coerce_embedding_vector(self, value: Any) -> Optional[np.ndarray]:
        try:
            vector = np.asarray(value, dtype=float).reshape(-1)
        except Exception:
            return None
        if vector.size == 0 or not np.all(np.isfinite(vector)):
            return None
        return vector

    def _sanitize_loaded_payload(self) -> int:
        """Drop corrupt lookup keys; return count removed."""
        removed = 0
        clean_raw: dict[str, np.ndarray] = {}
        clean_meta: dict[str, dict[str, Any]] = {}
        clean_order: list[str] = []

        for lookup_key in self._lookup_order:
            vector = self._coerce_embedding_vector(self.raw_embeddings.get(lookup_key))
            if vector is None:
                removed += 1
                continue
            meta = self.lookup_metadata.get(lookup_key)
            if not isinstance(meta, dict):
                removed += 1
                continue
            project_id = str(meta.get("project_id") or "").strip()
            asset_id = str(meta.get("asset_id") or "").strip()
            if not project_id or not asset_id:
                removed += 1
                continue
            clean_raw[lookup_key] = vector
            clean_meta[lookup_key] = meta
            clean_order.append(lookup_key)

        self.raw_embeddings = clean_raw
        self.lookup_metadata = clean_meta
        self._lookup_order = clean_order
        self.reduced_embeddings = {
            key: value
            for key, value in self.reduced_embeddings.items()
            if key in clean_raw
        }
        return removed

    def _recover_from_corrupt_load(self, path: Path, reason: str) -> None:
        self._reset_index_state()
        self._load_error = reason
        self._load_recovered = True
        _quarantine_corrupt_file(path, "corrupt")

    def save_to_disk(self) -> None:
        if not self.persist_path:
            return
        path = Path(self.persist_path)
        path.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "raw_embeddings": self.raw_embeddings,
            "reduced_embeddings": self.reduced_embeddings,
            "lookup_metadata": self.lookup_metadata,
            "_lookup_order": self._lookup_order,
            "_umap_model": self._umap_model,
            "_nn_model": self._nn_model,
            "_vector_scaler": self._vector_scaler,
        }
        with NamedTemporaryFile("wb", dir=str(path.parent), delete=False) as tmp:
            pickle.dump(payload, tmp)
            tmp.flush()
            os.fsync(tmp.fileno())
            tmp_path = Path(tmp.name)
        tmp_path.replace(path)

    def load_from_disk(self) -> None:
        if not self.persist_path:
            return
        path = Path(self.persist_path)
        if not path.exists():
            return

        try:
            with path.open("rb") as f:
                data = pickle.load(f)
        except Exception as exc:
            self._recover_from_corrupt_load(path, f"unreadable embedding index: {exc}")
            return

        if not isinstance(data, dict):
            self._recover_from_corrupt_load(path, "invalid embedding index payload (not a dict)")
            return

        try:
            self.raw_embeddings = data.get("raw_embeddings", {}) or {}
            self.reduced_embeddings = data.get("reduced_embeddings", {}) or {}
            self.lookup_metadata = data.get("lookup_metadata", {}) or {}
            loaded_order = data.get("_lookup_order", []) or []
            if not isinstance(loaded_order, list):
                loaded_order = []
            self._lookup_order = [str(k) for k in loaded_order if str(k) in self.raw_embeddings]

            self._umap_model = data.get("_umap_model")
            self._nn_model = data.get("_nn_model")
            self._vector_scaler = data.get("_vector_scaler")

            dropped = self._sanitize_loaded_payload()
            if dropped:
                self._load_recovered = True

            if not self._lookup_order:
                self._reset_index_state()
                if dropped:
                    self._load_error = f"dropped {dropped} corrupt embedding entries"
                return

            try:
                self._raw_matrix = np.vstack([self.raw_embeddings[key] for key in self._lookup_order])
            except Exception as exc:
                self._recover_from_corrupt_load(path, f"embedding matrix rebuild failed: {exc}")
                return

            if all(key in self.reduced_embeddings for key in self._lookup_order):
                try:
                    reduced = np.vstack([self.reduced_embeddings[key] for key in self._lookup_order])
                    reduced = self._to_fixed_dim(np.asarray(reduced, dtype=float))
                    self._reduced_matrix = reduced
                    self.reduced_embeddings = {
                        key: reduced[idx]
                        for idx, key in enumerate(self._lookup_order)
                    }
                except Exception:
                    self._refit_indexes()
            else:
                self._refit_indexes()

            if self._nn_model is None and self._lookup_order:
                self._refit_indexes()

            if not self._lookup_order or self._reduced_matrix is None:
                self._load_error = self._load_error or "embedding index partially loaded; search unavailable until re-embed"
        except Exception as exc:
            self._recover_from_corrupt_load(path, f"embedding index load failed: {exc}")

    @property
    def has_embeddings(self) -> bool:
        return bool(self._lookup_order)

    def embed_assets(
        self,
        items: list[tuple[str, str, Any]],
        *,
        n_jobs: int = 2,
    ) -> dict[tuple[str, str], bool]:
        if not items:
            return {}

        plans = [
            (item, self._plan_asset_embed(item[0], item[1], item[2]))
            for item in items
        ]

        embed_plans = [(item, plan) for item, plan in plans if plan.action == "embed"]
        if embed_plans and n_jobs > 1:
            with ThreadPoolExecutor(max_workers=n_jobs) as executor:
                computed = list(
                    executor.map(
                        lambda pair: (pair[0], self._compute_embed_vectors(pair[1])),
                        embed_plans,
                    )
                )
            plan_vectors = {item: vectors for item, vectors in computed}
        else:
            plan_vectors = {
                item: self._compute_embed_vectors(plan)
                for item, plan in embed_plans
            }

        results: dict[tuple[str, str], bool] = {}
        changed = False
        for item, plan in plans:
            project_id, asset_id, asset = item
            vectors = plan_vectors.get(item) if plan.action == "embed" else None
            applied = self._apply_asset_embed(project_id, asset_id, asset, plan, vectors)
            results[(project_id, asset_id)] = applied
            if applied:
                changed = True

        if changed:
            self._refit_indexes()
            self.save_to_disk()
        return results

    def embed_workspace(self, workspace, *, n_jobs: int = 2) -> None:
        items = [
            (project_id, asset_id, asset)
            for project_id, project in workspace.projects.items()
            for asset_id, asset in project.assets.items()
        ]
        self.embed_assets(items, n_jobs=n_jobs)

    def _tracking_row_for_asset(
        self,
        tracking_rows: dict[str, dict[str, str]],
        project_id: str,
        asset_id: str,
    ) -> Optional[dict[str, str]]:
        key = build_asset_lookup_key(project_id, asset_id)
        row = tracking_rows.get(key)
        if row is not None:
            return row
        return tracking_rows.get(asset_id)

    def _lookup_keys_for_asset(self, project_id: str, asset_id: str) -> list[str]:
        base_key = build_asset_lookup_key(project_id, asset_id)
        chunk_prefix = f"{base_key}#chunk"
        return [
            lookup_key
            for lookup_key in self._lookup_order
            if lookup_key == base_key or lookup_key.startswith(chunk_prefix)
        ]

    def _remove_lookup_key(self, lookup_key: str) -> None:
        self.raw_embeddings.pop(lookup_key, None)
        self.reduced_embeddings.pop(lookup_key, None)
        self.lookup_metadata.pop(lookup_key, None)
        self._lookup_order = [key for key in self._lookup_order if key != lookup_key]

    def _asset_id_from_lookup_key(self, lookup_key: str) -> str:
        meta = self.lookup_metadata.get(lookup_key) or {}
        asset_id = str(meta.get("asset_id") or "").strip()
        if asset_id:
            return asset_id
        base = str(lookup_key or "").split("#", 1)[0]
        if ":" in base:
            return base.split(":", 1)[1].strip()
        return base.strip()

    def remove_asset(self, project_id: str, asset_id: str) -> bool:
        asset_id = str(asset_id or "").strip()
        if not asset_id:
            return False
        clone_root = os.path.join(self._tracking_data_dir(), "workspace", "group_space_clones")
        if os.path.isdir(clone_root):
            try:
                from modules.asset_tracking import group_clone_asset_ids
                for workspace_id in os.listdir(clone_root):
                    workspace_id = str(workspace_id or "").strip()
                    if not workspace_id:
                        continue
                    dummy = type("_CloneWorkspace", (), {"id": workspace_id})()
                    if asset_id in (group_clone_asset_ids(dummy, data_dir=self._tracking_data_dir()) or set()):
                        return False
            except Exception:
                pass
        project_id = str(project_id or "").strip()
        if project_id:
            existing_keys = self._lookup_keys_for_asset(project_id, asset_id)
        else:
            existing_keys = [
                lookup_key
                for lookup_key in list(self._lookup_order)
                if self._asset_id_from_lookup_key(lookup_key) == asset_id
            ]
        if not existing_keys:
            return False
        for lookup_key in existing_keys:
            self._remove_lookup_key(lookup_key)
        self._refit_indexes()
        self.save_to_disk()
        return True

    def drop_unkept_assets(self, kept_asset_ids) -> int:
        kept = {str(item or "").strip() for item in (kept_asset_ids or set()) if str(item or "").strip()}
        to_remove = [
            lookup_key
            for lookup_key in list(self._lookup_order)
            if self._asset_id_from_lookup_key(lookup_key) not in kept
        ]
        if not to_remove:
            return 0
        for lookup_key in to_remove:
            self._remove_lookup_key(lookup_key)
        self._refit_indexes()
        self.save_to_disk()
        return len(to_remove)

    def _tracking_data_dir(self) -> str:
        if self.persist_path:
            return str(Path(self.persist_path).parent)
        return str(Path(DEFAULT_PERSIST_PATH).parent)

    def _asset_requires_reembed(self, project_id: str, asset_id: str) -> bool:
        try:
            from modules.asset_tracking import get_asset_tracking_rows
        except Exception:
            return True
        tracking_rows = get_asset_tracking_rows(data_dir=self._tracking_data_dir())
        row = self._tracking_row_for_asset(tracking_rows, project_id, asset_id)
        return _tracking_requires_embed(row)

    def _plan_asset_embed(self, project_id: str, asset_id: str, asset) -> _AssetEmbedPlan:
        text = self._asset_text_for_embedding(asset, project_id=project_id)
        existing_keys = self._lookup_keys_for_asset(project_id, asset_id)

        if existing_keys and not self._asset_requires_reembed(project_id, asset_id):
            return _AssetEmbedPlan(action="skip", existing_keys=existing_keys)

        if not text:
            return _AssetEmbedPlan(action="remove", existing_keys=existing_keys)

        text_chunks = split_text_for_embedding(text)
        if not text_chunks:
            return _AssetEmbedPlan(action="remove", existing_keys=existing_keys)

        chunk_count = len(text_chunks)
        chunks: list[tuple[str, str, dict[str, Any]]] = []
        for chunk_index, chunk_text in enumerate(text_chunks):
            if chunk_count == 1:
                lookup_key = build_asset_lookup_key(project_id, asset_id)
            else:
                lookup_key = build_asset_chunk_lookup_key(project_id, asset_id, chunk_index)
            chunks.append(
                (
                    lookup_key,
                    chunk_text,
                    {
                        "project_id": project_id,
                        "asset_id": asset_id,
                        "kind": asset.kind,
                        "filename": asset.filename,
                        "chunk_index": chunk_index,
                        "chunk_count": chunk_count,
                        "chunk_word_count": len(chunk_text.split()),
                    },
                )
            )

        return _AssetEmbedPlan(action="embed", existing_keys=existing_keys, chunks=chunks)

    def _compute_embed_vectors(
        self,
        plan: _AssetEmbedPlan,
    ) -> list[tuple[str, np.ndarray, dict[str, Any]]]:
        return [
            (
                lookup_key,
                self._embed_text(chunk_text, input_type="search_document"),
                metadata,
            )
            for lookup_key, chunk_text, metadata in plan.chunks
        ]

    def _apply_asset_embed(
        self,
        project_id: str,
        asset_id: str,
        asset,
        plan: _AssetEmbedPlan,
        vectors: Optional[list[tuple[str, np.ndarray, dict[str, Any]]]] = None,
    ) -> bool:
        if plan.action == "skip":
            return False

        if plan.action == "remove":
            if not plan.existing_keys:
                return False
            for lookup_key in plan.existing_keys:
                self._remove_lookup_key(lookup_key)
            return True

        if not vectors:
            return False

        for lookup_key in plan.existing_keys:
            self._remove_lookup_key(lookup_key)

        for lookup_key, vector, metadata in vectors:
            self.raw_embeddings[lookup_key] = vector
            self.lookup_metadata[lookup_key] = metadata
            self._lookup_order.append(lookup_key)

        self._record_asset_embedded(project_id, asset_id, asset)
        return True

    def embed_asset(self, project_id: str, asset_id: str, asset) -> bool:
        plan = self._plan_asset_embed(project_id, asset_id, asset)
        vectors = self._compute_embed_vectors(plan) if plan.action == "embed" else None
        applied = self._apply_asset_embed(project_id, asset_id, asset, plan, vectors)
        if applied:
            self._refit_indexes()
            self.save_to_disk()
        return applied

    def _record_asset_embedded(self, project_id: str, asset_id: str, asset) -> None:
        try:
            from datetime import datetime, timezone

            from modules.asset_tracking import compute_asset_checksum, update_asset_tracking
            from modules.embedding_state import mark_embedding_up_to_date

            checksum = compute_asset_checksum(asset)
            data_dir = self._tracking_data_dir()
            update_asset_tracking(
                asset_id=asset_id,
                project_id=project_id,
                filename=getattr(asset, "filename", None),
                last_embed_time=datetime.now(timezone.utc).isoformat(),
                content_checksum=checksum,
                embedded_checksum=checksum,
                data_dir=data_dir,
            )
            mark_embedding_up_to_date(
                asset_id=asset_id,
                project_id=project_id,
                content_checksum=checksum,
                data_dir=data_dir,
            )
        except Exception:
            return

    def build_neighbor_matrix(self, max_neighbors: int = 5) -> dict[str, list[dict[str, Any]]]:
        if max_neighbors <= 0 or not self._lookup_order or self._reduced_matrix is None:
            return {}

        max_neighbors = min(max_neighbors, len(self._lookup_order))
        matrix: dict[str, list[dict[str, Any]]] = {}

        try:
            for lookup_key in self._lookup_order:
                query_vec = self.reduced_embeddings.get(lookup_key)
                if query_vec is None:
                    continue

                neighbors = self._kneighbors(query_vec, max_neighbors)
                payload = []
                for candidate_key, distance in neighbors:
                    if candidate_key == lookup_key:
                        continue
                    payload.append(
                        {
                            "lookup_key": candidate_key,
                            "distance": float(distance),
                            "score": float(1.0 - distance),
                            "metadata": self.lookup_metadata.get(candidate_key, {}),
                        }
                    )
                matrix[lookup_key] = payload
        except Exception:
            return {}

        return matrix

    def search_query(self, query: str, max_results: int = 10) -> list[dict[str, Any]]:
        query = query.strip()
        if not query or max_results <= 0 or not self._lookup_order or self._reduced_matrix is None:
            return []

        try:
            raw = self._embed_text(query, input_type="search_query")
            reduced = self._reduce_query(raw)
            neighbors = self._kneighbors(reduced, min(max_results, len(self._lookup_order)))
            return [
                {
                    "lookup_key": lookup_key,
                    "distance": float(distance),
                    "score": float(1.0 - distance),
                    "metadata": self.lookup_metadata.get(lookup_key, {}),
                }
                for lookup_key, distance in neighbors
                if lookup_key in self.lookup_metadata
            ]
        except Exception:
            return []

    def _asset_text_for_embedding(self, asset, project_id: Optional[str] = None) -> Optional[str]:
        if asset.kind == "image":
            return None

        if asset.kind == "pdf":
            try:
                extracted = (
                    extract_text_from_pdf_asset(asset, project_id=project_id, use_cache=True) or ""
                ).strip()
            except Exception:
                extracted = ""
            return extracted or None

        chunks = []
        if asset.filename:
            chunks.append(asset.filename)
        if asset.kind:
            chunks.append(asset.kind)
        if isinstance(asset.content, str) and asset.content.strip():
            chunks.append(asset.content)

        text = "\n".join(chunks).strip()
        return text or None

    def _embed_text(self, text: str, *, input_type: str) -> np.ndarray:
        if self._embed_fn is not None:
            vector = np.asarray(self._embed_fn(text, input_type), dtype=float)
            return self._normalize_vector(vector)

        if not self._remote_available:
            return self._fallback_embedding(text, input_type=input_type)

        url = self._embedding_url()
        headers = self._embedding_headers()

        payload_candidates: list[dict[str, Any]] = [
            {"input": text, "model": self.model},
            {"input": [text], "model": self.model},
            {"input": text},
            {"input": [text]},
        ]

        for payload in payload_candidates:
            try:
                response = requests.post(url, json=payload, headers=headers, timeout=self.timeout)
                response.raise_for_status()
                data = response.json()
            except Exception:
                continue

            vector = self._extract_embedding_vector(data)
            if vector is not None:
                return self._normalize_vector(np.asarray(vector, dtype=float))

        return self._fallback_embedding(text, input_type=input_type)

    def _embedding_headers(self) -> dict[str, str]:
        lowered = (self.endpoint or "").lower()
        if "/openai/v1" in lowered or self._is_project_endpoint(self.endpoint):
            return {
                "Content-Type": "application/json",
                "api-key": self.api_key,
                "Authorization": f"Bearer {self.api_key}",
            }

        return {
            "Content-Type": "application/json",
            "Authorization": self.api_key,
            "api-key": self.api_key,
        }

    def _embedding_url(self) -> str:
        endpoint = (self.endpoint or "").rstrip("/")
        if not endpoint:
            return endpoint

        lowered = endpoint.lower()
        if "/openai/v1" in lowered:
            if endpoint.endswith("/embeddings"):
                return endpoint
            return f"{endpoint}/embeddings"

        if self._is_project_endpoint(endpoint):
            if endpoint.endswith("/models/embeddings"):
                return self._ensure_api_version(endpoint)
            if endpoint.endswith("/models"):
                return self._ensure_api_version(f"{endpoint}/embeddings")
            if endpoint.endswith("/embeddings"):
                return self._ensure_api_version(endpoint)
            return self._ensure_api_version(f"{endpoint}/models/embeddings")

        return endpoint

    def _extract_embedding_vector(self, data: Any) -> Optional[list[float]]:
        if not isinstance(data, dict):
            return None

        if isinstance(data.get("data"), list) and data["data"]:
            first = data["data"][0]
            if isinstance(first, dict) and isinstance(first.get("embedding"), list):
                return first["embedding"]

        if isinstance(data.get("embeddings"), list) and data["embeddings"]:
            first = data["embeddings"][0]
            if isinstance(first, list):
                return first
            if isinstance(first, dict) and isinstance(first.get("embedding"), list):
                return first["embedding"]

        if isinstance(data.get("embedding"), list):
            return data["embedding"]

        return None

    def _normalize_foundry_project_endpoint(self, endpoint: str) -> str:
        raw = (endpoint or "").strip().rstrip("/")
        if not raw:
            return ""

        parsed = urlparse(raw if "://" in raw else f"https://{raw}")
        if not parsed.netloc:
            return raw

        scheme = parsed.scheme or "https"
        host = parsed.netloc

        path = (parsed.path or "").rstrip("/")

        for suffix in ("/chat/completions", "/responses", "/embeddings", "/models/embeddings"):
            if path.endswith(suffix):
                path = path[: -len(suffix)]

        if "/openai/v1" in path:
            prefix = path.split("/openai/v1", 1)[0]
            normalized_path = f"{prefix}/openai/v1"
        elif "/api/projects/" in path:
            prefix = path.split("/api/projects/", 1)[0]
            normalized_path = f"{prefix}/openai/v1"
        elif path.startswith("/openai/deployments") or path in {"", "/", "/openai"}:
            normalized_path = "/openai/v1"
        else:
            normalized_path = "/openai/v1"

        normalized = urlunparse(
            parsed._replace(
                scheme=scheme,
                netloc=host,
                path=normalized_path,
                params="",
                query="",
                fragment="",
            )
        )
        return normalized.rstrip("/")

    def _is_project_endpoint(self, endpoint: str) -> bool:
        lowered = (endpoint or "").lower()
        return "/api/projects/" in lowered or "services.ai.azure.com" in lowered

    def _ensure_api_version(self, url: str, api_version: str = "2024-05-01-preview") -> str:
        parsed = urlparse(url)
        query_pairs = parse_qsl(parsed.query, keep_blank_values=True)
        has_api_version = any(key == "api-version" for key, _ in query_pairs)
        if has_api_version:
            return url

        query_pairs.append(("api-version", api_version))
        new_query = urlencode(query_pairs)
        return urlunparse(parsed._replace(query=new_query))

    def _fallback_embedding(self, text: str, *, input_type: str) -> np.ndarray:
        dim = max(1, self.embedding_dim)
        vector = np.zeros(dim, dtype=float)

        seed = hashlib.sha256(f"{input_type}\n{text}".encode("utf-8")).digest()
        for idx, value in enumerate(seed):
            vector[idx % dim] += (float(value) - 127.5) / 127.5

        for token in text.lower().split():
            digest = hashlib.sha256(token.encode("utf-8")).digest()
            index = digest[0] % dim
            sign = 1.0 if (digest[1] % 2 == 0) else -1.0
            vector[index] += sign

        if not np.any(vector):
            vector[0] = 1.0

        return self._normalize_vector(vector)

    def _normalize_vector(self, vector: np.ndarray) -> np.ndarray:
        flat = np.asarray(vector, dtype=float).reshape(-1)
        if flat.size == 0:
            raise ValueError("Embedding vector is empty.")
        return flat

    def _to_fixed_dim(self, matrix: np.ndarray) -> np.ndarray:
        rows, cols = matrix.shape
        target_dim = max(1, int(self.umap_dim))
        if cols == target_dim:
            return matrix
        if cols > target_dim:
            return matrix[:, : target_dim]

        padded = np.zeros((rows, target_dim), dtype=float)
        padded[:, :cols] = matrix
        return padded

    def _refit_indexes(self) -> None:
        if not self._lookup_order:
            self._raw_matrix = None
            self._reduced_matrix = None
            self._umap_model = None
            self._nn_model = None
            self.reduced_embeddings = {}
            return

        self._raw_matrix = np.vstack([self.raw_embeddings[key] for key in self._lookup_order])

        reduced = self._raw_matrix
        self._umap_model = None

        if self._raw_matrix.shape[0] >= 3:
            try:
                import umap  # type: ignore

                n_components = max(2, min(self.umap_dim, self._raw_matrix.shape[1], self._raw_matrix.shape[0] - 1))
                n_neighbors = max(2, min(15, self._raw_matrix.shape[0] - 1))
                reducer = umap.UMAP(
                    n_components=n_components,
                    n_neighbors=n_neighbors,
                    metric="cosine",
                )
                reduced = reducer.fit_transform(self._raw_matrix)
                self._umap_model = reducer
            except Exception:
                reduced = self._raw_matrix
                self._umap_model = None

        reduced = self._to_fixed_dim(np.asarray(reduced, dtype=float))
        self._reduced_matrix = reduced

        self.reduced_embeddings = {
            key: reduced[idx]
            for idx, key in enumerate(self._lookup_order)
        }

        try:
            from sklearn.neighbors import NearestNeighbors  # type: ignore

            nn = NearestNeighbors(metric="cosine")
            nn.fit(reduced)
            self._nn_model = nn
        except Exception:
            self._nn_model = None

    def _reduce_query(self, raw_vector: np.ndarray) -> np.ndarray:
        vector = np.asarray(raw_vector, dtype=float).reshape(1, -1)
        if self._umap_model is not None:
            try:
                reduced = self._umap_model.transform(vector)
            except Exception:
                reduced = vector
        else:
            reduced = vector

        reduced = self._to_fixed_dim(np.asarray(reduced, dtype=float))
        return reduced.reshape(-1)

    def _kneighbors(self, vector: np.ndarray, k: int) -> list[tuple[str, float]]:
        if self._reduced_matrix is None or not self._lookup_order or k <= 0:
            return []

        query = np.asarray(vector, dtype=float).reshape(1, -1)

        if self._nn_model is not None:
            distances, indices = self._nn_model.kneighbors(query, n_neighbors=min(k, len(self._lookup_order)))
            return [
                (self._lookup_order[int(i)], float(d))
                for d, i in zip(distances[0], indices[0])
            ]

        query_vec = query[0]
        q_norm = float(np.linalg.norm(query_vec))
        if q_norm == 0.0:
            q_norm = 1.0

        rows = []
        for idx, row in enumerate(self._reduced_matrix):
            r_norm = float(np.linalg.norm(row))
            if r_norm == 0.0:
                distance = 1.0
            else:
                cosine_similarity = float(np.dot(query_vec, row) / (q_norm * r_norm))
                distance = float(1.0 - cosine_similarity)
            rows.append((self._lookup_order[idx], distance))

        rows.sort(key=lambda item: item[1])
        return rows[:k]
