"""
Graph construction module for Erica GraphRAG.

Components:
- chunker: Document chunking with metadata preservation
- entity_extractor: LLM-based entity/relation extraction
- neo4j_client: Neo4j database operations (TODO)
- graph_builder: Orchestrates the pipeline (TODO)
"""

from .chunker import Chunk, Chunker, DocumentChunker, chunk_documents
from .entity_extractor import (
    ExtractedConcept,
    ExtractedRelation,
    ExtractionResult,
    EntityExtractor,
    BatchExtractor,
    OpenRouterClient,
    extract_from_mongodb,
)

__all__ = [
    # Chunker
    "Chunk",
    "Chunker", 
    "DocumentChunker",
    "chunk_documents",
    # Entity Extractor
    "ExtractedConcept",
    "ExtractedRelation",
    "ExtractionResult",
    "EntityExtractor",
    "BatchExtractor",
    "OpenRouterClient",
    "extract_from_mongodb",
]