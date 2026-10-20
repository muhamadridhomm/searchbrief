"""FastAPI endpoints for the first local-only SearchBrief slice."""

from __future__ import annotations

import json
import subprocess
from queue import Queue
from threading import Thread
from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field, HttpUrl, model_validator

from .service import InvalidModelOutput, ModelUnavailable, OLLAMA_MODEL, OLLAMA_REVIEW_MODEL, OLLAMA_URL, _post_json, audit_draft, generate, review_draft_quality
from .research import ResearchUnavailable, _rank_sources, plan_queries, recheck_page, recheck_publication, research_sources as find_sources, search_github_repositories, search_openalex, search_pages, search_publications, search_saved_sources, search_stackexchange
from .images import ImageServiceError, generate_comfy_image, generate_image, search_images

app = FastAPI(title="SearchBrief Local API", version="0.1.0")
PROJECT_ROOT = Path(__file__).resolve().parents[2]
OLLAMA_START_SCRIPT = PROJECT_ROOT / "scripts" / "start-ollama-local.sh"
OLLAMA_BINARY = PROJECT_ROOT / ".tools" / "ollama" / "bin" / "ollama"
OLLAMA_MODEL_MANIFEST = PROJECT_ROOT / ".models" / "ollama" / "manifests" / "registry.ollama.ai" / "library" / "qwen3" / "4b"
_OLLAMA_PROCESS = None
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000", "http://127.0.0.1:3000", "http://localhost:3001", "http://127.0.0.1:3001"],
    allow_credentials=False,
    allow_methods=["GET", "POST"],
    allow_headers=["Content-Type"],
)


class Evidence(BaseModel):
    id: str = Field(min_length=1, max_length=60)
    title: str = Field(min_length=1, max_length=180)
    summary: str = Field(min_length=1, max_length=1200)
    url: HttpUrl | None = None


class SavedSource(Evidence):
    provider: str = Field(default="Saved source", max_length=80)
    venue: str = Field(default="", max_length=120)
    publication_date: str = Field(default="", max_length=30)
    retrieved_at: str = Field(default="", max_length=60)
    savedAt: str = Field(default="", max_length=60)


class ResearchRequest(BaseModel):
    topic: str = Field(min_length=3, max_length=240)
    question: str = Field(min_length=3, max_length=600)
    search_mode: str = Field(default="web_only", pattern="^(saved_then_web|web_only)$")
    saved_sources: list[SavedSource] = Field(default_factory=list, max_length=200)


class RecheckRequest(BaseModel):
    source_id: str = Field(min_length=1, max_length=60)
    summary: str = Field(min_length=1, max_length=1200)
    source_url: HttpUrl | None = None


class ImageSearchRequest(BaseModel):
    query: str = Field(min_length=3, max_length=180)


class ImageGenerateRequest(BaseModel):
    prompt: str = Field(min_length=10, max_length=600)
    api_key: str = Field(min_length=10, max_length=300)


class ComfyGenerateRequest(BaseModel):
    prompt: str = Field(min_length=10, max_length=600)
    base_url: str = Field(default="http://127.0.0.1:8188", max_length=240)
    workflow: dict[str, Any]
    prompt_node_id: str = Field(min_length=1, max_length=30)


@app.post("/api/images/comfyui")
def image_generate_comfy(request: ComfyGenerateRequest) -> dict[str, Any]:
    try:
        return {"image": generate_comfy_image(request.prompt, request.base_url, request.workflow, request.prompt_node_id)}
    except ImageServiceError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc


class AuditRequest(BaseModel):
    draft: str = Field(min_length=1, max_length=12000)
    claim_to_check: str = Field(default="", max_length=600)
    evidence: list[Evidence] = Field(min_length=1, max_length=12)


