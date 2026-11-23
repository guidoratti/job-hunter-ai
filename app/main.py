"""FastAPI backend for Job Hunter AI."""

from __future__ import annotations

import asyncio
import json
import os
import shutil
import subprocess
import traceback
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from app import database as db
from app.ai_engine import (
    DEFAULT_AGENT_MODEL,
    DEFAULT_GEMINI_MODEL,
    DEPRECATED_MODEL_MAP,
    ai_engine,
    evaluate_salary_fit,
    normalize_model_spec,
)
from app.appliers.external_applier import apply_external_job
from app.appliers.linkedin_applier import apply_linkedin_job
from app.browser_manager import browser_manager
from app.config import BROWSER_PROFILE_DIR, RESUMES_DIR, STATIC_DIR
from app.document_parser import extract_text_from_file
from app.scrapers.glassdoor_scraper import search_glassdoor_jobs
from app.scrapers.indeed_scraper import search_indeed_jobs
from app.scrapers.linkedin_scraper import search_linkedin_jobs
from app.scrapers.remote_boards_scraper import search_remote_boards
from app.scrapers.ziprecruiter_scraper import search_ziprecruiter_jobs

# Track background task state
runner_state: dict[str, Any] = {
    "searching": False,
    "applying": False,
    "current_job_id": None,
}


@asynccontextmanager
async def lifespan(app: FastAPI):
    await db.init_db()
    yield
    await browser_manager.close()


app = FastAPI(title="Job Hunter AI", lifespan=lifespan)
app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")


# --- Pydantic Models ---

class SettingsPayload(BaseModel):
    gemini_api_key: str = ""
    openai_api_key: str = ""
    anthropic_api_key: str = ""
    openrouter_api_key: str = ""
    ollama_url: str = ""
    gemini_model: str = DEFAULT_GEMINI_MODEL
    agent_matcher_model: str = DEFAULT_AGENT_MODEL
    agent_writer_model: str = DEFAULT_AGENT_MODEL
    agent_form_model: str = DEFAULT_AGENT_MODEL
    agent_fallback_model: str = ""


class TestProviderPayload(BaseModel):
    provider: str
    model_spec: str = ""


class CredentialPayload(BaseModel):
    site_name: str
    site_domain: str
    username: str
    password: str = ""
    auth_provider: str = "standard"
    notes: str = ""


class AutofillPayload(BaseModel):
    provider: str = ""


class SearchPayload(BaseModel):
    sources: list[str] = ["linkedin", "indeed", "glassdoor", "ziprecruiter", "remotive"]
    keywords: list[str] = ["Product Manager", "Engineering Manager", "Tech Manager", "IT Business Partner"]
    locations: list[str] = ["São Paulo, Brazil", "Cotia, São Paulo, Brazil", "Europe", "United States"]
    work_modes: list[str] = ["hybrid", "remote"]
    easy_apply_only: bool = False
    max_per_query: int = 10
    max_total_results: int = 50
    include_skills_in_search: bool = False
    match_preferences: dict[str, Any] | None = None


class ApplyPayload(BaseModel):
    job_ids: list[int] | None = None
    auto_submit: bool = False


class BrowserOpenPayload(BaseModel):
    url: str


class RoadblockDecisionPayload(BaseModel):
    decision: str = "resume"  # resume | skip | abort


class ManualJobPayload(BaseModel):
    title: str
    company: str
    location: str = "São Paulo, SP"
    url: str
    description: str = ""
    source: str = "external"


# --- Root UI ---

@app.get("/")
async def index():
    return FileResponse(STATIC_DIR / "index.html")


# --- Live Event Stream (SSE) ---

@app.get("/api/events")
async def event_stream():
    q = browser_manager.subscribe()

    async def gen():
        try:
            # Send initial state snapshot
            snapshot = {
                "type": "state",
                "data": {
                    "runner": runner_state,
                    "roadblock": browser_manager.current_roadblock,
                    "search_progress": browser_manager.search_progress,
                },
            }
            yield f"data: {json.dumps(snapshot, ensure_ascii=False)}\n\n"
            while True:
                try:
                    msg = await asyncio.wait_for(q.get(), timeout=20.0)
                    yield f"data: {json.dumps(msg, ensure_ascii=False)}\n\n"
                except asyncio.TimeoutError:
                    yield ": keepalive\n\n"
        finally:
            browser_manager.unsubscribe(q)

    return StreamingResponse(gen(), media_type="text/event-stream")


