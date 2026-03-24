"""
knowledge/rag.py

RAG (Retrieval-Augmented Generation) pipeline for the IDM Generative System.

Combines:
    - Qdrant semantic search (knowledge/qdrant_client.py)
    - GPT-4o completion with retrieved context

Two modes (from SPEC):
    - Manual: Sound design advisor — answers questions about DSP, hardware,
      synthesis techniques, regional aesthetics, effects chain configuration.
    - Auto: Composer — generates parameter configurations for the effects chain
      and sample generators based on aesthetic intent.

Usage:
    from knowledge.rag import RAGPipeline

    rag = RAGPipeline()
    response = rag.ask("How do I get the Autechre granular texture?")
    response = rag.compose("dark Detroit techno with heavy 909 swing")
"""

from __future__ import annotations

import os
from typing import Any

from dotenv import load_dotenv
from openai import OpenAI

from knowledge.qdrant_client import KnowledgeBase


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

GPT_MODEL = "gpt-4o"
MAX_CONTEXT_CHUNKS = 5
MAX_CONTEXT_CHARS = 6000  # Hard cap on total retrieved context length

SYSTEM_PROMPT_ADVISOR = """You are the sound design advisor for the IDM Generative System — a generative audio engine modelling the underground electronic music era (1987–1999).

Your knowledge comes from THE MASTER DATASET SPECIFICATION, covering:
- Hardware constraints: TR-808, TR-909, TB-303, SP-1200, Akai S950, DX100, CZ-101
- DSP algorithms: acid slide (30ms RC glide), accent coupling, Detroit chord memory
- Effects chain: 10 hardware-sourced blocks (NoiseFloor → Bitcrusher → ResonantFilter → Saturation → Reverb → TapeDelay → SpatialProcessor → GlitchEngine → Compressor → VinylMastering)
- Regional aesthetics: UK IDM (Warp/Rephlex), Detroit Techno (UR/Model 500), Japanese (Sublime/Frogman), European Acid
- Synthesis: FM operator ratios (Lately Bass, Detroit stabs), PWM (B12/Juno pads), granular (Autechre)
- Mastering: Mackie 1604 saturation, DAT brick-wall, vinyl pre-emphasis

Rules:
1. Answer ONLY from the provided context. If the context doesn't contain the answer, say so explicitly.
2. Be technically precise — cite specific hardware, parameter values, algorithms, and formulas.
3. When recommending effects chain settings, reference the block names and parameter names from the system.
4. Keep responses focused and actionable. No filler.
5. If the question involves DSP implementation, include the relevant formula or algorithm."""

SYSTEM_PROMPT_COMPOSER = """You are the auto-composer for the IDM Generative System — a generative audio engine modelling the underground electronic music era (1987–1999).

Given an aesthetic description, you generate a JSON configuration for the effects chain and sample generators.

Your output MUST be valid JSON with this structure:
{
    "generator": "glitch_click" | "noise_burst" | "fm_blip",
    "generator_params": { ... },
    "chain_overrides": {
        "block_key": { "param": value, ... },
        ...
    },
    "chain_skip": [ "block_key", ... ],
    "reasoning": "Brief explanation of aesthetic choices"
}

Available chain blocks and their keys:
- noise_floor, bitcrusher, filter, saturation, reverb, delay, spatial, glitch, compressor, vinyl

Rules:
1. Use ONLY parameters that exist in the effects chain blocks. Reference the context for valid parameter names.
2. Match the aesthetic intent to specific hardware characteristics from the dataset.
3. The "reasoning" field must reference specific hardware, techniques, or regional aesthetics from the dataset.
4. If the aesthetic is ambiguous, make a decisive choice and explain it.
5. Output ONLY the JSON object, no markdown fences, no preamble."""


# ---------------------------------------------------------------------------
# RAG Pipeline
# ---------------------------------------------------------------------------

