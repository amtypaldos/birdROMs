import { afterEach, describe, expect, it, vi } from "vitest";
import { act, cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";

function page(results, { count = results.length, next = null, previous = null } = {}) {
  return { count, next, previous, results };
}

vi.mock("./api/client", () => ({
  consumeOidcFragment: vi.fn(() => null),
  api: {
    oidcLoginUrl: "/api/auth/oidc/login/",
    handheldInfo: vi.fn(() => Promise.resolve({ available: false })),
    authConfig: vi.fn(() => Promise.resolve({ methods: ["local"], invites: true })),
    me: vi.fn(() => Promise.resolve({ id: 1, username: "alice", email: "", role: "readonly" })),
    login: vi.fn(),
    register: vi.fn(),
    logout: vi.fn(() => Promise.resolve(null)),
    checkInvite: vi.fn(() => Promise.resolve({ valid: true })),
    acceptInvite: vi.fn(),
    createInvite: vi.fn(),
    listRoms: vi.fn(() => Promise.resolve(page([]))),
    listPlatforms: vi.fn(() => Promise.resolve([])),
    createRom: vi.fn(),
    libraryStatus: vi.fn(() => Promise.resolve({ backend: "local", writable: true, write_covers: true, running: false, last_scan: null })),
    rescanLibrary: vi.fn(),
    scrapeCover: vi.fn(),
    downloadRom: vi.fn(() => Promise.resolve()),
    coverObjectUrl: vi.fn(() => Promise.resolve("blob:cover")),
    coverExists: vi.fn(() => Promise.resolve(false)),
    approveDevice: vi.fn(() => Promise.resolve({ detail: "Device approved." })),
    listPlaylists: vi.fn(() => Promise.resolve([])),
    getPlaylist: vi.fn(),
    createPlaylist: vi.fn(),
    updatePlaylist: vi.fn(),
    deletePlaylist: vi.fn()
  }
}));

import App, { COVER_POLL_INTERVAL_MS, COVER_POLL_MAX_ATTEMPTS, platformFamily } from "./App";
import { offlineError } from "./offline";
import { api, consumeOidcFragment } from "./api/client";

// The app is signed in whenever `me()` answers (the stub does by default); a 401 from it means signed out.
function httpError(status) {
  return Object.assign(new Error("{}"), { status });
}

function signedOutOnce() {
  api.me.mockRejectedValueOnce(httpError(401));
}

describe("App", () => {
  it("renders the login form when there is no session", async () => {
    signedOutOnce();
    render(<App />);

    expect(await screen.findByRole("heading", { name: "Login" })).toBeInTheDocument();
    expect(screen.getByPlaceholderText("Username")).toBeInTheDocument();
    expect(screen.getByPlaceholderText("Password")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Login" })).toBeInTheDocument();
    expect(screen.queryByText("ROM Library")).not.toBeInTheDocument();
    expect(api.listRoms).not.toHaveBeenCalled();
  });

  it("shows an offline notice, not the login form, when the API cannot be reached at start-up", async () => {
    api.me.mockRejectedValueOnce(offlineError());

    render(<App />);

    expect(await screen.findByText(/You're offline/)).toBeInTheDocument();
    // We can't tell signed-in from signed-out without the server, so neither screen is shown.
    expect(screen.queryByRole("heading", { name: "Login" })).not.toBeInTheDocument();
    expect(screen.queryByText("ROM Library")).not.toBeInTheDocument();
    expect(api.authConfig).not.toHaveBeenCalled();
  });

  it("checks the session again when the connection comes back after an offline start", async () => {
    api.me.mockRejectedValueOnce(offlineError());
    render(<App />);
    expect(await screen.findByText(/You're offline/)).toBeInTheDocument();

    act(() => {
      window.dispatchEvent(new Event("online"));
    });

    expect(await screen.findByText("ROM Library")).toBeInTheDocument();
    expect(screen.queryByText(/You're offline/)).not.toBeInTheDocument();
  });

  it("stays signed in, with an offline notice, when the library cannot be reached", async () => {
    api.listRoms.mockRejectedValueOnce(offlineError());

    render(<App />);

    expect(await screen.findByText(/You're offline/)).toBeInTheDocument();
    expect(await screen.findByText("alice")).toBeInTheDocument();
    expect(screen.queryByRole("heading", { name: "Login" })).not.toBeInTheDocument();
  });

  it("shows the login form when the sign-in check is refused (401 or 403)", async () => {
    for (const status of [401, 403]) {
      api.me.mockRejectedValueOnce(httpError(status));

      const { unmount } = render(<App />);

      expect(await screen.findByRole("heading", { name: "Login" })).toBeInTheDocument();
      expect(screen.queryByText(/You're offline/)).not.toBeInTheDocument();
      expect(screen.queryByRole("alert")).not.toBeInTheDocument(); // signed out is not an error
      unmount();
    }
  });

  it("shows an error, not the library, when the sign-in check fails for another reason", async () => {
    api.me.mockRejectedValueOnce(httpError(500));

    render(<App />);

    expect(await screen.findByRole("alert")).toBeInTheDocument();
    expect(screen.queryByText("ROM Library")).not.toBeInTheDocument();
  });

  it("shows no empty state or account-loading label while offline", async () => {
    api.listRoms.mockRejectedValueOnce(offlineError());

    render(<App />);

    expect(await screen.findByText(/You're offline/)).toBeInTheDocument();
    expect(screen.queryByText("No ROMs found.")).not.toBeInTheDocument();
    expect(screen.queryByText("Loading account…")).not.toBeInTheDocument();
  });

  it("clears the offline notice and reloads when the connection comes back", async () => {
    api.listRoms.mockRejectedValueOnce(offlineError());

    render(<App />);
    expect(await screen.findByText(/You're offline/)).toBeInTheDocument();

    act(() => {
      window.dispatchEvent(new Event("online"));
    });

    await waitFor(() => expect(screen.queryByText(/You're offline/)).not.toBeInTheDocument());
    expect(api.listRoms).toHaveBeenCalledTimes(2);
  });

  it("downloads through the authenticated API instead of linking to media", async () => {
    const rom = { id: 3, title: "Zelda", platform: "NES", extension: ".nes", download_url: "/api/roms/3/download/" };
    api.listRoms.mockResolvedValueOnce(page([rom]));

    const { container } = render(<App />);
    fireEvent.click(await screen.findByRole("button", { name: "Download" }));

    expect(api.downloadRom).toHaveBeenCalledWith(rom);
    expect(container.querySelector("a[href]")).toBeNull();
  });

  it("loads stored cover art with the token and skips ROMs without art", async () => {
    const withArt = { id: 3, title: "Zelda", platform: "NES", extension: ".nes", cover_art_url: "/api/roms/3/cover/" };
    const without = { id: 4, title: "Metroid", platform: "NES", extension: ".nes", cover_art_url: null };
    api.listRoms.mockResolvedValueOnce(page([withArt, without]));
    const revokeObjectURL = vi.fn(); // jsdom has no object URLs
    vi.stubGlobal("URL", { revokeObjectURL });

    const { unmount } = render(<App />);

    expect(await screen.findByRole("img", { name: "Zelda" })).toHaveAttribute("src", "blob:cover");
    expect(screen.queryByRole("img", { name: "Metroid" })).not.toBeInTheDocument();
    expect(api.coverObjectUrl).toHaveBeenCalledTimes(1);
    expect(api.coverObjectUrl).toHaveBeenCalledWith(expect.objectContaining({ id: 3 }));
    unmount();
    expect(revokeObjectURL).toHaveBeenCalledWith("blob:cover");
    vi.unstubAllGlobals();
  });

  it("shows only the SSO button when only OIDC is enabled", async () => {
    signedOutOnce();
    api.authConfig.mockResolvedValueOnce({
      methods: ["oidc"],
      oidc: { provider_name: "Pocket ID", login_url: "/api/auth/oidc/login/" }
    });

    render(<App />);

    const sso = await screen.findByRole("link", { name: "Login with Pocket ID" });
    expect(sso).toHaveAttribute("href", "/api/auth/oidc/login/");
    expect(screen.queryByPlaceholderText("Username")).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Login" })).not.toBeInTheDocument();
  });

  it("shows both the local form and the SSO button when both are enabled", async () => {
    signedOutOnce();
    api.authConfig.mockResolvedValueOnce({ methods: ["local", "oidc"], oidc: { provider_name: "SSO" } });

    render(<App />);

    expect(await screen.findByRole("link", { name: "Login with SSO" })).toBeInTheDocument();
    expect(screen.getByPlaceholderText("Username")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Login" })).toBeInTheDocument();
  });

  it("hides the SSO button when only local login is enabled", async () => {
    signedOutOnce();
    render(<App />);

    expect(await screen.findByPlaceholderText("Username")).toBeInTheDocument();
    expect(screen.queryByRole("link", { name: /Login with/ })).not.toBeInTheDocument();
  });

  it("hides the create-account button when registration is closed", async () => {
    signedOutOnce();
    api.authConfig.mockResolvedValueOnce({ methods: ["local"], registration: false });

    render(<App />);

    expect(await screen.findByRole("button", { name: "Login" })).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Create account" })).not.toBeInTheDocument();
  });

  it("hides the create-account button when the config has no registration flag", async () => {
    signedOutOnce();
    render(<App />);

    expect(await screen.findByRole("button", { name: "Login" })).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Create account" })).not.toBeInTheDocument();
  });

  it("registers a local account and signs in", async () => {
    signedOutOnce();
    api.authConfig.mockResolvedValueOnce({ methods: ["local"], registration: true });
    api.register.mockResolvedValueOnce({ user: { username: "bob" } });

    render(<App />);
    fireEvent.click(await screen.findByRole("button", { name: "Create account" }));
    fireEvent.change(screen.getByPlaceholderText("Username"), { target: { value: "bob" } });
    fireEvent.change(screen.getByPlaceholderText("Email"), { target: { value: "bob@example.com" } });
    fireEvent.change(screen.getByPlaceholderText("Password"), { target: { value: "s3cure-pass" } });
    fireEvent.click(screen.getByRole("button", { name: "Register" }));

    await waitFor(() =>
      expect(api.register).toHaveBeenCalledWith({ username: "bob", email: "bob@example.com", password: "s3cure-pass" })
    );
    // The session cookie is the sign-in: the app just asks `me()` who it is, and never looks for a token.
    expect(await screen.findByText("ROM Library")).toBeInTheDocument();
    expect(api.me).toHaveBeenCalledTimes(2);
    expect(localStorage.length).toBe(0);
  });

  it("is signed in after an SSO redirect by asking me(), with no token anywhere", async () => {
    window.history.replaceState(null, "", "/");
    api.me.mockResolvedValueOnce({ id: 7, username: "grace", email: "g@example.com", role: "super_admin" });

    render(<App />);

    expect(await screen.findByText("grace")).toBeInTheDocument();
    expect(screen.getByText(/super_admin/)).toBeInTheDocument();
    expect(localStorage.length).toBe(0);
  });

  it("shows an SSO error returned by the callback", async () => {
    signedOutOnce();
    consumeOidcFragment.mockReturnValueOnce({ error: "Single sign-on failed. Please try again." });

    render(<App />);

    expect(await screen.findByText("Single sign-on failed. Please try again.")).toBeInTheDocument();
    expect(await screen.findByRole("heading", { name: "Login" })).toBeInTheDocument();
    expect(api.me).not.toHaveBeenCalled(); // a failed redirect means there is no session to look for
  });

  it("drives the library with search, platform filter and pagination", async () => {
    const zelda = { id: 1, title: "Zelda", platform: "NES", extension: ".nes" };
    const metroid = { id: 2, title: "Metroid", platform: "NES", extension: ".nes" };
    api.listPlatforms.mockResolvedValue(["Game Boy Advance", "NES"]);
    api.listRoms.mockImplementation(({ page: number = 1 } = {}) =>
      Promise.resolve(
        number === 1
          ? page([zelda], { count: 30, next: "/api/roms/?page=2" })
          : page([metroid], { count: 30, previous: "/api/roms/" })
      )
    );

    render(<App />);

    expect(await screen.findByText("Zelda")).toBeInTheDocument();
    expect(api.listRoms).toHaveBeenLastCalledWith({ search: "", platform: "", page: 1 });
    expect(screen.getByText("Page 1 of 2 · 30 ROMs")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Previous" })).toBeDisabled();

    fireEvent.click(screen.getByRole("button", { name: "Next" }));
    expect(await screen.findByText("Metroid")).toBeInTheDocument();
    expect(api.listRoms).toHaveBeenLastCalledWith({ search: "", platform: "", page: 2 });
    expect(screen.getByRole("button", { name: "Next" })).toBeDisabled();

    fireEvent.change(await screen.findByRole("combobox", { name: "Platform" }), { target: { value: "NES" } });
    await waitFor(() => expect(api.listRoms).toHaveBeenLastCalledWith({ search: "", platform: "NES", page: 1 }));

    fireEvent.change(screen.getByPlaceholderText("Search titles"), { target: { value: "zel" } });
    fireEvent.click(screen.getByRole("button", { name: "Search" }));
    await waitFor(() => expect(api.listRoms).toHaveBeenLastCalledWith({ search: "zel", platform: "NES", page: 1 }));

  });

  it("hides upload and scrape controls from readonly users", async () => {
    api.listRoms.mockResolvedValue(page([{ id: 1, title: "Zelda", platform: "NES", extension: ".nes" }]));

    render(<App />);

    expect(await screen.findByText("Zelda")).toBeInTheDocument();
    expect(await screen.findByText("alice")).toBeInTheDocument();
    expect(screen.getByText("readonly")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Download" })).toBeInTheDocument();
    expect(screen.queryByRole("heading", { name: "Upload ROM" })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Upload" })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Scrape Cover" })).not.toBeInTheDocument();
  });

  it("shows upload and scrape controls to super_admin users", async () => {
    api.me.mockResolvedValueOnce({ id: 2, username: "root", email: "", role: "super_admin" });
    api.listRoms.mockResolvedValue(page([{ id: 1, title: "Zelda", platform: "NES", extension: ".nes" }]));

    render(<App />);

    expect(await screen.findByRole("heading", { name: "Upload ROM" })).toBeInTheDocument();
    expect(screen.getByText("root")).toBeInTheDocument();
    expect(screen.getByText("super_admin")).toBeInTheDocument();
    expect(await screen.findByRole("button", { name: "Scrape Cover" })).toBeInTheDocument();
  });

  it("shows upload but no scrape or library admin controls to members", async () => {
    api.me.mockResolvedValueOnce({ id: 3, username: "helper", email: "", role: "member" });
    api.listRoms.mockResolvedValue(page([{ id: 1, title: "Zelda", platform: "NES", extension: ".nes" }]));

    render(<App />);

    expect(await screen.findByRole("heading", { name: "Upload ROM" })).toBeInTheDocument();
    expect(screen.getByText("helper")).toBeInTheDocument();
    expect(screen.getByText("member")).toBeInTheDocument();
    expect(await screen.findByText("Zelda")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Download" })).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Scrape Cover" })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Rescan now" })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Accept removals" })).not.toBeInTheDocument();
    expect(screen.queryByText("Invite a friend")).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /delete/i })).not.toBeInTheDocument();
    expect(api.libraryStatus).not.toHaveBeenCalled();
  });

  it("still shows scrape, rescan and invites to super_admin users", async () => {
    api.me.mockResolvedValueOnce({ id: 2, username: "root", email: "", role: "super_admin" });
    api.listRoms.mockResolvedValue(page([{ id: 1, title: "Zelda", platform: "NES", extension: ".nes" }]));

    render(<App />);

    expect(await screen.findByRole("button", { name: "Scrape Cover" })).toBeInTheDocument();
    expect(await screen.findByRole("button", { name: "Rescan now" })).toBeInTheDocument();
    expect(screen.getByText("Invite a friend")).toBeInTheDocument();
  });

  it("uploads just the file, with no title input", async () => {
    api.me.mockResolvedValueOnce({ id: 2, username: "root", email: "", role: "super_admin" });
    api.listRoms.mockResolvedValue(page([]));
    api.createRom.mockResolvedValue({});

    render(<App />);

    const fileInput = await screen.findByLabelText("ROM file");
    expect(screen.queryByLabelText("ROM title")).not.toBeInTheDocument();
    const file = new File(["x"], "Zelda (USA).nes");
    fireEvent.change(fileInput, { target: { files: [file] } });
    fireEvent.click(screen.getByRole("button", { name: "Upload" }));

    await waitFor(() => expect(api.createRom).toHaveBeenCalledTimes(1));
    const formData = api.createRom.mock.calls[0][0];
    expect(formData.has("title")).toBe(false);
    expect(formData.get("file").name).toBe("Zelda (USA).nes");
  });

  it("shows an upload refusal from the API in the upload panel", async () => {
    api.me.mockResolvedValueOnce({ id: 2, username: "root", email: "", role: "super_admin" });
    api.listRoms.mockResolvedValue(page([]));
    api.createRom.mockRejectedValue(new Error("This library is read-only."));

    render(<App />);

    fireEvent.change(await screen.findByLabelText("ROM file"), { target: { files: [new File(["x"], "a.nes")] } });
    fireEvent.click(screen.getByRole("button", { name: "Upload" }));

    expect(await screen.findByText("This library is read-only.")).toBeInTheDocument();
  });

  it("renders a ROM card with no uploader and shows the library panel only to admins", async () => {
    api.listRoms.mockResolvedValue(page([{ id: 1, title: "Zelda", platform: "NES", extension: ".nes", uploaded_by_username: null }]));

    const { unmount } = render(<App />);
    expect(await screen.findByRole("heading", { name: "Zelda" })).toBeInTheDocument();
    expect(screen.queryByRole("region", { name: "Library scan" })).not.toBeInTheDocument();
    unmount();

    api.me.mockResolvedValueOnce({ id: 2, username: "root", email: "", role: "super_admin" });
    render(<App />);
    expect(await screen.findByRole("region", { name: "Library scan" })).toBeInTheDocument();
  });

  it("shows region and dump tags under the title, and nothing without tags", async () => {
    const tagged = { id: 1, title: "Zelda", filename: "Zelda (USA) [!].nes", tags: ["USA", "Verified good dump"], platform: "NES", extension: ".nes" };
    const plain = { id: 2, title: "Metroid", platform: "NES", extension: ".nes" };
    const empty = { id: 3, title: "Kirby", filename: "Kirby.nes", tags: [], platform: "NES", extension: ".nes" };
    api.listRoms.mockResolvedValueOnce(page([tagged, plain, empty]));

    const { container } = render(<App />);

    expect(await screen.findByText("USA · Verified good dump")).toHaveClass("rom-tags");
    expect(container.querySelectorAll(".rom-tags")).toHaveLength(1);
    expect(screen.getByRole("heading", { name: "Zelda" })).toHaveAttribute("title", "Zelda (USA) [!].nes");
    expect(screen.getByRole("heading", { name: "Metroid" })).toHaveAttribute("title", "Metroid");
  });

  it("shows neither the library nor write controls until the session check answers", async () => {
    api.me.mockReturnValueOnce(new Promise(() => {}));
    api.listRoms.mockResolvedValue(page([{ id: 1, title: "Zelda", platform: "NES", extension: ".nes" }]));

    render(<App />);

    expect(await screen.findByText("Checking your session…")).toBeInTheDocument();
    expect(screen.queryByText("Zelda")).not.toBeInTheDocument();
    expect(screen.queryByRole("heading", { name: "Login" })).not.toBeInTheDocument();
    expect(screen.queryByRole("heading", { name: "Upload ROM" })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Scrape Cover" })).not.toBeInTheDocument();
    expect(api.listRoms).not.toHaveBeenCalled();
  });

  it("stays signed in and says so when logging out fails", async () => {
    api.logout.mockRejectedValueOnce(offlineError());
    render(<App />);

    fireEvent.click(await screen.findByRole("button", { name: "Logout" }));

    expect(await screen.findByText(/You're offline/)).toBeInTheDocument();
    expect(screen.queryByRole("heading", { name: "Login" })).not.toBeInTheDocument();
    expect(screen.getByText("alice")).toBeInTheDocument();
  });

  it("shows the role after a local login and logs out back to the login form", async () => {
    signedOutOnce();
    api.login.mockResolvedValueOnce({ user: { username: "root" } });
    api.me.mockResolvedValueOnce({ id: 2, username: "root", email: "", role: "super_admin" });

    render(<App />);
    fireEvent.change(await screen.findByPlaceholderText("Username"), { target: { value: "root" } });
    fireEvent.change(screen.getByPlaceholderText("Password"), { target: { value: "pw" } });
    fireEvent.click(screen.getByRole("button", { name: "Login" }));

    expect(await screen.findByRole("heading", { name: "Upload ROM" })).toBeInTheDocument();
    expect(screen.getByText("super_admin")).toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: "Logout" }));

    await waitFor(() => expect(api.logout).toHaveBeenCalledTimes(1));
    expect(await screen.findByRole("heading", { name: "Login" })).toBeInTheDocument();
    expect(screen.queryByRole("heading", { name: "Upload ROM" })).not.toBeInTheDocument();
    expect(screen.queryByText("root")).not.toBeInTheDocument();
  });

  it("says when no ROMs match the filters", async () => {

    render(<App />);

    expect(await screen.findByText("No ROMs found.")).toBeInTheDocument();
  });

  it("renders the library as a grid of cover cards with platform badges and placeholders", async () => {
    const zelda = { id: 1, title: "Zelda", platform: "NES", extension: ".nes", cover_art_url: "/api/roms/1/cover/" };
    const sonic = { id: 2, title: "Sonic", platform: "Sega Genesis", extension: ".md", cover_art_url: null };
    api.listRoms.mockResolvedValue(page([zelda, sonic]));
    vi.stubGlobal("URL", { revokeObjectURL: vi.fn() }); // jsdom has no object URLs

    const { container, unmount } = render(<App />);

    const grid = await screen.findByRole("list", { name: "ROMs" });
    const cards = grid.querySelectorAll("li.rom-card");
    expect(cards).toHaveLength(2);
    expect(await screen.findByRole("img", { name: "Zelda" })).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "Sonic" })).toBeInTheDocument();
    expect(screen.getByText("Sega Genesis")).toHaveClass("platform-badge");
    expect(cards[0]).toHaveAttribute("data-family", "nintendo");
    expect(cards[1]).toHaveAttribute("data-family", "sega");
    // ROMs without art get a decorative placeholder that is hidden from assistive tech.
    const placeholder = cards[1].querySelector(".cover-placeholder");
    expect(placeholder).toHaveAttribute("aria-hidden", "true");
    expect(placeholder).toHaveTextContent("S");
    expect(container.querySelectorAll(".skeleton")).toHaveLength(0);
    unmount();
    vi.unstubAllGlobals();
  });

  it("shows loading skeletons until the first page arrives", async () => {
    api.listRoms.mockReturnValueOnce(new Promise(() => {}));

    render(<App />);

    expect(await screen.findByRole("list", { name: "Loading ROMs" })).toBeInTheDocument();
    expect(screen.queryByText("No ROMs found.")).not.toBeInTheDocument();
  });

  it("maps platforms to badge families", () => {
    expect(platformFamily("SNES")).toBe("nintendo");
    expect(platformFamily("Game Boy Advance")).toBe("nintendo");
    expect(platformFamily("Sega Dreamcast")).toBe("sega");
    expect(platformFamily("Sony PSP")).toBe("sony");
    expect(platformFamily("Atari Lynx")).toBe("atari");
    expect(platformFamily("WonderSwan")).toBe("other");
    expect(platformFamily(undefined)).toBe("other");
  });
});

describe("global drag-and-drop upload", () => {
  function romFile(name) {
    return new File(["data"], name, { type: "application/octet-stream" });
  }

  function dragData(files) {
    return { dataTransfer: { files, types: ["Files"] } };
  }

  async function renderAs(role) {
    api.me.mockResolvedValue({ id: 2, username: "root", email: "", role });
    api.listRoms.mockResolvedValue(page([]));
    render(<App />);
    await screen.findByText("No ROMs found.");
    await screen.findByText(role);
  }

  it("test_dropzone_super_admin_only", async () => {
    api.createRom.mockResolvedValue({});
    await renderAs("readonly");

    fireEvent.dragEnter(document.body, dragData([romFile("a.nes")]));
    expect(screen.queryByText("Drop ROM files to upload")).not.toBeInTheDocument();
    fireEvent.drop(document.body, dragData([romFile("a.nes")]));
    expect(api.createRom).not.toHaveBeenCalled();
    cleanup();

    await renderAs("super_admin");
    fireEvent.dragEnter(document.body, dragData([romFile("a.nes")]));
    expect(await screen.findByText("Drop ROM files to upload")).toBeInTheDocument();
    fireEvent.dragLeave(document.body, dragData([romFile("a.nes")]));
    expect(screen.queryByText("Drop ROM files to upload")).not.toBeInTheDocument();
  });

  it("test_dropzone_open_to_members", async () => {
    api.createRom.mockResolvedValue({});
    await renderAs("member");

    fireEvent.dragEnter(document.body, dragData([romFile("a.nes")]));
    expect(await screen.findByText("Drop ROM files to upload")).toBeInTheDocument();
    fireEvent.drop(document.body, dragData([romFile("a.nes")]));
    await waitFor(() => expect(api.createRom).toHaveBeenCalledTimes(1));
  });

  it("test_multi_drop_uploads_each", async () => {
    api.createRom.mockResolvedValue({});
    await renderAs("super_admin");
    const callsBefore = api.listRoms.mock.calls.length;

    fireEvent.dragEnter(document.body, dragData([romFile("a.nes")]));
    fireEvent.drop(document.body, dragData([romFile("a.nes"), romFile("b.sfc"), romFile("c.gba")]));

    await waitFor(() => expect(api.createRom).toHaveBeenCalledTimes(3));
    const titles = api.createRom.mock.calls.map(([formData]) => formData.get("title"));
    expect(titles).toEqual([null, null, null]);
    const names = api.createRom.mock.calls.map(([formData]) => formData.get("file").name);
    expect(names).toEqual(["a.nes", "b.sfc", "c.gba"]);
    expect(api.createRom.mock.calls[0][0].get("file").name).toBe("a.nes");
    await waitFor(() => expect(screen.getAllByText("Uploaded")).toHaveLength(3));
    expect(screen.queryByText("Drop ROM files to upload")).not.toBeInTheDocument();
    await waitFor(() => expect(api.listRoms.mock.calls.length).toBeGreaterThan(callsBefore));
  });

  it("uploads one file at a time", async () => {
    let active = 0;
    let peak = 0;
    api.createRom.mockImplementation(async () => {
      active += 1;
      peak = Math.max(peak, active);
      await new Promise((resolve) => setTimeout(resolve, 5));
      active -= 1;
      return {};
    });
    await renderAs("super_admin");

    fireEvent.drop(document.body, dragData([romFile("a.nes"), romFile("b.sfc"), romFile("c.gba")]));

    await waitFor(() => expect(screen.getAllByText("Uploaded")).toHaveLength(3));
    expect(peak).toBe(1);
  });

  it("test_one_bad_file_does_not_abort_rest", async () => {
    api.createRom
      .mockResolvedValueOnce({})
      .mockRejectedValueOnce(new Error("Unsupported ROM type"))
      .mockResolvedValueOnce({});
    await renderAs("super_admin");

    fireEvent.drop(document.body, dragData([romFile("a.nes"), romFile("bad.txt"), romFile("c.gba")]));

    await waitFor(() => expect(api.createRom).toHaveBeenCalledTimes(3));
    await waitFor(() => expect(screen.getAllByText("Uploaded")).toHaveLength(2));
    const failed = await screen.findByText(/Unsupported ROM type/);
    expect(failed.closest("li")).toHaveTextContent("bad.txt");
    expect(failed).toHaveAttribute("role", "alert");
  });

  it("ignores drags that carry no files", async () => {
    await renderAs("super_admin");

    fireEvent.dragEnter(document.body, { dataTransfer: { files: [], types: ["text/plain"] } });

    expect(screen.queryByText("Drop ROM files to upload")).not.toBeInTheDocument();
  });

  it("removes its window listeners on unmount", async () => {
    api.me.mockResolvedValue({ id: 2, username: "root", email: "", role: "super_admin" });
    api.listRoms.mockResolvedValue(page([]));
    const add = vi.spyOn(window, "addEventListener");
    const remove = vi.spyOn(window, "removeEventListener");

    const { unmount } = render(<App />);
    await screen.findByText("super_admin");
    const added = add.mock.calls.filter(([type]) => /^drag|^drop/.test(type));
    expect(added.length).toBeGreaterThan(0);
    unmount();

    for (const [type, handler] of added) {
      expect(remove).toHaveBeenCalledWith(type, handler);
    }
  });
});

describe("cover polling", () => {
  const fresh = { id: 9, title: "Fresh", platform: "NES", extension: ".nes", cover_art_url: null };

  async function advance(ms) {
    await act(async () => {
      await vi.advanceTimersByTimeAsync(ms);
    });
  }

  async function renderFresh() {
    api.me.mockResolvedValue({ id: 1, username: "alice", email: "", role: "readonly" });
    api.listRoms.mockResolvedValue(page([fresh]));
    api.coverObjectUrl.mockResolvedValue("blob:cover");
    vi.stubGlobal("URL", { revokeObjectURL: vi.fn() }); // jsdom has no object URLs
    const view = render(<App />);
    await advance(0); // let auth + the first list load settle
    return view;
  }

  afterEach(() => {
    cleanup(); // unmount while URL is still stubbed
    vi.useRealTimers();
    vi.unstubAllGlobals();
  });

  it("test_card_polls_then_shows_cover", async () => {
    vi.useFakeTimers();
    api.coverExists.mockResolvedValueOnce(false).mockResolvedValueOnce(false).mockResolvedValue(true);
    await renderFresh();

    expect(screen.queryByRole("img", { name: "Fresh" })).not.toBeInTheDocument();
    expect(api.coverExists).not.toHaveBeenCalled();

    await advance(COVER_POLL_INTERVAL_MS);
    expect(api.coverExists).toHaveBeenCalledTimes(1);
    expect(screen.queryByRole("img", { name: "Fresh" })).not.toBeInTheDocument();

    await advance(COVER_POLL_INTERVAL_MS);
    expect(api.coverExists).toHaveBeenCalledTimes(2);

    await advance(COVER_POLL_INTERVAL_MS);
    expect(api.coverExists).toHaveBeenCalledTimes(3);
    expect(api.coverObjectUrl).toHaveBeenCalledWith(expect.objectContaining({ id: 9 }));
    expect(screen.getByRole("img", { name: "Fresh" })).toHaveAttribute("src", "blob:cover");

    // Art arrived: polling has stopped for good.
    await advance(COVER_POLL_INTERVAL_MS * (COVER_POLL_MAX_ATTEMPTS + 5));
    expect(api.coverExists).toHaveBeenCalledTimes(3);
    expect(vi.getTimerCount()).toBe(0);
  });

  it("test_poll_gives_up_after_limit", async () => {
    vi.useFakeTimers();
    api.coverExists.mockResolvedValue(false);
    await renderFresh();

    await advance(COVER_POLL_INTERVAL_MS * (COVER_POLL_MAX_ATTEMPTS + 20));

    expect(api.coverExists).toHaveBeenCalledTimes(COVER_POLL_MAX_ATTEMPTS);
    expect(api.coverObjectUrl).not.toHaveBeenCalled();
    expect(screen.queryByRole("img", { name: "Fresh" })).not.toBeInTheDocument();
    expect(document.querySelector(".cover-placeholder")).toBeInTheDocument();
    expect(vi.getTimerCount()).toBe(0);
  });

  it("keeps polling through transient check errors", async () => {
    vi.useFakeTimers();
    api.coverExists.mockRejectedValueOnce(new Error("boom")).mockResolvedValue(true);
    await renderFresh();

    await advance(COVER_POLL_INTERVAL_MS * 2);

    expect(screen.getByRole("img", { name: "Fresh" })).toBeInTheDocument();
  });

  it("stops polling when the card unmounts", async () => {
    vi.useFakeTimers();
    api.coverExists.mockResolvedValue(false);
    const { unmount } = await renderFresh();
    await advance(COVER_POLL_INTERVAL_MS);
    expect(api.coverExists).toHaveBeenCalledTimes(1);

    unmount();
    await advance(COVER_POLL_INTERVAL_MS * COVER_POLL_MAX_ATTEMPTS);

    expect(api.coverExists).toHaveBeenCalledTimes(1);
    expect(vi.getTimerCount()).toBe(0);
  });
});

describe("approve device page", () => {
  function openPairLink(search = "?code=ABC123") {
    window.history.pushState(null, "", `/pair${search}`);
  }

  afterEach(() => {
    window.history.pushState(null, "", "/");
  });

  it("test_approve_device_page_calls_api_and_shows_result", async () => {
    openPairLink();

    render(<App />);

    expect(await screen.findByRole("heading", { name: "Approve device" })).toBeInTheDocument();
    expect(screen.getByText("ABC123")).toBeInTheDocument();
    expect(screen.queryByText("ROM Library")).not.toBeInTheDocument();
    expect(api.approveDevice).not.toHaveBeenCalled();

    fireEvent.click(screen.getByRole("button", { name: "Approve this device" }));

    await waitFor(() => expect(api.approveDevice).toHaveBeenCalledWith("ABC123"));
    expect(await screen.findByText(/Device approved/)).toHaveAttribute("role", "status");
    expect(screen.queryByRole("button", { name: "Approve this device" })).not.toBeInTheDocument();
  });

  it("shows a readable error when approval is rejected and allows retrying", async () => {
    openPairLink();
    api.approveDevice.mockRejectedValueOnce(new Error("This pairing code has expired."));

    render(<App />);
    fireEvent.click(await screen.findByRole("button", { name: "Approve this device" }));

    expect(await screen.findByRole("alert")).toHaveTextContent("This pairing code has expired.");
    expect(screen.queryByText(/Device approved/)).not.toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: "Approve this device" }));
    expect(await screen.findByText(/Device approved/)).toBeInTheDocument();
    expect(api.approveDevice).toHaveBeenCalledTimes(2);
  });

  it("asks a signed-out visitor to log in, then shows the approve view", async () => {
    signedOutOnce();
    openPairLink();
    api.login.mockResolvedValueOnce({ user: { username: "alice" } });

    render(<App />);

    expect(await screen.findByText(/log in to approve/i)).toBeInTheDocument();
    expect(screen.getByText("ABC123")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Approve this device" })).not.toBeInTheDocument();
    expect(api.approveDevice).not.toHaveBeenCalled();

    fireEvent.change(screen.getByPlaceholderText("Username"), { target: { value: "alice" } });
    fireEvent.change(screen.getByPlaceholderText("Password"), { target: { value: "pw" } });
    fireEvent.click(screen.getByRole("button", { name: "Login" }));

    expect(await screen.findByRole("button", { name: "Approve this device" })).toBeInTheDocument();
    expect(api.approveDevice).not.toHaveBeenCalled();
  });

  it("explains a pairing link that has no code", async () => {
    openPairLink("");

    render(<App />);

    expect(await screen.findByText(/no pairing code/i)).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Approve this device" })).not.toBeInTheDocument();
  });

  it("leaves the library alone on ordinary paths", async () => {

    render(<App />);

    expect(await screen.findByText("ROM Library")).toBeInTheDocument();
    expect(screen.queryByRole("heading", { name: "Approve device" })).not.toBeInTheDocument();
  });
});

describe("App playlists", () => {
  afterEach(() => {
    window.history.replaceState(null, "", "/");
  });

  it("switches between Library and Playlists with the nav and the address bar hash", async () => {
    api.listRoms.mockResolvedValue(page([{ id: 1, title: "Zelda", platform: "NES", extension: ".nes" }]));
    api.listPlaylists.mockResolvedValue([{ id: 3, name: "Road trip", created_by: 1, rom_count: 2 }]);
    render(<App />);

    expect(await screen.findByRole("heading", { name: "ROM Library" })).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Playlists" }));

    expect(await screen.findByRole("heading", { name: "Playlists" })).toBeInTheDocument();
    expect(await screen.findByRole("button", { name: /Road trip/ })).toBeInTheDocument();
    expect(window.location.hash).toBe("#/playlists");
    expect(screen.queryByRole("heading", { name: "ROM Library" })).not.toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: "Library" }));
    expect(await screen.findByRole("heading", { name: "ROM Library" })).toBeInTheDocument();
    expect(window.location.hash).toBe("");
  });

  it("marks the tab of the view being shown as current, also after hash changes", async () => {
    render(<App />);
    const library = await screen.findByRole("button", { name: "Library" });
    const playlists = screen.getByRole("button", { name: "Playlists" });
    expect(library).toHaveAttribute("aria-current", "page");
    expect(playlists).not.toHaveAttribute("aria-current");

    fireEvent.click(playlists);
    expect(await screen.findByRole("heading", { name: "Playlists" })).toBeInTheDocument();
    expect(playlists).toHaveAttribute("aria-current", "page");
    expect(library).not.toHaveAttribute("aria-current");

    act(() => {
      window.location.hash = "";
      window.dispatchEvent(new HashChangeEvent("hashchange"));
    });
    expect(await screen.findByRole("heading", { name: "ROM Library" })).toBeInTheDocument();
    expect(library).toHaveAttribute("aria-current", "page");
    expect(playlists).not.toHaveAttribute("aria-current");
  });

  it("opens straight to playlists from #/playlists", async () => {
    window.history.replaceState(null, "", "/#/playlists");
    render(<App />);

    expect(await screen.findByRole("heading", { name: "Playlists" })).toBeInTheDocument();
  });

  it("opens the handheld install guide from the nav and from #/handheld", async () => {
    render(<App />);

    fireEvent.click(await screen.findByRole("button", { name: "Handheld" }));
    expect(await screen.findByRole("heading", { name: "Get birdROMs on your handheld" })).toBeInTheDocument();
    expect(window.location.hash).toBe("#/handheld");
    cleanup();

    window.history.replaceState(null, "", "/#/handheld");
    render(<App />);
    expect(await screen.findByRole("heading", { name: "Get birdROMs on your handheld" })).toBeInTheDocument();
  });

  it("offers Add to playlist on ROM cards", async () => {
    api.listRoms.mockResolvedValue(page([{ id: 1, title: "Zelda", platform: "NES", extension: ".nes" }]));
    render(<App />);

    expect(await screen.findByRole("button", { name: "Add Zelda to a playlist" })).toBeInTheDocument();
  });

  it("does not show the nav on the login screen", async () => {
    signedOutOnce();
    render(<App />);
    await screen.findByRole("heading", { name: "Login" });
    expect(screen.queryByRole("button", { name: "Playlists" })).not.toBeInTheDocument();
  });
});

describe("invite links", () => {
  function openInvite(path = "/invite/abc-123_XYZ") {
    window.history.pushState(null, "", path);
  }

  afterEach(() => {
    window.history.pushState(null, "", "/");
  });

  function fillAndSubmit() {
    fireEvent.change(screen.getByPlaceholderText("Username"), { target: { value: "dave" } });
    fireEvent.change(screen.getByPlaceholderText("Email (optional)"), { target: { value: "dave@example.com" } });
    fireEvent.change(screen.getByPlaceholderText("Password"), { target: { value: "s3cure-pass-xyz" } });
    fireEvent.click(screen.getByRole("button", { name: "Create account" }));
  }

  it("checks the token from the path, then shows the sign-up form instead of the login card", async () => {
    signedOutOnce();
    openInvite();

    render(<App />);

    expect(await screen.findByRole("heading", { name: "Join birdROMs" })).toBeInTheDocument();
    await screen.findByPlaceholderText("Username");
    expect(api.checkInvite).toHaveBeenCalledWith("abc-123_XYZ");
    expect(screen.queryByRole("heading", { name: "Login" })).not.toBeInTheDocument();
  });

  it("shows no accept form, and never checks the token, when invites are off on this server", async () => {
    signedOutOnce();
    openInvite();
    api.authConfig.mockResolvedValueOnce({ methods: ["oidc"], registration: false, invites: false });

    render(<App />);

    expect(await screen.findByText("Invite links are not available on this server.")).toBeInTheDocument();
    expect(screen.queryByPlaceholderText("Username")).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Create account" })).not.toBeInTheDocument();
    expect(api.checkInvite).not.toHaveBeenCalled();
    fireEvent.click(screen.getByRole("button", { name: "Go to login" }));
    expect(await screen.findByRole("heading", { name: "Login" })).toBeInTheDocument();
  });

  it("accepts the invite, signs in with the session and lands in the library", async () => {
    signedOutOnce();
    openInvite();
    api.acceptInvite.mockResolvedValueOnce({ user: { username: "dave" } });

    render(<App />);
    await screen.findByPlaceholderText("Username");
    fillAndSubmit();

    await waitFor(() =>
      expect(api.acceptInvite).toHaveBeenCalledWith({
        token: "abc-123_XYZ",
        username: "dave",
        email: "dave@example.com",
        password: "s3cure-pass-xyz"
      })
    );
    expect(await screen.findByText("ROM Library")).toBeInTheDocument();
    expect(window.location.pathname).toBe("/");
    expect(window.location.search).toBe("");
    expect(localStorage.length).toBe(0);
  });

  it("shows one unavailable message when the link is invalid, expired, used or revoked", async () => {
    signedOutOnce();
    openInvite();
    api.checkInvite.mockRejectedValueOnce(Object.assign(new Error("gone"), { status: 404 }));

    render(<App />);

    expect(await screen.findByRole("alert")).toHaveTextContent("This invite link is invalid, expired or already used.");
    expect(screen.queryByPlaceholderText("Username")).not.toBeInTheDocument();
    expect(screen.queryByRole("heading", { name: "Login" })).not.toBeInTheDocument();
  });

  it("shows the same message if the link dies between the check and the sign-up", async () => {
    signedOutOnce();
    openInvite();
    api.acceptInvite.mockRejectedValueOnce(Object.assign(new Error("gone"), { status: 404 }));

    render(<App />);
    await screen.findByPlaceholderText("Username");
    fillAndSubmit();

    expect(await screen.findByRole("alert")).toHaveTextContent("This invite link is invalid, expired or already used.");
    expect(screen.queryByPlaceholderText("Username")).not.toBeInTheDocument();
  });

  it("shows a refused username or password and keeps the form", async () => {
    signedOutOnce();
    openInvite();
    api.acceptInvite.mockRejectedValueOnce(Object.assign(new Error("That username is already taken."), { status: 400 }));

    render(<App />);
    await screen.findByPlaceholderText("Username");
    fillAndSubmit();

    expect(await screen.findByRole("alert")).toHaveTextContent("That username is already taken.");
    expect(screen.getByPlaceholderText("Username")).toBeInTheDocument();
  });

  it("goes to the login card from the unavailable message", async () => {
    signedOutOnce();
    openInvite();
    api.checkInvite.mockRejectedValueOnce(Object.assign(new Error("gone"), { status: 404 }));

    render(<App />);
    fireEvent.click(await screen.findByRole("button", { name: "Go to login" }));

    expect(await screen.findByRole("heading", { name: "Login" })).toBeInTheDocument();
    expect(window.location.pathname).toBe("/");
  });

  it("does not treat other paths as invites", async () => {
    signedOutOnce();
    openInvite("/invites-are-great");

    render(<App />);

    expect(await screen.findByRole("heading", { name: "Login" })).toBeInTheDocument();
    expect(api.checkInvite).not.toHaveBeenCalled();
  });
});

describe("creating invites", () => {
  it("offers an admin a short form and shows the link once", async () => {
    api.me.mockResolvedValueOnce({ id: 2, username: "root", email: "", role: "super_admin" });
    api.createInvite.mockResolvedValueOnce({ id: 5, url: "https://roms.example.com/invite/tok123", token: "tok123" });
    render(<App />);

    fireEvent.click(await screen.findByText("Invite a friend"));
    fireEvent.change(screen.getByLabelText("Invite role"), { target: { value: "super_admin" } });
    fireEvent.change(screen.getByLabelText("Invite label"), { target: { value: " Sam " } });
    fireEvent.click(screen.getByRole("button", { name: "Create invite link" }));

    await waitFor(() => expect(api.createInvite).toHaveBeenCalledWith({ role: "super_admin", label: "Sam" }));
    expect(await screen.findByLabelText("Invite link")).toHaveValue("https://roms.example.com/invite/tok123");
    expect(screen.getByText(/will not be shown again/)).toBeInTheDocument();
  });

  it("offers all three roles, and can invite a member", async () => {
    api.me.mockResolvedValueOnce({ id: 2, username: "root", email: "", role: "super_admin" });
    api.createInvite.mockResolvedValueOnce({ id: 6, url: "https://roms.example.com/invite/tok9", token: "tok9" });
    render(<App />);

    fireEvent.click(await screen.findByText("Invite a friend"));
    const select = screen.getByLabelText("Invite role");
    expect([...select.options].map((option) => option.value)).toEqual(["readonly", "member", "super_admin"]);
    expect(screen.getByRole("option", { name: /browse, download and upload/i })).toBeInTheDocument();
    fireEvent.change(select, { target: { value: "member" } });
    fireEvent.click(screen.getByRole("button", { name: "Create invite link" }));

    await waitFor(() => expect(api.createInvite).toHaveBeenCalledWith({ role: "member", label: "" }));
  });

  it("does not show the invite form to readonly users", async () => {
    render(<App />);

    expect(await screen.findByText("ROM Library")).toBeInTheDocument();
    expect(screen.queryByText("Invite a friend")).not.toBeInTheDocument();
  });

  it("does not offer invites to an admin when the server reports invites off", async () => {
    api.me.mockResolvedValueOnce({ id: 2, username: "root", email: "", role: "super_admin" });
    api.authConfig.mockResolvedValueOnce({ methods: ["oidc"], registration: false, invites: false });
    render(<App />);

    expect(await screen.findByRole("heading", { name: "Upload ROM" })).toBeInTheDocument();
    await waitFor(() => expect(api.authConfig).toHaveBeenCalled());
    await act(async () => {}); // let the config answer land before asserting the form stayed hidden
    expect(screen.queryByText("Invite a friend")).not.toBeInTheDocument();
  });

  it("does not offer invites while the config is still loading, or if it cannot be read", async () => {
    api.me.mockResolvedValueOnce({ id: 2, username: "root", email: "", role: "super_admin" });
    api.authConfig.mockReturnValueOnce(new Promise(() => {}));
    render(<App />);

    expect(await screen.findByRole("heading", { name: "Upload ROM" })).toBeInTheDocument();
    expect(screen.queryByText("Invite a friend")).not.toBeInTheDocument();
  });

  it("offers invites to an admin when local login is on, even with self-registration closed", async () => {
    api.me.mockResolvedValueOnce({ id: 2, username: "root", email: "", role: "super_admin" });
    api.authConfig.mockResolvedValueOnce({ methods: ["local"], registration: false, invites: true });
    render(<App />);

    expect(await screen.findByText("Invite a friend")).toBeInTheDocument();
  });
});
