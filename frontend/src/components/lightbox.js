/**
 * 圖像分類帽 — Lightbox 大圖檢視元件
 */
import {
  getImageFileUrl,
  deleteImageRecord,
  addArtistTag,
  listIndividualTags,
  createIndividualTag,
  addCharacterTag,
  createCharacterTag,
  listCharacterTags,
} from '../api.js';
import { showToast } from '../app.js';

let currentImages = [];
let currentIndex = 0;
let isOpen = false;
let onListChanged = null;
let artistPickerDebounce = null;
let characterPickerDebounce = null;
let characterParentDebounce = null;
// The parent node picked (or not) for the NEXT "+新增" character creation --
// null means "use the backend default (the `characters` node)". Reset every
// time the character picker opens/closes so a stale pick from a previous
// image/session can never silently apply to a different creation.
let selectedCharacterParent = null;

export function initLightbox() {
  const lightbox = document.getElementById('lightbox');
  const overlay = lightbox.querySelector('.lightbox-overlay');
  const closeBtn = document.getElementById('lightbox-close');
  const prevBtn = document.getElementById('lightbox-prev');
  const nextBtn = document.getElementById('lightbox-next');
  const removeBtn = document.getElementById('lightbox-remove-tracking');

  overlay.addEventListener('click', closeLightbox);
  closeBtn.addEventListener('click', closeLightbox);
  prevBtn.addEventListener('click', showPrev);
  nextBtn.addEventListener('click', showNext);
  removeBtn.addEventListener('click', handleRemoveFromTracking);
  initArtistPicker();
  initCharacterPicker();

  // Keyboard navigation
  document.addEventListener('keydown', (e) => {
    if (!isOpen) return;
    // Typing in the artist picker (e.g. moving the cursor with arrow keys)
    // must not also navigate the lightbox to a different image -- the
    // picker's assign action targets currentIndex, so a navigation while
    // it's open would assign to the wrong image on the next click.
    if (e.target.tagName === 'INPUT' || e.target.tagName === 'TEXTAREA') return;
    switch (e.key) {
      case 'Escape':
        closeLightbox();
        break;
      case 'ArrowLeft':
        showPrev();
        break;
      case 'ArrowRight':
        showNext();
        break;
    }
  });
}

export function openLightbox(images, index, onChanged) {
  currentImages = images;
  currentIndex = index;
  isOpen = true;
  // Called (no arguments) after anything that changes what this list should
  // show -- a successful "移出追蹤" delete or a successful 指定作者 -- so the
  // caller (the page that opened this lightbox) can refresh its own list.
  // This module only owns what's shown inside the lightbox itself.
  onListChanged = onChanged || null;

  const lightbox = document.getElementById('lightbox');
  lightbox.classList.remove('hidden');
  document.body.style.overflow = 'hidden';

  showImage();
}

export function closeLightbox() {
  isOpen = false;
  const lightbox = document.getElementById('lightbox');
  lightbox.classList.add('hidden');
  document.body.style.overflow = '';
  // suggestionsEl is reparented to <body> (see initArtistPicker), so it's no
  // longer a descendant of #lightbox -- hiding the lightbox no longer hides
  // it as a side effect, unlike before the reparent.
  closeArtistPicker();
  closeCharacterPicker();
}

function showPrev() {
  if (currentIndex > 0) {
    currentIndex--;
    showImage();
  }
}

function showNext() {
  if (currentIndex < currentImages.length - 1) {
    currentIndex++;
    showImage();
  }
}

