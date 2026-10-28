import { beforeEach, describe, expect, it, vi } from "vitest";
import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";

vi.mock("./api/client", () => ({
  api: {
    listPlaylists: vi.fn(),
    getPlaylist: vi.fn(),
    createPlaylist: vi.fn(),
    updatePlaylist: vi.fn(),
    deletePlaylist: vi.fn(),
    listRoms: vi.fn(),
    coverObjectUrl: vi.fn(() => Promise.resolve("blob:cover"))
  }
}));

import PlaylistsView from "./PlaylistsView";
import { api } from "./api/client";

const ME = { id: 1, username: "alice", role: "readonly" };

function rom(id, title, extra = {}) {
  return { id, title, platform: "NES", extension: ".nes", filename: `${title}.nes`, tags: [], cover_url: null, ...extra };
}

function detail(roms, extra = {}) {
  return { id: 5, name: "Road trip", created_by: 1, created_by_username: "alice", rom_count: roms.length, roms, ...extra };
}

function romPage(results) {
  return { count: results.length, next: null, previous: null, results };
}

function rowTitles() {
  return within(screen.getByRole("list", { name: "Playlist ROMs" }))
    .getAllByRole("heading", { level: 3 })
    .map((node) => node.textContent);
}

async function openDetail(playlist, me = ME) {
  api.listPlaylists.mockResolvedValue([{ id: 5, name: playlist.name, created_by: playlist.created_by, rom_count: playlist.roms.length }]);
  api.getPlaylist.mockResolvedValue(playlist);
  render(<PlaylistsView me={me} />);
  fireEvent.click(await screen.findByRole("button", { name: new RegExp(playlist.name) }));
  await screen.findByRole("heading", { name: playlist.name });
}

beforeEach(() => {
  vi.clearAllMocks();
  api.coverObjectUrl.mockResolvedValue("blob:cover");
  api.listRoms.mockResolvedValue(romPage([]));
});

describe("PlaylistsView list", () => {
  it("lists playlists with counts and marks the ones you own", async () => {
    api.listPlaylists.mockResolvedValue([
      { id: 1, name: "Mine", created_by: 1, rom_count: 3 },
      { id: 2, name: "Theirs", created_by: 9, rom_count: 1 }
    ]);
    render(<PlaylistsView me={ME} />);

    expect(await screen.findByRole("button", { name: /Mine/ })).toHaveTextContent("3 ROMs");
    expect(screen.getByRole("button", { name: /Theirs/ })).toHaveTextContent("1 ROM");
    expect(screen.getAllByText("Yours")).toHaveLength(1);
  });

  it("creates a playlist and opens it", async () => {
    api.listPlaylists.mockResolvedValue([]);
    api.createPlaylist.mockResolvedValue(detail([], { id: 8, name: "Fresh" }));
    render(<PlaylistsView me={ME} />);

    fireEvent.change(await screen.findByLabelText("New playlist name"), { target: { value: "  Fresh " } });
    fireEvent.click(screen.getByRole("button", { name: "Create playlist" }));

    expect(await screen.findByRole("heading", { name: "Fresh" })).toBeInTheDocument();
    expect(api.createPlaylist).toHaveBeenCalledWith({ name: "Fresh" });
  });

  it("surfaces a list error", async () => {
    api.listPlaylists.mockRejectedValue(new Error("boom"));
    render(<PlaylistsView me={ME} />);
    expect(await screen.findByRole("alert")).toHaveTextContent("boom");
  });

  it("surfaces a create error and stays on the list", async () => {
    api.listPlaylists.mockResolvedValue([]);
    api.createPlaylist.mockRejectedValue(new Error('{"name":["Required"]}'));
    render(<PlaylistsView me={ME} />);

    fireEvent.change(await screen.findByLabelText("New playlist name"), { target: { value: "x" } });
    fireEvent.click(screen.getByRole("button", { name: "Create playlist" }));

    expect(await screen.findByRole("alert")).toHaveTextContent("Required");
  });
});

