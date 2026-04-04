// =============================================
// PRODUCT CARD PAGE
// =============================================
const _cardParams = new URLSearchParams(window.location.search);
const cardSteId = _cardParams.get('ste_id') || '';
const cardQuery = _cardParams.get('query') || '';
const cardPosition = parseInt(_cardParams.get('position') || '0', 10);

// Dwell time tracking
const _enterTime = Date.now();
let _beaconSent = false;

function _sendDwellBeacon() {
  if (_beaconSent || !state.isAuthorized || !cardSteId) return;
  _beaconSent = true;
  const dwellMs = Date.now() - _enterTime;
  const eventType = dwellMs < 3000 ? 'quick_return' : 'dwell';
  const payload = JSON.stringify({
    inn: state.user.inn,
    query: cardQuery,
    ste_id: cardSteId,
    position: cardPosition,
    event_type: eventType,
    dwell_ms: dwellMs,
  });
  navigator.sendBeacon(
    BASE_URL + '/event',
    new Blob([payload], { type: 'application/json' })
  );
}

window.addEventListener('pagehide', _sendDwellBeacon);
window.addEventListener('beforeunload', _sendDwellBeacon);

// Override openModal to log target_action
const _origOpenModal = openModal;
window.openModal = function () {
  if (state.isAuthorized && API_ENABLED && cardSteId) {
    apiLogEvent(state.user.inn, cardQuery, cardSteId, cardPosition, 'target_action', null);
  }
  _origOpenModal();
};

function onAuthChange() {
  renderProduct();
}

async function renderProduct() {
  const isAuth = state.isAuthorized;
  document.getElementById('product-history').classList.toggle('hidden', !isAuth);
  document.getElementById('product-why').classList.toggle('hidden', !isAuth);
  document.getElementById('viewed-section').classList.toggle('hidden', !isAuth);
  document.getElementById('pv-badge-frequent').classList.toggle('hidden', !isAuth);
  document.getElementById('pv-badge-ai').classList.toggle('hidden', !isAuth);

  document.getElementById('together-grid').innerHTML = togetherProducts.map(p => renderCard(p, 'compact')).join('');
  document.getElementById('analogs-track').innerHTML = analogProducts.map(p => renderCard(p, 'carousel')).join('');
  if (isAuth) {
    document.getElementById('viewed-track').innerHTML = viewedProducts.map(p => renderCard(p, 'carousel')).join('');
  }

  // Load STE data from API
  if (API_ENABLED && cardSteId) {
    const data = await apiGetSte(cardSteId);
    if (data) {
      const titleEl = document.querySelector('.product-title');
      const idEl = document.querySelector('.product-id');
      const catEl = document.querySelector('.product-visual-cat');
      const attrsEl = document.querySelector('.product-attrs');

      if (titleEl) titleEl.textContent = data.name;
      if (idEl) idEl.textContent = 'Реестровый №: ' + data.ste_id;
      if (catEl) catEl.textContent = data.category || '';

      if (attrsEl && data.attributes) {
        let attrs = [];
        try {
          const parsed = typeof data.attributes === 'string' ? JSON.parse(data.attributes) : data.attributes;
          if (Array.isArray(parsed)) {
            attrs = parsed;
          } else if (typeof parsed === 'object' && parsed !== null) {
            // attributes is a key:value dict — show first 6 entries as pills
            attrs = Object.entries(parsed).slice(0, 6).map(([k, v]) => `${k}: ${v}`);
          }
        } catch {
          attrs = [String(data.attributes)];
        }
        attrsEl.innerHTML = attrs.map(a => `<span class="attr-pill">${a}</span>`).join('');
      }
    }
  }

  // Load explain data for #product-why block
  if (isAuth && API_ENABLED && cardQuery) {
    const whyBlock = document.getElementById('product-why');
    const explainData = await apiGetExplain(state.user.inn, cardQuery);

    if (explainData && explainData.reasons && explainData.reasons.length > 0) {
      const reasonsHtml = explainData.reasons.map(r =>
        `<div class="progress-item">
          <div class="progress-label">
            <span>${r.influence}</span>
            <span style="font-size:11px;color:var(--gray)">${r.ste_id}</span>
          </div>
          <div style="font-size:12px;color:var(--teal);margin-top:2px;">${r.event_type}</div>
        </div>`
      ).join('');

      whyBlock.querySelector('.why-header').insertAdjacentHTML('afterend', reasonsHtml);
      // Remove static placeholder bars
      whyBlock.querySelectorAll('.progress-item:has(.progress-bar)').forEach(el => el.remove());
      whyBlock.classList.remove('hidden');
    } else {
      whyBlock.classList.add('hidden');
    }
  }
}

renderProduct();
