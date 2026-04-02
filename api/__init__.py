"""IDM Generative System — API package.

FastAPI backend for audio generation, effects processing,
and RAG-augmented sound design.
"""

from importlib.metadata import PackageNotFoundError, version

try:
    __version__: str = version("idm-generative-system")
except PackageNotFoundError:
    # Package not installed (editable dev mode without pip install -e).
    __version__ = "0.2.2"

__all__: list[str] = ["__version__"]
