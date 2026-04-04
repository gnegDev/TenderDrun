// =============================================
// STATE
// =============================================
const state = {
  isAuthorized: false,
  user: null,
  region: 'Москва',
  currentQuery: '',
  currentResults: [],
  cartItems: [
    { id: 'c1', title: 'Перчатки латексные нестерильные, 100 шт, р-р M', price: 450, qty: 2 },
    { id: 'c2', title: 'Шприц инъекционный одноразовый 5 мл', price: 120, qty: 5 },
  ],
};

// =============================================
// RENDER PRODUCT CARD
// =============================================
// Default card click handler — overridden in search.js for tracked navigation
function handleCardClick(e, steId, position) {
  window.location.href = `card.html?ste_id=${encodeURIComponent(steId)}`;
}

function renderCard(p, variant = 'grid', position = 0) {
  // Support both API data (ste_id/name/category/reason) and mock data (id/title/categoryName/attrs)
  const id = p.ste_id || p.id || '';
  const title = p.name || p.title || '';
  const catName = p.categoryName || p.category || '';
  const attrs = Array.isArray(p.attrs) ? p.attrs : [];
  const price = typeof p.price === 'number' ? p.price : null;
  const catKey = p.category in categoryIcons ? p.category : 'other';

  const showBadges = state.isAuthorized && p.badges && p.badges.length;
  const badgesHtml = showBadges ? `<div class="badges">${p.badges.map(b => {
    const cfg = badgeConfigs[b];
    return cfg ? `<span class="badge ${cfg.cls}">${cfg.icon} ${cfg.label}</span>` : '';
  }).join('')}</div>` : '';

  const historyHtml = (state.isAuthorized && p.historyCount)
    ? `<div class="card-history">Закупали ${p.historyCount} раза · ${p.historyDate}</div>` : '';

  const reasonHtml = (state.isAuthorized && p.reason)
    ? `<div class="card-reason" style="font-size:12px;color:var(--teal);margin-top:4px;">${p.reason}</div>`
    : '';

  const sizeClass = variant === 'carousel' ? 'carousel-card' : variant === 'compact' ? 'grid-card compact-card' : 'grid-card';

  const onclickCard = p.ste_id
    ? `handleCardClick(event,'${p.ste_id}',${position})`
    : `window.location.href='card.html'`;

  const addCartCall = `event.stopPropagation();addToCart('${title.substring(0, 30)}',${price || 0});showToast('Добавлено в корзину')`;

  return `<div class="product-card ${sizeClass}" onclick="${onclickCard}">
    <div class="card-icon-wrap">
      <div class="card-icon">${categoryIcons[catKey] || categoryIcons.other}</div>
      <span class="card-category">${catName}</span>
      <span class="card-status" style="margin-left:auto">● ${p.status || 'Активна'}</span>
    </div>
    ${badgesHtml}
    <div class="card-title">${title}</div>
    <div class="card-attrs">${attrs.join(' · ')}</div>
    ${reasonHtml}
    ${historyHtml}
    <div class="card-footer">
      <div>
        <div class="card-price">${price ? price.toLocaleString('ru') + ' ₽' : '—'}</div>
        <div class="card-price-sub">за единицу</div>
      </div>
      <div class="card-offers">${p.offers ? p.offers + ' предл.' : ''}</div>
    </div>
    <button class="btn-add-cart" onclick="${addCartCall}">В корзину</button>
  </div>`;
}

// =============================================
// SEARCH
// =============================================
function doSearch(query) {
  if (!query.trim()) return;
  closeAllDropdowns();
  window.location.href = 'search.html?q=' + encodeURIComponent(query);
}

function showSearchDd(ddId) {
  const inputId = ddId === 'home-dd' ? 'home-search' : 'search-page-input';
  updateSearchDropdown(inputId, ddId);
}