function showImage() {
  const img = currentImages[currentIndex];
  if (!img) return;

  // Navigating to a different image (prev/next, or after this image's own
  // assignment just re-rendered) must never leave a picker open on stale
  // state -- otherwise a suggestion click after navigating would assign to
  // whatever image is now showing, not the one the picker was opened for.
  closeArtistPicker();
  closeCharacterPicker();

  const imageEl = document.getElementById('lightbox-image');
  const filenameEl = document.getElementById('lightbox-filename');
  const tagsEl = document.getElementById('lightbox-tags');
  const metaEl = document.getElementById('lightbox-meta');
  const prevBtn = document.getElementById('lightbox-prev');
  const nextBtn = document.getElementById('lightbox-next');

  // Show loading state
  imageEl.style.opacity = '0.3';
  imageEl.src = getImageFileUrl(img.id);
  imageEl.onload = () => {
    imageEl.style.opacity = '1';
  };
  imageEl.alt = img.file_name;

  filenameEl.textContent = img.file_name;

  // Build tag badges
  const charTags = (img.character_tags || [])
    .map((t) => `<span class="tag-badge character">👤 ${t.name}</span>`)
    .join('');
  const artistTags = (img.artist_tags || [])
    .map((a) => `<span class="tag-badge artist">🎨 ${a.name}</span>`)
    .join('');

  tagsEl.innerHTML = charTags + artistTags || '<span style="color: var(--text-muted); font-size: 12px;">無標註</span>';

  // Meta info
  const parts = [];
  if (img.image_width && img.image_height) {
    parts.push(`${img.image_width} × ${img.image_height}`);
  }
  if (img.file_size) {
    parts.push(formatFileSize(img.file_size));
  }
  if (img.file_format) {
    parts.push(img.file_format.toUpperCase());
  }
  if (img.source_folder) {
    const labels = { characters: '🧑 角色/系列', individuals: '🎨 個人作者', other: '📄 其他位置' };
    parts.push(labels[img.source_folder] || img.source_folder);
  }
  parts.push(`${currentIndex + 1} / ${currentImages.length}`);
  metaEl.textContent = parts.join(' · ');

  // Nav button visibility
  prevBtn.style.visibility = currentIndex > 0 ? 'visible' : 'hidden';
  nextBtn.style.visibility = currentIndex < currentImages.length - 1 ? 'visible' : 'hidden';
}

async function handleRemoveFromTracking() {
  const img = currentImages[currentIndex];
  if (!img) return;

  // artist_id is always manually recorded now (never folder-derived), backed
  // up server-side by file_hash (see backend/artist_backup.py) precisely so
  // deleting the row here doesn't lose it -- a later rescan reapplies it.
  // char_id needs no equivalent note: it's always folder-derived, so 移出追蹤
  // followed by a rescan is exactly how it's *meant* to be changed.
  const hasManualArtist = (img.artist_tags || []).length > 0;
  const artistWarning = hasManualArtist
    ? `\n\n這張圖已經手動指定過作者「${img.artist_tags[0].name}」，移出追蹤後這個分類會從資料庫消失，但已備份到本機的分類記錄檔——把檔案移到正確位置後重新掃描，會自動套用回來。`
    : '';
  const confirmed = window.confirm(
    `確定要把「${img.file_name}」移出追蹤嗎？\n\n` +
      '這只會刪除資料庫紀錄，不會刪除實體檔案。之後把檔案移到正確的資料夾、重新觸發掃描，就會依新位置重新分類。' +
      artistWarning
  );
  if (!confirmed) return;

  const removeBtn = document.getElementById('lightbox-remove-tracking');
  removeBtn.disabled = true;
  try {
    await deleteImageRecord(img.id);
  } catch (err) {
    showToast(`移出追蹤失敗：${err.message}`, 'error');
    return;
  } finally {
    removeBtn.disabled = false;
  }

  showToast('已移出追蹤', 'success');
  currentImages.splice(currentIndex, 1);
  if (onListChanged) onListChanged();

  if (currentImages.length === 0) {
    closeLightbox();
    return;
  }
  if (currentIndex >= currentImages.length) currentIndex = currentImages.length - 1;
  showImage();
}

// Wires the 指定作者 picker: toggle button open/close, debounced search
// against /individual-tags, click-to-assign via addArtistTag, and inline
// "+新增" create-then-assign when there's no exact existing match. New
// logic local to this module rather than reusing search-bar.js -- that
// component's onSelect always also navigates via window.location.hash as a
// side effect, which isn't wanted here.
function closeArtistPicker() {
  const picker = document.getElementById('lightbox-artist-picker');
  const input = document.getElementById('lightbox-artist-picker-input');
  const suggestionsEl = document.getElementById('lightbox-artist-picker-suggestions');
  picker.classList.add('hidden');
  suggestionsEl.classList.add('hidden');
  input.value = '';
}

function closeCharacterPicker() {
  const picker = document.getElementById('lightbox-character-picker');
  const input = document.getElementById('lightbox-character-picker-input');
  const suggestionsEl = document.getElementById('lightbox-character-picker-suggestions');
  const parentInput = document.getElementById('lightbox-character-parent-input');
  const parentSuggestionsEl = document.getElementById('lightbox-character-parent-suggestions');
  picker.classList.add('hidden');
  suggestionsEl.classList.add('hidden');
  parentSuggestionsEl.classList.add('hidden');
  input.value = '';
  parentInput.value = '';
  selectedCharacterParent = null;
}

