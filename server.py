"""FastAPI backend for KIMAKAai Email Handler."""
import os
import json
import threading

from fastapi import FastAPI, UploadFile, File, HTTPException
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from email_fetcher import get_gmail_service, fetch_unread_emails_and_save
from email_processing import run_agentic_pipeline, resolve_llm_config, list_provider_models

AUTH_DIR = os.environ.get("AUTH_DIR", "/app/auth")
CLIENT_SECRET_PATH = os.path.join(AUTH_DIR, "client_secret.json")
TOKEN_PATH = os.path.join(AUTH_DIR, "token.pickle")
SETTINGS_FILE = os.path.join(AUTH_DIR, "settings.json")
PROCESSED_EMAILS_FILE = "processed_emails.jsonl"
os.makedirs(AUTH_DIR, exist_ok=True)

app = FastAPI(title="KIMAKAai Email Handler")

_jobs: dict = {
    "fetch": {"running": False, "last": None},
    "process": {"running": False, "last": None},
}


def _read_settings_file() -> dict:
    try:
        with open(SETTINGS_FILE) as f:
            return json.load(f)
    except (OSError, json.JSONDecodeError):
        return {}


def _write_settings_file(data: dict) -> None:
    os.makedirs(AUTH_DIR, exist_ok=True)
    with open(SETTINGS_FILE, "w") as f:
        json.dump(data, f, indent=2)


# ── Status ────────────────────────────────────────────────────────────────────

@app.get("/api/status")
def get_status():
    llm = resolve_llm_config()
    provider = llm.get("provider", "ollama")
    has_ai_config = bool(llm.get("model"))
    if provider in ("gemini", "openai"):
        has_ai_config = has_ai_config and bool(llm.get("api_key"))
    return {
        "has_client_secret": os.path.exists(CLIENT_SECRET_PATH),
        "authenticated": os.path.exists(TOKEN_PATH),
        "has_api_key": bool((llm.get("api_key") or "").strip()),
        "llm_provider": provider,
        "llm_model": llm.get("model", ""),
        "llm_base_url": llm.get("base_url", ""),
        "llm_configured": has_ai_config,
    }


# ── Settings ──────────────────────────────────────────────────────────────────

@app.post("/api/settings/client-secret")
async def upload_client_secret(file: UploadFile = File(...)):
    content = await file.read()
    try:
        json.loads(content)
    except json.JSONDecodeError:
        raise HTTPException(status_code=400, detail="Invalid JSON file")
    os.makedirs(AUTH_DIR, exist_ok=True)
    with open(CLIENT_SECRET_PATH, "wb") as f:
        f.write(content)
    return {"ok": True}


class ApiKeyBody(BaseModel):
    api_key: str


@app.post("/api/settings/api-key")
def save_api_key(body: ApiKeyBody):
    key = body.api_key.strip()
    if not key:
        raise HTTPException(status_code=400, detail="API key cannot be empty")
    current = _read_settings_file()
    current["api_key"] = key
    if not (current.get("provider") or os.getenv("LLM_PROVIDER", "").strip()):
        current["provider"] = "gemini"
    _write_settings_file(current)

    # Update in-process environment for immediate effect
    os.environ["LLM_API_KEY"] = key
    if current.get("provider"):
        os.environ["LLM_PROVIDER"] = current["provider"]
    return {"ok": True}


class LlmSettingsBody(BaseModel):
    provider: str
    model: str = ""
    api_key: str = ""
    base_url: str = ""


@app.get("/api/llm/providers")
def get_llm_providers():
    cfg = resolve_llm_config()

    providers = [
        {
            "id": "ollama",
            "label": "Local Ollama",
            "api_key_required": False,
            "base_url": cfg.get("base_url") if cfg.get("provider") == "ollama" else os.getenv("OLLAMA_BASE_URL", "http://host.docker.internal:11434"),
        },
        {
            "id": "gemini",
            "label": "Google Gemini",
            "api_key_required": True,
            "base_url": "",
        },
        {
            "id": "openai",
            "label": "OpenAI",
            "api_key_required": True,
            "base_url": cfg.get("base_url") if cfg.get("provider") == "openai" else "https://api.openai.com/v1",
        },
        {
            "id": "anthropic",
            "label": "Anthropic (Claude)",
            "api_key_required": True,
            "base_url": cfg.get("base_url") if cfg.get("provider") == "anthropic" else "https://api.anthropic.com/v1",
        },
        {
            "id": "groq",
            "label": "Groq",
            "api_key_required": True,
            "base_url": cfg.get("base_url") if cfg.get("provider") == "groq" else "https://api.groq.com/openai/v1",
        },
        {
            "id": "mistral",
            "label": "Mistral",
            "api_key_required": True,
            "base_url": cfg.get("base_url") if cfg.get("provider") == "mistral" else "https://api.mistral.ai/v1",
        },
        {
            "id": "openrouter",
            "label": "OpenRouter",
            "api_key_required": True,
            "base_url": cfg.get("base_url") if cfg.get("provider") == "openrouter" else "https://openrouter.ai/api/v1",
        },
        {
            "id": "cohere",
            "label": "Cohere",
            "api_key_required": True,
            "base_url": cfg.get("base_url") if cfg.get("provider") == "cohere" else "https://api.cohere.com/compatibility/v1",
        },
        {
            "id": "custom",
            "label": "Custom / OpenAI-Compatible",
            "api_key_required": False,
            "base_url": cfg.get("base_url") if cfg.get("provider") == "custom" else "",
        },
    ]

    current_provider = cfg.get("provider", "ollama")

    # Only fetch models for the currently-saved provider (uses saved credentials).
    # All other providers start empty; the Refresh button fetches on demand.
    model_map = {p["id"]: [] for p in providers}
    model_map[current_provider] = list_provider_models(
        current_provider,
        api_key=cfg.get("api_key", ""),
        base_url=cfg.get("base_url", ""),
    )

    return {
        "providers": providers,
        "current": cfg,
        "models": model_map,
    }


