const tabs = [...document.querySelectorAll('[role="tab"]')];
let previewController;
let scanController;
let scansAvailable = false;
let inputRevision = 0;
let gmailConnection;
let gmailSelection;
let gmailController;
let gmailListController;
let gmailStatusController;
let gmailEpoch = 0;
let gmailPages = [null];
let gmailPageIndex = 0;
let gmailMessageButtons = [];
let gmailDisconnecting = false;
let gmailRemovalPending = false;
let feedbackTarget;
let feedbackPending = false;
const savedFeedback = new Map();
let feedbackAfter = '';
const feedbackRecords = new Map();

function updateScanButton() {
  const gmailSelected = document.getElementById('tab-gmail').getAttribute('aria-selected') === 'true';
  const button = document.getElementById('scan');
  button.disabled = !scansAvailable || !!scanController || (gmailSelected && (!gmailConnection || !gmailSelection));
  button.setAttribute('aria-busy', String(!!scanController));
}

function assessmentState(state, announcement) {
  document.getElementById('assessment-section').dataset.state = state;
  document.getElementById('assessment-progress').textContent = announcement;
}

function clearAssessment(
  title = scansAvailable ? 'Ready to scan' : 'Setup required',
  message = scansAvailable ? 'Scan a message to see its assessment.' : 'Check local model setup before scanning.',
  state = scansAvailable ? 'ready' : 'setup_required',
) {
  scanController?.abort();
  scanController = undefined;
  feedbackTarget = undefined;
  document.getElementById('training-feedback').hidden = true;
  document.getElementById('feedback-retain').checked = false;
  document.getElementById('feedback-status').textContent = '';
  updateFeedbackButton();
  const result = document.getElementById('assessment-result');
  result.hidden = true;
  delete result.dataset.scanId;
  delete result.dataset.sourceFingerprint;
  ['result-status', 'result-score', 'result-indicators', 'result-warnings', 'result-coverage'].forEach((id) => {
    document.getElementById(id).textContent = '';
  });
  document.getElementById('assessment-empty').hidden = false;
  document.getElementById('assessment-state').textContent = title;
  document.getElementById('assessment-message').textContent = message;
  assessmentState(state, title);
  updateScanButton();
}

function renderAssessment(result) {
  if (typeof result.scan_id !== 'string' || !result.scan_id.length ||
      !/^[0-9a-f]{64}$/.test(result.source_fingerprint)) throw new Error('Invalid scan identity');
  const scored = result.status === 'complete' && result.score_kind === 'uncalibrated_score' &&
    Number.isInteger(result.score) && result.score >= 0 && result.score <= 100 &&
    !result.critical_content_missing && !result.is_test_double;
  const panel = document.getElementById('assessment-result');
  panel.dataset.scanId = result.scan_id;
  panel.dataset.sourceFingerprint = result.source_fingerprint;
  document.getElementById('result-status').textContent = result.is_test_double ?
    'TEST DOUBLE — simulated output only' : scored ? 'Experimental assessment' :
      result.status === 'failed' ? 'Assessment failed' : 'Needs review';
  document.getElementById('result-score').textContent = scored ?
    `Risk score: ${result.score}/100 — Uncalibrated model estimate` : 'No overall score available';
  const indicators = document.getElementById('result-indicators');
  indicators.textContent = '';
  document.getElementById('result-indicator-section').hidden = !scored || !result.indicators.length;
  if (scored) result.indicators.forEach((indicator) => addListText(indicators,
    `${indicator.description} Model estimate: ${Math.round(100 * indicator.estimate)}/100.`));
  const warnings = document.getElementById('result-warnings');
  warnings.textContent = '';
  result.warnings.forEach((warning) => addListText(warnings, warning));
  if (!result.warnings.length) addListText(warnings, 'No additional warnings reported.');
  document.getElementById('result-coverage').textContent = result.coverage_statement;
  document.getElementById('assessment-empty').hidden = true;
  panel.hidden = false;
  assessmentState(scored ? 'complete' : result.status === 'failed' ? 'failed' : 'needs_review',
    scored ? 'Assessment complete' : result.status === 'failed' ? 'Assessment failed' : 'Incomplete evidence — needs review');
}

