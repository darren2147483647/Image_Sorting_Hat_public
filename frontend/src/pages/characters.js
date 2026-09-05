/**
 * 圖像分類帽 — 角色管理頁面
 */
import { listCharacterTags } from '../api.js';
import { renderTagBrowserPage } from '../components/tag-browser.js';

export async function renderCharactersPage(container) {
  await renderTagBrowserPage(container, {
    title: '角色管理',
    nounLabel: '角色',
    emptyIcon: '👤',
    listFn: listCharacterTags,
    listFilter: { is_referenced: true },
    filterParamName: 'char_id',
  });
}
