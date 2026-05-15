"""
api/main.py

FastAPI backend for the IDM Generative System.

Endpoints:
    GET  /health    — liveness check
    GET  /effects   — list available effect blocks with parameter schemas
    POST /generate  — generate a sample and process through effects chain
    POST /process   — upload audio, process through effects chain, return WAV
    POST /synthdef  — generate SuperCollider code from engine configuration
    POST /tidal     — generate TidalCycles code from engine configuration
    POST /ask       — sound design advisor (RAG: Qdrant + GPT-4o)
    POST /compose   — auto-composer (RAG: Qdrant + GPT-4o)

The API is a thin transport layer. All DSP logic lives in engine/.
All audio I/O uses 24-bit WAV at 44100 Hz (matching PO-33/EP-133 specs).
Knowledge retrieval and LLM integration live in knowledge/.

Run:
    uvicorn api.main:app --reload --host 0.0.0.0 --port 8000
"""

from __future__ import annotations

from dotenv import load_dotenv

load_dotenv()

import inspect
import io
import json
import logging
import time
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from importlib.metadata import version as pkg_version
from pathlib import Path
from typing import Any, Union, get_args, get_origin

import numpy as np
import pandas as pd
import soundfile as sf
from fastapi import FastAPI, File, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, ConfigDict, Field, model_validator

from engine.codegen import generate_synthdef, generate_tidal
from engine.effects import (
    CANONICAL_ORDER,
    EffectChain,
    build_chain,
)
from engine.ml.regional_profiles import RegionCode, SubRegion
from engine.sample_maker import SAMPLE_RATE, fm_blip, glitch_click, noise_burst
from knowledge.rag import RAGPipeline

# ---------------------------------------------------------------------------
# Logger (used by V2.3 lifespan and elsewhere)
# ---------------------------------------------------------------------------

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# V2.3 — Model Serving lifespan (model loaded once at startup)
#
# Per V2_ROADMAP §V2.3 + DECISIONS.md (S12 Fix A: TuningEstimator v1
# manually promoted Staging → Production before this lifespan can succeed).
#
# Architecture (industrial-PRO substitutions over spec example):
#   - Modern `lifespan` async context manager replaces deprecated
#     @app.on_event("startup") shown in V2_ROADMAP §V2.3 example.
#   - Fail-soft on model load failure: V1 endpoints continue to serve.
#     app.state.tuning_model = None signals to the /tuning handler
#     (Sub-stage D) to return HTTP 503.
#   - mlflow imported conditionally — CI installs [dev] only, not [ml]
#     extras (D-S7-01, Gotcha #17). Lifespan runs always; no-ops gracefully
#     when mlflow unavailable.
#   - Model metadata (run_id, dataset_dvc_hash) extracted at startup from
#     MLflow Model Registry; cached in app.state.tuning_model_metadata.
#     Single source of truth — no per-request registry calls.
#   - dataset_dvc_hash sourced from MLflow run tag "dvc_dataset_hash";
#     placeholder "unknown" with WARNING log when the tag is absent (the
#     S12 v1 baseline run predates training-side tag logging — see
#     TODO-S13-E for retroactive fix to engine.ml.model_training.train()).
# ---------------------------------------------------------------------------

try:
    import mlflow
    import pandera as pa
    from mlflow.tracking import MlflowClient

    from engine.ml.dataset_schema import InferenceSchema

    _HAS_MLFLOW = True
except ImportError:
    _HAS_MLFLOW = False

# Langfuse is in [monitoring] extras — separately gated from [ml].
# Either can be installed independently; observability is decoupled from
# model serving. (Decision: B + fail-open, S13 sub-stage E planning.)
try:
    from langfuse import Langfuse

    _HAS_LANGFUSE = True
except ImportError:
    _HAS_LANGFUSE = False