@app.get("/api/status")
async def get_status():
    return {
        "runner": runner_state,
        "roadblock": browser_manager.current_roadblock,
    }


@app.get("/api/logs")
async def get_logs(limit: int = 80):
    return await db.list_logs(limit=limit)


@app.get("/api/stats")
async def get_stats():
    return await db.get_dashboard_stats()


@app.post("/api/stats/clear")
async def clear_stats():
    removed = await db.clear_all_jobs()
    browser_manager.search_progress["indexed"] = 0
    browser_manager.search_progress["percent"] = 0
    browser_manager.search_progress["active"] = False
    await browser_manager.log(f"Cleared statistics ({removed} job record(s) removed). Profile, CVs, and credentials preserved.", level="warning")
    return {"cleared": removed}


# --- Settings ---

def _preview_key(k: str) -> str:
    if not k:
        return ""
    return f"{k[:6]}...{k[-4:]}" if len(k) > 12 else "***"


@app.get("/api/settings")
async def get_settings():
    g_key = await db.get_setting("gemini_api_key")
    o_key = await db.get_setting("openai_api_key")
    a_key = await db.get_setting("anthropic_api_key")
    r_key = await db.get_setting("openrouter_api_key")
    ollama_url = await db.get_setting("ollama_url") or ""

    ollama_ready = False
    if ollama_url:
        try:
            import httpx

            r = httpx.get(f"{ollama_url.rstrip('/')}/api/tags", timeout=0.8)
            ollama_ready = r.status_code == 200 and len(r.json().get("models", [])) > 0
        except Exception:
            ollama_ready = False

    legacy_model = await db.get_setting("gemini_model") or DEFAULT_GEMINI_MODEL
    if legacy_model in DEPRECATED_MODEL_MAP:
        legacy_model = DEPRECATED_MODEL_MAP[legacy_model]
        await db.set_setting("gemini_model", legacy_model, encrypted=False)

    default_spec = normalize_model_spec(legacy_model)
    matcher_m = normalize_model_spec(await db.get_setting("agent_matcher_model") or default_spec)
    writer_m = normalize_model_spec(await db.get_setting("agent_writer_model") or default_spec)
    form_m = normalize_model_spec(await db.get_setting("agent_form_model") or default_spec)
    fallback_raw = await db.get_setting("agent_fallback_model") or ""
    fallback_m = normalize_model_spec(fallback_raw) if fallback_raw else ""

    return {
        "has_gemini_api_key": bool(g_key),
        "gemini_api_key_preview": _preview_key(g_key),
        "has_openai_api_key": bool(o_key),
        "openai_api_key_preview": _preview_key(o_key),
        "has_anthropic_api_key": bool(a_key),
        "anthropic_api_key_preview": _preview_key(a_key),
        "has_openrouter_api_key": bool(r_key),
        "openrouter_api_key_preview": _preview_key(r_key),
        "ollama_url": ollama_url,
        "ollama_ready": ollama_ready,
        "gemini_model": legacy_model,
        "agent_matcher_model": matcher_m,
        "agent_writer_model": writer_m,
        "agent_form_model": form_m,
        "agent_fallback_model": fallback_m,
    }


@app.post("/api/settings")
async def save_settings(payload: SettingsPayload):
    for key_name, val in (
        ("gemini_api_key", payload.gemini_api_key),
        ("openai_api_key", payload.openai_api_key),
        ("anthropic_api_key", payload.anthropic_api_key),
        ("openrouter_api_key", payload.openrouter_api_key),
    ):
        if val.strip():
            await db.set_setting(key_name, val.strip(), encrypted=True)

    await db.set_setting("ollama_url", payload.ollama_url.strip(), encrypted=False)
    if payload.gemini_model.strip():
        await db.set_setting("gemini_model", payload.gemini_model.strip(), encrypted=False)
    if payload.agent_matcher_model.strip():
        await db.set_setting("agent_matcher_model", normalize_model_spec(payload.agent_matcher_model), encrypted=False)
    if payload.agent_writer_model.strip():
        await db.set_setting("agent_writer_model", normalize_model_spec(payload.agent_writer_model), encrypted=False)
    if payload.agent_form_model.strip():
        await db.set_setting("agent_form_model", normalize_model_spec(payload.agent_form_model), encrypted=False)
    await db.set_setting(
        "agent_fallback_model",
        normalize_model_spec(payload.agent_fallback_model) if payload.agent_fallback_model.strip() else "",
        encrypted=False,
    )
    await browser_manager.log("AI provider keys and multi-agent model routing updated.")
    return await get_settings()


