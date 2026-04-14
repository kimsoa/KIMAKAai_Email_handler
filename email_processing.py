import os
import json
import base64
import email
from email.policy import default
from langchain_google_genai import ChatGoogleGenerativeAI
from langchain_core.prompts import ChatPromptTemplate
from langchain_core.output_parsers import JsonOutputParser
from googleapiclient.discovery import build
from google.auth.transport.requests import Request
import pickle
from googleapiclient.errors import HttpError
import prompts  # The new prompts file
from dotenv import load_dotenv

# Load env vars
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

# --- Configuration ---
DEFAULT_GEMINI_MODEL = "gemini-2.5-flash-lite"
RAW_EMAILS_DIR = "raw_emails"
PROCESSED_EMAILS_FILE = "processed_emails.jsonl"
SCOPES = ['https://www.googleapis.com/auth/gmail.modify']
CRITIC_THRESHOLD = 4  # Scores below this trigger a revision

# --- Gmail Service Helpers ---
def get_gmail_service_for_modify():
    creds = None
    if os.path.exists('token.pickle'):
        with open('token.pickle', 'rb') as token:
            creds = pickle.load(token)
    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
        else:
            # Note: usually handled by fetcher, but good fallback
            print("Warning: simple refresh needed or creds invalid.")
    return build('gmail', 'v1', credentials=creds)

# --- Class Definitions ---

class LLMClient:
    def __init__(self):
        # Default to env var
        api_key = os.getenv("LLM_API_KEY", "")
        
        if not api_key:
            raise ValueError("LLM_API_KEY environment variable not set.")

        print(f"Detected Key. Using Google GenAI Model: {DEFAULT_GEMINI_MODEL}")
        self.llm = ChatGoogleGenerativeAI(
            model=DEFAULT_GEMINI_MODEL,
            google_api_key=api_key,
            temperature=0
        )

    def invoke_json(self, system_prompt, user_prompt_text):
        """Helper to invoke LLM and ensure JSON output."""
        # Use safe variable injection to avoid LangChain parsing braces in content
        prompt = ChatPromptTemplate.from_messages([
            ("system", "{system_content}"),
            ("user", "{user_content}")
        ])
        chain = prompt | self.llm
        
        try:
            response_str = chain.invoke({
                "system_content": system_prompt,
                "user_content": user_prompt_text
            }).content
            # Basic cleanup for markdown code blocks common in local models
            clean_str = response_str.strip()
            if clean_str.startswith("```json"):
                clean_str = clean_str[7:]
            if clean_str.endswith("```"):
                clean_str = clean_str[:-3]
            
            return json.loads(clean_str.strip())
        except Exception as e:
            print(f"LLM Invocation Error: {e}")
            # print(f"Raw Output: {response_str}") # response_str might be unbound
            return None

class EmailCategorizer:
    def __init__(self, llm_client):
        self.client = llm_client

    def categorize(self, email_data):
        print(f"   [Categorizer] Analyzing email from {email_data['sender']}...")
        user_text = prompts.CATEGORIZATION_USER_PROMPT.format(
            sender=email_data['sender'],
            subject=email_data['subject'],
            body=email_data['body'][:1000] # Truncate for context window
        )
        result = self.client.invoke_json(prompts.CATEGORIZATION_SYSTEM_PROMPT, user_text)
        if not result:
            return {"category": "Uncategorized", "priority": "Medium"}
        return result

class EmailHandler:
    def __init__(self, llm_client):
        self.client = llm_client

    def process_email(self, email_data, category_info):
        raise NotImplementedError

class DeadlineHandler(EmailHandler):
    def process_email(self, email_data, category_info):
        print("   [Handler] Using Deadline-Driven Strategy.")
        user_text = f"Email Body:\n{email_data['body']}"
        return self.client.invoke_json(prompts.DEADLINE_HANDLER_SYSTEM_PROMPT, user_text)

class GeneralHandler(EmailHandler):
    def process_email(self, email_data, category_info):
        print("   [Handler] Using General Strategy.")
        user_text = f"Email Body:\n{email_data['body']}"
        return self.client.invoke_json(prompts.GENERAL_HANDLER_SYSTEM_PROMPT, user_text)

class HandlerFactory:
    @staticmethod
    def get_handler(category, llm_client):
        if "Deadline" in category:
            return DeadlineHandler(llm_client)
        # Extend here for other specific handlers (Urgent, Personal, etc.)
        return GeneralHandler(llm_client)

