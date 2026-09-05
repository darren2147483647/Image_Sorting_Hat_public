/**
 * 圖像分類帽 — 搜尋列元件
 */
import { searchSuggest } from '../api.js';
import { isIncludeDescendants } from './filter-panel.js';

let debounceTimer = null;

export function renderSearchBar(container, onSelect) {
  container.innerHTML = `
    <div class="search-wrapper">
      <svg class="search-icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
        <circle cx="11" cy="11" r="8"/><path d="m21 21-4.35-4.35"/>
      </svg>
      <input type="text" class="search-input" id="global-search-input"
             placeholder="搜尋角色、作品、作者..." autocomplete="off" />
      <div class="search-suggestions hidden" id="search-suggestions"></div>
    </div>
  `;

  const input = document.getElementById('global-search-input');
  const suggestionsEl = document.getElementById('search-suggestions');

  input.addEventListener('input', () => {
    clearTimeout(debounceTimer);
    const query = input.value.trim();

    if (query.length < 1) {
      suggestionsEl.classList.add('hidden');
      return;
    }

    debounceTimer = setTimeout(async () => {
      try {
        const data = await searchSuggest(query);
        if (data.suggestions.length === 0) {
          suggestionsEl.classList.add('hidden');
          return;
        }

        suggestionsEl.innerHTML = data.suggestions
          .map(
            (s) => `
            <div class="search-suggestion-item" data-type="${s.type}" data-id="${s.id}" data-name="${s.name}">
              <span>${s.label}</span>
            </div>
          `
          )
          .join('');
        suggestionsEl.classList.remove('hidden');

        // Bind click
        suggestionsEl.querySelectorAll('.search-suggestion-item').forEach((item) => {
          item.addEventListener('click', () => {
            const result = {
              type: item.dataset.type,
              id: parseInt(item.dataset.id),
              name: item.dataset.name,
            };
            input.value = result.name;
            suggestionsEl.classList.add('hidden');

            // Navigate based on type, carrying forward the include-descendants
            // toggle's current value rather than forcing it -- the toggle
            // (next to this search bar) is the single source of truth for
            // exact-match vs. expand-to-descendants, so a suggestion click
            // shouldn't silently override whatever the user has it set to.
            const includeDescendants = isIncludeDescendants();
            const idParam = result.type === 'artist' ? `artist_id=${result.id}` : `char_id=${result.id}`;
            window.location.hash = `#/?${idParam}&include_descendants=${includeDescendants}`;

            if (onSelect) onSelect(result);
          });
        });
      } catch (err) {
        suggestionsEl.classList.add('hidden');
      }
    }, 250);
  });

  // Hide suggestions on outside click
  document.addEventListener('click', (e) => {
    if (!container.contains(e.target)) {
      suggestionsEl.classList.add('hidden');
    }
  });

  // Hide on escape
  input.addEventListener('keydown', (e) => {
    if (e.key === 'Escape') {
      suggestionsEl.classList.add('hidden');
      input.blur();
    }
  });
}