@app.post("/api/settings/test")
async def test_ai_provider(payload: TestProviderPayload):
    try:
        return await ai_engine.test_provider(payload.provider, payload.model_spec)
    except Exception as exc:
        raise HTTPException(status_code=400, detail=f"{type(exc).__name__}: {exc}")


@app.post("/api/ollama/setup")
async def setup_local_ollama():
    """Start the local Ollama server, ensure recommended models are pulled, and configure local agent routing."""
    import httpx

    ollama_exe = shutil.which("ollama")
    if not ollama_exe:
        local_candidate = Path(os.environ.get("LOCALAPPDATA", "")) / "Programs" / "Ollama" / "ollama.exe"
        if local_candidate.exists():
            ollama_exe = str(local_candidate)
    if not ollama_exe:
        raise HTTPException(
            status_code=400,
            detail="Ollama is not installed yet. Click 'Install ↗' to download Ollama first, then click 'Setup Local Server'.",
        )

    base_url = "http://127.0.0.1:11434"

    # 1. Start Ollama server if not already listening
    running = False
    try:
        r = httpx.get(f"{base_url}/api/tags", timeout=2.5)
        running = r.status_code == 200
    except Exception:
        running = False

    if not running:
        creationflags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
        subprocess.Popen(
            [ollama_exe, "serve"],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            creationflags=creationflags,
        )
        for _ in range(15):
            await asyncio.sleep(0.5)
            try:
                r = httpx.get(f"{base_url}/api/tags", timeout=2.0)
                if r.status_code == 200:
                    running = True
                    break
            except Exception:
                continue

    if not running:
        raise HTTPException(status_code=500, detail="Could not start local Ollama server on http://127.0.0.1:11434.")

    # 2. Check installed models
    tags_resp = httpx.get(f"{base_url}/api/tags", timeout=5.0)
    installed = {m.get("name", "") for m in tags_resp.json().get("models", [])}
    recommended = ["qwen2.5:7b", "gemma3:12b"]
    missing = [m for m in recommended if m not in installed]

    # 3. Configure Job Hunter AI to use local Ollama
    await db.set_setting("ollama_url", base_url, encrypted=False)
    await db.set_setting("agent_matcher_model", "ollama:qwen2.5:7b", encrypted=False)
    await db.set_setting("agent_writer_model", "ollama:gemma3:12b", encrypted=False)
    await db.set_setting("agent_form_model", "ollama:qwen2.5:7b", encrypted=False)

    if missing:
        async def _pull_missing():
            for m in missing:
                await browser_manager.log(f"Ollama Setup: pulling '{m}' in background (this may take a few minutes)...", level="info")
                proc = await asyncio.create_subprocess_exec(
                    ollama_exe,
                    "pull",
                    m,
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.STDOUT,
                )
                await proc.wait()
                if proc.returncode == 0:
                    await browser_manager.log(f"Ollama Setup: '{m}' downloaded and ready!", level="success")
                else:
                    await browser_manager.log(f"Ollama Setup: failed to pull '{m}' (exit {proc.returncode}).", level="error")

        asyncio.create_task(_pull_missing())
        return {
            "status": "pulling",
            "url": base_url,
            "installed": sorted(installed),
            "pulling": missing,
            "message": f"Local Ollama server is running! Pulling missing model(s) in background: {', '.join(missing)}. Check Live Activity Log for completion.",
        }

    await browser_manager.log("Local Ollama server verified & configured (qwen2.5:7b + gemma3:12b ready).", level="success")
    return {
        "status": "ready",
        "url": base_url,
        "installed": sorted(installed),
        "pulling": [],
        "message": "Local Ollama server is running and ready with qwen2.5:7b & gemma3:12b! Agent routing has been configured automatically.",
    }


