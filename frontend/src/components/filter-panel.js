/**
 * 圖像分類帽 — 篩選面板元件
 */
import { getImageFormats } from '../api.js';

// Active filter state
let activeFilters = {
  file_format: null,
  file_name: null,
  char_id: null,
  artist_id: null,
  char_unclassified: false,
  artist_unclassified: false,
  include_descendants: true,
};

let onChangeCallback = null;
let panelContainer = null;

export async function renderFilterPanel(container, onChange) {
  onChangeCallback = onChange;
  panelContainer = container;

  container.innerHTML = `
    <div class="filter-panel">
      <div class="filter-section">
        <div class="filter-section-title">分類狀態</div>
        <label class="filter-option" style="cursor: pointer;">
          <input type="checkbox" id="char-unclassified-toggle" />
          <span>👤 角色未分類</span>
        </label>
        <label class="filter-option" style="cursor: pointer;">
          <input type="checkbox" id="artist-unclassified-toggle" />
          <span>🎨 作者未分類</span>
        </label>
      </div>

      <div class="filter-section">
        <div class="filter-section-title">檔名搜尋</div>
        <input type="text" class="input-field" id="filename-search-input"
               placeholder="輸入檔名關鍵字..." />
      </div>

      <div class="filter-section" id="format-filter-section">
        <div class="filter-section-title">圖片格式</div>
        <div class="loading-screen" style="padding: 12px"><div class="loading-spinner"></div></div>
      </div>

      <div class="filter-section" style="margin-top: var(--space-md);">
        <button class="btn btn-secondary btn-sm" id="clear-filters-btn" style="width: 100%;">
          清除所有篩選
        </button>
      </div>
    </div>
  `;

  // Restore filters from the URL hash before anything reads activeFilters,
  // so the descendants checkbox (and any restored option's active class)
  // reflects the real starting state rather than a stale default.
  restoreFiltersFromHash();

  // Single delegated listener on the container -- options rendered later
  // (the async format list) are handled by the same listener, so nothing
  // needs re-binding and no option ever ends up with two listeners.
  container.addEventListener('click', (e) => {
    const opt = e.target.closest('.filter-option[data-filter]');
    if (!opt || !container.contains(opt)) return;
    handleOptionClick(container, opt);
  });

  applyActiveClasses(container);

  // Filename search (debounced)
  const filenameInput = document.getElementById('filename-search-input');
  filenameInput.value = activeFilters.file_name || '';
  let debounceTimer;
  filenameInput.addEventListener('input', () => {
    clearTimeout(debounceTimer);
    debounceTimer = setTimeout(() => {
      activeFilters.file_name = filenameInput.value.trim() || null;
      if (onChangeCallback) onChangeCallback();
    }, 300);
  });

  // 未分類 toggles -- char_unclassified/artist_unclassified are UI-only
  // booleans (translated to char_id=0/artist_id=0 in getActiveFilters()),
  // kept separate from char_id/artist_id so a specific character/artist
  // selection and "show me the unclassified ones" can't silently collide.
  wireUnclassifiedToggle('char-unclassified-toggle', 'char_unclassified', 'char_id');
  wireUnclassifiedToggle('artist-unclassified-toggle', 'artist_unclassified', 'artist_id');

  // Include-descendants toggle -- rendered by the page next to the global
  // search bar (a more prominent, always-visible spot), not by this panel;
  // this module still owns its state and wiring. Its wrapper already carries
  // the shared .filter-option class, so reusing .active gives it the same
  // "selected" look as the other filter options for free.
  const descendantsToggle = document.getElementById('include-descendants-toggle');
  const descendantsWrapper = document.getElementById('descendants-toggle-wrapper');
  descendantsToggle.checked = activeFilters.include_descendants;
  descendantsWrapper?.classList.toggle('active', descendantsToggle.checked);
  descendantsToggle.addEventListener('change', () => {
    activeFilters.include_descendants = descendantsToggle.checked;
    descendantsWrapper?.classList.toggle('active', descendantsToggle.checked);
    syncHashFromFilters();
    if (onChangeCallback) onChangeCallback();
  });

  // Clear all
  document.getElementById('clear-filters-btn').addEventListener('click', () => {
    activeFilters = {
      file_format: null,
      file_name: null,
      char_id: null,
      artist_id: null,
      char_unclassified: false,
      artist_unclassified: false,
      include_descendants: true,
    };
    filenameInput.value = '';
    document.getElementById('char-unclassified-toggle').checked = false;
    document.getElementById('artist-unclassified-toggle').checked = false;
    descendantsToggle.checked = true;
    descendantsWrapper?.classList.add('active');
    container.querySelectorAll('.filter-option').forEach((el) => el.classList.remove('active'));
    syncHashFromFilters();
    if (onChangeCallback) onChangeCallback();
  });

  await loadFormatOptions(container);
}