class DraftQualityRequest(BaseModel):
    topic: str = Field(min_length=3, max_length=240)
    reader: str = Field(min_length=3, max_length=240)
    question: str = Field(min_length=3, max_length=600)
    useful_outcome: str = Field(min_length=3, max_length=600)
    current_brief: str = Field(default="", max_length=4000)
    draft: str = Field(min_length=1, max_length=12000)
    target_words_min: int = Field(default=120, ge=50, le=500)
    target_words_max: int = Field(default=180, ge=50, le=700)
    paragraphs_min: int = Field(default=2, ge=1, le=8)
    paragraphs_max: int = Field(default=4, ge=1, le=10)
    sentences_min: int = Field(default=2, ge=1, le=8)
    sentences_max: int = Field(default=4, ge=1, le=10)
    paragraph_style: str = Field(default="problem_explanation_takeaway", max_length=60)
    sentence_style: str = Field(default="varied", max_length=60)
    overall_tone: str = Field(default="conversational_professional", max_length=60)

    @model_validator(mode="after")
    def validate_ranges(self):
        if self.target_words_min > self.target_words_max:
            raise ValueError("Minimum word count must not exceed maximum word count.")
        if self.paragraphs_min > self.paragraphs_max:
            raise ValueError("Minimum paragraph count must not exceed maximum paragraph count.")
        if self.sentences_min > self.sentences_max:
            raise ValueError("Minimum sentences per paragraph must not exceed maximum.")
        return self


@app.post("/api/audit")
def run_claim_audit(request: AuditRequest) -> dict[str, Any]:
    result = audit_draft(request.model_dump(mode="json"), request.draft)
    return result


@app.post("/api/draft-quality")
def run_draft_quality_review(request: DraftQualityRequest) -> dict[str, Any]:
    try:
        result = review_draft_quality(request.model_dump(mode="json"), request.draft)
        return {**result, "reviewed_draft": request.draft}
    except ModelUnavailable as exc:
        raise HTTPException(status_code=503, detail="The separate draft-quality reviewer is unavailable. Check Ollama and retry.") from exc
    except InvalidModelOutput as exc:
        raise HTTPException(status_code=502, detail=f"{exc} Your draft is unchanged; retry the manual review.") from exc


@app.post("/api/images/search")
def image_search(request: ImageSearchRequest) -> dict[str, Any]:
    try:
        return {"images": search_images(request.query)}
    except ImageServiceError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc


@app.post("/api/images/generate")
def image_generate(request: ImageGenerateRequest) -> dict[str, Any]:
    try:
        return {"image": generate_image(request.prompt, request.api_key)}
    except ImageServiceError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc


class GenerateRequest(BaseModel):
    topic: str = Field(min_length=3, max_length=240)
    reader: str = Field(min_length=3, max_length=240)
    question: str = Field(min_length=3, max_length=600)
    useful_outcome: str = Field(min_length=3, max_length=600)
    writer_notes: str = Field(default="", max_length=2000)
    claim_to_check: str = Field(default="", max_length=600)
    evidence: list[Evidence] = Field(default_factory=list, max_length=12)
    previous_draft: str = Field(default="", max_length=12000)
    variation_instruction: str = Field(default="", max_length=240)
    audit_sources: bool = True
    target_words_min: int = Field(default=120, ge=50, le=500)
    target_words_max: int = Field(default=180, ge=50, le=700)
    paragraphs_min: int = Field(default=2, ge=1, le=8)
    paragraphs_max: int = Field(default=4, ge=1, le=10)
    sentences_min: int = Field(default=2, ge=1, le=8)
    sentences_max: int = Field(default=4, ge=1, le=10)
    paragraph_style: str = Field(default="problem_explanation_takeaway", pattern="^(problem_explanation_takeaway|narrative|concise_blocks)$")
    sentence_style: str = Field(default="varied", pattern="^(short_direct|varied|detailed)$")
    overall_tone: str = Field(default="conversational_professional", pattern="^(plain|conversational_professional|reflective|professional)$")
    custom_style: str = Field(default="", max_length=300)
    hashtag_mode: str = Field(default="off", pattern="^(off|auto|custom)$")
    hashtag_count: int = Field(default=3, ge=1, le=15)
    custom_hashtags: str = Field(default="", max_length=300)
    add_imperfections: bool = False
    imperfection_level: str = Field(default="light", pattern="^(light|medium|noticeable)$")

    @model_validator(mode="after")
    def validate_ranges(self):
        if self.audit_sources and not self.evidence:
            raise ValueError("Source comparison requires at least one evidence note, or disable audit_sources.")
        if self.target_words_min > self.target_words_max:
            raise ValueError("Minimum word count must not exceed maximum word count.")
        if self.paragraphs_min > self.paragraphs_max:
            raise ValueError("Minimum paragraph count must not exceed maximum paragraph count.")
        if self.sentences_min > self.sentences_max:
            raise ValueError("Minimum sentences per paragraph must not exceed maximum.")
        if self.hashtag_mode == "custom" and not self.custom_hashtags.strip():
            raise ValueError("Enter hashtags when custom hashtag mode is selected.")
        return self