class EmailCritic:
    def __init__(self, llm_client):
        self.client = llm_client

    def evaluate(self, email_data, draft_response):
        print("   [Critic] Evaluating draft response...")
        user_text = prompts.CRITIC_USER_PROMPT.format(
            sender=email_data['sender'],
            subject=email_data['subject'],
            body=email_data['body'][:500],
            draft_response=draft_response
        )
        return self.client.invoke_json(prompts.CRITIC_SYSTEM_PROMPT, user_text)

class EmailReviser:
    def __init__(self, llm_client):
        self.client = llm_client

    def revise(self, draft_data, critique_data):
        print("   [Reviser] Improving draft based on feedback...")
        user_text = f"Original Draft: {draft_data['draft_response']}"
        system_text = prompts.REVISION_SYSTEM_PROMPT.format(
            score=critique_data['score'],
            feedback=critique_data.get('feedback', 'Improve clarity and tone.')
        )
        return self.client.invoke_json(system_text, user_text)

# --- Main Logic ---

def parse_raw_email(file_path):
    """Parses .txt raw email into a dict."""
    with open(file_path, 'r', encoding='utf-8') as f:
        content = f.read()
    
    # Simple parsing heuristic
    email_msg = email.message_from_string(content, policy=default)
    body = ""
    if email_msg.is_multipart():
        for part in email_msg.walk():
            if part.get_content_type() == "text/plain":
                body = part.get_payload(decode=True).decode(part.get_content_charset() or 'utf-8', errors='ignore')
                break
    else:
        body = email_msg.get_payload(decode=True).decode(email_msg.get_content_charset() or 'utf-8', errors='ignore')

    # Fallback if parsing failed (file might be raw text dump)
    if not body.strip():
        body = content

    return {
        "gmail_id": os.path.basename(file_path).replace(".txt", ""),
        "sender": email_msg.get("From", "Unknown"),
        "subject": email_msg.get("Subject", "No Subject"),
        "date": email_msg.get("Date", ""),
        "body": body.strip()
    }

def run_agentic_pipeline():
    print(f"Connecting to LLM (Gemini/Local)...")
    llm_client = LLMClient()
    categorizer = EmailCategorizer(llm_client)
    critic = EmailCritic(llm_client)
    reviser = EmailReviser(llm_client)

    if not os.path.exists(RAW_EMAILS_DIR):
        print("No raw_emails directory found.")
        return

    processed_ids = set()
    if os.path.exists(PROCESSED_EMAILS_FILE):
        with open(PROCESSED_EMAILS_FILE, 'r') as f:
            for line in f:
                try:
                    processed_ids.add(json.loads(line).get('gmail_id'))
                except: pass

    files = [f for f in os.listdir(RAW_EMAILS_DIR) if f.endswith(".txt")]
    print(f"Found {len(files)} emails. Processing...")

    for fname in files:
        if fname.replace(".txt", "") in processed_ids:
            continue

        email_data = parse_raw_email(os.path.join(RAW_EMAILS_DIR, fname))
        print(f"\nExample: Processing {email_data['subject']}...")

        # 1. Categorize
        cat_result = categorizer.categorize(email_data)
        category = cat_result.get("category", "General")
        
        # 2. Handle (Draft)
        handler = HandlerFactory.get_handler(category, llm_client)
        draft_result = handler.process_email(email_data, cat_result)
        
        if not draft_result:
            print("   [Error] Handler failed to generate draft.")
            continue

        # 3. Critique
        critique_result = critic.evaluate(email_data, draft_result.get("draft_response", ""))
        score = critique_result.get("score", 5)
        
        final_output = draft_result
        final_output['critique'] = critique_result

        # 4. Loop / Revise
        if score < CRITIC_THRESHOLD:
            print(f"   [Loop] Score {score}/5 is below threshold {CRITIC_THRESHOLD}. Revising...")
            revised_result = reviser.revise(draft_result, critique_result)
            if revised_result:
                final_output = revised_result
                final_output['revision_history'] = "Revised based on critique."
                print("   [Loop] Revision complete.")
            else:
                print("   [Loop] Revision failed. Keeping original.")

        # Save
        final_record = {**email_data, **cat_result, **final_output}
        with open(PROCESSED_EMAILS_FILE, 'a') as f:
            f.write(json.dumps(final_record) + "\n")
        
        print("   [Done] Saved processed email.")

if __name__ == "__main__":
    run_agentic_pipeline()