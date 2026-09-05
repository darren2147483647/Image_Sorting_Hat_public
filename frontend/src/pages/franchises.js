/**
 * 圖像分類帽 — 作品管理頁面
 */
import { listCharacterTags } from '../api.js';
import { renderTagBrowserPage } from '../components/tag-browser.js';

export async function renderFranchisesPage(container) {
  await renderTagBrowserPage(container, {
    title: '作品管理',
    nounLabel: '系列',
    emptyIcon: '📂',
    listFn: listCharacterTags,
    // 系列 (per CONTEXT.md) is any non-root character_tag node -- the list
    // endpoint's base query already restricts to id != 0, so no extra
    // filter is needed. Not the same set as 角色管理 (is_referenced: true);
    // the two intentionally overlap.
    listFilter: {},
    filterParamName: 'char_id',
  });
}
