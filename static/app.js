/* ============================================================
   KIMAKAai Email Handler — Frontend Logic
   ============================================================ */

// ── State ────────────────────────────────────────────────────────────────────
let _jobPollInterval = null;
let _selectedEmail = null;

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
    renderEmailList(emails);
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

function renderEmailList(emails) {
  const container = document.getElementById('email-list');
  if (!emails.length) {
    container.innerHTML = `
      <div class="empty-state">
        <p>No processed emails yet.<br>Use the sidebar to fetch and process.</p>
      </div>`;
    _selectedEmail = null;
    document.getElementById('email-detail').innerHTML = `
      <div class="detail-empty">
        <span class="detail-empty-icon">📬</span>
        <p>Select an email to view details</p>
      </div>`;
    return;
  }

  container.innerHTML = emails.map((e, i) => {
    const es = e.executive_summary || {};
    const priority = es.priority || e.priority || null;
    const oneLiner = es.one_liner || e.subject || '(no subject)';
    const sender = e.sender || '?';
    const category = e.category || 'General';
    return `
      <div class="email-row" data-idx="${i}" onclick="selectEmail(${i})">
        <div class="row-top">
          <span class="row-subject">${escHtml(oneLiner)}</span>
          ${priorityBadge(priority)}
        </div>
        <div class="row-meta">${escHtml(sender)} · ${escHtml(category)}</div>
      </div>`;
  }).join('');

  // Keep selection in sync after list refresh
  if (_selectedEmail) {
    const idx = emails.findIndex(e => e.gmail_id === _selectedEmail.gmail_id);
    if (idx >= 0) {
      container.querySelectorAll('.email-row')[idx].classList.add('selected');
      renderDetailPanel(emails[idx]);
    }
  }

  window._emailsCache = emails;
}

function selectEmail(idx) {
  _selectedEmail = window._emailsCache[idx];
  document.querySelectorAll('.email-row').forEach((r, i) => {
    r.classList.toggle('selected', i === idx);
  });
  renderDetailPanel(_selectedEmail);
}

function renderDetailPanel(email) {
  const es = email.executive_summary || {};
  const ai = email.action_items || {};
  const draft = email.draft_options || {};
  const tasks = ai.tasks || [];
  const owner = ai.owner || 'user';
  const priority = es.priority || email.priority || 'Medium';
  const sentiment = (es.sentiment || '').replace(/\s+/g, '');

  const passiveBanner = email.is_passive_participation
    ? `<div class="passive-banner">👁 You are CC'd — no action required from you</div>`
    : '';

  const keyPoints = (es.key_points || []).map(p =>
    `<li>${escHtml(p)}</li>`).join('');

  const taskItems = tasks.length
    ? tasks.map(t => `
        <li class="task-item">
          <span class="task-bullet"></span>
          <span class="task-text">${escHtml(t.task)}</span>
          ${t.due_date ? `<span class="task-due">${escHtml(t.due_date)}</span>` : ''}
        </li>`).join('')
    : `<li class="task-item"><span class="task-text" style="color:var(--text-muted)">No action items</span></li>`;

  const hasProfessional = !!draft.professional;
  const hasBrief        = !!draft.brief;
  const hasScheduler    = !!draft.scheduler;
  const defaultDraft    = draft.professional || draft.brief || draft.scheduler || '';

  const detailHtml = `
    <div class="detail-header">
      <h2>${escHtml(email.subject || '(no subject)')}</h2>
      <div class="detail-meta">
        <span>From: ${escHtml(email.sender || '?')}</span>
        <span>${escHtml(email.date || '')}</span>
        ${priorityBadge(priority)}
        <span class="sentiment-badge sentiment-${escHtml(sentiment)}">${escHtml(es.sentiment || '—')}</span>
      </div>
    </div>

    ${passiveBanner}

    <div class="detail-card" id="card-exec">
      <div class="detail-card-title">📋 Executive Summary</div>
      <div class="exec-one-liner">${escHtml(es.one_liner || '—')}</div>
      <ul class="exec-key-points">${keyPoints}</ul>
    </div>

    <div class="detail-card" id="card-actions">
      <div class="detail-card-title">✅ Action Items</div>
      <ul class="task-list">${taskItems}</ul>
      <div class="owner-chip">Owner: ${escHtml(owner)}</div>
    </div>

    <div class="detail-card" id="card-drafts">
      <div class="detail-card-title">✍ Draft Options</div>
      <div class="draft-tabs">
        <button class="draft-tab active" id="tab-professional"
          onclick="switchDraft('professional')" ${hasProfessional ? '' : 'disabled'}>Professional</button>
        <button class="draft-tab" id="tab-brief"
          onclick="switchDraft('brief')" ${hasBrief ? '' : 'disabled'}>Brief</button>
        <button class="draft-tab" id="tab-scheduler"
          onclick="switchDraft('scheduler')" ${hasScheduler ? '' : 'disabled'}>Scheduler</button>
      </div>
      <textarea class="draft-textarea" id="draft-textarea" spellcheck="true">${escHtml(defaultDraft)}</textarea>
      <button class="copy-btn" onclick="copyDraft()">📋 Copy draft</button>
    </div>
  `;

  document.getElementById('email-detail').innerHTML = detailHtml;
  window._currentDrafts = {
    professional: draft.professional || '',
    brief: draft.brief || '',
    scheduler: draft.scheduler || '',
  };
}

