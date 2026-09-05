/**
 * 圖像分類帽 — 掃描設定頁面
 */
import {
  getAvailableFolders,
  startScan,
  getScanProgress,
  getScanHistory,
  listCharacterTags,
  listIndividualTags,
  getImportRoot,
  setImportRoot,
  getRecordsDir,
  setRecordsDir,
} from '../api.js';
import { showToast } from '../app.js';

let pollingTimer = null;
let charFixedPicker = null;
let artistFixedPicker = null;

function wireCheckboxToggle(label, checkbox) {
  checkbox.addEventListener('change', () => {
    label.classList.toggle('checked', checkbox.checked);
  });
}

export async function renderScannerPage(container) {
  container.innerHTML = `
    <div class="scanner-container">
      <div class="scanner-card">
        <div class="scanner-card-title">🗂️ 導入根目錄</div>
        <div class="input-group">
          <label class="input-label">導入根目錄</label>
          <div style="display: flex; gap: var(--space-sm);">
            <input type="text" class="input-field" id="import-root-input" style="flex: 1;" />
            <button class="btn btn-secondary" id="save-import-root-btn">儲存</button>
          </div>
          <div class="input-hint">所有影像都相對於這個根目錄解析；圖庫資料夾搬家（例如搬到外接硬碟）後，只需要更新這裡</div>
        </div>
      </div>

      <div class="scanner-card">
        <div class="scanner-card-title">💾 紀錄目錄</div>
        <div class="input-group">
          <label class="input-label">紀錄目錄</label>
          <div style="display: flex; gap: var(--space-sm);">
            <input type="text" class="input-field" id="records-dir-input" style="flex: 1;" />
            <button class="btn btn-secondary" id="save-records-dir-btn">儲存</button>
          </div>
          <div class="input-hint">資料庫與作者備份的存放位置。跟導入根目錄不同，改這裡不會馬上生效——存檔後需要重新啟動後端才會套用新位置</div>
        </div>
      </div>

      <div class="scanner-card">
        <div class="scanner-card-title">📂 掃描設定</div>
        <div class="input-group">
          <label class="input-label">Sort 資料夾路徑</label>
          <input type="text" class="input-field" id="scan-root-path"
                 placeholder="例如：C:\\Users\\username\\Pictures\\sort" />
          <div class="input-hint">請輸入 sort 資料夾的絕對路徑</div>
        </div>
        <div class="input-group">
          <label class="input-label">選擇要掃描的分類資料夾</label>
          <div class="folder-checkboxes" id="folder-checkboxes">
            <div class="loading-screen" style="padding: 20px"><div class="loading-spinner"></div></div>
          </div>
          <!-- Independent of folder-checkboxes above: "other" has no tag tree /
               table, so it isn't part of GET /scan/folders's CONTAINERS-driven
               list -- it's a standalone scan scope, not a fourth container. -->
          <label class="folder-checkbox checked" style="margin-top: var(--space-sm);">
            <input type="checkbox" id="scan-include-other" checked />
            <div class="folder-checkbox-info">
              <div class="folder-checkbox-name">📄 其他位置</div>
              <div class="folder-checkbox-desc">掃描根目錄底下 characters／individuals 之外的所有影像（不分類，不建立 tag 節點）</div>
            </div>
          </label>
        </div>
      </div>

      <div class="scanner-card">
        <div class="scanner-card-title">🧑 角色設定</div>
        <div class="input-group" id="char-policy-options">
          <label class="input-label" style="display:flex; align-items:center; gap:6px; font-weight:normal;">
            <input type="radio" name="char-policy" value="folder" checked />
            依 characters 資料夾內路徑分類
          </label>
          <label class="input-label" style="display:flex; align-items:center; gap:6px; font-weight:normal;">
            <input type="radio" name="char-policy" value="fixed" />
            整批分類為指定角色
          </label>
          <label class="input-label" style="display:flex; align-items:center; gap:6px; font-weight:normal;">
            <input type="radio" name="char-policy" value="none" />
            不加上任何角色 tag
          </label>
          <div class="search-wrapper hidden" id="char-fixed-picker" style="margin-top: var(--space-sm);">
            <input type="text" class="search-input" id="char-fixed-picker-input"
                   placeholder="搜尋既有角色..." autocomplete="off" />
            <div class="search-suggestions hidden" id="char-fixed-picker-suggestions"></div>
          </div>
        </div>
      </div>

      <div class="scanner-card">
        <div class="scanner-card-title">🎨 作者設定</div>
        <div class="input-group" id="artist-policy-options">
          <label class="input-label" style="display:flex; align-items:center; gap:6px; font-weight:normal;">
            <input type="radio" name="artist-policy" value="folder" checked />
            依 individuals 底下的子資料夾名稱分類
          </label>
          <label class="input-label" style="display:flex; align-items:center; gap:6px; font-weight:normal;">
            <input type="radio" name="artist-policy" value="fixed" />
            整批分類為指定作者
          </label>
          <label class="input-label" style="display:flex; align-items:center; gap:6px; font-weight:normal;">
            <input type="radio" name="artist-policy" value="none" />
            不加上任何作者 tag
          </label>
          <div class="search-wrapper hidden" id="artist-fixed-picker" style="margin-top: var(--space-sm);">
            <input type="text" class="search-input" id="artist-fixed-picker-input"
                   placeholder="搜尋既有作者..." autocomplete="off" />
            <div class="search-suggestions hidden" id="artist-fixed-picker-suggestions"></div>
          </div>
        </div>
      </div>

      <div class="scanner-card">
        <button class="btn btn-primary" id="start-scan-btn" style="width: 100%;">
          🔍 開始掃描
        </button>
      </div>

      <!-- Progress Section -->
      <div class="scanner-card" id="scan-progress-card" style="display: none;">
        <div class="scanner-card-title">⏳ 掃描進度</div>
        <div class="progress-container">
          <div class="progress-bar-track">
            <div class="progress-bar-fill" id="scan-progress-bar" style="width: 0%"></div>
          </div>
          <div class="progress-info">
            <span id="scan-progress-text">準備中...</span>
            <span id="scan-progress-percent">0%</span>
          </div>
        </div>
        <div class="progress-stats" id="scan-progress-stats"></div>
        <div id="scan-conflicts" style="margin-top: var(--space-md);"></div>
        <div id="scan-errors" style="margin-top: var(--space-md);"></div>
      </div>

      <!-- History Section -->
      <div class="scanner-card">
        <div class="scanner-card-title">📋 掃描歷史</div>
        <div class="scan-history-list" id="scan-history-list">
          <div class="loading-screen" style="padding: 20px"><div class="loading-spinner"></div></div>
        </div>
      </div>
    </div>
  `;

  await loadFolderOptions();
  await loadScanHistory();
  await resumeIfScanning();
  await loadImportRoot();
  await loadRecordsDir();

  document.getElementById('save-import-root-btn').addEventListener('click', handleSaveImportRoot);
  document.getElementById('save-records-dir-btn').addEventListener('click', handleSaveRecordsDir);

  const includeOtherCheckbox = document.getElementById('scan-include-other');
  wireCheckboxToggle(includeOtherCheckbox.closest('.folder-checkbox'), includeOtherCheckbox);

  charFixedPicker = initFixedTargetPicker({
    inputId: 'char-fixed-picker-input',
    suggestionsId: 'char-fixed-picker-suggestions',
    // is_referenced=true: a real character (an existing image's char_id
    // actually points at it), not a series/container node -- character_tag
    // has no fixed depth, so unlike individual_tag this can't be inferred
    // from parent_id alone.
    fetchNodes: async (query) => {
      const data = await listCharacterTags({ search: query, per_page: 30, is_referenced: true });
      return data.nodes;
    },
  });
  artistFixedPicker = initFixedTargetPicker({
    inputId: 'artist-fixed-picker-input',
    suggestionsId: 'artist-fixed-picker-suggestions',
    // parent_id !== 0 excludes the root sentinel and the `individuals`
    // container node itself -- individual_tag is always exactly two levels
    // deep post-flattening, so this alone is a complete "real artist" filter.
    fetchNodes: async (query) => {
      const data = await listIndividualTags({ search: query, per_page: 30 });
      return data.nodes.filter((n) => n.parent_id !== 0);
    },
  });
  wirePolicyRadios('char-policy', 'char-fixed-picker', charFixedPicker);
  wirePolicyRadios('artist-policy', 'artist-fixed-picker', artistFixedPicker);

  document.getElementById('start-scan-btn').addEventListener('click', handleStartScan);
}

