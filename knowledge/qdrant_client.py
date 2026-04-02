"""
knowledge/qdrant_client.py

Knowledge base client for the IDM Generative System.

Handles:
    - Markdown document chunking (section-aware, preserves context)
    - Embedding via OpenAI text-embedding-3-large (3072 dims)
    - Qdrant collection management (create, ingest, search)
    - Semantic search with metadata filtering

The primary data source is THE_MASTER_DATASET_SPECIFICATION.md — a 667-line
technical document covering hardware specs, DSP algorithms, regional aesthetics,
and synthesis architecture for 1987–1999 underground electronic music.

Usage:
    # Ingest
    python -m knowledge.qdrant_client ingest path/to/THE_MASTER_DATASET_SPECIFICATION.md

    # Search (CLI quick test)
    python -m knowledge.qdrant_client search "TB-303 acid slide filter"

    # Programmatic
    from knowledge.qdrant_client import KnowledgeBase
    kb = KnowledgeBase()
    kb.ingest_markdown("path/to/doc.md")
    results = kb.search("acid slide nonlinear glide")
"""

from __future__ import annotations

import hashlib
import os
import re
import sys
from pathlib import Path
from typing import Any

from dotenv import load_dotenv
from openai import APIConnectionError, APITimeoutError, OpenAI, RateLimitError
from qdrant_client.models import (
    Distance,
    FieldCondition,
    Filter,
    MatchValue,
    PointStruct,
    VectorParams,
)
from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_exponential

from qdrant_client import QdrantClient

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

COLLECTION_NAME = "master_dataset"
EMBEDDING_MODEL = "text-embedding-3-large"
EMBEDDING_DIMS = 3072
QDRANT_URL = os.getenv("QDRANT_URL", "http://localhost:6333")

# Chunking
MAX_CHUNK_CHARS = 2000  # Soft limit — split further on ### if exceeded
MIN_CHUNK_CHARS = 100   # Skip trivially small chunks


# ---------------------------------------------------------------------------
# Chunking
# ---------------------------------------------------------------------------

def chunk_markdown(text: str) -> list[dict[str, Any]]:
    """
    Split a markdown document into semantically meaningful chunks.

    Strategy:
        1. Split on ## headers (PART level) — each becomes a chunk.
        2. If a chunk exceeds MAX_CHUNK_CHARS, further split on ### headers.
        3. Each chunk carries metadata: part, subsection, title.
        4. Table of Contents (lines before first ## header) is a single chunk.
        5. Code blocks are kept intact within their parent chunk.

    Args:
        text: Raw markdown string.

    Returns:
        List of dicts: {text, part, subsection, title}
    """
    lines = text.split("\n")
    chunks: list[dict[str, Any]] = []

    # Find all ## header positions
    h2_positions: list[tuple[int, str]] = []
    for i, line in enumerate(lines):
        if line.startswith("## "):
            h2_positions.append((i, line.strip("# ").strip()))

    # Pre-TOC content (if any substantial content before first ##)
    if h2_positions:
        pre_toc = "\n".join(lines[: h2_positions[0][0]]).strip()
        if len(pre_toc) >= MIN_CHUNK_CHARS:
            chunks.append({
                "text": pre_toc,
                "part": "TOC",
                "subsection": None,
                "title": "Table of Contents",
            })

    # Process each ## section
    for idx, (start, title) in enumerate(h2_positions):
        # Section end = next ## or EOF
        end = h2_positions[idx + 1][0] if idx + 1 < len(h2_positions) else len(lines)
        section_text = "\n".join(lines[start:end]).strip()

        # Extract PART number if present
        part_match = re.match(r"PART\s+(\d+[\.\d]*)", title)
        part = part_match.group(1) if part_match else title[:50]

        # If section is small enough, keep as single chunk
        if len(section_text) <= MAX_CHUNK_CHARS:
            if len(section_text) >= MIN_CHUNK_CHARS:
                chunks.append({
                    "text": section_text,
                    "part": part,
                    "subsection": None,
                    "title": title,
                })
            continue

        # Section too large — split on ### subsections
        sub_chunks = _split_on_h3(lines[start:end], part, title)
        chunks.extend(sub_chunks)

    return chunks


