# DECISIONS.md

Log keputusan teknis yang mempengaruhi runtime aplikasi saat ini. Keputusan notebook/eksperimen yang sudah superseded tidak dicatat di sini.

---

## DEC-001 - Pembagian Peran LlamaIndex dan LangChain

LlamaIndex menangani document layer (parsing, chunking). LangChain menangani retrieval dan orchestration.

**Rationale:** LlamaIndex lebih matang untuk document pipeline; LangChain lebih kuat untuk retrieval orchestration. Batas peran yang jelas mencegah overlap.

**Trade-off:** Dua dependency besar.

---

## DEC-002 - Pinecone sebagai Vector Store

Pinecone dipilih atas FAISS dan Qdrant karena proyek sebelumnya sudah pakai Qdrant. Variasi ini menunjukkan familiarity dengan lebih dari satu platform. Managed service juga lebih representatif untuk demo portfolio.

**Trade-off:** Butuh API key, tidak bisa fully offline.

---

## DEC-022 - Ephemeral Namespace per Sesi

Setiap server startup menghasilkan UUID sesi sebagai Pinecone namespace. Namespace dihapus total saat shutdown.

**Rationale:** Menghindari desinkronisasi antara BM25 in-memory dan Pinecone, dan mencegah data sisa dari sesi sebelumnya mencemari hasil. Lebih sederhana dari state management yang persisten untuk scope single-tenant ini.

**Trade-off:** Dokumen harus diupload ulang setiap restart.

---

## DEC-023 - Frontend via SSR (HTMX + Alpine.js)

Jinja2 + HTMX (AJAX partial swap) + Alpine.js (reactive state micro) + Tailwind CSS (CDN). Tanpa build step, tanpa bundle.

**Rationale:** Tidak ada kebutuhan client-side routing atau state kompleks.

**Trade-off:** Tidak cocok untuk aplikasi dengan state klien yang kompleks.

---

## DEC-024 - Migrasi Reranker dari Cohere ke Jina Reranker v2

Cohere Trial quota habis (334 reranks dalam satu hari). Ganti ke `jina-reranker-v2-base-multilingual`.

**Rationale:** 10 juta token gratis, drop-in replacement via `langchain_community.JinaRerank`, multilingual termasuk Bahasa Indonesia.

**Trade-off:** Jina kurang dikenal industri dibanding Cohere, acceptable untuk skala portfolio.

---

## DEC-025 - Source Attribution Berbasis Citation Markers

Setiap chunk diberi ID `<c>chunk_id</c>` di konteks. LLM mengembalikan daftar chunk_id yang digunakan via `_AnswerWithCitations` structured output. Sumber yang ditampilkan hanya dari citations, bukan top-N retrieved.

**Rationale:** Menampilkan top-N retrieved selalu, terlepas apakah LLM menggunakannya, menyesatkan user. Citation markers membuat attribution lebih akurat. (Ref: Gao et al. 2023, ALCE framework)

**Keterbatasan:** LLM bisa post-rationalize, mengklaim menggunakan chunk tertentu padahal tidak. Tidak ada solusi deterministik tanpa ground truth per chunk.

---

## DEC-026 - Trust Score: Tiga Label Kategoris

Menggantikan formula numerik tiga komponen sebelumnya.

`TrustScore(label, source_count)` dengan label `found` / `not_found` / `conflict`.

**Rationale:** Formula numerik (avg_relevance + bonus) tidak pernah dikalibrasi ke data nyata, bobotnya heuristik. Label kategoris lebih jujur karena berbasis sinyal deterministik: apakah LLM menyatakan tidak menemukan jawaban, dan apakah konflik terdeteksi.

**Trade-off:** Kehilangan granularitas. Diterima karena tanpa dataset kalibrasi, angka numerik hanya terlihat presisi.

---

## DEC-027 - Parameter Final Pipeline

| Parameter | Nilai lama | Nilai baru | Alasan |
|-----------|------------|------------|--------|
| chunk_size | 300 | 512 | Standar de facto RAG (Lewis et al. 2020); 300 terlalu pendek, informasi terpotong |
| chunk_overlap | 50 | 100 | Proporsional dengan chunk_size baru |
| top_k_rerank | 5 | 10 | top_n=5 terlalu agresif, recall turun dari 92% ke 60% |
| min_relevance | 0.35 | 0.20 | 0.35 membuang chunk relevan untuk dokumen kerja informal |