function wirePolicyRadios(radioName, pickerWrapperId, picker) {
  const wrapper = document.getElementById(pickerWrapperId);
  document.querySelectorAll(`input[name="${radioName}"]`).forEach((radio) => {
    radio.addEventListener('change', () => {
      wrapper.classList.toggle('hidden', radio.value !== 'fixed');
      if (radio.value !== 'fixed') picker.reset();
    });
  });
}

function getSelectedPolicyMode(radioName) {
  return document.querySelector(`input[name="${radioName}"]:checked`).value;
}

// A small type-ahead combobox local to this page: debounced search via
// fetchNodes, click-to-select, invalidated on further typing. Not reused
// from lightbox.js's artist picker -- this lives in normal page flow (no
// backdrop-filter ancestor to escape), so it doesn't need position:fixed or
// the reparenting that picker required.
function initFixedTargetPicker({ inputId, suggestionsId, fetchNodes }) {
  const input = document.getElementById(inputId);
  const suggestionsEl = document.getElementById(suggestionsId);
  let selected = null;
  let debounceTimer = null;

  input.addEventListener('input', () => {
    selected = null;
    clearTimeout(debounceTimer);
    const query = input.value.trim();
    if (query.length < 1) {
      suggestionsEl.classList.add('hidden');
      return;
    }

    debounceTimer = setTimeout(async () => {
      try {
        const nodes = await fetchNodes(query);
        if (nodes.length === 0) {
          suggestionsEl.classList.add('hidden');
          return;
        }

        suggestionsEl.innerHTML = nodes
          .map((n) => `<div class="search-suggestion-item" data-id="${n.id}" data-name="${n.name}"><span>${n.name}</span></div>`)
          .join('');
        suggestionsEl.classList.remove('hidden');

        suggestionsEl.querySelectorAll('.search-suggestion-item').forEach((item) => {
          item.addEventListener('click', () => {
            selected = { id: parseInt(item.dataset.id), name: item.dataset.name };
            input.value = item.dataset.name;
            suggestionsEl.classList.add('hidden');
          });
        });
      } catch (err) {
        suggestionsEl.classList.add('hidden');
      }
    }, 250);
  });

  document.addEventListener('click', (e) => {
    if (!input.parentElement.contains(e.target)) {
      suggestionsEl.classList.add('hidden');
    }
  });

  return {
    getSelected: () => selected,
    reset: () => {
      selected = null;
      input.value = '';
      suggestionsEl.classList.add('hidden');
    },
  };
}

