const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const { test } = require('node:test');
const root = path.resolve(__dirname, '../..');
const html = fs.readFileSync(path.join(root, 'src/bad_email_check/static/review.html'), 'utf8');
const source = fs.readFileSync(path.join(root, 'src/bad_email_check/static/review.js'), 'utf8');
const tick = () => new Promise(setImmediate);

class Element {
  constructor() { this.listeners = {}; this.value = ''; this.checked = false; this.disabled = false; this.text = ''; this.children = []; }
  addEventListener(name, handler) { this.listeners[name] = handler; }
  focus() { this.focused = true; }
  set textContent(value) { this.text = String(value); this.children = []; }
  get textContent() { return this.text + this.children.map((child) => child.textContent).join(' '); }
  set innerHTML(value) { throw new Error('Untrusted HTML must not be rendered'); }
  appendChild(child) { this.children.push(child); }
}

async function createUI(status = { total: 2, reviewed: 0, finalized: false, policy: null }) {
  const elements = new Map([...html.matchAll(/id="([^"]+)"/g)].map((match) => [match[1], new Element()]));
  const radios = ['scam', 'legitimate', 'unknown'].map((value) => Object.assign(new Element(), { value }));
  elements.get('review-policy').value = 'recall_no_extra_alerts';
  elements.get('alert-budget').value = '0';
  const requests = [];
  const tags = [];
  const context = vm.createContext({
    document: {
      getElementById: (id) => elements.get(id),
      querySelectorAll: (selector) => selector === '#decision-form input' ? [...radios, elements.get('owner-reviewed')] : radios,
      querySelector: () => radios.find((input) => input.checked),
      createElement: (tag) => { tags.push(tag); return new Element(); },
    },
    fetch: async (url, options) => url === '/api/review/status' ?
      { ok: true, json: async () => status } : new Promise((resolve) => requests.push({ url, options, resolve })),
  });
  vm.runInContext(source, context);
  await tick();
  return { elements, radios, requests, tags, context };
}

function item(index = 0, body = '<img src="https://remote.invalid/x" onerror="alert(1)">') {
  return { id: String(index).repeat(64), index, total: 2, sender: 'synthetic@example.org', subject: '<script>literal</script>', body_text: body, links: [{ displayed_text: 'bank.example', destination: 'https://different.example' }], previous_label: null, finalized: false };
}

async function resolveItem(ui, data = item()) {
  ui.requests.at(-1).resolve({ ok: true, json: async () => data });
  await tick();
}

test('review renders literal email text and no active destinations', async () => {
  const ui = await createUI();
  await resolveItem(ui);
  assert.equal(ui.elements.get('review-body').textContent, item().body_text);
  assert.equal(ui.elements.get('review-subject').textContent, '<script>literal</script>');
  assert.deepEqual(ui.tags, ['li']);
  assert.ok(ui.radios.every((input) => !input.checked));
  assert.equal(ui.elements.get('owner-reviewed').checked, false);
  assert.equal(ui.elements.get('message-heading').focused, true);
  assert.match(html, /<fieldset>/);
  assert.match(html, /role="alert"/);
});

test('review save requires explicit owner confirmation and only posts decision fields', async () => {
  const ui = await createUI();
  await resolveItem(ui, { ...item(0), id: '1'.repeat(64), total: 1 });
  ui.radios[2].checked = true;
  const count = ui.requests.length;
  await ui.elements.get('decision-form').listeners.submit({ preventDefault() {} });
  assert.equal(ui.requests.length, count);
  ui.elements.get('owner-reviewed').checked = true;
  const pending = ui.elements.get('decision-form').listeners.submit({ preventDefault() {} });
  const request = ui.requests.at(-1);
  assert.deepEqual(JSON.parse(request.options.body), { item_id: '1'.repeat(64), label: 'unknown', reviewed_by_owner: true });
  assert.ok(ui.radios.every((input) => input.disabled));
  request.resolve({ ok: true, json: async () => ({ total: 2, reviewed: 1, finalized: false }) });
  await pending;
});

test('late message response cannot replace the current review item', async () => {
  const ui = await createUI();
  const early = ui.requests[0];
  const pending = ui.context.loadItem(1);
  await resolveItem(ui, item(1, 'Message B'));
  await pending;
  early.resolve({ ok: true, json: async () => item(0, 'Message A') });
  await tick();
  assert.equal(ui.elements.get('review-body').textContent, 'Message B');
  assert.equal(ui.elements.get('message-heading').textContent, 'Message 2 of 2');
});

test('frozen review restores the agreed policy and prevents edits', async () => {
  const ui = await createUI({ total: 2, reviewed: 2, finalized: true, policy: { name: 'fewer_alerts', extra_false_alerts: 0 } });
  await resolveItem(ui);
  assert.equal(ui.elements.get('review-policy').value, 'fewer_alerts');
  assert.equal(ui.elements.get('review-policy').disabled, true);
  assert.equal(ui.elements.get('finish-review').disabled, true);
  assert.equal(ui.elements.get('save-decision').disabled, true);
});
