"""
Retrieval module for Erica GraphRAG.

Components:
- concept_embeddings: ChromaDB-based semantic search
- graph_retriever: Neo4j subgraph expansion
- hybrid_retriever: Combined semantic + graph retrieval
"""

from .concept_embeddings import ConceptEmbedder, embed_concepts, search_concepts
from .graph_retriever import (
    GraphRetriever,
    Subgraph,
    RetrievedConcept,
    RetrievedResource,
    RetrievedExample,
)
from .hybrid_retriever import HybridRetriever, RetrievalResult

__all__ = [
    "ConceptEmbedder",
    "embed_concepts",
    "search_concepts",
    "GraphRetriever",
    "Subgraph",
    "RetrievedConcept",
    "RetrievedResource",
    "RetrievedExample",
    "HybridRetriever",
    "RetrievalResult",
]