async function resumeIfScanning() {
  try {
    const progress = await getScanProgress();
    if (progress.status !== 'scanning' && progress.status !== 'importing') return;

    document.getElementById('scan-progress-card').style.display = 'block';
    updateProgressUI(progress);

    const btn = document.getElementById('start-scan-btn');
    btn.disabled = true;
    btn.textContent = '⏳ 掃描中...';

    startPolling();
  } catch (err) {
    // Backend might be offline; loadFolderOptions already surfaces that error.
  }
}

async function loadImportRoot() {
  try {
    const { root_path } = await getImportRoot();
    document.getElementById('import-root-input').value = root_path;
    // Pre-fill only -- the scan-path field stays independently editable and
    // never writes back to the saved import root (see ADR-0004).
    document.getElementById('scan-root-path').value = root_path;
  } catch (err) {
    // loadFolderOptions already surfaces a backend-offline error; avoid a
    // second, redundant toast for the same underlying cause.
  }
}

async function handleSaveImportRoot() {
  const rootPath = document.getElementById('import-root-input').value.trim();
  if (!rootPath) {
    showToast('請輸入導入根目錄', 'error');
    return;
  }

  try {
    const result = await setImportRoot(rootPath);
    if (result.exists) {
      showToast('導入根目錄已儲存', 'success');
    } else {
      // Non-blocking per ADR-0004: e.g. an external drive that isn't
      // plugged in yet -- the setting is saved regardless.
      showToast('導入根目錄已儲存，但這個路徑目前不存在', 'info');
    }
  } catch (err) {
    showToast(`儲存失敗: ${err.message}`, 'error');
  }
}

async function loadRecordsDir() {
  try {
    const { records_dir } = await getRecordsDir();
    document.getElementById('records-dir-input').value = records_dir;
  } catch (err) {
    // loadFolderOptions already surfaces a backend-offline error; avoid a
    // second, redundant toast for the same underlying cause.
  }
}

async function handleSaveRecordsDir() {
  const recordsDir = document.getElementById('records-dir-input').value.trim();
  if (!recordsDir) {
    showToast('請輸入紀錄目錄', 'error');
    return;
  }

  try {
    const result = await setRecordsDir(recordsDir);
    // 不管路徑存不存在，都要提醒需要重啟——這跟導入根目錄不同，見 ADR-0008。
    if (result.exists) {
      showToast('紀錄目錄已儲存，重新啟動後端後生效', 'success');
    } else {
      showToast('紀錄目錄已儲存，但這個路徑目前不存在（重啟後會在這裡建立全新的空資料庫）', 'info');
    }
  } catch (err) {
    showToast(`儲存失敗: ${err.message}`, 'error');
  }
}