class ClaimFeedback(BaseModel):
    claim: str = Field(max_length=1200)
    status: str = Field(default="needs_review", max_length=40)
    reason: str = Field(default="", max_length=1200)
    evidence_excerpt: str = Field(default="", max_length=1200)
    source_ids: list[str] = Field(default_factory=list, max_length=12)
    checked_by_user: bool = False
    reviewer_note: str = Field(default="", max_length=1200)
    revision_action: str = Field(default="undecided", pattern="^(undecided|keep|rewrite|remove|source_needed)$")


class RevisionRequest(GenerateRequest):
    current_draft: str = Field(min_length=1, max_length=12000)
    current_brief: str = Field(default="", max_length=4000)
    revision_notes: str = Field(default="", max_length=3000)
    claim_reviews: list[ClaimFeedback] = Field(default_factory=list, max_length=60)


@app.get("/api/health")
def health() -> dict[str, Any]:
    try:
        tags = _post_json(f"{OLLAMA_URL}/api/show", {"name": OLLAMA_MODEL})
        del tags
        available = True
    except ModelUnavailable:
        available = False
    return {"status": "ok", "model": OLLAMA_MODEL, "ollama_available": available}


@app.post("/api/integrations/ollama/start")
def start_local_ollama(request: Request) -> dict[str, str]:
    """Start only SearchBrief's fixed, bundled local Ollama launcher."""
    global _OLLAMA_PROCESS
    if request.client is None or request.client.host not in {"127.0.0.1", "::1"}:
        raise HTTPException(status_code=403, detail="Ollama can only be started from this device.")
    origin = request.headers.get("origin")
    if origin and origin not in {"http://localhost:3000", "http://127.0.0.1:3000", "http://localhost:3001", "http://127.0.0.1:3001"}:
        raise HTTPException(status_code=403, detail="Ollama can only be started from the SearchBrief page on this device.")
    if health()["ollama_available"]:
        return {"status": "ready", "model": OLLAMA_MODEL, "message": "The local model is already ready."}
    if not OLLAMA_START_SCRIPT.is_file() or not OLLAMA_BINARY.is_file() or not OLLAMA_MODEL_MANIFEST.is_file():
        raise HTTPException(
            status_code=503,
            detail="The bundled Ollama launcher or Qwen3 model is missing. Follow the Ollama setup guide in Settings.",
        )
    if _OLLAMA_PROCESS is not None and _OLLAMA_PROCESS.poll() is None:
        return {"status": "starting", "model": OLLAMA_MODEL, "message": "Ollama is already starting. This page will update when it is ready."}
    try:
        _OLLAMA_PROCESS = subprocess.Popen(
            [str(OLLAMA_START_SCRIPT)],
            cwd=str(PROJECT_ROOT),
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            start_new_session=True,
        )
    except OSError as exc:
        raise HTTPException(status_code=503, detail=f"Could not start local Ollama: {exc}") from exc
    return {"status": "starting", "model": OLLAMA_MODEL, "message": "Starting the local model. SearchBrief will check its status automatically."}


