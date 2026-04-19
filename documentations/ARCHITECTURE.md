# ARCHITECTURE.md

---

## Arsitektur Sistem

```
[Browser] - HTMX -> [FastAPI]
                       |
          +------------+-----------+
          v                        v
  Ingestion Pipeline          Query Pipeline
  (upload dokumen)            (POST /api/query)
  LlamaIndex + OpenAI         LangChain + Jina + OpenAI
          |                        |
          +-------- Pinecone Namespace (session-scoped) ----+
                    BM25 In-Memory (session-scoped)
```

Detail pipeline: lihat [PIPELINE.md](PIPELINE.md).

---

## Session Management

Setiap server startup menghasilkan UUID sesi (`session-{8hex}`) sebagai Pinecone namespace.

| Event | Aksi |
|-------|------|
| Startup | UUID dibuat, stale namespace dari sesi crash sebelumnya dibersihkan |
| Upload | Chunk di-embed ke namespace aktif; BM25 dibangun ulang |
| Shutdown | `pinecone_index.delete(delete_all=True, namespace=session_id)` |

Restart server = sesi baru. Dokumen harus diupload ulang.

---

## Struktur Modul

```
app/
├── main.py          # Routes FastAPI
├── pipeline.py      # RAGPipeline: retrieval, reranking, answer, conflict
├── ingestion.py     # IngestionPipeline: parse, chunk, enrich, index
├── prompts.py       # Semua prompt string (satu sumber kebenaran)
├── models.py        # Pydantic: QueryRequest, QueryResponse, Source, TrustScore
├── config.py        # Settings (env vars) + PipelineConfig (parameter)
├── stopwords.py     # Stopwords Indonesia untuk highlight excerpt
└── templates/
    ├── base.html
    ├── index.html
    ├── session.html
    └── components/
        ├── upload_success.html
        └── query_result.html
```

---

## Limitasi Arsitektur

| Limitasi | Status |
|----------|--------|
| Single-tenant, tidak ada isolasi antar user simultan | By design |
| BM25 in-memory, hilang jika server crash (Pinecone tetap ada) | By design |
| Tidak ada autentikasi | By design, bukan produk |
| Rate limiting berbasis IP in-memory, tidak persisten antar restart, tidak efektif di balik shared proxy | By design |
| Refresh browser: chat history hilang karena state hanya di DOM, dokumen tetap terindeks | By design |
