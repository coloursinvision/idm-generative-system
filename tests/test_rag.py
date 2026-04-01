"""
tests/test_rag.py

Unit tests for the RAG pipeline and knowledge base endpoints.

All external dependencies (OpenAI, Qdrant) are mocked — no API keys or
network access required. Tests verify:
    - /ask endpoint returns structured response
    - /compose endpoint returns parsed JSON config
    - /compose validates GPT-4o output (malformed JSON, missing keys)
    - RAG pipeline single-search optimisation (no double calls)
    - Knowledge base chunking logic
    - Error propagation from RAG pipeline to API

Run:
    pytest tests/test_rag.py -v
"""

from __future__ import annotations

import json
from unittest.mock import patch, MagicMock

import pytest
from fastapi.testclient import TestClient

from api.main import app
from knowledge.rag import RAGPipeline
from knowledge.qdrant_client import chunk_markdown


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture(scope="module")
def client() -> TestClient:
    return TestClient(app)


def _mock_search_results(n: int = 2) -> list[dict]:
    """Build mock Qdrant search results."""
    return [
        {
            "text": f"Mock chunk {i}: TB-303 filter uses 18dB/oct 3-pole topology.",
            "part": f"1.{i}",
            "subsection": None,
            "title": f"Part 1.{i} — Test Section",
            "score": round(0.95 - i * 0.05, 3),
        }
        for i in range(n)
    ]


def _mock_openai_response(content: str) -> MagicMock:
    """Build a mock OpenAI ChatCompletion response."""
    mock = MagicMock()
    mock.choices = [MagicMock()]
    mock.choices[0].message.content = content
    mock.usage.prompt_tokens = 100
    mock.usage.completion_tokens = 50
    mock.usage.total_tokens = 150
    return mock


# ---------------------------------------------------------------------------
# /ask endpoint
# ---------------------------------------------------------------------------

class TestAskEndpoint:
    """POST /ask — sound design advisor."""

    @patch("api.main.rag")
    def test_ask_returns_200_with_answer(
        self, mock_rag: MagicMock, client: TestClient
    ) -> None:
        mock_rag.ask.return_value = {
            "answer": "The TB-303 uses a 3-pole 18dB/oct low-pass filter.",
            "sources": [{"title": "Part 1.2", "part": "1.2", "score": 0.92}],
            "model": "gpt-4o",
            "usage": {"prompt_tokens": 100, "completion_tokens": 50, "total_tokens": 150},
        }

        resp = client.post("/ask", json={"question": "How does the 303 filter work?"})
        assert resp.status_code == 200

        data = resp.json()
        assert "answer" in data
        assert "sources" in data
        assert "model" in data
        assert "usage" in data
        assert data["model"] == "gpt-4o"

    @patch("api.main.rag")
    def test_ask_with_part_filter(
        self, mock_rag: MagicMock, client: TestClient
    ) -> None:
        mock_rag.ask.return_value = {
            "answer": "Filtered answer.",
            "sources": [],
            "model": "gpt-4o",
            "usage": {"prompt_tokens": 80, "completion_tokens": 20, "total_tokens": 100},
        }

        resp = client.post("/ask", json={
            "question": "What is the SP-1200 sample rate?",
            "part_filter": "1.1",
            "limit": 3,
        })
        assert resp.status_code == 200
        mock_rag.ask.assert_called_once_with(
            question="What is the SP-1200 sample rate?",
            limit=3,
            part_filter="1.1",
        )

    def test_ask_rejects_empty_question(self, client: TestClient) -> None:
        resp = client.post("/ask", json={"question": ""})
        assert resp.status_code == 422

    def test_ask_rejects_too_short_question(self, client: TestClient) -> None:
        resp = client.post("/ask", json={"question": "ab"})
        assert resp.status_code == 422

    @patch("api.main.rag")
    def test_ask_500_on_pipeline_error(
        self, mock_rag: MagicMock, client: TestClient
    ) -> None:
        mock_rag.ask.side_effect = Exception("Qdrant connection refused")

        resp = client.post("/ask", json={"question": "Test question here"})
        assert resp.status_code == 500
        assert "RAG pipeline error" in resp.json()["detail"]


# ---------------------------------------------------------------------------
# /compose endpoint
# ---------------------------------------------------------------------------