function clearPreview() {
  inputRevision += 1;
  clearAssessment();
  previewController?.abort();
  previewController = undefined;
  document.getElementById('preview').disabled = false;
  document.getElementById('message-preview').hidden = true;
  ['preview-body', 'preview-sender', 'preview-subject', 'preview-status', 'preview-coverage',
    'preview-links', 'preview-warnings', 'action-message'].forEach((id) => {
    document.getElementById(id).textContent = '';
  });
}

function selectTab(tab, focus = false) {
  clearPreview();
  clearGmailSelection();
  gmailListController?.abort();
  gmailListController = undefined;
  updateGmailControls();
  tabs.forEach((item) => {
    const selected = item === tab;
    item.setAttribute('aria-selected', String(selected));
    item.tabIndex = selected ? 0 : -1;
    document.getElementById(item.getAttribute('aria-controls')).hidden = !selected;
  });
  updateScanButton();
  if (focus) tab.focus();
}

tabs.forEach((tab, index) => {
  tab.addEventListener('click', () => selectTab(tab));
  tab.addEventListener('keydown', (event) => {
    let target;
    if (event.key === 'ArrowRight') target = tabs[(index + 1) % tabs.length];
    if (event.key === 'ArrowLeft') target = tabs[(index + tabs.length - 1) % tabs.length];
    if (event.key === 'Home') target = tabs[0];
    if (event.key === 'End') target = tabs[tabs.length - 1];
    if (target) {
      event.preventDefault();
      selectTab(target, true);
    }
  });
});

document.querySelectorAll('[data-unavailable]').forEach((button) => {
  button.addEventListener('click', () => {
    document.getElementById('action-message').textContent = button.dataset.unavailable;
  });
});

async function refreshReadiness() {
  const wasAvailable = scansAvailable;
  const button = document.getElementById('refresh');
  button.disabled = true;
  const title = document.getElementById('setup-title');
  const message = document.getElementById('setup-message');
  try {
    const response = await fetch('/api/readiness', { cache: 'no-store', signal: AbortSignal.timeout(5000) });
    if (!response.ok) throw new Error('Readiness unavailable');
    const state = await response.json();
    scansAvailable = state.scans_available === true;
    title.textContent = state.is_test_double ? 'TEST DOUBLE — simulated output only' :
      state.model_loaded && state.status === 'ready' ? 'Local model ready' : 'Setup required';
    message.textContent = state.message;
    if (state.mode !== 'production') message.textContent += ` Mode: ${state.mode}.`;
    if (!scansAvailable) clearAssessment('Setup required', state.message, 'setup_required');
    else if (!wasAvailable) clearAssessment();
  } catch {
    scansAvailable = false;
    title.textContent = 'Server unavailable';
    message.textContent = 'Could not check the local server. Start the app and try again.';
    clearAssessment('Server unavailable', message.textContent, 'failed');
  } finally {
    button.disabled = false;
    updateScanButton();
  }
}

document.getElementById('refresh').addEventListener('click', refreshReadiness);
refreshReadiness();

document.getElementById('email-text').addEventListener('input', clearPreview);
document.getElementById('email-file').addEventListener('change', clearPreview);

function addListText(list, text) {
  const item = document.createElement('li');
  item.textContent = text;
  list.append(item);
}