function escapeHtml(str) {
  const div = document.createElement('div');
  div.textContent = str;
  return div.innerHTML;
}

// position:fixed (see index.css) needs its coordinates computed from the
// input's current on-screen position -- recomputed on every show since the
// lightbox's own layout can vary per image. The input sits inside
// .lightbox-info, a panel capped near the bottom of the viewport, so it can
// be too close to the bottom edge for the list to fit below it -- flip to
// anchor above the input instead when there isn't room, standard combobox
// behaviour. suggestionsEl must already have its final content (and be
// visible, not display:none) before this runs, since flipping needs to know
// how tall the content actually wants to be.
function positionSuggestions(input, suggestionsEl) {
  suggestionsEl.classList.remove('hidden');
  suggestionsEl.style.top = 'auto';
  suggestionsEl.style.bottom = 'auto';

  const rect = input.getBoundingClientRect();
  suggestionsEl.style.left = `${rect.left}px`;
  suggestionsEl.style.width = `${rect.width}px`;

  const contentHeight = Math.min(suggestionsEl.scrollHeight, 300); // 300 matches index.css's max-height
  const spaceBelow = window.innerHeight - rect.bottom;
  const spaceAbove = rect.top;
  const flipUp = spaceBelow < contentHeight + 4 && spaceAbove > spaceBelow;

  if (flipUp) {
    suggestionsEl.style.bottom = `${window.innerHeight - rect.top + 4}px`;
  } else {
    suggestionsEl.style.top = `${rect.bottom + 4}px`;
  }
}

function initArtistPicker() {
  const toggleBtn = document.getElementById('lightbox-assign-artist');
  const picker = document.getElementById('lightbox-artist-picker');
  const input = document.getElementById('lightbox-artist-picker-input');
  const suggestionsEl = document.getElementById('lightbox-artist-picker-suggestions');

  // .lightbox-info (an ancestor) has backdrop-filter for its glass effect --
  // per spec, filter/backdrop-filter/transform on an ancestor creates a new
  // containing block for position:fixed descendants, silently trapping this
  // element's "fixed" positioning relative to .lightbox-info instead of the
  // viewport, which then clips it via .lightbox-info's own overflow-y:auto.
  // Moving it out to a direct child of <body> escapes that permanently,
  // regardless of any future filter/transform on any ancestor in between.
  document.body.appendChild(suggestionsEl);

  toggleBtn.addEventListener('click', () => {
    if (picker.classList.contains('hidden')) {
      closeCharacterPicker();
      picker.classList.remove('hidden');
      input.focus();
    } else {
      closeArtistPicker();
    }
  });

  input.addEventListener('input', () => {
    clearTimeout(artistPickerDebounce);
    const query = input.value.trim();
    if (query.length < 1) {
      suggestionsEl.classList.add('hidden');
      return;
    }

    artistPickerDebounce = setTimeout(async () => {
      try {
        // /individual-tags is dedicated to individual_tag -- unlike the old
        // /search/suggest (mixed character/franchise/artist results sharing
        // one truncated limit), nothing here can crowd artist matches out.
        // parent_id !== 0 excludes both the root sentinel and the
        // `individuals` container node itself (a real, non-root row after
        // the individual_tag flattening), leaving only real artists.
        const data = await listIndividualTags({ search: query, per_page: 30 });
        const artists = data.nodes.filter((n) => n.parent_id !== 0);

        const normalizedQuery = query.toLowerCase();
        const hasExactMatch = artists.some((a) => a.name.toLowerCase() === normalizedQuery);

        let itemsHtml = artists
          .map((s) => `<div class="search-suggestion-item" data-type="artist" data-id="${s.id}" data-name="${escapeHtml(s.name)}"><span>🎨 ${escapeHtml(s.name)}</span></div>`)
          .join('');
        if (!hasExactMatch) {
          itemsHtml += `<div class="search-suggestion-item search-suggestion-create" data-type="create" data-create-name="${escapeHtml(query)}"><span>+ 新增「${escapeHtml(query)}」</span></div>`;
        }

        if (!itemsHtml) {
          suggestionsEl.classList.add('hidden');
          return;
        }

        suggestionsEl.innerHTML = itemsHtml;
        positionSuggestions(input, suggestionsEl); // also unhides it -- needs real content height first

        suggestionsEl.querySelectorAll('.search-suggestion-item').forEach((item) => {
          item.addEventListener('click', () => {
            if (item.dataset.type === 'create') {
              handleCreateAndAssignArtist(item.dataset.createName);
            } else {
              handleAssignArtist(item.dataset.id, item.dataset.name);
            }
          });
        });
      } catch (err) {
        suggestionsEl.classList.add('hidden');
      }
    }, 250);
  });

  // The global lightbox keydown listener already ignores every keydown
  // targeting an INPUT/TEXTAREA (see initLightbox), so Escape here never
  // reaches it in the first place -- no stopPropagation needed, this is
  // purely "Escape while this input is focused closes the picker."
  input.addEventListener('keydown', (e) => {
    if (e.key === 'Escape') closeArtistPicker();
  });

  document.addEventListener('click', (e) => {
    // suggestionsEl is reparented to <body> (see above), so it's no longer
    // inside `picker` -- must be checked separately or every click on a
    // suggestion would also match "outside click" and hide the list, racing
    // with (and on a failed assignment, wrongly overriding) the item's own
    // click handler.
    if (!picker.contains(e.target) && !suggestionsEl.contains(e.target) && e.target !== toggleBtn) {
      suggestionsEl.classList.add('hidden');
    }
  });
}

