from fastapi import FastAPI, HTTPException, UploadFile, File, Request, Form
from fastapi.templating import Jinja2Templates
from fastapi.staticfiles import StaticFiles
from contextlib import asynccontextmanager
from collections import defaultdict
from typing import List
import tempfile
import shutil
import os
import re
import logging
import markdown
import bleach
from slowapi import Limiter, _rate_limit_exceeded_handler
from slowapi.util import get_remote_address
from slowapi.errors import RateLimitExceeded

from .config import settings, setup_logging
from .models import QueryRequest, QueryResponse, UploadResponse
from .pipeline import pipeline_service
from .stopwords import ID_STOPWORDS

setup_logging()
logger = logging.getLogger(__name__)

limiter = Limiter(key_func=get_remote_address)

ALLOWED_EXTENSIONS = settings.allowed_extensions_set

# Tags allowed in LLM-generated markdown answer
_ANSWER_TAGS = [
    "p", "br", "strong", "b", "em", "i", "ul", "ol", "li",
    "code", "pre", "blockquote", "h1", "h2", "h3", "h4", "h5", "h6",
    "a", "hr", "table", "thead", "tbody", "tr", "th", "td",
]
_ANSWER_ATTRS: dict = {"a": ["href", "title"], "code": ["class"], "td": ["align"], "th": ["align"]}

# Tags allowed in highlighted source excerpts
_EXCERPT_TAGS = ["mark"]
_EXCERPT_ATTRS: dict = {"mark": ["class"]}


@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("Initializing RAG Pipeline...")
    try:
        pipeline_service.initialize()
        logger.info("rag_pipeline_initialized", extra={"session_id": pipeline_service.session_id})
    except Exception as e:
        logger.error("rag_pipeline_init_failed", extra={"error": str(e)})

    yield

    try:
        pipeline_service.shutdown()
        logger.info("rag_pipeline_shutdown_complete")
    except Exception as e:
        logger.error("rag_pipeline_shutdown_failed", extra={"error": str(e)})


app = FastAPI(
    title="Indonesian Document Intelligence API",
    description="API for Ephemeral RAG Pipeline answering queries based on uploaded Indonesian work documents.",
    version="1.3.0",
    lifespan=lifespan
)
app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)

app.mount("/static", StaticFiles(directory="app/static"), name="static")
templates = Jinja2Templates(directory="app/templates")


@app.get("/")
async def web_index(request: Request):
    if pipeline_service.session_documents:
        files_processed = len({d.metadata.get("doc_id") for d in pipeline_service.session_documents})
        return templates.TemplateResponse(
            request=request,
            name="session.html",
            context={
                "response": {
                    "files_processed": files_processed,
                    "chunks_indexed": len(pipeline_service.session_documents),
                    "message": f"Dokumen di-ingest ke namespace ({pipeline_service.session_id}).",
                }
            }
        )
    return templates.TemplateResponse(request=request, name="index.html")


@app.post("/web/upload")
async def web_upload(request: Request, files: List[UploadFile] = File(...)):
    upload_resp = await upload_documents(request, files)
    return templates.TemplateResponse(
        request=request,
        name="components/upload_success.html",
        context={"response": upload_resp}
    )


def _highlight_excerpt(text: str, query: str) -> str:
    """Wrap matching query keywords in <mark class='hl'>, skipping stopwords."""
    words = sorted(
        [w for w in re.split(r'\W+', query.lower()) if len(w) > 3 and w not in ID_STOPWORDS],
        key=len, reverse=True
    )
    for word in words:
        text = re.sub(f'({re.escape(word)})', r'<mark class="hl">\1</mark>', text, flags=re.IGNORECASE)
    return bleach.clean(text, tags=_EXCERPT_TAGS, attributes=_EXCERPT_ATTRS, strip=True)