document.getElementById('preview').addEventListener('click', async () => {
  clearPreview();
  const selected = tabs.find((tab) => tab.getAttribute('aria-selected') === 'true');
  const action = document.getElementById('action-message');
  let url;
  let body;
  let contentType;
  if (selected.id === 'tab-paste') {
    const text = document.getElementById('email-text').value;
    if (!text.trim()) { action.textContent = 'Paste a message first.'; return; }
    url = '/api/previews/paste';
    body = JSON.stringify({ text });
    contentType = 'application/json';
  } else if (selected.id === 'tab-import') {
    const file = document.getElementById('email-file').files[0];
    if (!file || !file.name.toLowerCase().endsWith('.eml')) {
      action.textContent = 'Choose an .eml file first.'; return;
    }
    url = '/api/previews/import';
    body = file;
    contentType = 'message/rfc822';
  } else {
    if (!gmailSelection) { action.textContent = 'Select a Gmail message first.'; return; }
    renderPreview(gmailSelection.preview);
    action.textContent = 'Selected Gmail message preview.';
    return;
  }
  const controller = new AbortController();
  previewController = controller;
  const timeout = setTimeout(() => controller.abort(), 20000);
  document.getElementById('preview').disabled = true;
  action.textContent = 'Extracting message evidence…';
  try {
    const response = await fetch(url, {
      method: 'POST', headers: { 'Content-Type': contentType, 'X-Email-Checker-Request': '1' },
      body, signal: controller.signal, cache: 'no-store',
    });
    const data = await response.json();
    if (previewController !== controller) return;
    if (!response.ok) throw new Error(data.message || 'Preview could not be completed.');
    renderPreview(data);
    action.textContent = 'Preview ready. No scam score was generated.';
  } catch (error) {
    if (previewController === controller) {
      action.textContent = controller.signal.aborted ? 'Preview timed out. Try again.' : error.message;
    }
  } finally {
    clearTimeout(timeout);
    if (previewController === controller) {
      document.getElementById('preview').disabled = false;
      previewController = undefined;
    }
  }
});

document.getElementById('scan').addEventListener('click', async () => {
  if (!scansAvailable || scanController) return;
  clearAssessment();
  const selected = tabs.find((tab) => tab.getAttribute('aria-selected') === 'true');
  let url;
  let body;
  let expectedFingerprint;
  let feedbackSource;
  const headers = { 'X-Email-Checker-Request': '1' };
  if (selected.id === 'tab-paste') {
    const text = document.getElementById('email-text').value;
    if (!text.trim()) { clearAssessment('Message needed', 'Paste a message first.'); return; }
    url = '/api/scans';
    headers['Content-Type'] = 'application/json';
    body = JSON.stringify({ text });
    feedbackSource = { url: '/api/previews/paste', body, contentType: 'application/json' };
  } else if (selected.id === 'tab-import') {
    const file = document.getElementById('email-file').files[0];
    if (!file || !file.name.toLowerCase().endsWith('.eml')) {
      clearAssessment('Message needed', 'Choose an .eml file first.'); return;
    }
    url = '/api/scans/import';
    body = new FormData();
    body.append('file', file);
    feedbackSource = { url: '/api/previews/import', body: file, contentType: 'message/rfc822' };
  } else {
    if (!gmailConnection || !gmailSelection) {
      clearAssessment('Message needed', 'Connect Gmail and select a message first.'); return;
    }
    url = '/api/scans';
    headers['Content-Type'] = 'application/json';
    body = JSON.stringify({ source: 'gmail', source_message_id: gmailSelection.id,
      account_scope: gmailConnection.account_scope });
    expectedFingerprint = gmailSelection.preview.evidence.fingerprint;
    feedbackSource = { evidence: gmailSelection.preview.evidence };
  }
  clearAssessment('Scan queued or running', 'The local model is checking this message.', 'running');
  const controller = new AbortController();
  const revision = inputRevision;
  scanController = controller;
  updateScanButton();
  const timeout = setTimeout(() => {
    if (scanController === controller) clearAssessment('Assessment failed', 'The scan timed out. Try again shortly.', 'failed');
  }, 150000);
  try {
    const response = await fetch(url, {
      method: 'POST', headers, body, signal: controller.signal, cache: 'no-store',
    });
    const result = await response.json();
    if (scanController !== controller || revision !== inputRevision) return;
    if (!response.ok) {
      clearAssessment('Assessment failed', result.retryable ?
        'The scan could not finish. Try again shortly.' : 'The scan could not finish. Check input and local model setup.', 'failed');
      return;
    }
    if (expectedFingerprint && result.source_fingerprint !== expectedFingerprint) {
      clearGmailSelection();
      clearAssessment('Message changed', 'Select the Gmail message again before scanning.', 'needs_review');
      return;
    }
    renderAssessment(result);
    if (!result.is_test_double && result.status !== 'failed') {
      feedbackTarget = { scanId: result.scan_id, fingerprint: result.source_fingerprint, source: feedbackSource, submitted: false };
      document.getElementById('training-feedback').hidden = false;
      updateFeedbackButton();
    }
  } catch {
    if (scanController === controller) clearAssessment('Assessment failed', 'The local scan could not finish. Check the server and try again.', 'failed');
  } finally {
    clearTimeout(timeout);
    if (scanController === controller) {
      scanController = undefined;
      updateScanButton();
    }
  }
});

