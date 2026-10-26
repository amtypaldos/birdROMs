import { describe, expect, it, vi } from "vitest";
import { render, screen } from "@testing-library/react";

vi.mock("./api/client", () => ({
  getToken: vi.fn(() => null),
  setToken: vi.fn(),
  api: {
    login: vi.fn(),
    listRoms: vi.fn(() => Promise.resolve([])),
    createRom: vi.fn(),
    scrapeCover: vi.fn()
  }
}));

import App from "./App";
import { api } from "./api/client";

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
});