@app.post("/web/query")
async def web_query(request: Request, query: str = Form(...)):
    query_req = QueryRequest(query=query)
    resp = await query_endpoint(request, query_req)

    raw_html = markdown.Markdown(extensions=['extra']).convert(resp.answer)
    html_answer = bleach.clean(raw_html, tags=_ANSWER_TAGS, attributes=_ANSWER_ATTRS, strip=True)

    doc_chunks: dict = defaultdict(list)
    for s in resp.sources:
        doc_chunks[s.doc_id].append(s)

    all_sources = []
    for doc_id, chunks in doc_chunks.items():
        is_conflict = any(c.is_conflict_party for c in chunks)
        best = max(chunks, key=lambda c: c.relevance_score)
        excerpt_html = best.excerpt if is_conflict else _highlight_excerpt(best.excerpt, resp.query)
        all_sources.append({
            "doc_id": doc_id,
            "section": best.section,
            "is_conflict_party": is_conflict,
            "excerpt_html": excerpt_html,
            "score_pct": int(best.relevance_score * 100),
            "default_open": False,
        })

    all_sources.sort(key=lambda x: (0 if x["is_conflict_party"] else 1, -x["score_pct"]))

    return templates.TemplateResponse(
        request=request,
        name="components/query_result.html",
        context={
            "query": resp.query,
            "html_answer": html_answer,
            "trust": resp.trust,
            "has_conflict": resp.has_conflict,
            "all_sources": all_sources,
        }
    )


@app.post("/api/upload", response_model=UploadResponse)
@limiter.limit("5/minute")
async def upload_documents(request: Request, files: List[UploadFile] = File(...)) -> UploadResponse:
    try:
        from .ingestion import ingestion_service
    except ImportError as e:
        raise HTTPException(status_code=500, detail="Sistem ingestion gagal memuat. " + str(e))

    if len(files) > settings.max_upload_files:
        raise HTTPException(status_code=400, detail=f"Maksimal {settings.max_upload_files} file per upload.")

    for f in files:
        ext = os.path.splitext(f.filename or "")[1].lower()
        if ext not in ALLOWED_EXTENSIONS:
            raise HTTPException(
                status_code=400,
                detail=f"Format '{ext}' tidak didukung. Gunakan: {', '.join(sorted(ALLOWED_EXTENSIONS))}"
            )

    with tempfile.TemporaryDirectory() as temp_dir:
        files_processed = 0
        for f in files:
            file_path = os.path.join(temp_dir, f.filename)
            with open(file_path, "wb") as buffer:
                shutil.copyfileobj(f.file, buffer)
            size_mb = os.path.getsize(file_path) / (1024 * 1024)
            if size_mb > settings.max_file_size_mb:
                raise HTTPException(
                    status_code=400,
                    detail=f"File '{f.filename}' melebihi batas {settings.max_file_size_mb}MB ({size_mb:.1f}MB)."
                )
            files_processed += 1

        try:
            chunks = await ingestion_service.ingest_directory(temp_dir)
            return UploadResponse(
                message=f"Dokumen di-ingest secara terisolasi ke namespace ({pipeline_service.session_id}).",
                files_processed=files_processed,
                chunks_indexed=chunks
            )
        except Exception as e:
            logger.error("ingestion_failed", extra={"error": str(e)})
            raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/progress")
async def get_progress() -> dict:
    try:
        from .ingestion import ingestion_service
        return ingestion_service.progress
    except Exception:
        return {"current": 0, "total": 0, "done": True, "status": "idle"}


@app.post("/api/query", response_model=QueryResponse)
@limiter.limit("20/minute")
async def query_endpoint(request: Request, query_req: QueryRequest) -> QueryResponse:
    try:
        response = await pipeline_service.run(query_req.query)
        return response
    except RuntimeError as re:
        logger.error("query_runtime_error", extra={"error": str(re)})
        raise HTTPException(status_code=503, detail=str(re))
    except Exception as e:
        logger.error("query_unexpected_error", extra={"error": str(e)})
        raise HTTPException(status_code=500, detail="Internal server error executing query.")
