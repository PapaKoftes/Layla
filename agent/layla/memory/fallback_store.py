"""Compiler-free vector store fallback (REQ-72, Friend-Ready A3).

`chromadb` needs `chroma-hnswlib`, a C++ extension that will not build on a machine
without a toolchain (the friend's CPU laptop). This is a drop-in replacement: a
SQLite-backed collection with NumPy brute-force cosine search that implements the
subset of the chromadb Collection API `vector_store.py` actually uses —
``add / upsert / update / get / query / delete / count / peek`` with ``include``,
``where`` and ``n_results``. Brute force is fine at single-user memory scale
(thousands of vectors), and it needs only stdlib + numpy (which ships wheels
everywhere). So Layla's memory/RAG works on a compiler-less box instead of silently
turning off.

Distances match Chroma's cosine space: ``distance = 1 - cosine_similarity`` (so 0 is
identical, nearest-first). ``query`` returns the Chroma-style nested-list shape
(one inner list per query embedding).
"""
from __future__ import annotations

import json
import sqlite3
import threading
from pathlib import Path
from typing import Any

import numpy as np


def _f32(v: Any) -> np.ndarray:
    return np.asarray(v, dtype="float32").ravel()


def _cosine_distances(mat: np.ndarray, q: np.ndarray) -> np.ndarray:
    """Row-wise cosine distance (1 - sim) between each row of mat and q."""
    if mat.size == 0:
        return np.empty((0,), dtype="float32")
    qn = q / (float(np.linalg.norm(q)) + 1e-8)
    mn = mat / (np.linalg.norm(mat, axis=1, keepdims=True) + 1e-8)
    return (1.0 - (mn @ qn)).astype("float32")