async function loadFolderOptions() {
  const container = document.getElementById('folder-checkboxes');
  try {
    const folders = await getAvailableFolders();
    const categoryEmojis = { game: '🎮', vt: '📺', individuals: '🎨', populars: '🌟' };

    container.innerHTML = Object.entries(folders)
      .map(
        ([name, config]) => `
        <label class="folder-checkbox checked">
          <input type="checkbox" value="${name}" checked />
          <div class="folder-checkbox-info">
            <div class="folder-checkbox-name">${categoryEmojis[name] || '📁'} ${config.label}</div>
            <div class="folder-checkbox-desc">${config.description}</div>
          </div>
        </label>
      `
      )
      .join('');

    container.querySelectorAll('.folder-checkbox').forEach((label) => {
      wireCheckboxToggle(label, label.querySelector('input[type="checkbox"]'));
    });
  } catch (err) {
    container.innerHTML = `<p style="color: var(--error); font-size: 13px;">載入資料夾設定失敗: ${err.message}</p>`;
  }
}

async function handleStartScan() {
  const rootPath = document.getElementById('scan-root-path').value.trim();
  if (!rootPath) {
    showToast('請輸入 sort 資料夾路徑', 'error');
    return;
  }

  const checkboxes = document.querySelectorAll('#folder-checkboxes input[type="checkbox"]:checked');
  const folders = Array.from(checkboxes).map((cb) => cb.value);
  const includeOther = document.getElementById('scan-include-other').checked;

  if (folders.length === 0 && !includeOther) {
    showToast('請至少選擇一個資料夾', 'error');
    return;
  }

  const charMode = getSelectedPolicyMode('char-policy');
  const artistMode = getSelectedPolicyMode('artist-policy');
  const charSelected = charFixedPicker.getSelected();
  const artistSelected = artistFixedPicker.getSelected();

  if (charMode === 'fixed' && !charSelected) {
    showToast('請先選擇要整批分類的角色', 'error');
    return;
  }
  if (artistMode === 'fixed' && !artistSelected) {
    showToast('請先選擇要整批分類的作者', 'error');
    return;
  }

  const charPolicy = { mode: charMode, fixedId: charSelected?.id };
  const artistPolicy = { mode: artistMode, fixedId: artistSelected?.id };

  const btn = document.getElementById('start-scan-btn');
  btn.disabled = true;
  btn.textContent = '⏳ 掃描中...';

  const progressCard = document.getElementById('scan-progress-card');
  progressCard.style.display = 'block';

  try {
    const result = await startScan(rootPath, folders, includeOther, charPolicy, artistPolicy);
    updateProgressUI(result.progress);

    const isActive = result.progress && ['scanning', 'importing'].includes(result.progress.status);

    if (result.error) {
      showToast(result.error, 'error');
      if (!isActive) {
        btn.disabled = false;
        btn.textContent = '🔍 開始掃描';
        return;
      }
    }

    // Non-blocking: purely informational, scan proceeds regardless.
    if (result.loose_individuals_count > 0) {
      showToast(`提醒：individuals/ 底下有 ${result.loose_individuals_count} 張影像未放入任何作者子資料夾，不會被分類作者`, 'info');
    }

    startPolling();
  } catch (err) {
    showToast(`掃描失敗: ${err.message}`, 'error');
    btn.disabled = false;
    btn.textContent = '🔍 開始掃描';
  }
}

function startPolling() {
  stopPolling();
  pollingTimer = setInterval(async () => {
    // Stop if the user navigated away from the scanner page.
    if (!document.getElementById('scan-progress-card')) {
      stopPolling();
      return;
    }

    try {
      const progress = await getScanProgress();
      updateProgressUI(progress);

      if (progress.status === 'completed' || progress.status === 'failed') {
        stopPolling();
        finishScan(progress);
      }
    } catch (err) {
      console.error('取得掃描進度失敗:', err);
    }
  }, 800);
}

function stopPolling() {
  if (pollingTimer) {
    clearInterval(pollingTimer);
    pollingTimer = null;
  }
}

