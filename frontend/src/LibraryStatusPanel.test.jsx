import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { act, cleanup, fireEvent, render, screen } from "@testing-library/react";

vi.mock("./api/client", () => ({
  api: { libraryStatus: vi.fn(), rescanLibrary: vi.fn() }
}));

import LibraryStatusPanel, { POLL_INTERVAL_MS } from "./LibraryStatusPanel";
import { api } from "./api/client";

const SCAN = {
  state: "finished",
  started_at: "2026-10-28T10:00:00Z",
  finished_at: "2026-10-28T10:01:00Z",
  added: 12,
  changed: 3,
  missing: 2,
  restored: 0,
  skipped_multifile: 0,
  skipped_other: 0,
  unknown_folders: [],
  message: ""
};

function status(overrides = {}) {
  return { backend: "local", writable: true, write_covers: true, running: false, last_scan: SCAN, ...overrides };
}

async function renderPanel(me = { role: "super_admin" }) {
  render(<LibraryStatusPanel me={me} />);
  await act(async () => {});
}

describe("LibraryStatusPanel", () => {
  beforeEach(() => {
    vi.resetAllMocks();
    api.libraryStatus.mockResolvedValue(status());
    api.rescanLibrary.mockResolvedValue({ queued: true });
  });

  afterEach(() => {
    cleanup();
    vi.useRealTimers();
  });

  it("shows the last scan's time and counts", async () => {
    await renderPanel();

    expect(screen.getByText(new Date(SCAN.finished_at).toLocaleString())).toBeInTheDocument();
    expect(screen.getByText("12 added")).toBeInTheDocument();
    expect(screen.getByText("3 changed")).toBeInTheDocument();
    expect(screen.getByText("2 missing")).toBeInTheDocument();
  });

  it("does not render or fetch for non-admins", async () => {
    await renderPanel({ role: "readonly" });

    expect(screen.queryByRole("region", { name: "Library scan" })).not.toBeInTheDocument();
    expect(api.libraryStatus).not.toHaveBeenCalled();
  });

  it("rescans without accepting removals and shows Scanning…", async () => {
    await renderPanel();

    fireEvent.click(screen.getByRole("button", { name: "Rescan now" }));
    await act(async () => {});

    expect(api.rescanLibrary).toHaveBeenCalledWith({ acceptRemovals: false });
    expect(screen.getByRole("button", { name: "Scanning…" })).toBeDisabled();
  });

  it("polls every 5 seconds while running and stops when done", async () => {
    vi.useFakeTimers();
    api.libraryStatus.mockResolvedValueOnce(status({ running: true }));
    await renderPanel();
    expect(api.libraryStatus).toHaveBeenCalledTimes(1);
    expect(screen.getByRole("button", { name: "Scanning…" })).toBeInTheDocument();

    api.libraryStatus.mockResolvedValue(status({ running: true }));
    await act(async () => { await vi.advanceTimersByTimeAsync(POLL_INTERVAL_MS); });
    expect(api.libraryStatus).toHaveBeenCalledTimes(2);

    api.libraryStatus.mockResolvedValue(status({ running: false }));
    await act(async () => { await vi.advanceTimersByTimeAsync(POLL_INTERVAL_MS); });
    expect(api.libraryStatus).toHaveBeenCalledTimes(3);
    expect(screen.getByRole("button", { name: "Rescan now" })).toBeEnabled();

    await act(async () => { await vi.advanceTimersByTimeAsync(POLL_INTERVAL_MS * 3); });
    expect(api.libraryStatus).toHaveBeenCalledTimes(3);
  });

  it("offers to accept removals after an aborted scan", async () => {
    api.libraryStatus.mockResolvedValue(
      status({ last_scan: { ...SCAN, state: "aborted", message: "Would mark 400 ROMs missing." } })
    );
    await renderPanel();

    expect(screen.getByText("Would mark 400 ROMs missing.")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Accept removals" }));
    await act(async () => {});

    expect(api.rescanLibrary).toHaveBeenCalledWith({ acceptRemovals: true });
  });

  it("shows the conflict message when a scan is already running", async () => {
    api.rescanLibrary.mockRejectedValue(new Error("A library scan is already running."));
    await renderPanel();

    fireEvent.click(screen.getByRole("button", { name: "Rescan now" }));
    await act(async () => {});

    expect(screen.getByRole("alert")).toHaveTextContent("A library scan is already running.");
  });

  it("says when the library is read-only", async () => {
    api.libraryStatus.mockResolvedValue(status({ writable: false }));
    await renderPanel();

    expect(screen.getByText("Read-only library: uploads and cover saving are off.")).toBeInTheDocument();
  });

  it("lists unknown folders", async () => {
    api.libraryStatus.mockResolvedValue(status({ last_scan: { ...SCAN, unknown_folders: ["FOO", "BAR"] } }));
    await renderPanel();

    expect(screen.getByText(/Unknown folders/)).toHaveTextContent("FOO, BAR");
  });

  it("handles a library that has never been scanned", async () => {
    api.libraryStatus.mockResolvedValue(status({ last_scan: null }));
    await renderPanel();

    expect(screen.getByText("Never scanned.")).toBeInTheDocument();
  });
});
