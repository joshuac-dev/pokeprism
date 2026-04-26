from pydantic_settings import BaseSettings
from pydantic import Field


class Settings(BaseSettings):
    # Database
    DATABASE_URL: str = Field(
        default="postgresql+asyncpg://pokeprism:pokeprism@localhost:5433/pokeprism"
    )

    # Redis
    REDIS_URL: str = Field(default="redis://localhost:6380/0")

    # Neo4j
    NEO4J_URI: str = Field(default="bolt://localhost:7687")
    NEO4J_USER: str = Field(default="neo4j")
    NEO4J_PASSWORD: str = Field(default="changeme_neo4j")

    # Ollama
    OLLAMA_BASE_URL: str = Field(default="http://localhost:11434")
    OLLAMA_PLAYER_MODEL: str = Field(default="qwen3.5:9b-q4_K_M")
    OLLAMA_COACH_MODEL: str = Field(default="gemma4-e4b:q6_K")
    OLLAMA_EMBED_MODEL: str = Field(default="nomic-embed-text")

    # TCGDex
    TCGDEX_BASE_URL: str = Field(default="https://api.tcgdex.net/v2/en")

    # Logging
    LOG_LEVEL: str = Field(default="INFO")

    class Config:
        env_file = ".env"
        extra = "ignore"


settings = Settings()
