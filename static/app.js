/* ============================================================
   KIMAKAai Email Handler — Frontend Logic
   ============================================================ */

// ── State ────────────────────────────────────────────────────────────────────
let _jobPollInterval = null;

// ── Utilities ─────────────────────────────────────────────────────────────────

function show(id) {
  document.querySelectorAll('.view').forEach(v => {
    v.classList.remove('active');
    v.style.display = 'none';
  });
  const el = document.getElementById(id);
  el.style.display = 'flex';
  el.classList.add('active');
}

function showCard(cardId) {
  ['setup-step-1', 'setup-step-2', 'setup-step-3', 'setup-done'].forEach(id => {
    document.getElementById(id).classList.add('hidden');
  });
  document.getElementById(cardId).classList.remove('hidden');
}

function setStepIndicator(active) {
  [1, 2, 3].forEach(i => {
    const el = document.getElementById(`step-indicator-${i}`);
    el.classList.remove('active', 'done');
    if (i < active) el.classList.add('done');
    if (i === active) el.classList.add('active');
  });
}

function showFeedback(id, msg, type) {
  const el = document.getElementById(id);
  el.textContent = msg;
  el.className = `feedback ${type}`;
}

function hideFeedback(id) {
  const el = document.getElementById(id);
  el.className = 'feedback hidden';
}

function escHtml(s) {
  return String(s)
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;');
}

async function api(method, path, body = null) {
  const opts = { method, headers: {} };
  if (body && !(body instanceof FormData)) {
    opts.headers['Content-Type'] = 'application/json';
    opts.body = JSON.stringify(body);
  } else if (body instanceof FormData) {
    opts.body = body;
  }
  const resp = await fetch(path, opts);
  if (!resp.ok) {
    const err = await resp.json().catch(() => ({ detail: resp.statusText }));
    throw new Error(err.detail || resp.statusText);
  }
  return resp.json();
}

// ── Init ──────────────────────────────────────────────────────────────────────

async function init() {
  show('view-loading');
  document.querySelector('#view-loading p').textContent = 'Loading…';
  try {
    const status = await api('GET', '/api/status');
    route(status);
  } catch (e) {
    document.querySelector('#view-loading p').textContent = 'Failed to connect to server. Retrying…';
    setTimeout(init, 3000);
  }
}

function route(status) {
  if (!status.has_client_secret) {
    show('view-setup');
    showCard('setup-step-1');
    setStepIndicator(1);
    return;
  }
  if (!status.authenticated) {
    show('view-setup');
    showCard('setup-step-2');
    setStepIndicator(2);
    return;
  }
  if (!status.has_api_key) {
    show('view-setup');
    showCard('setup-step-3');
    setStepIndicator(3);
    return;
  }
  showInbox();
}

// ── Step 1: Upload client_secret.json ─────────────────────────────────────────

let _selectedFile = null;

document.getElementById('upload-area').addEventListener('click', () => {
  document.getElementById('file-input').click();
});

document.getElementById('upload-area').addEventListener('dragover', e => {
  e.preventDefault();
  document.getElementById('upload-area').classList.add('dragover');
});

document.getElementById('upload-area').addEventListener('dragleave', () => {
  document.getElementById('upload-area').classList.remove('dragover');
});

document.getElementById('upload-area').addEventListener('drop', e => {
  e.preventDefault();
  document.getElementById('upload-area').classList.remove('dragover');
  const file = e.dataTransfer.files[0];
  if (file) handleFileSelected(file);
});

document.getElementById('file-input').addEventListener('change', e => {
  if (e.target.files[0]) handleFileSelected(e.target.files[0]);
});

function handleFileSelected(file) {
  if (!file.name.endsWith('.json')) {
    showFeedback('upload-feedback', 'Please select a .json file', 'error');
    return;
  }
  _selectedFile = file;
  hideFeedback('upload-feedback');
  document.getElementById('btn-upload').disabled = false;
  document.querySelector('#upload-area p').innerHTML =
    `Selected: <strong>${escHtml(file.name)}</strong>`;
}

