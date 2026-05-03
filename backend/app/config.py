from pydantic_settings import BaseSettings
from pydantic import ConfigDict, Field


class Settings(BaseSettings):
    model_config = ConfigDict(env_file=[".env", "../.env"], extra="ignore")

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
    OLLAMA_COACH_MODEL: str = Field(default="gemma4-E4B-it-Q6_K:latest")
    OLLAMA_EMBED_MODEL: str = Field(default="nomic-embed-text")

    # TCGDex
    TCGDEX_BASE_URL: str = Field(default="https://api.tcgdex.net/v2/en")

    # Logging
    LOG_LEVEL: str = Field(default="INFO")

    # HTTP/WebSocket browser origins. Use "*" only for explicitly trusted local
    # deployments; production should list concrete origins.
    CORS_ORIGINS: str = Field(
        default=(
            "http://localhost:3000,http://localhost:5173,http://localhost:4173,"
            "http://127.0.0.1:4173,https://pokeprism.joshuac.dev"
        )
    )

    @property
    def cors_origins_list(self) -> list[str] | str:
        origins = [origin.strip() for origin in self.CORS_ORIGINS.split(",") if origin.strip()]
        return "*" if origins == ["*"] else origins


settings = Settings()
