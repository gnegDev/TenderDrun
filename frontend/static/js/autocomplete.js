/**
 * autocomplete.js — выпадающий список подсказок при вводе в поисковую строку.
 * Endpoint: GET /api/autocomplete?q=...&inn=...
 * Учитывает: SymSpell-коррекцию опечаток, Word2Vec-синонимы, Redis-сессию пользователя.
 */
(function () {
  'use strict';

  var _timer = null;
  var _activeIdx = -1;

  function getContainer(input) {
    return input.closest('.search-container');
  }

  function getDropdown(input) {
    var c = getContainer(input);
    return c ? c.querySelector('.ac-dropdown') : null;
  }

  function clearDropdown(input) {
    var d = getDropdown(input);
    if (d) d.remove();
    _activeIdx = -1;
  }

  function buildDropdown(input, suggestions) {
    clearDropdown(input);
    if (!suggestions || suggestions.length === 0) return;

    var container = getContainer(input);
    if (!container) return;

    var dropdown = document.createElement('ul');
    dropdown.className = 'ac-dropdown';
    dropdown.setAttribute('role', 'listbox');

    suggestions.forEach(function (s, i) {
      var li = document.createElement('li');
      li.className = 'ac-item' + (s.is_ai_recommended ? ' ac-item--ai' : '');
      li.setAttribute('role', 'option');
      li.setAttribute('data-idx', String(i));

      if (s.is_ai_recommended) {
        var badge = document.createElement('span');
        badge.className = 'ac-badge';
        badge.textContent = 'ИИ';
        li.appendChild(badge);
      }

      var text = document.createElement('span');
      text.className = 'ac-text';
      text.textContent = s.query;
      li.appendChild(text);

      li.addEventListener('mousedown', function (e) {
        // preventDefault предотвращает blur до того, как сработает click
        e.preventDefault();
        selectItem(input, s.query);
      });

      dropdown.appendChild(li);
    });

    container.appendChild(dropdown);
  }

  function selectItem(input, query) {
    input.value = query;
    clearDropdown(input);
    var form = input.closest('form');
    if (form) form.submit();
  }

  function fetchSuggestions(input) {
    var q = input.value.trim();
    if (q.length < 2) {
      clearDropdown(input);
      return;
    }

    var innVal = (typeof INN !== 'undefined') ? INN : '';
    var params = new URLSearchParams({ q: q });
    if (innVal) params.set('inn', innVal);

    fetch('/api/autocomplete?' + params.toString())
      .then(function (r) { return r.json(); })
      .then(function (data) {
        // Не рендерим если фокус ушёл за время запроса
        if (input !== document.activeElement) return;
        buildDropdown(input, data.suggestions || []);
      })
      .catch(function () { /* ML недоступен — молчим */ });
  }

  function handleKeydown(e, input) {
    var dropdown = getDropdown(input);
    if (!dropdown) return;

    var items = dropdown.querySelectorAll('.ac-item');
    if (!items.length) return;

    if (e.key === 'ArrowDown') {
      e.preventDefault();
      _activeIdx = Math.min(_activeIdx + 1, items.length - 1);
    } else if (e.key === 'ArrowUp') {
      e.preventDefault();
      _activeIdx = Math.max(_activeIdx - 1, -1);
    } else if (e.key === 'Enter') {
      if (_activeIdx >= 0) {
        e.preventDefault();
        selectItem(input, items[_activeIdx].querySelector('.ac-text').textContent);
      }
      return;
    } else if (e.key === 'Escape') {
      clearDropdown(input);
      return;
    } else {
      return;
    }

    items.forEach(function (el, i) {
      el.classList.toggle('ac-item--active', i === _activeIdx);
    });

    // Предпросмотр выбранного в поле ввода
    if (_activeIdx >= 0) {
      input.value = items[_activeIdx].querySelector('.ac-text').textContent;
    }
  }

  function initInput(input) {
    input.addEventListener('input', function () {
      clearTimeout(_timer);
      _activeIdx = -1;
      _timer = setTimeout(function () { fetchSuggestions(input); }, 150);
    });

    input.addEventListener('keydown', function (e) {
      handleKeydown(e, input);
    });

    // Скрываем дропдаун при потере фокуса с небольшой задержкой
    // (чтобы mousedown на item успел сработать первым)
    input.addEventListener('blur', function () {
      setTimeout(function () { clearDropdown(input); }, 180);
    });
  }

  function init() {
    document.querySelectorAll('.search-box').forEach(initInput);
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', init);
  } else {
    init();
  }
})();
