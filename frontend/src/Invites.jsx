import { useEffect, useState } from "react";
import { api } from "./api/client";

const INVITE_PREFIX = "/invite/";
export const INVITE_UNAVAILABLE = "This invite link is invalid, expired or already used.";
export const INVITES_OFF = "Invite links are not available on this server.";

// An invite link is `/invite/<token>`. The token stays in the path and is only ever POSTed, never put in a query string.
export function inviteTokenFromPath(pathname = window.location.pathname) {
  if (!pathname.startsWith(INVITE_PREFIX)) return null;
  const raw = pathname.slice(INVITE_PREFIX.length).replace(/\/$/, "");
  try {
    return decodeURIComponent(raw);
  } catch {
    return raw;
  }
}

// What a friend sees at `/invite/<token>`: pick a username and password; success signs them in with a session.
// `invites` is the server's auth-config flag: null while unknown, false when invites cannot be used (no check is made).
export function InviteAcceptPanel({ token, invites = true, onAccepted, onDone }) {
  const [state, setState] = useState("checking"); // checking | ready | unavailable
  const [username, setUsername] = useState("");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    if (invites !== true) return undefined;
    let cancelled = false;
    api.checkInvite(token).then(
      () => {
        if (!cancelled) setState("ready");
      },
      () => {
        // Unknown, expired, used and revoked all look the same, and so does anything else that goes wrong.
        if (!cancelled) setState("unavailable");
      }
    );
    return () => {
      cancelled = true;
    };
  }, [token, invites]);

  async function handleSubmit(event) {
    event.preventDefault();
    if (busy) return;
    setBusy(true);
    try {
      await api.acceptInvite({ token, username, email, password });
      setError("");
      onAccepted();
    } catch (err) {
      if (err.status === 404) setState("unavailable");
      else setError(String(err.message || err));
    } finally {
      setBusy(false);
    }
  }

  return (
    <section className="card auth-card">
      <p className="eyebrow" aria-hidden="true">Player 2 joined?</p>
      <h2>Join birdROMs</h2>
      {invites === false ? (
        <div className="stack">
          <p className="error" role="alert">{INVITES_OFF}</p>
          <button className="ghost" onClick={onDone}>Go to login</button>
        </div>
      ) : null}
      {invites !== false && state === "checking" ? <p className="muted loading-text">Checking your invite…</p> : null}
      {invites !== false && state === "unavailable" ? (
        <div className="stack">
          <p className="error" role="alert">{INVITE_UNAVAILABLE}</p>
          <button className="ghost" onClick={onDone}>Go to login</button>
        </div>
      ) : null}
      {invites !== false && state === "ready" ? (
        <form className="stack" onSubmit={handleSubmit}>
          <p className="muted">Choose a username and password to create your account.</p>
          <input
            aria-label="Username"
            placeholder="Username"
            autoComplete="username"
            value={username}
            onChange={(e) => setUsername(e.target.value)}
          />
          <input
            aria-label="Email"
            placeholder="Email (optional)"
            type="email"
            autoComplete="email"
            value={email}
            onChange={(e) => setEmail(e.target.value)}
          />
          <input
            aria-label="Password"
            placeholder="Password"
            type="password"
            autoComplete="new-password"
            value={password}
            onChange={(e) => setPassword(e.target.value)}
          />
          {error ? <p className="error" role="alert">{error}</p> : null}
          <div className="row">
            <button type="submit" className="primary" disabled={busy}>
              {busy ? "Creating…" : "Create account"}
            </button>
          </div>
        </form>
      ) : null}
    </section>
  );
}

// A short admin-only form on the Library view. The link it returns is shown once and is not recoverable.
export function InviteCreator() {
  const [role, setRole] = useState("readonly");
  const [label, setLabel] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [created, setCreated] = useState(null);
  const [copied, setCopied] = useState(false);

  async function handleCreate(event) {
    event.preventDefault();
    if (busy) return;
    setBusy(true);
    setCopied(false);
    try {
      const invite = await api.createInvite({ role, label: label.trim() });
      setCreated(invite);
      setLabel("");
      setError("");
    } catch (err) {
      setCreated(null);
      setError(
        err.status === 404 ? "Invites need local login, which is turned off on this server." : String(err.message || err)
      );
    } finally {
      setBusy(false);
    }
  }

  async function copy() {
    try {
      await navigator.clipboard.writeText(created.url);
      setCopied(true);
    } catch {
      setCopied(false); // the link is selectable in the field, so copying by hand still works
    }
  }

  return (
    <details className="card invite-card">
      <summary>Invite a friend</summary>
      <form className="stack" onSubmit={handleCreate}>
        <p className="muted">Make a one-time link that lets someone create their own account. It expires on its own.</p>
        <div className="row">
          <select aria-label="Invite role" value={role} onChange={(e) => setRole(e.target.value)}>
            <option value="readonly">Read-only (browse and download)</option>
            <option value="member">Member (browse, download and upload)</option>
            <option value="super_admin">Admin (also edit, delete and manage the library)</option>
          </select>
          <input
            aria-label="Invite label"
            placeholder="Label, e.g. their name (optional)"
            maxLength={100}
            value={label}
            onChange={(e) => setLabel(e.target.value)}
          />
          <button type="submit" className="primary" disabled={busy}>
            {busy ? "Creating…" : "Create invite link"}
          </button>
        </div>
        {error ? <p className="error" role="alert">{error}</p> : null}
        {created ? (
          <div className="stack" role="status">
            <p className="muted">Copy this link now: it will not be shown again.</p>
            <div className="row">
              <input aria-label="Invite link" readOnly value={created.url} onFocus={(e) => e.target.select()} />
              <button type="button" className="ghost" onClick={copy}>{copied ? "Copied" : "Copy"}</button>
            </div>
          </div>
        ) : null}
      </form>
    </details>
  );
}