class TestComposeEndpoint:
    """POST /compose — auto-composer."""

    @patch("api.main.rag")
    def test_compose_returns_200_with_config(
        self, mock_rag: MagicMock, client: TestClient
    ) -> None:
        mock_rag.compose.return_value = {
            "config": {
                "generator": "glitch_click",
                "generator_params": {"length_ms": 200, "decay": 4.0},
                "chain_overrides": {"bitcrusher": {"hardware_preset": "sp1200"}},
                "chain_skip": [],
                "reasoning": "SP-1200 grit for classic boom-bap texture.",
            },
            "sources": [{"title": "Part 1.1", "part": "1.1", "score": 0.89}],
            "model": "gpt-4o",
            "usage": {"prompt_tokens": 120, "completion_tokens": 80, "total_tokens": 200},
        }

        resp = client.post("/compose", json={
            "description": "dark Detroit techno with heavy 909 swing",
        })
        assert resp.status_code == 200

        data = resp.json()
        assert "config" in data
        assert isinstance(data["config"], dict)
        assert data["config"]["generator"] == "glitch_click"

    def test_compose_rejects_empty_description(self, client: TestClient) -> None:
        resp = client.post("/compose", json={"description": ""})
        assert resp.status_code == 422

    @patch("api.main.rag")
    def test_compose_500_on_pipeline_error(
        self, mock_rag: MagicMock, client: TestClient
    ) -> None:
        mock_rag.compose.side_effect = Exception("OpenAI rate limit")

        resp = client.post("/compose", json={"description": "acid techno style"})
        assert resp.status_code == 500
        assert "RAG pipeline error" in resp.json()["detail"]


# ---------------------------------------------------------------------------
# RAGPipeline internal logic (unit tests, fully mocked)
# ---------------------------------------------------------------------------

class TestRAGPipelineInternal:
    """Direct unit tests for RAGPipeline methods."""

    @patch("knowledge.rag.OpenAI")
    @patch("knowledge.rag.KnowledgeBase")
    def test_ask_calls_search_once(
        self, MockKB: MagicMock, MockOpenAI: MagicMock
    ) -> None:
        """CR-02: verify single search call, not double."""
        mock_kb = MockKB.return_value
        mock_kb.search.return_value = _mock_search_results(2)

        mock_client = MockOpenAI.return_value
        mock_client.chat.completions.create.return_value = _mock_openai_response(
            "The answer is 42."
        )

        pipeline = RAGPipeline()
        pipeline.kb = mock_kb
        pipeline.openai = mock_client

        result = pipeline.ask("test question")

        # search must be called exactly once (was 2 before CR-02)
        assert mock_kb.search.call_count == 1
        assert "answer" in result
        assert len(result["sources"]) == 2

    @patch("knowledge.rag.OpenAI")
    @patch("knowledge.rag.KnowledgeBase")
    def test_compose_calls_search_once(
        self, MockKB: MagicMock, MockOpenAI: MagicMock
    ) -> None:
        """CR-02: verify single search call in compose."""
        mock_kb = MockKB.return_value
        mock_kb.search.return_value = _mock_search_results(2)

        valid_config = json.dumps({
            "generator": "fm_blip",
            "generator_params": {"freq": 440},
            "chain_overrides": {},
            "chain_skip": [],
            "reasoning": "test",
        })

        mock_client = MockOpenAI.return_value
        mock_client.chat.completions.create.return_value = _mock_openai_response(
            valid_config
        )

        pipeline = RAGPipeline()
        pipeline.kb = mock_kb
        pipeline.openai = mock_client

        result = pipeline.compose("test description")

        assert mock_kb.search.call_count == 1
        assert isinstance(result["config"], dict)
        assert result["config"]["generator"] == "fm_blip"

    @patch("knowledge.rag.OpenAI")
    @patch("knowledge.rag.KnowledgeBase")
    def test_compose_handles_markdown_fences(
        self, MockKB: MagicMock, MockOpenAI: MagicMock
    ) -> None:
        """CR-14: GPT-4o sometimes wraps JSON in ```json fences."""
        mock_kb = MockKB.return_value
        mock_kb.search.return_value = _mock_search_results(1)

        fenced_json = '```json\n{"generator": "noise_burst", "generator_params": {}, "chain_overrides": {}}\n```'

        mock_client = MockOpenAI.return_value
        mock_client.chat.completions.create.return_value = _mock_openai_response(
            fenced_json
        )

        pipeline = RAGPipeline()
        pipeline.kb = mock_kb
        pipeline.openai = mock_client

        result = pipeline.compose("ambient pad texture")
        assert result["config"]["generator"] == "noise_burst"

    @patch("knowledge.rag.OpenAI")
    @patch("knowledge.rag.KnowledgeBase")
    def test_compose_rejects_invalid_json(
        self, MockKB: MagicMock, MockOpenAI: MagicMock
    ) -> None:
        """CR-14: malformed JSON raises ValueError."""
        mock_kb = MockKB.return_value
        mock_kb.search.return_value = _mock_search_results(1)

        mock_client = MockOpenAI.return_value
        mock_client.chat.completions.create.return_value = _mock_openai_response(
            "Sure! Here is the config: {broken json"
        )

        pipeline = RAGPipeline()
        pipeline.kb = mock_kb
        pipeline.openai = mock_client

        with pytest.raises(ValueError, match="invalid JSON"):
            pipeline.compose("acid techno")

    @patch("knowledge.rag.OpenAI")
    @patch("knowledge.rag.KnowledgeBase")
    def test_compose_rejects_missing_keys(
        self, MockKB: MagicMock, MockOpenAI: MagicMock
    ) -> None:
        """CR-14: valid JSON but missing required keys."""
        mock_kb = MockKB.return_value
        mock_kb.search.return_value = _mock_search_results(1)

        # Missing "generator" and "chain_overrides"
        incomplete_json = json.dumps({"generator_params": {"freq": 440}})

        mock_client = MockOpenAI.return_value
        mock_client.chat.completions.create.return_value = _mock_openai_response(
            incomplete_json
        )

        pipeline = RAGPipeline()
        pipeline.kb = mock_kb
        pipeline.openai = mock_client

        with pytest.raises(ValueError, match="missing required keys"):
            pipeline.compose("breakbeat jungle")

    @patch("knowledge.rag.OpenAI")
    @patch("knowledge.rag.KnowledgeBase")
    def test_ask_empty_context(
        self, MockKB: MagicMock, MockOpenAI: MagicMock
    ) -> None:
        """No search results should still produce an answer."""
        mock_kb = MockKB.return_value
        mock_kb.search.return_value = []

        mock_client = MockOpenAI.return_value
        mock_client.chat.completions.create.return_value = _mock_openai_response(
            "I could not find relevant information in the knowledge base."
        )

        pipeline = RAGPipeline()
        pipeline.kb = mock_kb
        pipeline.openai = mock_client

        result = pipeline.ask("obscure question with no matches")
        assert "answer" in result
        assert result["sources"] == []


