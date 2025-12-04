"""
Embed concepts into ChromaDB for semantic search.

Usage:
    from src.retrieval.concept_embeddings import ConceptEmbedder
    
    embedder = ConceptEmbedder()
    embedder.embed_all_concepts()
    
    # Search
    results = embedder.search("What is backpropagation?", top_k=5)
"""

import chromadb
from pymongo import MongoClient
from sentence_transformers import SentenceTransformer
from typing import Optional
import hashlib


class ConceptEmbedder:
    """Embeds concepts into ChromaDB for semantic retrieval."""
    
    def __init__(
        self,
        mongo_uri: str = "mongodb://erica:erica_password_123@localhost:27017/",
        chroma_host: str = "chromadb",
        chroma_port: int = 8000,
        db_name: str = "erica",
        collection_name: str = "concepts",
        embedding_model: str = "all-MiniLM-L6-v2",
    ):
        # MongoDB connection
        self.mongo_client = MongoClient(mongo_uri)
        self.db = self.mongo_client[db_name]
        
        # ChromaDB connection
        self.chroma_client = chromadb.HttpClient(host=chroma_host, port=chroma_port)
        self.collection_name = collection_name
        
        # Embedding model (runs locally)
        print(f"Loading embedding model: {embedding_model}...")
        self.model = SentenceTransformer(embedding_model)
        print(f"Model loaded. Embedding dimension: {self.model.get_sentence_embedding_dimension()}")
    
    def _get_or_create_collection(self, clear_existing: bool = False):
        """Get or create the ChromaDB collection."""
        if clear_existing:
            try:
                self.chroma_client.delete_collection(self.collection_name)
                print(f"Deleted existing collection: {self.collection_name}")
            except Exception:
                pass
        
        collection = self.chroma_client.get_or_create_collection(
            name=self.collection_name,
            metadata={"description": "Concept embeddings for semantic search"}
        )
        return collection
    
    def _concept_to_text(self, concept: dict) -> str:
        """Convert concept to text for embedding."""
        title = concept.get("title", "")
        definition = concept.get("definition", "")
        aliases = concept.get("aliases", [])
        
        # Combine title, definition, and aliases
        text_parts = [title]
        if definition:
            text_parts.append(definition)
        if aliases:
            text_parts.append(f"Also known as: {', '.join(aliases)}")
        
        return ". ".join(text_parts)
    
    def _generate_id(self, title: str) -> str:
        """Generate a stable ID from concept title."""
        return hashlib.md5(title.encode()).hexdigest()[:16]
    
    def embed_all_concepts(self, clear_existing: bool = True, batch_size: int = 100):
        """
        Embed all concepts from MongoDB into ChromaDB.
        
        Args:
            clear_existing: Whether to clear existing embeddings
            batch_size: Number of concepts to embed at once
        """
        collection = self._get_or_create_collection(clear_existing=clear_existing)
        
        # Fetch all concepts from MongoDB
        concepts = list(self.db.concepts.find({}))
        print(f"Found {len(concepts)} concepts in MongoDB")
        
        # Process in batches
        total_embedded = 0
        
        for i in range(0, len(concepts), batch_size):
            batch = concepts[i:i + batch_size]
            
            # Prepare batch data
            ids = []
            texts = []
            metadatas = []
            
            for concept in batch:
                title = concept.get("title", "")
                if not title:
                    continue
                
                concept_id = self._generate_id(title)
                text = self._concept_to_text(concept)
                
                ids.append(concept_id)
                texts.append(text)
                metadatas.append({
                    "title": title,
                    "definition": concept.get("definition", "")[:500],  # Truncate for metadata
                    "difficulty": concept.get("difficulty", "unknown"),
                    "mention_count": concept.get("mention_count", 0),
                })
            
            if not ids:
                continue
            
            # Generate embeddings
            embeddings = self.model.encode(texts, show_progress_bar=False).tolist()
            
            # Add to ChromaDB
            collection.add(
                ids=ids,
                embeddings=embeddings,
                documents=texts,
                metadatas=metadatas,
            )
            
            total_embedded += len(ids)
            print(f"  Embedded {total_embedded}/{len(concepts)} concepts")
        
        print(f"\nDone! {total_embedded} concepts embedded into ChromaDB collection '{self.collection_name}'")
        return total_embedded
    
    def search(
        self,
        query: str,
        top_k: int = 10,
        min_score: Optional[float] = None,
    ) -> list[dict]:
        """
        Search for concepts similar to the query.
        
        Args:
            query: User question or search text
            top_k: Number of results to return
            min_score: Minimum similarity score (0-1, higher is more similar)
        
        Returns:
            List of dicts with 'title', 'definition', 'difficulty', 'score'
        """
        collection = self.chroma_client.get_collection(self.collection_name)
        
        # Embed the query
        query_embedding = self.model.encode(query).tolist()
        
        # Search ChromaDB
        results = collection.query(
            query_embeddings=[query_embedding],
            n_results=top_k,
            include=["metadatas", "distances", "documents"],
        )
        
        # Format results
        formatted = []
        for i, (meta, distance, doc) in enumerate(zip(
            results["metadatas"][0],
            results["distances"][0],
            results["documents"][0],
        )):
            # ChromaDB returns L2 distance by default; convert to similarity score
            # Lower distance = more similar
            score = 1 / (1 + distance)
            
            if min_score and score < min_score:
                continue
            
            formatted.append({
                "title": meta["title"],
                "definition": meta["definition"],
                "difficulty": meta["difficulty"],
                "score": round(score, 4),
                "full_text": doc,
            })
        
        return formatted
    
    def get_stats(self) -> dict:
        """Get statistics about the ChromaDB collection."""
        try:
            collection = self.chroma_client.get_collection(self.collection_name)
            return {
                "collection": self.collection_name,
                "count": collection.count(),
                "metadata": collection.metadata,
            }
        except Exception as e:
            return {"error": str(e)}
    
    def close(self):
        """Close connections."""
        self.mongo_client.close()


# Convenience functions for notebook use
def embed_concepts(
    mongo_uri: str = "mongodb://erica:erica_password_123@localhost:27017/",
    chroma_host: str = "chromadb",
):
    """One-liner to embed all concepts."""
    embedder = ConceptEmbedder(mongo_uri=mongo_uri, chroma_host=chroma_host)
    embedder.embed_all_concepts()
    embedder.close()


def search_concepts(
    query: str,
    top_k: int = 10,
    chroma_host: str = "chromadb",
) -> list[dict]:
    """One-liner to search concepts."""
    embedder = ConceptEmbedder(chroma_host=chroma_host)
    results = embedder.search(query, top_k=top_k)
    embedder.close()
    return results