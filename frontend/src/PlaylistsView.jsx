import { useEffect, useRef, useState } from "react";
import { api } from "./api/client";

// Mirrors the backend's cap on `rom_ids`.
export const MAX_PLAYLIST_ROMS = 500;

// DRF errors arrive as raw JSON text ({"name": ["..."]} or {"detail": "..."}); show just the words.
export function errorMessage(err) {
  const raw = String(err?.message || err);
  try {
    const body = JSON.parse(raw);
    if (body && typeof body === "object") {
      if (typeof body.detail === "string") return body.detail;
      const parts = Object.values(body).flat().filter((part) => typeof part === "string");
      if (parts.length > 0) return parts.join(" ");
    }
  } catch {
    // not a JSON body; keep the raw text
  }
  return raw;
}

function plural(count, word) {
  return `${count} ${word}${count === 1 ? "" : "s"}`;
}

// Playlist ROMs use the compact device shape, so the cover is `cover_url`, fetched with the token.
function PlaylistCover({ rom }) {
  const [src, setSrc] = useState(null);
  // Picked-but-unsaved ROMs have the library shape (`cover_art_url`); saved ones the device shape.
  const hasCover = Boolean(rom.cover_url || rom.cover_art_url);

  useEffect(() => {
    if (!hasCover) return undefined;
    let cancelled = false;
    let objectUrl = null;
    api.coverObjectUrl({ id: rom.id }).then(
      (url) => {
        if (cancelled) URL.revokeObjectURL?.(url);
        else setSrc((objectUrl = url));
      },
      () => {}
    );
    return () => {
      cancelled = true;
      if (objectUrl) URL.revokeObjectURL?.(objectUrl);
      setSrc(null);
    };
  }, [rom.id, hasCover]);

  const initial = (rom.title || "?").trim().charAt(0).toUpperCase() || "?";
  return (
    <div className="playlist-cover">
      {src ? <img src={src} alt={rom.title} /> : <span aria-hidden="true">{initial}</span>}
    </div>
  );
}

function RomPicker({ existingIds, onAdd, onClose }) {
  const [search, setSearch] = useState("");
  const [query, setQuery] = useState({ search: "", page: 1 });
  const [romPage, setRomPage] = useState(null);
  const [picked, setPicked] = useState([]); // ROM objects, in pick order, across pages
  const [error, setError] = useState("");

  useEffect(() => {
    let cancelled = false;
    api.listRoms(query).then(
      (data) => {
        if (cancelled) return;
        setRomPage(data);
        setError("");
      },
      (err) => {
        if (!cancelled) setError(errorMessage(err));
      }
    );
    return () => {
      cancelled = true;
    };
  }, [query]);

  function toggle(rom) {
    setPicked((current) =>
      current.some((item) => item.id === rom.id) ? current.filter((item) => item.id !== rom.id) : [...current, rom]
    );
  }

  function handleSearch(event) {
    event.preventDefault();
    setQuery({ search: search.trim(), page: 1 });
  }

  const results = romPage?.results || [];
  return (
    <section className="card picker" role="dialog" aria-label="Add ROMs">
      <div className="picker-head">
        <h3>Add ROMs</h3>
        <button type="button" className="ghost" onClick={onClose}>Close</button>
      </div>
      <form className="filters" role="search" onSubmit={handleSearch}>
        <input
          type="search"
          aria-label="Search titles"
          placeholder="Search titles"
          value={search}
          onChange={(e) => setSearch(e.target.value)}
        />
        <button type="submit" className="primary">Search</button>
      </form>
      {error ? <p className="error" role="alert">{error}</p> : null}
      {romPage && results.length === 0 ? <p className="muted">No ROMs found.</p> : null}
      <ul className="picker-list" aria-label="Library ROMs">
        {results.map((rom) => {
          const already = existingIds.includes(rom.id);
          return (
            <li key={rom.id} className="picker-row">
              <label>
                <input
                  type="checkbox"
                  checked={already || picked.some((item) => item.id === rom.id)}
                  disabled={already}
                  onChange={() => toggle(rom)}
                />
                <span>{rom.title}</span>
              </label>
              <span className="muted picker-meta">
                {[rom.platform, ...(Array.isArray(rom.tags) ? rom.tags : [])].filter(Boolean).join(" · ")}
              </span>
            </li>
          );
        })}
      </ul>
      <div className="picker-foot">
        <button
          type="button"
          disabled={!romPage || !romPage.previous}
          onClick={() => setQuery({ ...query, page: query.page - 1 })}
        >
          Previous
        </button>
        <button
          type="button"
          disabled={!romPage || !romPage.next}
          onClick={() => setQuery({ ...query, page: query.page + 1 })}
        >
          Next
        </button>
        <button type="button" className="primary" disabled={picked.length === 0} onClick={() => onAdd(picked)}>
          Add {picked.length} selected
        </button>
      </div>
    </section>
  );
}

