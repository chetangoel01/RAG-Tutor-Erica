"""
Answer generation using retrieved subgraph context.

Takes a RetrievalResult and generates a scaffolded answer with citations.

Usage:
    from src.generation.answer_generator import AnswerGenerator
    
    generator = AnswerGenerator()
    answer = generator.generate(retrieval_result)
"""

import os
from typing import Optional
from openai import OpenAI

from src.retrieval.hybrid_retriever import RetrievalResult


class AnswerGenerator:
    """
    Generates answers using Qwen via OpenRouter.
    """
    
    def __init__(
        self,
        api_key: Optional[str] = None,
        model: str = "qwen/qwen-2.5-72b-instruct",
        base_url: str = "https://openrouter.ai/api/v1",
    ):
        self.api_key = api_key or os.environ.get("OPENROUTER_API_KEY")
        if not self.api_key:
            raise ValueError(
                "OpenRouter API key required. Set OPENROUTER_API_KEY environment variable."
            )
        
        self.model = model
        self.client = OpenAI(api_key=self.api_key, base_url=base_url)
    
    def generate(
        self,
        retrieval_result: RetrievalResult,
        temperature: float = 0.7,
        max_tokens: int = 4096,
    ) -> str:
        """
        Generate an answer based on retrieved context.
        
        Args:
            retrieval_result: Result from HybridRetriever
            temperature: LLM temperature
            max_tokens: Maximum tokens to generate
        
        Returns:
            Generated answer with citations
        """
        context = self._build_context(retrieval_result)
        
        system_prompt = """You are Erica, an enthusiastic and knowledgeable AI tutor for an Introduction to AI course at a university.

## Your Personality
- You are patient, encouraging, and passionate about teaching AI/ML concepts
- You celebrate when students ask good questions
- You use analogies and real-world examples to make complex ideas accessible
- You're thorough but never condescending

## Your Teaching Style
1. **Start with intuition**: Before diving into technical details, explain WHY a concept matters and give an intuitive understanding
2. **Build from foundations**: Always explain prerequisite concepts first, building a solid foundation before advancing
3. **Use concrete examples**: Illustrate abstract concepts with specific examples, code snippets, or mathematical walkthroughs
4. **Connect the dots**: Show how concepts relate to each other and to the broader field of AI
5. **Summarize key points**: End with a concise summary of the main takeaways

## Response Format
- Use clear headings and subheadings to organize your explanation
- Include mathematical notation when relevant (use LaTeX: \\( inline \\) or \\[ block \\])
- Provide code examples when they help illustrate a concept
- Cite resources using [Resource: URL] format when referencing specific materials
- Aim for comprehensive explanations - don't rush through important details

## Important Guidelines
- If a concept has prerequisites, explain them first
- Use the examples from the knowledge graph to illustrate points
- When explaining algorithms, walk through them step-by-step
- If there are common misconceptions, address them
- Encourage the student and suggest related topics they might explore next

Remember: Your goal is not just to answer the question, but to help the student truly understand the concept and how it fits into the bigger picture of AI/ML."""

        user_prompt = f"""## Student's Question
{retrieval_result.query}

## Knowledge Graph Context
{context}

---

Please provide a thorough, well-structured explanation that:
1. Starts with an intuitive overview of why this topic matters
2. Explains any prerequisite concepts the student needs to understand first
3. Dives deep into the main topic with examples and mathematical details where appropriate
4. Uses the provided examples to illustrate key points
5. Cites relevant resources for further reading
6. Ends with a summary and suggestions for what to learn next

Take your time and be comprehensive - the student wants to truly understand this topic."""

        response = self.client.chat.completions.create(
            model=self.model,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            temperature=temperature,
            max_tokens=max_tokens,
        )
        
        return response.choices[0].message.content
    
    def _build_context(self, result: RetrievalResult) -> str:
        """Build context string from retrieval result."""
        sections = []
        
        sections.append("### Relevant Concepts (ordered from foundational to advanced)")
        
        concept_lookup = {c.title: c for c in result.subgraph.concepts}
        
        for i, title in enumerate(result.ordered_concepts, 1):
            concept = concept_lookup.get(title)
            if concept:
                difficulty = concept.difficulty or "unknown"
                definition = concept.definition or "No definition available."
                sections.append(f"\n**{i}. {title}** [{difficulty}]")
                sections.append(definition)
                
                if concept.relation_to_seed != "seed":
                    sections.append(f"*(Relationship: {concept.relation_to_seed} of {concept.seed_concept})*")
        
        if result.subgraph.examples:
            sections.append("\n### Examples from Course Materials")
            
            examples_by_concept = {}
            for ex in result.subgraph.examples:
                if ex.concept not in examples_by_concept:
                    examples_by_concept[ex.concept] = []
                examples_by_concept[ex.concept].append(ex)
            
            for concept_title in result.ordered_concepts:
                if concept_title in examples_by_concept:
                    sections.append(f"\n**Examples for {concept_title}:**")
                    for ex in examples_by_concept[concept_title]:
                        sections.append(f"- [{ex.example_type}] {ex.text}")
                        if ex.source_url:
                            sections.append(f"  Source: {ex.source_url}")
        
        if result.subgraph.resources:
            sections.append("\n### Available Resources for Further Reading")
            
            by_type = {}
            for r in result.subgraph.resources:
                rtype = r.resource_type or "other"
                if rtype not in by_type:
                    by_type[rtype] = []
                by_type[rtype].append(r)
            
            for rtype, resources in by_type.items():
                sections.append(f"\n**{rtype.upper()} Resources:**")
                for r in resources[:5]:
                    concepts_str = ", ".join(r.concepts_explained[:3])
                    sections.append(f"- {r.url}")
                    sections.append(f"  Explains: {concepts_str}")
                    if r.page_numbers:
                        sections.append(f"  Pages: {r.page_numbers}")
                    if r.timecodes:
                        sections.append(f"  Time: {r.timecodes['start']}s - {r.timecodes['end']}s")
        
        if result.subgraph.prereq_chain:
            sections.append("\n### Learning Path (Prerequisites → Target)")
            for chain in result.subgraph.prereq_chain:
                if len(chain) > 1:
                    sections.append(f"- {' → '.join(chain)}")
        
        return "\n".join(sections)