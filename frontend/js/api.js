// =============================================
// API CLIENT
// =============================================
const BASE_URL = 'http://localhost:8080';
const API_ENABLED = true;

// POST /search → { results: [{ste_id, name, category, score, reason}], suggested_query }
async function apiSearch(query, inn) {
  if (!API_ENABLED) return null;
  try {
    const res = await fetch(`${BASE_URL}/search`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ query, inn }),
    });
    if (!res.ok) return null;
    return await res.json();
  } catch { return null; }
}

// POST /event
async function apiLogEvent(inn, query, steId, position, eventType, dwellMs = null) {
  if (!API_ENABLED) return null;
  try {
    const res = await fetch(`${BASE_URL}/event`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ inn, query, ste_id: steId, position, event_type: eventType, dwell_ms: dwellMs }),
    });
    if (!res.ok) return null;
    return await res.json();
  } catch { return null; }
}

// GET /ste/{ste_id} → { ste_id, name, category, attributes }
async function apiGetSte(steId) {
  if (!API_ENABLED) return null;
  try {
    const res = await fetch(`${BASE_URL}/ste/${encodeURIComponent(steId)}`);
    if (!res.ok) return null;
    return await res.json();
  } catch { return null; }
}

// GET /suggest?inn=... → { suggested_query }
async function apiGetSuggest(inn) {
  if (!API_ENABLED) return null;
  try {
    const res = await fetch(`${BASE_URL}/suggest?inn=${encodeURIComponent(inn)}`);
    if (!res.ok) return null;
    return await res.json();
  } catch { return null; }
}

// GET /explain?inn=...&query=... → { reasons: [{ste_id, event_type, influence}] }
async function apiGetExplain(inn, query) {
  if (!API_ENABLED) return null;
  try {
    const res = await fetch(`${BASE_URL}/explain?inn=${encodeURIComponent(inn)}&query=${encodeURIComponent(query)}`);
    if (!res.ok) return null;
    return await res.json();
  } catch { return null; }
}
