import { useState } from "react";
import { api } from "./api/client";
import { errorMessage } from "./PlaylistsView";

// "Add to playlist" on a library card: pick one of your own playlists and the ROM is appended.
// Updates send the playlist's full current order plus the new ROM, since `rom_ids` replaces it.
export default function AddToPlaylist({ rom, me }) {
  const [open, setOpen] = useState(false);
  const [playlists, setPlaylists] = useState(null);
  const [status, setStatus] = useState("");
  const [error, setError] = useState("");

  async function toggle() {
    const next = !open;
    setOpen(next);
    setStatus("");
    setError("");
    if (!next) return;
    try {
      const all = await api.listPlaylists();
      setPlaylists(all.filter((playlist) => playlist.created_by === me?.id));
    } catch (err) {
      setError(errorMessage(err));
    }
  }

  async function add(playlist) {
    setStatus("");
    setError("");
    try {
      const current = await api.getPlaylist(playlist.id);
      const ids = (current.roms || []).map((item) => item.id);
      if (ids.includes(rom.id)) {
        setStatus(`Already in ${playlist.name}`);
        return;
      }
      await api.updatePlaylist(playlist.id, { rom_ids: [...ids, rom.id] });
      setStatus(`Added to ${playlist.name}`);
      setOpen(false);
    } catch (err) {
      setError(errorMessage(err));
    }
  }

  return (
    <div className="add-to-playlist">
      <button
        type="button"
        className="ghost"
        aria-expanded={open}
        aria-label={`Add ${rom.title} to a playlist`}
        onClick={toggle}
      >
        Add to playlist
      </button>
      {open ? (
        <div className="playlist-menu">
          {playlists && playlists.length === 0 ? <p className="muted">You have no playlists yet.</p> : null}
          {(playlists || []).map((playlist) => (
            <button key={playlist.id} type="button" className="ghost" onClick={() => add(playlist)}>
              {playlist.name}
            </button>
          ))}
          {error ? <p className="error" role="alert">{error}</p> : null}
        </div>
      ) : null}
      {status ? <p className="add-status" role="status">{status}</p> : null}
    </div>
  );
}