function updateFeedbackButton() {
  document.getElementById('feedback-submit').disabled = !feedbackTarget || feedbackTarget.submitted || feedbackPending || !document.getElementById('feedback-retain').checked;
  document.getElementById('feedback-submit').setAttribute('aria-busy', String(feedbackPending));
}

document.getElementById('feedback-retain').addEventListener('change', updateFeedbackButton);

function renderSavedFeedback() {
  const list = document.getElementById('feedback-records');
  list.textContent = '';
  for (const [id, deleting] of savedFeedback) {
    const item = document.createElement('li');
    const description = document.createElement('p');
    const record = feedbackRecords.get(id);
    description.textContent = record ? `${record.label} report · ${record.created_at} · ${id.slice(0, 8)}` : `Malicious report · ${id.slice(0, 8)}`;
    const remove = document.createElement('button');
    remove.type = 'button';
    remove.textContent = deleting ? 'Deleting…' : 'Delete saved example';
    remove.disabled = deleting;
    remove.addEventListener('click', () => deleteSavedFeedback(id));
    item.append(description, remove);
    list.append(item);
  }
}

document.getElementById('feedback-load').addEventListener('click', async () => {
  const button = document.getElementById('feedback-load');
  if (button.disabled) return;
  button.disabled = true;
  const status = document.getElementById('feedback-list-status');
  status.textContent = 'Loading saved examples…';
  try {
    const query = new URLSearchParams({ include_content: 'false', limit: '25', after: feedbackAfter });
    const response = await fetch(`/api/feedback/export?${query}`, {
      headers: { 'X-Email-Checker-Request': '1' }, cache: 'no-store', signal: AbortSignal.timeout(20000),
    });
    if (!response.ok) throw new Error('List failed');
    const data = await response.json();
    if (!Array.isArray(data.records) || (data.next_after !== null && !/^[0-9a-f-]{36}$/.test(data.next_after))) throw new Error('Invalid list');
    for (const record of data.records) {
      if (!/^[0-9a-f-]{36}$/.test(record.feedback_id)) throw new Error('Invalid record');
      if (!savedFeedback.has(record.feedback_id)) savedFeedback.set(record.feedback_id, false);
      feedbackRecords.set(record.feedback_id, { label: record.label, created_at: record.created_at });
    }
    feedbackAfter = data.next_after || '';
    button.textContent = data.next_after ? 'Load more examples' : 'Refresh saved examples';
    status.textContent = data.next_after ? 'More saved examples are available.' : 'Saved examples loaded. Email content was not fetched.';
    renderSavedFeedback();
  } catch {
    status.textContent = 'Could not load saved examples. Try again.';
  } finally {
    button.disabled = false;
  }
});

async function deleteSavedFeedback(id) {
  if (!savedFeedback.has(id) || savedFeedback.get(id)) return;
  savedFeedback.set(id, true);
  renderSavedFeedback();
  const status = document.getElementById('feedback-delete-status');
  status.textContent = 'Deleting saved example…';
  try {
    const response = await fetch(`/api/feedback/${id}`, {
      method: 'DELETE', headers: { 'X-Email-Checker-Request': '1' },
      cache: 'no-store', signal: AbortSignal.timeout(20000),
    });
    if (!response.ok && response.status !== 404) throw new Error('Delete failed');
    savedFeedback.delete(id);
    feedbackRecords.delete(id);
    status.textContent = 'Saved example deleted.';
  } catch {
    savedFeedback.set(id, false);
    status.textContent = 'Could not delete the saved example. Try again.';
  } finally {
    renderSavedFeedback();
  }
}