document.getElementById('btn-upload').addEventListener('click', async () => {
  if (!_selectedFile) return;
  const btn = document.getElementById('btn-upload');
  btn.disabled = true;
  btn.textContent = 'Uploading…';
  try {
    const form = new FormData();
    form.append('file', _selectedFile);
    await api('POST', '/api/settings/client-secret', form);
    showFeedback('upload-feedback', '✅ Uploaded successfully!', 'success');
    setTimeout(() => {
      showCard('setup-step-2');
      setStepIndicator(2);
    }, 800);
  } catch (e) {
    showFeedback('upload-feedback', `Error: ${e.message}`, 'error');
    btn.disabled = false;
    btn.textContent = 'Upload & Continue';
  }
});

// ── Step 2: OAuth Authorization ───────────────────────────────────────────────

document.getElementById('btn-get-auth-url').addEventListener('click', async () => {
  const btn = document.getElementById('btn-get-auth-url');
  btn.disabled = true;
  btn.textContent = 'Generating…';
  try {
    const data = await api('GET', '/api/auth/url');
    if (data.authenticated) {
      showCard('setup-step-3');
      setStepIndicator(3);
      return;
    }
    document.getElementById('auth-url-link').href = data.auth_url;
    document.getElementById('auth-url-section').classList.remove('hidden');
  } catch (e) {
    alert(`Error: ${e.message}`);
  } finally {
    btn.disabled = false;
    btn.textContent = 'Generate Authorization URL';
  }
});

document.getElementById('btn-submit-callback').addEventListener('click', submitCallback);
document.getElementById('redirect-url-input').addEventListener('keydown', e => {
  if (e.key === 'Enter') submitCallback();
});

async function submitCallback() {
  const url = document.getElementById('redirect-url-input').value.trim();
  if (!url) return;
  const btn = document.getElementById('btn-submit-callback');
  btn.disabled = true;
  btn.textContent = 'Verifying…';
  hideFeedback('callback-feedback');
  try {
    await api('POST', '/api/auth/callback', { redirect_url: url });
    showFeedback('callback-feedback', '✅ Gmail authorized!', 'success');
    setTimeout(() => {
      showCard('setup-step-3');
      setStepIndicator(3);
    }, 800);
  } catch (e) {
    showFeedback('callback-feedback', `Error: ${e.message}`, 'error');
    btn.disabled = false;
    btn.textContent = 'Submit';
  }
}

// ── Step 3: API Key ───────────────────────────────────────────────────────────

document.getElementById('btn-save-api-key').addEventListener('click', saveApiKey);
document.getElementById('api-key-input').addEventListener('keydown', e => {
  if (e.key === 'Enter') saveApiKey();
});

async function saveApiKey() {
  const key = document.getElementById('api-key-input').value.trim();
  if (!key) return;
  const btn = document.getElementById('btn-save-api-key');
  btn.disabled = true;
  btn.textContent = 'Saving…';
  hideFeedback('api-key-feedback');
  try {
    await api('POST', '/api/settings/api-key', { api_key: key });
    showFeedback('api-key-feedback', '✅ API key saved!', 'success');
    setTimeout(() => {
      showCard('setup-done');
      [1, 2, 3].forEach(i =>
        document.getElementById(`step-indicator-${i}`).classList.add('done')
      );
    }, 600);
  } catch (e) {
    showFeedback('api-key-feedback', `Error: ${e.message}`, 'error');
    btn.disabled = false;
    btn.textContent = 'Save & Finish';
  }
}

document.getElementById('btn-go-inbox').addEventListener('click', showInbox);

// ── Inbox ─────────────────────────────────────────────────────────────────────

function showInbox() {
  show('view-inbox');
  loadEmails();
  startJobPolling();
}

