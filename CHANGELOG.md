# CHANGELOG

Urutan terbaru di atas.

---

## v1.3.0 - Rate Limiting, Session State, LangSmith

**Rate limiting:**
`slowapi` ditambahkan: `POST /api/upload` 5/menit, `POST /api/query` 20/menit (IP-based, in-memory). Web routes tidak didekorasi terpisah karena limit berlaku otomatis lewat panggilan ke fungsi API.

**Session state saat refresh:**
`GET /` kini mengecek `session_documents`. Jika dokumen sudah terindeks, render query interface langsung tanpa upload ulang. Chat history tetap hilang karena state DOM. Mencegah duplikasi chunk akibat upload ulang yang tidak perlu.

**LangSmith:**
Enrichment call di `ingestion.py` dibungkus `with tracing_v2_enabled(False)`. Sebelumnya setiap upload menghasilkan N trace enrichment yang mencemari dashboard dan menyulitkan analisis query pipeline.

Lihat [DECISIONS.md](DECISIONS.md): DEC-030, DEC-031, DEC-032.

---

## v1.2.0 - Code Cleanup dan Dokumentasi

**Kode:**
- `app/prompts.py` dibuat sebagai satu sumber kebenaran untuk semua prompt
- `app/pipeline.py`: conflict guard ditambah; else branch diperbaiki agar conflict_doc_ids selalu kosong saat has_conflict=False; source building jadi list comprehension
- `app/ingestion.py`: `_enrich_chunk` return context_sentence langsung tanpa roundtrip parse; dead write metadata["text"] dihapus; prefix kosong dihilangkan saat enrichment gagal
- `app/models.py`: hapus field `pipeline_version` yang tidak digunakan
- `app/config.py`: hapus `logger` dan `artifacts_dir` yang tidak digunakan
- `app/main.py`: pindah `defaultdict` import ke top-level
- `scripts/test_pipeline.py`: conflict_parties deduplicated dengan set comprehension

**Dokumentasi:** Semua doc disederhanakan, satu fakta satu tempat.

---

## v1.1.0 - Conflict Detection Refactor

**Masalah:** `check_conflict()` sebagai LLM call terpisah menghasilkan false positive. Tidak tahu konteks query.

**Perubahan `app/pipeline.py`:**
- `check_conflict()` dihapus
- `_AnswerWithCitations` ditambah `has_conflict: bool` dan `conflict_doc_ids: List[str]`
- Conflict detection digabung ke answer generation (satu LLM call)
- Early return dengan `sources=[]` saat `trust.label == "not_found"`
- LLM call per query: 3 turun menjadi 2

Lihat [DECISIONS.md](DECISIONS.md): DEC-028, DEC-029.

---

## v1.0.0 - Baseline Aplikasi

- Trust score: formula numerik diganti 3 label (`found` / `not_found` / `conflict`)
- Reranker: Cohere diganti Jina Reranker v2 karena quota Cohere habis
- Citation markers `<c>chunk_id</c>` + `_AnswerWithCitations` structured output
- Parameter: chunk_size 300 ke 512, overlap 50 ke 100, top_k_rerank 5 ke 10, min_relevance 0.35 ke 0.20
- UI: redesign dengan Tailwind custom, HTMX, typing bubble, conflict warning banner
- Pinecone: ephemeral namespace per sesi (UUID)

Lihat [DECISIONS.md](DECISIONS.md): DEC-022 sampai DEC-027.
