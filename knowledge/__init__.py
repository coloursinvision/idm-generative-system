"""IDM Generative System — Knowledge package.

RAG pipeline and vector database client for domain-specific
sound design advice and composition configuration generation.
"""

from knowledge.qdrant_client import KnowledgeBase
from knowledge.rag import RAGPipeline

__all__: list[str] = ["KnowledgeBase", "RAGPipeline"]
