// Shared helpers for the dashboard

async function api(method, url, body, { silent = false } = {}) {
  const opts = { method, headers: { 'Content-Type': 'application/json' } };
  if (body !== undefined) opts.body = JSON.stringify(body);
  const res = await fetch(url, opts);
  if (!res.ok) {
    let detail = res.statusText;
    try {
      const data = await res.json();
      // FastAPI 422 returns detail as an array of {loc, msg}; flatten it so
      // the toast shows something readable instead of "[object Object]".
      if (Array.isArray(data.detail)) {
        detail = data.detail.map(e => `${(e.loc || []).slice(-1)[0]}: ${e.msg}`).join('; ');
      } else {
        detail = data.detail || detail;
      }
    } catch (_) {}
    if (!silent) toast(detail, true);
    throw new Error(detail);
  }
  return res.json();
}

let toastTimer;
function toast(msg, isError = false) {
  const el = document.getElementById('toast');
  el.textContent = msg;
  el.classList.toggle('error', isError);
  el.classList.add('show');
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => el.classList.remove('show'), 3200);
}

function escapeHtml(s) {
  const div = document.createElement('div');
  div.textContent = s ?? '';
  return div.innerHTML;
}

async function refreshConfigStatus() {
  const el = document.getElementById('config-status');
  try {
    const cfg = await api('GET', '/api/config');
    if (cfg.configured) {
      el.textContent = 'API connected';
      el.className = 'pill pill-ok';
    } else {
      el.textContent = 'Setup needed';
      el.className = 'pill pill-warn';
    }
  } catch (_) {
    el.textContent = 'offline';
    el.className = 'pill pill-muted';
  }
}

refreshConfigStatus();