@app.post("/api/research")
def research_sources(request: ResearchRequest) -> dict[str, Any]:
    try:
        queries, planner = plan_queries(request.topic, request.question)
        local = search_saved_sources(request.topic, request.question, queries, [source.model_dump(mode="json") for source in request.saved_sources]) if request.search_mode == "saved_then_web" else []
        try:
            web, provider = find_sources(request.topic, request.question, queries=queries)
        except ResearchUnavailable:
            if not local:
                raise
            web, provider = [], ""
        candidates = _merge_sources(local, web, limit=500)
        ranked_candidates = _rank_sources(candidates, request.topic, request.question)
        sources = ranked_candidates[:30]
        screened_out_count = len(candidates) - len(ranked_candidates)
        capped_count = max(0, len(ranked_candidates) - len(sources))
        provider = " + ".join(part for part in ("Source Library" if local else "", provider) if part)
    except ResearchUnavailable as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    return {"sources": sources, "provider": provider, "planner": planner, "queries": queries, "screened_out_count": screened_out_count, "capped_count": capped_count, "notice": "Searched multiple query variations across available providers. Weak topic matches are excluded; topic fit and evidence type are shown separately and neither proves truth."}


def _merge_sources(local: list[dict[str, Any]], web: list[dict[str, Any]], *, limit: int = 500) -> list[dict[str, Any]]:
    result = []
    seen = set()
    for item in local[:3] + web + local[3:]:
        if item["id"] not in seen:
            result.append(item)
            seen.add(item["id"])
        if len(result) >= limit:
            break
    return result


def _line(event: dict[str, Any]) -> str:
    return json.dumps(event, ensure_ascii=False) + "\n"


def research_events(request: ResearchRequest):
    """Emit real research phases as newline-delimited JSON."""
    try:
        use_local = request.search_mode == "saved_then_web"
        total = 9 if use_local else 8
        yield _line({"type": "progress", "step": 1, "total": total, "message": "Planning source search with local Ollama when available"})
        queries, planner = plan_queries(request.topic, request.question)
        local = []
        if use_local:
            yield _line({"type": "progress", "step": 2, "total": total, "message": "Searching your saved Source Library on this device"})
            local = search_saved_sources(request.topic, request.question, queries, [source.model_dump(mode="json") for source in request.saved_sources])
        web_step = 3 if use_local else 2
        yield _line({"type": "progress", "step": web_step, "total": total, "message": f"Found {len(local)} saved matches; searching topic-matched publications" if use_local else "Searching topic-matched publications"})
        errors = []
        provider_status: dict[str, str] = {}
        try:
            papers = search_publications(request.topic, request.question, queries=queries)
            provider_status["Crossref"] = f"{len(papers)} results"
        except ResearchUnavailable as exc:
            papers = []
            errors.append(str(exc))
            provider_status["Crossref"] = "unavailable"
        yield _line({"type": "progress", "step": web_step + 1, "total": total, "message": f"Found {len(papers)} research records; searching public code repositories"})
        try:
            repositories = search_github_repositories(request.topic, request.question, queries=queries)
            provider_status["GitHub"] = f"{len(repositories)} results"
        except ResearchUnavailable as exc:
            repositories = []
            errors.append(str(exc))
            provider_status["GitHub"] = "unavailable"
        yield _line({"type": "progress", "step": web_step + 2, "total": total, "message": f"Found {len(repositories)} GitHub repositories; searching OpenAlex research"})
        try:
            openalex = search_openalex(request.topic, request.question, queries=queries)
            provider_status["OpenAlex"] = f"{len(openalex)} results"
        except ResearchUnavailable as exc:
            openalex = []
            errors.append(str(exc))
            provider_status["OpenAlex"] = "unavailable"
        yield _line({"type": "progress", "step": web_step + 3, "total": total, "message": f"Found {len(openalex)} OpenAlex works; searching technical Q&A"})
        try:
            community = search_stackexchange(request.topic, request.question, queries=queries)
            provider_status["Stack Exchange"] = f"{len(community)} results"
        except ResearchUnavailable as exc:
            community = []
            errors.append(str(exc))
            provider_status["Stack Exchange"] = "unavailable"
        yield _line({"type": "progress", "step": web_step + 4, "total": total, "message": f"Found {len(community)} Stack Exchange discussions; searching background references"})
        try:
            pages = search_pages(request.topic, request.question, queries=queries)
            provider_status["Wikipedia"] = f"{len(pages)} results"
        except ResearchUnavailable as exc:
            pages = []
            errors.append(str(exc))
            provider_status["Wikipedia"] = "unavailable"
        yield _line({"type": "progress", "step": web_step + 5, "total": total, "message": f"Found {len(pages)} background pages; ranking source candidates"})
        web = papers + repositories + openalex + community + pages
        candidates = _merge_sources(local, web, limit=500)
        ranked_candidates = _rank_sources(candidates, request.topic, request.question)
        sources = ranked_candidates[:30]
        screened_out_count = len(candidates) - len(ranked_candidates)
        capped_count = max(0, len(ranked_candidates) - len(sources))
        if not sources and errors:
            raise ResearchUnavailable("Public research providers are unavailable. Try again when online.")
        provider = " + ".join(name for name, results in (("Source Library", local), ("Crossref", papers), ("GitHub", repositories), ("OpenAlex", openalex), ("Stack Exchange", community), ("Wikipedia", pages)) if results)
        yield _line({"type": "progress", "step": total, "total": total, "message": f"{len(sources)} sources ready for your review"})
        if local or use_local:
            provider_status["Source Library"] = f"{len(local)} matches"
        yield _line({"type": "result", "data": {"sources": sources, "provider": provider, "planner": planner, "queries": queries, "provider_status": provider_status, "screened_out_count": screened_out_count, "capped_count": capped_count}})
    except ResearchUnavailable as exc:
        yield _line({"type": "error", "message": str(exc)})
    except Exception:
        yield _line({"type": "error", "message": "Research stopped unexpectedly. Retry or refine the topic."})


