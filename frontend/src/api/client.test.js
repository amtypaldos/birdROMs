import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { api, consumeOidcFragment, filenameFromDisposition, getToken, setToken } from "./client";

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

  it("downloads ROMs through the authenticated endpoint as a blob", async () => {
    const blob = new Blob(["NES"]);
    const fetchMock = vi.fn().mockResolvedValue({
      ok: true,
      status: 200,
      headers: new Headers({ "Content-Disposition": 'attachment; filename="Zelda.nes"' }),
      blob: () => Promise.resolve(blob)
    });
    vi.stubGlobal("fetch", fetchMock);
    const createObjectURL = vi.fn(() => "blob:rom");
    const revokeObjectURL = vi.fn();
    vi.stubGlobal("URL", { ...URL, createObjectURL, revokeObjectURL });
    const click = vi.spyOn(HTMLAnchorElement.prototype, "click").mockImplementation(() => {});
    setToken("abc123");

    await api.downloadRom({ id: 7, title: "Zelda", extension: ".nes" });

    const [url, options] = fetchMock.mock.calls[0];
    expect(url).toBe("/api/roms/7/download/");
    expect(options.headers.Authorization).toBe("Token abc123");
    expect(createObjectURL).toHaveBeenCalledWith(blob);
    expect(click).toHaveBeenCalledTimes(1);
    expect(click.mock.contexts[0].download).toBe("Zelda.nes");
    expect(revokeObjectURL).toHaveBeenCalledWith("blob:rom");
    click.mockRestore();
  });

  it("parses Content-Disposition filenames", () => {
    expect(filenameFromDisposition('attachment; filename="Zelda.nes"')).toBe("Zelda.nes");
    expect(filenameFromDisposition("attachment; filename*=UTF-8''Pok%C3%A9mon.gb")).toBe("Pokémon.gb");
    expect(filenameFromDisposition(null)).toBeNull();
  });
});

describe("consumeOidcFragment", () => {
  afterEach(() => {
    window.history.replaceState(null, "", "/");
  });

  it("returns null when there is no SSO result in the URL", () => {
    window.history.replaceState(null, "", "/?page=2#section");
    expect(consumeOidcFragment()).toBeNull();
    expect(window.location.hash).toBe("#section");
  });

  it("reads the token and strips it from the address bar", () => {
    window.history.replaceState(null, "", "/library?x=1#oidc_token=tok123");
    expect(consumeOidcFragment()).toEqual({ token: "tok123", error: null });
    expect(window.location.hash).toBe("");
    expect(window.location.pathname + window.location.search).toBe("/library?x=1");
  });

  it("reads an error", () => {
    window.history.replaceState(null, "", "/#oidc_error=Single+sign-on+failed.");
    expect(consumeOidcFragment()).toEqual({ token: null, error: "Single sign-on failed." });
  });
});