@app.post("/api/reset/nuclear")
async def nuclear_reset():
    """Scrub ALL personal data, files, CVs, credentials, API keys, logs, jobs, and browser sessions."""
    await browser_manager.close()
    await db.nuclear_reset_db()

    # Delete all uploaded resumes and work-history files
    if RESUMES_DIR.exists():
        for item in RESUMES_DIR.iterdir():
            try:
                if item.is_file():
                    item.unlink()
                elif item.is_dir():
                    shutil.rmtree(item, ignore_errors=True)
            except Exception:
                pass

    # Delete persistent browser cookies/sessions
    if BROWSER_PROFILE_DIR.exists():
        shutil.rmtree(BROWSER_PROFILE_DIR, ignore_errors=True)
    BROWSER_PROFILE_DIR.mkdir(parents=True, exist_ok=True)

    browser_manager._revoked_sso.clear()
    browser_manager.search_progress = {
        "active": False,
        "indexed": 0,
        "max_total": 50,
        "max_seconds": 300,
        "started_ts": 0.0,
        "deadline_ts": 0.0,
        "current_platform": "",
        "current_query": "",
        "percent": 0,
        "stop_reason": "",
    }
    return {"reset": True}


# --- Profile & Documents ---

@app.get("/api/profile")
async def get_profile():
    return await db.get_profile()


@app.put("/api/profile")
async def update_profile(payload: dict[str, Any]):
    existing = await db.get_profile()
    merged = dict(existing)
    merged.update(payload)

    # Protect localized[lang] against stale client race conditions wiping out a processed language
    ex_loc = existing.get("localized") or {}
    in_loc = payload.get("localized") or {}
    merged_loc = {}
    for code in ("pt", "en"):
        ex_b = ex_loc.get(code) or {}
        in_b = in_loc.get(code) or {}
        in_has_content = any(str(in_b.get(k) or "").strip() for k in ("summary", "work_history", "t_letter_examples"))
        ex_has_content = any(str(ex_b.get(k) or "").strip() for k in ("summary", "work_history", "t_letter_examples"))
        # If incoming bucket is completely empty while DB already has content and user didn't explicitly clear active lang, preserve DB content
        if not in_has_content and ex_has_content and payload.get("edited_language") != code:
            merged_loc[code] = ex_b
        else:
            merged_loc[code] = {
                "summary": in_b.get("summary", ex_b.get("summary", "")),
                "work_history": in_b.get("work_history", ex_b.get("work_history", "")),
                "t_letter_examples": in_b.get("t_letter_examples", ex_b.get("t_letter_examples", "")),
            }
    merged["localized"] = merged_loc
    silent = bool(merged.pop("silent", False))
    merged.pop("edited_language", None)

    saved = await db.save_profile(merged)
    # Re-evaluate salary_fit across all existing jobs when salary range changes
    all_jobs = await db.list_jobs()
    for j in all_jobs:
        new_fit = evaluate_salary_fit(
            j.get("estimated_salary_min", 0),
            j.get("estimated_salary_avg", 0),
            j.get("estimated_salary_max", 0),
            j.get("estimated_salary_currency", "BRL"),
            j.get("estimated_salary_period", "monthly"),
            saved,
        )
        if new_fit != j.get("salary_fit"):
            await db.update_job(j["id"], salary_fit=new_fit)
    if not silent:
        await browser_manager.log("Candidate profile updated (salary range fit recalculated across jobs).")
    return saved


class ProcessProfilePayload(BaseModel):
    language: str = "pt"


@app.post("/api/profile/process")
async def process_profile_from_docs(payload: ProcessProfilePayload):
    lang = "en" if payload.language.lower() == "en" else "pt"
    try:
        extracted = await ai_engine.extract_profile_from_documents(language=lang)
    except Exception as exc:
        raise HTTPException(status_code=400, detail=f"{type(exc).__name__}: {exc}")

    profile = await db.get_profile()
    profile["preferred_language"] = lang
    loc = profile.get("localized") or {}
    loc[lang] = {
        "summary": extracted["summary"],
        "work_history": extracted["work_history"],
        "t_letter_examples": extracted["t_letter_examples"],
    }
    profile["localized"] = loc
    profile["summary"] = extracted["summary"]
    profile["work_history"] = extracted["work_history"]
    profile["t_letter_examples"] = extracted["t_letter_examples"]
    saved = await db.save_profile(profile)
    await browser_manager.log(f"Processed uploaded documents in {lang.upper()} and saved to {lang.upper()} profile.", level="success")
    return saved


@app.get("/api/documents")
async def list_documents():
    return await db.list_documents(include_text=False)


