"""
Erica AI Tutor - Configuration Management
"""
import os
from pydantic_settings import BaseSettings
from pydantic import Field
from typing import Optional


class Settings(BaseSettings):
    """Application settings loaded from environment variables."""
    
    # ===========================================
    # LLM Configuration (OpenRouter is primary)
    # ===========================================
    openrouter_api_key: Optional[str] = Field(default=None, env="OPENROUTER_API_KEY")
    openrouter_model: str = Field(default="qwen/qwen-2.5-72b-instruct", env="OPENROUTER_MODEL")
    
    # Local Ollama (optional fallback)
    ollama_host: str = Field(default="http://localhost:11434", env="OLLAMA_HOST")
    ollama_model: str = Field(default="qwen2.5:7b", env="OLLAMA_MODEL")
    
    # ===========================================
    # Neo4j Configuration
    # ===========================================
    neo4j_uri: str = Field(default="bolt://neo4j:7687", env="NEO4J_URI")
    neo4j_user: str = Field(default="neo4j", env="NEO4J_USER")
    neo4j_password: str = Field(default="erica_password_123", env="NEO4J_PASSWORD")
    
    # ===========================================
    # ChromaDB Configuration
    # ===========================================
    chroma_host: str = Field(default="chromadb", env="CHROMA_HOST")
    chroma_port: int = Field(default=8000, env="CHROMA_PORT")
    
    # ===========================================
    # MongoDB Configuration
    # ===========================================
    mongodb_uri: str = Field(default="mongodb://erica:erica_password_123@mongodb:27017/", env="MONGODB_URI")
    mongodb_database: str = Field(default="erica_tutor", env="MONGODB_DATABASE")
    
    # ===========================================
    # Embedding Configuration
    # ===========================================
    embedding_model: str = Field(default="all-MiniLM-L6-v2", env="EMBEDDING_MODEL")
    
    # ===========================================
    # Processing Configuration
    # ===========================================
    chunk_size: int = Field(default=512, env="CHUNK_SIZE")
    chunk_overlap: int = Field(default=50, env="CHUNK_OVERLAP")
    
    # ===========================================
    # Application Settings
    # ===========================================
    log_level: str = Field(default="INFO", env="LOG_LEVEL")
    
    class Config:
        env_file = ".env"
        env_file_encoding = "utf-8"
    
    @property
    def chroma_url(self) -> str:
        return f"http://{self.chroma_host}:{self.chroma_port}"
    
    @property
    def use_openrouter(self) -> bool:
        """Use OpenRouter if API key is set and ollama is not accessible."""
        return self.openrouter_api_key is not None and self.openrouter_api_key != ""


# Global settings instance
settings = Settings()


def get_settings() -> Settings:
    """Get the global settings instance."""
    return settings
