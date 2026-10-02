// Central API Client for RajLabs FreeRADIUS Enterprise AAA

const TOKEN_KEY = 'admin_token';
const USER_TOKEN_KEY = 'user_token';
const USER_INFO_KEY = 'auth_user_info';

export const getAuthToken = () => localStorage.getItem(TOKEN_KEY);
export const setAuthToken = (token) => localStorage.setItem(TOKEN_KEY, token);
export const removeAuthToken = () => {
  localStorage.removeItem(TOKEN_KEY);
  localStorage.removeItem(USER_INFO_KEY);
};

export const getUserToken = () => localStorage.getItem(USER_TOKEN_KEY);
export const setUserToken = (token) => localStorage.setItem(USER_TOKEN_KEY, token);
export const removeUserToken = () => {
  localStorage.removeItem(USER_TOKEN_KEY);
  localStorage.removeItem(USER_INFO_KEY);
};

export const getUserInfo = () => {
  try {
    const raw = localStorage.getItem(USER_INFO_KEY);
    return raw ? JSON.parse(raw) : null;
  } catch {
    return null;
  }
};

export const setUserInfo = (info) => {
  try {
    localStorage.setItem(USER_INFO_KEY, JSON.stringify(info));
  } catch {}
};


export async function apiRequest(path, options = {}) {
  const url = path.startsWith('/') ? path : `/radius/api/${path}`;
  const headers = {
    'Accept': 'application/json',
    ...(options.headers || {})
  };

  if (!(options.body instanceof FormData) && !headers['Content-Type'] && options.method && options.method !== 'GET') {
    headers['Content-Type'] = 'application/json';
  }

  const token = getAuthToken() || getUserToken();
  if (token && !headers['Authorization']) {
    headers['Authorization'] = `Bearer ${token}`;
  }

  const response = await fetch(url, {
    ...options,
    headers
  });

  if (response.status === 401) {
    // Only remove admin token if accessing protected endpoint
    if (!path.includes('/auth/login') && !path.includes('/auth/cert-login') && !path.includes('/portal')) {
      removeAuthToken();
    }
  }

  return response;
}

export async function fetchJson(path, options = {}) {
  const response = await apiRequest(path, options);
  const data = await response.json().catch(() => ({}));
  if (!response.ok) {
    const error = new Error(data.detail || data.message || data.error || `HTTP ${response.status}`);
    error.status = response.status;
    error.data = data;
    throw error;
  }
  return data;
}

export function formatBytes(bytes) {
  if (bytes === 0 || !bytes) return '0 B';
  const k = 1024;
  const sizes = ['B', 'KB', 'MB', 'GB', 'TB'];
  const i = Math.floor(Math.log(bytes) / Math.log(k));
  return parseFloat((bytes / Math.pow(k, i)).toFixed(2)) + ' ' + sizes[i];
}

export function formatDuration(seconds) {
  if (!seconds || seconds <= 0) return '0s';
  const d = Math.floor(seconds / (3600 * 24));
  const h = Math.floor((seconds % (3600 * 24)) / 3600);
  const m = Math.floor((seconds % 3600) / 60);
  const s = Math.floor(seconds % 60);
  const parts = [];
  if (d > 0) parts.push(`${d}d`);
  if (h > 0) parts.push(`${h}h`);
  if (m > 0) parts.push(`${m}m`);
  if (s > 0 && d === 0) parts.push(`${s}s`);
  return parts.join(' ') || '0s';
}

export function formatDateTime(isoString) {
  if (!isoString) return '—';
  try {
    const d = new Date(isoString);
    if (isNaN(d.getTime())) return String(isoString);
    return d.toLocaleString(undefined, {
      year: 'numeric',
      month: 'short',
      day: 'numeric',
      hour: '2-digit',
      minute: '2-digit',
      second: '2-digit'
    });
  } catch {
    return String(isoString);
  }
}

export function calculatePasswordStrength(pass) {
  if (!pass) return { score: 0, label: 'Empty', color: '#64748b', pct: 0, bits: 0 };
  let bits = 0;
  if (/[a-z]/.test(pass)) bits += 26;
  if (/[A-Z]/.test(pass)) bits += 26;
  if (/[0-9]/.test(pass)) bits += 10;
  if (/[^a-zA-Z0-9]/.test(pass)) bits += 33;
  const entropy = Math.round(pass.length * (Math.log2(bits || 1)));
  if (pass.length < 12 || entropy < 50) {
    return { score: 1, label: 'Weak', color: '#f43f5e', pct: 30, bits: entropy };
  } else if (entropy < 70) {
    return { score: 2, label: 'Moderate', color: '#f59e0b', pct: 65, bits: entropy };
  } else if (entropy < 90) {
    return { score: 3, label: 'Strong', color: '#10b981', pct: 85, bits: entropy };
  } else {
    return { score: 4, label: 'Very Strong', color: '#06b6d4', pct: 100, bits: entropy };
  }
}