function finishScan(progress) {
  const btn = document.getElementById('start-scan-btn');
  if (btn) {
    btn.disabled = false;
    btn.textContent = '🔍 開始掃描';
  }

  if (progress.status === 'completed') {
    showToast(`掃描完成！已處理 ${progress.processed_files} 個檔案`, 'success');
    window.dispatchEvent(new Event('refresh-stats'));
  } else {
    showToast('掃描失敗，請查看下方錯誤詳情', 'error');
  }

  loadScanHistory();
}

// Shared shape behind #scan-conflicts and #scan-errors: a collapsible count
// + list, or nothing when the list is empty.
function renderDetailsList(container, items, { color, summary }) {
  if (!items || items.length === 0) {
    container.innerHTML = '';
    return;
  }
  container.innerHTML = `
    <details style="font-size: 12px; color: var(--text-muted);">
      <summary style="cursor: pointer; color: ${color};">
        ${summary(items.length)}
      </summary>
      <ul style="list-style: none; margin-top: var(--space-xs);">
        ${items.map((item) => `<li style="padding: 2px 0; word-break: break-all;">• ${item}</li>`).join('')}
      </ul>
    </details>
  `;
}

function updateProgressUI(progress) {
  const bar = document.getElementById('scan-progress-bar');
  const text = document.getElementById('scan-progress-text');
  const percent = document.getElementById('scan-progress-percent');
  const stats = document.getElementById('scan-progress-stats');
  const conflicts = document.getElementById('scan-conflicts');
  const errors = document.getElementById('scan-errors');

  bar.style.width = `${progress.progress_percent}%`;
  percent.textContent = `${progress.progress_percent}%`;

  const statusMessages = {
    scanning: '掃描資料夾結構中...',
    importing: `匯入中... ${progress.current_file || ''}`,
    completed: '✅ 掃描完成！',
    failed: '❌ 掃描失敗',
    idle: '等待中',
  };
  text.textContent = statusMessages[progress.status] || progress.status;

  stats.innerHTML = `
    <div class="progress-stat">
      <div class="progress-stat-value">${progress.processed_files}${progress.total_files ? ' / ' + progress.total_files : ''}</div>
      <div class="progress-stat-label">已處理檔案</div>
    </div>
    <div class="progress-stat">
      <div class="progress-stat-value">${progress.total_characters}</div>
      <div class="progress-stat-label">角色</div>
    </div>
    <div class="progress-stat">
      <div class="progress-stat-value">${progress.total_franchises}</div>
      <div class="progress-stat-label">作品</div>
    </div>
    <div class="progress-stat">
      <div class="progress-stat-value">${progress.total_artists}</div>
      <div class="progress-stat-label">作者</div>
    </div>
    <div class="progress-stat">
      <div class="progress-stat-value">${progress.elapsed_seconds}s</div>
      <div class="progress-stat-label">耗時</div>
    </div>
  `;

  // Separate from errors below: a conflict is an image that imported fine
  // (using the existing/winning backup entry, not a failure) -- informational
  // and non-blocking, not a failure to surface alongside real errors.
  renderDetailsList(conflicts, progress.conflicts, {
    color: 'var(--info)',
    summary: (n) => `ℹ️ ${n} 筆作者分類衝突（已保留既有紀錄，詳見 data/scan_conflicts.log）`,
  });
  renderDetailsList(errors, progress.errors, {
    color: 'var(--warning)',
    summary: (n) => `⚠️ ${n} 個錯誤`,
  });
}

async function loadScanHistory() {
  const container = document.getElementById('scan-history-list');
  try {
    const data = await getScanHistory();

    if (data.history.length === 0) {
      container.innerHTML = '<p style="color: var(--text-muted); font-size: 13px; text-align: center; padding: var(--space-md);">尚無掃描紀錄</p>';
      return;
    }

    container.innerHTML = data.history
      .map(
        (h) => `
        <div class="scan-history-item">
          <div>
            <div style="font-weight: 500;">${h.folders_scanned || '—'}</div>
            <div style="font-size: 11px; color: var(--text-muted);">
              ${new Date(h.started_at).toLocaleString('zh-TW')} ·
              ${h.total_files_imported || 0} 檔案 ·
              ${h.total_characters_found || 0} 角色
            </div>
          </div>
          <span class="scan-history-status ${h.status}">${h.status === 'completed' ? '✓ 完成' : h.status === 'failed' ? '✗ 失敗' : '⟳ 進行中'}</span>
        </div>
      `
      )
      .join('');
  } catch (err) {
    container.innerHTML = `<p style="color: var(--error); font-size: 13px;">載入歷史失敗</p>`;
  }
}
