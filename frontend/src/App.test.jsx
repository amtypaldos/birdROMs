import { describe, expect, it, vi } from "vitest";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";

function page(results, { count = results.length, next = null, previous = null } = {}) {
  return { count, next, previous, results };
}

vi.mock("./api/client", () => ({
  getToken: vi.fn(() => null),
  setToken: vi.fn(),
  consumeOidcFragment: vi.fn(() => null),
  api: {
    oidcLoginUrl: "/api/auth/oidc/login/",
    authConfig: vi.fn(() => Promise.resolve({ methods: ["local"] })),
    me: vi.fn(() => Promise.resolve({ id: 1, username: "alice", email: "", role: "readonly" })),
    login: vi.fn(),
    register: vi.fn(),
    listRoms: vi.fn(() => Promise.resolve(page([]))),
    listPlatforms: vi.fn(() => Promise.resolve([])),
    createRom: vi.fn(),
    scrapeCover: vi.fn(),
    downloadRom: vi.fn(() => Promise.resolve()),
    coverObjectUrl: vi.fn(() => Promise.resolve("blob:cover"))
  }
}));

import App from "./App";
import { api, consumeOidcFragment, getToken, setToken } from "./api/client";

describe("App", () => {
  it("renders the login form when there is no token", async () => {
    render(<App />);

    expect(await screen.findByRole("heading", { name: "Login" })).toBeInTheDocument();
    expect(screen.getByPlaceholderText("Username")).toBeInTheDocument();
    expect(screen.getByPlaceholderText("Password")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Login" })).toBeInTheDocument();
    expect(screen.queryByText("ROM Library")).not.toBeInTheDocument();
    expect(api.listRoms).not.toHaveBeenCalled();
  });

  it("downloads through the authenticated API instead of linking to media", async () => {
    const rom = { id: 3, title: "Zelda", platform: "NES", extension: ".nes", download_url: "/api/roms/3/download/" };
    getToken.mockReturnValueOnce("abc123");
    api.listRoms.mockResolvedValueOnce(page([rom]));

    const { container } = render(<App />);
    fireEvent.click(await screen.findByRole("button", { name: "Download" }));

    expect(api.downloadRom).toHaveBeenCalledWith(rom);
    expect(container.querySelector("a[href]")).toBeNull();
  });

  it("loads stored cover art with the token and skips ROMs without art", async () => {
    const withArt = { id: 3, title: "Zelda", platform: "NES", extension: ".nes", cover_art_url: "/api/roms/3/cover/" };
    const without = { id: 4, title: "Metroid", platform: "NES", extension: ".nes", cover_art_url: null };
    getToken.mockReturnValueOnce("abc123");
    api.listRoms.mockResolvedValueOnce(page([withArt, without]));
    const revokeObjectURL = vi.fn(); // jsdom has no object URLs
    vi.stubGlobal("URL", { revokeObjectURL });

    const { unmount } = render(<App />);

    expect(await screen.findByRole("img", { name: "Zelda" })).toHaveAttribute("src", "blob:cover");
    expect(screen.queryByRole("img", { name: "Metroid" })).not.toBeInTheDocument();
    expect(api.coverObjectUrl).toHaveBeenCalledTimes(1);
    expect(api.coverObjectUrl).toHaveBeenCalledWith(withArt);
    unmount();
    expect(revokeObjectURL).toHaveBeenCalledWith("blob:cover");
    vi.unstubAllGlobals();
  });

  it("shows only the SSO button when only OIDC is enabled", async () => {
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
    api.authConfig.mockResolvedValueOnce({ methods: ["local", "oidc"], oidc: { provider_name: "SSO" } });

    render(<App />);

    expect(await screen.findByRole("link", { name: "Login with SSO" })).toBeInTheDocument();
    expect(screen.getByPlaceholderText("Username")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Login" })).toBeInTheDocument();
  });

  it("hides the SSO button when only local login is enabled", async () => {
    render(<App />);

    expect(await screen.findByPlaceholderText("Username")).toBeInTheDocument();
    expect(screen.queryByRole("link", { name: /Login with/ })).not.toBeInTheDocument();
  });

  it("registers a local account and signs in", async () => {
    api.register.mockResolvedValueOnce({ token: "newtok", user: { username: "bob" } });
    getToken.mockReturnValueOnce(null).mockReturnValue(null);

    render(<App />);
    fireEvent.click(await screen.findByRole("button", { name: "Create account" }));
    fireEvent.change(screen.getByPlaceholderText("Username"), { target: { value: "bob" } });
    fireEvent.change(screen.getByPlaceholderText("Email"), { target: { value: "bob@example.com" } });
    fireEvent.change(screen.getByPlaceholderText("Password"), { target: { value: "s3cure-pass" } });
    fireEvent.click(screen.getByRole("button", { name: "Register" }));

    await waitFor(() =>
      expect(api.register).toHaveBeenCalledWith({ username: "bob", email: "bob@example.com", password: "s3cure-pass" })
    );
    expect(setToken).toHaveBeenCalledWith("newtok");
    expect(await screen.findByText("ROM Library")).toBeInTheDocument();
  });

  it("stores the token from an SSO callback and shows the signed-in user", async () => {
    consumeOidcFragment.mockReturnValueOnce({ token: "ssotok", error: null });
    getToken.mockReturnValue("ssotok");
    api.me.mockResolvedValueOnce({ id: 7, username: "grace", email: "g@example.com", role: "super_admin" });

    render(<App />);

    expect(setToken).toHaveBeenCalledWith("ssotok");
    expect(await screen.findByText("grace")).toBeInTheDocument();
    expect(screen.getByText(/super_admin/)).toBeInTheDocument();
    expect(api.authConfig).not.toHaveBeenCalled();
  });

  it("shows an SSO error returned by the callback", async () => {
    consumeOidcFragment.mockReturnValueOnce({ token: null, error: "Single sign-on failed. Please try again." });

    render(<App />);

    expect(await screen.findByText("Single sign-on failed. Please try again.")).toBeInTheDocument();
    expect(await screen.findByRole("heading", { name: "Login" })).toBeInTheDocument();
  });

  it("drives the library with search, platform filter and pagination", async () => {
    getToken.mockReturnValue("tok");
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

    const calls = api.listRoms.mock.calls.length;
    fireEvent.click(screen.getByRole("button", { name: "Refresh" }));
    await waitFor(() => expect(api.listRoms.mock.calls.length).toBe(calls + 1));
    expect(api.listRoms).toHaveBeenLastCalledWith({ search: "zel", platform: "NES", page: 1 });
  });

  it("hides upload and scrape controls from readonly users", async () => {
    getToken.mockReturnValue("tok");
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
    getToken.mockReturnValue("tok");
    api.me.mockResolvedValueOnce({ id: 2, username: "root", email: "", role: "super_admin" });
    api.listRoms.mockResolvedValue(page([{ id: 1, title: "Zelda", platform: "NES", extension: ".nes" }]));

    render(<App />);

    expect(await screen.findByRole("heading", { name: "Upload ROM" })).toBeInTheDocument();
    expect(screen.getByText("root")).toBeInTheDocument();
    expect(screen.getByText("super_admin")).toBeInTheDocument();
    expect(await screen.findByRole("button", { name: "Scrape Cover" })).toBeInTheDocument();
  });

  it("renders no write controls before the user's role is known", async () => {
    getToken.mockReturnValue("tok");
    api.me.mockReturnValueOnce(new Promise(() => {}));
    api.listRoms.mockResolvedValue(page([{ id: 1, title: "Zelda", platform: "NES", extension: ".nes" }]));

    render(<App />);

    expect(await screen.findByText("Zelda")).toBeInTheDocument();
    expect(screen.queryByRole("heading", { name: "Upload ROM" })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Scrape Cover" })).not.toBeInTheDocument();
  });

  it("shows the role after a local login and logs out back to the login form", async () => {
    api.login.mockResolvedValueOnce({ token: "loctok" });
    api.me.mockResolvedValueOnce({ id: 2, username: "root", email: "", role: "super_admin" });

    render(<App />);
    fireEvent.change(await screen.findByPlaceholderText("Username"), { target: { value: "root" } });
    fireEvent.change(screen.getByPlaceholderText("Password"), { target: { value: "pw" } });
    fireEvent.click(screen.getByRole("button", { name: "Login" }));

    expect(await screen.findByRole("heading", { name: "Upload ROM" })).toBeInTheDocument();
    expect(screen.getByText("super_admin")).toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: "Logout" }));

    expect(setToken).toHaveBeenLastCalledWith(null);
    expect(await screen.findByRole("heading", { name: "Login" })).toBeInTheDocument();
    expect(screen.queryByRole("heading", { name: "Upload ROM" })).not.toBeInTheDocument();
    expect(screen.queryByText("root")).not.toBeInTheDocument();
  });

  it("says when no ROMs match the filters", async () => {
    getToken.mockReturnValue("tok");

    render(<App />);

    expect(await screen.findByText("No ROMs found.")).toBeInTheDocument();
  });
});
