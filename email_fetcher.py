import os
import json
import time
import pickle
from urllib.parse import urlparse, parse_qs
from google.auth.transport.requests import Request
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError
import base64
import email

SCOPES = ['https://www.googleapis.com/auth/gmail.readonly']

# Google deprecated the OOB flow in Oct 2022. Loopback redirect is the replacement.
# The browser will show "This site can't be reached" — that is expected.
REDIRECT_URI = 'http://localhost'

# Google auth codes expire in 10 minutes. We allow 15 min before regenerating.
_PKCE_MAX_AGE_SECS = 900


def _pkce_file(token_path: str) -> str:
    return os.path.join(os.path.dirname(os.path.abspath(token_path)), 'pkce_pending.json')


def _load_pending(token_path: str):
    """Return saved (auth_url, verifier) if within max age, else None."""
    path = _pkce_file(token_path)
    try:
        with open(path, 'r') as f:
            data = json.load(f)
        if time.time() - data.get('ts', 0) > _PKCE_MAX_AGE_SECS:
            os.remove(path)
            return None
        return data
    except (OSError, json.JSONDecodeError, KeyError):
        return None


def _save_pending(token_path: str, auth_url: str, verifier: str):
    path = _pkce_file(token_path)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, 'w') as f:
        json.dump({'auth_url': auth_url, 'verifier': verifier, 'ts': time.time()}, f)


def _clear_pending(token_path: str):
    try:
        os.remove(_pkce_file(token_path))
    except OSError:
        pass


def _extract_code(raw_input: str) -> str:
    """Accepts either a bare auth code or the full redirect URL and returns just the code."""
    raw_input = raw_input.strip()
    if raw_input.startswith('http'):
        parsed = urlparse(raw_input)
        params = parse_qs(parsed.query)
        codes = params.get('code')
        if codes:
            return codes[0]
    return raw_input


def get_gmail_service(client_secret_path='client_secret.json', token_path='token.pickle',
                      auth_code=None, code_verifier=None):
    """Loads credentials from `token.pickle` if available, otherwise performs OAuth flow.

    PKCE (auth_url + code_verifier) is persisted to a file next to token.pickle so the
    pair survives Streamlit server restarts triggered by file-watcher reloads.

    Returns (service, auth_url, code_verifier):
      - (service, None, None)       — already authenticated
      - (None, auth_url, verifier)  — need user to visit auth_url, then call back with auth_code
      - (None, None, None)          — error (missing client_secret or unrecoverable state)
    """
    creds = None
    if os.path.exists(token_path):
        with open(token_path, 'rb') as f:
            creds = pickle.load(f)
        _clear_pending(token_path)  # auth is complete; clean up any leftover pending file

    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
        else:
            if not os.path.exists(client_secret_path):
                return None, None, None

            flow = InstalledAppFlow.from_client_secrets_file(client_secret_path, SCOPES)
            flow.redirect_uri = REDIRECT_URI

            if auth_code:
                # --- Token exchange ---
                # Resolve verifier: prefer the value passed in (from session_state),
                # then fall back to the file (survives Streamlit restarts).
                verifier = code_verifier
                if not verifier:
                    pending = _load_pending(token_path)
                    if pending:
                        verifier = pending.get('verifier')

                if not verifier:
                    # Verifier is gone and the pending file is expired/missing.
                    # Return a sentinel so the caller can show the auth URL again.
                    return None, None, None

                code = _extract_code(auth_code.strip())
                flow.fetch_token(code=code, code_verifier=verifier)
                creds = flow.credentials
                _clear_pending(token_path)
            else:
                # --- Auth URL request ---
                # Reuse an existing valid pending pair so we never change the
                # code_challenge that's already been sent to Google's auth server.
                pending = _load_pending(token_path)
                if pending:
                    return None, pending['auth_url'], pending['verifier']

                # No valid pending file — generate a fresh PKCE pair.
                auth_url, _ = flow.authorization_url(prompt='consent')
                verifier = flow.code_verifier
                _save_pending(token_path, auth_url, verifier)
                return None, auth_url, verifier

        with open(token_path, 'wb') as f:
            pickle.dump(creds, f)

    return build('gmail', 'v1', credentials=creds), None, None

def fetch_unread_emails_and_save():
    """Fetches unread emails from Gmail and saves their raw content."""
    auth_dir = os.environ.get("AUTH_DIR", ".")
    secret = os.path.join(auth_dir, "client_secret.json")
    token = os.path.join(auth_dir, "token.pickle")
    service, _, _ = get_gmail_service(secret, token)
    emails_fetched_count = 0
    try:
        # Request only unread messages
        results = service.users().messages().list(userId='me', labelIds=['UNREAD']).execute()
        messages = results.get('messages', [])

        if not messages:
            print("No unread messages found.")
            return

        print(f"Found {len(messages)} unread messages.")

        # Create a directory to store raw emails if it doesn't exist
        os.makedirs('raw_emails', exist_ok=True)

        for msg in messages:
            msg_id = msg['id']
            # Get the full message details
            message_data = service.users().messages().get(userId='me', id=msg_id, format='raw').execute()
            raw_email = base64.urlsafe_b64decode(message_data['raw']).decode('utf-8')

            # Parse the email using the email library to extract header and body
            msg_parser = email.message_from_string(raw_email)
            subject = msg_parser['subject']
            sender = msg_parser['from']
            date = msg_parser['date']

            # For now, we'll just save the raw content to a file
            # In Phase 2, we'll parse and process this content.
            file_path = f"raw_emails/{msg_id}.txt"
            with open(file_path, 'w', encoding='utf-8') as f:
                f.write(f"Sender: {sender}\n")
                f.write(f"Subject: {subject}\n")
                f.write(f"Date: {date}\n\n")
                f.write(raw_email) # Save the full raw content

            print(f"Saved email '{subject}' from '{sender}' (ID: {msg_id}) to {file_path}")
            emails_fetched_count += 1
            # OPTIONAL: Mark email as read after processing (for later, after successful triage)
            # service.users().messages().modify(userId='me', id=msg_id, body={'removeLabelIds': ['UNREAD']}).execute()

    except HttpError as error:
        print(f"An error occurred: {error}")
    
    print(f"Successfully fetched and saved {emails_fetched_count} unread emails.")


if __name__ == '__main__':
    fetch_unread_emails_and_save()
