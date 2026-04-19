import uuid
import logging
from typing import List, Any
from pydantic import BaseModel, Field as PydanticField

from .config import settings, pipeline_config
from .models import QueryResponse, TrustScore, Source
from .prompts import ANSWER_SYSTEM, ANSWER_HUMAN, QUERY_NORMALIZATION

from langchain_openai import ChatOpenAI, OpenAIEmbeddings
from langchain_pinecone import PineconeVectorStore
from langchain_community.retrievers import BM25Retriever
from langchain_community.document_compressors import JinaRerank
from langchain_classic.retrievers import EnsembleRetriever
from langchain_classic.retrievers.contextual_compression import ContextualCompressionRetriever
from langchain_core.prompts import ChatPromptTemplate
from langchain_core.documents import Document
from pinecone import Pinecone

logger = logging.getLogger(__name__)


class _AnswerWithCitations(BaseModel):
    answer: str = PydanticField(
        description="Jawaban dalam Bahasa Indonesia. Jika tidak ditemukan tulis 'Tidak ditemukan dalam dokumen.'"
    )
    citations: List[str] = PydanticField(
        default_factory=list,
        description="Daftar chunk_id dari marker <c>chunk_id</c> yang benar-benar digunakan. Kosongkan jika tidak ditemukan."
    )
    has_conflict: bool = PydanticField(
        default=False,
        description=(
            "True jika dua atau lebih sumber memberikan fakta yang SALING BERTENTANGAN "
            "untuk pertanyaan ini — misalnya nilai berbeda untuk hal yang sama persis "
            "(tanggal, nama PIC, status). "
            "False jika sumber membahas topik berbeda, periode berbeda, atau tidak ada kontradiksi."
        )
    )
    conflict_doc_ids: List[str] = PydanticField(
        default_factory=list,
        description="doc_id dari dokumen yang saling berkonflik. Isi hanya jika has_conflict True."
    )


