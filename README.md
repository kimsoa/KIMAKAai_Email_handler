# KIMAKAai Email Handler

A sophisticated open-source Gmail triaging and processing application using AI. It fetches unread emails, analyzes their content for specific queries, issues, or requests, and outputs parsed structured actions based on dynamic prompts.

## New Feature ✨
The UI has been upgraded so you **no longer need to edit the source code** to upload your Google App `client_secret.json`! You can securely point to your local credentials file entirely via the Streamlit web interface and control the OAuth flow dynamically.

## Quick Installation & Run (via Docker)

You don't need any Python dependencies! Run this app perfectly isolated in 1 step from Docker Hub.

**Prerequisites:** [Docker](https://docs.docker.com/get-docker/)

```bash
docker run -d --name kimakaai-email-handler -v auth_data:/app/auth -p 8503:8501 <YOUR_DOCKER_USERNAME>/kimakaai-email-handler:latest
```

## How to Access & Configure

Before accessing the application, you need to generate a Google App `client_secret.json` from the Google Cloud Console.

**Step 1: Get your `client_secret.json`**
1. Go to the [Google Cloud Console](https://console.cloud.google.com/).
2. Create a new Project (e.g., "Email Triage Agent").
3. In the search bar, type **"Gmail API"** and click **Enable**.
4. Navigate to **APIs & Services > OAuth consent screen**. Configure it as "External" and add your personal email address under "Test users".
5. Navigate to **Credentials** in the left sidebar.
6. Click **Create Credentials > OAuth client ID**. Select **Desktop app** as the Application type. 
7. Click **Download JSON** on the created client ID popup and save it securely.

**Step 2: Run the App**
1. Open your web browser and go to: **[http://localhost:8503](http://localhost:8503)**.
2. You will be greeted by the **Setup & Settings Page**.
3. Upload the `client_secret.json` file you acquired in Step 1.
4. If you wish to use the AI capabilities, enter your Google Gemini API Key in the second section (instructions included in the app).
5. Follow the Google authentication prompts via the secure callback URL.
6. The app will turn green, granting you access to the Inbox Dashboard where you can analyze your inbox securely!

*(Note: Replace `<YOUR_DOCKER_USERNAME>` with the Docker Hub username where the image is hosted)*.