_TUNING_MODEL_REGISTRY_NAME = "TuningEstimator"
_TUNING_MODEL_PROD_URI = "models:/TuningEstimator/Production"


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    """FastAPI lifespan — load /tuning model once at startup.

    Modern replacement for the deprecated ``@app.on_event("startup")``
    pattern shown in the V2_ROADMAP §V2.3 spec example. On any failure
    (mlflow not installed, no Production version in registry, network or
    artefact-store error) the lifespan logs a WARNING and leaves
    ``app.state.tuning_model = None`` — the Sub-stage D /tuning handler
    will then return HTTP 503 Service Unavailable. V1 endpoints are
    unaffected.

    Sets two ``app.state`` attributes consumed by the /tuning handler:
        - ``tuning_model``: the loaded ``mlflow.pyfunc.PyFuncModel`` or
          ``None`` on failure.
        - ``tuning_model_metadata``: dict with ``model_version`` (MLflow
          run_id) and ``dataset_dvc_hash`` (MLflow run tag), or ``None``
          on failure.
    """
    # Pre-initialise — handler relies on attributes existing.
    app.state.tuning_model = None
    app.state.tuning_model_metadata = None

    if not _HAS_MLFLOW:
        logger.warning(
            "V2.3 /tuning disabled — mlflow not installed. "
            "Install with `pip install -e '.[ml,monitoring]'` on the "
            "production droplet."
        )
    else:
        try:
            model = mlflow.pyfunc.load_model(_TUNING_MODEL_PROD_URI)
            client = MlflowClient()
            versions = client.get_latest_versions(
                name=_TUNING_MODEL_REGISTRY_NAME,
                stages=["Production"],
            )
            if not versions:
                logger.warning(
                    "V2.3 /tuning disabled — no Production version in "
                    "MLflow Registry for model '%s'. Promote a Staging "
                    "version manually before this lifespan retries.",
                    _TUNING_MODEL_REGISTRY_NAME,
                )
            else:
                mv = versions[0]
                run = client.get_run(mv.run_id)
                dataset_dvc_hash = run.data.tags.get("dvc_dataset_hash", "unknown")

                # Extract target column ordering from training-time MLflow
                # params. The model was logged without an explicit signature
                # (see engine.ml.model_training.train L367-370), so
                # model.predict returns a raw np.ndarray of shape (1, n_targets)
                # with no column metadata. We need the names to shape the
                # /tuning response. train() logs them as a comma-separated
                # string via mlflow.log_params({"target_columns": ...}).
                target_columns_str = run.data.params.get("target_columns", "")
                target_columns = target_columns_str.split(",") if target_columns_str else []

                app.state.tuning_model = model
                app.state.tuning_model_metadata = {
                    "model_version": mv.run_id,
                    "dataset_dvc_hash": dataset_dvc_hash,
                    "target_columns": target_columns,
                }

                if not target_columns:
                    logger.warning(
                        "V2.3 /tuning loaded, but 'target_columns' param "
                        "missing from MLflow run %s — /tuning handler will "
                        "return HTTP 503 because response shaping requires "
                        "column ordering.",
                        mv.run_id,
                    )

                if dataset_dvc_hash == "unknown":
                    logger.warning(
                        "V2.3 /tuning loaded, but 'dvc_dataset_hash' tag "
                        "missing from MLflow run %s — TuningResponse "
                        "provenance field will read 'unknown'. See "
                        "TODO-S13-E for retroactive tag addition.",
                        mv.run_id,
                    )

                logger.info(
                    "V2.3 /tuning ready: %s v%s @ Production "
                    "(run_id=%s..., dvc_hash=%s, n_targets=%d)",
                    _TUNING_MODEL_REGISTRY_NAME,
                    mv.version,
                    mv.run_id[:12],
                    dataset_dvc_hash[:12] if dataset_dvc_hash != "unknown" else "unknown",
                    len(target_columns),
                )
        except Exception as e:
            logger.warning(
                "V2.3 /tuning disabled — model load failed: %s. "
                "V1 endpoints continue to serve normally.",
                e,
            )

    # -----------------------------------------------------------------------
    # Langfuse tracing client init (separate fail-soft block — observability
    # is independent from model serving; either can succeed without the other,
    # per decision "B + fail-open" from S13 sub-stage C planning).
    # -----------------------------------------------------------------------
    app.state.langfuse_client = None
    if not _HAS_LANGFUSE:
        logger.warning(
            "V2.3 Langfuse tracing disabled — langfuse package not installed. "
            "Install with `pip install -e '.[monitoring]'` on the production "
            "droplet (or '.[ml,monitoring]' for full V2.3 stack)."
        )
    else:
        try:
            langfuse_client = Langfuse()
            if langfuse_client.auth_check():
                app.state.langfuse_client = langfuse_client
                logger.info("V2.3 Langfuse tracing ready: client authenticated.")
            else:
                logger.warning(
                    "V2.3 Langfuse tracing disabled — auth_check returned "
                    "False. Verify LANGFUSE_PUBLIC_KEY / LANGFUSE_SECRET_KEY "
                    "/ LANGFUSE_HOST env vars match an active Langfuse "
                    "project."
                )
        except Exception as e:
            logger.warning(
                "V2.3 Langfuse tracing disabled — client init failed: %s. "
                "Endpoint will serve without tracing.",
                e,
            )

    yield

    # SHUTDOWN — flush any buffered Langfuse events before teardown (Langfuse
    # SDK is async / batched; short-lived apps must flush or lose events).
    if app.state.langfuse_client is not None:
        try:
            app.state.langfuse_client.flush()
        except Exception as e:
            logger.warning("Langfuse flush on shutdown failed: %s.", e)

    # mlflow.pyfunc.PyFuncModel has no close() method; GC handles the model
    # object on app teardown.
    logger.info("FastAPI shutdown complete")


# ---------------------------------------------------------------------------
# App
# ---------------------------------------------------------------------------

