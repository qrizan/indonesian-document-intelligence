import os
import uuid
import logging
import json
from typing import List
from llama_index.core import SimpleDirectoryReader
from llama_index.core.node_parser import SentenceSplitter
from langchain_openai import ChatOpenAI
from langchain_core.documents import Document
from langchain_core.tracers.context import tracing_v2_enabled
from pydantic import BaseModel, Field

from .config import pipeline_config
from .pipeline import pipeline_service
from .prompts import CHUNK_ENRICHMENT

logger = logging.getLogger(__name__)


class ChunkEnrichment(BaseModel):
    context_sentence: str = Field(description="Satu kalimat ringkasan konteks tentang apa atau siapa teks ini.")
    section: str = Field(default="", description="Judul bagian/seksi dokumen tempat teks ini berada (contoh: 'Keputusan', 'Action Items', 'Peserta', 'Langkah-Langkah'). Kosongkan jika tidak ada struktur seksi yang jelas.")
    person: List[str] = Field(default_factory=list, description="Nama orang")
    organization: List[str] = Field(default_factory=list, description="Nama instansi/perusahaan/tim")
    location: List[str] = Field(default_factory=list, description="Nama tempat")
    date: List[str] = Field(default_factory=list, description="Waktu atau tanggal")
    task: List[str] = Field(default_factory=list, description="Tugas, pekerjaan, atau deadline")


class IngestionPipeline:
    def __init__(self) -> None:
        self.llm            = ChatOpenAI(model=pipeline_config.llm_model, temperature=0)
        self.structured_llm = self.llm.with_structured_output(ChunkEnrichment)
        self.progress: dict = {"current": 0, "total": 0, "done": True, "status": "idle"}

    async def _enrich_chunk(self, text: str) -> tuple[str, dict]:
        try:
            with tracing_v2_enabled(False):
                res: ChunkEnrichment = await self.structured_llm.ainvoke(CHUNK_ENRICHMENT.format(text=text))
            entities = {
                "section":      res.section,
                "person":       res.person,
                "organization": res.organization,
                "location":     res.location,
                "date":         res.date,
                "task":         res.task,
            }
            return res.context_sentence, entities
        except Exception as e:
            logger.warning(f"Enrichment gagal, fallback ke teks asli. Err: {e}")
            return "", {}

    async def ingest_directory(self, temp_dir: str) -> int:
        logger.info("Membaca dokumen dari session upload...")
        reader = SimpleDirectoryReader(input_dir=temp_dir, required_exts=[".txt", ".pdf", ".docx"])
        docs   = reader.load_data()

        if not docs:
            return 0

        logger.info("Memotong teks menjadi chunk (SentenceSplitter)...")
        splitter = SentenceSplitter(
            chunk_size=pipeline_config.chunk_size,
            chunk_overlap=pipeline_config.chunk_overlap,
        )
        nodes = splitter.get_nodes_from_documents(docs)

        self.progress  = {"current": 0, "total": len(nodes), "done": False, "status": "processing"}
        langchain_docs = []

        for i, node in enumerate(nodes):
            self.progress["current"] = i + 1
            logger.info(f"Enrichment chunk {i+1}/{len(nodes)}...")

            context_sentence, entities = await self._enrich_chunk(node.text)

            doc_id   = os.path.basename(node.metadata.get("file_name", "unknown"))
            chunk_id = str(uuid.uuid4())
            section  = entities.pop("section", "")

            prefix          = f"Seksi: {section}\n" if section else ""
            context_prefix  = f"Ringkasan Konteks: {context_sentence}\n\n" if context_sentence else ""
            page_content    = f"{prefix}{context_prefix}Teks Asli:\n{node.text}"

            metadata = {
                "doc_id":   doc_id,
                "chunk_id": chunk_id,
                "section":  section,
                "text":     page_content,
            }
            if entities:
                metadata["entities"] = json.dumps(entities, ensure_ascii=False)

            langchain_docs.append(Document(page_content=page_content, metadata=metadata))

        logger.info("Mengirim vektor ke Pinecone dan me-refresh BM25 memori...")
        if langchain_docs:
            await pipeline_service.add_documents(langchain_docs)

        self.progress["done"]   = True
        self.progress["status"] = "done"
        return len(langchain_docs)


ingestion_service = IngestionPipeline()