def _split_on_h3(
    lines: list[str], part: str, parent_title: str
) -> list[dict[str, Any]]:
    """
    Split a ## section further on ### headers.

    The ## header line is prepended to the first sub-chunk for context.
    """
    chunks: list[dict[str, Any]] = []
    h3_positions: list[tuple[int, str]] = []

    for i, line in enumerate(lines):
        if line.startswith("### "):
            h3_positions.append((i, line.strip("# ").strip()))

    if not h3_positions:
        # No ### headers — keep as single large chunk
        text = "\n".join(lines).strip()
        if len(text) >= MIN_CHUNK_CHARS:
            chunks.append({
                "text": text,
                "part": part,
                "subsection": None,
                "title": parent_title,
            })
        return chunks

    # Content before first ### (includes ## header)
    pre_h3 = "\n".join(lines[: h3_positions[0][0]]).strip()
    if len(pre_h3) >= MIN_CHUNK_CHARS:
        chunks.append({
            "text": pre_h3,
            "part": part,
            "subsection": None,
            "title": parent_title,
        })

    # Each ### subsection
    context_header = lines[0].strip()  # The ## line for context
    for idx, (start, sub_title) in enumerate(h3_positions):
        end = (
            h3_positions[idx + 1][0]
            if idx + 1 < len(h3_positions)
            else len(lines)
        )
        sub_text = "\n".join(lines[start:end]).strip()

        # Prepend parent ## header for retrieval context
        full_text = f"{context_header}\n\n{sub_text}"

        if len(full_text) >= MIN_CHUNK_CHARS:
            chunks.append({
                "text": full_text,
                "part": part,
                "subsection": sub_title[:100],
                "title": f"{parent_title} > {sub_title}",
            })

    return chunks


def _deterministic_id(text: str) -> str:
    """Generate a deterministic hex ID from chunk text (for idempotent upserts)."""
    return hashlib.md5(text.encode("utf-8")).hexdigest()


# ---------------------------------------------------------------------------
# KnowledgeBase
# ---------------------------------------------------------------------------

