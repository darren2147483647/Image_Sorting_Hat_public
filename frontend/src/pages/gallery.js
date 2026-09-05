/**
 * 圖像分類帽 — 圖片瀏覽頁面
 */
import { listImages, getImageFileUrl, getImage, getCharacterTag, getIndividualTag } from '../api.js';
import { openLightbox } from '../components/lightbox.js';
import { renderFilterPanel, getActiveFilters, removeFilter } from '../components/filter-panel.js';
import { renderSearchBar } from '../components/search-bar.js';

let currentPage = 1;
let totalPages = 0;
let currentImages = [];
let activeFilterChipsSeq = 0;
let charChipCache = null; // { id, name } -- avoids re-fetching the same tag's name on every page turn
let artistChipCache = null;

function escapeHtml(str) {
  const div = document.createElement('div');
  div.textContent = str;
  return div.innerHTML;
}

export async function renderGalleryPage(container) {
  container.innerHTML = `
    <div class="gallery-container">
      <aside class="gallery-sidebar">
        <div id="search-bar-container"></div>
        <label class="filter-option" id="descendants-toggle-wrapper"
               style="cursor: pointer; margin-bottom: var(--space-lg);">
          <input type="checkbox" id="include-descendants-toggle" />
          <span>包含子孫節點</span>
        </label>
        <div id="filter-panel-container"></div>
      </aside>
      <div class="gallery-main">
        <div class="page-header">
          <div>
            <h1 class="page-title">圖片瀏覽</h1>
            <p class="page-subtitle" id="gallery-subtitle">載入中...</p>
          </div>
          <div class="filter-tags" id="active-filters"></div>
        </div>
        <div class="image-grid" id="image-grid"></div>
        <div id="gallery-pagination"></div>
      </div>
    </div>
  `;

  renderSearchBar(
    document.getElementById('search-bar-container'),
    handleSearchSelect
  );
  await renderFilterPanel(
    document.getElementById('filter-panel-container'),
    handleFilterChange
  );

  await loadImages();
}

async function loadImages(page = 1) {
  currentPage = page;
  const grid = document.getElementById('image-grid');
  const subtitle = document.getElementById('gallery-subtitle');

  grid.innerHTML = '<div class="loading-screen"><div class="loading-spinner"></div><p>載入圖片中...</p></div>';

  const filters = getActiveFilters();
  renderActiveFilterChips(filters);

  try {
    const params = {
      page,
      per_page: 50,
      ...filters,
    };

    const data = await listImages(params);

    // A page can go out of range without the user ever touching pagination
    // -- e.g. removing the last image on the last page via 移出追蹤. Rather
    // than showing a false "no images" empty state, snap back to the new
    // last page instead of rendering this one.
    if (data.images.length === 0 && data.total > 0 && page > data.total_pages) {
      await loadImages(data.total_pages);
      return;
    }

    currentImages = data.images;
    totalPages = data.total_pages;

    subtitle.textContent = `共 ${data.total.toLocaleString()} 張圖片`;

    if (data.images.length === 0) {
      grid.innerHTML = `
        <div class="empty-state" style="grid-column: 1 / -1">
          <div class="empty-state-icon">🖼️</div>
          <div class="empty-state-title">沒有找到圖片</div>
          <div class="empty-state-desc">
            ${data.total === 0
              ? '資料庫中還沒有圖片。請先到「掃描導入」頁面導入圖片。'
              : '嘗試調整篩選條件。'
            }
          </div>
        </div>
      `;
      document.getElementById('gallery-pagination').innerHTML = '';
      return;
    }

    grid.innerHTML = data.images
      .map((img, index) => renderImageCard(img, index))
      .join('');

    // Bind click events
    grid.querySelectorAll('.image-card').forEach((card) => {
      card.addEventListener('click', () => {
        const idx = parseInt(card.dataset.index);
        openLightbox(currentImages, idx, () => loadImages(currentPage));
      });
    });

    renderPagination(data.page, data.total_pages, data.total);
  } catch (err) {
    grid.innerHTML = `
      <div class="empty-state" style="grid-column: 1 / -1">
        <div class="empty-state-icon">⚠️</div>
        <div class="empty-state-title">載入失敗</div>
        <div class="empty-state-desc">${err.message}</div>
      </div>
    `;
  }
}

