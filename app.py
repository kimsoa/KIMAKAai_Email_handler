import streamlit as st
import pandas as pd
import json
import os
from dotenv import set_key, load_dotenv
from email_fetcher import get_gmail_service

# Configuration
PROCESSED_EMAILS_FILE = "processed_emails.jsonl"
PAGE_TITLE = "Email Triage Agent"
PAGE_ICON = "📧"
ENV_FILE = ".env"

load_dotenv(ENV_FILE)

st.set_page_config(page_title=PAGE_TITLE, page_icon=PAGE_ICON, layout="wide")

# --- Helper Functions ---
def load_data():
    """Loads processed emails from JSONL file."""
    data = []
    if os.path.exists(PROCESSED_EMAILS_FILE):
        with open(PROCESSED_EMAILS_FILE, 'r') as f:
            for line in f:
                try:
                    data.append(json.loads(line))
                except json.JSONDecodeError:
                    pass
    return data

def get_stats(data):
    """Calculates basic stats for the sidebar."""
    df = pd.DataFrame(data)
    if df.empty:
        return {"total": 0, "urgent": 0, "deadline": 0}
    
    return {
        "total": len(df),
        "urgent": len(df[df['priority'] == 'High']),
        "deadline": len(df[df['category'].str.contains('Deadline', na=False)])
    }

