const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const { test } = require('node:test');
const { File } = require('node:buffer');

const root = path.resolve(__dirname, '../..');
const html = fs.readFileSync(path.join(root, 'src/bad_email_check/static/index.html'), 'utf8');
const source = fs.readFileSync(path.join(root, 'src/bad_email_check/static/app.js'), 'utf8');
const disclosure = 'Linked websites and attachments were not inspected.';

class Element {
  constructor(attributes = {}) {
    this.attributes = attributes;
    this.id = attributes.id;
    this.hidden = Object.hasOwn(attributes, 'hidden');
    this.disabled = Object.hasOwn(attributes, 'disabled');
    this.dataset = {};
    this.children = [];
    this.listeners = {};
    this.value = '';
    this.files = [];
    this.text = '';
  }
  get textContent() { return this.text + this.children.map((item) => item.textContent).join(' '); }
  set textContent(value) { this.text = String(value); this.children = []; }
  append(...items) { this.children.push(...items); }
  getAttribute(name) { return this.attributes[name]; }
  setAttribute(name, value) { this.attributes[name] = value; }
  addEventListener(name, callback) { this.listeners[name] = callback; }
  focus() { this.focused = true; }
}

async function createUI(options = {}) {
  const elements = new Map();
  for (const match of html.matchAll(/<[a-z][^>]*\sid="[^"]+"[^>]*>/g)) {
    const attrs = Object.fromEntries([...match[0].matchAll(/([\w-]+)="([^"]*)"/g)].map((item) => [item[1], item[2]]));
    if (/\shidden[\s>]/.test(match[0])) attrs.hidden = '';
    if (/\sdisabled[\s>]/.test(match[0])) attrs.disabled = '';
    elements.set(attrs.id, new Element(attrs));
  }
  const created = [];
  const tabs = [...elements.values()].filter((item) => item.attributes.role === 'tab');
  const requests = [];
  const readiness = { available: true, fail: false, ...options.readiness };
  const gmailStatus = { connected: false, code: 'gmail_setup_required', ...options.gmailStatus };
  const timers = new Map();
  let timerId = 0;
  const context = vm.createContext({
    document: {
      getElementById: (id) => assert.ok(elements.has(id), id) || elements.get(id),
      querySelectorAll: (selector) => selector === '[role="tab"]' ? tabs : [],
      createElement: (tag) => { created.push(tag); return new Element(); },
    },
    AbortController, AbortSignal, FormData, URL, URLSearchParams,
    window: { location: { assign: (url) => { context.destination = url; } } },
    setTimeout: options.fakeTimers ? (callback, delay) => { timers.set(++timerId, { callback, delay }); return timerId; } : setTimeout,
    clearTimeout: options.fakeTimers ? (id) => timers.delete(id) : clearTimeout,
    fetch: async (url, options) => {
      if (url === '/api/auth/gmail/status') {
        if (gmailStatus.fail === 'network') throw new Error('Synthetic network failure');
        return { ok: gmailStatus.fail !== 'http', json: async () => ({ ...gmailStatus }) };
      }
      if (url === '/api/readiness') {
        if (readiness.fail) throw new Error('Synthetic connection failure');
        return { ok: true, json: async () => ({ scans_available: readiness.available, model_loaded: readiness.available, status: readiness.available ? 'ready' : 'setup_required', mode: 'test', message: 'Fixture setup' }) };
      }
      return new Promise((resolve, reject) => requests.push({ url, options, resolve, reject }));
    },
  });
  vm.runInContext(source, context);
  await new Promise(setImmediate);
  return { elements, created, context, requests, readiness, gmailStatus, timers, render: (result) => context.renderAssessment(result) };
}

function result(overrides = {}) {
  return {
    scan_id: 'synthetic-scan', source_fingerprint: 'a'.repeat(64), status: 'complete',
    score: 82, score_kind: 'uncalibrated_score', risk_label: null, is_test_double: false,
    critical_content_missing: false,
    indicators: [{ description: 'Possible credential solicitation.', estimate: 0.7 }],
    warnings: ['Authentication claims were not independently verified.'],
    coverage_statement: 'Complete model input checked.', ...overrides,
  };
}

function visibleResultText(ui) {
  return ['result-status', 'result-score', 'result-indicators', 'result-warnings', 'result-coverage']
    .map((id) => ui.elements.get(id).textContent).join(' ');
}

test('complete panel shows explicit uncalibrated score, signals, warnings and coverage', async () => {
  const ui = await createUI();
  ui.render(result());
  assert.equal(ui.elements.get('assessment-result').hidden, false);
  assert.equal(ui.elements.get('assessment-empty').hidden, true);
  assert.equal(ui.elements.get('result-status').textContent, 'Experimental assessment');
  assert.equal(ui.elements.get('result-score').textContent, 'Risk score: 82/100 \u2014 Uncalibrated model estimate');
  assert.match(visibleResultText(ui), /Possible credential solicitation.*70\/100/);
  assert.match(visibleResultText(ui), /not independently verified/);
  assert.match(visibleResultText(ui), /Complete model input checked/);
  assert.equal(ui.elements.get('assessment-result').dataset.scanId, 'synthetic-scan');
  assert.equal(ui.elements.get('assessment-result').dataset.sourceFingerprint, 'a'.repeat(64));
});

test('all display states retain static disclosure and omit prohibited reassurance', async () => {
  const ui = await createUI();
  assert.ok(html.includes(`<p class="disclosure">${disclosure}</p>`));
  assert.ok(!/\bsafe\b|guaranteed legitimate/i.test(html));
  for (const status of ['complete', 'needs_review', 'failed']) {
    ui.render(result({ status, score: status === 'complete' ? 0 : null, score_kind: status === 'complete' ? 'uncalibrated_score' : 'unavailable' }));
    assert.ok(!/\bsafe\b|guaranteed legitimate/i.test(visibleResultText(ui)));
    if (status !== 'complete') {
      assert.equal(ui.elements.get('result-score').textContent, 'No overall score available');
      assert.equal(ui.elements.get('result-indicator-section').hidden, true);
    }
  }
  ui.context.clearAssessment();
  assert.equal(ui.elements.get('assessment-result').hidden, true);
  assert.equal(ui.elements.get('result-score').textContent, '');
});

test('fixture, critical missing content and unsupported score kinds cannot display a score', async () => {
  const ui = await createUI();
  for (const changes of [{ is_test_double: true }, { critical_content_missing: true }, { score_kind: 'calibrated_probability' }, { score: 101 }, { score: null }]) {
    ui.render(result(changes));
    assert.equal(ui.elements.get('result-score').textContent, 'No overall score available');
    assert.equal(ui.elements.get('result-indicators').textContent, '');
  }
  ui.render(result({ is_test_double: true }));
  assert.match(ui.elements.get('result-status').textContent, /TEST DOUBLE/);
});

test('untrusted result text remains literal and replacement clears prior warnings', async () => {
  const ui = await createUI();
  const literal = '<img src="https://example.invalid/pixel" onerror="alert(1)">';
  ui.render(result({ warnings: [literal], coverage_statement: literal, indicators: [{ description: literal, estimate: 0.1 }] }));
  assert.ok(visibleResultText(ui).includes(literal));
  assert.ok(ui.created.every((tag) => tag === 'li'));
  ui.render(result({ warnings: [], indicators: [] }));
  assert.equal(ui.elements.get('result-warnings').textContent, 'No additional warnings reported.');
  assert.equal(ui.elements.get('result-indicator-section').hidden, true);
  assert.ok(!visibleResultText(ui).includes(literal));
});

test('paste scan uses local API and input edits invalidate pending results', async () => {
  const ui = await createUI();
  ui.elements.get('email-text').value = 'Synthetic email';
  const pending = ui.elements.get('scan').listeners.click();
  assert.equal(ui.requests[0].url, '/api/scans');
  assert.equal(JSON.parse(ui.requests[0].options.body).text, 'Synthetic email');
  assert.equal(ui.elements.get('scan').disabled, true);
  ui.elements.get('email-text').listeners.input();
  assert.ok(ui.requests[0].options.signal.aborted);
  ui.requests[0].resolve({ ok: true, json: async () => result() });
  await pending;
  assert.equal(ui.elements.get('assessment-result').hidden, true);
});

test('successful scan and subsequent API failure clear old score', async () => {
  const ui = await createUI();
  ui.elements.get('email-text').value = 'Synthetic email';
  let pending = ui.elements.get('scan').listeners.click();
  ui.requests[0].resolve({ ok: true, json: async () => result() });
  await pending;
  assert.match(ui.elements.get('result-score').textContent, /82\/100/);
  pending = ui.elements.get('scan').listeners.click();
  assert.equal(ui.elements.get('result-score').textContent, '');
  ui.requests[1].resolve({ ok: false, json: async () => ({ retryable: true }) });
  await pending;
  assert.equal(ui.elements.get('assessment-state').textContent, 'Assessment failed');
  assert.equal(ui.elements.get('assessment-result').hidden, true);
});

test('import scan sends a named multipart file and renders the returned assessment', async () => {
  const ui = await createUI();
  ui.context.selectTab(ui.elements.get('tab-import'));
  ui.elements.get('email-file').files = [new File(['Subject: Example\n\nSynthetic body'], 'example.eml', { type: 'message/rfc822' })];
  const pending = ui.elements.get('scan').listeners.click();
  const request = ui.requests[0];
  assert.equal(request.url, '/api/scans/import');
  assert.equal(request.options.body.get('file').name, 'example.eml');
  assert.equal(request.options.headers['Content-Type'], undefined);
  assert.equal(request.options.headers['X-Email-Checker-Request'], '1');
  request.resolve({ ok: true, json: async () => result() });
  await pending;
  assert.equal(ui.elements.get('assessment-result').hidden, false);
  assert.match(ui.elements.get('result-score').textContent, /82\/100/);
});

test('setup, ready and unavailable states recover and gate scan controls', async () => {
  const ui = await createUI({ readiness: { available: false } });
  assert.equal(ui.elements.get('assessment-section').dataset.state, 'setup_required');
  assert.equal(ui.elements.get('scan').disabled, true);
  await ui.elements.get('scan').listeners.click();
  assert.equal(ui.requests.length, 0);
  ui.readiness.available = true;
  await ui.context.refreshReadiness();
  assert.equal(ui.elements.get('assessment-section').dataset.state, 'ready');
  assert.equal(ui.elements.get('assessment-progress').textContent, 'Ready to scan');
  assert.equal(ui.elements.get('scan').disabled, false);
  ui.readiness.fail = true;
  await ui.context.refreshReadiness();
  assert.equal(ui.elements.get('assessment-section').dataset.state, 'failed');
  assert.equal(ui.elements.get('scan').disabled, true);
  ui.readiness.fail = false;
  await ui.context.refreshReadiness();
  assert.equal(ui.elements.get('assessment-section').dataset.state, 'ready');
});

test('all result states are explicit and result region is keyboard focusable', async () => {
  const ui = await createUI();
  assert.match(html, /id="assessment-progress"[^>]*role="status"[^>]*aria-live="polite"/);
  assert.equal(ui.elements.get('assessment-result').getAttribute('tabindex'), '0');
  assert.equal(ui.elements.get('preview-body').getAttribute('tabindex'), '0');
  for (const status of ['complete', 'needs_review', 'failed']) {
    ui.render(result({ status, score: status === 'complete' ? 82 : null }));
    assert.equal(ui.elements.get('assessment-section').dataset.state, status);
    assert.ok(ui.elements.get('assessment-progress').textContent.length);
  }
});

test('message B remains associated with B after late A success and failure', async () => {
  for (const lateFailure of [false, true]) {
    const ui = await createUI();
    ui.elements.get('email-text').value = 'Synthetic message A';
    const a = ui.elements.get('scan').listeners.click();
    assert.equal(ui.elements.get('assessment-section').dataset.state, 'running');
    assert.equal(ui.elements.get('scan').getAttribute('aria-busy'), 'true');
    ui.elements.get('email-text').value = 'Synthetic message B';
    ui.elements.get('email-text').listeners.input();
    const b = ui.elements.get('scan').listeners.click();
    ui.requests[1].resolve({ ok: true, json: async () => result({ scan_id: 'scan-B', source_fingerprint: 'b'.repeat(64), score: 12 }) });
    await b;
    if (lateFailure) ui.requests[0].reject(new Error('Late A failure'));
    else ui.requests[0].resolve({ ok: true, json: async () => result({ scan_id: 'scan-A' }) });
    await a;
    assert.equal(ui.elements.get('assessment-result').dataset.scanId, 'scan-B');
    assert.equal(ui.elements.get('assessment-result').dataset.sourceFingerprint, 'b'.repeat(64));
    assert.match(ui.elements.get('result-score').textContent, /12\/100/);
    assert.equal(ui.elements.get('assessment-section').dataset.state, 'complete');
    assert.equal(ui.elements.get('scan').getAttribute('aria-busy'), 'false');
  }
});

test('switching source and changing imported file invalidate in-flight assessment', async () => {
  for (const change of ['tab', 'file']) {
    const ui = await createUI();
    ui.elements.get('email-text').value = 'Synthetic message A';
    const a = ui.elements.get('scan').listeners.click();
    if (change === 'tab') ui.context.selectTab(ui.elements.get('tab-import'));
    else ui.elements.get('email-file').listeners.change();
    ui.requests[0].resolve({ ok: true, json: async () => result() });
    await a;
    assert.equal(ui.elements.get('assessment-result').hidden, true);
    assert.equal(ui.elements.get('assessment-result').dataset.scanId, undefined);
    assert.equal(ui.elements.get('result-score').textContent, '');
  }
});

test('keyboard arrows, Home and End select exactly one tab and clear results', async () => {
  const ui = await createUI();
  for (const [from, key, target] of [
    ['paste', 'ArrowRight', 'import'], ['import', 'ArrowLeft', 'paste'],
    ['paste', 'ArrowLeft', 'gmail'], ['gmail', 'Home', 'paste'], ['paste', 'End', 'gmail'],
  ]) {
    ui.render(result());
    let prevented = false;
    ui.elements.get(`tab-${from}`).listeners.keydown({ key, preventDefault() { prevented = true; } });
    assert.ok(prevented);
    for (const name of ['paste', 'import', 'gmail']) {
      const tab = ui.elements.get(`tab-${name}`);
      assert.equal(tab.getAttribute('aria-selected'), String(name === target));
      assert.equal(tab.tabIndex, name === target ? 0 : -1);
      assert.equal(ui.elements.get(`panel-${name}`).hidden, name !== target);
    }
    assert.ok(ui.elements.get(`tab-${target}`).focused);
    assert.equal(ui.elements.get('assessment-result').hidden, true);
    assert.equal(ui.elements.get('scan').disabled, target === 'gmail');
  }
});

test('missing scan identity fails closed rather than showing an unassociated result', async () => {
  for (const identity of [{ scan_id: '' }, { source_fingerprint: 'invalid' }]) {
    const ui = await createUI();
    ui.elements.get('email-text').value = 'Synthetic example';
    const pending = ui.elements.get('scan').listeners.click();
    ui.requests[0].resolve({ ok: true, json: async () => result(identity) });
    await pending;
    assert.equal(ui.elements.get('assessment-section').dataset.state, 'failed');
    assert.equal(ui.elements.get('assessment-result').hidden, true);
  }
});

test('client deadline clears score and ignores a late successful response', async () => {
  const ui = await createUI({ fakeTimers: true });
  ui.elements.get('email-text').value = 'Synthetic example';
  const pending = ui.elements.get('scan').listeners.click();
  const deadline = [...ui.timers.values()].find((timer) => timer.delay === 150000);
  assert.ok(deadline);
  deadline.callback();
  assert.ok(ui.requests[0].options.signal.aborted);
  assert.equal(ui.elements.get('assessment-section').dataset.state, 'failed');
  assert.equal(ui.elements.get('scan').disabled, false);
  ui.requests[0].resolve({ ok: true, json: async () => result() });
  await pending;
  assert.equal(ui.elements.get('assessment-result').hidden, true);
  assert.equal(ui.elements.get('result-score').textContent, '');
});

test('readiness loss invalidates active response and blocks another scan', async () => {
  const ui = await createUI();
  ui.elements.get('email-text').value = 'Synthetic example';
  const pending = ui.elements.get('scan').listeners.click();
  ui.readiness.available = false;
  await ui.context.refreshReadiness();
  ui.requests[0].resolve({ ok: true, json: async () => result() });
  await pending;
  assert.equal(ui.elements.get('assessment-section').dataset.state, 'setup_required');
  assert.equal(ui.elements.get('assessment-result').hidden, true);
  assert.equal(ui.elements.get('scan').disabled, true);
});

function gmailPreview(id, fingerprint = 'a'.repeat(64)) {
  return { status: 'complete', evidence: {
    source: 'gmail', account_scope: 'c'.repeat(64), source_message_id: id,
    fingerprint, sender: 'sender@example.org', subject: `Synthetic ${id}`, body_text: 'Synthetic body',
    links: [], warnings: [], missing_fields: [],
  }, coverage_statement: 'Extraction only.' };
}

async function gmailPage(ui, messages = [{ id: 'abc123', sender: 'sender@example.org', subject: 'Synthetic subject', date: 'Synthetic date' }]) {
  ui.context.selectTab(ui.elements.get('tab-gmail'));
  const pending = ui.elements.get('gmail-refresh').listeners.click();
  await new Promise(setImmediate);
  const request = ui.requests.at(-1);
  assert.ok(request.url.startsWith('/api/messages?account_scope='));
  request.resolve({ ok: true, json: async () => ({ account_scope: 'c'.repeat(64), messages, next_page_token: 'next' }) });
  await pending;
  return ui.elements.get('gmail-messages').children.map((item) => item.children[0]);
}

test('Gmail refresh, select, scan and pagination use scoped APIs', async () => {
  const ui = await createUI({ gmailStatus: { connected: true, account_scope: 'c'.repeat(64) } });
  const [button] = await gmailPage(ui);
  let pending = button.listeners.click();
  assert.ok(ui.requests.at(-1).url.startsWith('/api/messages/abc123?account_scope='));
  ui.requests.at(-1).resolve({ ok: true, json: async () => gmailPreview('abc123') });
  await pending;
  assert.equal(ui.elements.get('scan').disabled, false);
  pending = ui.elements.get('scan').listeners.click();
  const request = ui.requests.at(-1);
  assert.deepEqual(JSON.parse(request.options.body), { source: 'gmail', source_message_id: 'abc123', account_scope: 'c'.repeat(64) });
  request.resolve({ ok: true, json: async () => result() });
  await pending;
  assert.match(ui.elements.get('result-score').textContent, /82\/100/);
  pending = ui.elements.get('gmail-next').listeners.click();
  assert.equal(ui.elements.get('result-score').textContent, '');
  assert.ok(ui.requests.at(-1).url.includes('page_token=next'));
  ui.requests.at(-1).resolve({ ok: true, json: async () => ({ account_scope: 'c'.repeat(64), messages: [], next_page_token: null }) });
  await pending;
  assert.equal(ui.elements.get('gmail-next').disabled, true);
  assert.equal(ui.elements.get('gmail-previous').disabled, false);
});

test('Gmail late selection A cannot replace selection B or its scan', async () => {
  const ui = await createUI({ gmailStatus: { connected: true, account_scope: 'c'.repeat(64) } });
  const buttons = await gmailPage(ui, ['abc123', 'def456'].map((id) => ({ id, sender: 'Synthetic sender', subject: id, date: 'Synthetic date' })));
  const a = buttons[0].listeners.click();
  const requestA = ui.requests.at(-1);
  const b = buttons[1].listeners.click();
  ui.requests.at(-1).resolve({ ok: true, json: async () => gmailPreview('def456', 'b'.repeat(64)) });
  await b;
  requestA.resolve({ ok: true, json: async () => gmailPreview('abc123') });
  await a;
  assert.equal(ui.elements.get('preview-subject').textContent, 'Synthetic def456');
  assert.equal(buttons[0].getAttribute('aria-pressed'), 'false');
  assert.equal(buttons[1].getAttribute('aria-pressed'), 'true');
  const pending = ui.elements.get('scan').listeners.click();
  assert.equal(JSON.parse(ui.requests.at(-1).options.body).source_message_id, 'def456');
  ui.requests.at(-1).resolve({ ok: true, json: async () => result({ source_fingerprint: 'b'.repeat(64) }) });
  await pending;
  assert.equal(ui.elements.get('assessment-result').dataset.sourceFingerprint, 'b'.repeat(64));
});

test('Gmail scan with changed content is withheld and requires reselection', async () => {
  const ui = await createUI({ gmailStatus: { connected: true, account_scope: 'c'.repeat(64) } });
  const [button] = await gmailPage(ui);
  let pending = button.listeners.click();
  ui.requests.at(-1).resolve({ ok: true, json: async () => gmailPreview('abc123') });
  await pending;
  pending = ui.elements.get('scan').listeners.click();
  ui.requests.at(-1).resolve({ ok: true, json: async () => result({ source_fingerprint: 'b'.repeat(64) }) });
  await pending;
  assert.equal(ui.elements.get('assessment-result').hidden, true);
  assert.equal(ui.elements.get('scan').disabled, true);
  assert.equal(ui.elements.get('assessment-state').textContent, 'Message changed');
});

test('Gmail connection loss clears selected evidence and result', async () => {
  const ui = await createUI({ gmailStatus: { connected: true, account_scope: 'c'.repeat(64) } });
  const [button] = await gmailPage(ui);
  const pending = button.listeners.click();
  ui.requests.at(-1).resolve({ ok: true, json: async () => gmailPreview('abc123') });
  await pending;
  ui.render(result());
  ui.gmailStatus.connected = false;
  await ui.context.refreshGmailStatus();
  assert.equal(ui.elements.get('assessment-result').hidden, true);
  assert.equal(ui.elements.get('message-preview').hidden, true);
  assert.equal(ui.elements.get('gmail-messages').textContent, '');
  assert.equal(ui.elements.get('scan').disabled, true);
});

test('Connect navigates only to Google HTTPS after a local user action', async () => {
  const ui = await createUI();
  let pending = ui.elements.get('gmail-connect').listeners.click();
  ui.requests.at(-1).resolve({ ok: true, json: async () => ({ authorization_url: 'https://attacker.example/' }) });
  await pending;
  assert.equal(ui.context.destination, undefined);
  pending = ui.elements.get('gmail-connect').listeners.click();
  assert.equal(ui.requests.at(-1).options.headers['X-Email-Checker-Request'], '1');
  ui.requests.at(-1).resolve({ ok: true, json: async () => ({ authorization_url: 'https://accounts.google.com/o/oauth2/auth?synthetic=1' }) });
  await pending;
  assert.ok(ui.context.destination.startsWith('https://accounts.google.com/'));
});

test('P5-5-F1 HTTP and network status errors remove Gmail evidence and ignore late scans', async () => {
  for (const failure of ['http', 'network']) {
    const ui = await createUI({ gmailStatus: { connected: true, account_scope: 'c'.repeat(64) } });
    const [button] = await gmailPage(ui);
    let pending = button.listeners.click();
    ui.requests.at(-1).resolve({ ok: true, json: async () => gmailPreview('abc123') });
    await pending;
    ui.render(result());
    pending = ui.elements.get('scan').listeners.click();
    const late = ui.requests.at(-1);
    ui.gmailStatus.fail = failure;
    await ui.context.refreshGmailStatus();
    assert.equal(ui.elements.get('assessment-result').hidden, true);
    assert.equal(ui.elements.get('message-preview').hidden, true);
    assert.equal(ui.elements.get('preview-body').textContent, '');
    assert.equal(ui.elements.get('scan').disabled, true);
    assert.ok(late.options.signal.aborted);
    late.resolve({ ok: true, json: async () => result() });
    await pending;
    assert.equal(ui.elements.get('assessment-result').hidden, true);
  }
});

test('Gmail status failure does not invalidate an unrelated pasted scan', async () => {
  const ui = await createUI();
  ui.elements.get('email-text').value = 'Synthetic pasted message';
  const pending = ui.elements.get('scan').listeners.click();
  const request = ui.requests.at(-1);
  ui.gmailStatus.fail = 'network';
  await ui.context.refreshGmailStatus();
  assert.equal(request.options.signal.aborted, false);
  request.resolve({ ok: true, json: async () => result() });
  await pending;
  assert.equal(ui.elements.get('assessment-result').hidden, false);
});

test('Disconnect clears Gmail content and discards a late scan', async () => {
  const ui = await createUI({ gmailStatus: { connected: true, account_scope: 'c'.repeat(64) } });
  const [button] = await gmailPage(ui);
  let pending = button.listeners.click();
  ui.requests.at(-1).resolve({ ok: true, json: async () => gmailPreview('abc123') });
  await pending;
  pending = ui.elements.get('scan').listeners.click();
  const late = ui.requests.at(-1);
  const disconnect = ui.elements.get('gmail-disconnect').listeners.click();
  assert.ok(late.options.signal.aborted);
  assert.equal(ui.elements.get('message-preview').hidden, true);
  assert.equal(ui.elements.get('gmail-messages').textContent, '');
  assert.equal(ui.elements.get('gmail-connect').disabled, true);
  ui.requests.at(-1).resolve({ ok: true, json: async () => ({ disconnected: true, revocation_failed: true }) });
  await disconnect;
  assert.match(ui.elements.get('gmail-state').textContent, /Disconnected locally.*revocation/);
  assert.equal(ui.elements.get('gmail-connect').disabled, false);
  late.resolve({ ok: true, json: async () => result() });
  await pending;
  assert.equal(ui.elements.get('assessment-result').hidden, true);
});

test('Disconnect local removal failure retains a retry control', async () => {
  const ui = await createUI({ gmailStatus: { connected: true, account_scope: 'c'.repeat(64) } });
  let pending = ui.elements.get('gmail-disconnect').listeners.click();
  ui.requests.at(-1).resolve({ ok: false, json: async () => ({ code: 'credential_store_failed' }) });
  await pending;
  assert.match(ui.elements.get('gmail-state').textContent, /Could not confirm local credential removal/);
  assert.equal(ui.elements.get('gmail-connect').disabled, true);
  assert.equal(ui.elements.get('gmail-disconnect').disabled, false);
  pending = ui.elements.get('gmail-disconnect').listeners.click();
  ui.requests.at(-1).resolve({ ok: true, json: async () => ({ disconnected: true, revocation_failed: false }) });
  await pending;
  assert.equal(ui.elements.get('gmail-connect').disabled, false);
  assert.equal(ui.elements.get('gmail-disconnect').disabled, true);
});

test('malicious feedback requires opt-in and submits matching assessed evidence without review promotion', async () => {
  const ui = await createUI();
  ui.elements.get('email-text').value = 'Synthetic malicious message';
  const scanning = ui.elements.get('scan').listeners.click();
  ui.requests[0].resolve({ ok: true, json: async () => result() });
  await scanning;
  assert.equal(ui.elements.get('training-feedback').hidden, false);
  assert.equal(ui.elements.get('feedback-submit').disabled, true);
  await ui.elements.get('feedback-submit').listeners.click();
  assert.equal(ui.requests.length, 1);
  ui.elements.get('feedback-retain').checked = true;
  ui.elements.get('feedback-retain').listeners.change();
  const saving = ui.elements.get('feedback-submit').listeners.click();
  assert.equal(ui.requests[1].url, '/api/previews/paste');
  assert.equal(JSON.parse(ui.requests[1].options.body).text, 'Synthetic malicious message');
  ui.requests[1].resolve({ ok: true, json: async () => ({ evidence: { fingerprint: 'a'.repeat(64), body_text: 'Synthetic evidence' } }) });
  await new Promise(setImmediate);
  assert.equal(ui.requests[2].url, '/api/feedback');
  const payload = JSON.parse(ui.requests[2].options.body);
  assert.equal(payload.label, 'scam');
  assert.equal(payload.reviewed, false);
  assert.equal(payload.retain_content, true);
  assert.equal(payload.scan_id, 'synthetic-scan');
  assert.equal(payload.evidence.body_text, 'Synthetic evidence');
  ui.requests[2].resolve({ ok: true, json: async () => ({ feedback_id: '11111111-1111-4111-8111-111111111111', reviewed: false, content_retained: true }) });
  await saving;
  assert.equal(ui.elements.get('feedback-submit').disabled, true);
  assert.match(ui.elements.get('feedback-status').textContent, /needs verification/);
  const remove = ui.elements.get('feedback-records').children[0].children[1];
  const deleting = remove.listeners.click();
  assert.equal(ui.requests[3].options.method, 'DELETE');
  ui.requests[3].resolve({ ok: true });
  await deleting;
  assert.equal(ui.elements.get('feedback-records').children.length, 0);
});

test('changed input, withdrawn consent and mismatched fingerprint cannot attach feedback to another message', async () => {
  for (const change of ['input', 'consent', 'fingerprint']) {
    const ui = await createUI();
    ui.elements.get('email-text').value = 'Synthetic message A';
    const scanning = ui.elements.get('scan').listeners.click();
    ui.requests[0].resolve({ ok: true, json: async () => result() });
    await scanning;
    ui.elements.get('feedback-retain').checked = true;
    const saving = ui.elements.get('feedback-submit').listeners.click();
    if (change === 'input') ui.elements.get('email-text').listeners.input();
    if (change === 'consent') ui.elements.get('feedback-retain').checked = false;
    ui.requests[1].resolve({ ok: true, json: async () => ({ evidence: { fingerprint: (change === 'fingerprint' ? 'b' : 'a').repeat(64) } }) });
    await saving;
    assert.equal(ui.requests.length, 2);
    if (change === 'input') {
      assert.equal(ui.elements.get('training-feedback').hidden, true);
      assert.equal(ui.elements.get('feedback-retain').checked, false);
    }
  }
});

test('saved earlier email remains deletable after selection changes during submission', async () => {
  const ui = await createUI();
  ui.elements.get('email-text').value = 'Synthetic message A';
  const scanning = ui.elements.get('scan').listeners.click();
  ui.requests[0].resolve({ ok: true, json: async () => result() });
  await scanning;
  ui.elements.get('feedback-retain').checked = true;
  const saving = ui.elements.get('feedback-submit').listeners.click();
  ui.requests[1].resolve({ ok: true, json: async () => ({ evidence: { fingerprint: 'a'.repeat(64) } }) });
  await new Promise(setImmediate);
  ui.elements.get('email-text').listeners.input();
  ui.requests[2].resolve({ ok: true, json: async () => ({ feedback_id: '22222222-2222-4222-8222-222222222222', reviewed: false, content_retained: true }) });
  await saving;
  assert.equal(ui.elements.get('training-feedback').hidden, true);
  assert.equal(ui.elements.get('feedback-status').textContent, '');
  assert.equal(ui.elements.get('saved-feedback').hidden, false);
  assert.ok(ui.elements.get('feedback-records').children[0].children[1].listeners.click);
});

test('feedback save and deletion failures retain a retry path and never announce success', async () => {
  const ui = await createUI();
  ui.elements.get('email-text').value = 'Synthetic message';
  const scanning = ui.elements.get('scan').listeners.click();
  ui.requests[0].resolve({ ok: true, json: async () => result() });
  await scanning;
  ui.elements.get('feedback-retain').checked = true;
  let saving = ui.elements.get('feedback-submit').listeners.click();
  ui.requests[1].resolve({ ok: false });
  await saving;
  assert.match(ui.elements.get('feedback-status').textContent, /Could not confirm/);
  assert.equal(ui.elements.get('feedback-submit').disabled, false);
  saving = ui.elements.get('feedback-submit').listeners.click();
  ui.requests[2].resolve({ ok: true, json: async () => ({ evidence: { fingerprint: 'a'.repeat(64) } }) });
  await new Promise(setImmediate);
  ui.requests[3].resolve({ ok: true, json: async () => ({ feedback_id: '33333333-3333-4333-8333-333333333333', reviewed: false, content_retained: true }) });
  await saving;
  const deleting = ui.elements.get('feedback-records').children[0].children[1].listeners.click();
  ui.requests[4].resolve({ ok: false, status: 500 });
  await deleting;
  assert.match(ui.elements.get('feedback-delete-status').textContent, /Could not delete/);
  assert.equal(ui.elements.get('feedback-records').children[0].children[1].disabled, false);
});

test('failed and test-double assessments cannot offer malicious training submission', async () => {
  for (const changes of [{ status: 'failed' }, { is_test_double: true }]) {
    const ui = await createUI();
    ui.elements.get('email-text').value = 'Synthetic message';
    const scanning = ui.elements.get('scan').listeners.click();
    ui.requests[0].resolve({ ok: true, json: async () => result(changes) });
    await scanning;
    assert.equal(ui.elements.get('training-feedback').hidden, true);
  }
});

test('import and Gmail feedback preserve the exact selected source and reset consent on disconnect', async () => {
  for (const source of ['import', 'gmail']) {
    const ui = await createUI({ gmailStatus: { connected: true, account_scope: 'c'.repeat(64) } });
    let file;
    if (source === 'import') {
      ui.context.selectTab(ui.elements.get('tab-import'));
      file = new File(['Subject: Synthetic\n\nSynthetic email'], 'synthetic.eml');
      ui.elements.get('email-file').files = [file];
    } else {
      const [button] = await gmailPage(ui);
      const selecting = button.listeners.click();
      ui.requests.at(-1).resolve({ ok: true, json: async () => gmailPreview('abc123') });
      await selecting;
    }
    const scanning = ui.elements.get('scan').listeners.click();
    ui.requests.at(-1).resolve({ ok: true, json: async () => result() });
    await scanning;
    ui.elements.get('feedback-retain').checked = true;
    const saving = ui.elements.get('feedback-submit').listeners.click();
    if (source === 'import') {
      assert.equal(ui.requests.at(-1).url, '/api/previews/import');
      assert.equal(ui.requests.at(-1).options.body, file);
      ui.requests.at(-1).resolve({ ok: true, json: async () => ({ evidence: { fingerprint: 'a'.repeat(64), source: 'eml' } }) });
      await new Promise(setImmediate);
    }
    assert.equal(ui.requests.at(-1).url, '/api/feedback');
    const payload = JSON.parse(ui.requests.at(-1).options.body);
    assert.equal(payload.evidence.source, source === 'gmail' ? 'gmail' : 'eml');
    if (source === 'gmail') assert.equal(payload.evidence.source_message_id, 'abc123');
    ui.requests.at(-1).resolve({ ok: true, json: async () => ({ feedback_id: '44444444-4444-4444-8444-444444444444', reviewed: false, content_retained: true }) });
    await saving;
    if (source === 'gmail') ui.context.selectTab(ui.elements.get('tab-paste'));
    else ui.elements.get('email-file').listeners.change();
    assert.equal(ui.elements.get('training-feedback').hidden, true);
    assert.equal(ui.elements.get('feedback-retain').checked, false);
  }
});

test('saved submissions can be discovered and deleted after reload or an uncertain save', async () => {
  for (const uncertain of [false, true]) {
    const ui = await createUI();
    if (uncertain) {
      ui.elements.get('email-text').value = 'Synthetic message';
      const scanning = ui.elements.get('scan').listeners.click();
      ui.requests.at(-1).resolve({ ok: true, json: async () => result() });
      await scanning;
      ui.elements.get('feedback-retain').checked = true;
      const saving = ui.elements.get('feedback-submit').listeners.click();
      ui.requests.at(-1).resolve({ ok: true, json: async () => ({ evidence: { fingerprint: 'a'.repeat(64) } }) });
      await new Promise(setImmediate);
      ui.requests.at(-1).reject(new Error('Synthetic lost confirmation'));
      await saving;
      assert.match(ui.elements.get('feedback-status').textContent, /Load saved examples/);
    }
    assert.equal(ui.elements.get('saved-feedback').hidden, false);
    const loading = ui.elements.get('feedback-load').listeners.click();
    assert.match(ui.requests.at(-1).url, /include_content=false/);
    assert.equal(ui.requests.at(-1).options.headers['X-Email-Checker-Request'], '1');
    ui.requests.at(-1).resolve({ ok: true, json: async () => ({ records: [{ feedback_id: '55555555-5555-4555-8555-555555555555', created_at: '2026-11-17T12:00:00Z', label: 'scam' }], next_after: null }) });
    await loading;
    assert.match(ui.elements.get('feedback-records').textContent, /scam report.*2026-11-17.*55555555/);
    const deleting = ui.elements.get('feedback-records').children[0].children[1].listeners.click();
    assert.equal(ui.requests.at(-1).url, '/api/feedback/55555555-5555-4555-8555-555555555555');
    ui.requests.at(-1).resolve({ ok: true });
    await deleting;
    assert.equal(ui.elements.get('feedback-records').children.length, 0);
  }
});

test('saved example metadata pagination and load failure preserve deletion controls', async () => {
  const ui = await createUI();
  let loading = ui.elements.get('feedback-load').listeners.click();
  const id = '66666666-6666-4666-8666-666666666666';
  ui.requests.at(-1).resolve({ ok: true, json: async () => ({ records: [{ feedback_id: id, created_at: 'synthetic date', label: 'scam' }], next_after: id }) });
  await loading;
  assert.equal(ui.elements.get('feedback-load').textContent, 'Load more examples');
  loading = ui.elements.get('feedback-load').listeners.click();
  assert.ok(ui.requests.at(-1).url.includes(`after=${id}`));
  ui.requests.at(-1).resolve({ ok: false });
  await loading;
  assert.equal(ui.elements.get('feedback-load').disabled, false);
  assert.equal(ui.elements.get('feedback-records').children.length, 1);
  assert.match(ui.elements.get('feedback-list-status').textContent, /Could not load/);
});