@app.post("/api/documents/upload")
async def upload_document(
    file: UploadFile = File(...),
    doc_type: str = Form("resume"),
    language: str = Form("pt"),
):
    if not file.filename:
        raise HTTPException(status_code=400, detail="Missing filename")
    safe_name = Path(file.filename).name
    dest = RESUMES_DIR / f"{language}_{doc_type}_{safe_name}"
    content = await file.read()
    dest.write_bytes(content)

    try:
        extracted = extract_text_from_file(dest)
    except Exception as exc:
        dest.unlink(missing_ok=True)
        raise HTTPException(status_code=400, detail=str(exc))

    doc = await db.add_document(
        filename=safe_name,
        stored_path=str(dest),
        doc_type=doc_type,
        language=language,
        extracted_text=extracted,
    )
    await browser_manager.log(f"Uploaded {doc_type} ({language.upper()}): {safe_name} ({len(extracted)} chars extracted).")
    return doc


class DocumentPriorityPayload(BaseModel):
    priority: str = "primary"


@app.patch("/api/documents/{doc_id}/priority")
async def set_document_priority(doc_id: int, payload: DocumentPriorityPayload):
    await db.update_document_priority(doc_id, payload.priority)
    return {"id": doc_id, "priority": payload.priority}


@app.delete("/api/documents/{doc_id}")
async def delete_document(doc_id: int):
    path = await db.delete_document(doc_id)
    if path:
        Path(path).unlink(missing_ok=True)
    return {"deleted": True}


# --- Encrypted Credential Vault ---

@app.get("/api/credentials")
async def list_credentials():
    return await db.list_credentials()


@app.post("/api/credentials")
async def save_credential(payload: CredentialPayload):
    res = await db.upsert_credential(
        site_name=payload.site_name,
        site_domain=payload.site_domain,
        username=payload.username,
        password=payload.password,
        auth_provider=payload.auth_provider,
        notes=payload.notes,
    )
    await browser_manager.log(
        f"Saved encrypted credentials for {payload.site_name} ({payload.site_domain}, provider={payload.auth_provider})."
    )
    return res


@app.delete("/api/credentials/{cred_id}")
async def delete_credential(cred_id: int):
    await db.delete_credential(cred_id)
    return {"deleted": True}


# --- Interactive Browser & Roadblocks ---

@app.post("/api/browser/open")
async def open_browser(payload: BrowserOpenPayload):
    url = payload.url.strip()
    if not url.startswith(("http://", "https://")):
        url = "https://" + url
    try:
        return await browser_manager.open_interactive_url(url)
    except Exception as exc:
        traceback.print_exc()
        await browser_manager.log(f"Browser open failed: {type(exc).__name__}: {exc}", level="error")
        raise HTTPException(status_code=500, detail=f"{type(exc).__name__}: {exc}")


@app.post("/api/browser/show")
async def show_browser():
    try:
        return await browser_manager.show_browser()
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"{type(exc).__name__}: {exc}")


@app.post("/api/browser/hide")
async def hide_browser():
    try:
        return await browser_manager.hide_browser()
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"{type(exc).__name__}: {exc}")


@app.post("/api/browser/sso/connect")
async def connect_sso(payload: AutofillPayload):
    try:
        return await browser_manager.connect_sso_provider(payload.provider)
    except Exception as exc:
        traceback.print_exc()
        raise HTTPException(status_code=400, detail=f"{type(exc).__name__}: {exc}")


@app.get("/api/browser/sso/status")
async def sso_status():
    return await browser_manager.get_sso_session_status()


@app.post("/api/browser/autofill")
async def autofill_browser(payload: AutofillPayload | None = None):
    provider = payload.provider if payload else ""
    try:
        return await browser_manager.autofill_saved_credentials(provider=provider or None)
    except Exception as exc:
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=f"{type(exc).__name__}: {exc}")


@app.post("/api/browser/roadblock")
async def resolve_roadblock(payload: RoadblockDecisionPayload):
    ok = browser_manager.resolve_roadblock(payload.decision)
    return {"resolved": ok, "decision": payload.decision}