document.getElementById('feedback-submit').addEventListener('click', async () => {
  const target = feedbackTarget;
  if (!target || target.submitted || feedbackPending || !document.getElementById('feedback-retain').checked) return;
  const status = document.getElementById('feedback-status');
  feedbackPending = true;
  updateFeedbackButton();
  status.textContent = 'Preparing your example…';
  try {
    let evidence = target.source.evidence;
    if (!evidence) {
      const response = await fetch(target.source.url, {
        method: 'POST', body: target.source.body,
        headers: { 'Content-Type': target.source.contentType, 'X-Email-Checker-Request': '1' },
        cache: 'no-store', signal: AbortSignal.timeout(20000),
      });
      if (!response.ok) throw new Error('Preview failed');
      evidence = (await response.json()).evidence;
    }
    if (feedbackTarget !== target || !document.getElementById('feedback-retain').checked) return;
    if (evidence.fingerprint !== target.fingerprint) throw new Error('Message changed');
    status.textContent = 'Saving your malicious example locally…';
    const response = await fetch('/api/feedback', {
      method: 'POST', headers: { 'Content-Type': 'application/json', 'X-Email-Checker-Request': '1' },
      body: JSON.stringify({ scan_id: target.scanId, label: 'scam', reviewed: false, retain_content: true, evidence }),
      cache: 'no-store', signal: AbortSignal.timeout(20000),
    });
    if (!response.ok) throw new Error('Feedback failed');
    const saved = await response.json();
    if (!/^[0-9a-f-]{36}$/.test(saved.feedback_id) || saved.content_retained !== true || saved.reviewed !== false) throw new Error('Invalid feedback confirmation');
    savedFeedback.set(saved.feedback_id, false);
    target.submitted = true;
    renderSavedFeedback();
    if (feedbackTarget === target) status.textContent = 'Saved locally as a suggested malicious example. It needs verification before a future training run.';
  } catch {
    if (feedbackTarget === target) status.textContent = 'Could not confirm the save. Load saved examples to check before submitting again.';
  } finally {
    feedbackPending = false;
    updateFeedbackButton();
  }
});

function renderPreview(data) {
  const evidence = data.evidence;
  document.getElementById('preview-sender').textContent = evidence.sender || 'Not provided';
  document.getElementById('preview-subject').textContent = evidence.subject || 'Not provided';
  document.getElementById('preview-body').textContent = evidence.body_text || 'No readable body extracted.';
  document.getElementById('preview-status').textContent = {
    complete: 'Extraction complete', needs_review: 'Incomplete evidence — needs review',
    failed: 'Extraction failed — no assessment is available',
  }[data.status];
  const links = document.getElementById('preview-links');
  evidence.links.forEach((link) => addListText(links,
    `${link.displayed_text || '(no link text)'} → ${link.destination} [${link.hostname || 'unresolved hostname'}]`));
  if (!evidence.links.length) addListText(links, 'No destinations extracted.');
  const warnings = document.getElementById('preview-warnings');
  evidence.warnings.forEach((warning) => addListText(warnings, warning));
  if (evidence.missing_fields.length) addListText(warnings, `Missing fields: ${evidence.missing_fields.join(', ')}.`);
  document.getElementById('preview-coverage').textContent = data.coverage_statement;
  document.getElementById('message-preview').hidden = false;
}

function clearGmailSelection() {
  gmailController?.abort();
  gmailController = undefined;
  gmailSelection = undefined;
  gmailMessageButtons.forEach((button) => button.setAttribute('aria-pressed', 'false'));
  document.getElementById('gmail-selected').textContent = 'Select a message to preview and scan.';
  updateScanButton();
}

function updateGmailControls() {
  document.getElementById('gmail-connect').disabled = !!gmailConnection || gmailDisconnecting || gmailRemovalPending;
  document.getElementById('gmail-cancel').disabled = !!gmailConnection || gmailDisconnecting;
  document.getElementById('gmail-disconnect').disabled = (!gmailConnection && !gmailRemovalPending) || gmailDisconnecting;
  document.getElementById('gmail-refresh').disabled = !gmailConnection || !!gmailListController;
  document.getElementById('gmail-previous').disabled = !gmailConnection || !!gmailListController || gmailPageIndex === 0;
  document.getElementById('gmail-next').disabled = !gmailConnection || !!gmailListController || !gmailPages[gmailPageIndex + 1];
}

