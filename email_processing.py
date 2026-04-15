import os
import json
import email
import urllib.request
import urllib.error
from email.policy import default
from datetime import date
from langchain_google_genai import ChatGoogleGenerativeAI
from langchain_core.prompts import ChatPromptTemplate
import prompts
from dotenv import load_dotenv

load_dotenv()

# --- Monkey Patch for LangChain/Google GenAI Compatibility ---
import google.generativeai as genai
if not hasattr(genai.GenerationConfig, "MediaResolution"):
    class MediaResolution:
        UNSPECIFIED = "MEDIA_RESOLUTION_UNSPECIFIED"
        LOW = "MEDIA_RESOLUTION_LOW"
        MEDIUM = "MEDIA_RESOLUTION_MEDIUM"
        HIGH = "MEDIA_RESOLUTION_HIGH"
    genai.GenerationConfig.MediaResolution = MediaResolution

DEFAULT_GEMINI_MODEL = "gemini-2.5-flash-lite"
DEFAULT_OLLAMA_MODEL = "phi4-mini"
DEFAULT_OPENAI_MODEL = "gpt-4o-mini"
DEFAULT_OLLAMA_BASE_URL = os.getenv("OLLAMA_BASE_URL", "http://host.docker.internal:11434")
DEFAULT_OPENAI_BASE_URL = os.getenv("OPENAI_BASE_URL", "https://api.openai.com/v1")
RAW_EMAILS_DIR = "raw_emails"
PROCESSED_EMAILS_FILE = "processed_emails.jsonl"


def _read_json_response(url, headers=None, method="GET", payload=None):
    req = urllib.request.Request(url, method=method)
    if headers:
        for k, v in headers.items():
            req.add_header(k, v)
    if payload is not None:
        data = json.dumps(payload).encode("utf-8")
        req.add_header("Content-Type", "application/json")
    else:
        data = None

    with urllib.request.urlopen(req, data=data, timeout=20) as resp:
        body = resp.read().decode("utf-8")
    return json.loads(body)


def _normalize_json_response(response_str):
    clean = response_str.strip()
    if clean.startswith("```json"):
        clean = clean[7:]
    if clean.startswith("```"):
        clean = clean[3:]
    if clean.endswith("```"):
        clean = clean[:-3]
    return json.loads(clean.strip())


def _ollama_base_candidates(base_url=""):
    seed = (base_url or "").strip()
    candidates = [
        seed,
        os.getenv("OLLAMA_BASE_URL", "").strip(),
        DEFAULT_OLLAMA_BASE_URL,
        "http://172.17.0.1:11434",
        "http://localhost:11434",
    ]
    seen = set()
    ordered = []
    for raw in candidates:
        if not raw:
            continue
        normalized = raw.rstrip("/")
        if normalized in seen:
            continue
        seen.add(normalized)
        ordered.append(normalized)
    return ordered


def _ollama_request_json(base_url, path, method="GET", payload=None):
    last_err = None
    for candidate in _ollama_base_candidates(base_url):
        try:
            return _read_json_response(f"{candidate}{path}", method=method, payload=payload)
        except Exception as e:
            last_err = e
            continue
    raise RuntimeError(f"Unable to reach Ollama on any known endpoint: {last_err}")


def list_provider_models(provider, api_key="", base_url=""):
    provider = (provider or "").strip().lower()

    try:
        if provider == "ollama":
            data = _ollama_request_json(base_url, "/api/tags")
            models = [m.get("name", "") for m in data.get("models", []) if m.get("name")]
            return sorted(models)

        if provider == "openai":
            if not api_key:
                return []
            openai_url = (base_url or DEFAULT_OPENAI_BASE_URL).rstrip("/")
            data = _read_json_response(
                f"{openai_url}/models",
                headers={"Authorization": f"Bearer {api_key}"},
            )
            models = [m.get("id", "") for m in data.get("data", []) if m.get("id")]
            return sorted(models)

        if provider == "gemini":
            if not api_key:
                return []
            genai.configure(api_key=api_key)
            models = []
            for model in genai.list_models():
                name = getattr(model, "name", "")
                if name.startswith("models/") and "generateContent" in getattr(model, "supported_generation_methods", []):
                    models.append(name.replace("models/", ""))
            return sorted(models)
    except Exception:
        return []

    return []


