// =============================================
// SEARCH PAGE
// =============================================
let currentPageNum = 1;

// Timers for impression_skip: ste_id → timeoutId
const impressionTimers = new Map();

// Override default handleCardClick from common.js with tracking version
function handleCardClick(e, steId, position) {
  // Cancel impression_skip timer for this card
  if (impressionTimers.has(steId)) {
    clearTimeout(impressionTimers.get(steId));
    impressionTimers.delete(steId);
  }

  // Log click event
  if (state.isAuthorized && API_ENABLED) {
    apiLogEvent(state.user.inn, state.currentQuery, steId, position, 'click');
  }

  // Navigate to card page with context
  const query = encodeURIComponent(state.currentQuery);
  window.location.href = `card.html?ste_id=${encodeURIComponent(steId)}&query=${query}&position=${position}`;
}

function onAuthChange() {
  renderSearch();
}

async function renderSearch() {
  const isAuth = state.isAuthorized;
  document.getElementById('personal-box').classList.toggle('hidden', !isAuth);
  document.getElementById('personal-order-label').classList.toggle('hidden', !isAuth);
  document.getElementById('reorder-section').classList.toggle('hidden', !isAuth);

  const grid = document.getElementById('search-products-grid');

  // Read query from URL
  const urlParams = new URLSearchParams(window.location.search);
  const query = urlParams.get('q') || '';
  state.currentQuery = query;

  if (isAuth && API_ENABLED && query) {
    // --- API path ---
    grid.innerHTML = '<div style="padding:32px;text-align:center;color:var(--gray)">Поиск...</div>';

    const data = await apiSearch(query, state.user.inn);

    if (data && data.results && data.results.length > 0) {
      state.currentResults = data.results;

      // Show suggested_query in synonyms bar
      if (data.suggested_query) {
        const synonymsDiv = document.querySelector('.synonyms');
        if (synonymsDiv) {
          const btn = document.createElement('button');
          btn.className = 'synonym-btn';
          btn.style.borderColor = 'var(--teal)';
          btn.style.color = 'var(--teal)';
          btn.textContent = data.suggested_query;
          btn.onclick = () => doSearch(data.suggested_query);
          synonymsDiv.insertBefore(btn, synonymsDiv.firstChild);
        }
      }

      // Update results count
      const countEl = document.getElementById('results-count');
      if (countEl) countEl.textContent = data.results.length;

      // Render cards
      grid.innerHTML = data.results.map((p, i) => renderCard(p, 'grid', i + 1)).join('');

      // Schedule impression_skip for each card
      _scheduleImpressionSkip(data.results, query);

    } else if (data && data.results && data.results.length === 0) {
      state.currentResults = [];
      grid.innerHTML = '<div style="padding:32px;text-align:center;color:var(--gray)">Ничего не найдено. Попробуйте другой запрос.</div>';
    } else {
      // API failed — fall back to mocks
      _renderMockResults(grid);
    }

  } else {
    // --- Mock path (not authorized or API disabled or no query) ---
    _renderMockResults(grid);
  }
}

function _renderMockResults(grid) {
  let products = [...mockProducts];
  const sort = document.getElementById('sort-select').value;
  if (sort === 'price-asc') products.sort((a, b) => a.price - b.price);
  else if (sort === 'price-desc') products.sort((a, b) => b.price - a.price);
  else if (sort === 'offers') products.sort((a, b) => b.offers - a.offers);
  grid.innerHTML = products.map(p => renderCard(p, 'grid')).join('');
}

function _scheduleImpressionSkip(results, query) {
  // Clear existing timers
  impressionTimers.forEach(t => clearTimeout(t));
  impressionTimers.clear();

  results.forEach(p => {
    const timerId = setTimeout(() => {
      if (state.isAuthorized && API_ENABLED) {
        const pos = results.indexOf(p) + 1;
        apiLogEvent(state.user.inn, query, p.ste_id, pos, 'impression_skip');
      }
      impressionTimers.delete(p.ste_id);
    }, 10000);
    impressionTimers.set(p.ste_id, timerId);
  });
}

function resetFilters() {
  document.getElementById('filter-medical').checked = true;
  document.getElementById('filter-hardware').checked = false;
  document.getElementById('filter-stationery').checked = false;
  document.getElementById('price-from').value = '';
  document.getElementById('price-to').value = '';
  document.getElementById('filter-offers').checked = true;
  renderSearch();
}

function applyFilters() {
  renderSearch();
  showToast('Фильтры применены');
}

function setPage(n) {
  currentPageNum = n;
  document.querySelectorAll('.page-btn').forEach(b => b.classList.remove('active'));
  const btn = document.getElementById('pg-' + n);
  if (btn) btn.classList.add('active');
  window.scrollTo(0, 0);
}

function changePage(dir) {
  setPage(Math.max(1, Math.min(10, currentPageNum + dir)));
}

function togglePersonal() {
  const btn = document.querySelector('.personal-box-toggle');
  const isPersonal = btn.textContent.includes('общую');
  btn.textContent = isPersonal ? 'Показать персональную выдачу ↓' : 'Показать общую выдачу ↓';
  renderSearch();
}

// Set search input value from URL
const urlParams = new URLSearchParams(window.location.search);
const q = urlParams.get('q');
if (q) {
  const input = document.getElementById('search-page-input');
  if (input) input.value = q;
}

renderSearch();