async function loadEmails() {
  try {
    const emails = await api('GET', '/api/emails');
    renderEmails(emails);
    document.getElementById('email-count-title').textContent =
      `Processed Emails (${emails.length})`;
  } catch (e) {
    console.error('Failed to load emails:', e);
  }
}

function priorityBadge(priority) {
  if (!priority) return `<span class="email-badge badge-default">—</span>`;
  const cls =
    priority === 'High'   ? 'badge-high'   :
    priority === 'Medium' ? 'badge-medium' : 'badge-low';
  return `<span class="email-badge ${cls}">${escHtml(priority)}</span>`;
}

function renderEmails(emails) {
  const container = document.getElementById('email-list');
  if (!emails.length) {
    container.innerHTML = `
      <div class="empty-state">
        <p>No processed emails yet.<br>Use the sidebar to fetch and process.</p>
      </div>`;
    return;
  }
  container.innerHTML = emails.map((e, i) => `
    <div class="email-card" data-idx="${i}" onclick="this.classList.toggle('expanded')">
      <div class="email-card-header">
        <span class="email-subject">${escHtml(e.subject || '(no subject)')}</span>
        ${priorityBadge(e.priority)}
      </div>
      <div class="email-meta">
        From: ${escHtml(e.sender || '?')}
        &nbsp;·&nbsp; ${escHtml(e.category || 'General')}
        &nbsp;·&nbsp; ${escHtml(e.date || '')}
      </div>
      ${e.summary ? `<div class="email-summary">${escHtml(e.summary)}</div>` : ''}
      ${e.draft_response ? `<div class="email-draft">${escHtml(e.draft_response)}</div>` : ''}
    </div>
  `).join('');
}

// ── Job polling ───────────────────────────────────────────────────────────────

function startJobPolling() {
  if (_jobPollInterval) return;
  updateJobStatus();
  _jobPollInterval = setInterval(updateJobStatus, 3000);
}

async function updateJobStatus() {
  try {
    const jobs = await api('GET', '/api/jobs');
    const lines = [];
    if (jobs.fetch.running)        lines.push('⏳ Fetching emails…');
    else if (jobs.fetch.last)      lines.push(`Fetch: ${jobs.fetch.last}`);
    if (jobs.process.running)      lines.push('⏳ Processing with AI…');
    else if (jobs.process.last)    lines.push(`Process: ${jobs.process.last}`);

    // Auto-refresh list when a job just succeeded
    if (jobs.fetch.last === 'success' || jobs.process.last === 'success') {
      loadEmails();
    }
    document.getElementById('job-status').textContent = lines.join('\n');
  } catch (_) {}
}

document.getElementById('btn-fetch').addEventListener('click', async () => {
  const btn = document.getElementById('btn-fetch');
  btn.disabled = true;
  try {
    await api('POST', '/api/emails/fetch');
    updateJobStatus();
  } catch (e) {
    alert(`Error: ${e.message}`);
  } finally {
    btn.disabled = false;
  }
});

document.getElementById('btn-process').addEventListener('click', async () => {
  const btn = document.getElementById('btn-process');
  btn.disabled = true;
  try {
    await api('POST', '/api/emails/process');
    updateJobStatus();
  } catch (e) {
    alert(`Error: ${e.message}`);
  } finally {
    btn.disabled = false;
  }
});

document.getElementById('btn-refresh-list').addEventListener('click', loadEmails);

document.getElementById('btn-reset').addEventListener('click', async () => {
  if (!confirm('This will remove your Gmail credentials and token. Continue?')) return;
  try {
    await api('DELETE', '/api/auth/reset');
    clearInterval(_jobPollInterval);
    _jobPollInterval = null;
    init();
  } catch (e) {
    alert(`Error: ${e.message}`);
  }
});

// ── Boot ──────────────────────────────────────────────────────────────────────
document.addEventListener('DOMContentLoaded', init);