def resolve_llm_config():
    provider = os.getenv("LLM_PROVIDER", "").strip().lower()
    if not provider:
        provider = "gemini" if os.getenv("LLM_API_KEY", "").strip() else "ollama"

    if provider == "gemini":
        api_key = os.getenv("LLM_API_KEY", "").strip()
        model = os.getenv("LLM_MODEL", DEFAULT_GEMINI_MODEL).strip() or DEFAULT_GEMINI_MODEL
        return {
            "provider": provider,
            "api_key": api_key,
            "model": model,
            "base_url": "",
        }

    if provider == "openai":
        api_key = os.getenv("OPENAI_API_KEY", "").strip() or os.getenv("LLM_API_KEY", "").strip()
        model = os.getenv("LLM_MODEL", DEFAULT_OPENAI_MODEL).strip() or DEFAULT_OPENAI_MODEL
        base_url = os.getenv("OPENAI_BASE_URL", DEFAULT_OPENAI_BASE_URL).strip() or DEFAULT_OPENAI_BASE_URL
        return {
            "provider": provider,
            "api_key": api_key,
            "model": model,
            "base_url": base_url,
        }

    # Default to ollama for local/offline processing.
    model = os.getenv("LLM_MODEL", DEFAULT_OLLAMA_MODEL).strip() or DEFAULT_OLLAMA_MODEL
    base_url = os.getenv("OLLAMA_BASE_URL", DEFAULT_OLLAMA_BASE_URL).strip() or DEFAULT_OLLAMA_BASE_URL
    return {
        "provider": "ollama",
        "api_key": "",
        "model": model,
        "base_url": base_url,
    }


class LLMClient:
    def __init__(self):
        cfg = resolve_llm_config()
        self.provider = cfg["provider"]
        self.model = cfg["model"]
        self.base_url = cfg["base_url"]
        self.api_key = cfg["api_key"]

        print(f"Using LLM provider={self.provider} model={self.model}")

        if self.provider == "gemini":
            if not self.api_key:
                raise ValueError("LLM_API_KEY environment variable not set for Gemini provider.")
            self.llm = ChatGoogleGenerativeAI(
                model=self.model,
                google_api_key=self.api_key,
                temperature=0,
                max_retries=1,  # Fail fast — don't spin forever on quota errors
            )
        else:
            self.llm = None

    def invoke_json(self, system_prompt, user_prompt_text):
        """Invoke LLM and return parsed JSON, or None on failure."""
        try:
            if self.provider == "gemini":
                prompt = ChatPromptTemplate.from_messages([
                    ("system", "{system_content}"),
                    ("user", "{user_content}"),
                ])
                chain = prompt | self.llm
                response_str = chain.invoke({
                    "system_content": system_prompt,
                    "user_content": user_prompt_text,
                }).content
                return _normalize_json_response(response_str)

            if self.provider == "ollama":
                payload = {
                    "model": self.model,
                    "stream": False,
                    "format": "json",
                    "prompt": f"System:\n{system_prompt}\n\nUser:\n{user_prompt_text}",
                    "options": {"temperature": 0},
                }
                data = _ollama_request_json(self.base_url, "/api/generate", method="POST", payload=payload)
                return _normalize_json_response(data.get("response", "{}"))

            if self.provider == "openai":
                payload = {
                    "model": self.model,
                    "temperature": 0,
                    "response_format": {"type": "json_object"},
                    "messages": [
                        {"role": "system", "content": system_prompt},
                        {"role": "user", "content": user_prompt_text},
                    ],
                }
                data = _read_json_response(
                    f"{self.base_url.rstrip('/')}/chat/completions",
                    method="POST",
                    headers={"Authorization": f"Bearer {self.api_key}"},
                    payload=payload,
                )
                response_str = data.get("choices", [{}])[0].get("message", {}).get("content", "{}")
                return _normalize_json_response(response_str)

            raise RuntimeError(f"Unsupported LLM provider: {self.provider}")
        except Exception as e:
            err_str = str(e)
            # Surface quota errors immediately — don't swallow them
            if any(k in err_str for k in ("quota", "ResourceExhausted", "429", "rate limit")):
                raise RuntimeError(
                    "Provider quota/rate limit exceeded. "
                    "Switch provider/model in Setup or retry after provider quota resets."
                ) from e
            print(f"LLM Invocation Error: {e}")
            return None