# --- Settings & Configuration ---
def render_settings_page():
    st.title("⚙️ Setup & Configuration")
    
    st.markdown("""
    Welcome to the **Email Triage Agent**. To securely read your emails and process them with AI, you need to configure two things:
    1. **Google Gmail Connection** (so the app can read your inbox).
    2. **Gemini AI API Key** (so the agent can summarize emails and draft replies).
    """)

    auth_dir = "/app/auth"
    if not os.path.exists(auth_dir):
        os.makedirs(auth_dir)
    client_secret_path = os.path.join(auth_dir, "client_secret.json")
    token_path = os.path.join(auth_dir, "token.pickle")
    
    st.divider()

    # SECTION 1: GMAIL API SETUP
    st.header("1. Gmail API Configuration")
    
    # If the user has NOT uploaded their client secret yet
    if not os.path.exists(client_secret_path):
        st.warning("⚠️ You have not connected a Gmail account yet.")
        with st.expander("📖 Instructions: How to get your `client_secret.json`", expanded=True):
            st.markdown("""
            1. Go to the [Google Cloud Console](https://console.cloud.google.com/).
            2. Create a new Project (e.g., "Email Triage Agent").
            3. In the search bar, type **"Gmail API"** and click **Enable**.
            4. Navigate to **APIs & Services > OAuth consent screen**. Configure it as "External" and add your email address under "Test users".
            5. Navigate to **Credentials** in the left sidebar.
            6. Click **Create Credentials > OAuth client ID**. Select **Desktop app** as the Application type. *(If Desktop app asks for a redirect URI, ignore or use defaults)*
            7. Click **Download JSON** on the created client ID popup.
            8. Upload that downloaded JSON file below!
            """)
        
        st.subheader("Upload Credentials")
        st.info("Your credentials will be stored locally in an encrypted volume and are never transmitted to third parties.")
        uploaded_file = st.file_uploader("Upload your `client_secret.json` file here:", type="json")
        if uploaded_file is not None:
            with open(client_secret_path, "wb") as f:
                f.write(uploaded_file.getbuffer())
            st.success("✅ Client secret file uploaded successfully!")
            st.rerun()

    # If the user HAS uploaded their client secret but needs to authorize the consent screen
    else:
        auth_code = st.session_state.get("auth_code")
        service, auth_url = get_gmail_service(client_secret_path, token_path, auth_code)
        
        if auth_url:
            st.warning("⚠️ You uploaded the credentials, but you must now authorize the application.")

            st.info("""
            📋 **Quick Summary of what will happen:**
            
            You will click the link below → sign in → your browser will show **\'This site can\'t be reached\'**.
            
            ✅ **That \'error\' page IS the success!** The code you need is hidden in the browser\'s address bar URL.
            
            Copy that URL and paste it in the box below. That\'s it!
            """)

            st.markdown(f"""
            ### Step-by-Step Authorization:
            **Step 1** — [👉 Click here to open the Google sign-in page]({auth_url})
            
            **Step 2** — Sign in with the Gmail account you want to triage.
            
            **Step 3** — If you see **"Google hasn\'t verified this app"**, click **Advanced** → **Go to Email Triager (unsafe)**.
            
            **Step 4** — Grant the required permissions and click **Continue** / **Allow**.
            
            **Step 5** — Your browser will go to `http://localhost` and show a page saying **"This site can\'t be reached"** or **"ERR_CONNECTION_REFUSED"**.
            
            > 🟢 **THIS IS CORRECT — DO NOT try to refresh or fix it.** This page confirms Google sent your login code.
            
            **Step 6** — Look at your browser\'s **address bar** (where you type website URLs). You will see a long URL starting with `http://localhost/?state=...&code=4/0A...`
            
            **Step 7** — Select the entire URL from the address bar, **copy it** (Ctrl+C or Cmd+C), and paste it in the box below.
            """)

            auth_code_input = st.text_input("🔑 Step 7 — Paste the full URL from your browser address bar here (starts with http://localhost/?...):")
            if st.button("Connect Account"):
                st.session_state["auth_code"] = auth_code_input
                st.rerun()
                
        elif service is None:
            st.error("Authentication failed. Please check your credentials or delete `token.pickle` and try again.")
            if st.button("Reset Gmail Authentication"):
                if os.path.exists(client_secret_path):
                    os.remove(client_secret_path)
                if os.path.exists(token_path):
                    os.remove(token_path)
                st.session_state.pop("auth_code", None)
                st.rerun()
        else:
            st.success("✅ Your Gmail account is securely connected!")
            if st.button("Disconnect Gmail Account"):
                if os.path.exists(client_secret_path):
                    os.remove(client_secret_path)
                if os.path.exists(token_path):
                    os.remove(token_path)
                st.session_state.pop("auth_code", None)
                st.rerun()

    st.divider()

    # SECTION 2: GEMINI API SETUP
    st.header("2. AI Intelligence (Gemini API)")
    current_key = os.getenv("LLM_API_KEY", "")
    
    if current_key:
        st.success("✅ Gemini AI Key is configured!")
        with st.expander("Update / Change API Key"):
            new_key = st.text_input("Enter new Google Gemini API Key:", type="password")
            if st.button("Save New Key"):
                set_key(ENV_FILE, "LLM_API_KEY", new_key)
                os.environ["LLM_API_KEY"] = new_key
                st.rerun()
    else:
        st.warning("⚠️ You have not set an AI API Key. The agent cannot summarize emails.")
        with st.expander("📖 Instructions: How to get your Gemini API Key", expanded=True):
            st.markdown("""
            1. Go to Google AI Studio: [https://aistudio.google.com/app/apikey](https://aistudio.google.com/app/apikey).
            2. Sign in with your Google account.
            3. Click the **Create API key** button.
            4. Copy the generated key and paste it below.
            """)
        new_key = st.text_input("Enter your Google Gemini API Key:", type="password")
        if st.button("Save API Key"):
            if not os.path.exists(ENV_FILE):
                open(ENV_FILE, 'a').close()
            set_key(ENV_FILE, "LLM_API_KEY", new_key)
            os.environ["LLM_API_KEY"] = new_key
            st.success("API Key saved!")
            st.rerun()
    
    st.divider()
    st.info("Once both settings are ✅ green, click 'Inbox' in the sidebar to view your emails.")