class FallbackCollection:
    """A SQLite + NumPy stand-in for a chromadb Collection (the methods Layla uses)."""

    def __init__(self, name: str, path: str | Path):
        self.name = name
        self._lock = threading.RLock()
        p = Path(path)
        p.parent.mkdir(parents=True, exist_ok=True)
        self._db = sqlite3.connect(str(p), check_same_thread=False)
        self._db.execute(
            "CREATE TABLE IF NOT EXISTS vectors ("
            "id TEXT PRIMARY KEY, embedding BLOB, metadata TEXT, document TEXT)"
        )
        self._db.commit()

    # ---- writes ----
    def add(self, ids, embeddings, metadatas=None, documents=None):
        self._upsert(ids, embeddings, metadatas, documents)

    def upsert(self, ids, embeddings, metadatas=None, documents=None):
        self._upsert(ids, embeddings, metadatas, documents)

    def _upsert(self, ids, embeddings, metadatas, documents):
        metadatas = metadatas or [{} for _ in ids]
        documents = documents if documents is not None else [None for _ in ids]
        with self._lock:
            for i, _id in enumerate(ids):
                emb = _f32(embeddings[i]).tobytes()
                meta = metadatas[i] or {}
                doc = documents[i] if documents[i] is not None else meta.get("content")
                self._db.execute(
                    "INSERT INTO vectors (id, embedding, metadata, document) VALUES (?,?,?,?) "
                    "ON CONFLICT(id) DO UPDATE SET embedding=excluded.embedding, "
                    "metadata=excluded.metadata, document=excluded.document",
                    (_id, emb, json.dumps(meta), doc),
                )
            self._db.commit()

    def update(self, ids, metadatas=None, embeddings=None, documents=None):
        with self._lock:
            for i, _id in enumerate(ids):
                if metadatas is not None:
                    self._db.execute("UPDATE vectors SET metadata=? WHERE id=?",
                                     (json.dumps(metadatas[i] or {}), _id))
                if embeddings is not None:
                    self._db.execute("UPDATE vectors SET embedding=? WHERE id=?",
                                     (_f32(embeddings[i]).tobytes(), _id))
                if documents is not None:
                    self._db.execute("UPDATE vectors SET document=? WHERE id=?", (documents[i], _id))
            self._db.commit()

    def delete(self, ids=None, where=None):
        with self._lock:
            if ids:
                self._db.executemany("DELETE FROM vectors WHERE id=?", [(i,) for i in ids])
            elif where:
                for rid in self._ids_where(where):
                    self._db.execute("DELETE FROM vectors WHERE id=?", (rid,))
            self._db.commit()

    # ---- reads ----
    def count(self) -> int:
        with self._lock:
            return int(self._db.execute("SELECT COUNT(*) FROM vectors").fetchone()[0])

    @staticmethod
    def _match(meta: dict, where: dict | None) -> bool:
        if not where:
            return True
        for key, cond in where.items():
            val = meta.get(key)
            if isinstance(cond, dict):
                for op, target in cond.items():
                    if op == "$eq" and val != target:
                        return False
                    if op == "$ne" and val == target:
                        return False
                    if op == "$in" and val not in target:
                        return False
            elif val != cond:
                return False
        return True

    def _all_rows(self):
        return self._db.execute(
            "SELECT id, embedding, metadata, document FROM vectors").fetchall()

    def _ids_where(self, where):
        return [r[0] for r in self._all_rows() if self._match(json.loads(r[2] or "{}"), where)]

    def get(self, ids=None, where=None, include=None, limit=None):
        include = include or ["metadatas", "documents"]
        with self._lock:
            if ids:
                rows = []
                for i in ids:
                    r = self._db.execute(
                        "SELECT id, embedding, metadata, document FROM vectors WHERE id=?", (i,)
                    ).fetchone()
                    if r:
                        rows.append(r)
            else:
                rows = self._all_rows()
                if where:
                    rows = [r for r in rows if self._match(json.loads(r[2] or "{}"), where)]
                if limit:
                    rows = rows[: int(limit)]
        return self._format(rows, include)

    def peek(self, limit=10):
        return self.get(limit=limit, include=["metadatas", "embeddings", "documents"])

    @staticmethod
    def _format(rows, include):
        out: dict[str, Any] = {"ids": [r[0] for r in rows]}
        if "embeddings" in include:
            out["embeddings"] = [np.frombuffer(r[1], dtype="float32").tolist() for r in rows]
        if "metadatas" in include:
            out["metadatas"] = [json.loads(r[2] or "{}") for r in rows]
        if "documents" in include:
            out["documents"] = [r[3] for r in rows]
        return out

    def query(self, query_embeddings=None, n_results=5, where=None, include=None):
        include = include or ["metadatas", "distances"]
        with self._lock:
            rows = self._all_rows()
        if where:
            rows = [r for r in rows if self._match(json.loads(r[2] or "{}"), where)]
        res: dict[str, list] = {"ids": [], "distances": [], "metadatas": [], "documents": []}
        mat = (np.stack([np.frombuffer(r[1], dtype="float32") for r in rows])
               if rows else np.empty((0, 0), dtype="float32"))
        for q in (query_embeddings or []):
            if not rows:
                for key in res:
                    res[key].append([])
                continue
            dists = _cosine_distances(mat, _f32(q))
            order = list(np.argsort(dists)[: int(n_results)])
            res["ids"].append([rows[i][0] for i in order])
            res["distances"].append([float(dists[i]) for i in order])
            res["metadatas"].append([json.loads(rows[i][2] or "{}") for i in order])
            res["documents"].append([rows[i][3] for i in order])
        return res


_collections: dict[str, FallbackCollection] = {}
_factory_lock = threading.RLock()


def get_fallback_collection(name: str, base_dir: str | Path) -> FallbackCollection:
    """Process-wide singleton fallback collection persisted under base_dir."""
    with _factory_lock:
        if name not in _collections:
            _collections[name] = FallbackCollection(name, Path(base_dir) / f"fallback_{name}.sqlite")
        return _collections[name]


def reset_fallback_cache() -> None:
    """Test helper: drop the in-process collection cache."""
    with _factory_lock:
        _collections.clear()