app = FastAPI(
    title="IDM Generative System",
    version=pkg_version("idm-generative-system"),
    description=(
        "Generative IDM audio engine — algorithmic sample generation, "
        "a 10-block hardware-sourced DSP effects chain, and RAG-powered "
        "sound design advisor."
    ),
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://localhost:3000"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ---------------------------------------------------------------------------
# Singletons
# ---------------------------------------------------------------------------

GENERATORS: dict[str, Any] = {
    "glitch_click": glitch_click,
    "noise_burst": noise_burst,
    "fm_blip": fm_blip,
}

rag = RAGPipeline()


# ---------------------------------------------------------------------------
# Request / response models
# ---------------------------------------------------------------------------


class GenerateRequest(BaseModel):
    """Request body for /generate."""

    generator: str = Field(
        default="glitch_click",
        description=(
            "Sample generator function. Options: 'glitch_click', 'noise_burst', 'fm_blip'."
        ),
    )
    generator_params: dict[str, Any] = Field(
        default_factory=dict,
        description="Keyword arguments forwarded to the generator function.",
    )
    chain_overrides: dict[str, dict[str, Any]] = Field(
        default_factory=dict,
        description=(
            "Per-block parameter overrides for the effects chain. "
            "Keys: 'noise_floor', 'bitcrusher', 'filter', 'saturation', "
            "'reverb', 'delay', 'spatial', 'glitch', 'compressor', 'vinyl'."
        ),
    )
    chain_skip: list[str] = Field(
        default_factory=list,
        description="Block keys to skip in the chain.",
    )
    bypass_chain: bool = Field(
        default=False,
        description="If true, return the raw generated sample without effects.",
    )


class ProcessRequest(BaseModel):
    """Query parameters for /process (chain config sent alongside file)."""

    chain_overrides: dict[str, dict[str, Any]] = Field(
        default_factory=dict,
        description="Per-block parameter overrides.",
    )
    chain_skip: list[str] = Field(
        default_factory=list,
        description="Block keys to skip.",
    )
    bypass_chain: bool = Field(
        default=False,
        description="If true, return the uploaded audio unchanged.",
    )


class AskRequest(BaseModel):
    """Request body for /ask."""

    question: str = Field(
        ...,
        description="Natural language question about sound design, DSP, or hardware.",
        min_length=3,
    )
    limit: int = Field(
        default=5,
        ge=1,
        le=10,
        description="Max number of knowledge base chunks to retrieve.",
    )
    part_filter: str | None = Field(
        default=None,
        description="Optional — restrict search to a specific PART number.",
    )


class ComposeRequest(BaseModel):
    """Request body for /compose."""

    description: str = Field(
        ...,
        description="Aesthetic description for auto-composition.",
        min_length=3,
    )
    limit: int = Field(
        default=5,
        ge=1,
        le=10,
        description="Max number of knowledge base chunks for context.",
    )


class CodegenRequest(BaseModel):
    """Request body for /synthdef and /tidal."""

    generator: str = Field(
        default="glitch_click",
        description="Sample generator. Options: 'glitch_click', 'noise_burst', 'fm_blip'.",
    )
    generator_params: dict[str, Any] = Field(
        default_factory=dict,
        description="Keyword arguments for the generator function.",
    )
    effects: dict[str, dict[str, Any]] = Field(
        default_factory=dict,
        description=(
            "Per-block effect parameters. Only blocks present are included in output. "
            "Keys: 'noise_floor', 'bitcrusher', 'filter', 'saturation', "
            "'reverb', 'delay', 'spatial', 'glitch', 'compressor', 'vinyl'."
        ),
    )
    pattern: dict[str, Any] | None = Field(
        default=None,
        description=(
            "Pattern configuration. Required key: 'type' (euclidean/probabilistic/density). "
            "Euclidean: {'type': 'euclidean', 'pulses': {'kick': 5}, 'steps': 16}. "
            "Density: {'type': 'density', 'density': 0.3, 'steps': 16}."
        ),
    )
    mode: str = Field(
        default="studio",
        description="Generation mode: 'studio' (self-contained) or 'live' (hot-swap).",
    )
    include_pattern: bool = Field(
        default=True,
        description="Include pattern code (Pbind/Pdef for SC, d1/d2 for Tidal).",
    )
    bpm: float = Field(
        default=120.0,
        ge=20.0,
        le=300.0,
        description="Beats per minute — controls pattern timing.",
    )
    bus_offset: int = Field(
        default=16,
        ge=0,
        le=128,
        description="Starting private bus number (SuperCollider only).",
    )


class CodegenResponse(BaseModel):
    """Response body for /synthdef and /tidal."""

    code: str = Field(description="Generated source code string.")
    target: str = Field(description="Target language: 'supercollider' or 'tidalcycles'.")
    mode: str = Field(description="Generation mode used: 'studio' or 'live'.")
    warnings: list[str] = Field(
        default_factory=list,
        description="Mapping approximation warnings.",
    )
    unmapped_params: dict[str, list[str]] = Field(
        default_factory=dict,
        description="Parameters with no target equivalent (documented, not dropped).",
    )
    metadata: dict[str, Any] = Field(
        default_factory=dict,
        description="Target-specific metadata (SynthDef names, bus allocation, etc.).",
    )
    setup_notes: list[str] = Field(
        default_factory=list,
        description="User-facing setup instructions for the generated code.",
    )


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _signal_to_wav_response(
    signal: np.ndarray,
    sr: int = SAMPLE_RATE,
    filename: str = "output.wav",
) -> StreamingResponse:
    """
    Encode a numpy signal as 24-bit WAV and return as a streaming response.

    24-bit matches PO-33 / EP-133 import specs and preserves full
    dynamic range from the effects chain.
    """
    buf = io.BytesIO()
    sf.write(buf, signal, sr, subtype="PCM_24", format="WAV")
    buf.seek(0)

    return StreamingResponse(
        buf,
        media_type="audio/wav",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


def _process_through_chain(
    signal: np.ndarray,
    chain: EffectChain,
    sr: int = SAMPLE_RATE,
    tail_seconds: float = 2.0,
    silence_threshold_db: float = -60.0,
    safety_margin_s: float = 0.1,
) -> np.ndarray:
    """
    Process signal through effects chain with tail padding and trim.

    Pads the input with silence so reverb/delay tails decay naturally,
    then trims trailing silence from the output. This is the canonical
    processing path — both /generate and /process must use it.

    Decision ref: DECISIONS.md 2026-03-26 (2-second tail padding).

    Args:
        signal:               Input audio array.
        chain:                Configured EffectChain instance.
        sr:                   Sample rate in Hz.
        tail_seconds:         Silence to append before processing.
        silence_threshold_db: Trim threshold in dB (below = silence).
        safety_margin_s:      Extra time kept after last audible sample.

    Returns:
        Processed and trimmed audio array.
    """
    # Pad with silence so reverb/delay tails can decay naturally
    tail_samples = int(tail_seconds * sr)
    padded = np.concatenate([signal, np.zeros(tail_samples)])

    processed = chain(padded)

    # Trim trailing silence
    threshold = 10.0 ** (silence_threshold_db / 20.0)
    above = np.where(np.abs(processed) > threshold)[0]
    if len(above) > 0:
        end = min(above[-1] + int(safety_margin_s * sr), len(processed))
        processed = processed[:end]

    return processed


def _format_type_hint(type_hint: type) -> str:
    """Format a type hint into a human-readable string.

    Handles Optional[X] (Union[X, None]), Union[X, Y], and plain types.
    Used by _extract_param_schema to produce readable type names for the
    /effects endpoint response.

    Examples:
        int                   → "int"
        Optional[float]       → "float | null"
        Union[str, int]       → "str | int"
        list[str]             → "list[str]"
    """
    origin = get_origin(type_hint)
    if origin is Union:
        args = get_args(type_hint)
        non_none = [a for a in args if a is not type(None)]
        if len(non_none) == 1 and type(None) in args:
            # Optional[X] — display as "X | null"
            return f"{_format_type_hint(non_none[0])} | null"
        return " | ".join(_format_type_hint(a) for a in args)
    return getattr(type_hint, "__name__", str(type_hint))


def _extract_param_schema(cls: type) -> dict[str, Any]:
    """
    Extract constructor parameters and their defaults from an effect class.

    Returns a dict of {param_name: {type, default, doc}} for use in the
    /effects endpoint. Skips 'self' and private params.
    """
    sig = inspect.signature(cls.__init__)
    params = {}
    for name, param in sig.parameters.items():
        if name == "self":
            continue

        default = param.default if param.default is not inspect.Parameter.empty else None

        # Convert numpy types to native Python for JSON serialisation
        if isinstance(default, (np.integer,)):
            default = int(default)
        elif isinstance(default, (np.floating,)):
            default = float(default)

        type_hint = param.annotation
        type_name = (
            _format_type_hint(type_hint) if type_hint is not inspect.Parameter.empty else "any"
        )

        params[name] = {
            "type": type_name,
            "default": default,
        }

    return params


# Valid block keys derived from canonical chain order — single source of truth
_VALID_CHAIN_KEYS: set[str] = {key for key, _ in CANONICAL_ORDER}

# Maximum file size accepted by /process — enforced before audio decoding
MAX_UPLOAD_BYTES: int = 50 * 1024 * 1024  # 50 MB


def _validate_chain_keys(
    overrides: dict[str, Any] | None,
    skip: list[str] | None,
) -> None:
    """
    Validate that chain_overrides keys and chain_skip entries are
    recognised block names. Raises HTTPException 400 on invalid keys.
    """
    if overrides:
        invalid = set(overrides.keys()) - _VALID_CHAIN_KEYS
        if invalid:
            raise HTTPException(
                status_code=400,
                detail=(
                    f"Unknown chain block keys in overrides: {sorted(invalid)}. "
                    f"Valid: {sorted(_VALID_CHAIN_KEYS)}"
                ),
            )

    if skip:
        invalid = set(skip) - _VALID_CHAIN_KEYS
        if invalid:
            raise HTTPException(
                status_code=400,
                detail=(
                    f"Unknown chain block keys in skip: {sorted(invalid)}. "
                    f"Valid: {sorted(_VALID_CHAIN_KEYS)}"
                ),
            )


# ---------------------------------------------------------------------------
# Endpoints — DSP
# ---------------------------------------------------------------------------


@app.get("/health")
async def health() -> dict[str, str]:
    """Liveness check."""
    return {"status": "ok", "version": app.version}


@app.get("/effects")
async def list_effects() -> list[dict[str, Any]]:
    """
    List all available effect blocks with their parameter schemas.

    Returns the canonical chain order. Each entry includes the block key,
    class name, position in the chain (0–9), and a full parameter schema
    with types and defaults.

    This endpoint is self-documenting — a frontend can use it to
    dynamically build a configuration UI for the effects chain.
    """
    result = []
    for idx, (key, cls) in enumerate(CANONICAL_ORDER):
        result.append(
            {
                "position": idx,
                "key": key,
                "class_name": cls.__name__,
                "params": _extract_param_schema(cls),
                "docstring": (cls.__doc__ or "").strip()[:500],
            }
        )
    return result


@app.post("/generate")
async def generate(req: GenerateRequest) -> StreamingResponse:
    """
    Generate a sample and process it through the effects chain.

    1. Calls the selected generator function with provided params.
    2. Builds the effects chain with optional overrides/skips.
    3. Returns the processed audio as a 24-bit WAV file.
    """
    # Validate generator
    gen_fn = GENERATORS.get(req.generator)
    if gen_fn is None:
        raise HTTPException(
            status_code=400,
            detail=(f"Unknown generator '{req.generator}'. Options: {list(GENERATORS.keys())}"),
        )

    # Generate raw sample — randomise params if none provided
    params = dict(req.generator_params)
    if not params:
        if req.generator == "glitch_click":
            params = {
                "length_ms": float(np.random.uniform(150, 500)),
                "decay": float(np.random.uniform(2.0, 5.0)),
            }
        elif req.generator == "noise_burst":
            params = {
                "length_ms": float(np.random.uniform(200, 800)),
                "tone": float(np.random.uniform(0.0, 1.0)),
                "decay": float(np.random.uniform(1.5, 6.0)),
            }
        elif req.generator == "fm_blip":
            params = {
                "freq": float(np.random.uniform(80, 2000)),
                "mod_freq": float(np.random.uniform(20, 500)),
                "mod_index": float(np.random.uniform(0.5, 8.0)),
                "length_ms": float(np.random.uniform(200, 800)),
                "decay": float(np.random.uniform(1.5, 6.0)),
            }

    try:
        signal = gen_fn(**params)
    except TypeError as e:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid generator params: {e}",
        ) from e
    # Ensure float64 for effects chain
    signal = signal.astype(np.float64)

    # Normalise to [-1.0, 1.0] if needed
    peak = np.max(np.abs(signal))
    if peak > 1.0:
        signal = signal / peak

    # Process through effects chain
    if not req.bypass_chain:
        _validate_chain_keys(req.chain_overrides, req.chain_skip)
        chain = build_chain(
            overrides=req.chain_overrides or None,
            skip=req.chain_skip or None,
        )
        signal = _process_through_chain(signal, chain)

    return _signal_to_wav_response(signal, filename="generated.wav")


@app.post("/process")
async def process_audio(
    file: UploadFile = File(..., description="WAV audio file to process"),
    chain_overrides: str = "{}",
    chain_skip: str = "[]",
    bypass_chain: bool = False,
) -> StreamingResponse:
    """
    Upload a WAV file, process it through the effects chain, return WAV.

    Chain configuration is passed as JSON strings in form fields
    (multipart/form-data limitation — file + JSON body not supported).

    Args:
        file:            WAV audio file.
        chain_overrides: JSON string of per-block overrides.
        chain_skip:      JSON string of block keys to skip.
        bypass_chain:    If true, return uploaded audio unchanged.
    """
    # Parse JSON config from form fields
    try:
        overrides = json.loads(chain_overrides)
    except json.JSONDecodeError:
        raise HTTPException(status_code=400, detail="Invalid chain_overrides JSON.") from None

    try:
        skip = json.loads(chain_skip)
    except json.JSONDecodeError:
        raise HTTPException(status_code=400, detail="Invalid chain_skip JSON.") from None

    # Read uploaded audio
    try:
        contents = await file.read()
        if len(contents) > MAX_UPLOAD_BYTES:
            raise HTTPException(
                status_code=413,
                detail=(
                    f"File too large ({len(contents) / (1024 * 1024):.1f} MB). "
                    f"Maximum: {MAX_UPLOAD_BYTES // (1024 * 1024)} MB."
                ),
            )
        audio_buf = io.BytesIO(contents)
        signal, sr = sf.read(audio_buf, dtype="float64")
    except Exception as e:
        raise HTTPException(
            status_code=400,
            detail=f"Could not read audio file: {e}",
        ) from e

    # Handle stereo → mono (effects chain is mono)
    if signal.ndim == 2:
        signal = np.mean(signal, axis=1)

    # Normalise to [-1.0, 1.0]
    peak = np.max(np.abs(signal))
    if peak > 0.0:
        signal = signal / peak

    # Process
    if not bypass_chain:
        _validate_chain_keys(overrides, skip)
        chain = build_chain(
            overrides=overrides or None,
            skip=skip or None,
        )
        signal = _process_through_chain(signal, chain, sr=sr)

    return _signal_to_wav_response(signal, sr=sr, filename="processed.wav")


# ---------------------------------------------------------------------------
# Endpoints — Code Generation (SuperCollider / TidalCycles)
# ---------------------------------------------------------------------------


def _codegen_result_to_response(result: Any) -> CodegenResponse:
    """Convert a CodegenResult dataclass to a Pydantic response model."""
    return CodegenResponse(
        code=result.code,
        target=result.target.value,
        mode=result.mode.value,
        warnings=result.warnings,
        unmapped_params=result.unmapped_params,
        metadata=result.metadata,
        setup_notes=result.setup_notes,
    )


@app.post("/synthdef", response_model=CodegenResponse)
async def synthdef(req: CodegenRequest) -> CodegenResponse:
    """
    Generate SuperCollider (.scd) code from engine configuration.

    Produces composable SynthDefs with bus routing, group ordering,
    and optional Pbind/Pdef pattern code. Supports studio and live modes.

    Returns:
        code:            Generated SuperCollider source code.
        target:          'supercollider'.
        mode:            Generation mode used ('studio' or 'live').
        warnings:        Mapping approximation warnings.
        unmapped_params: Parameters with no SC equivalent.
        metadata:        SynthDef names, bus allocation, effects chain.
        setup_notes:     User-facing setup instructions.
    """
    try:
        result = generate_synthdef(
            generator=req.generator,
            generator_params=req.generator_params,
            effects=req.effects,
            pattern=req.pattern,
            mode=req.mode,
            include_pattern=req.include_pattern,
            bpm=req.bpm,
            bus_offset=req.bus_offset,
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Code generation error: {e}") from e

    return _codegen_result_to_response(result)


@app.post("/tidal", response_model=CodegenResponse)
async def tidal(req: CodegenRequest) -> CodegenResponse:
    """
    Generate TidalCycles (Haskell DSL) code from engine configuration.

    Produces ready-to-evaluate Tidal patterns with effect chains.
    Supports studio (full setup) and live (bare patterns) modes.

    Returns:
        code:            Generated TidalCycles source code.
        target:          'tidalcycles'.
        mode:            Generation mode used ('studio' or 'live').
        warnings:        Mapping approximation warnings.
        unmapped_params: Parameters with no Tidal equivalent.
        metadata:        Tidal sound name, orbit assignments, BPM.
        setup_notes:     User-facing setup instructions.
    """
    try:
        result = generate_tidal(
            generator=req.generator,
            generator_params=req.generator_params,
            effects=req.effects,
            pattern=req.pattern,
            mode=req.mode,
            include_pattern=req.include_pattern,
            bpm=req.bpm,
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Code generation error: {e}") from e

    return _codegen_result_to_response(result)


# ---------------------------------------------------------------------------
# Endpoints — RAG (Knowledge Base + GPT-4o)
# ---------------------------------------------------------------------------


@app.post("/ask")
async def ask(req: AskRequest) -> dict:
    """
    Sound design advisor (Manual mode).

    Retrieves relevant context from the knowledge base (Qdrant),
    then uses GPT-4o to answer the question with technical precision.

    Returns:
        answer:  GPT-4o response grounded in the master dataset.
        sources: Retrieved knowledge base chunks with relevance scores.
        model:   GPT model used.
        usage:   Token usage breakdown.
    """
    try:
        result = rag.ask(
            question=req.question,
            limit=req.limit,
            part_filter=req.part_filter,
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"RAG pipeline error: {e}") from e

    return result


@app.post("/compose")
async def compose(req: ComposeRequest) -> dict:
    """
    Auto-composer (Auto mode).

    Given an aesthetic description, retrieves relevant context and uses
    GPT-4o to generate a JSON configuration for the effects chain and
    sample generators.

    Returns:
        config:  JSON string with generator, params, chain overrides.
        sources: Retrieved knowledge base chunks with relevance scores.
        model:   GPT model used.
        usage:   Token usage breakdown.
    """
    try:
        result = rag.compose(
            description=req.description,
            limit=req.limit,
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"RAG pipeline error: {e}") from e

    return result


# ---------------------------------------------------------------------------
# V2 — /tuning endpoint (Model Serving)
#
# Pydantic API contract. Implementation references:
#   - V2_ROADMAP.md §V2.3 (authoritative spec)
#   - DECISIONS.md D-S7-02/03/04 (feature schema), D-S3-05 (sub_region scope)
#   - PROJECT_PROTOCOL.md §3 #11 (extra="forbid"), #16 (pandera declarative)
#
# Field origin (vs V2_ROADMAP v2.0):
#   pitch_class:int[0,11]     → pitch_midi:float[0,127]   (D-S3-05, D-S7-04)
#   swing_pct retained at API → internal swing [0,1] via /100.0 (D-S7-04)
#   genre_profile             → region (+ sub_region for JAPAN_IDM) (D-S7-02)
#   sample_mapping_category   → REMOVED (D-S7-03)
#   effects_density           → REMOVED (D-S7-03)
# ---------------------------------------------------------------------------


class TuningRequest(BaseModel):
    """API contract for the /tuning endpoint.

    Five-field input vector matching the internal feature schema
    materialised by Layer 5 (``dataset_generator``) and Layer 6
    (``model_training``). The ``region`` and ``sub_region`` fields use
    type aliases from ``engine.ml.regional_profiles`` rather than
    hardcoded Literal unions — single source of truth, no drift risk
    (same pattern as ``engine.ml.dataset_schema`` per D-S7-02).
    """

    model_config = ConfigDict(extra="forbid")

    bpm: float = Field(
        ...,
        ge=60.0,
        le=240.0,
        description="Tempo in beats per minute.",
    )
    pitch_midi: float = Field(
        ...,
        ge=0.0,
        le=127.0,
        description=(
            "MIDI note number (A4 = 69). Replaces pitch_class:int[0,11] "
            "from V2_ROADMAP v2.0 (D-S3-05, D-S7-04)."
        ),
    )
    swing_pct: float = Field(
        ...,
        ge=0.0,
        le=100.0,
        description=(
            "Swing percentage [0, 100] for API ergonomics. Converted to "
            "internal swing [0.0, 1.0] at the handler boundary "
            "(swing = swing_pct / 100.0) per D-S7-04 before model.predict."
        ),
    )
    region: RegionCode = Field(
        ...,
        description=(
            "Regional profile identifier. Mirrors the RegionCode type "
            "alias in engine/ml/regional_profiles.py (D-S7-02). Renamed "
            "from genre_profile (V2_ROADMAP v2.0)."
        ),
    )
    sub_region: SubRegion | None = Field(
        default=None,
        description=(
            "Sub-region discriminator. Required when region == "
            "'JAPAN_IDM', MUST be None otherwise (D-S3-05, D-S7-02). "
            "Cross-field validation enforced by _validate_sub_region "
            "below; pandera InferenceSchema (Sub-stage B) provides "
            "DataFrame-level defence in depth."
        ),
    )

    @model_validator(mode="after")
    def _validate_sub_region(self) -> TuningRequest:
        """Cross-field rule: sub_region scope tied to JAPAN_IDM.

        Pydantic v2 wraps the raised ``ValueError`` into a
        ``ValidationError``; FastAPI surfaces it as HTTP 422.
        """
        if self.region == "JAPAN_IDM" and self.sub_region is None:
            msg = "sub_region required when region == 'JAPAN_IDM'"
            raise ValueError(msg)
        if self.region != "JAPAN_IDM" and self.sub_region is not None:
            msg = "sub_region must be None when region != 'JAPAN_IDM'"
            raise ValueError(msg)
        return self


class ResonantPoint(BaseModel):
    """A single resonant frequency point with provenance and confidence.

    Variable-cardinality element of ``TuningResponse.resonant_points``.
    Mirrors the ``(hz, label, confidence)`` shape of the internal
    ``ResonantPoint`` dataclass produced by
    ``engine.ml.deterministic_mapper``, in API-serialisable form.
    """

    model_config = ConfigDict(extra="forbid")

    hz: float = Field(
        ...,
        gt=0.0,
        description="Frequency in Hertz. Must be positive.",
    )
    label: str = Field(
        ...,
        min_length=1,
        description=(
            "Provenance tag — e.g. 'Earth resonance 2x', 'Solfeggio MI', 'mains_hum_50hz_h4'."
        ),
    )
    confidence: float = Field(
        ...,
        ge=0.0,
        le=1.0,
        description="Model confidence in [0.0, 1.0].",
    )


class TuningResponse(BaseModel):
    """API response from the /tuning endpoint.

    Returns the predicted A4 tuning reference plus a variable-cardinality
    list of resonant frequency points. Cardinality of ``resonant_points``
    corresponds to the non-NaN ``freq_*`` columns in the trained model's
    output schema, which varies per region (per V2_ROADMAP §V2.1).

    ``protected_namespaces=()`` is set explicitly to allow the
    ``model_version`` field name (Pydantic v2 reserves the ``model_``
    prefix by default). The field name is locked by V2_ROADMAP §V2.3
    spec — we permit it here without renaming.
    """

    model_config = ConfigDict(extra="forbid", protected_namespaces=())

    tuning_hz: float = Field(
        ...,
        gt=0.0,
        description=(
            "A4 reference frequency selected by the model. Discrete "
            "value (typically 432.0 or 440.0) per D-S5-01."
        ),
    )
    resonant_points: list[ResonantPoint] = Field(
        ...,
        description=(
            "Resonant frequency points. Variable cardinality per region "
            "(NOT fixed-8 as in V2_ROADMAP v2.0); count corresponds to "
            "non-NaN freq_* columns in the trained model output. Ranked "
            "by confidence descending."
        ),
    )
    model_version: str = Field(
        ...,
        description=(
            "MLflow run_id of the loaded model. Populated from "
            "app.state.tuning_model_metadata at request time "
            "(Sub-stage C — lifespan)."
        ),
    )
    dataset_dvc_hash: str = Field(
        ...,
        description=(
            "DVC content hash of the training dataset. Provenance "
            "signal for reproducibility — pairs ``model_version`` with "
            "the exact data that produced it."
        ),
    )
    inference_latency_ms: float = Field(
        ...,
        ge=0.0,
        description=(
            "Wall-clock latency of the model.predict call only "
            "(excludes Pydantic validation, pandera validation, "
            "response shaping, and network I/O)."
        ),
    )


# ---------------------------------------------------------------------------
# V2.3 — /tuning endpoint handler (Sub-stage D)
#
# 5-step flow per V2_ROADMAP §V2.3:
#   1. 503 gate — model loaded? (fail-soft from lifespan honored here)
#   2. Boundary conversion swing_pct → swing (D-S7-04)
#   3. Build inference DataFrame; pandera InferenceSchema validates
#   4. NaN sentinel for sub_region (mirror prepare_data L275); predict
#   5. Response shaping — scalar tuning_hz + variable list[ResonantPoint]
#
# Registration is gated on _HAS_MLFLOW. When [ml] extras are absent (CI /
# local dev without `pip install .[ml,monitoring]`), /tuning is NOT
# registered and FastAPI returns 404 for that path. Production droplet
# always has [ml] installed, so 404 is unreachable there.
# ---------------------------------------------------------------------------

# Minimum hz to keep as resonant point in response. Filters out XGBoost
# regression predictions for "absent" freq_* columns — those train as 0.0
# via engine.ml.model_training.prepare_data().fillna(0.0) and predict as
# low-magnitude noise floats (~ ±1.0). Threshold of 1.0 Hz sits in the gap
# between prediction noise and any legitimate MASTER_DATASET resonant
# point (Schumann fundamental ~7.83 Hz, Drexciya sub-bass minimum ~16 Hz).
# Reference: DATASET_SCHEMA freq_* check is pa.Check.gt(0); legitimate
# values are always >> 1.
_RESONANT_POINT_MIN_HZ: float = 1.0

# Placeholder confidence value for resonant point predictions. XGBoost
# regression does NOT natively expose prediction confidence; quantile
# regression / conformal prediction would be the proper signal.
# See TODO-S13-F for that future iteration. Static 1.0 documents the gap
# transparently rather than fabricating false uncertainty.
_RESONANT_POINT_DEFAULT_CONFIDENCE: float = 1.0


if _HAS_MLFLOW:

    @app.post("/tuning", response_model=TuningResponse)
    async def tuning(request: TuningRequest) -> TuningResponse:
        """Predict A4 tuning + resonant frequency points for a generative context.

        Five-step flow per V2_ROADMAP §V2.3. Returns a fully shaped
        :class:`TuningResponse` on success; raises HTTPException(503) when
        the model is unavailable (lifespan fail-soft path) and
        HTTPException(422) on pandera schema violations from the inference
        DataFrame (defence in depth — TuningRequest @model_validator
        catches the same case earlier).
        """
        # Step 1 — 503 gate. Lifespan fail-soft sets tuning_model = None when
        # MLflow Registry / S3 / network blip prevents model load. Handler
        # honors that signal and returns Service Unavailable.
        if app.state.tuning_model is None:
            raise HTTPException(
                status_code=503,
                detail=(
                    "Tuning model unavailable — lifespan failed to load the "
                    "model at startup. Check server logs for the underlying "
                    "error; restart the application once resolved."
                ),
            )

        target_columns: list[str] = app.state.tuning_model_metadata.get("target_columns", [])
        if not target_columns:
            # Lifespan logged a WARNING at startup. Cannot shape response
            # without column ordering — fail closed rather than guess.
            raise HTTPException(
                status_code=503,
                detail=(
                    "Tuning model metadata incomplete — target_columns "
                    "missing from MLflow run params. Re-train so "
                    "engine.ml.model_training.train() logs target_columns "
                    "(currently it does — see L355 — so a missing value "
                    "indicates registry corruption)."
                ),
            )

        # Step 2 — boundary conversion (D-S7-04). External API speaks
        # swing_pct in [0, 100]; internal model speaks swing in [0.0, 1.0].
        payload = request.model_dump()
        payload["swing"] = payload.pop("swing_pct") / 100.0

        # -------------------------------------------------------------------
        # Langfuse trace span — opened here (after 503 gates, after payload
        # built) so the trace captures only valid-shape requests. Fail-open
        # at every hook (start, update, end) — Langfuse SDK promises its own
        # fail-open semantics, but we add defense-in-depth wrappers because
        # observability MUST NOT block business path (decision B + fail-open).
        # -------------------------------------------------------------------
        trace_input = {
            "bpm": payload["bpm"],
            "pitch_midi": payload["pitch_midi"],
            "swing_pct": request.swing_pct,
            "swing_internal": payload["swing"],
            "region": payload["region"],
            "sub_region": payload["sub_region"],
        }

        trace_span = None
        if app.state.langfuse_client is not None:
            try:
                trace_span = app.state.langfuse_client.start_observation(
                    as_type="span",
                    name="POST /tuning",
                    input=trace_input,
                )
            except Exception as e:
                logger.warning(
                    "Langfuse span start failed: %s. Request continues without trace.",
                    e,
                )
                trace_span = None

        try:
            # Step 3 — build inference DataFrame; pandera InferenceSchema
            # validate. Pydantic @model_validator already enforced the
            # sub_region cross-field rule at request parsing; this is defence
            # in depth at the DataFrame level.
            df_validate = pd.DataFrame([payload])
            try:
                InferenceSchema.validate(df_validate)
            except (pa.errors.SchemaError, pa.errors.SchemaErrors) as e:
                raise HTTPException(
                    status_code=422,
                    detail=f"Inference schema violation: {e}",
                ) from e

            # Step 4 — NaN sentinel for sub_region (mirror prepare_data L275
            # in engine.ml.model_training); model.predict with latency timing.
            # The OrdinalEncoder in the trained pipeline expects "__NaN__" as
            # the sentinel category for missing sub_region; pandera tolerates
            # None (nullable=True), so we substitute AFTER schema validation.
            df_predict = df_validate.copy()
            df_predict["sub_region"] = df_predict["sub_region"].fillna("__NaN__")

            t0 = time.monotonic()
            raw_predictions = app.state.tuning_model.predict(df_predict)
            latency_ms = (time.monotonic() - t0) * 1000.0

            # Step 5 — response shaping. raw_predictions is np.ndarray of
            # shape (1, n_targets) because the model was logged without an
            # mlflow signature (see engine.ml.model_training.train L367-370).
            # Coerce to DataFrame using target_columns captured at lifespan
            # time.
            predictions_2d = (
                raw_predictions
                if hasattr(raw_predictions, "ndim") and raw_predictions.ndim == 2
                else np.asarray(raw_predictions).reshape(1, -1)
            )
            predictions_df = pd.DataFrame(predictions_2d, columns=target_columns)

            tuning_hz = float(predictions_df["tuning_hz"].iloc[0])

            resonant_points: list[ResonantPoint] = []
            for col in target_columns:
                if not col.startswith("freq_"):
                    continue
                hz = float(predictions_df[col].iloc[0])
                if hz < _RESONANT_POINT_MIN_HZ:
                    # XGBoost regression for "absent" freq_* targets (trained
                    # as 0.0) predicts low-magnitude noise; filter per
                    # _RESONANT_POINT_MIN_HZ rationale above.
                    continue
                resonant_points.append(
                    ResonantPoint(
                        hz=hz,
                        label=col.removeprefix("freq_"),
                        confidence=_RESONANT_POINT_DEFAULT_CONFIDENCE,
                    )
                )

            # Rank by confidence descending; tie-break by hz ascending for
            # deterministic output. With placeholder confidence=1.0 for all
            # points (TODO-S13-F), ordering reduces to hz ascending. When
            # real confidence is wired (quantile regression / conformal
            # prediction), this primary sort key takes effect naturally.
            resonant_points.sort(key=lambda rp: (-rp.confidence, rp.hz))

            response = TuningResponse(
                tuning_hz=tuning_hz,
                resonant_points=resonant_points,
                model_version=app.state.tuning_model_metadata["model_version"],
                dataset_dvc_hash=app.state.tuning_model_metadata["dataset_dvc_hash"],
                inference_latency_ms=latency_ms,
            )

            # Trace update with output + metadata (fail-open).
            if trace_span is not None:
                try:
                    trace_span.update(
                        output={
                            "tuning_hz": tuning_hz,
                            "n_resonant_points": len(resonant_points),
                            "inference_latency_ms": latency_ms,
                        },
                        metadata={
                            "model_version": app.state.tuning_model_metadata["model_version"],
                            "dataset_dvc_hash": app.state.tuning_model_metadata["dataset_dvc_hash"],
                            "n_targets": len(target_columns),
                        },
                    )
                except Exception as e:
                    logger.warning("Langfuse span update failed: %s.", e)

            return response
        finally:
            # End span unconditionally (fail-open). The trace will record
            # latency even if the response shaping raised an exception above —
            # useful for production debugging.
            if trace_span is not None:
                try:
                    trace_span.end()
                except Exception as e:
                    logger.warning("Langfuse span end failed: %s.", e)


# ---------------------------------------------------------------------------
# Static frontend serving (production only — Vite bundle in /app/static)
# ---------------------------------------------------------------------------


STATIC_DIR = Path(__file__).resolve().parent.parent / "static"

if STATIC_DIR.is_dir():
    # Serve Vite hashed assets (/assets/index-XXXXX.js, /assets/index-XXXXX.css).
    app.mount("/assets", StaticFiles(directory=STATIC_DIR / "assets"), name="assets")

    # Serve files in static root (favicon.ico, manifest.json, etc.).
    app.mount("/static-root", StaticFiles(directory=STATIC_DIR), name="static-root")

    @app.get("/{full_path:path}")
    async def serve_spa(full_path: str) -> FileResponse:
        """SPA catch-all — return index.html for any unmatched GET request.

        FastAPI evaluates routes in registration order. All API routes are
        registered before this catch-all, so /health, /generate, etc. take
        priority. Only genuinely unmatched paths (/, /advisor, /codegen, etc.)
        reach this handler.
        """
        return FileResponse(STATIC_DIR / "index.html")
