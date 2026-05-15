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

import json
import os
import re
from typing import Any

from dotenv import load_dotenv
from openai import APIConnectionError, APITimeoutError, OpenAI, RateLimitError
from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_exponential

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


TUNING_EXTRACT_SYSTEM_PROMPT = """You extract structured generative-context parameters from free-text descriptions for the IDM Generative System's /tuning endpoint.

Your output is a JSON object matching the TuningRequest API contract:

{
  "bpm": float in [60.0, 240.0],
  "pitch_midi": float in [0.0, 127.0],
  "swing_pct": float in [0.0, 100.0],
  "region": one of [
    "DETROIT_FIRST_WAVE",
    "DETROIT_UR",
    "DREXCIYA",
    "UK_IDM",
    "UK_BRAINDANCE",
    "JAPAN_IDM"
  ],
  "sub_region": one of ["TOKYO", "OSAKA"] OR null
}

Cross-field rule:
- sub_region MUST be one of "TOKYO" or "OSAKA" when region == "JAPAN_IDM".
- sub_region MUST be null when region is any other value.

Field guidance:
- pitch_midi: MIDI note number (A4 = 69, middle C = 60). Convert pitch names
  to MIDI integers (e.g. "C3" -> 48, "F#4" -> 66).
- swing_pct: percentage in [0, 100]. "straight"/"no swing" -> 0; "heavy swing"
  -> ~66; "moderate"/"shuffled" -> ~55.
- region: pick the closest match. Detroit techno first wave -> DETROIT_FIRST_WAVE.
  Underground Resistance / Mad Mike / Drexciya-orbit Detroit -> DETROIT_UR.
  Drexciya specifically -> DREXCIYA. UK IDM (Aphex Twin, Squarepusher, Autechre,
  Boards of Canada) -> UK_IDM. Rephlex braindance scene -> UK_BRAINDANCE.
  Japanese IDM (Susumu Yokota, Aoki Takamasa, Nobukazu Takemura) -> JAPAN_IDM.
- sub_region: for JAPAN_IDM, infer TOKYO (50 Hz grid, Yokota/Takemura) or
  OSAKA (60 Hz grid, Aoki) from cues. Default TOKYO if no signal.

Rules:
1. Output ONLY the JSON object, no markdown fences, no preamble, no explanation.
2. If a field is genuinely unspecified, make a decisive default choice from
   typical genre conventions rather than refusing. Defaults: bpm=130,
   pitch_midi=69 (A4), swing_pct=0.
3. region MUST be one of the six exact strings above. Never invent new values.
4. The cross-field rule is non-negotiable: validate before outputting.
"""


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

        api_key = os.getenv("OPENAI_API_KEY")
        if not api_key:
            raise OSError("OPENAI_API_KEY not set. Add it to .env or export it.")

        self.kb = KnowledgeBase(qdrant_url=qdrant_url)
        self.openai = OpenAI(api_key=api_key)
        self.model = model

    # ------------------------------------------------------------------
    # LLM call with retry
    # ------------------------------------------------------------------

    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=1, max=10),
        retry=retry_if_exception_type((RateLimitError, APITimeoutError, APIConnectionError)),
    )
    def _complete(
        self,
        system_prompt: str,
        user_message: str,
        temperature: float = 0.3,
        max_tokens: int = 1500,
    ) -> Any:
        """
        Call OpenAI chat completion with automatic retry on transient errors.

        Retries up to 3 times with exponential backoff (1s, 2s, 4s) on:
            - 429 RateLimitError
            - APITimeoutError
            - APIConnectionError

        All other errors propagate immediately.
        """
        return self.openai.chat.completions.create(
            model=self.model,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_message},
            ],
            temperature=temperature,
            max_tokens=max_tokens,
        )

    # ------------------------------------------------------------------
    # Context assembly
    # ------------------------------------------------------------------

    def _retrieve_context(
        self,
        query: str,
        limit: int = MAX_CONTEXT_CHUNKS,
        part_filter: str | None = None,
    ) -> tuple[str, list[dict[str, Any]]]:
        """
        Retrieve relevant chunks and assemble into a context string.

        Applies a hard character cap to prevent context overflow.
        Each chunk is wrapped with metadata for traceability.

        Returns:
            Tuple of (context_string, raw_search_results).
            Single search call — callers use both outputs without
            repeating the embedding + Qdrant query.
        """
        results = self.kb.search(
            query=query,
            limit=limit,
            part_filter=part_filter,
        )

        if not results:
            return "[No relevant context found in knowledge base.]", []

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

        return "\n\n---\n\n".join(context_parts), results

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
        context, results = self._retrieve_context(
            query=question,
            limit=limit,
            part_filter=part_filter,
        )

        user_message = f"CONTEXT:\n{context}\n\nQUESTION:\n{question}"

        response = self._complete(
            system_prompt=SYSTEM_PROMPT_ADVISOR,
            user_message=user_message,
            temperature=0.3,
        )

        choice = response.choices[0]

        source_titles = [
            {"title": s["title"], "part": s["part"], "score": s["score"]} for s in results
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
            Dict with: config (parsed dict), sources, model, usage.
        """
        context, results = self._retrieve_context(query=description, limit=limit)

        user_message = f"CONTEXT:\n{context}\n\nAESTHETIC DESCRIPTION:\n{description}"

        response = self._complete(
            system_prompt=SYSTEM_PROMPT_COMPOSER,
            user_message=user_message,
            temperature=0.7,
        )

        choice = response.choices[0]

        # Validate and parse GPT-4o JSON output
        config = self._parse_compose_output(choice.message.content)

        source_titles = [
            {"title": s["title"], "part": s["part"], "score": s["score"]} for s in results
        ]

        return {
            "config": config,
            "sources": source_titles,
            "model": self.model,
            "usage": {
                "prompt_tokens": response.usage.prompt_tokens,
                "completion_tokens": response.usage.completion_tokens,
                "total_tokens": response.usage.total_tokens,
            },
        }

    # ------------------------------------------------------------------
    # Tuning request extraction (V2.4 — frontend free-text → API contract)
    # ------------------------------------------------------------------

    def extract_tuning_request(self, text: str) -> dict[str, Any]:
        """
        Extract a TuningRequest-shaped JSON payload from free-text description.

        Used by the V2.4 frontend TuningPanel: user types a free-form
        description (e.g. "120 BPM Detroit techno in A minor, slight swing"),
        the LLM extracts structured fields, frontend pre-fills the form for
        user review before POST /tuning.

        Args:
            text: User-provided free-text description.

        Returns:
            Dict with keys: bpm, pitch_midi, swing_pct, region, sub_region.
            Matches the api.main.TuningRequest Pydantic contract; downstream
            still validates via the Pydantic model and pandera InferenceSchema.

        Raises:
            ValueError: GPT-4o returned invalid JSON or missing/wrong fields.
            RateLimitError, APITimeoutError, APIConnectionError: transient
                OpenAI errors after 3 retries (propagated by tenacity).
        """
        if not text or not text.strip():
            raise ValueError("text must be a non-empty string")

        response = self._complete(
            system_prompt=TUNING_EXTRACT_SYSTEM_PROMPT,
            user_message=text.strip(),
            temperature=0.1,
            max_tokens=300,
        )
        raw = response.choices[0].message.content
        return self._parse_tuning_extract_output(raw)

    # ------------------------------------------------------------------
    # Output validation
    # ------------------------------------------------------------------

    @staticmethod
    def _parse_compose_output(raw: str) -> dict[str, Any]:
        text = raw.strip()

        # Extract JSON from markdown code fence (handles preamble before fence)
        fence_match = re.search(r"```(?:json)?\s*\n(.*?)```", text, re.DOTALL)
        if fence_match:
            text = fence_match.group(1).strip()
        else:
            # No fence — try to extract raw JSON object
            brace_start = text.find("{")
            brace_end = text.rfind("}")
            if brace_start != -1 and brace_end > brace_start:
                text = text[brace_start : brace_end + 1]

        try:
            config = json.loads(text)
        except json.JSONDecodeError as e:
            raise ValueError(
                f"GPT-4o returned invalid JSON: {e}. Raw output (first 500 chars): {raw[:500]}"
            ) from e

        if not isinstance(config, dict):
            raise ValueError(f"GPT-4o returned {type(config).__name__}, expected dict.")

        required = {"generator", "generator_params", "chain_overrides"}
        missing = required - config.keys()
        if missing:
            raise ValueError(f"GPT-4o config missing required keys: {sorted(missing)}")

        return config

    @staticmethod
    def _parse_tuning_extract_output(raw: str) -> dict[str, Any]:
        """
        Parse and validate GPT-4o tuning extraction output.

        Defence-in-depth: validates types and ranges so a malformed LLM
        response surfaces here rather than at downstream Pydantic /
        pandera boundaries. Cross-field rule (sub_region scope) is also
        checked.
        """
        text = raw.strip()

        fence_match = re.search(r"```(?:json)?\s*\n(.*?)```", text, re.DOTALL)
        if fence_match:
            text = fence_match.group(1).strip()
        else:
            brace_start = text.find("{")
            brace_end = text.rfind("}")
            if brace_start != -1 and brace_end > brace_start:
                text = text[brace_start : brace_end + 1]

        try:
            payload = json.loads(text)
        except json.JSONDecodeError as e:
            raise ValueError(
                f"GPT-4o returned invalid JSON: {e}. "
                f"Raw output (first 500 chars): {raw[:500]}"
            ) from e

        if not isinstance(payload, dict):
            raise ValueError(
                f"GPT-4o returned {type(payload).__name__}, expected dict."
            )

        required = {"bpm", "pitch_midi", "swing_pct", "region", "sub_region"}
        missing = required - payload.keys()
        if missing:
            raise ValueError(
                f"GPT-4o extraction missing required keys: {sorted(missing)}"
            )

        valid_regions = {
            "DETROIT_FIRST_WAVE",
            "DETROIT_UR",
            "DREXCIYA",
            "UK_IDM",
            "UK_BRAINDANCE",
            "JAPAN_IDM",
        }
        valid_sub_regions = {"TOKYO", "OSAKA", None}

        if not isinstance(payload["bpm"], int | float):
            raise ValueError(f"bpm must be a number, got {type(payload['bpm']).__name__}")
        if not 60.0 <= float(payload["bpm"]) <= 240.0:
            raise ValueError(f"bpm out of range [60, 240]: {payload['bpm']}")

        if not isinstance(payload["pitch_midi"], int | float):
            raise ValueError(
                f"pitch_midi must be a number, got {type(payload['pitch_midi']).__name__}"
            )
        if not 0.0 <= float(payload["pitch_midi"]) <= 127.0:
            raise ValueError(
                f"pitch_midi out of range [0, 127]: {payload['pitch_midi']}"
            )

        if not isinstance(payload["swing_pct"], int | float):
            raise ValueError(
                f"swing_pct must be a number, got {type(payload['swing_pct']).__name__}"
            )
        if not 0.0 <= float(payload["swing_pct"]) <= 100.0:
            raise ValueError(
                f"swing_pct out of range [0, 100]: {payload['swing_pct']}"
            )

        if payload["region"] not in valid_regions:
            raise ValueError(
                f"region must be one of {sorted(valid_regions)}, "
                f"got {payload['region']!r}"
            )

        if payload["sub_region"] not in valid_sub_regions:
            raise ValueError(
                f"sub_region must be 'TOKYO', 'OSAKA', or null, "
                f"got {payload['sub_region']!r}"
            )

        if payload["region"] == "JAPAN_IDM" and payload["sub_region"] is None:
            raise ValueError(
                "sub_region must be 'TOKYO' or 'OSAKA' when region == 'JAPAN_IDM'"
            )
        if payload["region"] != "JAPAN_IDM" and payload["sub_region"] is not None:
            raise ValueError(
                f"sub_region must be null when region != 'JAPAN_IDM' "
                f"(got region={payload['region']!r}, sub_region={payload['sub_region']!r})"
            )

        return payload
