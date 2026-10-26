import { useCallback, useEffect, useRef, useState } from "react";
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

const PAGE_SIZE = 24;
const EMPTY_PAGE = { count: 0, next: null, previous: null, results: [] };
const DEFAULT_QUERY = { search: "", platform: "", page: 1 };

function LibraryFilters({ query, platforms, onChange }) {
  const [search, setSearch] = useState(query.search);

  function handleSearch(event) {
    event.preventDefault();
    onChange({ ...query, search: search.trim(), page: 1 });
  }

  return (
    <form className="row" role="search" onSubmit={handleSearch}>
      <input placeholder="Search titles" value={search} onChange={(e) => setSearch(e.target.value)} />
      <button type="submit">Search</button>
      <select
        aria-label="Platform"
        value={query.platform}
        onChange={(e) => onChange({ ...query, platform: e.target.value, page: 1 })}
      >
        <option value="">All platforms</option>
        {platforms.map((platform) => (
          <option key={platform} value={platform}>
            {platform}
          </option>
        ))}
      </select>
    </form>
  );
}

function Pagination({ romPage, page, onPage }) {
  const pages = Math.max(1, Math.ceil(romPage.count / PAGE_SIZE));
  return (
    <div className="row">
      <button disabled={!romPage.previous} onClick={() => onPage(page - 1)}>
        Previous
      </button>
      <span className="muted">
        Page {page} of {pages} · {romPage.count} ROM{romPage.count === 1 ? "" : "s"}
      </span>
      <button disabled={!romPage.next} onClick={() => onPage(page + 1)}>
        Next
      </button>
    </div>
  );
}

function RomList({ romPage, query, platforms, onQuery, onScrape, onDownload }) {
  return (
    <section className="card">
      <h2>ROM Library</h2>
      <div className="stack">
        <LibraryFilters query={query} platforms={platforms} onChange={onQuery} />
        {romPage.results.length === 0 ? <p className="muted">No ROMs found.</p> : null}
        {romPage.results.map((rom) => (
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
        <Pagination romPage={romPage} page={query.page} onPage={(page) => onQuery({ ...query, page })} />
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
  const [romPage, setRomPage] = useState(EMPTY_PAGE);
  const [query, setQuery] = useState(DEFAULT_QUERY);
  const [platforms, setPlatforms] = useState([]);
  const latestRequest = useRef(0);
  const [authed, setAuthed] = useState(initial.authed);
  const [error, setError] = useState(initial.error);
  const [authConfig, setAuthConfig] = useState(null);
  const [me, setMe] = useState(null);

  // Only the newest request may update the list, so a slow response for an old filter
  // cannot overwrite the results of a newer one.
  const loadRoms = useCallback(async () => {
    const requestId = ++latestRequest.current;
    try {
      const [data, platformList] = await Promise.all([api.listRoms(query), api.listPlatforms()]);
      if (requestId !== latestRequest.current) return;
      setRomPage(data);
      setPlatforms(platformList);
      setError("");
    } catch (err) {
      if (requestId !== latestRequest.current) return;
      setError(String(err.message || err));
    }
  }, [query]);

  useEffect(() => {
    if (authed) {
      api.me().then(setMe, () => logout());
    }
  }, [authed]);

  useEffect(() => {
    if (authed) loadRoms();
  }, [authed, loadRoms]);

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
    setRomPage(EMPTY_PAGE);
    setQuery(DEFAULT_QUERY);
    setPlatforms([]);
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
            romPage={romPage}
            query={query}
            platforms={platforms}
            onQuery={setQuery}
            onScrape={async (id) => { await api.scrapeCover(id); await loadRoms(); }}
            onDownload={downloadRom}
          />
        </>
      ) : null}
    </main>
  );
}
