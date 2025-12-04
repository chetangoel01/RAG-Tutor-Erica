"""
Hybrid retriever combining semantic search and graph expansion.

Pipeline:
1. Embed user query
2. Semantic search in ChromaDB for candidate concepts
3. (Optional) LLM extraction of explicit concept mentions
4. Expand seeds via Neo4j graph traversal
5. Return unified subgraph for generation

Usage:
    from src.retrieval.hybrid_retriever import HybridRetriever
    
    retriever = HybridRetriever()
    result = retriever.retrieve("How does backpropagation work?")
"""

from dataclasses import dataclass
from typing import Optional

from .concept_embeddings import ConceptEmbedder
from .graph_retriever import GraphRetriever, Subgraph


@dataclass
class RetrievalResult:
    """Complete retrieval result for answer generation."""
    query: str
    semantic_matches: list[dict]  # Raw ChromaDB results
    seed_concepts: list[str]  # Concepts used as seeds
    subgraph: Subgraph  # Expanded subgraph from Neo4j
    ordered_concepts: list[str]  # Topologically sorted for explanation
    
    def summary(self) -> str:
        """Return a summary of what was retrieved."""
        return (
            f"Query: {self.query}\n"
            f"Seeds: {', '.join(self.seed_concepts)}\n"
            f"Concepts: {len(self.subgraph.concepts)}\n"
            f"Resources: {len(self.subgraph.resources)}\n"
            f"Examples: {len(self.subgraph.examples)}\n"
            f"Order: {' → '.join(self.ordered_concepts[:5])}..."
        )


class HybridRetriever:
    """
    Combines semantic search with graph-based retrieval.
    """
    
    def __init__(
        self,
        mongo_uri: str = "mongodb://erica:erica_password_123@localhost:27017/",
        chroma_host: str = "chromadb",
        chroma_port: int = 8000,
        neo4j_uri: str = "bolt://localhost:7687",
        neo4j_user: str = "neo4j",
        neo4j_password: str = "erica_password_123",
    ):
        # Initialize components
        self.embedder = ConceptEmbedder(
            mongo_uri=mongo_uri,
            chroma_host=chroma_host,
            chroma_port=chroma_port,
        )
        self.graph_retriever = GraphRetriever(
            neo4j_uri=neo4j_uri,
            neo4j_user=neo4j_user,
            neo4j_password=neo4j_password,
        )
    
    def retrieve(
        self,
        query: str,
        top_k_semantic: int = 5,
        min_semantic_score: float = 0.4,
        prereq_depth: int = 2,
        related_depth: int = 1,
        max_concepts: int = 15,
        max_examples_per_concept: int = 2,
    ) -> RetrievalResult:
        """
        Retrieve relevant subgraph for a user query.
        
        Args:
            query: User's question
            top_k_semantic: Number of semantic search results
            min_semantic_score: Minimum similarity score for semantic matches
            prereq_depth: How deep to traverse prerequisites
            related_depth: How deep to traverse related concepts
            max_concepts: Maximum concepts in final subgraph
            max_examples_per_concept: Max examples per concept
        
        Returns:
            RetrievalResult with subgraph and metadata
        """
        # Step 1: Semantic search for candidate concepts
        semantic_matches = self.embedder.search(
            query=query,
            top_k=top_k_semantic,
            min_score=min_semantic_score,
        )
        
        # Step 2: Extract seed concepts from semantic matches
        seed_concepts = [match["title"] for match in semantic_matches]
        
        if not seed_concepts:
            # Fallback: if no semantic matches, return empty result
            return RetrievalResult(
                query=query,
                semantic_matches=[],
                seed_concepts=[],
                subgraph=Subgraph(
                    seed_concepts=[],
                    concepts=[],
                    resources=[],
                    examples=[],
                    prereq_chain=[],
                ),
                ordered_concepts=[],
            )
        
        # Step 3: Expand seeds via graph traversal
        subgraph = self.graph_retriever.expand_seeds(
            seed_titles=seed_concepts,
            prereq_depth=prereq_depth,
            related_depth=related_depth,
            max_concepts=max_concepts,
            max_examples_per_concept=max_examples_per_concept,
        )
        
        # Step 4: Get topological order for explanation scaffolding
        ordered_concepts = self.graph_retriever.get_topological_order(subgraph.concepts)
        
        return RetrievalResult(
            query=query,
            semantic_matches=semantic_matches,
            seed_concepts=seed_concepts,
            subgraph=subgraph,
            ordered_concepts=ordered_concepts,
        )
    
    def retrieve_with_explicit_concepts(
        self,
        query: str,
        explicit_concepts: list[str],
        **kwargs,
    ) -> RetrievalResult:
        """
        Retrieve with explicitly specified seed concepts.
        
        Useful when you know exactly which concepts to explain,
        or when combining with LLM-based concept extraction.
        """
        # Combine explicit concepts with semantic search
        semantic_matches = self.embedder.search(
            query=query,
            top_k=kwargs.get("top_k_semantic", 3),
            min_score=kwargs.get("min_semantic_score", 0.4),
        )
        
        # Union of explicit + semantic, explicit first
        seed_concepts = list(explicit_concepts)
        for match in semantic_matches:
            if match["title"] not in seed_concepts:
                seed_concepts.append(match["title"])
        
        # Expand via graph
        subgraph = self.graph_retriever.expand_seeds(
            seed_titles=seed_concepts,
            prereq_depth=kwargs.get("prereq_depth", 2),
            related_depth=kwargs.get("related_depth", 1),
            max_concepts=kwargs.get("max_concepts", 15),
            max_examples_per_concept=kwargs.get("max_examples_per_concept", 2),
        )
        
        ordered_concepts = self.graph_retriever.get_topological_order(subgraph.concepts)
        
        return RetrievalResult(
            query=query,
            semantic_matches=semantic_matches,
            seed_concepts=seed_concepts,
            subgraph=subgraph,
            ordered_concepts=ordered_concepts,
        )
    
    def close(self):
        """Close all connections."""
        self.embedder.close()
        self.graph_retriever.close()