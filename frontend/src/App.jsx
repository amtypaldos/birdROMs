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
      <input
        aria-label="Username"
        placeholder="Username"
        autoComplete="username"
        value={username}
        onChange={(e) => setUsername(e.target.value)}
      />
      {registering ? (
        <input
          aria-label="Email"
          placeholder="Email"
          type="email"
          autoComplete="email"
          value={email}
          onChange={(e) => setEmail(e.target.value)}
        />
      ) : null}
      <input
        aria-label="Password"
        placeholder="Password"
        type="password"
        autoComplete={registering ? "new-password" : "current-password"}
        value={password}
        onChange={(e) => setPassword(e.target.value)}
      />
      {error ? <p className="error" role="alert">{error}</p> : null}
      <div className="row">
        <button type="submit" className="primary">{registering ? "Register" : "Login"}</button>
        <button type="button" className="ghost" onClick={() => setMode(registering ? "login" : "register")}>
          {registering ? "Back to login" : "Create account"}
        </button>
      </div>
    </form>
  );
}

function AuthPanel({ config, onAuthed }) {
  if (!config) {
    return (
      <section className="card auth-card">
        <p className="muted loading-text">Loading sign-in options…</p>
      </section>
    );
  }
  const local = config.methods.includes("local");
  const oidc = config.methods.includes("oidc");

  return (
    <section className="card auth-card">
      <p className="eyebrow" aria-hidden="true">Insert coin</p>
      <h2>Login</h2>
      <div className="stack">
        {oidc ? (
          <a className="button primary" href={api.oidcLoginUrl}>
            Login with {config.oidc?.provider_name || "SSO"}
          </a>
        ) : null}
        {local && oidc ? <p className="divider">or</p> : null}
        {local ? <LocalAuthForm onAuthed={onAuthed} /> : null}
        {!local && !oidc ? <p className="error">No login methods are enabled on this server.</p> : null}
      </div>
    </section>
  );
}

