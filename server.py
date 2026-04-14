"""FastAPI backend for KIMAKAai Email Handler."""
import os
import json
import threading

from fastapi import FastAPI, UploadFile, File, HTTPException
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
from dotenv import set_key, load_dotenv

from email_fetcher import get_gmail_service, fetch_unread_emails_and_save
from email_processing import run_agentic_pipeline

AUTH_DIR = os.environ.get("AUTH_DIR", "/app/auth")
CLIENT_SECRET_PATH = os.path.join(AUTH_DIR, "client_secret.json")
TOKEN_PATH = os.path.join(AUTH_DIR, "token.pickle")
PROCESSED_EMAILS_FILE = "processed_emails.jsonl"
ENV_FILE = ".env"

load_dotenv(ENV_FILE)
os.makedirs(AUTH_DIR, exist_ok=True)

app = FastAPI(title="KIMAKAai Email Handler")

_jobs: dict = {
    "fetch": {"running": False, "last": None},
    "process": {"running": False, "last": None},
}


# ── Status ────────────────────────────────────────────────────────────────────

@app.get("/api/status")
def get_status():
    load_dotenv(ENV_FILE, override=True)
    return {
        "has_client_secret": os.path.exists(CLIENT_SECRET_PATH),
        "authenticated": os.path.exists(TOKEN_PATH),
        "has_api_key": bool(os.getenv("LLM_API_KEY", "").strip()),
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
    set_key(ENV_FILE, "LLM_API_KEY", key)
    os.environ["LLM_API_KEY"] = key
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
        fetch_unread_emails_and_save()
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
