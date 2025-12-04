"""
Graph-based retrieval from Neo4j.

Takes seed concepts and expands them into a subgraph containing:
- Prerequisites (for scaffolding explanations)
- Related concepts (siblings, is_a, part_of, contrasts_with)
- Resources that explain the concepts
- Examples that demonstrate the concepts

Usage:
    from src.retrieval.graph_retriever import GraphRetriever
    
    retriever = GraphRetriever()
    subgraph = retriever.expand_seeds(["Gradient Descent", "Backpropagation"])
"""

from neo4j import GraphDatabase
from typing import Optional
from dataclasses import dataclass, field


@dataclass
class RetrievedConcept:
    """A concept retrieved from the knowledge graph."""
    title: str
    definition: str
    difficulty: str
    depth: int  # 0 = seed, 1 = direct neighbor, 2 = 2-hop, etc.
    relation_to_seed: str  # How this concept relates to a seed concept
    seed_concept: str  # Which seed concept this came from


@dataclass
class RetrievedResource:
    """A resource that explains a concept."""
    url: str
    resource_type: str
    title: str
    concepts_explained: list[str]
    page_numbers: Optional[list[int]] = None
    timecodes: Optional[dict] = None


@dataclass
class RetrievedExample:
    """An example that demonstrates a concept."""
    text: str
    example_type: str
    concept: str
    source_url: str


@dataclass
class Subgraph:
    """A retrieved subgraph centered on seed concepts."""
    seed_concepts: list[str]
    concepts: list[RetrievedConcept]
    resources: list[RetrievedResource]
    examples: list[RetrievedExample]
    prereq_chain: list[list[str]]  # Ordered paths for scaffolding
    
    def concept_titles(self) -> list[str]:
        """Get all concept titles in the subgraph."""
        return [c.title for c in self.concepts]
    
    def to_dict(self) -> dict:
        """Convert to dictionary for serialization."""
        return {
            "seed_concepts": self.seed_concepts,
            "concepts": [
                {
                    "title": c.title,
                    "definition": c.definition,
                    "difficulty": c.difficulty,
                    "depth": c.depth,
                    "relation_to_seed": c.relation_to_seed,
                    "seed_concept": c.seed_concept,
                }
                for c in self.concepts
            ],
            "resources": [
                {
                    "url": r.url,
                    "type": r.resource_type,
                    "title": r.title,
                    "concepts": r.concepts_explained,
                    "page_numbers": r.page_numbers,
                    "timecodes": r.timecodes,
                }
                for r in self.resources
            ],
            "examples": [
                {
                    "text": e.text,
                    "type": e.example_type,
                    "concept": e.concept,
                    "source_url": e.source_url,
                }
                for e in self.examples
            ],
            "prereq_chain": self.prereq_chain,
        }


