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
    expect(screen.getByRole("list", { name: "Installation steps" }).children).toHaveLength(3);
    expect(screen.getAllByText(/ARCHIVE/).length).toBeGreaterThan(0);
    expect(screen.getAllByText(/Archive Manager/).length).toBeGreaterThan(0);
    expect(screen.getByText(/2\.8 MB/)).toBeInTheDocument();
  });

  it("downloads the package through the signed-in session", async () => {
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

    expect(screen.getByText(/type the code shown on your device/i)).toBeInTheDocument();
  });

  it("says the handheld updates itself instead of asking for a re-copy", async () => {
    await renderView();

    expect(screen.getByText(/handheld updates itself from this server/i)).toBeInTheDocument();
    expect(screen.queryByText(/copy it into/i)).not.toBeInTheDocument();
  });


  it("switches to the Switch package and its distinct installation instructions", async () => {
    api.handheldInfo.mockImplementation((platform) => Promise.resolve(platform === "switch"
      ? { ...INFO, filename: "birdroms-switch.zip", version: "2026.11.01" } : INFO));
    await renderView();
    fireEvent.click(screen.getByRole("button", { name: /Nintendo Switch/ }));
    await act(async () => {});
    expect(api.handheldInfo).toHaveBeenLastCalledWith("switch");
    expect(screen.getByText("2026.11.01")).toBeInTheDocument();
    expect(screen.getByText("/switch/birdroms/birdroms.nro")).toBeInTheDocument();
    expect(screen.getAllByText(/server.json/).length).toBeGreaterThan(0);
    expect(screen.getByRole("list", { name: "Installation steps" }).children).toHaveLength(3);
    expect(screen.queryByText(/Archive Manager/)).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Download birdroms-switch.zip" }));
    await act(async () => {});
    expect(api.downloadHandheldApp).toHaveBeenCalledWith("switch");
    expect(screen.getAllByRole("form", { name: "Approve a device by code" })).toHaveLength(1);
  });

  it("keeps release loading, unavailability and errors specific to the chosen platform", async () => {
    api.handheldInfo.mockImplementation((platform) => platform === "switch"
      ? Promise.reject(new Error("Switch package check failed")) : Promise.resolve(INFO));
    await renderView();
    fireEvent.click(screen.getByRole("button", { name: /Nintendo Switch/ }));
    await act(async () => {});
    expect(screen.getByRole("alert")).toHaveTextContent("Switch package check failed");
    expect(screen.queryByRole("button", { name: "Download birdROMs.muxapp" })).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: /muOS/ }));
    await act(async () => {});
    expect(screen.queryByRole("alert")).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Download birdROMs.muxapp" })).toBeInTheDocument();
  });

  it("does not let an old platform response replace the current release", async () => {
    let resolveMuos;
    api.handheldInfo.mockImplementation((platform) => platform === "switch"
      ? Promise.resolve({ available: false }) : new Promise((resolve) => { resolveMuos = resolve; }));
    await renderView();
    expect(screen.getByText(/Checking this server/)).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: /Nintendo Switch/ }));
    await act(async () => {});
    await act(async () => { resolveMuos(INFO); });
    expect(screen.getByText(/Switch app has not been published yet/)).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /Download birdROMs/ })).not.toBeInTheDocument();
  });

  it("explains server personalization without putting a device token in a link", async () => {
    await renderView();
    fireEvent.click(screen.getByRole("button", { name: /Nintendo Switch/ }));
    await act(async () => {});
    expect(screen.getByText(/contains this server.*address, not a device token/)).toBeInTheDocument();
    expect(screen.getByText(/created after you approve pairing/)).toBeInTheDocument();
    for (const link of screen.queryAllByRole("link")) expect(link.href).not.toMatch(/device_token|Authorization/);
  });


  it("retries a failed package check without leaving the selected platform", async () => {
    api.handheldInfo.mockResolvedValueOnce(INFO).mockRejectedValueOnce(new Error("Server unavailable"))
      .mockResolvedValueOnce({ ...INFO, filename: "birdroms-switch.zip" });
    await renderView();
    fireEvent.click(screen.getByRole("button", { name: /Nintendo Switch/ }));
    await act(async () => {});
    fireEvent.click(screen.getByRole("button", { name: "Check again" }));
    await act(async () => {});
    expect(api.handheldInfo).toHaveBeenLastCalledWith("switch");
    expect(screen.getByRole("button", { name: "Download birdroms-switch.zip" })).toBeInTheDocument();
    expect(screen.queryByRole("alert")).not.toBeInTheDocument();
  });

  it("locks platform selection until the current package download finishes", async () => {
    let resolveDownload;
    api.downloadHandheldApp.mockReturnValue(new Promise((resolve) => { resolveDownload = resolve; }));
    await renderView();
    fireEvent.click(screen.getByRole("button", { name: "Download birdROMs.muxapp" }));
    expect(screen.getByRole("button", { name: /Nintendo Switch/ })).toBeDisabled();
    expect(screen.getByRole("button", { name: /muOS/ })).toBeDisabled();
    expect(screen.getByRole("button", { name: "Downloading…" })).toBeDisabled();
    await act(async () => { resolveDownload(); });
    expect(screen.getByRole("button", { name: /Nintendo Switch/ })).toBeEnabled();
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
