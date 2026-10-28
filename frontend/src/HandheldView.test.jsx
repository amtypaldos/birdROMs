import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { act, cleanup, fireEvent, render, screen } from "@testing-library/react";

vi.mock("./api/client", () => ({
  api: { handheldInfo: vi.fn(), downloadHandheldApp: vi.fn() }
}));

import HandheldView from "./HandheldView";
import { api } from "./api/client";

const INFO = {
  available: true,
  filename: "birdROMs.muxapp",
  size: 2961114,
  sha256: "a".repeat(64),
  published_at: "2026-10-28T10:00:00+00:00"
};

async function renderView() {
  render(<HandheldView />);
  await act(async () => {});
}

describe("HandheldView", () => {
  beforeEach(() => {
    vi.resetAllMocks();
    api.handheldInfo.mockResolvedValue(INFO);
    api.downloadHandheldApp.mockResolvedValue();
  });
  afterEach(cleanup);

  it("shows the numbered install steps and the package details", async () => {
    await renderView();

    expect(screen.getByRole("heading", { name: "Get birdROMs on your handheld" })).toBeInTheDocument();
    expect(screen.getAllByRole("listitem").length).toBeGreaterThanOrEqual(5);
    expect(screen.getAllByText(/ARCHIVE/).length).toBeGreaterThan(0);
    expect(screen.getAllByText(/Archive Manager/).length).toBeGreaterThan(0);
    expect(screen.getByText(/2\.8 MB/)).toBeInTheDocument();
  });

  it("downloads the package with the sign-in token", async () => {
    await renderView();

    fireEvent.click(screen.getByRole("button", { name: "Download birdROMs.muxapp" }));
    await act(async () => {});

    expect(api.downloadHandheldApp).toHaveBeenCalledTimes(1);
  });

  it("says so when the owner has not published the app yet", async () => {
    api.handheldInfo.mockResolvedValue({ available: false });
    await renderView();

    expect(screen.getByText(/has not been published yet/i)).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /Download/ })).not.toBeInTheDocument();
  });

  it("shows a download failure", async () => {
    api.downloadHandheldApp.mockRejectedValue(new Error("boom"));
    await renderView();

    fireEvent.click(screen.getByRole("button", { name: "Download birdROMs.muxapp" }));
    await act(async () => {});

    expect(screen.getByRole("alert")).toHaveTextContent("boom");
  });
});