@app.post("/api/browser/fill-now")
async def fill_current_browser_form():
    """Immediately upload matching CV and fill all visible form fields on the active browser tab."""
    from app.appliers.form_filler import fill_visible_form_fields, upload_matching_resume

    try:
        page = await browser_manager.get_active_page(bring_to_front=True)
        rb = browser_manager.current_roadblock or {}
        job_id = rb.get("job_id") or runner_state.get("current_job_id")
        job = await db.get_job(job_id) if job_id else None
        if not job:
            profile = await db.get_profile()
            job = {
                "id": None,
                "title": await page.title(),
                "company": "",
                "location": f"{profile.get('city', '')}, {profile.get('country', '')}",
                "language": profile.get("preferred_language") or "pt",
                "is_international": False,
            }
        cv_ok = await upload_matching_resume(page, job)
        filled_count, missing = await fill_visible_form_fields(page, job)
        msg = f"Filled {filled_count} field(s){' + uploaded CV' if cv_ok else ''}."
        if missing:
            msg += f" Remaining for you: {', '.join(missing[:5])}."
        await browser_manager.log(f"📝 Fill Form Now: {msg}", level="success", job_id=job.get("id"))
        return {"filled": filled_count, "cv_uploaded": cv_ok, "missing": missing, "message": msg}
    except Exception as exc:
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=f"{type(exc).__name__}: {exc}")


# --- Job Search & Management ---

@app.post("/api/search")
async def start_search(payload: SearchPayload):
    if runner_state["searching"]:
        raise HTTPException(status_code=409, detail="A job search is already running.")

    # Persist human/skills/culture preferences to profile before searching
    if payload.match_preferences:
        prof = await db.get_profile()
        prof["match_preferences"] = payload.match_preferences
        await db.save_profile(prof)

    async def _run():
        runner_state["searching"] = True
        cap = max(1, min(50, int(payload.max_total_results or 50)))
        per_q = max(1, min(cap, int(payload.max_per_query or 10)))
        await browser_manager.start_search_progress(max_total=cap, max_seconds=300)
        await browser_manager.emit("runner_state", runner_state)
        try:
            keywords = [k.strip() for k in payload.keywords if k.strip()]
            if payload.include_skills_in_search and payload.match_preferences:
                extra_skills = [
                    s.strip()
                    for s in str(payload.match_preferences.get("skills", "")).split(",")
                    if s.strip()
                ][:4]
                for sk in extra_skills:
                    if sk.lower() not in {k.lower() for k in keywords}:
                        keywords.append(sk)
            locations = [l.strip() for l in payload.locations if l.strip()]
            # LinkedIn is always searched first, followed by secondary platforms (capped at 100 results total)
            if "linkedin" in payload.sources and not browser_manager.search_limit_reached():
                await search_linkedin_jobs(
                    keywords=keywords,
                    locations=locations,
                    work_modes=payload.work_modes,
                    easy_apply_only=payload.easy_apply_only,
                    max_per_query=per_q,
                )
            if "indeed" in payload.sources and not browser_manager.search_limit_reached():
                await search_indeed_jobs(
                    keywords=keywords,
                    locations=locations,
                    max_per_query=per_q,
                )
            if "glassdoor" in payload.sources and not browser_manager.search_limit_reached():
                await search_glassdoor_jobs(
                    keywords=keywords,
                    locations=locations,
                    max_per_query=per_q,
                )
            if "ziprecruiter" in payload.sources and not browser_manager.search_limit_reached():
                await search_ziprecruiter_jobs(
                    keywords=keywords,
                    max_per_query=per_q,
                )
            if "remotive" in payload.sources and not browser_manager.search_limit_reached():
                await search_remote_boards(keywords=keywords, max_per_query=per_q)
        except Exception as exc:
            traceback.print_exc()
            await browser_manager.log(f"Search failed: {type(exc).__name__}: {exc}", level="error")
        finally:
            runner_state["searching"] = False
            await browser_manager.finish_search_progress()
            await browser_manager.emit("runner_state", runner_state)

    asyncio.create_task(_run())
    return {"started": True}


@app.post("/api/search/stop")
async def stop_search():
    if not runner_state["searching"]:
        return {"stopping": False, "message": "No search is currently running."}
    await browser_manager.request_search_stop()
    return {"stopping": True}


