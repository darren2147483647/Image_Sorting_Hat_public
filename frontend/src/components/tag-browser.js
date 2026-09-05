/**
 * 圖像分類帽 — Tag 節點瀏覽頁面共用元件
 *
 * character_tags／individual_tags 兩個端點回傳完全同樣的形狀（has_children／
 * is_referenced／direct_image_count／total_image_count），角色管理／作品管理／
 * 作者管理三個頁面都是同一種瀏覽介面，差別只在呼叫哪個 API、用哪個附加篩選條件、
 * 導覽到圖片瀏覽頁時要用 char_id 還是 artist_id。
 */
let state = {};
let requestSeq = 0;

const SORT_STORAGE_KEY = 'tagBrowserSort';
// Must match the <option value="{sortBy}-{sortOrder}"> combinations in the
// select below, and what the backend's sort_by/sort_order Query patterns
// accept -- a stray stored value would otherwise 422 every request.
const VALID_SORT_BY = ['name', 'image_count'];
const VALID_SORT_ORDER = ['asc', 'desc'];

function escapeHtml(str) {
  const div = document.createElement('div');
  div.textContent = str;
  return div.innerHTML;
}

// Shared across the character/franchise/artist management pages (they all
// render this same component), so the sort a user picks on any one of them
// carries over to the others rather than each page tracking its own.
function loadStoredSort() {
  try {
    const raw = localStorage.getItem(SORT_STORAGE_KEY);
    const parsed = raw ? JSON.parse(raw) : null;
    if (parsed && VALID_SORT_BY.includes(parsed.sortBy) && VALID_SORT_ORDER.includes(parsed.sortOrder)) {
      return parsed;
    }
  } catch (err) {
    // localStorage unavailable (private browsing, disabled) or corrupt value
    // -- fall through to the default sort below.
  }
  return null;
}

function saveStoredSort(sortBy, sortOrder) {
  try {
    localStorage.setItem(SORT_STORAGE_KEY, JSON.stringify({ sortBy, sortOrder }));
  } catch (err) {
    // Storage unavailable -- the sort choice just won't persist this time.
  }
}

export async function renderTagBrowserPage(container, config) {
  const storedSort = loadStoredSort();
  state = {
    page: 1,
    config,
    search: '',
    sortBy: storedSort ? storedSort.sortBy : 'name',
    sortOrder: storedSort ? storedSort.sortOrder : 'asc',
  };

  container.innerHTML = `
    <div class="page-header">
      <div>
        <h1 class="page-title">${config.title}</h1>
        <p class="page-subtitle" id="tag-browser-subtitle">載入中...</p>
      </div>
      <div style="display: flex; gap: var(--space-sm); align-items: center;">
        <input type="text" class="input-field" id="tag-browser-search"
               placeholder="搜尋${config.nounLabel}名稱..." style="width: 250px;" />
        <select class="input-field" id="tag-browser-sort" style="width: 160px;">
          <option value="name-asc">名稱 A→Z</option>
          <option value="name-desc">名稱 Z→A</option>
          <option value="image_count-desc">圖片數 多→少</option>
          <option value="image_count-asc">圖片數 少→多</option>
        </select>
      </div>
    </div>
    <div class="character-grid" id="tag-browser-grid"></div>
    <div id="tag-browser-pagination"></div>
  `;

  document.getElementById('tag-browser-sort').value = `${state.sortBy}-${state.sortOrder}`;

  const searchInput = document.getElementById('tag-browser-search');
  let debounceTimer;
  searchInput.addEventListener('input', () => {
    clearTimeout(debounceTimer);
    debounceTimer = setTimeout(() => {
      state.search = searchInput.value.trim();
      loadNodes(1);
    }, 300);
  });

  document.getElementById('tag-browser-sort').addEventListener('change', (e) => {
    const [sortBy, sortOrder] = e.target.value.split('-');
    state.sortBy = sortBy;
    state.sortOrder = sortOrder;
    saveStoredSort(sortBy, sortOrder);
    loadNodes(1);
  });

  await loadNodes(1);
}

