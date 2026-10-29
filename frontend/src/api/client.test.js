import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { isNetworkError } from "../offline";
import { OIDC_ERROR_MESSAGES, api, consumeOidcFragment, filenameFromDisposition } from "./client";

function setCsrfCookie(value) {
  document.cookie = value ? `csrftoken=${value}; path=/` : "csrftoken=; path=/; expires=Thu, 01 Jan 1970 00:00:00 GMT";
}

function okJson(body = {}, status = 200) {
  return { ok: true, status, json: () => Promise.resolve(body) };
}

describe("api client", () => {
  beforeEach(() => {
    setCsrfCookie("cookietoken");
  });

  afterEach(() => {
    vi.unstubAllGlobals();
    setCsrfCookie(null);
  });

  it("never stores or reads a token in localStorage", async () => {
    const storage = { getItem: vi.fn(), setItem: vi.fn(), removeItem: vi.fn() };
    vi.stubGlobal("localStorage", storage);
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(okJson({ user: { id: 1 } })));

    await api.login({ username: "alice", password: "pw" });
    await api.me();

    expect(storage.getItem).not.toHaveBeenCalled();
    expect(storage.setItem).not.toHaveBeenCalled();
  });

  it("flags a failed fetch (no response at all) as a network error", async () => {
    vi.stubGlobal("fetch", vi.fn().mockRejectedValue(new TypeError("Failed to fetch")));

    const err = await api.me().catch((e) => e);

    expect(isNetworkError(err)).toBe(true);
  });

  it("does not flag an HTTP error status as a network error", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue({ ok: false, status: 500, text: () => Promise.resolve("boom") }));

    const err = await api.me().catch((e) => e);

    expect(err.message).toBe("boom");
    expect(isNetworkError(err)).toBe(false);
  });

  it("sends the session cookie with every request and no Authorization header", async () => {
    const fetchMock = vi.fn().mockResolvedValue(okJson([]));
    vi.stubGlobal("fetch", fetchMock);

    await api.listRoms();

    expect(fetchMock).toHaveBeenCalledTimes(1);
    const [url, options] = fetchMock.mock.calls[0];
    expect(url).toBe("/api/roms/");
    expect(options.credentials).toBe("include");
    expect(options.headers.Authorization).toBeUndefined();
    expect(options.headers["X-CSRFToken"]).toBeUndefined(); // safe methods need no CSRF token
  });

  it("echoes the CSRF cookie in X-CSRFToken on unsafe requests", async () => {
    const fetchMock = vi.fn().mockResolvedValue(okJson({}));
    vi.stubGlobal("fetch", fetchMock);

    await api.createPlaylist({ name: "x" });
    await api.deletePlaylist(3);

    expect(fetchMock).toHaveBeenCalledTimes(2); // the cookie is already there, so no extra /auth/csrf/ trip
    for (const [, options] of fetchMock.mock.calls) {
      expect(options.headers["X-CSRFToken"]).toBe("cookietoken");
      expect(options.credentials).toBe("include");
    }
  });

  it("fetches the CSRF cookie first when it is missing, then sends the token", async () => {
    setCsrfCookie(null);
    const fetchMock = vi.fn().mockImplementation((url) => {
      if (url === "/api/auth/csrf/") {
        setCsrfCookie("fresh"); // what the Set-Cookie of the real response does
        return Promise.resolve(okJson({ csrfToken: "fresh" }));
      }
      return Promise.resolve(okJson({}));
    });
    vi.stubGlobal("fetch", fetchMock);

    await api.createPlaylist({ name: "x" });

    expect(fetchMock.mock.calls[0][0]).toBe("/api/auth/csrf/");
    expect(fetchMock.mock.calls[0][1].credentials).toBe("include");
    expect(fetchMock.mock.calls[1][0]).toBe("/api/playlists/");
    expect(fetchMock.mock.calls[1][1].headers["X-CSRFToken"]).toBe("fresh");
  });

  it("falls back to the token in the csrf response when the cookie is not readable here", async () => {
    setCsrfCookie(null);
    const fetchMock = vi.fn().mockImplementation((url) =>
      Promise.resolve(okJson(url === "/api/auth/csrf/" ? { csrfToken: "from-body" } : {}))
    );
    vi.stubGlobal("fetch", fetchMock);

    await api.createPlaylist({ name: "x" });
    await api.createPlaylist({ name: "y" });

    const csrfCalls = fetchMock.mock.calls.filter(([url]) => url === "/api/auth/csrf/");
    expect(csrfCalls).toHaveLength(1);
    expect(fetchMock.mock.calls[1][1].headers["X-CSRFToken"]).toBe("from-body");
  });

  it("reports an unreachable server during the CSRF fetch as a network error", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(okJson({ user: {} })));
    await api.login({ username: "a", password: "b" }); // signing in drops any CSRF token fetched earlier
    setCsrfCookie(null);
    const fetchMock = vi.fn().mockRejectedValue(new TypeError("Failed to fetch"));
    vi.stubGlobal("fetch", fetchMock);

    const err = await api.createPlaylist({ name: "x" }).catch((e) => e);

    expect(fetchMock.mock.calls.map(([url]) => url)).toEqual(["/api/auth/csrf/"]);

    expect(isNetworkError(err)).toBe(true);
  });

  it("attaches the HTTP status to errors, so callers can tell signed-out from other failures", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue({ ok: false, status: 403, text: () => Promise.resolve("{}") }));
    expect((await api.me().catch((e) => e)).status).toBe(403);

    const body = JSON.stringify({ detail: "nope" });
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue({ ok: false, status: 404, text: () => Promise.resolve(body) }));
    const refused = await api.checkInvite("t").catch((e) => e);
    expect(refused.status).toBe(404);
    expect(refused.message).toBe("nope");
  });

  it("logs in and registers with JSON and answers { user } with no token", async () => {
    const fetchMock = vi.fn().mockResolvedValue(okJson({ user: { id: 1, username: "alice" } }, 201));
    vi.stubGlobal("fetch", fetchMock);

    expect(await api.login({ username: "alice", password: "pw" })).toEqual({ user: { id: 1, username: "alice" } });
    await api.register({ username: "bob", email: "", password: "s3cure-pass" });

    const [loginUrl, login] = fetchMock.mock.calls[0];
    expect(loginUrl).toBe("/api/auth/login/");
    expect(login.method).toBe("POST");
    expect(login.credentials).toBe("include");
    expect(login.headers["X-CSRFToken"]).toBe("cookietoken");
    expect(JSON.parse(login.body)).toEqual({ username: "alice", password: "pw" });
    expect(fetchMock.mock.calls[1][0]).toBe("/api/auth/register/");
  });

  it("shows the server's sentence when a login is refused", async () => {
    const body = JSON.stringify({ non_field_errors: ["Unable to log in with provided credentials."] });
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue({ ok: false, status: 400, text: () => Promise.resolve(body) }));

    await expect(api.login({ username: "a", password: "b" })).rejects.toThrow("Unable to log in with provided credentials.");
  });

  it("logs out with a CSRF-protected POST", async () => {
    const fetchMock = vi.fn().mockResolvedValue({ ok: true, status: 204 });
    vi.stubGlobal("fetch", fetchMock);

    await api.logout();

    const [url, options] = fetchMock.mock.calls[0];
    expect(url).toBe("/api/auth/logout/");
    expect(options.method).toBe("POST");
    expect(options.headers["X-CSRFToken"]).toBe("cookietoken");
  });

  it("posts the invite token in the body, never in the URL", async () => {
    const fetchMock = vi.fn().mockResolvedValue(okJson({ valid: true }));
    vi.stubGlobal("fetch", fetchMock);

    await api.checkInvite("secret-token");
    await api.acceptInvite({ token: "secret-token", username: "dave", email: "", password: "s3cure-pass-xyz" });

    const [checkUrl, check] = fetchMock.mock.calls[0];
    expect(checkUrl).toBe("/api/auth/invites/check/");
    expect(check.method).toBe("POST");
    expect(JSON.parse(check.body)).toEqual({ token: "secret-token" });
    const [acceptUrl, accept] = fetchMock.mock.calls[1];
    expect(acceptUrl).toBe("/api/auth/invites/accept/");
    expect(JSON.parse(accept.body).token).toBe("secret-token");
    for (const [url] of fetchMock.mock.calls) expect(url).not.toContain("secret-token");
  });

  it("creates an invite with role and label", async () => {
    const fetchMock = vi.fn().mockResolvedValue(okJson({ url: "http://x/invite/t", token: "t" }, 201));
    vi.stubGlobal("fetch", fetchMock);

    expect((await api.createInvite({ role: "readonly", label: "Sam" })).url).toBe("http://x/invite/t");

    const [url, options] = fetchMock.mock.calls[0];
    expect(url).toBe("/api/auth/invites/");
    expect(JSON.parse(options.body)).toEqual({ role: "readonly", label: "Sam" });
    expect(options.headers["X-CSRFToken"]).toBe("cookietoken");
  });

  it("builds the ROM list query from search, platform and page, skipping blanks", async () => {
    const envelope = { count: 0, next: null, previous: null, results: [] };
    const fetchMock = vi.fn().mockResolvedValue({ ok: true, status: 200, json: () => Promise.resolve(envelope) });
    vi.stubGlobal("fetch", fetchMock);

    expect(await api.listRoms({ search: "  zelda ", platform: "Game Boy Advance", page: 2 })).toEqual(envelope);
    await api.listRoms({ search: "", platform: "", page: 1 });

    expect(fetchMock.mock.calls[0][0]).toBe("/api/roms/?search=zelda&platform=Game+Boy+Advance&page=2");
    expect(fetchMock.mock.calls[1][0]).toBe("/api/roms/");
  });

  it("fetches the distinct platform list", async () => {
    const fetchMock = vi.fn().mockResolvedValue({ ok: true, status: 200, json: () => Promise.resolve(["NES"]) });
    vi.stubGlobal("fetch", fetchMock);

    expect(await api.listPlatforms()).toEqual(["NES"]);
    expect(fetchMock.mock.calls[0][0]).toBe("/api/roms/platforms/");
  });

  it("falls back to the original filename when there is no Content-Disposition", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue({
      ok: true,
      status: 200,
      headers: new Headers(),
      blob: () => Promise.resolve(new Blob(["NES"]))
    }));
    vi.stubGlobal("URL", { ...URL, createObjectURL: vi.fn(() => "blob:rom"), revokeObjectURL: vi.fn() });
    const click = vi.spyOn(HTMLAnchorElement.prototype, "click").mockImplementation(() => {});

    await api.downloadRom({ id: 7, title: "Zelda", filename: "Zelda (USA).nes", extension: ".nes" });

    expect(click.mock.contexts[0].download).toBe("Zelda (USA).nes");
    click.mockRestore();
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

    await api.downloadRom({ id: 7, title: "Zelda", extension: ".nes" });

    const [url, options] = fetchMock.mock.calls[0];
    expect(url).toBe("/api/roms/7/download/");
    expect(options.credentials).toBe("include");
    expect(options.headers.Authorization).toBeUndefined();
    expect(createObjectURL).toHaveBeenCalledWith(blob);
    expect(click).toHaveBeenCalledTimes(1);
    expect(click.mock.contexts[0].download).toBe("Zelda.nes");
    expect(revokeObjectURL).toHaveBeenCalledWith("blob:rom");
    click.mockRestore();
  });

  it("loads cover art through the authenticated endpoint as an object URL", async () => {
    const blob = new Blob(["PNG"], { type: "image/png" });
    const fetchMock = vi.fn().mockResolvedValue({ ok: true, status: 200, blob: () => Promise.resolve(blob) });
    vi.stubGlobal("fetch", fetchMock);
    const createObjectURL = vi.fn(() => "blob:cover");
    vi.stubGlobal("URL", { ...URL, createObjectURL });

    const url = await api.coverObjectUrl({ id: 7, cover_art_url: "http://host/api/roms/7/cover/" });

    const [path, options] = fetchMock.mock.calls[0];
    expect(path).toBe("/api/roms/7/cover/");
    expect(options.credentials).toBe("include");
    expect(options.headers.Authorization).toBeUndefined();
    expect(createObjectURL).toHaveBeenCalledWith(blob);
    expect(url).toBe("blob:cover");
  });

  it("checks cover existence with an authenticated HEAD request, false on 404", async () => {
    const fetchMock = vi
      .fn()
      .mockResolvedValueOnce({ ok: false, status: 404, text: () => Promise.resolve("") })
      .mockResolvedValueOnce({ ok: true, status: 200 });
    vi.stubGlobal("fetch", fetchMock);

    expect(await api.coverExists(7)).toBe(false);
    expect(await api.coverExists(7)).toBe(true);

    const [path, options] = fetchMock.mock.calls[0];
    expect(path).toBe("/api/roms/7/cover/");
    expect(options.method).toBe("HEAD");
    expect(options.credentials).toBe("include");
    expect(options.headers.Authorization).toBeUndefined();
  });

  it("approves a pairing code with an authenticated JSON POST", async () => {
    const fetchMock = vi
      .fn()
      .mockResolvedValue({ ok: true, status: 200, json: () => Promise.resolve({ detail: "Device approved." }) });
    vi.stubGlobal("fetch", fetchMock);

    expect(await api.approveDevice("ABC123")).toEqual({ detail: "Device approved." });

    const [path, options] = fetchMock.mock.calls[0];
    expect(path).toBe("/api/devices/pair/approve");
    expect(options.method).toBe("POST");
    expect(options.credentials).toBe("include");
    expect(options.headers.Authorization).toBeUndefined();
    expect(options.headers["Content-Type"]).toBe("application/json");
    expect(JSON.parse(options.body)).toEqual({ code: "ABC123" });
  });

  it("surfaces the server's detail message when approval is refused", async () => {
    const body = JSON.stringify({ detail: "This pairing code has expired." });
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue({ ok: false, status: 410, text: () => Promise.resolve(body) }));

    await expect(api.approveDevice("ABC123")).rejects.toThrow("This pairing code has expired.");
  });

  it("fetches library status and queues rescans", async () => {
    const fetchMock = vi.fn().mockResolvedValue({ ok: true, status: 200, json: () => Promise.resolve({ running: false }) });
    vi.stubGlobal("fetch", fetchMock);

    expect(await api.libraryStatus()).toEqual({ running: false });
    expect(fetchMock.mock.calls[0][0]).toBe("/api/library/status/");

    await api.rescanLibrary();
    await api.rescanLibrary({ acceptRemovals: true });
    const [path, options] = fetchMock.mock.calls[1];
    expect(path).toBe("/api/library/scan/");
    expect(options.method).toBe("POST");
    expect(options.headers["Content-Type"]).toBe("application/json");
    expect(JSON.parse(options.body)).toEqual({ accept_removals: false });
    expect(JSON.parse(fetchMock.mock.calls[2][1].body)).toEqual({ accept_removals: true });
  });

  it("surfaces the detail message when a rescan or an upload is refused", async () => {
    const body = JSON.stringify({ detail: "A library scan is already running." });
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue({ ok: false, status: 409, text: () => Promise.resolve(body) }));
    await expect(api.rescanLibrary()).rejects.toThrow("A library scan is already running.");

    const refusal = JSON.stringify({ detail: "This library is read-only." });
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue({ ok: false, status: 403, text: () => Promise.resolve(refusal) }));
    await expect(api.createRom(new FormData())).rejects.toThrow("This library is read-only.");
  });

  it("turns DRF field errors on upload into the server's sentence", async () => {
    const cases = [
      [{ file: ["Super Mario World (U).smc is already in the library."] }, "Super Mario World (U).smc is already in the library."],
      [{ file: "The ROM library is unavailable." }, "The ROM library is unavailable."],
      [{ file: { nested: "x" } }, JSON.stringify({ file: { nested: "x" } })]
    ];
    for (const [body, expected] of cases) {
      vi.stubGlobal("fetch", vi.fn().mockResolvedValue({ ok: false, status: 400, text: () => Promise.resolve(JSON.stringify(body)) }));
      await expect(api.createRom(new FormData())).rejects.toMatchObject({ message: expected });
    }
  });

  it("keeps offline errors flagged when a refused-request helper is used", async () => {
    vi.stubGlobal("fetch", vi.fn().mockRejectedValue(new TypeError("Failed to fetch")));
    const err = await api.createRom(new FormData()).catch((e) => e);
    expect(isNetworkError(err)).toBe(true);
  });

  it("parses Content-Disposition filenames", () => {
    expect(filenameFromDisposition('attachment; filename="Zelda.nes"')).toBe("Zelda.nes");
    expect(filenameFromDisposition("attachment; filename*=UTF-8''Pok%C3%A9mon.gb")).toBe("Pokémon.gb");
    expect(filenameFromDisposition(null)).toBeNull();
  });
});

