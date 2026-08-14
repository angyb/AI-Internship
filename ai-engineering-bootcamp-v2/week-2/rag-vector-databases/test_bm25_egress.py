"""Tests for slim Pinecone payloads and Postgres-backed BM25 (no live Pinecone)."""

from __future__ import annotations

from langchain_core.documents import Document

from bm25_index import BM25Index, ChunkRecord, ensure_bm25_ready
from ingest import RetrievedChunk, _chunk_to_metadata, lookup_chunks_by_ids, retrieve_chunks


def test_chunk_metadata_omits_text() -> None:
    chunk = Document(
        page_content="A Tower Alert is generated for a teacher.",
        metadata={
            "document_id": "boosts",
            "title": "Boosts",
            "source_url": "https://help.zearn.org/boosts",
            "source": "zendesk/md/boosts.md",
        },
    )
    meta = _chunk_to_metadata(chunk, 0)
    assert "text" not in meta
    assert meta["document_id"] == "boosts"
    assert meta["chunk_index"] == 0
    assert meta["title"] == "Boosts"
    assert meta["source_url"] == "https://help.zearn.org/boosts"


def test_retrieve_chunks_sets_include_values_false(monkeypatch) -> None:
    captured: dict = {}

    class FakeIndex:
        def query(self, **kwargs):
            captured.update(kwargs)
            return {"matches": []}

    class FakeEmbed:
        def embed_query(self, _question: str):
            return [0.1, 0.2]

    monkeypatch.setattr("ingest._pinecone_index", lambda: FakeIndex())
    monkeypatch.setattr("ingest._embeddings_client", lambda: FakeEmbed())

    retrieve_chunks("does louisiana use zearn?", k=3)
    assert captured.get("include_values") is False
    assert captured.get("include_metadata") is True
    assert captured.get("top_k") == 3


def test_ensure_bm25_ready_uses_postgres_not_pinecone(monkeypatch) -> None:
    fake = BM25Index()
    calls = {"postgres": 0, "pinecone": 0}

    def load_from_postgres(self: BM25Index) -> int:
        calls["postgres"] += 1
        self._records = {
            "boosts__chunk_0": ChunkRecord(
                chunk_id="boosts__chunk_0",
                document_id="boosts",
                source="zendesk/md/boosts.md",
                text="A Tower Alert is generated after three Boosts.",
                chunk_index=0,
                title="Boosts",
            )
        }
        self._rebuild_bm25()
        return 1

    def rebuild_from_pinecone(self: BM25Index) -> int:
        calls["pinecone"] += 1
        return 0

    monkeypatch.setattr("bm25_index.get_bm25_index", lambda: fake)
    monkeypatch.setattr(BM25Index, "load_from_postgres", load_from_postgres)
    monkeypatch.setattr(BM25Index, "rebuild_from_pinecone", rebuild_from_pinecone)

    ready = ensure_bm25_ready()
    assert ready.record_count() == 1
    assert calls["postgres"] == 1
    assert calls["pinecone"] == 0


def test_lookup_chunks_by_ids_fetch_without_include_values(monkeypatch) -> None:
    """Pinecone SDK v9 fetch() rejects include_values — neighbor lookup must still work."""

    record = ChunkRecord(
        chunk_id="boosts__chunk_1",
        document_id="boosts",
        source="zendesk/md/boosts.md",
        text="Boosts provide scaffolded support in the Tower of Power.",
        chunk_index=1,
        title="Boosts",
    )

    class FakeVector:
        metadata = {
            "document_id": "boosts",
            "chunk_index": 1,
            "title": "Boosts",
            "source": "zendesk/md/boosts.md",
        }

    class FakeFetchResponse:
        vectors = {"boosts__chunk_99": FakeVector()}

    class FakeIndex:
        def fetch(self, *, ids, **kwargs):
            if "include_values" in kwargs:
                raise TypeError(
                    "Index.fetch() got an unexpected keyword argument 'include_values'"
                )
            assert ids == ["boosts__chunk_99"]
            return FakeFetchResponse()

    monkeypatch.setattr("ingest.get_bm25_index", lambda: BM25Index())
    monkeypatch.setattr("ingest._pinecone_index", lambda: FakeIndex())
    monkeypatch.setattr(
        "ingest._hydrate_from_bm25",
        lambda chunk: RetrievedChunk(
            text=record.text,
            document_id=chunk.document_id,
            title=chunk.title,
            source_url="",
            source=chunk.source,
            chunk_id=chunk.chunk_id,
            chunk_index=chunk.chunk_index,
        ),
    )

    resolved = lookup_chunks_by_ids(["boosts__chunk_99"])
    assert "boosts__chunk_99" in resolved
    assert resolved["boosts__chunk_99"].document_id == "boosts"