class RAGPipeline:
    """
    Retrieval-Augmented Generation pipeline.

    Attributes:
        kb:     KnowledgeBase instance (Qdrant + embeddings).
        openai: OpenAI client instance.
        model:  GPT model name.
    """

    def __init__(
        self,
        qdrant_url: str | None = None,
        model: str = GPT_MODEL,
    ) -> None:
        load_dotenv()

        self.kb = KnowledgeBase(qdrant_url=qdrant_url)
        self.openai = OpenAI()
        self.model = model

    # ------------------------------------------------------------------
    # Context assembly
    # ------------------------------------------------------------------

    def _retrieve_context(
        self,
        query: str,
        limit: int = MAX_CONTEXT_CHUNKS,
        part_filter: str | None = None,
    ) -> str:
        """
        Retrieve relevant chunks and assemble into a context string.

        Applies a hard character cap to prevent context overflow.
        Each chunk is wrapped with metadata for traceability.
        """
        results = self.kb.search(
            query=query,
            limit=limit,
            part_filter=part_filter,
        )

        if not results:
            return "[No relevant context found in knowledge base.]"

        context_parts: list[str] = []
        total_chars = 0

        for r in results:
            chunk_header = f"[Source: {r['title']} | Score: {r['score']:.3f}]"
            chunk_text = r["text"]

            # Truncate individual chunk if needed
            remaining = MAX_CONTEXT_CHARS - total_chars
            if remaining <= 0:
                break

            if len(chunk_text) > remaining:
                chunk_text = chunk_text[:remaining] + "\n[...truncated]"

            context_parts.append(f"{chunk_header}\n{chunk_text}")
            total_chars += len(chunk_text)

        return "\n\n---\n\n".join(context_parts)

    # ------------------------------------------------------------------
    # Advisor mode (Manual)
    # ------------------------------------------------------------------

    def ask(
        self,
        question: str,
        limit: int = MAX_CONTEXT_CHUNKS,
        part_filter: str | None = None,
    ) -> dict[str, Any]:
        """
        Sound design advisor — answer a question using RAG.

        Args:
            question:    Natural language question.
            limit:       Max context chunks to retrieve.
            part_filter: Optional PART number filter.

        Returns:
            Dict with: answer, sources, model, usage.
        """
        context = self._retrieve_context(
            query=question,
            limit=limit,
            part_filter=part_filter,
        )

        user_message = (
            f"CONTEXT:\n{context}\n\n"
            f"QUESTION:\n{question}"
        )

        response = self.openai.chat.completions.create(
            model=self.model,
            messages=[
                {"role": "system", "content": SYSTEM_PROMPT_ADVISOR},
                {"role": "user", "content": user_message},
            ],
            temperature=0.3,
            max_tokens=1500,
        )

        choice = response.choices[0]

        # Extract source titles for attribution
        sources = self.kb.search(query=question, limit=limit, part_filter=part_filter)
        source_titles = [
            {"title": s["title"], "part": s["part"], "score": s["score"]}
            for s in sources
        ]

        return {
            "answer": choice.message.content,
            "sources": source_titles,
            "model": self.model,
            "usage": {
                "prompt_tokens": response.usage.prompt_tokens,
                "completion_tokens": response.usage.completion_tokens,
                "total_tokens": response.usage.total_tokens,
            },
        }

    # ------------------------------------------------------------------
    # Composer mode (Auto)
    # ------------------------------------------------------------------

    def compose(
        self,
        description: str,
        limit: int = MAX_CONTEXT_CHUNKS,
    ) -> dict[str, Any]:
        """
        Auto-composer — generate effects chain config from aesthetic description.

        Args:
            description: Aesthetic intent (e.g., "dark Detroit techno with 909 swing").
            limit:       Max context chunks to retrieve.

        Returns:
            Dict with: config (raw JSON string), sources, model, usage.
        """
        context = self._retrieve_context(query=description, limit=limit)

        user_message = (
            f"CONTEXT:\n{context}\n\n"
            f"AESTHETIC DESCRIPTION:\n{description}"
        )

        response = self.openai.chat.completions.create(
            model=self.model,
            messages=[
                {"role": "system", "content": SYSTEM_PROMPT_COMPOSER},
                {"role": "user", "content": user_message},
            ],
            temperature=0.7,
            max_tokens=1500,
        )

        choice = response.choices[0]

        sources = self.kb.search(query=description, limit=limit)
        source_titles = [
            {"title": s["title"], "part": s["part"], "score": s["score"]}
            for s in sources
        ]

        return {
            "config": choice.message.content,
            "sources": source_titles,
            "model": self.model,
            "usage": {
                "prompt_tokens": response.usage.prompt_tokens,
                "completion_tokens": response.usage.completion_tokens,
                "total_tokens": response.usage.total_tokens,
            },
        }
