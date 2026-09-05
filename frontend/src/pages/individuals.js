/**
 * 圖像分類帽 — 作者管理頁面
 */
import { listIndividualTags } from '../api.js';
import { renderTagBrowserPage } from '../components/tag-browser.js';

export async function renderIndividualsPage(container) {
  await renderTagBrowserPage(container, {
    title: '作者管理',
    nounLabel: '作者',
    emptyIcon: '🎨',
    listFn: listIndividualTags,
    listFilter: {},
    filterParamName: 'artist_id',
  });
}
