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

async function request(path, options = {}) {
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
  if (response.status === 204) {
    return null;
  }
  return response.json();
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
  }
};
