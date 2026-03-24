"""
api/main.py

FastAPI backend for the IDM Generative System.

MVP scope — four endpoints:
    GET  /health    — liveness check
    GET  /effects   — list available effect blocks with parameter schemas
    POST /generate  — generate a sample and process through effects chain
    POST /process   — upload audio, process through effects chain, return WAV

The API is a thin transport layer. All DSP logic lives in engine/.
All audio I/O uses 24-bit WAV at 44100 Hz (matching PO-33/EP-133 specs).

Run:
    uvicorn api.main:app --reload --host 0.0.0.0 --port 8000
"""

from __future__ import annotations

import io
import inspect
from typing import Any

import numpy as np
import soundfile as sf
from fastapi import FastAPI, File, HTTPException, UploadFile
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from engine.sample_maker import glitch_click, noise_burst, fm_blip, SAMPLE_RATE
from engine.effects import (
    CANONICAL_ORDER,
    build_chain,
    BaseEffect,
)


# ---------------------------------------------------------------------------
# App
# ---------------------------------------------------------------------------

app = FastAPI(
    title="IDM Generative System",
    version="0.1.0",
    description=(
        "Generative IDM audio engine — algorithmic sample generation "
        "and a 10-block hardware-sourced DSP effects chain."
    ),
)


# ---------------------------------------------------------------------------
# Request / response models
# ---------------------------------------------------------------------------

GENERATORS: dict[str, Any] = {
    "glitch_click": glitch_click,
    "noise_burst":  noise_burst,
    "fm_blip":      fm_blip,
}


class GenerateRequest(BaseModel):
    """Request body for /generate."""

    generator: str = Field(
        default="glitch_click",
        description=(
            "Sample generator function. "
            "Options: 'glitch_click', 'noise_burst', 'fm_blip'."
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

        default = (
            param.default
            if param.default is not inspect.Parameter.empty
            else None
        )

        # Convert numpy types to native Python for JSON serialisation
        if isinstance(default, (np.integer,)):
            default = int(default)
        elif isinstance(default, (np.floating,)):
            default = float(default)

        type_hint = param.annotation
        type_name = (
            getattr(type_hint, "__name__", str(type_hint))
            if type_hint is not inspect.Parameter.empty
            else "any"
        )

        params[name] = {
            "type": type_name,
            "default": default,
        }

    return params


# ---------------------------------------------------------------------------
# Endpoints
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
        result.append({
            "position": idx,
            "key": key,
            "class_name": cls.__name__,
            "params": _extract_param_schema(cls),
            "docstring": (cls.__doc__ or "").strip()[:500],
        })
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
            detail=(
                f"Unknown generator '{req.generator}'. "
                f"Options: {list(GENERATORS.keys())}"
            ),
        )

    # Generate raw sample
    try:
        signal = gen_fn(**req.generator_params)
    except TypeError as e:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid generator params: {e}",
        )

    # Ensure float64 for effects chain
    signal = signal.astype(np.float64)

    # Normalise to [-1.0, 1.0] if needed
    peak = np.max(np.abs(signal))
    if peak > 1.0:
        signal = signal / peak

    # Process through effects chain
    if not req.bypass_chain:
        chain = build_chain(
            overrides=req.chain_overrides or None,
            skip=req.chain_skip or None,
        )
        signal = chain(signal)

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
    import json

    # Parse JSON config from form fields
    try:
        overrides = json.loads(chain_overrides)
    except json.JSONDecodeError:
        raise HTTPException(status_code=400, detail="Invalid chain_overrides JSON.")

    try:
        skip = json.loads(chain_skip)
    except json.JSONDecodeError:
        raise HTTPException(status_code=400, detail="Invalid chain_skip JSON.")

    # Read uploaded audio
    try:
        contents = await file.read()
        audio_buf = io.BytesIO(contents)
        signal, sr = sf.read(audio_buf, dtype="float64")
    except Exception as e:
        raise HTTPException(
            status_code=400,
            detail=f"Could not read audio file: {e}",
        )

    # Handle stereo → mono (effects chain is mono)
    if signal.ndim == 2:
        signal = np.mean(signal, axis=1)

    # Normalise to [-1.0, 1.0]
    peak = np.max(np.abs(signal))
    if peak > 0.0:
        signal = signal / peak

    # Process
    if not bypass_chain:
        chain = build_chain(
            overrides=overrides or None,
            skip=skip or None,
        )
        signal = chain(signal)

    return _signal_to_wav_response(signal, sr=sr, filename="processed.wav")