class KnowledgeBase:
    """
    Qdrant-backed knowledge base with OpenAI embeddings.

    Attributes:
        qdrant:     QdrantClient instance.
        openai:     OpenAI client instance.
        collection: Qdrant collection name.
    """

    def __init__(
        self,
        qdrant_url: str | None = None,
        collection: str = COLLECTION_NAME,
    ) -> None:
        load_dotenv()

        self.qdrant = QdrantClient(
            url=qdrant_url or QDRANT_URL,
            api_key=os.getenv("QDRANT_API_KEY"),
        )
        self.openai = OpenAI()  # Uses OPENAI_API_KEY from env
        self.collection = collection

    # ------------------------------------------------------------------
    # Collection management
    # ------------------------------------------------------------------

    def ensure_collection(self) -> None:
        """Create the collection if it doesn't exist."""
        existing = [c.name for c in self.qdrant.get_collections().collections]
        if self.collection in existing:
            return

        self.qdrant.create_collection(
            collection_name=self.collection,
            vectors_config=VectorParams(
                size=EMBEDDING_DIMS,
                distance=Distance.COSINE,
            ),
        )

    def delete_collection(self) -> None:
        """Delete the collection (for re-ingestion)."""
        self.qdrant.delete_collection(collection_name=self.collection)

    def collection_info(self) -> dict[str, Any]:
        """Return collection stats."""
        info = self.qdrant.get_collection(collection_name=self.collection)
        return {
            "name": self.collection,
            "points_count": info.points_count,
            "status": info.status.value,
        }

    # ------------------------------------------------------------------
    # Embedding
    # ------------------------------------------------------------------

    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=1, max=10),
        retry=retry_if_exception_type(
            (RateLimitError, APITimeoutError, APIConnectionError)
        ),
    )
    def embed(self, texts: list[str]) -> list[list[float]]:
        """
        Embed a batch of texts via OpenAI text-embedding-3-large.

        Retries up to 3 times with exponential backoff on transient
        OpenAI errors (rate limit, timeout, connection).

        Args:
            texts: List of strings to embed.

        Returns:
            List of embedding vectors (3072 dims each).
        """
        response = self.openai.embeddings.create(
            model=EMBEDDING_MODEL,
            input=texts,
        )
        return [item.embedding for item in response.data]

    # ------------------------------------------------------------------
    # Ingestion
    # ------------------------------------------------------------------

    def ingest_markdown(self, filepath: str | Path) -> dict[str, Any]:
        """
        Full ingestion pipeline: read → chunk → embed → upload to Qdrant.

        Args:
            filepath: Path to markdown file.

        Returns:
            Stats dict: {chunks, points_uploaded, collection_info}
        """
        filepath = Path(filepath)
        if not filepath.exists():
            raise FileNotFoundError(f"File not found: {filepath}")

        text = filepath.read_text(encoding="utf-8")
        chunks = chunk_markdown(text)

        if not chunks:
            raise ValueError(f"No chunks extracted from {filepath}")

        # Embed all chunks in a single batch
        texts = [c["text"] for c in chunks]
        embeddings = self.embed(texts)

        # Build Qdrant points
        points: list[PointStruct] = []
        for chunk, vector in zip(chunks, embeddings, strict=True):
            point_id = _deterministic_id(chunk["text"])
            points.append(
                PointStruct(
                    id=point_id,
                    vector=vector,
                    payload={
                        "text": chunk["text"],
                        "part": chunk["part"],
                        "subsection": chunk["subsection"],
                        "title": chunk["title"],
                        "source": filepath.name,
                    },
                )
            )

        # Upload
        self.ensure_collection()
        self.qdrant.upsert(
            collection_name=self.collection,
            points=points,
        )

        return {
            "chunks": len(chunks),
            "points_uploaded": len(points),
            "collection_info": self.collection_info(),
        }

    # ------------------------------------------------------------------
    # Search
    # ------------------------------------------------------------------

    def search(
        self,
        query: str,
        limit: int = 5,
        part_filter: str | None = None,
    ) -> list[dict[str, Any]]:
        """
        Semantic search over the knowledge base.

        Args:
            query:       Natural language query.
            limit:       Max results to return.
            part_filter: Optional — restrict to a specific PART number.

        Returns:
            List of dicts: {text, part, subsection, title, score}
        """
        query_vector = self.embed([query])[0]

        search_filter = None
        if part_filter:
            search_filter = Filter(
                must=[
                    FieldCondition(
                        key="part",
                        match=MatchValue(value=part_filter),
                    )
                ]
            )

        results = self.qdrant.query_points(
            collection_name=self.collection,
            query=query_vector,
            limit=limit,
            query_filter=search_filter,
        )

        return [
            {
                "text": hit.payload["text"],
                "part": hit.payload["part"],
                "subsection": hit.payload.get("subsection"),
                "title": hit.payload["title"],
                "score": hit.score,
            }
            for hit in results.points
        ]


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def _cli() -> None:
    """Minimal CLI for ingestion and search testing."""
    if len(sys.argv) < 2:
        print("Usage:")
        print("  python -m knowledge.qdrant_client ingest <path/to/file.md>")
        print("  python -m knowledge.qdrant_client search <query>")
        print("  python -m knowledge.qdrant_client info")
        sys.exit(1)

    command = sys.argv[1]
    kb = KnowledgeBase()

    if command == "ingest":
        if len(sys.argv) < 3:
            print("Error: provide path to markdown file.")
            sys.exit(1)
        filepath = sys.argv[2]
        print(f"Ingesting: {filepath}")
        result = kb.ingest_markdown(filepath)
        print(f"Chunks: {result['chunks']}")
        print(f"Points uploaded: {result['points_uploaded']}")
        print(f"Collection: {result['collection_info']}")

    elif command == "search":
        query = " ".join(sys.argv[2:])
        if not query:
            print("Error: provide a search query.")
            sys.exit(1)
        print(f"Searching: '{query}'\n")
        results = kb.search(query)
        for i, r in enumerate(results, 1):
            print(f"--- Result {i} (score: {r['score']:.4f}) ---")
            print(f"Part: {r['part']} | {r['title']}")
            print(r["text"][:300])
            print()

    elif command == "info":
        kb.ensure_collection()
        print(kb.collection_info())

    else:
        print(f"Unknown command: {command}")
        sys.exit(1)


if __name__ == "__main__":
    _cli()
