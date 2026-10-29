import { offlineError } from "../offline";

const API_BASE = (import.meta.env.VITE_API_BASE || "/api").replace(/\/$/, "");

// Sign-in is an HttpOnly session cookie the browser attaches by itself (`credentials: "include"`); script never
// sees it. Unsafe requests also carry Django's CSRF token, echoed from the script-readable `csrftoken` cookie.
const SAFE_METHODS = new Set(["GET", "HEAD", "OPTIONS"]);
const CSRF_COOKIE = "csrftoken";

function readCookie(name) {
  const prefix = `${name}=`;
  const found = document.cookie.split(";").map((part) => part.trim()).find((part) => part.startsWith(prefix));
  return found ? decodeURIComponent(found.slice(prefix.length)) : null;
}

// Used only when the cookie is not readable from here (an API on another origin); a rotated token
// (login rotates it) is picked up again by clearing this after the auth calls.
let fetchedCsrfToken = null;

// Make sure the CSRF cookie exists (GET /auth/csrf/ sets it) and return the token to send.
async function ensureCsrfToken() {
  const fromCookie = readCookie(CSRF_COOKIE);
  if (fromCookie) return fromCookie;
  if (fetchedCsrfToken) return fetchedCsrfToken;
  let response;
  try {
    response = await fetch(`${API_BASE}/auth/csrf/`, { credentials: "include" });
  } catch {
    throw offlineError();
  }
  if (!response.ok) throw new Error("Could not start a secure session.");
  const body = await response.json();
  fetchedCsrfToken = readCookie(CSRF_COOKIE) ? null : body.csrfToken || null;
  return readCookie(CSRF_COOKIE) || fetchedCsrfToken;
}

function httpError(status, text) {
  const error = new Error(text || "Request failed");
  error.status = status;
  return error;
}

async function rawRequest(path, options = {}) {
  const method = (options.method || "GET").toUpperCase();
  const headers = {
    ...(options.headers || {})
  };
  if (!SAFE_METHODS.has(method)) {
    const csrfToken = await ensureCsrfToken();
    if (csrfToken) headers["X-CSRFToken"] = csrfToken;
  }
  let response;
  try {
    response = await fetch(`${API_BASE}${path}`, {
      ...options,
      headers,
      credentials: "include"
    });
  } catch {
    throw offlineError();
  }
  if (!response.ok) {
    throw httpError(response.status, await response.text());
  }
  return response;
}

async function request(path, options = {}) {
  const response = await rawRequest(path, options);
  if (response.status === 204) {
    return null;
  }
  return response.json();
}

// DRF refusals are `{detail}` or field errors like `{file: ["sentence"]}`. Return a readable sentence:
// `detail`, else the first string in the first field's errors, else the raw text.
function errorSentence(text) {
  try {
    const body = JSON.parse(text);
    if (typeof body?.detail === "string") return body.detail;
    const first = Object.values(body || {})[0];
    const candidate = Array.isArray(first) ? first[0] : first;
    if (typeof candidate === "string") return candidate;
  } catch {
    // not a JSON body; keep the raw text
  }
  return text;
}

async function requestWithMessage(path, options) {
  try {
    return await request(path, options);
  } catch (err) {
    if (err.isNetworkError) throw err;
    throw httpError(err.status, errorSentence(String(err.message || err)));
  }
}

export function filenameFromDisposition(header) {
  if (!header) return null;
  const encoded = /filename\*=(?:UTF-8'')?([^;]+)/i.exec(header);
  if (encoded) {
    try {
      return decodeURIComponent(encoded[1].trim().replace(/^"|"$/g, ""));
    } catch {
      // fall through to the plain filename parameter
    }
  }
  const plain = /filename="?([^";]+)"?/i.exec(header);
  return plain ? plain[1] : null;
}

function saveBlob(blob, filename) {
  const url = URL.createObjectURL(blob);
  const link = document.createElement("a");
  link.href = url;
  link.download = filename;
  document.body.appendChild(link);
  link.click();
  link.remove();
  URL.revokeObjectURL(url);
}

// A failed SSO sign-in comes back as `#oidc_error=<code>`. The code is one of a fixed set the server sends;
// the wording lives here, so nothing in the URL (a crafted link, a provider's error text) can put text on the page.
export const OIDC_ERROR_MESSAGES = {
  provider_error: "The single sign-on provider reported a problem. Please try again.",
  failed: "Single sign-on failed. Please try again.",
  no_subject: "The identity provider did not identify you, so sign-in could not finish.",
  disabled: "This account is disabled.",
  not_allowed: "This account is not allowed to sign in here."
};

