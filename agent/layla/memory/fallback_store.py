"""Compiler-free vector store fallback (REQ-72, Friend-Ready A3).

`chromadb` needs `chroma-hnswlib`, a C++ extension that will not build on a machine
without a toolchain (the friend's CPU laptop). This is a drop-in replacement: a
SQLite-backed collection that implements the subset of the chromadb Collection API
`vector_store.py` actually uses — ``add / upsert / update / get / query / delete /
count / peek`` with ``include``, ``where`` and ``n_results``.

Search: when the **sqlite-vec** extension is available (a small prebuilt wheel, no
toolchain), the no-filter ``query`` path uses its SIMD cosine KNN inside SQLite;
otherwise (or for ``where``-filtered queries) it falls back to NumPy brute force.
Both are exact at single-user memory scale (thousands of vectors). So Layla's
memory/RAG works on a compiler-less box instead of silently turning off.

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

try:  # optional SIMD cosine KNN; NumPy brute force serves as the fallback when absent
    import sqlite_vec as _sqlite_vec
except Exception:  # pragma: no cover - import guard
    _sqlite_vec = None


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
    """A SQLite (+ optional sqlite-vec) stand-in for a chromadb Collection."""

    def __init__(self, name: str, path: str | Path):
        self.name = name
        self._lock = threading.RLock()
        p = Path(path)
        self._path = p
        p.parent.mkdir(parents=True, exist_ok=True)
        self._db = sqlite3.connect(str(p), check_same_thread=False)
        # Reclaim space over time: without this the file only ever grew — deletes left free
        # pages forever (audit H3). Must be set before the first table is created to take on a
        # NEW db; existing files pick it up on the next full VACUUM (see vacuum()).
        try:
            self._db.execute("PRAGMA auto_vacuum=INCREMENTAL")
        except Exception:
            pass
        # Optional sqlite-vec acceleration for the no-filter query path. Prebuilt
        # wheel → keeps the compiler-free property; degrades to NumPy on any error.
        self._vec_ok = False
        self._vec_dim: int | None = None
        if _sqlite_vec is not None:
            try:
                self._db.enable_load_extension(True)
                _sqlite_vec.load(self._db)
                self._db.enable_load_extension(False)
                self._vec_ok = True
            except Exception:
                self._vec_ok = False
        self._db.execute(
            "CREATE TABLE IF NOT EXISTS vectors ("
            "id TEXT PRIMARY KEY, embedding BLOB, metadata TEXT, document TEXT)"
        )
        self._db.commit()
        if self._vec_ok:
            try:
                self._rebuild_vec_index()
            except Exception:
                self._vec_ok = False

    def vacuum(self) -> bool:
        """Reclaim free pages so the file tracks current data instead of its high-water mark.
        A full VACUUM also applies the auto_vacuum=INCREMENTAL setting to a pre-existing db.
        Best-effort; returns True if it ran."""
        try:
            with self._lock:
                self._db.execute("VACUUM")
                self._db.commit()
            return True
        except Exception:
            return False

    # ---- sqlite-vec index (optional; mirrors the vectors table) ----
    def _create_vec_index(self, dim: int) -> None:
        self._db.execute("DROP TABLE IF EXISTS vec_idx")
        self._db.execute(
            "CREATE VIRTUAL TABLE vec_idx USING vec0("
            f"item_id TEXT PRIMARY KEY, embedding float[{int(dim)}] distance_metric=cosine)"
        )
        self._vec_dim = int(dim)

    def _rebuild_vec_index(self) -> None:
        """Repopulate vec_idx from the vectors table (e.g. after reopening the DB)."""
        rows = self._db.execute("SELECT id, embedding FROM vectors").fetchall()
        if not rows:
            return
        dim = int(np.frombuffer(rows[0][1], dtype="float32").size)
        self._create_vec_index(dim)
        for rid, emb in rows:
            v = np.frombuffer(emb, dtype="float32")
            if v.size == self._vec_dim:
                self._db.execute(
                    "INSERT INTO vec_idx(item_id, embedding) VALUES (?, ?)",
                    (rid, _sqlite_vec.serialize_float32(v)),
                )
        self._db.commit()

    def _vec_put(self, item_id: str, vec: np.ndarray) -> None:
        """Upsert one vector into vec_idx (vec0 has no INSERT OR REPLACE → delete+insert).
        Creates or (on an embedder dim change) rebuilds the index as needed."""
        if not self._vec_ok:
            return
        try:
            v = _f32(vec)
            if self._vec_dim is None:
                self._create_vec_index(v.size)
            elif v.size != self._vec_dim:
                # Embedding dimensionality changed (e.g. embedder swap) — rebuild the
                # index at the new dim from the already-updated vectors table.
                self._create_vec_index(v.size)
                for rid, emb in self._db.execute("SELECT id, embedding FROM vectors").fetchall():
                    vv = np.frombuffer(emb, dtype="float32")
                    if rid != item_id and vv.size == self._vec_dim:
                        self._db.execute(
                            "INSERT INTO vec_idx(item_id, embedding) VALUES (?, ?)",
                            (rid, _sqlite_vec.serialize_float32(vv)),
                        )
            self._db.execute("DELETE FROM vec_idx WHERE item_id=?", (item_id,))
            self._db.execute(
                "INSERT INTO vec_idx(item_id, embedding) VALUES (?, ?)",
                (item_id, _sqlite_vec.serialize_float32(v)),
            )
        except Exception:
            self._vec_ok = False  # never let the index break a write

    def _vec_del(self, ids) -> None:
        if not self._vec_ok:
            return
        try:
            self._db.executemany("DELETE FROM vec_idx WHERE item_id=?", [(i,) for i in ids])
        except Exception:
            self._vec_ok = False

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
                vec = _f32(embeddings[i])
                meta = metadatas[i] or {}
                doc = documents[i] if documents[i] is not None else meta.get("content")
                self._db.execute(
                    "INSERT INTO vectors (id, embedding, metadata, document) VALUES (?,?,?,?) "
                    "ON CONFLICT(id) DO UPDATE SET embedding=excluded.embedding, "
                    "metadata=excluded.metadata, document=excluded.document",
                    (_id, vec.tobytes(), json.dumps(meta), doc),
                )
                self._vec_put(_id, vec)
            self._db.commit()

    def update(self, ids, metadatas=None, embeddings=None, documents=None):
        with self._lock:
            for i, _id in enumerate(ids):
                if metadatas is not None:
                    self._db.execute("UPDATE vectors SET metadata=? WHERE id=?",
                                     (json.dumps(metadatas[i] or {}), _id))
                if embeddings is not None:
                    _v = _f32(embeddings[i])
                    self._db.execute("UPDATE vectors SET embedding=? WHERE id=?",
                                     (_v.tobytes(), _id))
                    self._vec_put(_id, _v)
                if documents is not None:
                    self._db.execute("UPDATE vectors SET document=? WHERE id=?", (documents[i], _id))
            self._db.commit()

    def delete(self, ids=None, where=None):
        with self._lock:
            if ids:
                self._db.executemany("DELETE FROM vectors WHERE id=?", [(i,) for i in ids])
                self._vec_del(ids)
            elif where:
                _wids = self._ids_where(where)
                for rid in _wids:
                    self._db.execute("DELETE FROM vectors WHERE id=?", (rid,))
                self._vec_del(_wids)
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

    def _vec_query(self, query_embeddings, n_results):
        """sqlite-vec SIMD cosine KNN (no metadata filter). Chroma-shaped result."""
        res: dict[str, list] = {"ids": [], "distances": [], "metadatas": [], "documents": []}
        with self._lock:
            for q in query_embeddings:
                hits = self._db.execute(
                    "SELECT item_id, distance FROM vec_idx WHERE embedding MATCH ? "
                    "ORDER BY distance LIMIT ?",
                    (_sqlite_vec.serialize_float32(_f32(q)), int(n_results)),
                ).fetchall()
                ids = [h[0] for h in hits]
                dists = [float(h[1]) for h in hits]
                metas, docs = [], []
                for rid in ids:
                    row = self._db.execute(
                        "SELECT metadata, document FROM vectors WHERE id=?", (rid,)
                    ).fetchone()
                    metas.append(json.loads((row[0] if row else None) or "{}"))
                    docs.append(row[1] if row else None)
                res["ids"].append(ids)
                res["distances"].append(dists)
                res["metadatas"].append(metas)
                res["documents"].append(docs)
        return res

    def query(self, query_embeddings=None, n_results=5, where=None, include=None):
        include = include or ["metadatas", "distances"]
        # Fast path: sqlite-vec SIMD cosine KNN when available and no metadata filter.
        if self._vec_ok and not where and self._vec_dim is not None:
            try:
                return self._vec_query(query_embeddings or [], int(n_results))
            except Exception:
                self._vec_ok = False  # fall through to brute force on any error
        with self._lock:
            rows = self._all_rows()
        if where:
            rows = [r for r in rows if self._match(json.loads(r[2] or "{}"), where)]
        res: dict[str, list] = {"ids": [], "distances": [], "metadatas": [], "documents": []}
        # Vectors may have been written by different embedder models over the store's
        # lifetime, so buffer lengths can differ. np.stack() requires uniform shape, so keep
        # only rows whose dimension matches the query (mixed dims => skip, never crash).
        q_list = list(query_embeddings or [])
        target_dim = None
        for q in q_list:
            try:
                target_dim = int(_f32(q).shape[0])
                break
            except Exception:
                continue
        if target_dim is None and rows:
            try:
                target_dim = int(np.frombuffer(rows[0][1], dtype="float32").shape[0])
            except Exception:
                target_dim = None
        _vecs: list = []
        _kept: list = []
        for r in rows:
            v = np.frombuffer(r[1], dtype="float32")
            if target_dim is not None and int(v.shape[0]) != target_dim:
                continue
            _vecs.append(v)
            _kept.append(r)
        rows = _kept
        mat = np.stack(_vecs) if _vecs else np.empty((0, 0), dtype="float32")
        for q in q_list:
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


def vacuum_open_fallback_stores(min_bytes: int = 20_000_000) -> int:
    """VACUUM any open fallback store whose file exceeds min_bytes (self-gating so we only pay
    the cost when there's meaningful reclaimable space). Called from the daily maintenance job.
    Returns the number vacuumed."""
    done = 0
    with _factory_lock:
        cols = list(_collections.values())
    for col in cols:
        try:
            p = getattr(col, "_path", None)
            if p and p.exists() and int(p.stat().st_size) >= min_bytes:
                if col.vacuum():
                    done += 1
        except Exception:
            pass
    return done


def reset_fallback_cache() -> None:
    """Test helper: drop the in-process collection cache."""
    with _factory_lock:
        _collections.clear()
