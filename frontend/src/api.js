/**
 * Shared API client for the FastAPI backend.
 *
 * - Production: empty base URL (same origin via api.py static serving)
 * - Dev (Vite): proxy in vite.config.js forwards /api, /stream, /auth to :7860
 * - Override: set VITE_API_BASE_URL=http://127.0.0.1:7860 in .env.local
 */
const API_BASE = (import.meta.env.VITE_API_BASE_URL || '').replace(/\/$/, '');

export function apiUrl(path) {
  if (!path.startsWith('/')) {
    path = `/${path}`;
  }
  return `${API_BASE}${path}`;
}

function parseErrorMessage(data, status) {
  if (!data) return `Request failed (${status})`;
  if (typeof data.detail === 'string') return data.detail;
  if (Array.isArray(data.detail)) {
    return data.detail.map((item) => item.msg || String(item)).join(', ');
  }
  if (data.error) return data.error;
  return `Request failed (${status})`;
}

export async function apiFetch(path, options = {}) {
  return fetch(apiUrl(path), options);
}

export async function apiJson(path, options = {}) {
  const response = await apiFetch(path, options);
  let data = null;
  try {
    data = await response.json();
  } catch {
    if (!response.ok) {
      throw new Error(`Request failed (${response.status})`);
    }
    return null;
  }
  if (!response.ok) {
    throw new Error(parseErrorMessage(data, response.status));
  }
  return data;
}

export async function apiStream(path, body) {
  const response = await apiFetch(path, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  });
  if (!response.ok) {
    let message = `Stream request failed (${response.status})`;
    try {
      const data = await response.json();
      message = parseErrorMessage(data, response.status);
    } catch {
      // ignore parse errors
    }
    throw new Error(message);
  }
  if (!response.body) {
    throw new Error('Readable stream not supported');
  }
  return response.body;
}