function PlaylistDetail({ id, initial, me, onBack, onDeleted }) {
  const [playlist, setPlaylist] = useState(initial || null);
  const [name, setName] = useState(initial?.name || "");
  const [roms, setRoms] = useState(initial?.roms || []);
  const [picking, setPicking] = useState(false);
  const [busy, setBusy] = useState(false);
  const [saved, setSaved] = useState(false);
  const [error, setError] = useState("");

  function adopt(data) {
    setPlaylist(data);
    setName(data.name);
    setRoms(data.roms || []);
  }

  useEffect(() => {
    if (initial) return undefined;
    let cancelled = false;
    api.getPlaylist(id).then(
      (data) => {
        if (!cancelled) adopt(data);
      },
      (err) => {
        if (!cancelled) setError(errorMessage(err));
      }
    );
    return () => {
      cancelled = true;
    };
  }, [id, initial]);

  if (!playlist) {
    return (
      <section className="card playlist-detail">
        <button type="button" className="ghost" onClick={onBack}>Back to playlists</button>
        {error ? <p className="error" role="alert">{error}</p> : <p className="muted loading-text">Loading playlist…</p>}
      </section>
    );
  }

  const owner = me?.id === playlist.created_by;
  const savedRoms = playlist.roms || [];
  const dirty =
    name.trim() !== playlist.name ||
    roms.length !== savedRoms.length ||
    roms.some((rom, index) => rom.id !== savedRoms[index].id);

  function edit(change) {
    setSaved(false);
    setError("");
    change();
  }

  function move(index, delta) {
    edit(() =>
      setRoms((current) => {
        const next = [...current];
        const [item] = next.splice(index, 1);
        next.splice(index + delta, 0, item);
        return next;
      })
    );
  }

  function remove(index) {
    edit(() => setRoms((current) => current.filter((_, position) => position !== index)));
  }

  function addPicked(picked) {
    const fresh = picked.filter((rom) => !roms.some((item) => item.id === rom.id));
    if (roms.length + fresh.length > MAX_PLAYLIST_ROMS) {
      setError(`A playlist can hold at most ${MAX_PLAYLIST_ROMS} ROMs.`);
      return;
    }
    edit(() => {
      setRoms([...roms, ...fresh]);
      setPicking(false);
    });
  }

  async function handleSave() {
    if (busy) return;
    setBusy(true);
    try {
      const data = await api.updatePlaylist(playlist.id, { name: name.trim(), rom_ids: roms.map((rom) => rom.id) });
      adopt({ ...data, roms: Array.isArray(data?.roms) ? data.roms : roms });
      setError("");
      setSaved(true);
    } catch (err) {
      setError(errorMessage(err));
    } finally {
      setBusy(false);
    }
  }

  async function handleDelete() {
    if (!window.confirm(`Delete the playlist "${playlist.name}"? The ROMs themselves are not deleted.`)) return;
    try {
      await api.deletePlaylist(playlist.id);
      onDeleted();
    } catch (err) {
      setError(errorMessage(err));
    }
  }

  return (
    <section className="card playlist-detail">
      <div className="playlist-head">
        <button type="button" className="ghost" onClick={onBack}>Back to playlists</button>
        <h2>{playlist.name}</h2>
        <p className="muted">
          {owner ? "Yours" : `By ${playlist.created_by_username || "a friend"}`} · {plural(roms.length, "ROM")}
        </p>
      </div>
      {owner ? (
        <div className="playlist-edit">
          <input
            aria-label="Playlist name"
            value={name}
            onChange={(e) => edit(() => setName(e.target.value))}
          />
          <button type="button" className="primary" disabled={!dirty || busy || !name.trim()} onClick={handleSave}>
            {busy ? "Saving…" : "Save changes"}
          </button>
          <button type="button" onClick={() => edit(() => setPicking(true))}>Add ROMs</button>
          <button type="button" className="danger" onClick={handleDelete}>Delete playlist</button>
        </div>
      ) : null}
      {error ? <p className="error" role="alert">{error}</p> : null}
      {saved ? <p role="status">Saved.</p> : null}
      {owner && picking ? (
        <RomPicker existingIds={roms.map((rom) => rom.id)} onAdd={addPicked} onClose={() => setPicking(false)} />
      ) : null}
      {roms.length === 0 ? <p className="muted">No ROMs in this playlist yet.</p> : null}
      <ol className="playlist-roms" aria-label="Playlist ROMs">
        {roms.map((rom, index) => (
          <li key={rom.id} className="playlist-row">
            <PlaylistCover rom={rom} />
            <div className="playlist-row-body">
              <h3 className="rom-title" title={rom.filename || rom.title}>{rom.title}</h3>
              {Array.isArray(rom.tags) && rom.tags.length > 0 ? <p className="rom-tags">{rom.tags.join(" · ")}</p> : null}
              <span className="muted">{rom.platform || "Unknown"}</span>
            </div>
            {owner ? (
              <div className="playlist-row-actions">
                <button
                  type="button"
                  className="ghost"
                  aria-label={`Move ${rom.title} up`}
                  disabled={index === 0}
                  onClick={() => move(index, -1)}
                >
                  ↑
                </button>
                <button
                  type="button"
                  className="ghost"
                  aria-label={`Move ${rom.title} down`}
                  disabled={index === roms.length - 1}
                  onClick={() => move(index, 1)}
                >
                  ↓
                </button>
                <button type="button" className="ghost" aria-label={`Remove ${rom.title}`} onClick={() => remove(index)}>
                  ✕
                </button>
              </div>
            ) : null}
          </li>
        ))}
      </ol>
    </section>
  );
}

