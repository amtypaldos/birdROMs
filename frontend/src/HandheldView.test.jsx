import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { act, cleanup, fireEvent, render, screen } from "@testing-library/react";

vi.mock("./api/client", () => ({
  api: { handheldInfo: vi.fn(), downloadHandheldApp: vi.fn(), approveDevice: vi.fn() }
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
    api.approveDevice.mockResolvedValue({ detail: "Device approved." });
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

  it("mentions typing the code on this page in the link step", async () => {
    await renderView();

    expect(screen.getByText(/type the code shown on the handheld/i)).toBeInTheDocument();
  });

  it("says the handheld updates itself instead of asking for a re-copy", async () => {
    await renderView();

    expect(screen.getByText(/handheld updates itself from this site/i)).toBeInTheDocument();
    expect(screen.queryByText(/copy it into/i)).not.toBeInTheDocument();
  });

  it("approves a typed code, trimmed, and shows success", async () => {
    await renderView();

    fireEvent.change(screen.getByLabelText("Pairing code"), { target: { value: "  ABC123 " } });
    fireEvent.click(screen.getByRole("button", { name: "Approve device" }));
    await act(async () => {});

    expect(api.approveDevice).toHaveBeenCalledTimes(1);
    expect(api.approveDevice).toHaveBeenCalledWith("ABC123");
    expect(screen.getByRole("status")).toHaveTextContent(/Device approved/);
    expect(screen.getByLabelText("Pairing code")).toHaveValue("");
  });

  it("shows the error when approving fails", async () => {
    api.approveDevice.mockRejectedValue(new Error("This pairing code has expired."));
    await renderView();

    fireEvent.change(screen.getByLabelText("Pairing code"), { target: { value: "ABC123" } });
    fireEvent.click(screen.getByRole("button", { name: "Approve device" }));
    await act(async () => {});

    expect(screen.getByRole("alert")).toHaveTextContent("This pairing code has expired.");
    expect(screen.queryByRole("status")).not.toBeInTheDocument();
  });

  it("does not call the API for an empty or blank code", async () => {
    await renderView();

    fireEvent.click(screen.getByRole("button", { name: "Approve device" }));
    fireEvent.change(screen.getByLabelText("Pairing code"), { target: { value: "   " } });
    fireEvent.click(screen.getByRole("button", { name: "Approve device" }));
    await act(async () => {});

    expect(api.approveDevice).not.toHaveBeenCalled();
  });

  it("disables the button while the approval is in flight", async () => {
    let resolve;
    api.approveDevice.mockReturnValue(new Promise((r) => { resolve = r; }));
    await renderView();

    fireEvent.change(screen.getByLabelText("Pairing code"), { target: { value: "ABC123" } });
    fireEvent.click(screen.getByRole("button", { name: "Approve device" }));
    await act(async () => {});

    expect(screen.getByRole("button", { name: "Approve device" })).toBeDisabled();

    await act(async () => { resolve({ detail: "Device approved." }); });

    expect(screen.getByRole("button", { name: "Approve device" })).toBeEnabled();
  });
});
