const API_BASE = (import.meta.env.VITE_API_BASE || "/api").replace(/\/$/, "");

export function getToken() {
  return localStorage.getItem("birdroms_token");
}

export function setToken(token) {
  if (token) {
    localStorage.setItem("birdroms_token", token);
  } else {
    localStorage.removeItem("birdroms_token");
  }
}

async function rawRequest(path, options = {}) {
  const token = getToken();
  const headers = {
    ...(options.headers || {})
  };
  if (token) {
    headers.Authorization = `Token ${token}`;
  }
  const response = await fetch(`${API_BASE}${path}`, {
    ...options,
    headers
  });
  if (!response.ok) {
    const text = await response.text();
    throw new Error(text || "Request failed");
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

export const api = {
  register(payload) {
    return request("/auth/register/", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload)
    });
  },
  login(payload) {
    return request("/auth/login/", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload)
    });
  },
  listRoms() {
    return request("/roms/");
  },
  createRom(formData) {
    return request("/roms/", { method: "POST", body: formData });
  },
  scrapeCover(romId) {
    return request(`/roms/${romId}/scrape_cover/`, { method: "POST" });
  },
  // ROMs are private: fetch through the authenticated endpoint, then save the blob locally.
  async downloadRom(rom) {
    const response = await rawRequest(`/roms/${rom.id}/download/`);
    const blob = await response.blob();
    const filename =
      filenameFromDisposition(response.headers.get("Content-Disposition")) || `${rom.title}${rom.extension || ""}`;
    saveBlob(blob, filename);
  }
};
