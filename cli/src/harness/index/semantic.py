"""Semantic search via ChromaDB — optional vector index over code symbols.

Embeds symbol signatures and docstrings into a persistent ChromaDB
collection so agents can ask natural-language questions like "find
functions that blur images" instead of exact keyword matches.

Requires: pip install chromadb sentence-transformers
Storage:  .harness/chroma/ (gitignored, rebuilt on demand)

Default model: nomic-embed-text-v1.5 (768 dims, Apache 2.0, good code
understanding). Configurable via context.index.embedding_model in
harness.yml.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any


def _check_chromadb() -> bool:
    try:
        import chromadb  # noqa: F401
        return True
    except ImportError:
        return False


HAS_CHROMADB = _check_chromadb()

DEFAULT_MODEL = "nomic-ai/nomic-embed-text-v1.5"
CHROMA_DIR_NAME = "chroma"
COLLECTION_NAME = "code_symbols"
BATCH_SIZE = 500


def _chroma_path(harness_root: Path) -> Path:
    return harness_root / ".harness" / CHROMA_DIR_NAME


def _get_client(harness_root: Path):
    """Return a persistent ChromaDB client."""
    import chromadb
    path = _chroma_path(harness_root)
    path.mkdir(parents=True, exist_ok=True)
    return chromadb.PersistentClient(path=str(path))


def _get_embedding_function(model_name: str | None = None):
    """Build the embedding function for the given model."""
    from chromadb.utils.embedding_functions import (
        SentenceTransformerEmbeddingFunction,
    )
    model = model_name or DEFAULT_MODEL
    return SentenceTransformerEmbeddingFunction(
        model_name=model,
        trust_remote_code=True,
    )


def _get_or_create_collection(client, model_name: str | None = None):
    ef = _get_embedding_function(model_name)
    return client.get_or_create_collection(
        name=COLLECTION_NAME,
        embedding_function=ef,
        metadata={"hnsw:space": "cosine"},
    )


def _symbol_document(
    name: str,
    kind: str,
    signature: str | None,
    docstring: str | None,
    path: str,
    language: str | None,
) -> str:
    """Build the text that gets embedded for a symbol."""
    parts = [f"{kind} {name}"]
    if signature:
        parts.append(signature)
    if docstring:
        parts.append(docstring)
    parts.append(f"in {path}")
    return "\n".join(parts)


def _symbol_id(project: str, path: str, name: str, line: int) -> str:
    return f"{project}:{path}:{name}:{line}"


def build_semantic_index(
    harness_root: Path,
    project: str | None = None,
    full: bool = False,
    model_name: str | None = None,
) -> dict:
    """Build or rebuild the ChromaDB semantic index from the SQLite index.

    Reads symbols from .harness/code.db and embeds them into ChromaDB.
    Returns summary with count of documents added.
    """
    from . import db

    conn = db.connect(harness_root)
    client = _get_client(harness_root)

    if full:
        try:
            client.delete_collection(COLLECTION_NAME)
        except Exception:
            pass

    collection = _get_or_create_collection(client, model_name)

    sql = """
        SELECT s.id, s.name, s.kind, s.signature, s.docstring,
               s.line_start, s.line_end, s.visibility, s.is_export,
               f.path, f.project, f.language
        FROM symbols s
        JOIN files f ON s.file_id = f.id
    """
    params: list = []
    if project:
        sql += " WHERE f.project = ?"
        params.append(project)

    rows = conn.execute(sql, params).fetchall()
    conn.close()

    if full:
        existing_ids: set[str] = set()
    else:
        try:
            result = collection.get(include=[])
            existing_ids = set(result["ids"])
        except Exception:
            existing_ids = set()

    ids_batch: list[str] = []
    docs_batch: list[str] = []
    metas_batch: list[dict[str, Any]] = []
    added = 0

    for row in rows:
        doc_id = _symbol_id(row["project"], row["path"], row["name"], row["line_start"])

        if doc_id in existing_ids:
            continue

        document = _symbol_document(
            name=row["name"],
            kind=row["kind"],
            signature=row["signature"],
            docstring=row["docstring"],
            path=row["path"],
            language=row["language"],
        )

        metadata = {
            "project": row["project"],
            "path": row["path"],
            "language": row["language"] or "",
            "kind": row["kind"],
            "name": row["name"],
            "line_start": row["line_start"],
            "line_end": row["line_end"],
            "visibility": row["visibility"] or "",
            "is_export": bool(row["is_export"]),
        }
        if row["signature"]:
            metadata["signature"] = row["signature"][:500]

        ids_batch.append(doc_id)
        docs_batch.append(document)
        metas_batch.append(metadata)

        if len(ids_batch) >= BATCH_SIZE:
            collection.add(ids=ids_batch, documents=docs_batch, metadatas=metas_batch)
            added += len(ids_batch)
            ids_batch, docs_batch, metas_batch = [], [], []

    if ids_batch:
        collection.add(ids=ids_batch, documents=docs_batch, metadatas=metas_batch)
        added += len(ids_batch)

    total = collection.count()
    return {"added": added, "total": total}


def semantic_search(
    harness_root: Path,
    query: str,
    *,
    project: str | None = None,
    kind: str | None = None,
    n_results: int = 10,
    model_name: str | None = None,
) -> list[dict]:
    """Search the semantic index with a natural-language query.

    Returns a list of dicts with symbol info and distance score.
    """
    client = _get_client(harness_root)
    ef = _get_embedding_function(model_name)
    try:
        collection = client.get_collection(COLLECTION_NAME, embedding_function=ef)
    except Exception:
        return []

    where: dict | None = None
    conditions = []
    if project:
        conditions.append({"project": project})
    if kind:
        conditions.append({"kind": kind})
    if len(conditions) == 1:
        where = conditions[0]
    elif len(conditions) > 1:
        where = {"$and": conditions}

    results = collection.query(
        query_texts=[query],
        n_results=n_results,
        where=where,
        include=["metadatas", "distances", "documents"],
    )

    output = []
    if results["ids"] and results["ids"][0]:
        for i, doc_id in enumerate(results["ids"][0]):
            meta = results["metadatas"][0][i]
            distance = results["distances"][0][i]
            output.append({
                "name": meta.get("name", ""),
                "kind": meta.get("kind", ""),
                "path": meta.get("path", ""),
                "project": meta.get("project", ""),
                "language": meta.get("language", ""),
                "line_start": meta.get("line_start", 0),
                "line_end": meta.get("line_end", 0),
                "signature": meta.get("signature", ""),
                "visibility": meta.get("visibility", ""),
                "distance": round(distance, 4),
                "document": results["documents"][0][i],
            })
    return output


def semantic_stats(harness_root: Path) -> dict:
    """Return stats about the semantic index."""
    client = _get_client(harness_root)
    try:
        collection = client.get_collection(COLLECTION_NAME)
        count = collection.count()
    except Exception:
        count = 0
    return {
        "total_documents": count,
        "path": str(_chroma_path(harness_root)),
    }


def clear_semantic_index(harness_root: Path) -> None:
    """Delete the semantic index entirely."""
    client = _get_client(harness_root)
    try:
        client.delete_collection(COLLECTION_NAME)
    except Exception:
        pass