**Trade-off:** Chunk lebih besar = biaya embedding lebih tinggi. min_relevance lebih rendah = lebih banyak noise ke LLM (tapi LLM bisa mengabaikan via citation mechanism).

---

## DEC-028 - Conflict Detection Digabung ke Answer Generation

Menggantikan `check_conflict()` sebagai LLM call terpisah.

`_AnswerWithCitations` diperluas dengan `has_conflict: bool` dan `conflict_doc_ids: List[str]`. `check_conflict()` dihapus.

**Rationale:** LLM call terpisah tidak mengetahui konteks query, menghasilkan false positive (dua notulen rapat berbeda dianggap konflik hanya karena menyebut orang yang sama). LLM yang sudah menjawab pertanyaan memiliki semua informasi yang dibutuhkan untuk mendeteksi konflik. (Ref: ICR framework, ScienceDirect 2025)

**Trade-off:** Answer prompt lebih panjang. Conflict detection tidak bisa ditest independen dari answer generation.

**Masalah terbuka:** `email_sprint_retrospective.txt` masih muncul sebagai sumber untuk query Beta v3. Ini batas retrieval semantik, bukan batas conflict detection.

---

## DEC-029 - Conflict Guard: Minimal 2 Dokumen Dikutip

```python
if has_conflict and len(cited_doc_ids) >= 2:
    conflict_doc_ids = conflict_doc_ids & cited_doc_ids
else:
    has_conflict     = False
    conflict_doc_ids = set()
```

**Rationale:** Satu dokumen tidak bisa berkonflik dengan dirinya sendiri. Guard ini mencegah dua bug: (1) LLM set `has_conflict=True` dari satu dokumen yang mencatat perubahan nilai; (2) `conflict_doc_ids` non-empty saat `has_conflict=False` karena LLM inconsistency, yang menyebabkan red border muncul tanpa conflict banner.

Enforcement di kode (bukan hanya prompt) karena invariant logis tidak boleh bergantung pada kepatuhan LLM.

**Dampak pada test:** S3 kadang fail dengan perilaku yang benar (trust=found) ketika retrieval hanya mengembalikan satu dokumen relevan.

---

## DEC-030 - LangSmith Tracing Dinonaktifkan saat Ingestion

Enrichment call di `ingestion.py` dibungkus `with tracing_v2_enabled(False)` agar tidak masuk ke LangSmith.

**Rationale:** Tracing aktif secara global via env var. Tanpa guard, setiap upload menghasilkan N trace (satu per chunk) yang mencemari dashboard dan menyulitkan analisis query pipeline. Enrichment adalah preprocessing satu arah; kegagalannya sudah di-log via `logger.warning`. Yang bernilai di-trace adalah query pipeline: normalization, retrieval, answer+conflict.

**Trade-off:** Kegagalan enrichment tidak terlihat di LangSmith, hanya di server log.

---

## DEC-031 - GET / Render Query Page jika Dokumen Sudah Terindeks

`GET /` mengecek `pipeline_service.session_documents`. Jika non-empty, render `session.html` (query interface); jika kosong, render `index.html` (upload form).

**Rationale:** Tanpa ini, refresh browser saat sesi aktif selalu mengembalikan halaman upload, padahal data masih terindeks di server. User yang upload ulang dokumen yang sama akan menduplikasi chunk di Pinecone, menghasilkan retrieval noise. `session.html` adalah full-page wrapper yang meng-include `upload_success.html` agar markup query UI tidak duplikat.

**Trade-off:** Chat history tetap hilang saat refresh karena state chat hanya ada di DOM browser. Lihat [ARCHITECTURE.md](ARCHITECTURE.md).

---

## DEC-032 - Rate Limiting via slowapi (IP-based, In-Memory)

Rate limiting diterapkan hanya di endpoint `/api/*` menggunakan `slowapi` + `get_remote_address`.

| Endpoint | Limit |
|----------|-------|
| `POST /api/upload` | 5/menit |
| `POST /api/query` | 20/menit |

Web routes (`/web/upload`, `/web/query`) tidak didekorasi secara terpisah karena keduanya memanggil fungsi API langsung, sehingga limit berlaku secara otomatis. Dekorasi ganda akan menghitung satu request dua kali.

**Rationale:** Query = 2 LLM call (normalization + answer), upload = N kali LLM call per chunk. Limit melindungi OpenAI quota dan Jina quota dari abuse atau loop tak sengaja.

**Trade-off:** Counter in-memory, reset saat server restart, tidak efektif di balik shared NAT/proxy. Acceptable untuk skala single-tenant portfolio.
