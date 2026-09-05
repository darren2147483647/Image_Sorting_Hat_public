/**
 * 圖像分類帽 — 主應用邏輯
 * Hash-based SPA router + global utilities
 */
import { getStats } from './api.js';
import { renderGalleryPage } from './pages/gallery.js';
import { renderCharactersPage } from './pages/characters.js';
import { renderFranchisesPage } from './pages/franchises.js';
import { renderIndividualsPage } from './pages/individuals.js';
import { renderScannerPage } from './pages/scanner.js';
import { initLightbox } from './components/lightbox.js';

// === Router ===
const routes = {
  '/': { render: renderGalleryPage, nav: 'gallery' },
  '/characters': { render: renderCharactersPage, nav: 'characters' },
  '/franchises': { render: renderFranchisesPage, nav: 'franchises' },
  '/individuals': { render: renderIndividualsPage, nav: 'individuals' },
  '/scanner': { render: renderScannerPage, nav: 'scanner' },
};

let currentPage = null;

async function navigate() {
  const hash = window.location.hash || '#/';
  const path = hash.split('?')[0].replace('#', '') || '/';

  const route = routes[path];
  if (!route) {
    window.location.hash = '#/';
    return;
  }

  // Update nav active state
  document.querySelectorAll('.nav-link').forEach((link) => {
    link.classList.toggle('active', link.dataset.page === route.nav);
  });

  // Render page
  const container = document.getElementById('app-content');
  currentPage = route.nav;

  try {
    await route.render(container);
  } catch (err) {
    container.innerHTML = `
      <div class="empty-state">
        <div class="empty-state-icon">⚠️</div>
        <div class="empty-state-title">頁面載入失敗</div>
        <div class="empty-state-desc">${err.message}</div>
      </div>
    `;
    console.error('Page render error:', err);
  }
}

// === Toast Notifications ===
export function showToast(message, type = 'info', duration = 4000) {
  const container = document.getElementById('toast-container');
  const toast = document.createElement('div');
  toast.className = `toast ${type}`;
  toast.innerHTML = `
    <span>${type === 'success' ? '✅' : type === 'error' ? '❌' : 'ℹ️'}</span>
    <span>${message}</span>
  `;
  container.appendChild(toast);

  setTimeout(() => {
    toast.style.animation = 'slideOut 0.3s ease-in forwards';
    setTimeout(() => toast.remove(), 300);
  }, duration);
}

// === Stats Refresh ===
async function refreshStats() {
  try {
    const stats = await getStats();
    const imagesEl = document.querySelector('#stat-images .stat-value');
    const charsEl = document.querySelector('#stat-characters .stat-value');
    if (imagesEl) imagesEl.textContent = stats.total_images.toLocaleString();
    if (charsEl) charsEl.textContent = stats.total_characters.toLocaleString();
  } catch (err) {
    // Backend might not be running yet
    console.log('Stats fetch failed (backend might be offline):', err.message);
  }
}

// === Initialization ===
async function init() {
  // Initialize lightbox
  initLightbox();

  // Listen for hash changes
  window.addEventListener('hashchange', navigate);

  // Listen for stats refresh events
  window.addEventListener('refresh-stats', refreshStats);

  // Initial load
  await refreshStats();
  await navigate();
}

// Boot
document.addEventListener('DOMContentLoaded', init);