_ALL_PROVIDERS = {"ollama", "gemini", "openai", "anthropic", "groq", "mistral", "openrouter", "cohere", "custom"}
_COMPAT_PROVIDERS = {"openai", "anthropic", "groq", "mistral", "openrouter", "cohere", "custom"}


class LlmModelsBody(BaseModel):
    provider: str
    api_key: str = ""
    base_url: str = ""


@app.post("/api/llm/models")
def get_provider_models_on_demand(body: LlmModelsBody):
    """Fetch models for a provider using the key/url supplied in the request body.
    Used by the Refresh button so it sends the currently-typed key, not saved config.
    """
    models = list_provider_models(
        body.provider,
        api_key=(body.api_key or "").strip(),
        base_url=(body.base_url or "").strip(),
    )
    return {"models": models}


@app.post("/api/settings/llm")
def save_llm_settings(body: LlmSettingsBody):
    provider = (body.provider or "").strip().lower()
    if provider not in _ALL_PROVIDERS:
        raise HTTPException(status_code=400, detail="Unsupported provider")

    model = (body.model or "").strip()
    api_key = (body.api_key or "").strip()
    base_url = (body.base_url or "").strip()

    if provider == "gemini" and not api_key:
        raise HTTPException(status_code=400, detail="Gemini provider requires API key")
    if provider in _COMPAT_PROVIDERS and not api_key and provider != "custom":
        raise HTTPException(status_code=400, detail=f"{provider.capitalize()} provider requires API key")

    # Persist to auth volume JSON (writable named Docker volume)
    current = _read_settings_file()
    current["provider"] = provider
    if model:
        current["model"] = model
    if api_key:
        current["api_key"] = api_key
    if base_url:
        current["base_url"] = base_url
    elif "base_url" in current and provider != "ollama" and provider != "custom":
        # Clear stale base_url when switching to a provider that doesn't use it
        current.pop("base_url", None)
    _write_settings_file(current)

    # Also update os.environ so in-process calls see the new value immediately
    os.environ["LLM_PROVIDER"] = provider
    if model:
        os.environ["LLM_MODEL"] = model
    if api_key:
        os.environ["LLM_API_KEY"] = api_key

    return {"ok": True}


# ── Auth ──────────────────────────────────────────────────────────────────────

@app.get("/api/auth/url")
def get_auth_url():
    if not os.path.exists(CLIENT_SECRET_PATH):
        raise HTTPException(status_code=400, detail="No client secret uploaded yet")
    _, auth_url, _ = get_gmail_service(CLIENT_SECRET_PATH, TOKEN_PATH)
    if not auth_url:
        return {"auth_url": None, "authenticated": True}
    return {"auth_url": auth_url, "authenticated": False}


class CallbackBody(BaseModel):
    redirect_url: str


@app.post("/api/auth/callback")
def auth_callback(body: CallbackBody):
    service, auth_url, _ = get_gmail_service(
        CLIENT_SECRET_PATH, TOKEN_PATH, auth_code=body.redirect_url
    )
    if service:
        return {"ok": True}
    if auth_url:
        raise HTTPException(
            status_code=400,
            detail="Code verifier expired — please start auth again",
        )
    raise HTTPException(
        status_code=400,
        detail="Authentication failed — invalid or expired code",
    )


@app.delete("/api/auth/reset")
def auth_reset():
    for p in [TOKEN_PATH, CLIENT_SECRET_PATH, os.path.join(AUTH_DIR, "pkce_pending.json")]:
        try:
            os.remove(p)
        except OSError:
            pass
    return {"ok": True}


# ── Emails ────────────────────────────────────────────────────────────────────

@app.get("/api/emails")
def get_emails():
    emails = []
    if os.path.exists(PROCESSED_EMAILS_FILE):
        with open(PROCESSED_EMAILS_FILE, "r") as f:
            for line in f:
                line = line.strip()
                if line:
                    try:
                        emails.append(json.loads(line))
                    except json.JSONDecodeError:
                        pass
    return emails


@app.delete("/api/emails/clear")
def clear_emails():
    try:
        os.remove(PROCESSED_EMAILS_FILE)
    except OSError:
        pass
    return {"ok": True}