function switchDraft(key) {
  const text = (window._currentDrafts || {})[key] || '';
  document.getElementById('draft-textarea').value = text;
  document.querySelectorAll('.draft-tab').forEach(btn => {
    btn.classList.toggle('active', btn.id === `tab-${key}`);
  });
}

function copyDraft() {
  const text = document.getElementById('draft-textarea').value;
  navigator.clipboard.writeText(text).then(() => {
    const btn = document.querySelector('.copy-btn');
    const orig = btn.textContent;
    btn.textContent = '✅ Copied!';
    setTimeout(() => { btn.textContent = orig; }, 1500);
  }).catch(() => alert('Copy failed — please select and copy manually.'));
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
    const parts = [];

    if (jobs.fetch.running) {
      parts.push('<span>⏳ Fetching emails…</span>');
    } else if (jobs.fetch.last) {
      if (jobs.fetch.last.startsWith('error:')) {
        parts.push(`<span class="job-error">❌ Fetch failed: ${escHtml(jobs.fetch.last.replace('error:', '').trim())}</span>`);
      } else {
        parts.push(`<span>Fetch: ${escHtml(jobs.fetch.last)}</span>`);
      }
    }

    if (jobs.process.running) {
      parts.push('<span>⏳ Processing with AI…</span>');
    } else if (jobs.process.last) {
      if (jobs.process.last.startsWith('error:')) {
        const msg = jobs.process.last.replace('error:', '').trim();
        parts.push(`<span class="job-error">❌ ${escHtml(msg)}</span>`);
      } else {
        parts.push(`<span>Process: ${escHtml(jobs.process.last)}</span>`);
      }
    }

    document.getElementById('job-status').innerHTML = parts.join('\n');

    // Auto-refresh list when a job just succeeded
    if (jobs.fetch.last === 'success' || jobs.process.last === 'success') {
      loadEmails();
    }
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

document.getElementById('btn-demo').addEventListener('click', async () => {
  try {
    const r = await api('POST', '/api/emails/demo');
    await loadEmails();
    // Select the first demo email automatically
    if (window._emailsCache && window._emailsCache.length > 0) {
      selectEmail(0);
    }
  } catch (e) {
    alert(`Error loading demo: ${e.message}`);
  }
});

document.getElementById('btn-clear').addEventListener('click', async () => {
  if (!confirm('Clear all processed emails? Raw emails are kept — you can reprocess anytime.')) return;
  try {
    await api('DELETE', '/api/emails/clear');
    await loadEmails();
  } catch (e) {
    alert(`Error: ${e.message}`);
  }
});

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