// Chips reflect only filters that narrow the image set (not sort/page).
// char_id/artist_id only carry an id, so their label needs a lookup against
// the tag tree; file_format/file_name are self-describing.
async function renderActiveFilterChips(filters) {
  const container = document.getElementById('active-filters');
  if (!container) return;

  const mySeq = ++activeFilterChipsSeq;

  const chips = [];
  // char_id/artist_id === 0 is the 未分類 toggles (root sentinel, never a
  // real selectable character/artist id) -- checked first since `0` is
  // falsy and would otherwise fall through the plain truthy checks below.
  if (filters.char_id === 0) {
    chips.push({ removable: true, key: 'char_unclassified', icon: '👤', resolve: () => Promise.resolve('角色未分類') });
  } else if (filters.char_id) {
    chips.push({
      removable: true,
      key: 'char_id',
      icon: '👤',
      resolve: async () => {
        if (charChipCache?.id === filters.char_id) return charChipCache.name;
        const t = await getCharacterTag(filters.char_id);
        charChipCache = { id: filters.char_id, name: t.name };
        return t.name;
      },
    });
  }
  if (filters.artist_id === 0) {
    chips.push({ removable: true, key: 'artist_unclassified', icon: '🎨', resolve: () => Promise.resolve('作者未分類') });
  } else if (filters.artist_id) {
    chips.push({
      removable: true,
      key: 'artist_id',
      icon: '🎨',
      resolve: async () => {
        if (artistChipCache?.id === filters.artist_id) return artistChipCache.name;
        const t = await getIndividualTag(filters.artist_id);
        artistChipCache = { id: filters.artist_id, name: t.name };
        return t.name;
      },
    });
  }
  if (filters.file_format) {
    const text = `格式：${filters.file_format.replace('.', '').toUpperCase()}`;
    chips.push({ removable: true, key: 'file_format', resolve: () => Promise.resolve(text) });
  }
  if (filters.file_name) {
    // No remove control: the filename filter is a live/debounced text
    // input, and a chip-driven removal would risk drifting out of sync
    // with whatever text is still sitting in that input.
    const text = `檔名：${filters.file_name}`;
    chips.push({ removable: false, key: 'file_name', resolve: () => Promise.resolve(text) });
  }

  if (chips.length === 0) {
    container.innerHTML = '';
    return;
  }

  const texts = await Promise.all(chips.map((c) => c.resolve().catch(() => null)));
  if (mySeq !== activeFilterChipsSeq) return; // superseded by a newer filter change

  // Tag names come from scanned folder names (user-renameable), so they're
  // untrusted and go through escapeHtml() before landing in innerHTML.
  container.innerHTML = chips
    .map((c, i) => {
      if (texts[i] == null) return '';
      const prefix = c.icon ? `${c.icon} ` : '';
      const removeBtn = c.removable
        ? `<span class="filter-tag-remove" data-remove-filter="${c.key}" title="移除">&times;</span>`
        : '';
      return `<span class="filter-tag">${prefix}${escapeHtml(texts[i])}${removeBtn}</span>`;
    })
    .join('');

  container.querySelectorAll('[data-remove-filter]').forEach((btn) => {
    btn.addEventListener('click', () => removeFilter(btn.dataset.removeFilter));
  });
}

function renderImageCard(img, index) {
  const tags = img.character_tags || [];
  const artists = img.artist_tags || [];

  const tagBadges = [
    ...tags.map(
      (t) =>
        `<span class="tag-badge character">${t.name}</span>`
    ),
    ...artists.map(
      (a) =>
        `<span class="tag-badge artist">${a.name}</span>`
    ),
  ].join('');

  return `
    <div class="image-card" data-index="${index}" data-id="${img.id}">
      <img src="${getImageFileUrl(img.id)}"
           alt="${img.file_name}"
           loading="lazy"
           onerror="this.src='data:image/svg+xml,<svg xmlns=%22http://www.w3.org/2000/svg%22 viewBox=%220 0 100 100%22><rect fill=%22%231a1a2e%22 width=%22100%22 height=%22100%22/><text x=%2250%22 y=%2250%22 text-anchor=%22middle%22 dy=%22.3em%22 fill=%22%2364748b%22 font-size=%2220%22>⚠️</text></svg>'" />
      <div class="image-card-overlay">
        ${tagBadges}
      </div>
    </div>
  `;
}

function renderPagination(page, totalPages, total) {
  const container = document.getElementById('gallery-pagination');
  if (totalPages <= 1) {
    container.innerHTML = '';
    return;
  }

  const maxVisible = 7;
  let pages = [];

  if (totalPages <= maxVisible) {
    pages = Array.from({ length: totalPages }, (_, i) => i + 1);
  } else {
    pages = [1];
    let start = Math.max(2, page - 2);
    let end = Math.min(totalPages - 1, page + 2);

    if (start > 2) pages.push('...');
    for (let i = start; i <= end; i++) pages.push(i);
    if (end < totalPages - 1) pages.push('...');
    pages.push(totalPages);
  }

  container.innerHTML = `
    <div class="pagination">
      <button class="pagination-btn" ${page <= 1 ? 'disabled' : ''} data-page="${page - 1}">‹ 上一頁</button>
      ${pages
        .map((p) =>
          p === '...'
            ? '<span class="pagination-info">…</span>'
            : `<button class="pagination-btn ${p === page ? 'active' : ''}" data-page="${p}">${p}</button>`
        )
        .join('')}
      <button class="pagination-btn" ${page >= totalPages ? 'disabled' : ''} data-page="${page + 1}">下一頁 ›</button>
      <span class="pagination-jump">
        <input type="number" class="input-field" id="pagination-jump-input"
               min="1" max="${totalPages}" placeholder="頁碼" style="width: 70px;" />
        <button class="btn btn-secondary btn-sm" id="pagination-jump-btn">跳至</button>
      </span>
      <span class="pagination-info">共 ${total.toLocaleString()} 張</span>
    </div>
  `;

  container.querySelectorAll('.pagination-btn:not([disabled])').forEach((btn) => {
    btn.addEventListener('click', () => {
      const targetPage = parseInt(btn.dataset.page);
      if (targetPage && targetPage !== currentPage) {
        loadImages(targetPage);
        window.scrollTo({ top: 0, behavior: 'smooth' });
      }
    });
  });

  const jumpInput = document.getElementById('pagination-jump-input');
  const jumpToInputValue = () => {
    const raw = parseInt(jumpInput.value);
    if (!raw) return;
    const target = Math.min(Math.max(raw, 1), totalPages);
    if (target !== currentPage) {
      loadImages(target);
      window.scrollTo({ top: 0, behavior: 'smooth' });
    }
    jumpInput.value = '';
  };
  document.getElementById('pagination-jump-btn').addEventListener('click', jumpToInputValue);
  jumpInput.addEventListener('keydown', (e) => {
    if (e.key === 'Enter') jumpToInputValue();
  });
}

function handleSearchSelect(result) {
  // Apply search as filter
  if (result.type === 'character') {
    loadImages(1);
  }
}

function handleFilterChange() {
  loadImages(1);
}