// Read the fragment once and strip it from the address bar. Returns `{ error }` with the fixed message for a
// known code, else null (a success carries no fragment at all: the session cookie is the sign-in).
export function consumeOidcFragment() {
  const params = new URLSearchParams(window.location.hash.replace(/^#/, ""));
  if (!params.has("oidc_error")) return null;
  window.history.replaceState(null, "", window.location.pathname + window.location.search);
  const code = params.get("oidc_error");
  return Object.hasOwn(OIDC_ERROR_MESSAGES, code) ? { error: OIDC_ERROR_MESSAGES[code] } : null;
}

function jsonPost(payload) {
  return { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(payload) };
}

export const api = {
  oidcLoginUrl: `${API_BASE}/auth/oidc/login/`,
  authConfig() {
    return request("/auth/config/");
  },
  me() {
    return request("/auth/me/");
  },
  // Register, login and invite sign-up all answer `{ user }` and set the session cookie; there is no token.
  // A fresh login rotates the CSRF token, so forget any copy fetched earlier.
  async register(payload) {
    const data = await requestWithMessage("/auth/register/", jsonPost(payload));
    fetchedCsrfToken = null;
    return data;
  },
  async login(payload) {
    const data = await requestWithMessage("/auth/login/", jsonPost(payload));
    fetchedCsrfToken = null;
    return data;
  },
  async logout() {
    await request("/auth/logout/", { method: "POST" });
    fetchedCsrfToken = null;
  },
  // Invite links: the token comes from the path of `/invite/<token>` and only ever travels in a POST body.
  // Both refuse an unknown, expired, used or revoked link with the same 404.
  checkInvite(token) {
    return requestWithMessage("/auth/invites/check/", jsonPost({ token }));
  },
  async acceptInvite(payload) {
    const data = await requestWithMessage("/auth/invites/accept/", jsonPost(payload));
    fetchedCsrfToken = null;
    return data;
  },
  // Admin-only. The response is the one and only time the raw link is shown.
  createInvite(payload) {
    return requestWithMessage("/auth/invites/", jsonPost(payload));
  },
  // Approves a handheld's pairing code (from the QR link). Refusals (404 unknown, 410 expired, 409
  // already approved) carry a DRF `{detail}` body; surface just that message.
  async approveDevice(code) {
    try {
      return await request("/devices/pair/approve", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ code })
      });
    } catch (err) {
      let message = String(err.message || err);
      try {
        message = JSON.parse(message).detail || message;
      } catch {
        // not a JSON body; keep the raw text
      }
      throw new Error(message, { cause: err });
    }
  },
  // Returns DRF's paginated envelope: { count, next, previous, results }.
  listRoms({ search = "", platform = "", page = 1 } = {}) {
    const params = new URLSearchParams();
    if (search.trim()) params.set("search", search.trim());
    if (platform) params.set("platform", platform);
    if (page > 1) params.set("page", String(page));
    const query = params.toString();
    return request(`/roms/${query ? `?${query}` : ""}`);
  },
  listPlatforms() {
    return request("/roms/platforms/");
  },
  createRom(formData) {
    return requestWithMessage("/roms/", { method: "POST", body: formData });
  },
  // Admin-only: library status (incl. the last scan) and on-demand rescans.
  libraryStatus() {
    return request("/library/status/");
  },
  rescanLibrary({ acceptRemovals = false } = {}) {
    return requestWithMessage("/library/scan/", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ accept_removals: acceptRemovals })
    });
  },
  scrapeCover(romId) {
    return request(`/roms/${romId}/scrape_cover/`, { method: "POST" });
  },
  // Cover art is private too: fetch it as a blob and return an object URL the caller must revoke.
  async coverObjectUrl(rom) {
    const response = await rawRequest(`/roms/${rom.id}/cover/`);
    return URL.createObjectURL(await response.blob());
  },
  // Cheap existence probe used while waiting for async scraping: 404 (or any failure) means
  // "no art yet", so the caller just tries again later.
  async coverExists(romId) {
    try {
      await rawRequest(`/roms/${romId}/cover/`, { method: "HEAD" });
      return true;
    } catch {
      return false;
    }
  },
  listPlaylists() {
    return request("/playlists/");
  },
  getPlaylist(id) {
    return request(`/playlists/${id}/`);
  },
  createPlaylist(payload) {
    return request("/playlists/", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload)
    });
  },
  // `rom_ids`, when sent, is the full new ordered list (it replaces the playlist's contents).
  updatePlaylist(id, payload) {
    return request(`/playlists/${id}/`, {
      method: "PATCH",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload)
    });
  },
  deletePlaylist(id) {
    return request(`/playlists/${id}/`, { method: "DELETE" });
  },
  handheldInfo() {
    return request("/handheld/");
  },
  // The app package is for signed-in users only: fetch with the session, then save the blob.
  async downloadHandheldApp() {
    const response = await rawRequest("/handheld/download/");
    const blob = await response.blob();
    saveBlob(blob, filenameFromDisposition(response.headers.get("Content-Disposition")) || "birdROMs.muxapp");
  },
  // ROMs are private: fetch through the authenticated endpoint, then save the blob locally.
  async downloadRom(rom) {
    const response = await rawRequest(`/roms/${rom.id}/download/`);
    const blob = await response.blob();
    const filename =
      filenameFromDisposition(response.headers.get("Content-Disposition")) || rom.filename || `${rom.title}${rom.extension || ""}`;
    saveBlob(blob, filename);
  }
};
