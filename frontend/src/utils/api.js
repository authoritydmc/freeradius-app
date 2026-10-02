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

// Canonical user-facing base URL for Wi-Fi users (captive portal, recharge,
// onboarding links). The backend serves the portal at this host's root.
export const WIFI_PORTAL_BASE_URL = 'https://wifi.rajlabs.in';
export const portalUrlFor = (path = '/radius/portal') =>
  `${WIFI_PORTAL_BASE_URL}${path}`;

/** Compact relative countdown: "12d 4h left" / "Expires today" / "Expired 2d ago". */
export function timeLeft(input) {
  try {
    const ms = typeof input === 'number' ? (input < 1e12 ? input * 1000 : input) : Date.parse(input);
    if (isNaN(ms)) return '';
    const diff = ms - Date.now();
    const abs = Math.abs(diff);
    const d = Math.floor(abs / 86400000);
    const h = Math.floor((abs % 86400000) / 3600000);
    const core = d > 0 ? `${d}d${h ? ` ${h}h` : ''}` : h > 0 ? `${h}h` : 'under an hour';
    return diff >= 0 ? (d === 0 && h === 0 ? 'Expires today' : `${core} left`) : `Expired ${core} ago`;
  } catch {
    return '';
  }
}

export function formatDateTime(input, opts = {}) {
  if (input == null || input === '') return '—';
  try {
    // Epoch millis (number or numeric string, 13 digits) or epoch seconds (10 digits)
    if (typeof input === 'number' || /^\d{10,13}$/.test(String(input).trim())) {
      const n = Number(input);
      const ms = n < 1e12 ? n * 1000 : n;
      const d = new Date(ms);
      if (!isNaN(d.getTime())) {
        return d.toLocaleString(undefined, {
          year: 'numeric', month: 'short', day: 'numeric',
          hour: '2-digit', minute: '2-digit', second: '2-digit',
          timeZoneName: opts.tzName || 'short'
        });
      }
    }
    let s = String(input).trim();
    // FreeRADIUS Expiration "03 Oct 2026 01:30:41" carries no zone — the
    // server generates it from UTC, so parse it as UTC explicitly.
    if (/^\d{2} \w{3} \d{4} \d{2}:\d{2}(:\d{2})?$/.test(s)) {
      // "03 Oct 2026 01:30:41" is not ISO — rebuild as ISO UTC explicitly.
      const m = s.match(/^(\d{2}) (\w{3}) (\d{4}) (\d{2}:\d{2}(?::\d{2})?)$/);
      const months = { jan: '01', feb: '02', mar: '03', apr: '04', may: '05', jun: '06', jul: '07', aug: '08', sep: '09', oct: '10', nov: '11', dec: '12' };
      if (m) {
        const mon = months[m[2].toLowerCase()] || '01';
        s = `${m[3]}-${mon}-${m[1]}T${m[4].length === 5 ? m[4] + ':00' : m[4]}Z`;
      }
    }
    const d = new Date(s);
    if (isNaN(d.getTime())) return String(input);
    // Always render in the viewer's LOCAL zone with an explicit TZ label,
    // so "UTC or local?" is never ambiguous again.
    return d.toLocaleString(undefined, {
      year: 'numeric',
      month: 'short',
      day: 'numeric',
      hour: '2-digit',
      minute: '2-digit',
      second: '2-digit',
      timeZoneName: opts.tzName || 'short'
    });
  } catch {
    return String(input);
  }
}

export function calculatePasswordStrength(pass) {
  if (!pass) return { score: 0, label: 'Empty', color: '#64748b', pct: 0, bits: 0 };
  let bits = 0;
  if (/[a-z]/.test(pass)) bits += 26;
  if (/[A-Z]/.test(pass)) bits += 26;
  if (/[0-9]/.test(pass)) bits += 10;
  // keep in sync with backend PASSWORD_SYMBOLS (11 chars)
  if (/[^a-zA-Z0-9]/.test(pass)) bits += 11;
  const entropy = Math.round(pass.length * (Math.log2(bits || 1)));
  // backend: min 8 chars, no forced mix — meter only advises, never blocks.
  if (pass.length < 8 || entropy < 45) {
    return { score: 1, label: 'Weak', color: '#f43f5e', pct: 30, bits: entropy };
  } else if (entropy < 70) {
    return { score: 2, label: 'Moderate', color: '#f59e0b', pct: 65, bits: entropy };
  } else if (entropy < 90) {
    return { score: 3, label: 'Strong', color: '#10b981', pct: 85, bits: entropy };
  } else {
    return { score: 4, label: 'Very Strong', color: '#06b6d4', pct: 100, bits: entropy };
  }
}

export const PASSWORD_POLICY_HINT = 'Min 8 chars — anything goes (e.g. 9876543210)';