function PlaylistList({ me, onOpen }) {
  const [playlists, setPlaylists] = useState(null);
  const [name, setName] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const mounted = useRef(true);

  useEffect(() => {
    mounted.current = true;
    api.listPlaylists().then(
      (data) => {
        if (mounted.current) setPlaylists(data);
      },
      (err) => {
        if (mounted.current) {
          setPlaylists([]);
          setError(errorMessage(err));
        }
      }
    );
    return () => {
      mounted.current = false;
    };
  }, []);

  async function handleCreate(event) {
    event.preventDefault();
    if (!name.trim() || busy) return;
    setBusy(true);
    try {
      const created = await api.createPlaylist({ name: name.trim() });
      if (mounted.current) onOpen(created.id, created);
    } catch (err) {
      if (mounted.current) setError(errorMessage(err));
    } finally {
      if (mounted.current) setBusy(false);
    }
  }

  return (
    <section className="library">
      <div className="library-head">
        <h2>Playlists</h2>
        <form className="filters" onSubmit={handleCreate}>
          <input
            aria-label="New playlist name"
            placeholder="New playlist name"
            value={name}
            onChange={(e) => setName(e.target.value)}
          />
          <button type="submit" className="primary" disabled={!name.trim() || busy}>Create playlist</button>
        </form>
      </div>
      {error ? <p className="error" role="alert">{error}</p> : null}
      {playlists && playlists.length === 0 && !error ? (
        <div className="empty-state">
          <p className="empty-title">No playlists yet.</p>
          <p className="muted">Create one above, then add ROMs to it.</p>
        </div>
      ) : null}
      {playlists && playlists.length > 0 ? (
        <ul className="playlist-list" aria-label="Playlists">
          {playlists.map((playlist) => (
            <li key={playlist.id}>
              <button type="button" className="playlist-item" onClick={() => onOpen(playlist.id)}>
                <span className="playlist-name">{playlist.name}</span>
                <span className="muted">{plural(playlist.rom_count, "ROM")}</span>
                {playlist.created_by === me?.id ? (
                  <span className="role-badge admin">Yours</span>
                ) : (
                  <span className="muted">By {playlist.created_by_username || "a friend"}</span>
                )}
              </button>
            </li>
          ))}
        </ul>
      ) : null}
    </section>
  );
}

export default function PlaylistsView({ me }) {
  const [selected, setSelected] = useState(null); // { id, initial? }
  if (selected) {
    return (
      <PlaylistDetail
        key={selected.id}
        id={selected.id}
        initial={selected.initial}
        me={me}
        onBack={() => setSelected(null)}
        onDeleted={() => setSelected(null)}
      />
    );
  }
  return <PlaylistList me={me} onOpen={(id, initial) => setSelected({ id, initial })} />;
}
