import os
import logging

from pythonjsonlogger import jsonlogger
from pydantic_settings import BaseSettings


def setup_logging() -> None:
    handler = logging.StreamHandler()
    handler.setFormatter(jsonlogger.JsonFormatter(
        fmt="%(asctime)s %(name)s %(levelname)s %(message)s",
        datefmt="%Y-%m-%dT%H:%M:%S",
    ))
    root = logging.getLogger()
    root.handlers = [handler]
    level = logging.DEBUG if os.getenv("LOG_LEVEL", "INFO").upper() == "DEBUG" else logging.INFO
    root.setLevel(level)


class Settings(BaseSettings):
    openai_api_key: str = ""
    pinecone_api_key: str = ""
    jina_api_key: str = ""
    langchain_api_key: str = ""
    langchain_tracing_v2: str = "false"
    langchain_project: str = "Indonesian-Document-Intelligence"

    # Upload constraints
    max_upload_files: int = 10
    max_file_size_mb: int = 10
    allowed_extensions: str = ".txt,.pdf,.docx"

    class Config:
        env_file = ".env"

    @property
    def allowed_extensions_set(self) -> set:
        return {ext.strip() for ext in self.allowed_extensions.split(",")}


settings = Settings()

# Set LangSmith env vars agar LangChain tracing aktif otomatis
os.environ["LANGCHAIN_TRACING_V2"] = settings.langchain_tracing_v2
os.environ["LANGCHAIN_API_KEY"]    = settings.langchain_api_key
os.environ["LANGCHAIN_PROJECT"]    = settings.langchain_project
os.environ["JINA_API_KEY"]         = settings.jina_api_key


class PipelineConfig:
    def __init__(self):
        self.pinecone_index        = "dokumen-indonesia"
        self.embed_model           = "text-embedding-3-small"
        self.reranker_model        = "jina-reranker-v2-base-multilingual"
        self.llm_model             = "gpt-4o-mini"
        self.top_k_retrieval       = 20
        self.top_k_rerank          = 10
        self.min_relevance         = 0.20
        self.chunk_size            = 512
        self.chunk_overlap         = 100


pipeline_config = PipelineConfig()