async function loadNodes(page) {
  state.page = page;
  const { config } = state;
  const grid = document.getElementById('tag-browser-grid');
  const subtitle = document.getElementById('tag-browser-subtitle');

  // Guards against out-of-order responses: search (debounced) and sort
  // (immediate) can both trigger a fetch in quick succession, and network
  // timing doesn't guarantee they resolve in the order they were sent.
  // Only the response matching the latest request actually gets applied.
  const mySeq = ++requestSeq;

  grid.innerHTML = '<div class="loading-screen" style="grid-column:1/-1"><div class="loading-spinner"></div></div>';

  try {
    const data = await config.listFn({
      page,
      per_page: 48,
      search: state.search || null,
      sort_by: state.sortBy,
      sort_order: state.sortOrder,
      ...config.listFilter,
    });

    if (mySeq !== requestSeq) return; // a newer request has since superseded this one

    subtitle.textContent = `共 ${data.total.toLocaleString()} 個${config.nounLabel}`;

    if (data.nodes.length === 0) {
      grid.innerHTML = `
        <div class="empty-state" style="grid-column: 1 / -1">
          <div class="empty-state-icon">${config.emptyIcon}</div>
          <div class="empty-state-title">沒有找到${config.nounLabel}</div>
          <div class="empty-state-desc">
            ${data.total === 0 ? '資料庫中還沒有資料。請先導入圖片。' : '嘗試調整搜尋條件。'}
          </div>
        </div>
      `;
      document.getElementById('tag-browser-pagination').innerHTML = '';
      return;
    }

    grid.innerHTML = data.nodes.map((node) => renderNodeCard(node, config)).join('');

    grid.querySelectorAll('.character-card').forEach((card) => {
      card.addEventListener('click', () => {
        const id = card.dataset.id;
        window.location.hash = `#/?${config.filterParamName}=${id}&include_descendants=true`;
      });
    });

    renderPagination(data.page, data.total_pages, data.total);
  } catch (err) {
    if (mySeq !== requestSeq) return;
    grid.innerHTML = `
      <div class="empty-state" style="grid-column: 1 / -1">
        <div class="empty-state-icon">⚠️</div>
        <div class="empty-state-title">載入失敗</div>
        <div class="empty-state-desc">${err.message}</div>
      </div>
    `;
  }
}

function renderNodeCard(node, config) {
  // has_children is a structural fact (does this node group other nodes
  // underneath it) -- not the same thing as "系列" (per CONTEXT.md, any
  // non-root node), which every card on 作品管理 already satisfies just by
  // being listed there. Label it as what it actually says, so a childless
  // series like 碧藍幻想 doesn't look like it's missing a badge it should have.
  const badges = [
    node.has_children ? '<span class="tag-badge">📂 有子節點</span>' : '',
    node.is_referenced ? '<span class="tag-badge character">🏷️ 角色</span>' : '',
  ].join('');

  // parent_id 0 is the sentinel root, not a real series -- don't show it.
  const parentLine =
    node.parent_id && node.parent_id !== 0
      ? `<div class="character-card-franchise">屬於：${escapeHtml(node.parent_name)}</div>`
      : '';

  return `
    <div class="character-card" data-id="${node.id}">
      <div class="character-card-name">${escapeHtml(node.name)}</div>
      ${parentLine}
      <div class="character-card-franchise">${badges}</div>
      <div class="character-card-stats">
        <div class="character-card-stat">
          <strong>${node.direct_image_count}</strong> 張圖片（直接）
        </div>
        <div class="character-card-stat">
          <strong>${node.total_image_count}</strong> 張圖片（含子孫）
        </div>
      </div>
    </div>
  `;
}

function renderPagination(page, totalPages, total) {
  const container = document.getElementById('tag-browser-pagination');
  if (totalPages <= 1) {
    container.innerHTML = '';
    return;
  }

  container.innerHTML = `
    <div class="pagination">
      <button class="pagination-btn" ${page <= 1 ? 'disabled' : ''} data-page="${page - 1}">‹</button>
      <span class="pagination-info">${page} / ${totalPages}（共 ${total} 個）</span>
      <button class="pagination-btn" ${page >= totalPages ? 'disabled' : ''} data-page="${page + 1}">›</button>
    </div>
  `;

  container.querySelectorAll('.pagination-btn:not([disabled])').forEach((btn) => {
    btn.addEventListener('click', () => {
      loadNodes(parseInt(btn.dataset.page));
      window.scrollTo({ top: 0, behavior: 'smooth' });
    });
  });
}