async function refreshGmailStatus() {
  gmailStatusController?.abort();
  const controller = new AbortController();
  const epoch = gmailEpoch;
  gmailStatusController = controller;
  try {
    const response = await fetch('/api/auth/gmail/status', { cache: 'no-store', signal: controller.signal });
    const data = await response.json();
    if (gmailStatusController !== controller || epoch !== gmailEpoch) return;
    if (!response.ok) throw new Error('Could not check Gmail. Reconnect or check setup.');
    const connection = data.connected ? { account_scope: data.account_scope } : undefined;
    if (gmailConnection?.account_scope !== connection?.account_scope) {
      gmailEpoch += 1;
      clearGmailSelection();
      if (document.getElementById('tab-gmail').getAttribute('aria-selected') === 'true') clearPreview();
      document.getElementById('gmail-messages').textContent = '';
      gmailMessageButtons = [];
    }
    gmailConnection = connection;
    document.getElementById('gmail-state').textContent = connection ?
      'Gmail connected — read-only. Refresh the list to choose a message.' :
      data.code === 'gmail_setup_required' ? 'Gmail setup required. See the local setup guide.' : 'No Gmail account connected.';
  } catch (error) {
    if (gmailStatusController === controller && !controller.signal.aborted) {
      gmailEpoch += 1;
      gmailConnection = undefined;
      clearGmailSelection();
      gmailListController?.abort();
      gmailListController = undefined;
      if (document.getElementById('tab-gmail').getAttribute('aria-selected') === 'true') clearPreview();
      document.getElementById('gmail-messages').textContent = '';
      gmailMessageButtons = [];
      document.getElementById('gmail-state').textContent = error.message;
    }
  } finally {
    if (gmailStatusController === controller) gmailStatusController = undefined;
    updateGmailControls();
    updateScanButton();
  }
}

async function loadGmailPage(index = 0, refresh = false) {
  if (!gmailConnection) return;
  gmailListController?.abort();
  clearPreview();
  clearGmailSelection();
  if (refresh) { gmailPages = [null]; gmailPageIndex = 0; }
  const controller = new AbortController();
  const epoch = gmailEpoch;
  const scope = gmailConnection.account_scope;
  gmailListController = controller;
  document.getElementById('gmail-messages').textContent = '';
  gmailMessageButtons = [];
  document.getElementById('gmail-state').textContent = 'Loading recent messages…';
  updateGmailControls();
  const parameters = new URLSearchParams({ account_scope: scope });
  if (gmailPages[index]) parameters.set('page_token', gmailPages[index]);
  try {
    const response = await fetch(`/api/messages?${parameters}`, { cache: 'no-store', signal: controller.signal });
    const data = await response.json();
    if (gmailListController !== controller || epoch !== gmailEpoch) return;
    if (!response.ok) throw new Error('Could not load Gmail messages. Refresh the connection and try again.');
    if (data.account_scope !== scope) throw new Error('Gmail connection changed. Refresh the connection.');
    gmailPageIndex = index;
    gmailPages[index + 1] = data.next_page_token;
    gmailPages.length = index + 2;
    const list = document.getElementById('gmail-messages');
    data.messages.forEach((message) => {
      const item = document.createElement('li');
      const button = document.createElement('button');
      button.type = 'button';
      button.setAttribute('aria-pressed', 'false');
      button.textContent = `${message.subject} — ${message.sender} · ${message.date}`;
      button.addEventListener('click', () => selectGmailMessage(message.id, button));
      gmailMessageButtons.push(button);
      item.append(button);
      list.append(item);
    });
    document.getElementById('gmail-state').textContent = data.messages.length ?
      `Page ${index + 1} · ${data.messages.length} messages. Select one to preview.` : 'No messages on this page.';
  } catch (error) {
    if (gmailListController === controller && !controller.signal.aborted) document.getElementById('gmail-state').textContent = error.message;
  } finally {
    if (gmailListController === controller) gmailListController = undefined;
    updateGmailControls();
  }
}