class SinglePassProcessor:
    def __init__(self, llm_client):
        self.client = llm_client

    def process(self, email_data):
        print(f"   [SinglePass] {email_data['subject']} — from {email_data['sender']}")
        current_date = date.today().isoformat()
        system_prompt = prompts.SINGLE_PASS_SYSTEM_PROMPT.format(current_date=current_date)
        user_text = (
            f"From: {email_data['sender']}\n"
            f"Subject: {email_data['subject']}\n"
            f"Date: {email_data['date']}\n\n"
            f"{email_data['body']}"
        )
        return self.client.invoke_json(system_prompt, user_text)


def parse_raw_email(file_path):
    """
    Parse a .txt email file saved by fetch_unread_emails_and_save().
    Files begin with prepended metadata lines (Sender/Subject/Date),
    followed by a blank line, then raw RFC-2822 content or plain body text.
    We extract sender/subject/date from the prepended lines directly
    to avoid confusion with the RFC-2822 parser.
    """
    with open(file_path, "r", encoding="utf-8") as f:
        lines = f.readlines()

    metadata = {}
    body_start = 0

    # Extract metadata from the prepended header block (until first blank line)
    for i, line in enumerate(lines):
        stripped = line.strip()
        if not stripped:
            body_start = i + 1
            break
        if stripped.startswith("Sender:"):
            metadata["sender"] = stripped[len("Sender:"):].strip()
        elif stripped.startswith("Subject:"):
            metadata["subject"] = stripped[len("Subject:"):].strip()
        elif stripped.startswith("Date:"):
            metadata["date"] = stripped[len("Date:"):].strip()

    # Try to extract a richer plain-text body from the RFC-2822 section
    body_content = "".join(lines[body_start:])
    body = ""
    try:
        email_msg = email.message_from_string(body_content, policy=default)
        if email_msg.is_multipart():
            for part in email_msg.walk():
                if part.get_content_type() == "text/plain":
                    body = part.get_payload(decode=True).decode(
                        part.get_content_charset() or "utf-8", errors="ignore"
                    )
                    break
        else:
            payload = email_msg.get_payload(decode=True)
            if payload:
                body = payload.decode(
                    email_msg.get_content_charset() or "utf-8", errors="ignore"
                )
    except Exception:
        pass

    # Fall back to raw body section if parser yielded nothing
    if not body.strip():
        body = body_content

    return {
        "gmail_id": os.path.basename(file_path).replace(".txt", ""),
        "sender": metadata.get("sender", "Unknown"),
        "subject": metadata.get("subject", "No Subject"),
        "date": metadata.get("date", ""),
        "body": body.strip() or body_content.strip(),
    }


def run_agentic_pipeline():
    print("Connecting to configured LLM provider…")
    llm_client = LLMClient()
    processor = SinglePassProcessor(llm_client)

    if not os.path.exists(RAW_EMAILS_DIR):
        print("No raw_emails directory found.")
        return

    processed_ids = set()
    if os.path.exists(PROCESSED_EMAILS_FILE):
        with open(PROCESSED_EMAILS_FILE, "r") as f:
            for line in f:
                try:
                    processed_ids.add(json.loads(line).get("gmail_id"))
                except Exception:
                    pass

    files = [fn for fn in os.listdir(RAW_EMAILS_DIR) if fn.endswith(".txt")]
    new_files = [fn for fn in files if fn.replace(".txt", "") not in processed_ids]
    print(f"Found {len(files)} raw emails. Processing {len(new_files)} new ones…")

    for fname in new_files:
        email_data = parse_raw_email(os.path.join(RAW_EMAILS_DIR, fname))
        print(f"\n→ {email_data['subject']}")

        result = processor.process(email_data)
        if not result:
            print("   [Error] Processing failed — skipping.")
            continue

        final_record = {**email_data, **result}
        with open(PROCESSED_EMAILS_FILE, "a") as f:
            f.write(json.dumps(final_record) + "\n")
        print("   [Done] Saved.")


if __name__ == "__main__":
    run_agentic_pipeline()