# ---------------------------------------------------------------------------
# Markdown chunking
# ---------------------------------------------------------------------------

class TestChunking:
    """Knowledge base chunking logic."""

    def test_empty_document(self) -> None:
        chunks = chunk_markdown("")
        assert chunks == []

    def test_single_section(self) -> None:
        md = "## PART 1 — Test Section\n\nThis is the content of part one. " * 5
        chunks = chunk_markdown(md)
        assert len(chunks) >= 1
        assert chunks[0]["part"] == "1"

    def test_multiple_sections(self) -> None:
        section_body = "This section contains detailed technical content about hardware. " * 3
        md = (
            f"## PART 1 — First\n\n{section_body}\n\n"
            f"## PART 2 — Second\n\n{section_body}\n\n"
            f"## PART 3 — Third\n\n{section_body}\n"
        )
        chunks = chunk_markdown(md)
        parts = [c["part"] for c in chunks]
        assert "1" in parts
        assert "2" in parts
        assert "3" in parts

    def test_toc_chunk_created(self) -> None:
        md = (
            "# Title\n\n"
            "This is a table of contents with enough text to exceed the minimum "
            "chunk size threshold so it becomes its own chunk in the system.\n\n"
            "## PART 1 — Section\n\nContent here.\n"
        )
        chunks = chunk_markdown(md)
        toc_chunks = [c for c in chunks if c["part"] == "TOC"]
        assert len(toc_chunks) <= 1

    def test_subsection_splitting(self) -> None:
        long_content = "Detailed technical content. " * 200  # ~5400 chars
        md = (
            f"## PART 1 — Big Section\n\n"
            f"### Subsection A\n\n{long_content}\n\n"
            f"### Subsection B\n\n{long_content}\n"
        )
        chunks = chunk_markdown(md)
        subsection_chunks = [c for c in chunks if c.get("subsection")]
        assert len(subsection_chunks) >= 2

    def test_chunks_have_required_metadata(self) -> None:
        md = "## PART 5 — Effects\n\nContent about effects chain parameters.\n"
        chunks = chunk_markdown(md)
        for chunk in chunks:
            assert "text" in chunk
            assert "part" in chunk
            assert "title" in chunk
            assert len(chunk["text"]) > 0