class GraphRetriever:
    """Retrieves subgraphs from Neo4j based on seed concepts."""
    
    def __init__(
        self,
        neo4j_uri: str = "bolt://localhost:7687",
        neo4j_user: str = "neo4j",
        neo4j_password: str = "erica_password_123",
    ):
        self.driver = GraphDatabase.driver(
            neo4j_uri, auth=(neo4j_user, neo4j_password)
        )
    
    def expand_seeds(
        self,
        seed_titles: list[str],
        prereq_depth: int = 2,
        related_depth: int = 1,
        max_concepts: int = 15,
        max_examples_per_concept: int = 2,
    ) -> Subgraph:
        """
        Expand seed concepts into a subgraph.
        
        Args:
            seed_titles: List of concept titles to start from
            prereq_depth: How many hops backward on PREREQ_OF edges
            related_depth: How many hops on related edges (IS_A, PART_OF, etc.)
            max_concepts: Maximum total concepts to return
            max_examples_per_concept: Max examples per concept
        
        Returns:
            Subgraph containing concepts, resources, examples, and prereq chains
        """
        with self.driver.session() as session:
            # 1. Get seed concepts with their properties
            concepts = self._get_seed_concepts(session, seed_titles)
            
            # 2. Get prerequisites (for scaffolding)
            prereqs = self._get_prerequisites(session, seed_titles, prereq_depth)
            concepts.extend(prereqs)
            
            # 3. Get related concepts (siblings, is_a, part_of, contrasts)
            related = self._get_related_concepts(session, seed_titles, related_depth)
            concepts.extend(related)
            
            # 4. Deduplicate and limit concepts
            concepts = self._deduplicate_concepts(concepts, max_concepts)
            
            # 5. Get prerequisite chains for ordering
            prereq_chains = self._get_prereq_chains(session, seed_titles, prereq_depth)
            
            # 6. Get resources that explain these concepts
            concept_titles = [c.title for c in concepts]
            resources = self._get_resources(session, concept_titles)
            
            # 7. Get examples for these concepts
            examples = self._get_examples(session, concept_titles, max_examples_per_concept)
        
        return Subgraph(
            seed_concepts=seed_titles,
            concepts=concepts,
            resources=resources,
            examples=examples,
            prereq_chain=prereq_chains,
        )
    
    def _get_seed_concepts(
        self, session, titles: list[str]
    ) -> list[RetrievedConcept]:
        """Get the seed concepts with their properties."""
        result = session.run("""
            UNWIND $titles AS title
            MATCH (c:Concept {title: title})
            RETURN c.title AS title, 
                   c.definition AS definition,
                   c.difficulty AS difficulty
        """, titles=titles)
        
        return [
            RetrievedConcept(
                title=record["title"],
                definition=record["definition"] or "",
                difficulty=record["difficulty"] or "unknown",
                depth=0,
                relation_to_seed="seed",
                seed_concept=record["title"],
            )
            for record in result
        ]
    
    def _get_prerequisites(
        self, session, seed_titles: list[str], depth: int
    ) -> list[RetrievedConcept]:
        """Get prerequisite concepts (traverse backward on PREREQ_OF)."""
        result = session.run("""
            UNWIND $titles AS seedTitle
            MATCH (seed:Concept {title: seedTitle})
            MATCH path = (prereq:Concept)-[:PREREQ_OF*1..""" + str(depth) + """]->(seed)
            WITH seedTitle, prereq, length(path) AS dist
            RETURN DISTINCT prereq.title AS title,
                   prereq.definition AS definition,
                   prereq.difficulty AS difficulty,
                   min(dist) AS depth,
                   seedTitle AS seed_concept
            ORDER BY depth
        """, titles=seed_titles)
        
        return [
            RetrievedConcept(
                title=record["title"],
                definition=record["definition"] or "",
                difficulty=record["difficulty"] or "unknown",
                depth=record["depth"],
                relation_to_seed="prerequisite",
                seed_concept=record["seed_concept"],
            )
            for record in result
        ]
    
    def _get_related_concepts(
        self, session, seed_titles: list[str], depth: int
    ) -> list[RetrievedConcept]:
        """Get related concepts via IS_A, PART_OF, SIBLING, CONTRASTS_WITH."""
        result = session.run("""
            UNWIND $titles AS seedTitle
            MATCH (seed:Concept {title: seedTitle})
            MATCH (seed)-[r:IS_A|PART_OF|SIBLING|CONTRASTS_WITH*1..""" + str(depth) + """]-(related:Concept)
            WHERE related.title <> seedTitle
            WITH seedTitle, related, type(r[0]) AS rel_type
            RETURN DISTINCT related.title AS title,
                   related.definition AS definition,
                   related.difficulty AS difficulty,
                   rel_type AS relation_type,
                   seedTitle AS seed_concept
        """, titles=seed_titles)
        
        return [
            RetrievedConcept(
                title=record["title"],
                definition=record["definition"] or "",
                difficulty=record["difficulty"] or "unknown",
                depth=1,
                relation_to_seed=record["relation_type"].lower(),
                seed_concept=record["seed_concept"],
            )
            for record in result
        ]
    
    def _deduplicate_concepts(
        self, concepts: list[RetrievedConcept], max_concepts: int
    ) -> list[RetrievedConcept]:
        """Remove duplicates, keeping the one with lowest depth."""
        seen = {}
        for c in concepts:
            if c.title not in seen or c.depth < seen[c.title].depth:
                seen[c.title] = c
        
        # Sort by depth (seeds first, then prereqs, then related)
        sorted_concepts = sorted(seen.values(), key=lambda x: x.depth)
        return sorted_concepts[:max_concepts]
    
    def _get_prereq_chains(
        self, session, seed_titles: list[str], depth: int
    ) -> list[list[str]]:
        """Get prerequisite chains for topological ordering."""
        chains = []
        
        for seed in seed_titles:
            result = session.run("""
                MATCH path = (prereq:Concept)-[:PREREQ_OF*1..""" + str(depth) + """]->(seed:Concept {title: $seed})
                WITH nodes(path) AS chain, path
                RETURN [n IN chain | n.title] AS titles
                ORDER BY length(path) DESC
                LIMIT 1
            """, seed=seed)
            
            record = result.single()
            if record:
                chains.append(record["titles"])
            else:
                chains.append([seed])
        
        return chains
    
    def _get_resources(
        self, session, concept_titles: list[str]
    ) -> list[RetrievedResource]:
        """Get resources that explain the concepts."""
        # Only access properties that exist on Resource nodes (url, type)
        # Other properties (title, page_numbers, start_time, end_time) may not exist
        result = session.run("""
            UNWIND $titles AS conceptTitle
            MATCH (r:Resource)-[:EXPLAINS]->(c:Concept {title: conceptTitle})
            RETURN DISTINCT r.url AS url,
                   r.type AS resource_type,
                   collect(DISTINCT c.title) AS concepts
        """, titles=concept_titles)
        
        resources = []
        seen_urls = set()
        
        for record in result:
            url = record["url"]
            if url in seen_urls:
                continue
            seen_urls.add(url)
            
            resources.append(RetrievedResource(
                url=url,
                resource_type=record["resource_type"] or "unknown",
                title=url,  # Use URL as title since title property doesn't exist
                concepts_explained=record["concepts"],
                page_numbers=None,  # Property doesn't exist on Resource nodes
                timecodes=None,  # Properties don't exist on Resource nodes
            ))
        
        return resources
    
    def _get_examples(
        self, session, concept_titles: list[str], max_per_concept: int
    ) -> list[RetrievedExample]:
        """Get examples that demonstrate the concepts."""
        result = session.run("""
            UNWIND $titles AS conceptTitle
            MATCH (e:Example)-[:EXEMPLIFIES]->(c:Concept {title: conceptTitle})
            WITH c.title AS concept, e
            ORDER BY e.example_type
            WITH concept, collect(e)[0..$max] AS examples
            UNWIND examples AS e
            RETURN e.text AS text,
                   e.example_type AS example_type,
                   concept,
                   e.source_url AS source_url
        """, titles=concept_titles, max=max_per_concept)
        
        return [
            RetrievedExample(
                text=record["text"],
                example_type=record["example_type"] or "unknown",
                concept=record["concept"],
                source_url=record["source_url"] or "",
            )
            for record in result
        ]
    
    def get_topological_order(self, concepts: list[RetrievedConcept]) -> list[str]:
        """
        Sort concepts in topological order based on PREREQ_OF relationships.
        Returns concepts ordered from foundational to advanced.
        """
        titles = [c.title for c in concepts]
        
        with self.driver.session() as session:
            # Get all PREREQ_OF edges between our concepts
            result = session.run("""
                MATCH (a:Concept)-[:PREREQ_OF]->(b:Concept)
                WHERE a.title IN $titles AND b.title IN $titles
                RETURN a.title AS prereq, b.title AS dependent
            """, titles=titles)
            
            # Build adjacency list
            edges = [(r["prereq"], r["dependent"]) for r in result]
        
        # Kahn's algorithm for topological sort
        from collections import defaultdict, deque
        
        in_degree = defaultdict(int)
        graph = defaultdict(list)
        
        for title in titles:
            in_degree[title] = 0
        
        for prereq, dependent in edges:
            graph[prereq].append(dependent)
            in_degree[dependent] += 1
        
        # Start with nodes that have no prerequisites
        queue = deque([t for t in titles if in_degree[t] == 0])
        result = []
        
        while queue:
            node = queue.popleft()
            result.append(node)
            
            for neighbor in graph[node]:
                in_degree[neighbor] -= 1
                if in_degree[neighbor] == 0:
                    queue.append(neighbor)
        
        # Add any remaining nodes (in case of cycles)
        for title in titles:
            if title not in result:
                result.append(title)
        
        return result
    
    def close(self):
        """Close the Neo4j driver."""
        self.driver.close()