// Wires the 指定角色 picker: same shape as initArtistPicker (toggle, debounced
// search, click-to-assign, inline "+新增"), plus a second, always-visible
// input for the new character's parent node -- character_tag has arbitrary
// depth (unlike individual_tag's fixed two levels, see ADR-0006), so
// creating one needs to know where to put it. The parent field only matters
// for the "+新增" path; clicking an existing suggestion ignores it entirely
// since that node's position is already resolved.
function initCharacterPicker() {
  const toggleBtn = document.getElementById('lightbox-assign-character');
  const picker = document.getElementById('lightbox-character-picker');
  const input = document.getElementById('lightbox-character-picker-input');
  const suggestionsEl = document.getElementById('lightbox-character-picker-suggestions');
  const parentInput = document.getElementById('lightbox-character-parent-input');
  const parentSuggestionsEl = document.getElementById('lightbox-character-parent-suggestions');

  // Same backdrop-filter escape as initArtistPicker -- see its comment.
  document.body.appendChild(suggestionsEl);
  document.body.appendChild(parentSuggestionsEl);

  toggleBtn.addEventListener('click', () => {
    if (picker.classList.contains('hidden')) {
      closeArtistPicker();
      picker.classList.remove('hidden');
      input.focus();
    } else {
      closeCharacterPicker();
    }
  });

  input.addEventListener('input', () => {
    clearTimeout(characterPickerDebounce);
    const query = input.value.trim();
    if (query.length < 1) {
      suggestionsEl.classList.add('hidden');
      return;
    }

    characterPickerDebounce = setTimeout(async () => {
      try {
        const data = await listCharacterTags({ search: query, per_page: 30 });
        const nodes = data.nodes;

        const normalizedQuery = query.toLowerCase();
        const hasExactMatch = nodes.some((n) => n.name.toLowerCase() === normalizedQuery);

        let itemsHtml = nodes
          .map((n) => `<div class="search-suggestion-item" data-type="character" data-id="${n.id}" data-name="${escapeHtml(n.name)}"><span>👤 ${escapeHtml(n.name)}</span></div>`)
          .join('');
        if (!hasExactMatch) {
          itemsHtml += `<div class="search-suggestion-item search-suggestion-create" data-type="create" data-create-name="${escapeHtml(query)}"><span>+ 新增「${escapeHtml(query)}」</span></div>`;
        }

        if (!itemsHtml) {
          suggestionsEl.classList.add('hidden');
          return;
        }

        suggestionsEl.innerHTML = itemsHtml;
        positionSuggestions(input, suggestionsEl);

        suggestionsEl.querySelectorAll('.search-suggestion-item').forEach((item) => {
          item.addEventListener('click', () => {
            if (item.dataset.type === 'create') {
              handleCreateAndAssignCharacter(item.dataset.createName);
            } else {
              handleAssignCharacter(item.dataset.id, item.dataset.name);
            }
          });
        });
      } catch (err) {
        suggestionsEl.classList.add('hidden');
      }
    }, 250);
  });

  parentInput.addEventListener('input', () => {
    clearTimeout(characterParentDebounce);
    selectedCharacterParent = null; // typing invalidates any earlier pick, same as the scanner page's picker
    const query = parentInput.value.trim();
    if (query.length < 1) {
      parentSuggestionsEl.classList.add('hidden');
      return;
    }

    characterParentDebounce = setTimeout(async () => {
      try {
        // No is_referenced filter here -- any existing node (a bare series
        // container included) is a valid parent, not just a real character.
        const data = await listCharacterTags({ search: query, per_page: 30 });
        if (data.nodes.length === 0) {
          parentSuggestionsEl.classList.add('hidden');
          return;
        }

        parentSuggestionsEl.innerHTML = data.nodes
          .map((n) => `<div class="search-suggestion-item" data-id="${n.id}" data-name="${escapeHtml(n.name)}"><span>${escapeHtml(n.name)}</span></div>`)
          .join('');
        positionSuggestions(parentInput, parentSuggestionsEl);

        parentSuggestionsEl.querySelectorAll('.search-suggestion-item').forEach((item) => {
          item.addEventListener('click', () => {
            selectedCharacterParent = { id: parseInt(item.dataset.id), name: item.dataset.name };
            parentInput.value = item.dataset.name;
            parentSuggestionsEl.classList.add('hidden');
          });
        });
      } catch (err) {
        parentSuggestionsEl.classList.add('hidden');
      }
    }, 250);
  });

  input.addEventListener('keydown', (e) => {
    if (e.key === 'Escape') closeCharacterPicker();
  });
  parentInput.addEventListener('keydown', (e) => {
    if (e.key === 'Escape') closeCharacterPicker();
  });

  document.addEventListener('click', (e) => {
    if (
      !picker.contains(e.target) &&
      !suggestionsEl.contains(e.target) &&
      !parentSuggestionsEl.contains(e.target) &&
      e.target !== toggleBtn
    ) {
      suggestionsEl.classList.add('hidden');
      parentSuggestionsEl.classList.add('hidden');
    }
  });
}

