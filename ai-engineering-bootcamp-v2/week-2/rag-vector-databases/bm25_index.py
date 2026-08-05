"""In-process BM25 index — synced on ingest and rebuilt from Pinecone on startup."""

from __future__ import annotations

import logging
import re
import threading
from dataclasses import dataclass
from typing import Callable

from langchain_core.documents import Document
from rank_bm25 import BM25Okapi

logger = logging.getLogger(__name__)

TOKEN_RE = re.compile(r"[a-z0-9]+")
FETCH_BATCH_SIZE = 100
LIST_PAGE_SIZE = 100
METADATA_TEXT_KEY = "text"


@dataclass
class ChunkRecord:
    chunk_id: str
    document_id: str
    source: str
    text: str
    chunk_index: int
    title: str = ""
    source_url: str = ""


class BM25Index:
    def __init__(self) -> None:
        self._records: dict[str, ChunkRecord] = {}
        self._bm25: BM25Okapi | None = None
        self._chunk_ids: list[str] = []
        # Reentrant so mutation methods can call _rebuild_bm25() while holding it.
        self._lock = threading.RLock()

    def is_empty(self) -> bool:
        with self._lock:
            return not self._records

    def record_count(self) -> int:
        with self._lock:
            return len(self._records)

    def clear(self) -> None:
        with self._lock:
            self._records.clear()
            self._rebuild_bm25()

    def delete_document(self, document_id: str) -> None:
        with self._lock:
            to_remove = [
                chunk_id
                for chunk_id, record in self._records.items()
                if record.document_id == document_id
            ]
            for chunk_id in to_remove:
                del self._records[chunk_id]
            if to_remove:
                self._rebuild_bm25()

    def upsert_chunks(
        self,
        chunks: list[Document],
        chunk_id_fn: Callable[[str, int], str],
    ) -> None:
        if not chunks:
            return

        with self._lock:
            document_ids = {
                str(chunk.metadata.get("document_id", "unknown")) for chunk in chunks
            }
            for document_id in document_ids:
                self.delete_document(document_id)

            by_document: dict[str, list[Document]] = {}
            for chunk in chunks:
                document_id = str(chunk.metadata.get("document_id", "unknown"))
                by_document.setdefault(document_id, []).append(chunk)

            for document_id, doc_chunks in by_document.items():
                for chunk_index, chunk in enumerate(doc_chunks):
                    chunk_id = chunk_id_fn(document_id, chunk_index)
                    self._records[chunk_id] = ChunkRecord(
                        chunk_id=chunk_id,
                        document_id=document_id,
                        source=str(chunk.metadata.get("source", "")),
                        text=chunk.page_content,
                        chunk_index=chunk_index,
                        title=str(chunk.metadata.get("title", "")),
                        source_url=str(chunk.metadata.get("source_url", "")),
                    )

            self._rebuild_bm25()

    def search(
        self,
        query: str,
        k: int,
        document_ids: list[str] | None = None,
        exclude_document_ids: list[str] | None = None,
    ) -> list[tuple[str, float]]:
        tokens = tokenize(query)
        if not tokens:
            return []

        allowed = (
            {doc_id.strip().lower() for doc_id in document_ids if doc_id.strip()}
            if document_ids
            else None
        )
        excluded = (
            {doc_id.strip().lower() for doc_id in exclude_document_ids if doc_id.strip()}
            if exclude_document_ids
            else None
        )

        with self._lock:
            if self._bm25 is None or not self._chunk_ids:
                return []

            scores = self._bm25.get_scores(tokens)
            ranked = sorted(
                zip(self._chunk_ids, scores, strict=True),
                key=lambda item: item[1],
                reverse=True,
            )
            results: list[tuple[str, float]] = []
            for chunk_id, score in ranked:
                if score <= 0:
                    continue
                doc_id = self._records[chunk_id].document_id.lower()
                if allowed and doc_id not in allowed:
                    continue
                if excluded and doc_id in excluded:
                    continue
                results.append((chunk_id, float(score)))
                if len(results) >= k:
                    break
            return results

    def get_record(self, chunk_id: str) -> ChunkRecord | None:
        with self._lock:
            return self._records.get(chunk_id)

    def rebuild_from_pinecone(self) -> int:
        """Load all chunk metadata from Pinecone and rebuild the BM25 corpus."""

        from ingest import _pinecone_index

        index = _pinecone_index()

        pagination_token: str | None = None
        all_ids: list[str] = []

        while True:
            kwargs: dict = {"limit": LIST_PAGE_SIZE}
            if pagination_token:
                kwargs["pagination_token"] = pagination_token

            page = index.list_paginated(**kwargs)
            all_ids.extend(item.id for item in page.vectors)

            pagination = page.pagination
            pagination_token = pagination.next if pagination else None
            if not pagination_token:
                break

        records: dict[str, ChunkRecord] = {}
        for start in range(0, len(all_ids), FETCH_BATCH_SIZE):
            batch_ids = all_ids[start : start + FETCH_BATCH_SIZE]
            if not batch_ids:
                continue

            fetched = index.fetch(ids=batch_ids)
            for chunk_id, vector in fetched.vectors.items():
                metadata = vector.metadata or {}
                text = str(metadata.get(METADATA_TEXT_KEY, "")).strip()
                if not text:
                    continue

                document_id = str(metadata.get("document_id", ""))
                chunk_index_raw = metadata.get("chunk_index", -1)
                chunk_index = int(chunk_index_raw) if chunk_index_raw is not None else -1

                records[chunk_id] = ChunkRecord(
                    chunk_id=chunk_id,
                    document_id=document_id,
                    source=str(metadata.get("source", "")),
                    text=text,
                    chunk_index=chunk_index,
                    title=str(metadata.get("title", "")),
                    source_url=str(metadata.get("source_url", "")),
                )

        # Swap in the freshly built corpus under the lock so concurrent searches
        # never observe a half-cleared index.
        with self._lock:
            self._records = records
            self._rebuild_bm25()
            logger.info("BM25 index rebuilt from Pinecone with %d chunks", len(self._records))
            return len(self._records)

    def _rebuild_bm25(self) -> None:
        self._chunk_ids = list(self._records.keys())
        if not self._chunk_ids:
            self._bm25 = None
            return

        corpus_tokens = [tokenize(self._records[chunk_id].text) for chunk_id in self._chunk_ids]
        self._bm25 = BM25Okapi(corpus_tokens)


def tokenize(text: str) -> list[str]:
    return TOKEN_RE.findall(text.lower())


_instance: BM25Index | None = None
_instance_lock = threading.Lock()


def get_bm25_index() -> BM25Index:
    global _instance
    if _instance is None:
        with _instance_lock:
            if _instance is None:
                _instance = BM25Index()
    return _instance


def ensure_bm25_ready() -> BM25Index:
    """Rebuild from Pinecone when the in-process index is empty."""

    from env_utils import bool_env

    index = get_bm25_index()
    if index.is_empty() and bool_env("HYBRID_SEARCH", True):
        index.rebuild_from_pinecone()
    return index
