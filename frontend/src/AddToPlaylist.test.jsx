import { beforeEach, describe, expect, it, vi } from "vitest";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";

vi.mock("./api/client", () => ({
  api: {
    listPlaylists: vi.fn(),
    getPlaylist: vi.fn(),
    updatePlaylist: vi.fn()
  }
}));

import AddToPlaylist from "./AddToPlaylist";
import { api } from "./api/client";

const ROM = { id: 9, title: "Zelda" };
const ME = { id: 1, username: "alice" };

beforeEach(() => {
  vi.clearAllMocks();
  api.listPlaylists.mockResolvedValue([
    { id: 1, name: "Mine", created_by: 1, rom_count: 2 },
    { id: 2, name: "Not mine", created_by: 5, rom_count: 0 }
  ]);
});

async function openMenu() {
  fireEvent.click(screen.getByRole("button", { name: "Add Zelda to a playlist" }));
  await screen.findByRole("button", { name: "Mine" });
}

describe("AddToPlaylist", () => {
  it("offers only your own playlists", async () => {
    render(<AddToPlaylist rom={ROM} me={ME} />);
    await openMenu();
    expect(screen.queryByRole("button", { name: "Not mine" })).not.toBeInTheDocument();
  });

  it("appends the ROM to the end of the playlist's current order", async () => {
    api.getPlaylist.mockResolvedValue({ id: 1, name: "Mine", roms: [{ id: 4 }, { id: 3 }] });
    api.updatePlaylist.mockResolvedValue({});
    render(<AddToPlaylist rom={ROM} me={ME} />);
    await openMenu();

    fireEvent.click(screen.getByRole("button", { name: "Mine" }));

    await waitFor(() => expect(api.updatePlaylist).toHaveBeenCalledWith(1, { rom_ids: [4, 3, 9] }));
    expect(await screen.findByRole("status")).toHaveTextContent("Added to Mine");
    expect(screen.queryByRole("button", { name: "Mine" })).not.toBeInTheDocument(); // menu closed
  });

  it("does not add a ROM that is already there", async () => {
    api.getPlaylist.mockResolvedValue({ id: 1, name: "Mine", roms: [{ id: 9 }] });
    render(<AddToPlaylist rom={ROM} me={ME} />);
    await openMenu();

    fireEvent.click(screen.getByRole("button", { name: "Mine" }));

    expect(await screen.findByRole("status")).toHaveTextContent("Already in Mine");
    expect(api.updatePlaylist).not.toHaveBeenCalled();
  });

  it("surfaces an error", async () => {
    api.getPlaylist.mockResolvedValue({ id: 1, name: "Mine", roms: [] });
    api.updatePlaylist.mockRejectedValue(new Error("nope"));
    render(<AddToPlaylist rom={ROM} me={ME} />);
    await openMenu();

    fireEvent.click(screen.getByRole("button", { name: "Mine" }));

    expect(await screen.findByRole("alert")).toHaveTextContent("nope");
  });

  it("says so when you have no playlists", async () => {
    api.listPlaylists.mockResolvedValue([]);
    render(<AddToPlaylist rom={ROM} me={ME} />);
    fireEvent.click(screen.getByRole("button", { name: "Add Zelda to a playlist" }));
    expect(await screen.findByText(/no playlists/i)).toBeInTheDocument();
  });
});
