"""
streamlit_app/app.py

IDM Generative System — Streamlit Auxiliary UI.

Three tabs:
    1. Sound Design Advisor (Manual mode) — ask questions, get RAG answers
    2. Auto-Composer (Auto mode) — describe aesthetic, get chain config
    3. Effects Explorer — browse all 10 blocks with params and docs

Requires:
    - Qdrant running on localhost:6333
    - OPENAI_API_KEY in .env
    - Knowledge base ingested (43 chunks)

Run:
    cd IDM_Generative_System_app
    streamlit run streamlit_app/app.py
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import streamlit as st

# ---------------------------------------------------------------------------
# Secrets bridge — Streamlit Cloud uses st.secrets, not .env
# Map secrets to env vars so knowledge/ modules work unchanged.
# ---------------------------------------------------------------------------
import os

def _bridge_secrets() -> None:
    """Copy Streamlit secrets to os.environ if available."""
    for key in ("OPENAI_API_KEY", "QDRANT_URL", "QDRANT_API_KEY"):
        if key not in os.environ:
            try:
                os.environ[key] = st.secrets[key]
            except (KeyError, FileNotFoundError):
                pass

_bridge_secrets()

# Ensure project root is on path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from dotenv import load_dotenv
load_dotenv()

from knowledge.rag import RAGPipeline
from engine.effects import CANONICAL_ORDER


# ---------------------------------------------------------------------------
# Page config
# ---------------------------------------------------------------------------

st.set_page_config(
    page_title="IDM Generative System",
    page_icon="🎛",
    layout="wide",
    initial_sidebar_state="collapsed",
)

# ---------------------------------------------------------------------------
# Custom CSS — Sheffield / Designers Republic nod
# ---------------------------------------------------------------------------

st.markdown("""
<style>
    @import url('https://fonts.googleapis.com/css2?family=Space+Mono:wght@400;700&family=Inter:wght@300;400;600&display=swap');

    .stApp {
        background-color: #0a0a0a;
        color: #e0e0e0;
    }

    h1, h2, h3 {
        font-family: 'Space Mono', monospace !important;
        letter-spacing: -0.02em;
    }

    .stMarkdown p, .stMarkdown li {
        font-family: 'Inter', sans-serif;
        font-weight: 300;
        line-height: 1.6;
    }

    .stTabs [data-baseweb="tab-list"] {
        gap: 0px;
        border-bottom: 1px solid #333;
    }

    .stTabs [data-baseweb="tab"] {
        font-family: 'Space Mono', monospace;
        font-size: 0.85rem;
        text-transform: uppercase;
        letter-spacing: 0.1em;
        padding: 12px 24px;
        color: #888;
        border-bottom: 2px solid transparent;
    }

    .stTabs [aria-selected="true"] {
        color: #00ff88 !important;
        border-bottom: 2px solid #00ff88 !important;
    }

    .block-info {
        background: #111;
        border: 1px solid #222;
        border-radius: 4px;
        padding: 16px;
        margin: 8px 0;
        font-family: 'Space Mono', monospace;
    }

    .source-tag {
        display: inline-block;
        background: #1a1a2e;
        border: 1px solid #333;
        border-radius: 3px;
        padding: 2px 8px;
        margin: 2px 4px 2px 0;
        font-size: 0.75rem;
        font-family: 'Space Mono', monospace;
        color: #00ff88;
    }

    .token-info {
        font-family: 'Space Mono', monospace;
        font-size: 0.7rem;
        color: #555;
        text-align: right;
    }

    div[data-testid="stTextInput"] label,
    div[data-testid="stTextArea"] label {
        font-family: 'Space Mono', monospace;
        text-transform: uppercase;
        font-size: 0.75rem;
        letter-spacing: 0.1em;
        color: #888;
    }

    .stButton > button {
        font-family: 'Space Mono', monospace;
        text-transform: uppercase;
        letter-spacing: 0.1em;
        background: #00ff88;
        color: #0a0a0a;
        border: none;
        font-weight: 700;
    }

    .stButton > button:hover {
        background: #00cc6a;
        color: #0a0a0a;
    }
