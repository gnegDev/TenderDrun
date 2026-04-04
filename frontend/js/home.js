// =============================================
// HOME PAGE
// =============================================
function onAuthChange() {
  renderHome();
}

async function renderHome() {
  const aiBadge = document.getElementById('ai-badge-hero');
  const recsTitle = document.getElementById('recs-title');
  if (state.isAuthorized) {
    aiBadge.classList.remove('hidden');
    recsTitle.textContent = 'Рекомендации для вас';
  } else {
    aiBadge.classList.add('hidden');
    recsTitle.textContent = 'Рекомендации';
  }
  renderCarousel();

  // AI suggest hint
  const existingHint = document.getElementById('ai-suggest-hint');
  if (existingHint) existingHint.remove();

  if (state.isAuthorized && API_ENABLED) {
    const data = await apiGetSuggest(state.user.inn);
    if (data && data.suggested_query) {
      const sq = data.suggested_query;
      const searchInput = document.getElementById('home-search');
      if (searchInput) searchInput.placeholder = sq;

      const hint = document.createElement('div');
      hint.id = 'ai-suggest-hint';
      hint.style.cssText = 'font-size:13px;color:var(--teal);margin-top:8px;';
      hint.innerHTML = `ИИ предлагает: <button onclick="doSearch('${sq.replace(/'/g, "\\'")}')" style="background:none;border:none;color:var(--teal);font-weight:600;cursor:pointer;text-decoration:underline;">${sq}</button>`;

      const searchWrap = document.querySelector('.search-wrap');
      if (searchWrap) searchWrap.appendChild(hint);
    }
  }
}

let carouselIndex = 0;

function renderCarousel() {
  const track = document.getElementById('carousel-track');
  track.innerHTML = mockProducts.map(p => renderCard(p, 'carousel')).join('');
  updateCarousel();
}

function carouselMove(dir) {
  const maxIndex = Math.max(0, mockProducts.length - 4);
  carouselIndex = Math.max(0, Math.min(carouselIndex + dir, maxIndex));
  updateCarousel();
}

function updateCarousel() {
  const track = document.getElementById('carousel-track');
  const cardW = 296;
  track.style.transform = `translateX(-${carouselIndex * cardW}px)`;
  document.getElementById('carousel-prev').disabled = carouselIndex === 0;
  document.getElementById('carousel-next').disabled = carouselIndex >= mockProducts.length - 4;
}

renderHome();
