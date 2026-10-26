import { useEffect, useState } from "react";
import { api, getToken, setToken } from "./api/client";

function AuthPanel({ onAuthed }) {
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState("");

  async function handleLogin(event) {
    event.preventDefault();
    try {
      const data = await api.login({ username, password });
      setToken(data.token);
      setError("");
      onAuthed();
    } catch (err) {
      setError(String(err.message || err));
    }
  }

  return (
    <section className="card">
      <h2>Login</h2>
      <form className="stack" onSubmit={handleLogin}>
        <input placeholder="Username" value={username} onChange={(e) => setUsername(e.target.value)} />
        <input placeholder="Password" type="password" value={password} onChange={(e) => setPassword(e.target.value)} />
        {error ? <p className="error">{error}</p> : null}
        <div className="row">
          <button type="submit">Login</button>
        </div>
      </form>
    </section>
  );
}

function UploadPanel({ onUploaded }) {
  const [title, setTitle] = useState("");
  const [file, setFile] = useState(null);

  async function handleUpload(event) {
    event.preventDefault();
    if (!file) return;
    const formData = new FormData();
    formData.append("title", title || file.name);
    formData.append("file", file);
    await api.createRom(formData);
    setTitle("");
    setFile(null);
    onUploaded();
  }

  return (
    <section className="card">
      <h2>Upload ROM</h2>
      <form className="stack" onSubmit={handleUpload}>
        <input placeholder="ROM title" value={title} onChange={(e) => setTitle(e.target.value)} />
        <input type="file" onChange={(e) => setFile(e.target.files?.[0] || null)} />
        <button type="submit">Upload</button>
      </form>
    </section>
  );
}

function RomList({ roms, onScrape, onDownload }) {
  return (
    <section className="card">
      <h2>ROM Library</h2>
      <div className="stack">
        {roms.map((rom) => (
          <div key={rom.id} className="rom">
            <div>
              <strong>{rom.title}</strong> - {rom.platform} ({rom.extension})
            </div>
            <div className="row">
              <button onClick={() => onDownload(rom)}>Download</button>
              <button onClick={() => onScrape(rom.id)}>Scrape Cover</button>
            </div>
            {rom.cover_art_url ? <img src={rom.cover_art_url} alt={rom.title} className="cover" /> : null}
          </div>
        ))}
      </div>
    </section>
  );
}

export default function App() {
  const [roms, setRoms] = useState([]);
  const [authed, setAuthed] = useState(Boolean(getToken()));
  const [error, setError] = useState("");

  async function loadRoms() {
    try {
      const data = await api.listRoms();
      setRoms(data);
      setError("");
    } catch (err) {
      setError(String(err.message || err));
    }
  }

  useEffect(() => {
    if (authed) {
      loadRoms();
    }
  }, [authed]);

  async function downloadRom(rom) {
    try {
      await api.downloadRom(rom);
      setError("");
    } catch (err) {
      setError(String(err.message || err));
    }
  }

  function logout() {
    setToken(null);
    setAuthed(false);
    setRoms([]);
  }

  return (
    <main className="container">
      <h1>birdROMs</h1>
      {error ? <p className="error">{error}</p> : null}
      {!authed ? <AuthPanel onAuthed={() => setAuthed(true)} /> : null}
      {authed ? (
        <>
          <div className="row">
            <button onClick={loadRoms}>Refresh</button>
            <button onClick={logout}>Logout</button>
          </div>
          <UploadPanel onUploaded={loadRoms} />
          <RomList
            roms={roms}
            onScrape={async (id) => { await api.scrapeCover(id); await loadRoms(); }}
            onDownload={downloadRom}
          />
        </>
      ) : null}
    </main>
  );
}
