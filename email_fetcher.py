import os
import pickle
from urllib.parse import urlparse, parse_qs
from google.auth.transport.requests import Request
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError
import base64
import email

SCOPES = ['https://www.googleapis.com/auth/gmail.readonly']

# Google deprecated the OOB (urn:ietf:wg:oauth:2.0:oob) copy-paste flow in Oct 2022.
# The loopback redirect URI is the supported replacement for Desktop app type OAuth clients.
# The user's browser will show "This site can't be reached" — that is expected.
# They should copy the full URL from the address bar and paste it into the app.
REDIRECT_URI = 'http://localhost'


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


def get_gmail_service(client_secret_path='client_secret.json', token_path='token.pickle', auth_code=None):
    """Loads credentials from `token.pickle` if available, otherwise performs OAuth flow."""
    creds = None
    if os.path.exists(token_path):
        with open(token_path, 'rb') as token:
            creds = pickle.load(token)

    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
        else:
            if not os.path.exists(client_secret_path):
                return None, None  # Indicate that client secret is missing

            flow = InstalledAppFlow.from_client_secrets_file(client_secret_path, SCOPES)
            flow.redirect_uri = REDIRECT_URI  # fixes Error 400: invalid_request / OOB flow deprecation
            if auth_code:
                code = _extract_code(auth_code)
                flow.fetch_token(code=code)
                creds = flow.credentials
            else:
                auth_url, _ = flow.authorization_url(prompt='consent')
                return None, auth_url

        with open(token_path, 'wb') as token:
            pickle.dump(creds, token)

    return build('gmail', 'v1', credentials=creds), None

def fetch_unread_emails_and_save():
    """Fetches unread emails from Gmail and saves their raw content."""
    service = get_gmail_service()
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