def is_fully_configured():
    """Returns True if both Gmail OAuth and LLM API Key are successfully set."""
    auth_dir = "/app/auth"
    token_path = os.path.join(auth_dir, "token.pickle")
    client_secret_path = os.path.join(auth_dir, "client_secret.json")
    
    has_api_key = bool(os.getenv("LLM_API_KEY", ""))
    
    if not os.path.exists(token_path) and not os.path.exists(client_secret_path):
        return False
        
    auth_code = st.session_state.get("auth_code")
    service, _ = get_gmail_service(client_secret_path, token_path, auth_code)
    
    return has_api_key and service is not None

# --- UI Components ---
def render_sidebar(stats):
    st.sidebar.title(f"{PAGE_ICON} {PAGE_TITLE}")
    
    st.sidebar.header("Inbox Stats")
    col1, col2 = st.sidebar.columns(2)
    col1.metric("Urgent", stats['urgent'])
    col2.metric("Deadline", stats['deadline'])
    st.sidebar.metric("Total Pending", stats['total'])
    
    st.sidebar.markdown("---")
    st.sidebar.subheader("Navigation")
    
    # Check config to default to Settings if incomplete
    configured = is_fully_configured()
    options = ["Inbox", "Drafts", "Archived", "⚙️ Settings"]
    default_idx = 0 if configured else 3
    
    choice = st.sidebar.radio("Go to", options, index=default_idx)
    return choice

def render_email_card(email):
    """Renders a single email decision card."""
    with st.container():
        st.markdown(f"### {email.get('subject', 'No Subject')}")
        
        # Metadata Badges
        col1, col2, col3 = st.columns([1, 1, 4])
        
        priority_color = "red" if email.get('priority') == "High" else "blue"
        category_color = "orange" if "Deadline" in email.get('category', '') else "green"
        
        col1.markdown(f":{priority_color}[{email.get('priority', 'Normal')}]")
        col2.markdown(f":{category_color}[{email.get('category', 'General')}]")
        
        # Main Content Layout
        c1, c2 = st.columns([3, 2])
        
        with c1:
            st.markdown(f"**From:** {email.get('sender', 'Unknown')}")
            
            if 'summary' in email:
                st.markdown(f"**Summary:** {email['summary']}")
            
            if 'action_items' in email and email['action_items']:
                st.markdown("**Action Items:**")
                for item in email['action_items']:
                    st.checkbox(item, key=f"check_{email.get('gmail_id')}_{item}")
            
            with st.expander("View Original Email Body", expanded=False):
                st.text(email.get('body', ''))
                
            st.markdown("#### AI Draft Response")
            draft_text = email.get('draft_response', 'No draft generated.')
            st.info(draft_text)
            
            critique = email.get('critique', {})
            score = critique.get('score', 0)
            if score > 0:
                st.markdown(f"**Quality Score:** {score}/5")
                if score < 5:
                    st.caption(f"Feedback: {critique.get('feedback', '')}")

        with c2:
            st.markdown("### Actions")
            if st.button("Approve & Send", key=f"btn_approve_{email.get('gmail_id')}"):
                st.success("Email sent! (Simulated)")
            
            if st.button("Edit Draft", key=f"btn_edit_{email.get('gmail_id')}"):
                st.session_state[f"edit_mode_{email.get('gmail_id')}"] = True

            if st.button("Reject / Archive", key=f"btn_reject_{email.get('gmail_id')}"):
                st.warning("Email archived. (Simulated)")

        st.markdown("---")

# --- Main App ---
def main():
    data = load_data()
    stats = get_stats(data)
    
    choice = render_sidebar(stats)
    
    if choice == "⚙️ Settings":
        render_settings_page()
    elif not is_fully_configured():
        st.warning("Please complete the Setup in the Settings page before viewing your Inbox.")
        st.stop()
    elif choice == "Inbox":
        st.header(f"Inbox ({stats['total']} Pending)")
        
        if not data:
            st.info("No processed emails found. Check back later or run the processing script.")
            return
        
        for email in reversed(data): # Show newest first
            render_email_card(email)
    elif choice in ["Drafts", "Archived"]:
        st.header(choice)
        st.info("This section is under construction.")

if __name__ == "__main__":
    main()