@app.post("/api/jobs/reanalyze")
async def reanalyze_new_jobs(match_preferences: dict[str, Any] | None = None):
    """Re-score all 'new' jobs with Gemini using updated human/culture/skills preferences."""
    if match_preferences:
        prof = await db.get_profile()
        prof["match_preferences"] = match_preferences
        await db.save_profile(prof)

    jobs = await db.list_jobs(status="new")
    if not jobs:
        return {"reanalyzed": 0}

    async def _run_reanalyze():
        await browser_manager.log(f"Re-scoring {len(jobs)} pending job(s) with updated Human Fit & Skills preferences...")
        for j in jobs:
            try:
                analysis = await ai_engine.analyze_job(j)
                await db.update_job(j["id"], **analysis)
            except Exception as exc:
                await browser_manager.log(f"Re-score failed for {j['title']}: {exc}", level="warning", job_id=j["id"])
        await browser_manager.log("Re-scoring complete!", level="success")
        await browser_manager.emit("job_added", {"reanalyzed": len(jobs)})

    asyncio.create_task(_run_reanalyze())
    return {"started": True, "count": len(jobs)}


@app.get("/api/jobs")
async def list_jobs(status: str = "all", min_score: int = 0, salary_fit: str = "all"):
    return await db.list_jobs(status=status, min_score=min_score, salary_fit=salary_fit)


@app.post("/api/jobs/manual")
async def add_manual_job(payload: ManualJobPayload):
    raw_job = {
        "source": payload.source,
        "external_id": payload.url.strip(),
        "title": payload.title.strip(),
        "company": payload.company.strip(),
        "location": payload.location.strip(),
        "apply_type": "easy_apply" if "linkedin.com" in payload.url.lower() else "external",
        "url": payload.url.strip(),
        "external_apply_url": payload.url.strip(),
        "description": payload.description.strip(),
    }
    analysis = await ai_engine.analyze_job(raw_job)
    raw_job.update(analysis)
    job_id = await db.upsert_job(raw_job)
    return await db.get_job(job_id)


@app.patch("/api/jobs/{job_id}/select")
async def toggle_select_job(job_id: int, selected: bool = True):
    await db.update_job(job_id, selected=1 if selected else 0)
    return {"id": job_id, "selected": selected}


@app.post("/api/jobs/{job_id}/materials")
async def generate_materials(job_id: int):
    job = await db.get_job(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    try:
        mats = await ai_engine.generate_application_materials(job)
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    await db.update_job(
        job_id,
        generated_t_letter=mats["t_letter"],
        generated_cover_letter=mats["cover_letter"],
    )
    return mats


@app.delete("/api/jobs/{job_id}")
async def delete_job(job_id: int):
    await db.delete_job(job_id)
    return {"deleted": True}


# --- Automated Application Runner ---

@app.post("/api/apply")
async def start_apply(payload: ApplyPayload):
    if runner_state["applying"]:
        raise HTTPException(status_code=409, detail="Application runner is already active.")

    if payload.job_ids:
        jobs = [await db.get_job(jid) for jid in payload.job_ids]
        jobs = [j for j in jobs if j is not None]
    else:
        all_jobs = await db.list_jobs()
        jobs = [j for j in all_jobs if j["selected"] == 1 and j["status"] in ("new", "needs_action", "failed")]

    if not jobs:
        raise HTTPException(status_code=400, detail="No selected jobs to apply for.")

    async def _run_apply():
        runner_state["applying"] = True
        await browser_manager.emit("runner_state", runner_state)
        try:
            await browser_manager.log(f"Starting automated application run for {len(jobs)} selected job(s)...")
            for job in jobs:
                runner_state["current_job_id"] = job["id"]
                await browser_manager.emit("runner_state", runner_state)
                await db.update_job(job["id"], status="applying")
                try:
                    if job["source"] == "linkedin" or "linkedin.com" in job["url"].lower():
                        result = await apply_linkedin_job(job, auto_submit=payload.auto_submit)
                    else:
                        result = await apply_external_job(job, auto_submit=payload.auto_submit)

                    if result == "abort":
                        await db.update_job(job["id"], status="new", status_note="Run aborted by user.")
                        await browser_manager.log("Application batch aborted by user.", level="warning")
                        break
                except Exception as exc:
                    await db.update_job(job["id"], status="failed", status_note=str(exc)[:300])
                    await browser_manager.log(f"Error applying to {job['title']}: {exc}", level="error", job_id=job["id"])
        finally:
            runner_state["applying"] = False
            runner_state["current_job_id"] = None
            await browser_manager.emit("runner_state", runner_state)
            await browser_manager.log("Application batch finished.")

    asyncio.create_task(_run_apply())
    return {"started": True, "count": len(jobs)}
