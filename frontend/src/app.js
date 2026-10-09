// Bundle HTMX + Alpine.js into a single ~50KB file
import 'htmx.org';
import Alpine from 'alpinejs';

// HTMX error handling — show dismissible inline error on request failure
document.addEventListener('htmx:responseError', (event) => {
  showError(`Request failed: ${event.detail.xhr.status} ${event.detail.xhr.statusText}`);
});
document.addEventListener('htmx:sendError', (event) => {
  showError(`Network error: could not reach server (${event.detail.el?.id || 'unknown'})`);
});

function showError(message) {
  const existing = document.getElementById('htmx-error-banner');
  if (existing) existing.remove();

  const banner = document.createElement('div');
  banner.id = 'htmx-error-banner';
  banner.className = 'fixed bottom-4 right-4 z-50 max-w-md bg-red-900/90 border border-red-700 text-red-200 px-4 py-3 rounded-lg shadow-lg flex items-center gap-3 animate-slide-up';
  banner.setAttribute('role', 'alert');
  banner.innerHTML = `
    <span class="flex-shrink-0">⚠️</span>
    <span class="text-sm flex-1">${escapeHtml(message)}</span>
    <button class="flex-shrink-0 text-red-400 hover:text-red-200 transition-colors" onclick="this.parentElement.remove()" aria-label="Dismiss error">✕</button>
  `;
  document.body.appendChild(banner);
  setTimeout(() => banner?.remove(), 8000);
}

function escapeHtml(str) {
  const div = document.createElement('div');
  div.textContent = str;
  return div.innerHTML;
}

// Alpine.js fallback handling
document.addEventListener('DOMContentLoaded', () => {
  if (typeof Alpine === 'undefined') {
    document.getElementById('alpine-fallback')?.classList.remove('hidden');
  }
});

// Make Alpine globally available
window.Alpine = Alpine;
Alpine.start();
