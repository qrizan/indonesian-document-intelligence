# PIPELINE.md

Session management: lihat [ARCHITECTURE.md](ARCHITECTURE.md).

---

## Parameter

| Parameter | Nilai | Keterangan |
|-----------|-------|------------|
| `chunk_size` | 512 token | SentenceSplitter |
| `chunk_overlap` | 100 token | SentenceSplitter |
| `top_k_retrieval` | 20 | Kandidat dari EnsembleRetriever |
| `top_k_rerank` | 10 | Chunk dikirim ke LLM setelah Jina reranking |
| `min_relevance` | 0.20 | Threshold filter, chunk di bawah ini dibuang |
| `embed_model` | `text-embedding-3-small` | |
| `llm_model` | `gpt-4o-mini` | Normalisasi, enrichment, answer+conflict |
| `reranker_model` | `jina-reranker-v2-base-multilingual` | |

---

## Ingestion Pipeline

```
File Upload (PDF / TXT / DOCX)
   -> SimpleDirectoryReader (LlamaIndex): parse teks
   -> SentenceSplitter: N chunk per dokumen
   -> GPT-4o-mini per chunk [LLM call]: ChunkEnrichment
        context_sentence, section, person, org, location, date, task
   -> page_content = "[Seksi: {section}\n][Ringkasan Konteks: {cs}\n\n]Teks Asli:\n{text}"
        (prefix hanya ditambahkan jika non-empty)
   -> Upsert ke Pinecone namespace + rebuild BM25
```

**Biaya:** sekitar 1 LLM call per chunk. Untuk 10 dokumen (~50 chunk) = ~50 calls saat upload.

---

## Query Pipeline

```
User query
   -> [LLM call 1] Normalisasi: typo/singkatan ke Bahasa Indonesia formal
   -> EnsembleRetriever: BM25[0.5] + Pinecone[0.5] -> top-20 (Reciprocal Rank Fusion)
   -> Jina Reranker v2 -> top-10, setiap chunk dapat relevance_score
   -> Filter: buang chunk < min_relevance; fallback: pakai 1 terbaik jika semua di bawah
   -> Context: "[{doc_id}] <c>{chunk_id}</c>\n{page_content}" per chunk, dipisah "---"
   -> [LLM call 2] Answer + Conflict Detection, structured output _AnswerWithCitations:
        answer, citations (chunk_id[]), has_conflict, conflict_doc_ids (doc_id[])
   -> Validasi:
        cited_docs = chunk yang ada di citations (fallback: semua retrieved jika kosong)
        Guard: has_conflict hanya valid jika cited_doc_ids >= 2 dokumen berbeda
        conflict_doc_ids = conflict_doc_ids & cited_doc_ids
   -> Trust score: not_found | found | conflict
   -> QueryResponse
```

**Total LLM call per query: 2.**

---

## Prompts (`app/prompts.py`)

Semua prompt didefinisikan di `app/prompts.py` sebagai satu sumber kebenaran.

| Konstanta | Digunakan di | Fungsi |
|-----------|-------------|--------|
| `ANSWER_SYSTEM` | `pipeline.py` | System prompt: instruksi jawab + aturan conflict detection |
| `ANSWER_HUMAN` | `pipeline.py` | `"Konteks:\n{context}\n\nPertanyaan: {question}"` |
| `QUERY_NORMALIZATION` | `pipeline.py` | Normalisasi query informal ke Bahasa Indonesia formal |
| `CHUNK_ENRICHMENT` | `ingestion.py` | Ekstrak context_sentence + entitas per chunk |

**Aturan conflict di `ANSWER_SYSTEM`:**
- `has_conflict=True` hanya jika dua atau lebih sumber menyatakan fakta berlawanan untuk pertanyaan yang sama
- Sumber dari periode berbeda, rapat berbeda, atau topik berbeda bukan konflik
- `conflict_doc_ids` harus berisi semua pihak yang berkonflik (minimal 2 doc_id)

---

## Limitasi Pipeline

| Limitasi | Dampak | Status |
|----------|--------|--------|
| Semantic retrieval tanpa topic tagging | Dokumen berbagi entitas (nama, periode) ikut ter-retrieve meski topik berbeda. Contoh: `email_sprint_retrospective.txt` muncul untuk query deployment Beta v3 | Open, perlu `document_type`/`project_tag` saat ingestion |
| Conflict detection hanya memeriksa chunk yang dikutip LLM | Konflik antara dokumen yang tidak ter-retrieve tidak terdeteksi | By design |
| Citation post-rationalization | LLM bisa mengklaim menggunakan chunk tertentu padahal jawabannya dari pengetahuan lain | Known LLM limitation |
| NER tersimpan di metadata Pinecone tapi tidak digunakan saat query | Entitas yang diekstrak tidak aktif untuk entity-aware filtering | By design untuk saat ini |