</style>
""", unsafe_allow_html=True)


# ---------------------------------------------------------------------------
# Init
# ---------------------------------------------------------------------------

@st.cache_resource
def get_rag() -> RAGPipeline:
    """Singleton RAG pipeline — cached across reruns."""
    return RAGPipeline()


rag = get_rag()


# ---------------------------------------------------------------------------
# Header
# ---------------------------------------------------------------------------

st.markdown("# 🎛 IDM GENERATIVE SYSTEM")
st.markdown(
    "<span style='font-family: Space Mono; font-size: 0.8rem; color: #555;'>"
    "UNDERGROUND ELECTRONIC ARCHITECTURE — 1987–1999"
    "</span>",
    unsafe_allow_html=True,
)

st.markdown("---")


# ---------------------------------------------------------------------------
# Tabs
# ---------------------------------------------------------------------------

tab_advisor, tab_composer, tab_explorer = st.tabs([
    "⚡ ADVISOR",
    "🔧 COMPOSER",
    "📋 EFFECTS",
])


# ---------------------------------------------------------------------------
# Tab 1 — Sound Design Advisor
# ---------------------------------------------------------------------------

with tab_advisor:
    st.markdown("### Sound Design Advisor")
    st.markdown(
        "Ask anything about DSP, hardware, synthesis techniques, "
        "regional aesthetics, or effects chain configuration."
    )

    question = st.text_area(
        "Question",
        placeholder="How do I recreate the Autechre granular texture from Tri Repetae?",
        height=100,
        key="advisor_question",
    )

    col_btn, col_opts = st.columns([1, 3])

    with col_opts:
        limit = st.slider(
            "Context chunks", min_value=1, max_value=10, value=5, key="advisor_limit"
        )

    with col_btn:
        st.markdown("<br>", unsafe_allow_html=True)
        ask_clicked = st.button("ASK", key="advisor_btn", use_container_width=True)

    if ask_clicked and question.strip():
        with st.spinner("Searching knowledge base + GPT-4o..."):
            result = rag.ask(question=question.strip(), limit=limit)

        st.markdown("#### Answer")
        st.markdown(result["answer"])

        # Sources
        st.markdown("#### Sources")
        sources_html = ""
        for s in result["sources"]:
            sources_html += (
                f'<span class="source-tag">'
                f'{s["title"][:60]} (score: {s["score"]:.3f})'
                f'</span>'
            )
        st.markdown(sources_html, unsafe_allow_html=True)

        # Token usage
        usage = result["usage"]
        st.markdown(
            f'<div class="token-info">'
            f'tokens: {usage["prompt_tokens"]}p + {usage["completion_tokens"]}c '
            f'= {usage["total_tokens"]} | model: {result["model"]}'
            f'</div>',
            unsafe_allow_html=True,
        )


# ---------------------------------------------------------------------------
# Tab 2 — Auto-Composer
# ---------------------------------------------------------------------------

with tab_composer:
    st.markdown("### Auto-Composer")
    st.markdown(
        "Describe an aesthetic — get a complete effects chain configuration. "
        "Output is a JSON config ready for `/generate` or `/process`."
    )

    description = st.text_area(
        "Aesthetic Description",
        placeholder="dark Detroit techno stab with heavy 909 swing and dub delay",
        height=100,
        key="composer_description",
    )

    col_btn2, col_opts2 = st.columns([1, 3])

    with col_opts2:
        limit2 = st.slider(
            "Context chunks", min_value=1, max_value=10, value=5, key="composer_limit"
        )

    with col_btn2:
        st.markdown("<br>", unsafe_allow_html=True)
        compose_clicked = st.button(
            "COMPOSE", key="composer_btn", use_container_width=True
        )

    if compose_clicked and description.strip():
        with st.spinner("Composing with GPT-4o..."):
            result = rag.compose(description=description.strip(), limit=limit2)

        # Parse and display config
        st.markdown("#### Generated Configuration")

        try:
            config = json.loads(result["config"])
            st.json(config)

            # Reasoning (if present)
            if "reasoning" in config:
                st.markdown("#### Reasoning")
                st.markdown(config["reasoning"])

        except json.JSONDecodeError:
            st.markdown("*Raw response (not valid JSON):*")
            st.code(result["config"], language="json")

        # Sources
        st.markdown("#### Sources")
        sources_html = ""
        for s in result["sources"]:
            sources_html += (
                f'<span class="source-tag">'
                f'{s["title"][:60]} (score: {s["score"]:.3f})'
                f'</span>'
            )
        st.markdown(sources_html, unsafe_allow_html=True)

        # Token usage
        usage = result["usage"]
        st.markdown(
            f'<div class="token-info">'
            f'tokens: {usage["prompt_tokens"]}p + {usage["completion_tokens"]}c '
            f'= {usage["total_tokens"]} | model: {result["model"]}'
            f'</div>',
            unsafe_allow_html=True,
        )


# ---------------------------------------------------------------------------
# Tab 3 — Effects Explorer
# ---------------------------------------------------------------------------

with tab_explorer:
    st.markdown("### Effects Chain Explorer")
    st.markdown(
        "All 10 hardware-sourced DSP blocks in canonical signal chain order."
    )

    st.markdown(
        "<div style='font-family: Space Mono; font-size: 0.7rem; color: #555; "
        "padding: 8px; background: #111; border-radius: 4px; "
        "overflow-x: auto; white-space: nowrap;'>"
        "INPUT → NoiseFloor → Bitcrusher → ResonantFilter → Saturation → "
        "Reverb → TapeDelay → SpatialProcessor → GlitchEngine → "
        "Compressor → VinylMastering → OUTPUT"
        "</div>",
        unsafe_allow_html=True,
    )

    st.markdown("")

    for idx, (key, cls) in enumerate(CANONICAL_ORDER):
        with st.expander(
            f"**[{idx}]** {cls.__name__}  —  `{key}`", expanded=False
        ):
            # Docstring
            doc = (cls.__doc__ or "No documentation.").strip()
            st.markdown(f"*{doc[:500]}*")

            # Parameters
            import inspect
            sig = inspect.signature(cls.__init__)
            params = {
                name: param
                for name, param in sig.parameters.items()
                if name != "self"
            }

            if params:
                st.markdown("**Parameters:**")
                for pname, param in params.items():
                    default = (
                        param.default
                        if param.default is not inspect.Parameter.empty
                        else "—"
                    )
                    type_hint = param.annotation
                    type_name = (
                        getattr(type_hint, "__name__", str(type_hint))
                        if type_hint is not inspect.Parameter.empty
                        else "any"
                    )
                    st.markdown(
                        f"- `{pname}` : {type_name} = `{default}`"
                    )
            else:
                st.markdown("*No configurable parameters.*")