async function handleAssignArtist(artistId, artistName) {
  const img = currentImages[currentIndex];
  if (!img) return;

  try {
    await addArtistTag(img.id, artistId);
  } catch (err) {
    showToast(`指定失敗：${err.message}`, 'error');
    return; // picker stays open, typed query intact, state untouched
  }

  showToast(`已指定作者：${artistName}`, 'success');
  img.artist_tags = [{ id: parseInt(artistId), name: artistName }];
  showImage(); // re-renders badges from the patched data and closes the picker
  if (onListChanged) onListChanged();
}

// Create-then-assign is two separate calls, not one combined backend
// endpoint: reuses handleAssignArtist (and everything it already does --
// backup writes, UI patch, onListChanged) completely unchanged. Worst case
// on a failure between the two calls is a newly-created, momentarily
// unassigned artist node -- low-stakes, and it'll just show up in the next
// search.
async function handleCreateAndAssignArtist(name) {
  let created;
  try {
    created = await createIndividualTag(name);
  } catch (err) {
    showToast(`新增作者失敗：${err.message}`, 'error');
    return;
  }

  await handleAssignArtist(created.id, created.name);
}

async function handleAssignCharacter(characterId, characterName) {
  const img = currentImages[currentIndex];
  if (!img) return;

  try {
    // Unlike addArtistTag, this also moves the image's real file on disk
    // (see ADR-0006) -- a destination-collision or other backend error
    // surfaces here via err.message same as any other failure.
    await addCharacterTag(img.id, characterId);
  } catch (err) {
    showToast(`指定失敗：${err.message}`, 'error');
    return; // picker stays open, typed query intact, state untouched
  }

  showToast(`已指定角色：${characterName}`, 'success');
  img.character_tags = [{ id: parseInt(characterId), name: characterName }];
  showImage(); // re-renders badges from the patched data and closes the picker
  if (onListChanged) onListChanged();
}

// Create-then-assign, same shape as handleCreateAndAssignArtist -- the
// parent field only matters here, for the creation call itself.
async function handleCreateAndAssignCharacter(name) {
  let created;
  try {
    created = await createCharacterTag(name, selectedCharacterParent?.id);
  } catch (err) {
    showToast(`新增角色失敗：${err.message}`, 'error');
    return;
  }

  await handleAssignCharacter(created.id, created.name);
}

function formatFileSize(bytes) {
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1048576) return `${(bytes / 1024).toFixed(1)} KB`;
  return `${(bytes / 1048576).toFixed(1)} MB`;
}
