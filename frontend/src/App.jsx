import { useEffect, useState } from "react";
import { api, consumeOidcFragment, getToken, setToken } from "./api/client";

function LocalAuthForm({ onAuthed }) {
  const [mode, setMode] = useState("login");
  const [username, setUsername] = useState("");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState("");
  const registering = mode === "register";

  async function handleSubmit(event) {
    event.preventDefault();
    try {
      const data = registering
        ? await api.register({ username, email, password })
        : await api.login({ username, password });
      setToken(data.token);
      setError("");
      onAuthed();
    } catch (err) {
      setError(String(err.message || err));
    }
  }

  return (
    <form className="stack" onSubmit={handleSubmit}>
      <input placeholder="Username" value={username} onChange={(e) => setUsername(e.target.value)} />
      {registering ? (
        <input placeholder="Email" type="email" value={email} onChange={(e) => setEmail(e.target.value)} />
      ) : null}
      <input placeholder="Password" type="password" value={password} onChange={(e) => setPassword(e.target.value)} />
      {error ? <p className="error">{error}</p> : null}
      <div className="row">
        <button type="submit">{registering ? "Register" : "Login"}</button>
        <button type="button" onClick={() => setMode(registering ? "login" : "register")}>
          {registering ? "Back to login" : "Create account"}
        </button>
      </div>
    </form>
  );
}

function AuthPanel({ config, onAuthed }) {
  if (!config) {
    return <section className="card">Loading sign-in options…</section>;
  }
  const local = config.methods.includes("local");
  const oidc = config.methods.includes("oidc");

  return (
    <section className="card">
      <h2>Login</h2>
      <div className="stack">
        {oidc ? (
          <a className="button" href={api.oidcLoginUrl}>
            Login with {config.oidc?.provider_name || "SSO"}
          </a>
        ) : null}
        {local && oidc ? <p className="muted">or</p> : null}
        {local ? <LocalAuthForm onAuthed={onAuthed} /> : null}
        {!local && !oidc ? <p className="error">No login methods are enabled on this server.</p> : null}
      </div>
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

// Pick up an SSO callback result before the first render so the app starts signed in.
function initialAuth() {
  const result = consumeOidcFragment();
  if (result?.token) setToken(result.token);
  return { authed: Boolean(getToken()), error: result?.error || "" };
}

export default function App() {
  const [initial] = useState(initialAuth);
  const [roms, setRoms] = useState([]);
  const [authed, setAuthed] = useState(initial.authed);
  const [error, setError] = useState(initial.error);
  const [authConfig, setAuthConfig] = useState(null);
  const [me, setMe] = useState(null);

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
      api.me().then(setMe, () => logout());
    }
  }, [authed]);

  useEffect(() => {
    if (!authed && !authConfig) {
      api.authConfig().then(setAuthConfig, (err) => setError(String(err.message || err)));
    }
  }, [authed, authConfig]);

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
    setMe(null);
  }

  return (
    <main className="container">
      <h1>birdROMs</h1>
      {error ? <p className="error">{error}</p> : null}
      {!authed ? <AuthPanel config={authConfig} onAuthed={() => setAuthed(true)} /> : null}
      {authed ? (
        <>
          {me ? (
            <p className="muted">
              Signed in as <strong>{me.username}</strong>
              {me.role ? ` (${me.role})` : ""}
            </p>
          ) : null}
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