@app.post("/api/research/stream")
def stream_research(request: ResearchRequest):
    return StreamingResponse(research_events(request), media_type="application/x-ndjson", headers={"Cache-Control": "no-store", "X-Accel-Buffering": "no"})


@app.post("/api/recheck")
def recheck_source(request: RecheckRequest) -> dict[str, Any]:
    try:
        if request.source_id.startswith("crossref-"):
            return recheck_publication(request.source_id, str(request.source_url or ""), request.summary)
        return recheck_page(request.source_id, request.summary)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except ResearchUnavailable as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc


@app.post("/api/generate")
def generate_brief(request: GenerateRequest) -> dict[str, Any]:
    try:
        return generate(request.model_dump(mode="json"))
    except ModelUnavailable as exc:
        raise HTTPException(status_code=503, detail="Ollama is not responding. Start the local model service and retry.") from exc
    except InvalidModelOutput as exc:
        raise HTTPException(status_code=502, detail=f"{exc} Your input is still available.") from exc


def generate_events(request: GenerateRequest | RevisionRequest):
    """Forward model phases from a worker while the request remains open."""
    queue: Queue[dict[str, Any]] = Queue()
    def work():
        try:
            result = generate(request.model_dump(mode="json"), progress=lambda step, total, message: queue.put({"type": "progress", "step": step, "total": total, "message": message}))
            queue.put({"type": "result", "data": result})
        except ModelUnavailable:
            queue.put({"type": "error", "message": "Ollama is not responding. Start the local model service and retry."})
        except InvalidModelOutput as exc:
            queue.put({"type": "error", "message": f"{exc} Your input is still available."})
        except Exception:
            queue.put({"type": "error", "message": "Draft generation stopped unexpectedly. Your input is still available; retry."})
    Thread(target=work, daemon=True).start()
    while True:
        event = queue.get()
        yield _line(event)
        if event["type"] in {"result", "error"}:
            break


@app.post("/api/generate/stream")
def stream_generate(request: GenerateRequest):
    return StreamingResponse(generate_events(request), media_type="application/x-ndjson", headers={"Cache-Control": "no-store", "X-Accel-Buffering": "no"})


@app.post("/api/revise/stream")
def stream_revise(request: RevisionRequest):
    return StreamingResponse(generate_events(request), media_type="application/x-ndjson", headers={"Cache-Control": "no-store", "X-Accel-Buffering": "no"})
