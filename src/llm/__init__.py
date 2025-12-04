"""
Erica AI Tutor - LLM Client
Supports OpenRouter API with Qwen2.5 models
"""
import os
from typing import Optional, List, Dict, Any
from openai import OpenAI
from pydantic import BaseModel

from config import settings


class Message(BaseModel):
    role: str  # "system", "user", or "assistant"
    content: str


class LLMClient:
    """
    LLM Client using OpenRouter API.
    
    OpenRouter provides access to various models including Qwen2.5
    through an OpenAI-compatible API.
    """
    
    def __init__(
        self,
        api_key: Optional[str] = None,
        model: Optional[str] = None,
        base_url: str = "https://openrouter.ai/api/v1"
    ):
        self.api_key = api_key or settings.openrouter_api_key
        self.model = model or settings.openrouter_model
        self.base_url = base_url
        
        if not self.api_key:
            raise ValueError(
                "OpenRouter API key is required. "
                "Set OPENROUTER_API_KEY in your .env file. "
                "Get your key at: https://openrouter.ai/keys"
            )
        
        self.client = OpenAI(
            api_key=self.api_key,
            base_url=self.base_url,
        )
    
    def chat(
        self,
        messages: List[Dict[str, str]],
        temperature: float = 0.7,
        max_tokens: int = 2048,
        **kwargs
    ) -> str:
        """
        Send a chat completion request.
        
        Args:
            messages: List of message dicts with 'role' and 'content'
            temperature: Sampling temperature (0-2)
            max_tokens: Maximum tokens to generate
            
        Returns:
            Generated text response
        """
        response = self.client.chat.completions.create(
            model=self.model,
            messages=messages,
            temperature=temperature,
            max_tokens=max_tokens,
            **kwargs
        )
        return response.choices[0].message.content
    
    def generate(
        self,
        prompt: str,
        system_prompt: Optional[str] = None,
        temperature: float = 0.7,
        max_tokens: int = 2048,
    ) -> str:
        """
        Simple generation with a single prompt.
        
        Args:
            prompt: User prompt
            system_prompt: Optional system instruction
            temperature: Sampling temperature
            max_tokens: Maximum tokens to generate
            
        Returns:
            Generated text response
        """
        messages = []
        if system_prompt:
            messages.append({"role": "system", "content": system_prompt})
        messages.append({"role": "user", "content": prompt})
        
        return self.chat(messages, temperature=temperature, max_tokens=max_tokens)
    
    def extract_entities(
        self,
        text: str,
        entity_types: List[str] = None
    ) -> Dict[str, Any]:
        """
        Extract entities from text using the LLM.
        Useful for building the knowledge graph.
        
        Args:
            text: Text to extract entities from
            entity_types: Types of entities to extract
            
        Returns:
            Dict with extracted entities
        """
        if entity_types is None:
            entity_types = ["concept", "definition", "example", "prerequisite"]
        
        system_prompt = """You are an expert at extracting structured information from educational content.
Extract entities and their relationships from the given text.
Return your response as valid JSON."""

        prompt = f"""Extract the following entity types from this text: {', '.join(entity_types)}

Text:
{text}

Return a JSON object with:
- "entities": list of objects with "type", "name", "description"
- "relationships": list of objects with "source", "target", "relation_type"

JSON:"""

        response = self.generate(prompt, system_prompt=system_prompt, temperature=0.3)
        
        # Try to parse JSON from response
        import json
        try:
            # Find JSON in response (it might have extra text)
            start = response.find('{')
            end = response.rfind('}') + 1
            if start != -1 and end > start:
                return json.loads(response[start:end])
        except json.JSONDecodeError:
            pass
        
        return {"entities": [], "relationships": [], "raw_response": response}


# Convenience function
def get_llm_client() -> LLMClient:
    """Get a configured LLM client instance."""
    return LLMClient()


# Available Qwen models on OpenRouter (as of late 2024)
AVAILABLE_MODELS = {
    "qwen2.5-72b": "qwen/qwen-2.5-72b-instruct",      # Most capable, higher cost
    "qwen2.5-32b": "qwen/qwen-2.5-32b-instruct",      # Good balance
    "qwen2.5-14b": "qwen/qwen-2.5-14b-instruct",      # Smaller, faster
    "qwen2.5-7b": "qwen/qwen-2.5-7b-instruct",        # Smallest, cheapest
    "qwen2.5-coder-32b": "qwen/qwen-2.5-coder-32b-instruct",  # Code-focused
}
