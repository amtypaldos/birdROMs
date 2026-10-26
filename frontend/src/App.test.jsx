import { describe, expect, it, vi } from "vitest";
import { fireEvent, render, screen } from "@testing-library/react";

vi.mock("./api/client", () => ({
  getToken: vi.fn(() => null),
  setToken: vi.fn(),
  api: {
    login: vi.fn(),
    listRoms: vi.fn(() => Promise.resolve([])),
    createRom: vi.fn(),
    scrapeCover: vi.fn(),
    downloadRom: vi.fn(() => Promise.resolve())
  }
}));

import App from "./App";
import { api, getToken } from "./api/client";

describe("App", () => {
  it("renders the login form when there is no token", () => {
    render(<App />);

    expect(screen.getByRole("heading", { name: "Login" })).toBeInTheDocument();
    expect(screen.getByPlaceholderText("Username")).toBeInTheDocument();
    expect(screen.getByPlaceholderText("Password")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Login" })).toBeInTheDocument();
    expect(screen.queryByText("ROM Library")).not.toBeInTheDocument();
    expect(api.listRoms).not.toHaveBeenCalled();
  });

  it("downloads through the authenticated API instead of linking to media", async () => {
    const rom = { id: 3, title: "Zelda", platform: "NES", extension: ".nes", download_url: "/api/roms/3/download/" };
    getToken.mockReturnValueOnce("abc123");
    api.listRoms.mockResolvedValueOnce([rom]);

    const { container } = render(<App />);
    fireEvent.click(await screen.findByRole("button", { name: "Download" }));

    expect(api.downloadRom).toHaveBeenCalledWith(rom);
    expect(container.querySelector("a[href]")).toBeNull();
  });
});
