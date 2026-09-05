/**
 * 圖像分類帽 — API 呼叫封裝
 */

const API_BASE = 'http://127.0.0.1:8000/api';

class ApiError extends Error {
  constructor(status, message) {
    super(message);
    this.status = status;
  }
}

async function request(endpoint, options = {}) {
  const url = `${API_BASE}${endpoint}`;
  try {
    const response = await fetch(url, {
      ...options,
      headers: {
        'Content-Type': 'application/json',
        ...options.headers,
      },
    });

    if (!response.ok) {
      const errorData = await response.json().catch(() => ({}));
      throw new ApiError(
        response.status,
        errorData.detail || `HTTP ${response.status}`
      );
    }

    return await response.json();
  } catch (err) {
    if (err instanceof ApiError) throw err;
    throw new ApiError(0, `連線失敗: ${err.message}`);
  }
}

// === Health & Stats ===
export const getHealth = () => request('/health');
export const getStats = () => request('/stats');

// === Images ===
export const listImages = (params = {}) => {
  const qs = new URLSearchParams();
  Object.entries(params).forEach(([k, v]) => {
    if (v !== null && v !== undefined && v !== '') qs.set(k, v);
  });
  return request(`/images?${qs.toString()}`);
};

export const getImage = (id) => request(`/images/${id}`);
export const getImageFileUrl = (id) => `${API_BASE}/images/${id}/file`;
export const getImageFormats = () => request('/images/formats');

// Removes the image's row from the database entirely (the file on disk is
// untouched) -- distinct from deleteTag, which only resets a char/artist
// tag back to 0. Used by the "移出追蹤" flow: move the file to the right
// folder, remove it from tracking, rescan.
export const deleteImageRecord = (id) => request(`/images/${id}`, { method: 'DELETE' });

export const addCharacterTag = (imageId, characterId) =>
  request(`/images/${imageId}/tags/character?character_id=${characterId}`, {
    method: 'POST',
  });

// Create-or-resolve a character/series node (see ADR-0006) -- parentId is
// optional; the backend defaults to the `characters` node when omitted.
export const createCharacterTag = (name, parentId) => {
  const qs = new URLSearchParams({ name });
  if (parentId != null) qs.set('parent_id', parentId);
  return request(`/character-tags?${qs.toString()}`, { method: 'POST' });
};

// Sets an image's artist directly, independent of file location -- unlike
// char_id (which always corresponds to the image's real folder location,
// changed via 移出追蹤+rescan, the scan-time classification policy, or
// addCharacterTag above, which moves the file to match -- see ADR-0006),
// artist_id is meant to be freely (re)assigned this way regardless of
// whether the image currently sits under characters/ or individuals/.
export const addArtistTag = (imageId, artistId) =>
  request(`/images/${imageId}/tags/artist?artist_id=${artistId}`, {
    method: 'POST',
  });

export const deleteTag = (imageId, tagId, tagType = 'character') =>
  request(`/images/${imageId}/tags/${tagId}?tag_type=${tagType}`, {
    method: 'DELETE',
  });

// === Scan ===
export const getAvailableFolders = () => request('/scan/folders');

// Persisted, DB-independent import root (see ADR-0004) -- stored/resolved
// entirely on the backend; the frontend just displays/edits it.
export const getImportRoot = () => request('/scan/import-root');

export const setImportRoot = (rootPath) =>
  request(`/scan/import-root?root_path=${encodeURIComponent(rootPath)}`, {
    method: 'POST',
  });

// Persisted records directory (DB + artist backup, see ADR-0008) -- unlike
// import root, saving this does NOT take effect until the backend restarts.
export const getRecordsDir = () => request('/scan/records-dir');

export const setRecordsDir = (recordsDir) =>
  request(`/scan/records-dir?records_dir=${encodeURIComponent(recordsDir)}`, {
    method: 'POST',
  });

// charPolicy/artistPolicy: { mode: 'folder'|'fixed'|'none', fixedId?: number }
export const startScan = (rootPath, folders, includeOther = true, charPolicy = {}, artistPolicy = {}) => {
  const qs = new URLSearchParams({
    root_path: rootPath,
    folders: folders.join(','),
    include_other: includeOther.toString(),
    char_policy: charPolicy.mode || 'folder',
    artist_policy: artistPolicy.mode || 'folder',
  });
  if (charPolicy.fixedId != null) qs.set('char_fixed_id', charPolicy.fixedId);
  if (artistPolicy.fixedId != null) qs.set('artist_fixed_id', artistPolicy.fixedId);
  return request(`/scan/start?${qs.toString()}`, { method: 'POST' });
};

export const getScanProgress = () => request('/scan/progress');
export const getScanHistory = (limit = 20) => request(`/scan/history?limit=${limit}`);

// === Character tags (character_tag tree: series + characters, one resource) ===
export const listCharacterTags = (params = {}) => {
  const qs = new URLSearchParams();
  Object.entries(params).forEach(([k, v]) => {
    if (v !== null && v !== undefined && v !== '') qs.set(k, v);
  });
  return request(`/character-tags?${qs.toString()}`);
};

export const getCharacterTag = (id) => request(`/character-tags/${id}`);

export const updateCharacterTag = (id, data) =>
  request(`/character-tags/${id}?${new URLSearchParams(data).toString()}`, {
    method: 'PUT',
  });

// === Individual tags (individual_tag tree: artists) ===
export const listIndividualTags = (params = {}) => {
  const qs = new URLSearchParams();
  Object.entries(params).forEach(([k, v]) => {
    if (v !== null && v !== undefined && v !== '') qs.set(k, v);
  });
  return request(`/individual-tags?${qs.toString()}`);
};

export const getIndividualTag = (id) => request(`/individual-tags/${id}`);

// Case-insensitive find-or-create under the individuals container -- used by
// the lightbox "+新增作者" flow. A name matching an existing artist in any
// casing resolves to that existing node rather than creating a duplicate.
export const createIndividualTag = (name) =>
  request(`/individual-tags?name=${encodeURIComponent(name)}`, {
    method: 'POST',
  });

// === Search ===
export const globalSearch = (query, type = null, limit = 20) => {
  const qs = new URLSearchParams({ q: query, limit: limit.toString() });
  if (type) qs.set('type', type);
  return request(`/search?${qs.toString()}`);
};

export const searchSuggest = (query, limit = 10) =>
  request(`/search/suggest?q=${encodeURIComponent(query)}&limit=${limit}`);