// Wires a 未分類 checkbox: syncs its initial checked/active state from
// activeFilters[filterKey], and on change updates that flag, clears the
// paired specific-id filter (a character/artist selection and "show
// unclassified" can't both apply), and re-syncs the hash.
function wireUnclassifiedToggle(toggleId, filterKey, pairedIdKey) {
  const toggle = document.getElementById(toggleId);
  const wrapper = toggle.closest('.filter-option');
  toggle.checked = activeFilters[filterKey];
  wrapper.classList.toggle('active', activeFilters[filterKey]);
  toggle.addEventListener('change', () => {
    activeFilters[filterKey] = toggle.checked;
    if (activeFilters[filterKey]) activeFilters[pairedIdKey] = null;
    wrapper.classList.toggle('active', activeFilters[filterKey]);
    syncHashFromFilters();
    if (onChangeCallback) onChangeCallback();
  });
}

function handleOptionClick(container, opt) {
  const filterKey = opt.dataset.filter;
  const filterValue = opt.dataset.value;

  if (activeFilters[filterKey] === filterValue) {
    activeFilters[filterKey] = null;
    opt.classList.remove('active');
  } else {
    container
      .querySelectorAll(`.filter-option[data-filter="${filterKey}"]`)
      .forEach((el) => el.classList.remove('active'));
    activeFilters[filterKey] = filterValue;
    opt.classList.add('active');
  }

  if (onChangeCallback) onChangeCallback();
}

function applyActiveClasses(container) {
  container.querySelectorAll('.filter-option[data-filter]').forEach((opt) => {
    const { filter, value } = opt.dataset;
    opt.classList.toggle('active', activeFilters[filter] === value);
  });
}

async function loadFormatOptions(container) {
  const section = document.getElementById('format-filter-section');
  try {
    const data = await getImageFormats();
    const formats = data.formats || [];

    section.innerHTML = `
      <div class="filter-section-title">圖片格式</div>
      ${formats
        .map(
          (fmt) => `
        <div class="filter-option" data-filter="file_format" data-value="${fmt}">
          <span>${fmt.replace('.', '').toUpperCase()}</span>
        </div>
      `
        )
        .join('')}
    `;
    applyActiveClasses(container);
  } catch (err) {
    section.innerHTML = `<div class="filter-section-title">圖片格式</div><p style="color: var(--error); font-size: 12px;">載入格式清單失敗</p>`;
  }
}

export function getActiveFilters() {
  const result = {};
  Object.entries(activeFilters).forEach(([key, value]) => {
    if (value !== null && value !== undefined && value !== false) {
      result[key] = value;
    }
  });
  // char_unclassified/artist_unclassified are UI-only concepts -- translate
  // into the char_id=0/artist_id=0 the backend already treats as a
  // meaningful exact filter (0 = 未分類), not "absent". Must force
  // include_descendants off: 0 is the tag tree's root, so expanding its
  // descendants matches literally every node (i.e. every image), which
  // defeats the filter entirely.
  if (activeFilters.char_unclassified || activeFilters.artist_unclassified) {
    result.include_descendants = false;
  }
  if (activeFilters.char_unclassified) result.char_id = 0;
  if (activeFilters.artist_unclassified) result.artist_id = 0;
  delete result.char_unclassified;
  delete result.artist_unclassified;
  return result;
}