function updateSearchDropdown(inputId, ddId) {
  const input = document.getElementById(inputId);
  const dd = document.getElementById(ddId);
  if (!input || !dd) return;
  const val = input.value.toLowerCase().trim();
  dd.classList.remove('hidden');

  let html = '';

  if (val === 'перчаики') {
    html += `<div class="typo-note">Возможно, вы искали: <strong>перчатки</strong></div>`;
  }

  if (state.isAuthorized) {
    const filtered = searchSuggestions.history.filter(h => !val || h.includes(val));
    if (filtered.length) {
      html += `<div class="search-section"><div class="search-section-title">История поиска</div>`;
      filtered.forEach(s => {
        html += `<div class="search-item" onclick="doSearch('${s}')">
          <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="var(--gray)" stroke-width="2"><circle cx="12" cy="12" r="10"/><polyline points="12 6 12 12 16 14"/></svg>
          ${s}</div>`;
      });
      html += '</div>';
    }
  }

  const filtered = searchSuggestions.ai.filter(s => !val || s.includes(val));
  if (filtered.length) {
    html += `<div class="search-section"><div class="search-section-title">${state.isAuthorized ? 'AI рекомендует' : 'Популярные запросы'}</div>`;
    filtered.forEach(s => {
      const highlighted = val ? s.replace(new RegExp(val, 'gi'), m => `<span class="highlight">${m}</span>`) : s;
      html += `<div class="search-item" onclick="doSearch('${s}')">
        <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="var(--gray)" stroke-width="2"><circle cx="11" cy="11" r="8"/><path d="m21 21-4.35-4.35"/></svg>
        ${highlighted}</div>`;
    });
    html += '</div>';
  }

  if (val) {
    const results = mockProducts.filter(p => p.title.toLowerCase().includes(val));
    if (results.length) {
      html += `<div class="search-section"><div class="search-section-title">Позиции</div>`;
      results.slice(0, 3).forEach(p => {
        const t = p.title.replace(new RegExp(val, 'gi'), m => `<span class="highlight">${m}</span>`);
        html += `<div class="search-item" onclick="window.location.href='card.html'">
          <div class="card-icon" style="width:24px;height:24px;border-radius:3px;">${categoryIcons[p.category]}</div>
          <span>${t}</span></div>`;
      });
      html += '</div>';
    }
  }

  if (!html) html = `<div class="search-item" style="color:var(--gray)">Начните вводить запрос...</div>`;
  dd.innerHTML = html;
}

// =============================================
// AUTH
// =============================================
function doLogin() {
  const inn = document.getElementById('inn-input').value.trim();
  if (!inn) { showToast('Введите ИНН'); return; }
  state.isAuthorized = true;
  state.user = { inn, orgName: 'Детская городская поликлиника №39' };
  updateAuthUI();
  closeAllDropdowns();
  showToast('Добро пожаловать, ' + state.user.orgName);
  if (typeof onAuthChange === 'function') onAuthChange();
}

function doLogout() {
  state.isAuthorized = false;
  state.user = null;
  updateAuthUI();
  closeAllDropdowns();
  showToast('Вы вышли из системы');
  if (typeof onAuthChange === 'function') onAuthChange();
}

function updateAuthUI() {
  const loginBtn = document.getElementById('auth-btn');
  const avatarBtn = document.getElementById('avatar-btn');
  const loginForm = document.getElementById('auth-login-form');
  const profileDiv = document.getElementById('auth-profile');
  if (!loginBtn) return;

  if (state.isAuthorized) {
    loginBtn.classList.add('hidden');
    avatarBtn.classList.remove('hidden');
    loginForm.classList.add('hidden');
    profileDiv.classList.remove('hidden');
    document.getElementById('profile-name').textContent = state.user.orgName;
    document.getElementById('profile-inn').textContent = 'ИНН: ' + state.user.inn;
  } else {
    loginBtn.classList.remove('hidden');
    avatarBtn.classList.add('hidden');
    loginForm.classList.remove('hidden');
    profileDiv.classList.add('hidden');
  }
}

// =============================================
// CART
// =============================================
function openCart() {
  document.getElementById('cart-drawer').classList.add('open');
  document.getElementById('cart-overlay').classList.add('open');
  renderCart();
}
function closeCart() {
  document.getElementById('cart-drawer').classList.remove('open');
  document.getElementById('cart-overlay').classList.remove('open');
}

