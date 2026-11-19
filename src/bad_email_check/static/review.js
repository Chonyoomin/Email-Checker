const byId = (id) => document.getElementById(id);
let reviewIndex = 0;
let reviewItem;
let reviewStatus;
let loadingVersion = 0;
let saving = false;

function controls() {
  const frozen = !!reviewStatus?.finalized;
  byId('review-previous').disabled = saving || reviewIndex === 0;
  byId('review-next').disabled = saving || !reviewItem || reviewIndex + 1 >= reviewItem.total;
  byId('save-decision').disabled = saving || frozen || !reviewItem;
  byId('finish-review').disabled = saving || frozen || !reviewStatus || reviewStatus.reviewed !== reviewStatus.total;
  document.querySelectorAll('#decision-form input').forEach((input) => { input.disabled = saving || frozen || !reviewItem; });
  byId('review-policy').disabled = saving || frozen;
  byId('alert-budget').disabled = saving || frozen || byId('review-policy').value !== 'recall_with_alert_budget';
  byId('agree-policy').disabled = saving || frozen;
  byId('review-progress').textContent = reviewStatus ?
    `${reviewStatus.reviewed} of ${reviewStatus.total} reviewed${frozen ? ' — review frozen' : ''}.` : 'Loading review…';
}

async function refreshStatus() {
  const response = await fetch('/api/review/status', { cache: 'no-store' });
  if (!response.ok) throw new Error('Could not load review status. Reload the page.');
  reviewStatus = await response.json();
  if (reviewStatus.policy) {
    byId('review-policy').value = reviewStatus.policy.name;
    byId('alert-budget').value = String(reviewStatus.policy.extra_false_alerts);
  }
  controls();
}

async function loadItem(index) {
  const version = ++loadingVersion;
  reviewItem = undefined;
  byId('review-error').textContent = '';
  byId('review-body').textContent = '';
  byId('review-sender').textContent = '';
  byId('review-subject').textContent = '';
  byId('review-links').textContent = '';
  controls();
  try {
    const response = await fetch(`/api/review/item/${index}`, { cache: 'no-store' });
    if (!response.ok) throw new Error('Could not load this message. Try again.');
    const item = await response.json();
    if (version !== loadingVersion) return;
    reviewIndex = index;
    reviewItem = item;
    byId('message-heading').textContent = `Message ${index + 1} of ${item.total}`;
    byId('review-sender').textContent = item.sender || 'Not provided';
    byId('review-subject').textContent = item.subject || 'Not provided';
    byId('review-body').textContent = item.body_text;
    item.links.forEach((link) => {
      const entry = document.createElement('li');
      entry.textContent = `${link.displayed_text} → ${link.destination}`;
      byId('review-links').appendChild(entry);
    });
    if (!item.links.length) byId('review-links').textContent = 'No destinations extracted.';
    document.querySelectorAll('input[name="label"]').forEach((input) => { input.checked = input.value === item.previous_label; });
    byId('owner-reviewed').checked = false;
    byId('message-heading').focus();
  } catch (error) {
    if (version === loadingVersion) byId('review-error').textContent = error.message;
  } finally {
    if (version === loadingVersion) controls();
  }
}

async function post(url, payload) {
  const response = await fetch(url, { method: 'POST', headers: { 'Content-Type': 'application/json', 'X-Email-Checker-Request': '1' }, body: JSON.stringify(payload), cache: 'no-store' });
  const data = await response.json();
  if (!response.ok) throw new Error(data.message || 'Could not save. Try again.');
  return data;
}

byId('decision-form').addEventListener('submit', async (event) => {
  event.preventDefault();
  const selected = document.querySelector('input[name="label"]:checked');
  if (!reviewItem || !selected || !byId('owner-reviewed').checked || saving) return;
  saving = true;
  controls();
  try {
    reviewStatus = await post('/api/review/decision', { item_id: reviewItem.id, label: selected.value, reviewed_by_owner: true });
    if (reviewIndex + 1 < reviewItem.total) await loadItem(reviewIndex + 1);
  } catch (error) { byId('review-error').textContent = error.message; }
  finally { saving = false; controls(); }
});
byId('review-previous').addEventListener('click', () => loadItem(reviewIndex - 1));
byId('review-next').addEventListener('click', () => loadItem(reviewIndex + 1));
byId('review-policy').addEventListener('change', () => {
  byId('alert-budget').disabled = byId('review-policy').value !== 'recall_with_alert_budget';
  if (byId('alert-budget').disabled) byId('alert-budget').value = '0';
});
byId('finalize-form').addEventListener('submit', async (event) => {
  event.preventDefault();
  if (!byId('agree-policy').checked || saving) return;
  saving = true;
  controls();
  try {
    reviewStatus = await post('/api/review/finalize', { policy: byId('review-policy').value, extra_false_alerts: Number(byId('alert-budget').value), agree: true });
    byId('review-error').textContent = 'Review saved and frozen. Training has not started.';
  } catch (error) { byId('review-error').textContent = error.message; }
  finally { saving = false; controls(); }
});
refreshStatus().then(() => loadItem(reviewStatus.next_unreviewed_index ?? 0)).catch((error) => { byId('review-error').textContent = error.message; });
