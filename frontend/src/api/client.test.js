import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { api, getToken, setToken } from "./client";

function mockLocalStorage() {
  const store = new Map();
  return {
    getItem: vi.fn((key) => (store.has(key) ? store.get(key) : null)),
    setItem: vi.fn((key, value) => store.set(key, String(value))),
    removeItem: vi.fn((key) => store.delete(key))
  };
}

describe("api client", () => {
  let storage;

  beforeEach(() => {
    storage = mockLocalStorage();
    vi.stubGlobal("localStorage", storage);
  });

  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it("round-trips the token through localStorage", () => {
    expect(getToken()).toBeNull();
    setToken("abc123");
    expect(storage.setItem).toHaveBeenCalledWith("birdroms_token", "abc123");
    expect(getToken()).toBe("abc123");
    setToken(null);
    expect(storage.removeItem).toHaveBeenCalledWith("birdroms_token");
    expect(getToken()).toBeNull();
  });

  it("attaches the Authorization header when a token is set", async () => {
    const fetchMock = vi.fn().mockResolvedValue({
      ok: true,
      status: 200,
      json: () => Promise.resolve([])
    });
    vi.stubGlobal("fetch", fetchMock);
    setToken("abc123");

    await api.listRoms();

    expect(fetchMock).toHaveBeenCalledTimes(1);
    const [url, options] = fetchMock.mock.calls[0];
    expect(url).toBe("/api/roms/");
    expect(options.headers.Authorization).toBe("Token abc123");
  });

  it("omits the Authorization header when no token is set", async () => {
    const fetchMock = vi.fn().mockResolvedValue({
      ok: true,
      status: 200,
      json: () => Promise.resolve([])
    });
    vi.stubGlobal("fetch", fetchMock);

    await api.listRoms();

    const [, options] = fetchMock.mock.calls[0];
    expect(options.headers.Authorization).toBeUndefined();
  });
});