async function selectGmailMessage(id, button) {
  if (!gmailConnection) return;
  clearPreview();
  clearGmailSelection();
  const controller = new AbortController();
  const epoch = gmailEpoch;
  const scope = gmailConnection.account_scope;
  gmailController = controller;
  document.getElementById('gmail-selected').textContent = 'Retrieving the selected message…';
  try {
    const response = await fetch(`/api/messages/${encodeURIComponent(id)}?account_scope=${encodeURIComponent(scope)}`, {
      cache: 'no-store', signal: controller.signal,
    });
    const data = await response.json();
    if (gmailController !== controller || epoch !== gmailEpoch) return;
    if (!response.ok) throw new Error('Could not retrieve this message. Select it again or refresh the list.');
    if (data.evidence.account_scope !== scope || data.evidence.source_message_id !== id) throw new Error('The Gmail message selection changed.');
    gmailSelection = { id, preview: data };
    button.setAttribute('aria-pressed', 'true');
    renderPreview(data);
    document.getElementById('gmail-selected').textContent = 'Selected message ready. Scan email to assess it locally.';
  } catch (error) {
    if (gmailController === controller && !controller.signal.aborted) document.getElementById('gmail-selected').textContent = error.message;
  } finally {
    if (gmailController === controller) gmailController = undefined;
    updateScanButton();
  }
}

document.getElementById('gmail-connect').addEventListener('click', async () => {
  const button = document.getElementById('gmail-connect');
  button.disabled = true;
  try {
    const response = await fetch('/api/auth/gmail/start', {
      method: 'POST', headers: { 'X-Email-Checker-Request': '1' }, cache: 'no-store',
    });
    const data = await response.json();
    if (!response.ok) throw new Error('Could not start Gmail connection. Check the setup guide.');
    const url = new URL(data.authorization_url);
    if (url.protocol !== 'https:' || url.hostname !== 'accounts.google.com' || url.username || url.password) throw new Error('Invalid Google authorization destination.');
    window.location.assign(url.href);
  } catch (error) {
    document.getElementById('gmail-state').textContent = error.message;
    updateGmailControls();
  }
});

document.getElementById('gmail-cancel').addEventListener('click', async () => {
  try {
    const response = await fetch('/api/auth/gmail/cancel', {
      method: 'POST', headers: { 'X-Email-Checker-Request': '1' }, cache: 'no-store',
    });
    if (!response.ok) throw new Error('Could not cancel the connection request.');
    await refreshGmailStatus();
  } catch (error) {
    document.getElementById('gmail-state').textContent = error.message;
  }
});

document.getElementById('gmail-refresh').addEventListener('click', async () => {
  await refreshGmailStatus();
  if (gmailConnection) await loadGmailPage(0, true);
});
document.getElementById('gmail-next').addEventListener('click', () => loadGmailPage(gmailPageIndex + 1));
document.getElementById('gmail-previous').addEventListener('click', () => loadGmailPage(gmailPageIndex - 1));
refreshGmailStatus();

document.getElementById('gmail-disconnect').addEventListener('click', async () => {
  gmailEpoch += 1;
  gmailDisconnecting = true;
  gmailRemovalPending = true;
  gmailStatusController?.abort();
  gmailStatusController = undefined;
  gmailListController?.abort();
  gmailListController = undefined;
  clearGmailSelection();
  clearPreview();
  gmailConnection = undefined;
  gmailPages = [null];
  gmailPageIndex = 0;
  gmailMessageButtons = [];
  document.getElementById('gmail-messages').textContent = '';
  document.getElementById('gmail-state').textContent = 'Disconnecting Gmail…';
  updateGmailControls();
  try {
    const response = await fetch('/api/auth/gmail/disconnect', {
      method: 'POST', headers: { 'X-Email-Checker-Request': '1' }, cache: 'no-store',
    });
    const data = await response.json();
    if (!response.ok || data.disconnected !== true) throw new Error('Could not confirm local credential removal. Try Disconnect again.');
    gmailRemovalPending = false;
    document.getElementById('gmail-state').textContent = data.revocation_failed ?
      'Disconnected locally. Google revocation could not be confirmed; you can remove access in your Google account.' :
      'Gmail disconnected. Local credentials and cached assessments cleared.';
  } catch (error) {
    document.getElementById('gmail-state').textContent = error.message;
  } finally {
    gmailDisconnecting = false;
    updateGmailControls();
    updateScanButton();
  }
});