class RAGPipeline:
    def __init__(self) -> None:
        self.is_initialized  = False
        self.session_id      = f"session-{uuid.uuid4().hex[:8]}"
        self.pc              = None
        self.pinecone_index  = None
        self.session_documents: List[Document] = []
        self.retriever       = None

        self.llm        = ChatOpenAI(model=pipeline_config.llm_model, temperature=0)
        self.embeddings = OpenAIEmbeddings(model=pipeline_config.embed_model)
        self.answer_llm = self.llm.with_structured_output(_AnswerWithCitations)

        self.answer_prompt = ChatPromptTemplate.from_messages([
            ("system", ANSWER_SYSTEM),
            ("human",  ANSWER_HUMAN),
        ])

    def initialize(self) -> None:
        self.pc             = Pinecone(api_key=settings.pinecone_api_key)
        self.pinecone_index = self.pc.Index(pipeline_config.pinecone_index)

        self._cleanup_stale_sessions()

        self.vectorstore = PineconeVectorStore(
            index=self.pinecone_index,
            embedding=self.embeddings,
            namespace=self.session_id
        )
        self.pinecone_ret = self.vectorstore.as_retriever(
            search_kwargs={"k": pipeline_config.top_k_retrieval}
        )
        self.is_initialized = True
        logger.info(f"Pipeline initialized — namespace: {self.session_id}")

    def _cleanup_stale_sessions(self) -> None:
        try:
            stats = self.pinecone_index.describe_index_stats()
            stale = [ns for ns in stats.namespaces if ns.startswith("session-") and ns != self.session_id]
            for ns in stale:
                self.pinecone_index.delete(delete_all=True, namespace=ns)
                logger.info(f"Stale namespace dihapus: {ns}")
            if stale:
                logger.info(f"{len(stale)} stale namespace dibersihkan saat startup.")
        except Exception as e:
            logger.warning(f"Cleanup stale sessions gagal (non-fatal): {e}")

    def shutdown(self) -> None:
        if self.pinecone_index:
            try:
                self.pinecone_index.delete(delete_all=True, namespace=self.session_id)
                logger.info(f"Namespace {self.session_id} dihapus dari Pinecone.")
            except Exception as e:
                logger.error(f"Gagal menghapus namespace {self.session_id}: {e}")

    def _rebuild_retrievers(self) -> None:
        if not self.session_documents:
            self.retriever = None
            return

        bm25_ret   = BM25Retriever.from_documents(self.session_documents)
        bm25_ret.k = pipeline_config.top_k_retrieval

        hybrid_ret = EnsembleRetriever(
            retrievers=[bm25_ret, self.pinecone_ret],
            weights=[0.5, 0.5]
        )
        reranker = JinaRerank(
            model=pipeline_config.reranker_model,
            top_n=pipeline_config.top_k_rerank
        )
        self.retriever = ContextualCompressionRetriever(
            base_compressor=reranker,
            base_retriever=hybrid_ret
        )

    async def add_documents(self, docs: List[Document]) -> None:
        await self.vectorstore.aadd_documents(docs)
        self.session_documents.extend(docs)
        self._rebuild_retrievers()

    async def normalize_query(self, query: str) -> str:
        prompt = QUERY_NORMALIZATION.format(query=query)
        try:
            res  = await self.llm.ainvoke(prompt)
            norm = res.content.strip()
            if norm and norm != query:
                logger.info(f"Query normalized: '{query}' → '{norm}'")
            return norm if norm else query
        except Exception as e:
            logger.warning(f"Normalisasi gagal, pakai query asli: {e}")
            return query

    def compute_trust_score(self, cited_docs: List[Any], answer: str, has_conflict: bool) -> TrustScore:
        n = len(cited_docs)
        if not n or "tidak ditemukan dalam dokumen" in answer.lower():
            return TrustScore(label="not_found", source_count=0)
        if has_conflict:
            return TrustScore(label="conflict", source_count=n)
        return TrustScore(label="found", source_count=n)

    async def run(self, query: str) -> QueryResponse:
        if not self.is_initialized:
            raise RuntimeError("Pipeline belum diinisialisasi.")
        if self.retriever is None:
            raise RuntimeError("Belum ada dokumen yang diunggah di sesi ini.")

        normalized_query = await self.normalize_query(query)

        try:
            retrieved_docs = await self.retriever.ainvoke(normalized_query)
        except NotImplementedError:
            retrieved_docs = self.retriever.invoke(normalized_query)

        logger.info(
            "Retrieval scores: %s",
            [{"doc_id": d.metadata.get("doc_id"), "score": round(d.metadata.get("relevance_score", 0), 3)}
             for d in retrieved_docs]
        )

        filtered_docs  = [d for d in retrieved_docs if d.metadata.get("relevance_score", 0) >= pipeline_config.min_relevance]
        retrieved_docs = filtered_docs or retrieved_docs[:1]
        logger.info("Chunk setelah filter (threshold=%.2f): %d", pipeline_config.min_relevance, len(retrieved_docs))

        chunk_map     = {d.metadata.get("chunk_id", f"chunk-{i}"): d for i, d in enumerate(retrieved_docs)}
        context_parts = [
            f"[{d.metadata.get('doc_id', '')}] <c>{cid}</c>\n{d.page_content}"
            for cid, d in chunk_map.items()
        ]
        context = "\n\n---\n\n".join(context_parts)

        answer_result    = await self.answer_llm.ainvoke(
            self.answer_prompt.format_messages(context=context, question=normalized_query)
        )
        answer           = answer_result.answer
        has_conflict     = answer_result.has_conflict
        conflict_doc_ids = set(answer_result.conflict_doc_ids)

        cited_docs    = [chunk_map[cid] for cid in answer_result.citations if cid in chunk_map]
        if not cited_docs:
            cited_docs = retrieved_docs

        cited_doc_ids = {d.metadata.get("doc_id") for d in cited_docs}

        # konflik hanya valid jika minimal 2 dokumen berbeda dikutip
        if has_conflict and len(cited_doc_ids) >= 2:
            conflict_doc_ids = conflict_doc_ids & cited_doc_ids
        else:
            if has_conflict:
                logger.info("has_conflict di-reset ke False: hanya %d sumber dikutip", len(cited_doc_ids))
            has_conflict     = False
            conflict_doc_ids = set()

        trust = self.compute_trust_score(cited_docs, answer, has_conflict)

        logger.info("has_conflict=%s conflict_doc_ids=%s", has_conflict, conflict_doc_ids)

        if trust.label == "not_found":
            return QueryResponse(
                query=normalized_query,
                answer=answer,
                trust=trust,
                sources=[],
                has_conflict=False
            )

        sources = [
            Source(
                doc_id=d.metadata.get("doc_id", "unknown"),
                section=d.metadata.get("section", ""),
                excerpt=d.page_content.strip(),
                relevance_score=round(d.metadata.get("relevance_score", 0.5), 3),
                is_conflict_party=d.metadata.get("doc_id") in conflict_doc_ids
            )
            for d in cited_docs
        ]

        return QueryResponse(
            query=normalized_query,
            answer=answer,
            trust=trust,
            sources=sources,
            has_conflict=has_conflict
        )


pipeline_service = RAGPipeline()