// The raw current toggle value, unlike getActiveFilters() which omits it
// entirely when false (that's fine for building query params, since the
// backend already defaults to false when the param is absent, but callers
// that need to know the actual on/off state -- e.g. carrying it forward
// across a navigation -- need the real boolean).
export function isIncludeDescendants() {
  return activeFilters.include_descendants;
}

// Clears a single filter (e.g. from a removable chip) without touching any
// other filter, including include_descendants -- removing a character/artist
// filter this way intentionally leaves the user's descendants preference as
// they set it, ready to apply next time they pick a character/artist.
export function removeFilter(key) {
  if (!(key in activeFilters)) return;
  activeFilters[key] = null;

  if (key === 'file_name') {
    const filenameInput = document.getElementById('filename-search-input');
    if (filenameInput) filenameInput.value = '';
  }
  if (key === 'file_format' && panelContainer) {
    panelContainer
      .querySelectorAll(`.filter-option[data-filter="${key}"]`)
      .forEach((el) => el.classList.remove('active'));
  }
  if (key === 'char_id' || key === 'artist_id') {
    syncHashFromFilters();
  }
  if (key === 'char_unclassified' || key === 'artist_unclassified') {
    const toggleId = key === 'char_unclassified' ? 'char-unclassified-toggle' : 'artist-unclassified-toggle';
    const toggle = document.getElementById(toggleId);
    if (toggle) {
      toggle.checked = false;
      toggle.closest('.filter-option')?.classList.remove('active');
    }
  }

  if (onChangeCallback) onChangeCallback();
}

function restoreFiltersFromHash() {
  // activeFilters is module-level state that outlives a single page visit,
  // so a hash with no char_id/artist_id must actively clear any value left
  // over from a previous navigation, not just leave it untouched.
  const hash = window.location.hash;
  const params = hash.includes('?') ? new URLSearchParams(hash.split('?')[1]) : new URLSearchParams();

  activeFilters.char_id = params.get('char_id');
  activeFilters.artist_id = params.get('artist_id');
  // A hash-driven navigation to a specific character/artist (or a plain
  // visit with neither) always wins over a stale 未分類 toggle left on from
  // before this render -- the two concepts are mutually exclusive.
  activeFilters.char_unclassified = false;
  activeFilters.artist_unclassified = false;
  // Defaults to true (expand descendants) when the hash doesn't say
  // otherwise, so a plain visit -- and any navigation that forwards the
  // toggle's current value -- doesn't silently show an empty result for
  // series/artist nodes whose images live entirely on descendant nodes.
  activeFilters.include_descendants = params.has('include_descendants')
    ? params.get('include_descendants') === 'true'
    : true;
}

// Keeps the URL hash's char_id/artist_id/include_descendants in sync with
// activeFilters via replaceState (no hashchange, so no full page remount).
// Without this, removing a character/artist filter -- or flipping the
// descendants toggle -- only updates in-memory state; a later reload would
// re-read the stale hash via restoreFiltersFromHash() and silently bring
// the "removed" filter back.
function syncHashFromFilters() {
  const params = new URLSearchParams();
  if (activeFilters.char_id) params.set('char_id', activeFilters.char_id);
  if (activeFilters.artist_id) params.set('artist_id', activeFilters.artist_id);
  if (activeFilters.char_id || activeFilters.artist_id) {
    params.set('include_descendants', String(activeFilters.include_descendants));
  }
  const qs = params.toString();
  const newHash = `#/${qs ? `?${qs}` : ''}`;
  if (window.location.hash !== newHash) {
    history.replaceState(null, '', newHash);
  }
}
