# EVALUATION.md

---

## Fase 1 - Evaluasi Notebook dengan RAGAS

**Dataset:** 50 query sintetis yang dibuat oleh GPT-4o-mini dari dokumen yang sama.

**Catatan penting sebelum membaca angka:**
Query dan dokumen memiliki vocabulary overlap yang tinggi karena keduanya dihasilkan oleh model yang sama. Ini menciptakan retrieval yang terlalu mudah secara artifisial. Angka raw retrieval (98-99%) tidak mencerminkan performa nyata terhadap query pengguna asli. Evaluasi ini hanya valid sebagai sanity check awal pipeline, bukan sebagai ukuran performa sebenarnya.

| Metrik | Target | Hasil | Status |
|--------|--------|-------|--------|
| Faithfulness | >= 0.75 | 0.633 | Tidak tercapai |
| Answer Relevancy | >= 0.70 | 0.730 | Tercapai |
| Context Recall | >= 0.70 | 0.600 | Tidak tercapai |

Faithfulness 0.633 berarti sekitar 37% dari klaim dalam jawaban tidak dapat diverifikasi langsung dari chunk yang diambil. Ini bisa disebabkan oleh LLM yang melakukan paraphrase agresif atau menggunakan pengetahuan di luar konteks. Context Recall 0.600 berarti chunk yang relevan sering tidak masuk ke top-k retrieval.

---

## Fase 2 - Evaluasi Fungsional End-to-End

Dijalankan via `scripts/test_pipeline.py` terhadap server yang berjalan dengan dokumen sintetis. **9/10 skenario passed.**

```bash
docker compose up && python scripts/test_pipeline.py
```

| ID | Skenario | Status | Keterangan |
|----|----------|--------|------------|
| S1 | Single doc, query normal | Passed | |
| S2 | Multi-doc, tidak ada konflik | Passed | |
| S3 | Konflik tanggal Beta v3 | Failed | Lihat di bawah |
| S4 | Konflik PIC Beta v3 | Passed | |
| S5 | Informasi tidak ada di dokumen | Passed | |
| S6 | Query off-topic | Passed | |
| S7 | Dokumen pengetahuan umum | Passed | |
| S8 | Sintesis action items | Passed | |
| S9 | Dokumen chat WhatsApp | Passed | |
| S10 | Tokoh ambigu di banyak dokumen | Passed | |

**Catatan tentang S3 (Failed):**
`email_sprint_retrospective.txt` menyebut nama (Emma, Ava, Liam) dan periode (Nov-Des 2025) yang sama dengan dokumen Beta v3. Jina reranker memberi skor 0.43-0.54, cukup untuk lolos threshold 0.20. Akibatnya retrieval mengambil dokumen yang tidak relevan, conflict guard tidak memiliki cukup dokumen yang tepat, dan conflict tidak terdeteksi. Ini adalah batas retrieval semantik tanpa topic tagging, bukan bug conflict detection.

Lihat [PIPELINE.md](PIPELINE.md) dan [DECISIONS.md](DECISIONS.md): DEC-028.

---

## Apa yang Belum Dievaluasi

- Performa dengan dokumen nyata (semua data saat ini sintetis)
- Conflict detection precision/recall setelah refactor single-call
- Dokumen panjang (>50 halaman) dan format tidak standar (tabel, PDF multi-kolom)
- Performa retrieval setelah ada dokumen yang di-upload ulang (potensi duplikasi chunk di Pinecone)
