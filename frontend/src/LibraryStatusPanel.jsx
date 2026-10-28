import { useCallback, useEffect, useRef, useState } from "react";
import { api } from "./api/client";

export const POLL_INTERVAL_MS = 5000;

function formatTime(iso) {
  return iso ? new Date(iso).toLocaleString() : "";
}

// Admin-only card on the Library view: last scan summary, rescan controls, read-only notice.
export default function LibraryStatusPanel({ me }) {
  const isAdmin = me?.role === "super_admin";
  const [info, setInfo] = useState(null);
  const [starting, setStarting] = useState(false);
  const [error, setError] = useState("");
  const mounted = useRef(true);

  const refresh = useCallback(async () => {
    try {
      const next = await api.libraryStatus();
      if (mounted.current) setInfo(next);
    } catch (err) {
      if (mounted.current) setError(String(err.message || err));
    }
  }, []);

  useEffect(() => {
    mounted.current = true;
    return () => {
      mounted.current = false;
    };
  }, []);

  useEffect(() => {
    if (isAdmin) refresh();
  }, [isAdmin, refresh]);

  const running = Boolean(info?.running) || starting;

  useEffect(() => {
    if (!isAdmin || !info?.running) return undefined;
    const timer = setInterval(refresh, POLL_INTERVAL_MS);
    return () => clearInterval(timer);
  }, [isAdmin, info?.running, refresh]);

  if (!isAdmin) return null;

  async function rescan(acceptRemovals) {
    setError("");
    setStarting(true);
    try {
      await api.rescanLibrary({ acceptRemovals });
      if (mounted.current) setInfo((current) => ({ ...current, running: true }));
    } catch (err) {
      if (mounted.current) setError(String(err.message || err));
      await refresh();
    } finally {
      if (mounted.current) setStarting(false);
    }
  }

  const scan = info?.last_scan;
  const unknown = scan?.unknown_folders || [];

  return (
    <section className="card library-status" aria-label="Library scan">
      <div className="library-status-head">
        <h2>Library</h2>
        <button className="ghost" disabled={running} onClick={() => rescan(false)}>
          {running ? "Scanning…" : "Rescan now"}
        </button>
      </div>
      {info && !info.writable ? (
        <p className="muted">Read-only library: uploads and cover saving are off.</p>
      ) : null}
      {info && !scan ? <p className="muted">Never scanned.</p> : null}
      {scan ? (
        <>
          <p className="muted library-status-line">
            Last scan: <time dateTime={scan.finished_at || scan.started_at}>{formatTime(scan.finished_at || scan.started_at)}</time>
          </p>
          <ul className="library-status-counts">
            <li>{scan.added} added</li>
            <li>{scan.changed} changed</li>
            <li>{scan.missing} missing</li>
          </ul>
          {scan.state === "aborted" ? (
            <div className="library-status-aborted">
              <p className="error">{scan.message}</p>
              <button className="primary" disabled={running} onClick={() => rescan(true)}>Accept removals</button>
            </div>
          ) : null}
          {unknown.length > 0 ? <p className="muted">Unknown folders: {unknown.join(", ")}</p> : null}
        </>
      ) : null}
      {error ? <p className="error" role="alert">{error}</p> : null}
    </section>
  );
}
