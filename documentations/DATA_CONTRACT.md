# DATA_CONTRACT.md

Mencerminkan kode aktual di `app/models.py`, `app/pipeline.py`, `app/ingestion.py`. Parameter pipeline: lihat [PIPELINE.md](PIPELINE.md).

---

## API Schemas

### `POST /api/query`

```python
# Request
class QueryRequest(BaseModel):
    query: str  # min 3 karakter, max 500 karakter

# Response
class QueryResponse(BaseModel):
    query: str          # Query setelah normalisasi (bukan query asli)
    answer: str         # Jawaban Bahasa Indonesia
    trust: TrustScore
    sources: List[Source]
    has_conflict: bool
```

### `POST /api/upload`

```python
class UploadResponse(BaseModel):
    message: str
    files_processed: int
    chunks_indexed: int
```

---

## TrustScore

```python
class TrustScore(BaseModel):
    label: str        # "found" | "not_found" | "conflict"
    source_count: int
```

| Label | Kondisi |
|-------|---------|
| `not_found` | Jawaban mengandung "tidak ditemukan dalam dokumen" atau citations kosong |
| `conflict` | `has_conflict=True` dan >= 2 dokumen berbeda dikutip |
| `found` | Selain kedua kondisi di atas |

**Invariant:** `trust.label == "not_found"` selalu menghasilkan `sources == []`.

---

## Source

```python
class Source(BaseModel):
    doc_id: str              # Nama file (basename)
    section: str = ""        # Judul seksi, kosong jika tidak ada
    excerpt: str             # Konten chunk yang dikutip
    relevance_score: float   # Skor Jina Reranker, 0.0-1.0
    is_conflict_party: bool  # True jika dokumen ini terlibat konflik
```

**Invariant:** `is_conflict_party=True` hanya muncul jika `has_conflict=True` dan dokumen tersebut ada di `citations` LLM.

---

## Schema Internal (tidak diekspos ke API)

### ChunkEnrichment - output LLM per chunk saat ingestion

```python
class ChunkEnrichment(BaseModel):
    context_sentence: str     # Satu kalimat ringkasan chunk
    section: str = ""
    person: List[str]
    organization: List[str]
    location: List[str]
    date: List[str]
    task: List[str]
```

### Pinecone Metadata per chunk

```python
{
    "doc_id":   str,    # Nama file (basename)
    "chunk_id": str,    # UUID v4
    "section":  str,    # Kosong jika tidak ada
    "text":     str,    # page_content yang di-embed
    "entities": str,    # JSON: {person, organization, location, date, task}
                        # Hanya ada jika enrichment berhasil
}
```

### _AnswerWithCitations - structured output LLM saat query

```python
class _AnswerWithCitations(BaseModel):
    answer: str
    citations: List[str]         # chunk_id yang digunakan
    has_conflict: bool
    conflict_doc_ids: List[str]  # doc_id yang berkonflik
```

Post-processing sebelum diekspos: `conflict_doc_ids` divalidasi hanya berisi doc_id dari `citations`, dan di-reset ke `set()` jika `has_conflict=False` atau jumlah dokumen kurang dari 2.