function renderCart() {
  const list = document.getElementById('cart-items-list');
  if (state.cartItems.length === 0) {
    list.innerHTML = '<p style="text-align:center;color:var(--gray);padding:32px">Корзина пуста</p>';
    document.getElementById('cart-total-price').textContent = '0 ₽';
    updateCartBadge();
    return;
  }
  list.innerHTML = state.cartItems.map(item => `
    <div class="cart-item">
      <div class="cart-item-icon">
        <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="var(--blue)" stroke-width="2"><path d="M22 12h-4l-3 9L9 3l-3 9H2"/></svg>
      </div>
      <div class="cart-item-info">
        <div class="cart-item-title">${item.title}</div>
        <div class="cart-item-price">${(item.price * item.qty).toLocaleString('ru')} ₽</div>
        <div class="qty-controls">
          <button class="qty-btn" onclick="changeQty('${item.id}',-1)">−</button>
          <span class="qty-num">${item.qty}</span>
          <button class="qty-btn" onclick="changeQty('${item.id}',1)">+</button>
        </div>
      </div>
    </div>
  `).join('');
  const total = state.cartItems.reduce((s, i) => s + i.price * i.qty, 0);
  document.getElementById('cart-total-price').textContent = total.toLocaleString('ru') + ' ₽';
  updateCartBadge();
}

function changeQty(id, delta) {
  const item = state.cartItems.find(i => i.id === id);
  if (!item) return;
  item.qty += delta;
  if (item.qty <= 0) state.cartItems = state.cartItems.filter(i => i.id !== id);
  renderCart();
}

function addToCart(title, price) {
  const existing = state.cartItems.find(i => i.title.startsWith(title));
  if (existing) { existing.qty++; }
  else { state.cartItems.push({ id: 'c' + Date.now(), title, price, qty: 1 }); }
  updateCartBadge();
}

function updateCartBadge() {
  const total = state.cartItems.reduce((s, i) => s + i.qty, 0);
  const badge = document.getElementById('cart-badge');
  if (!badge) return;
  badge.textContent = total;
  badge.style.display = total > 0 ? 'flex' : 'none';
}

// =============================================
// MODAL
// =============================================
function openModal() {
  const modal = document.getElementById('quote-modal');
  if (!modal) return;
  modal.classList.add('open');
  const d = new Date();
  d.setDate(d.getDate() + 14);
  document.getElementById('quote-date').value = d.toISOString().split('T')[0];
}
function closeModal() {
  const modal = document.getElementById('quote-modal');
  if (modal) modal.classList.remove('open');
}
function createQuote() {
  closeModal();
  showToast('Котировочная сессия создана');
}

// =============================================
// DROPDOWNS
// =============================================
function toggleDropdown(id) {
  const dd = document.getElementById(id);
  const isOpen = !dd.classList.contains('hidden');
  closeAllDropdowns();
  if (!isOpen) {
    dd.classList.remove('hidden');
    if (id === 'region-dd') document.getElementById('region-chevron').classList.add('open');
  }
}

function setRegion(r) {
  state.region = r;
  document.getElementById('region-label').textContent = r;
  closeAllDropdowns();
}

function closeAllDropdowns() {
  document.querySelectorAll('.dropdown, .search-dropdown').forEach(d => d.classList.add('hidden'));
  document.querySelectorAll('.chevron').forEach(c => c.classList.remove('open'));
}

// =============================================
// TOAST
// =============================================
function showToast(msg) {
  const container = document.getElementById('toast-container');
  const t = document.createElement('div');
  t.className = 'toast';
  t.innerHTML = `<span class="toast-icon">✓</span>${msg}`;
  container.appendChild(t);
  setTimeout(() => t.remove(), 3000);
}

// =============================================
// GLOBAL EVENTS
// =============================================
document.addEventListener('click', function(e) {
  const isTrigger = e.target.closest('.region-btn') || e.target.closest('#auth-btn') || e.target.closest('#avatar-btn');
  const isInside = e.target.closest('.dropdown') || e.target.closest('.search-dropdown');
  const isSearchInput = e.target.closest('.search-container input');
  if (!isTrigger && !isInside && !isSearchInput) {
    closeAllDropdowns();
  }
});

const quoteModal = document.getElementById('quote-modal');
if (quoteModal) {
  quoteModal.addEventListener('click', function(e) {
    if (e.target === this) closeModal();
  });
}

// =============================================
// INIT
// =============================================
renderCart();
updateCartBadge();