_DEMO_EMAILS = [
    {
        "gmail_id": "_demo_1",
        "sender": "sarah.chen@acme-corp.com",
        "subject": "Q2 Budget Review — Action Required by Friday",
        "date": "Mon, 14 Apr 2026 09:15:00 +0000",
        "executive_summary": {
            "one_liner": "Q2 budget needs your sign-off by Friday or projects stall",
            "key_points": [
                "Marketing overspent by $42k in Q1; revised Q2 budget needs your approval",
                "Board meeting April 18 requires final budget slides from you",
                "Project Phoenix and Orion on hold pending funding confirmation",
            ],
            "sentiment": "Urgent",
            "priority": "High",
        },
        "action_items": {
            "tasks": [
                {"task": "Approve revised Q2 budget document", "due_date": "2026-04-17"},
                {"task": "Prepare updated budget slides for board meeting", "due_date": "2026-04-17"},
                {"task": "Confirm funding allocation for Project Phoenix and Orion", "due_date": "2026-04-18"},
            ],
            "owner": "user",
        },
        "draft_options": {
            "professional": (
                "Dear Sarah,\n\nThank you for the detailed Q2 budget overview. "
                "I have reviewed the revised figures and will complete the approval by end of day Thursday, April 17th.\n\n"
                "I will also prepare the updated board slides before the April 18th meeting — "
                "could you confirm the exact submission deadline?\n\n"
                "Funding confirmation for Project Phoenix and Orion will follow separately by Thursday.\n\nBest regards"
            ),
            "brief": "Noted — approving budget and sending board slides by Thursday EOD. Will confirm Project Phoenix/Orion funding separately.",
            "scheduler": "Hi Sarah, would a 30-min call Thursday April 17th at 2 PM work to align on budget figures before I submit the slides?",
        },
        "category": "Finance & Budgeting",
        "is_passive_participation": False,
    },
    {
        "gmail_id": "_demo_2",
        "sender": "all-staff@acme-corp.com",
        "subject": "Reminder: Office Closure on April 25th — Easter Weekend",
        "date": "Mon, 14 Apr 2026 08:00:00 +0000",
        "executive_summary": {
            "one_liner": "Office closed April 25 for Easter; no action required from you",
            "key_points": [
                "Office will be closed Friday April 25th for Easter",
                "Plan project deadlines and deliverables accordingly",
                "Emergency contact details available on the company intranet",
            ],
            "sentiment": "FYI",
            "priority": "Low",
        },
        "action_items": {
            "tasks": [],
            "owner": "user",
        },
        "draft_options": {
            "professional": "Thank you for the reminder — noted in the calendar.",
            "brief": "Got it, thanks.",
            "scheduler": None,
        },
        "category": "Company Announcements",
        "is_passive_participation": True,
    },
]


@app.post("/api/emails/demo")
def load_demo():
    """Wipe processed JSONL and write pre-built demo emails so UI can be previewed."""
    try:
        os.remove(PROCESSED_EMAILS_FILE)
    except OSError:
        pass
    with open(PROCESSED_EMAILS_FILE, "w") as f:
        for record in _DEMO_EMAILS:
            f.write(json.dumps(record) + "\n")
    return {"ok": True, "count": len(_DEMO_EMAILS)}


# ── Jobs ──────────────────────────────────────────────────────────────────────

@app.get("/api/jobs")
def get_jobs():
    return _jobs


def _run_fetch():
    _jobs["fetch"]["running"] = True
    try:
        try:
            days = int(os.environ.get("FETCH_UNREAD_DAYS", "2"))
        except Exception:
            days = 2
        try:
            max_results = int(os.environ.get("FETCH_MAX_RESULTS", "50"))
        except Exception:
            max_results = 50
        fetch_unread_emails_and_save(days=days, max_results=max_results)
        _jobs["fetch"]["last"] = "success"
    except Exception as e:
        _jobs["fetch"]["last"] = f"error: {e}"
    finally:
        _jobs["fetch"]["running"] = False


def _run_process():
    _jobs["process"]["running"] = True
    try:
        run_agentic_pipeline()
        _jobs["process"]["last"] = "success"
    except Exception as e:
        _jobs["process"]["last"] = f"error: {e}"
    finally:
        _jobs["process"]["running"] = False


@app.post("/api/emails/fetch")
def trigger_fetch():
    if _jobs["fetch"]["running"]:
        raise HTTPException(status_code=409, detail="Fetch already in progress")
    threading.Thread(target=_run_fetch, daemon=True).start()
    return {"ok": True, "message": "Fetch started"}


@app.post("/api/emails/process")
def trigger_process():
    if _jobs["process"]["running"]:
        raise HTTPException(status_code=409, detail="Process already in progress")
    threading.Thread(target=_run_process, daemon=True).start()
    return {"ok": True, "message": "Processing started"}


# ── Static files — must be last ───────────────────────────────────────────────

app.mount("/", StaticFiles(directory="/app/static", html=True), name="static")