describe("playlist api", () => {
  beforeEach(() => {
    setCsrfCookie("cookietoken");
  });

  afterEach(() => {
    vi.unstubAllGlobals();
    setCsrfCookie(null);
  });

  function stubFetch(body = {}, status = 200) {
    const fetchMock = vi.fn().mockResolvedValue({ ok: true, status, json: () => Promise.resolve(body) });
    vi.stubGlobal("fetch", fetchMock);
    return fetchMock;
  }

  it("lists and fetches playlists", async () => {
    const fetchMock = stubFetch([]);
    await api.listPlaylists();
    await api.getPlaylist(4);
    expect(fetchMock.mock.calls[0][0]).toBe("/api/playlists/");
    expect(fetchMock.mock.calls[1][0]).toBe("/api/playlists/4/");
  });

  it("creates a playlist with a JSON body", async () => {
    const fetchMock = stubFetch({ id: 1 });
    await api.createPlaylist({ name: "Road trip", rom_ids: [2, 1] });
    const [url, options] = fetchMock.mock.calls[0];
    expect(url).toBe("/api/playlists/");
    expect(options.method).toBe("POST");
    expect(options.headers["Content-Type"]).toBe("application/json");
    expect(JSON.parse(options.body)).toEqual({ name: "Road trip", rom_ids: [2, 1] });
  });

  it("updates with PATCH and deletes", async () => {
    const fetchMock = stubFetch({});
    await api.updatePlaylist(4, { name: "New", rom_ids: [3] });
    const [url, options] = fetchMock.mock.calls[0];
    expect(url).toBe("/api/playlists/4/");
    expect(options.method).toBe("PATCH");
    expect(JSON.parse(options.body)).toEqual({ name: "New", rom_ids: [3] });

    stubFetch(null, 204);
    const deleteMock = stubFetch(null, 204);
    expect(await api.deletePlaylist(4)).toBeNull();
    expect(deleteMock.mock.calls[0][1].method).toBe("DELETE");
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

  it("maps each fixed error code to its message and strips the fragment", () => {
    for (const [code, message] of Object.entries(OIDC_ERROR_MESSAGES)) {
      window.history.replaceState(null, "", `/library?x=1#oidc_error=${code}`);
      expect(consumeOidcFragment()).toEqual({ error: message });
      expect(window.location.hash).toBe("");
      expect(window.location.pathname + window.location.search).toBe("/library?x=1");
    }
    expect(Object.keys(OIDC_ERROR_MESSAGES).sort()).toEqual(
      ["disabled", "failed", "no_subject", "not_allowed", "provider_error"]
    );
  });

  it("never shows text taken from the URL: an unknown code is ignored, but still stripped", () => {
    window.history.replaceState(null, "", "/#oidc_error=%3Cb%3EYour+account+is+hacked%3C%2Fb%3E");
    expect(consumeOidcFragment()).toBeNull();
    expect(window.location.hash).toBe("");
  });

  it("does not look for a token in the fragment", () => {
    window.history.replaceState(null, "", "/#oidc_token=tok123");
    expect(consumeOidcFragment()).toBeNull();
    expect(window.location.hash).toBe("#oidc_token=tok123");
  });
});
