import os
import json
import email
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
RAW_EMAILS_DIR = "raw_emails"
PROCESSED_EMAILS_FILE = "processed_emails.jsonl"


class LLMClient:
    def __init__(self):
        api_key = os.getenv("LLM_API_KEY", "")
        if not api_key:
            raise ValueError("LLM_API_KEY environment variable not set.")
        print(f"Using Google GenAI Model: {DEFAULT_GEMINI_MODEL}")
        self.llm = ChatGoogleGenerativeAI(
            model=DEFAULT_GEMINI_MODEL,
            google_api_key=api_key,
            temperature=0,
            max_retries=1,  # Fail fast — don't spin forever on quota errors
        )

    def invoke_json(self, system_prompt, user_prompt_text):
        """Invoke LLM and return parsed JSON, or None on failure."""
        prompt = ChatPromptTemplate.from_messages([
            ("system", "{system_content}"),
            ("user", "{user_content}"),
        ])
        chain = prompt | self.llm
        try:
            response_str = chain.invoke({
                "system_content": system_prompt,
                "user_content": user_prompt_text,
            }).content
            clean = response_str.strip()
            if clean.startswith("```json"):
                clean = clean[7:]
            if clean.startswith("```"):
                clean = clean[3:]
            if clean.endswith("```"):
                clean = clean[:-3]
            return json.loads(clean.strip())
        except Exception as e:
            err_str = str(e)
            # Surface quota errors immediately — don't swallow them
            if any(k in err_str for k in ("quota", "ResourceExhausted", "429", "rate limit")):
                raise RuntimeError(
                    f"Gemini API daily quota exceeded "
                    f"(free tier: 20 req/day for {DEFAULT_GEMINI_MODEL}). "
                    f"Processing will resume automatically tomorrow when the quota resets."
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
    print("Connecting to LLM (Gemini)…")
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
