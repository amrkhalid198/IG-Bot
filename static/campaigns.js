// Campaigns page logic

const listEl = document.getElementById('campaign-list');
const emptyEl = document.getElementById('empty-state');
const modal = document.getElementById('modal');
const form = document.getElementById('campaign-form');

async function loadCampaigns() {
  const campaigns = await api('GET', '/api/campaigns');
  listEl.querySelectorAll('.campaign-card').forEach(el => el.remove());
  emptyEl.hidden = campaigns.length > 0;

  for (const c of campaigns) {
    const card = document.createElement('div');
    card.className = 'campaign-card';
    const thumb = c.post_thumbnail
      ? `<img class="campaign-thumb" src="${escapeHtml(c.post_thumbnail)}" alt="" onerror="this.outerHTML='<div class=\'campaign-thumb-placeholder\'>Preview unavailable</div>'">`
      : `<div class="campaign-thumb-placeholder">Post ${escapeHtml(c.post_id)}</div>`;
    card.innerHTML = `
      ${thumb}
      <div class="campaign-body">
        <div class="campaign-title-row">
          <span class="campaign-title">${escapeHtml(c.name)}</span>
          <span class="pill ${c.active ? 'pill-active' : 'pill-inactive'}">${c.active ? 'Active' : 'Inactive'}</span>
        </div>
        ${c.post_caption ? `<p class="campaign-caption">${escapeHtml(c.post_caption)}</p>` : ''}
        <div class="keyword-row">
          ${c.keywords.split(',').filter(k => k.trim()).map(k => `<span class="kw">${escapeHtml(k.trim())}</span>`).join('')}
        </div>
        <div class="campaign-actions">
          <button class="btn btn-sm" onclick="toggleCampaign(${c.id})">${c.active ? 'Pause' : 'Activate'}</button>
          <button class="btn btn-sm" onclick='editCampaign(${JSON.stringify(c).replace(/'/g, "&#39;")})'>Edit</button>
          <button class="btn btn-sm btn-danger" onclick="deleteCampaign(${c.id})">Delete</button>
        </div>
      </div>`;
    listEl.appendChild(card);
  }
}

function openModal(campaign) {
  form.reset();
  document.getElementById('c-id').value = campaign ? campaign.id : '';
  document.getElementById('modal-title').textContent = campaign ? 'Edit campaign' : 'New campaign';
  document.getElementById('post-preview').hidden = true;
  if (campaign) {
    document.getElementById('c-name').value = campaign.name;
    document.getElementById('c-post').value = campaign.post_id;
    document.getElementById('c-keywords').value = campaign.keywords;
    document.getElementById('c-reply').value = campaign.comment_reply;
    document.getElementById('c-dm').value = campaign.dm_message;
  }
  modal.hidden = false;
}
function closeModal() { modal.hidden = true; }
function editCampaign(c) { openModal(c); }

modal.addEventListener('click', (e) => { if (e.target === modal) closeModal(); });

// Auto-fetch post preview on blur.
// The preview is purely cosmetic — a failure here must NEVER affect the
// ability to save the campaign.
document.getElementById('c-post').addEventListener('blur', async (e) => {
  const postId = e.target.value.trim();
  const preview = document.getElementById('post-preview');
  if (!postId) { preview.hidden = true; return; }
  try {
    const details = await api('GET', `/api/post-preview/${encodeURIComponent(postId)}`, undefined, { silent: true });
    document.getElementById('pp-img').src = details.thumbnail_url || '';
    document.getElementById('pp-caption').textContent =
      (details.caption || '(no caption)').slice(0, 140);
    preview.hidden = false;
  } catch (_) {
    // Preview couldn't load (bad token, expired media, etc.). Show a gentle
    // note instead of an error toast, and leave the form fully usable.
    document.getElementById('pp-caption').textContent =
      'Preview unavailable — you can still save this campaign.';
    document.getElementById('pp-img').removeAttribute('src');
    preview.hidden = false;
  }
});

form.addEventListener('submit', async (e) => {
  e.preventDefault();
  const saveBtn = document.getElementById('save-btn');
  const id = document.getElementById('c-id').value;
  const payload = {
    name: document.getElementById('c-name').value.trim(),
    post_id: document.getElementById('c-post').value.trim(),
    keywords: document.getElementById('c-keywords').value.trim(),
    comment_reply: document.getElementById('c-reply').value.trim(),
    dm_message: document.getElementById('c-dm').value.trim(),
    active: true,
  };

  // Disable ONLY for the duration of the request, and always re-enable in
  // finally so the button can never get permanently stuck.
  saveBtn.disabled = true;
  const originalLabel = saveBtn.textContent;
  saveBtn.textContent = 'Saving…';
  try {
    if (id) {
      await api('PUT', `/api/campaigns/${id}`, payload);
      toast('Campaign updated');
    } else {
      await api('POST', '/api/campaigns', payload);
      toast('Campaign created');
    }
    closeModal();
    loadCampaigns();
  } catch (err) {
    // api() already shows a toast; keep the modal open so the user can fix
    // input and retry. Button is re-enabled below.
    console.error('Campaign save failed:', err);
  } finally {
    saveBtn.disabled = false;
    saveBtn.textContent = originalLabel;
  }
});

async function toggleCampaign(id) {
  await api('PATCH', `/api/campaigns/${id}/toggle`);
  loadCampaigns();
}

async function deleteCampaign(id) {
  if (!confirm('Delete this campaign?')) return;
  await api('DELETE', `/api/campaigns/${id}`);
  toast('Campaign deleted');
  loadCampaigns();
}

loadCampaigns();