describe("PlaylistsView detail (owner)", () => {
  it("shows ROMs in order with clean title and tags", async () => {
    await openDetail(detail([rom(2, "Zelda", { tags: ["USA", "Rev 1"] }), rom(1, "Metroid")]));

    expect(rowTitles()).toEqual(["Zelda", "Metroid"]);
    expect(screen.getByText("USA · Rev 1")).toBeInTheDocument();
  });

  it("renames and saves name with the unchanged ordered rom_ids", async () => {
    await openDetail(detail([rom(2, "Zelda"), rom(1, "Metroid")]));
    api.updatePlaylist.mockResolvedValue(detail([rom(2, "Zelda"), rom(1, "Metroid")], { name: "Better" }));

    fireEvent.change(screen.getByLabelText("Playlist name"), { target: { value: "Better" } });
    fireEvent.click(screen.getByRole("button", { name: "Save changes" }));

    await waitFor(() => expect(api.updatePlaylist).toHaveBeenCalledWith(5, { name: "Better", rom_ids: [2, 1] }));
    expect(await screen.findByRole("status")).toHaveTextContent("Saved");
  });

  it("removes and reorders, sending the new order on one save", async () => {
    await openDetail(detail([rom(1, "A"), rom(2, "B"), rom(3, "C")]));
    api.updatePlaylist.mockResolvedValue(detail([rom(3, "C"), rom(1, "A")]));

    fireEvent.click(screen.getByRole("button", { name: "Remove B" }));
    expect(rowTitles()).toEqual(["A", "C"]);
    fireEvent.click(screen.getByRole("button", { name: "Move C up" }));
    expect(rowTitles()).toEqual(["C", "A"]);
    expect(screen.getByRole("button", { name: "Move C up" })).toBeDisabled();
    expect(screen.getByRole("button", { name: "Move A down" })).toBeDisabled();
    fireEvent.click(screen.getByRole("button", { name: "Save changes" }));

    await waitFor(() => expect(api.updatePlaylist).toHaveBeenCalledWith(5, { name: "Road trip", rom_ids: [3, 1] }));
  });

  it("disables Save until something changed", async () => {
    await openDetail(detail([rom(1, "A")]));
    expect(screen.getByRole("button", { name: "Save changes" })).toBeDisabled();
    fireEvent.click(screen.getByRole("button", { name: "Remove A" }));
    expect(screen.getByRole("button", { name: "Save changes" })).toBeEnabled();
  });

  it("adds ROMs from the picker, appended in pick order", async () => {
    await openDetail(detail([rom(1, "A")]));
    api.listRoms.mockResolvedValue(romPage([rom(1, "A"), rom(7, "Gamma"), rom(8, "Delta")]));
    api.updatePlaylist.mockResolvedValue(detail([rom(1, "A"), rom(8, "Delta"), rom(7, "Gamma")]));

    fireEvent.click(screen.getByRole("button", { name: "Add ROMs" }));
    const picker = await screen.findByRole("dialog", { name: "Add ROMs" });
    expect(await within(picker).findByLabelText("Gamma")).toBeInTheDocument();
    expect(within(picker).getByLabelText("A")).toBeDisabled(); // already in the playlist
    fireEvent.click(within(picker).getByLabelText("Delta"));
    fireEvent.click(within(picker).getByLabelText("Gamma"));
    fireEvent.click(within(picker).getByRole("button", { name: "Add 2 selected" }));

    expect(rowTitles()).toEqual(["A", "Delta", "Gamma"]);
    fireEvent.click(screen.getByRole("button", { name: "Save changes" }));
    await waitFor(() => expect(api.updatePlaylist).toHaveBeenCalledWith(5, { name: "Road trip", rom_ids: [1, 8, 7] }));
  });

  it("searches in the picker", async () => {
    await openDetail(detail([]));
    fireEvent.click(screen.getByRole("button", { name: "Add ROMs" }));
    const picker = await screen.findByRole("dialog", { name: "Add ROMs" });
    fireEvent.change(within(picker).getByLabelText("Search titles"), { target: { value: "mario" } });
    fireEvent.click(within(picker).getByRole("button", { name: "Search" }));

    await waitFor(() => expect(api.listRoms).toHaveBeenLastCalledWith({ search: "mario", page: 1 }));
  });

  it("refuses to grow past 500 ROMs", async () => {
    const many = Array.from({ length: 500 }, (_, i) => rom(i + 1, `R${i + 1}`));
    await openDetail(detail(many));
    api.listRoms.mockResolvedValue(romPage([rom(999, "Extra")]));

    fireEvent.click(screen.getByRole("button", { name: "Add ROMs" }));
    const picker = await screen.findByRole("dialog", { name: "Add ROMs" });
    fireEvent.click(await within(picker).findByLabelText("Extra"));
    fireEvent.click(within(picker).getByRole("button", { name: "Add 1 selected" }));

    expect(await screen.findByRole("alert")).toHaveTextContent("500");
    expect(api.updatePlaylist).not.toHaveBeenCalled();
  });

  it("surfaces a save error and keeps the draft", async () => {
    await openDetail(detail([rom(1, "A")]));
    api.updatePlaylist.mockRejectedValue(new Error("nope"));

    fireEvent.click(screen.getByRole("button", { name: "Remove A" }));
    fireEvent.click(screen.getByRole("button", { name: "Save changes" }));

    expect(await screen.findByRole("alert")).toHaveTextContent("nope");
    expect(screen.getByRole("button", { name: "Save changes" })).toBeEnabled();
  });

  it("deletes the playlist after confirmation and returns to the list", async () => {
    await openDetail(detail([rom(1, "A")]));
    api.deletePlaylist.mockResolvedValue(null);
    const confirm = vi.spyOn(window, "confirm").mockReturnValue(true);

    fireEvent.click(screen.getByRole("button", { name: "Delete playlist" }));

    expect(await screen.findByLabelText("New playlist name")).toBeInTheDocument();
    expect(api.deletePlaylist).toHaveBeenCalledWith(5);
    confirm.mockRestore();
  });

  it("does not delete when the confirmation is declined", async () => {
    await openDetail(detail([rom(1, "A")]));
    const confirm = vi.spyOn(window, "confirm").mockReturnValue(false);
    fireEvent.click(screen.getByRole("button", { name: "Delete playlist" }));
    expect(api.deletePlaylist).not.toHaveBeenCalled();
    confirm.mockRestore();
  });

  it("loads private cover art through the authenticated api", async () => {
    await openDetail(detail([rom(1, "A", { cover_url: "/api/roms/1/cover/" }), rom(2, "B")]));
    expect(await screen.findByRole("img", { name: "A" })).toHaveAttribute("src", "blob:cover");
    expect(screen.queryByRole("img", { name: "B" })).not.toBeInTheDocument();
    expect(api.coverObjectUrl).toHaveBeenCalledTimes(1);
  });
});

describe("PlaylistsView detail (not the owner)", () => {
  it("is read-only", async () => {
    await openDetail(detail([rom(1, "A")], { created_by: 9, created_by_username: "bob" }));

    expect(screen.getByText(/bob/)).toBeInTheDocument();
    expect(rowTitles()).toEqual(["A"]);
    for (const name of ["Save changes", "Add ROMs", "Delete playlist", "Remove A", "Move A up", "Move A down"]) {
      expect(screen.queryByRole("button", { name })).not.toBeInTheDocument();
    }
    expect(screen.queryByLabelText("Playlist name")).not.toBeInTheDocument();
  });

  it("goes back to the list", async () => {
    await openDetail(detail([], { created_by: 9 }));
    fireEvent.click(screen.getByRole("button", { name: "Back to playlists" }));
    expect(await screen.findByLabelText("New playlist name")).toBeInTheDocument();
  });
});
