// Minimal event tracking — no rendering, no state

function trackClick(steId, position) {
  if (!INN) return;
  fetch('/api/event', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({
      inn: INN,
      query: CURRENT_QUERY,
      ste_id: steId,
      position: position,
      event_type: 'click',
      dwell_ms: null,
    }),
  }).catch(() => {});
}

function showToast(msg) {
  const container = document.getElementById('toast-container');
  if (!container) return;
  const t = document.createElement('div');
  t.className = 'toast';
  t.innerHTML = `<span class="toast-icon">✓</span>${msg}`;
  container.appendChild(t);
  setTimeout(() => t.remove(), 3000);
}
