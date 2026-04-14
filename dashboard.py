import streamlit as st
import pandas as pd
import json
import os
import pickle
from google.auth.transport.requests import Request
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError

# ----- Gmail helper ---------------------------------------------------------
def get_gmail_service():
    creds = None
    if os.path.exists('token.pickle'):
        with open('token.pickle', 'rb') as token:
            creds = pickle.load(token)
    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
        else:
            st.error("OAuth token missing or invalid. Please run the Gmail fetcher first.")
            st.stop()
    return build('gmail', 'v1', credentials=creds)

def add_label(email_id, label_name):
    """Add a label to the email; creates the label if it doesn't exist."""
    service = get_gmail_service()
    # 1. Search for the label ID
    labels = service.users().labels().list(userId='me').execute().get('labels', [])
    label_id = None
    for lbl in labels:
        if lbl['name'].lower() == label_name.lower():
            label_id = lbl['id']
            break
    # 2. Create the label if it doesn't exist
    if not label_id:
        lbl_body = {"name": label_name, "labelListVisibility": "labelShow", "messageListVisibility": "show"}
        label_id = service.users().labels().create(userId='me', body=lbl_body).execute()['id']
    # 3. Add the label to the message
    service.users().messages().modify(
        userId='me',
        id=email_id,
        body={'addLabelIds': [label_id]}
    ).execute()

# ----- Slack helper (copy‑paste from source [7]) -----------------------------
import urllib.request, json, threading, traceback

def notify_slack(channel, status, msg):
    slack_channel = channel.replace('-', '').replace('_', '').upper()
    url = os.environ['SLACK_' + slack_channel + '_WEBHOOK_URL']
    json_data = json.dumps({'text': f'--- {status} ---\\n{msg}'}).encode('ascii')
    req = urllib.request.Request(url, data=json_data, headers={'Content-type': 'application/json'})
    thr = threading.Thread(target=urllib.request.urlopen, args=(req, ))
    try:
        thr.start()
    except Exception as e:
        st.error(f'Failed to send alert to Slack: {e}')

# ----- Streamlit UI --------------------------------------------------------
st.title("Email Triage Dashboard")

# Load processed JSONL
if not os.path.exists('processed_emails.jsonl'):
    st.error("processed_emails.jsonl not found. Please run the LangChain triage script first.")
    st.stop()

records = []
with open('processed_emails.jsonl', 'r', encoding='utf-8') as f:
    for line in f:
        try:
            records.append(json.loads(line))
        except json.JSONDecodeError:
            continue
df = pd.DataFrame(records)

# Basic filter widgets
prio_filter = st.multiselect("Priority filter", options=df['priority'].unique(), default=df['priority'].unique())
cat_filter = st.multiselect("Category filter", options=df['category'].unique(), default=df['category'].unique())

filtered_df = df[df['priority'].isin(prio_filter) & df['category'].isin(cat_filter)]

st.write(f"Showing {len(filtered_df)} out of {len(df)} emails")

# Display table
st.dataframe(filtered_df[['gmail_id', 'sender', 'subject', 'priority', 'category', 'summary']])

# Action column
for idx, row in filtered_df.iterrows():
    col1, col2 = st.columns([2, 1])
    with col1:
        st.markdown(f"**{row['subject']}** (from {row['sender']})")
    with col2:
        if st.button("Mark as Reviewed", key=row['gmail_id']):
            try:
                add_label(row['gmail_id'], "Reviewed")
                st.success(f"Added 'Reviewed' label to email {row['gmail_id']}")
            except HttpError as e:
                st.error(f"Error adding label: {e}")

# Optional Slack alert for high‑priority items
high_priority = filtered_df[filtered_df['priority'] == 'High']
if not high_priority.empty and st.button("Send Slack alert for High‑Priority"):
    for _, hp in high_priority.iterrows():
        msg = f"High‑Priority email from {hp['sender']}: {hp['subject']}"
        notify_slack("general", "HIGH PRIORITY", msg)
    st.success("Slack alerts sent for all high‑priority emails.")

# End of app