function UploadPanel({ onUploaded }) {
  const [title, setTitle] = useState("");
  const [file, setFile] = useState(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const fileInput = useRef(null);

  async function handleUpload(event) {
    event.preventDefault();
    if (!file || busy) return;
    const formData = new FormData();
    formData.append("title", title || file.name);
    formData.append("file", file);
    setBusy(true);
    try {
      await api.createRom(formData);
      setTitle("");
      setFile(null);
      if (fileInput.current) fileInput.current.value = "";
      setError("");
      onUploaded();
    } catch (err) {
      setError(String(err.message || err));
    } finally {
      setBusy(false);
    }
  }

  return (
    <section className="card upload-card">
      <h2>Upload ROM</h2>
      <form className="upload-form" onSubmit={handleUpload}>
        <input
          aria-label="ROM title"
          placeholder="ROM title"
          value={title}
          onChange={(e) => setTitle(e.target.value)}
        />
        <input
          ref={fileInput}
          aria-label="ROM file"
          type="file"
          onChange={(e) => setFile(e.target.files?.[0] || null)}
        />
        <button type="submit" className="primary" disabled={!file || busy}>
          {busy ? "Uploading…" : "Upload"}
        </button>
      </form>
      {error ? <p className="error" role="alert">{error}</p> : null}
    </section>
  );
}

const UPLOAD_STATUS_LABEL = { queued: "Queued", uploading: "Uploading…", done: "Uploaded" };

function carriesFiles(event) {
  return Array.from(event.dataTransfer?.types || []).includes("Files");
}

// Page-level drop target: drag ROM files anywhere over the app to upload them. Files are sent one
// at a time; a failure is recorded against its file and never stops the rest of the batch.
function GlobalDropzone({ onUploaded }) {
  const [dragging, setDragging] = useState(false);
  const [uploads, setUploads] = useState([]);
  const depth = useRef(0);
  const nextId = useRef(0);
  const queue = useRef(Promise.resolve());
  const mounted = useRef(true);
  const onUploadedRef = useRef(onUploaded);
  onUploadedRef.current = onUploaded;

  useEffect(() => {
    mounted.current = true;
    return () => {
      mounted.current = false;
    };
  }, []);

  useEffect(() => {
    function setStatus(id, patch) {
      if (!mounted.current) return;
      setUploads((current) => current.map((item) => (item.id === id ? { ...item, ...patch } : item)));
    }

    async function uploadBatch(batch) {
      let uploaded = false;
      for (const { id, file } of batch) {
        if (!mounted.current) return;
        setStatus(id, { status: "uploading" });
        const formData = new FormData();
        formData.append("title", file.name);
        formData.append("file", file);
        try {
          await api.createRom(formData);
          uploaded = true;
          setStatus(id, { status: "done" });
        } catch (err) {
          setStatus(id, { status: "error", error: String(err.message || err) });
        }
      }
      if (uploaded && mounted.current) onUploadedRef.current();
    }

    function handleDragEnter(event) {
      if (!carriesFiles(event)) return;
      event.preventDefault();
      depth.current += 1;
      setDragging(true);
    }

    function handleDragOver(event) {
      if (!carriesFiles(event)) return;
      event.preventDefault(); // required for the drop event to fire
    }

    function handleDragLeave(event) {
      if (!carriesFiles(event)) return;
      depth.current = Math.max(0, depth.current - 1);
      if (depth.current === 0) setDragging(false);
    }

    function handleDrop(event) {
      if (!carriesFiles(event)) return;
      event.preventDefault();
      depth.current = 0;
      setDragging(false);
      const files = Array.from(event.dataTransfer.files || []);
      if (files.length === 0) return;
      const batch = files.map((file) => ({ id: nextId.current++, file }));
      setUploads((current) => [
        ...current,
        ...batch.map(({ id, file }) => ({ id, name: file.name, status: "queued", error: "" }))
      ]);
      queue.current = queue.current.then(() => uploadBatch(batch));
    }

    const handlers = {
      dragenter: handleDragEnter,
      dragover: handleDragOver,
      dragleave: handleDragLeave,
      drop: handleDrop
    };
    Object.entries(handlers).forEach(([type, handler]) => window.addEventListener(type, handler));
    return () => {
      Object.entries(handlers).forEach(([type, handler]) => window.removeEventListener(type, handler));
    };
  }, []);

  const finished = uploads.filter((item) => item.status === "done" || item.status === "error").length;

  return (
    <>
      {dragging ? (
        <div className="drop-overlay">
          <p className="drop-overlay-text" role="status">Drop ROM files to upload</p>
        </div>
      ) : null}
      {uploads.length > 0 ? (
        <section className="card upload-queue" aria-label="Upload queue">
          <div className="upload-queue-head">
            <h2>Uploads</h2>
            <span className="muted">{finished} of {uploads.length} finished</span>
            {finished === uploads.length ? (
              <button className="ghost" onClick={() => setUploads([])}>Clear</button>
            ) : null}
          </div>
          <ul className="upload-list">
            {uploads.map((item) => (
              <li key={item.id} className={`upload-item ${item.status}`}>
                <span className="upload-name" title={item.name}>{item.name}</span>
                {item.status === "error" ? (
                  <span className="error" role="alert">Failed: {item.error}</span>
                ) : (
                  <span className="muted">{UPLOAD_STATUS_LABEL[item.status]}</span>
                )}
              </li>
            ))}
          </ul>
        </section>
      ) : null}
    </>
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
    <form className="filters" role="search" onSubmit={handleSearch}>
      <input
        type="search"
        aria-label="Search titles"
        placeholder="Search titles"
        value={search}
        onChange={(e) => setSearch(e.target.value)}
      />
      <button type="submit" className="primary">Search</button>
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
    <nav className="pagination" aria-label="Pagination">
      <button disabled={!romPage.previous} onClick={() => onPage(page - 1)}>
        Previous
      </button>
      <span className="muted page-count">
        Page {page} of {pages} · {romPage.count} ROM{romPage.count === 1 ? "" : "s"}
      </span>
      <button disabled={!romPage.next} onClick={() => onPage(page + 1)}>
        Next
      </button>
    </nav>
  );
}

function CoverImage({ rom }) {
  const [src, setSrc] = useState(null);

  useEffect(() => {
    if (!rom.cover_art_url) return undefined;
    let objectUrl = null;
    let cancelled = false;
    api.coverObjectUrl(rom).then(
      (url) => {
        if (cancelled) URL.revokeObjectURL(url);
        else setSrc((objectUrl = url));
      },
      () => {}
    );
    return () => {
      cancelled = true;
      if (objectUrl) URL.revokeObjectURL(objectUrl);
      setSrc(null);
    };
  }, [rom]);

  return (
    <div className="cover-frame">
      {src ? <img src={src} alt={rom.title} className="cover" /> : <CoverPlaceholder rom={rom} />}
    </div>
  );
}

// Platform families pick the badge/glow accent; anything unrecognised uses the default cyan.
const PLATFORM_FAMILIES = [
  ["nintendo", /\b(nes|snes|nintendo|game boy)\b/i],
  ["sega", /\bsega\b/i],
  ["sony", /\bsony\b/i],
  ["atari", /\batari\b/i]
];

export function platformFamily(platform) {
  const match = PLATFORM_FAMILIES.find(([, pattern]) => pattern.test(platform || ""));
  return match ? match[0] : "other";
}

// Decorative stand-in "cartridge label" shown until (or instead of) real box art.
function CoverPlaceholder({ rom }) {
  const initial = (rom.title || "?").trim().charAt(0).toUpperCase() || "?";
  return (
    <div className="cover-placeholder" aria-hidden="true">
      <span className="cover-initial">{initial}</span>
      <span className="cover-ext">{rom.extension || "ROM"}</span>
    </div>
  );
}

function RomCard({ rom, onScrape, onDownload }) {
  const family = platformFamily(rom.platform);
  return (
    <li className="rom-card" data-family={family}>
      <CoverImage rom={rom} />
      <div className="rom-body">
        <h3 className="rom-title" title={rom.title}>{rom.title}</h3>
        <span className="platform-badge">{rom.platform || "Unknown"}</span>
      </div>
      <div className="rom-actions">
        <button className="primary" onClick={() => onDownload(rom)}>Download</button>
        {onScrape ? <button className="ghost" onClick={() => onScrape(rom.id)}>Scrape Cover</button> : null}
      </div>
    </li>
  );
}

const SKELETON_CARDS = 8;

function RomList({ romPage, loading, query, platforms, onQuery, onScrape, onDownload }) {
  const showSkeleton = loading && romPage.results.length === 0;
  return (
    <section className="library" aria-busy={loading}>
      <div className="library-head">
        <h2>ROM Library</h2>
        <LibraryFilters query={query} platforms={platforms} onChange={onQuery} />
      </div>
      {showSkeleton ? (
        <ul className="rom-grid" aria-label="Loading ROMs">
          {Array.from({ length: SKELETON_CARDS }, (_, index) => (
            <li key={index} className="rom-card skeleton" aria-hidden="true" />
          ))}
        </ul>
      ) : null}
      {!loading && romPage.results.length === 0 ? (
        <div className="empty-state">
          <p className="empty-title">No ROMs found.</p>
          <p className="muted">Try a different search or platform.</p>
        </div>
      ) : null}
      {romPage.results.length > 0 ? (
        <ul className="rom-grid" aria-label="ROMs">
          {romPage.results.map((rom) => (
            <RomCard key={rom.id} rom={rom} onScrape={onScrape} onDownload={onDownload} />
          ))}
        </ul>
      ) : null}
      <Pagination romPage={romPage} page={query.page} onPage={(page) => onQuery({ ...query, page })} />
    </section>
  );
}

const SUPER_ADMIN = "super_admin";

function SessionBar({ me, onRefresh, onLogout }) {
  return (
    <div className="session">
      {me ? (
        <p className="muted session-user">
          Signed in as <strong>{me.username}</strong>{" "}
          <span className={`role-badge${me.role === SUPER_ADMIN ? " admin" : ""}`}>{me.role || "no role"}</span>
        </p>
      ) : (
        <p className="muted">Loading account…</p>
      )}
      <div className="row">
        <button className="ghost" onClick={onRefresh}>Refresh</button>
        <button className="ghost" onClick={onLogout}>Logout</button>
      </div>
    </div>
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
  const [loading, setLoading] = useState(initial.authed);

  // Only the newest request may update the list, so a slow response for an old filter
  // cannot overwrite the results of a newer one.
  const loadRoms = useCallback(async () => {
    const requestId = ++latestRequest.current;
    setLoading(true);
    try {
      const [data, platformList] = await Promise.all([api.listRoms(query), api.listPlatforms()]);
      if (requestId !== latestRequest.current) return;
      setRomPage(data);
      setPlatforms(platformList);
      setError("");
    } catch (err) {
      if (requestId !== latestRequest.current) return;
      setError(String(err.message || err));
    } finally {
      if (requestId === latestRequest.current) setLoading(false);
    }
  }, [query]);

  useEffect(() => {
    if (authed) {
      api.me().then(setMe, () => logout());
    }
  }, [authed]);

  useEffect(() => {
    if (authed) loadRoms();
    else setLoading(false);
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

  // Write controls are only rendered for super_admin, and not until the role is known.
  const canWrite = me?.role === SUPER_ADMIN;

  return (
    <>
      <header className="topbar">
        <h1 className="logo">
          bird<span>ROMs</span>
        </h1>
        {authed ? <SessionBar me={me} onRefresh={loadRoms} onLogout={logout} /> : null}
      </header>
      <main className={`container${authed ? "" : " container-auth"}`}>
        {error ? <p className="error banner" role="alert">{error}</p> : null}
        {!authed ? <AuthPanel config={authConfig} onAuthed={() => setAuthed(true)} /> : null}
        {authed ? (
          <>
            {canWrite ? <GlobalDropzone onUploaded={loadRoms} /> : null}
            {canWrite ? <UploadPanel onUploaded={loadRoms} /> : null}
            <RomList
              romPage={romPage}
              loading={loading}
              query={query}
              platforms={platforms}
              onQuery={setQuery}
              onScrape={canWrite ? async (id) => { await api.scrapeCover(id); await loadRoms(); } : null}
              onDownload={downloadRom}
            />
          </>
        ) : null}
      </main>
    </>
  );
}
