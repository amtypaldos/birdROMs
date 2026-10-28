import { useEffect, useState } from "react";
import { api } from "./api/client";

function megabytes(bytes) {
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
}

// Install guide for the muOS handheld app. Keep in step with docs/install.md in the handheld repo.
export default function HandheldView() {
  const [info, setInfo] = useState(null);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    let cancelled = false;
    api.handheldInfo().then(
      (next) => !cancelled && setInfo(next),
      (err) => !cancelled && setError(String(err.message || err))
    );
    return () => {
      cancelled = true;
    };
  }, []);

  async function download() {
    setBusy(true);
    try {
      await api.downloadHandheldApp();
      setError("");
    } catch (err) {
      setError(String(err.message || err));
    } finally {
      setBusy(false);
    }
  }

  return (
    <section className="card handheld-view" aria-label="Handheld app">
      <h2>Get birdROMs on your handheld</h2>
      <p className="muted">For handhelds running muOS (Anbernic RG40XX, RG35XX and friends). No computer skills needed.</p>
      {error ? <p className="error banner" role="alert">{error}</p> : null}
      {info && !info.available ? <p className="muted">The handheld app has not been published yet. Ask whoever runs this server.</p> : null}
      <ol className="handheld-steps">
        <li>
          <strong>Download the app.</strong>{" "}
          {info?.available ? (
            <>
              <button className="primary" disabled={busy} onClick={download}>Download {info.filename}</button>
              <span className="muted"> {megabytes(info.size)}, updated {new Date(info.published_at).toLocaleDateString()}</span>
            </>
          ) : null}
        </li>
        <li>
          <strong>Put it on the SD card.</strong> Take the SD card out of the handheld and plug it into your computer. Open the
          folder called <code>ARCHIVE</code> (make one at the very top of the card if there isn&apos;t one) and drop
          <code> birdROMs.muxapp</code> in it. Put the card back. If your handheld has two cards, use the one with your games.
        </li>
        <li>
          <strong>Install it on the handheld.</strong> Turn it on, open <em>Applications</em>, then <em>Archive Manager</em>.
          Pick <em>birdROMs</em> in the list and press A. Wait for it to finish.
        </li>
        <li>
          <strong>Open it.</strong> Go back to <em>Applications</em> and open <em>birdROMs</em>.
        </li>
        <li>
          <strong>Link it to your account.</strong> The handheld shows a QR code. Scan it with your phone, sign in, and press
          Approve. Then pick your games and press Start.
        </li>
      </ol>
      <h3>Updating</h3>
      <p>
        Download the new version here, copy it into <code>ARCHIVE</code> again (replace the old file), and run steps 3 and 4
        again. You stay linked to your account.
      </p>
    </section>
  );
}
