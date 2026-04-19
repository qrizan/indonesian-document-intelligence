from pydantic import BaseModel, Field, field_validator
from typing import List

MAX_QUERY_LENGTH = 500
MIN_QUERY_LENGTH = 3

class QueryRequest(BaseModel):
    query: str = Field(..., description="Pertanyaan yang ingin dicari di dokumen")

    @field_validator("query")
    @classmethod
    def validate_query_length(cls, v: str) -> str:
        v = v.strip()
        if len(v) < MIN_QUERY_LENGTH:
            raise ValueError(f"Query terlalu pendek (minimal {MIN_QUERY_LENGTH} karakter).")
        if len(v) > MAX_QUERY_LENGTH:
            raise ValueError(f"Query terlalu panjang (maksimal {MAX_QUERY_LENGTH} karakter).")
        return v

class TrustScore(BaseModel):
    label: str = Field(..., description="found | not_found | conflict")
    source_count: int = Field(default=0, description="Jumlah chunk sumber yang digunakan")

class Source(BaseModel):
    doc_id: str
    section: str = ""
    excerpt: str
    relevance_score: float = 0.0
    is_conflict_party: bool = False

class QueryResponse(BaseModel):
    query: str
    answer: str
    trust: TrustScore
    sources: List[Source]
    has_conflict: bool

class UploadResponse(BaseModel):
    message: str
    files_processed: int
    chunks_indexed: int
