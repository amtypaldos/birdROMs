import { useEffect, useState } from "react";
import { api } from "./api/client";

function megabytes(bytes) {
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
}

function InstallSteps({ isSwitch }) {
  return (
    <ol className="handheld-install-steps" aria-label="Installation steps">
      {isSwitch ? <>
        <li>
          <span className="handheld-step-number" aria-hidden="true">01</span>
          <h4>Download &amp; extract</h4>
          <p>Get the ZIP from this server using the button above. Extract it to your SD card&apos;s root, keeping the <code>switch</code> folder structure.</p>
        </li>
        <li>
          <span className="handheld-step-number" aria-hidden="true">02</span>
          <h4>Check the app folder</h4>
          <p>These files belong together on your card:</p>
          <div className="handheld-file-paths"><code>/switch/birdroms/birdroms.nro</code><code>/switch/birdroms/server.json</code><code>/switch/birdroms/version.json</code></div>
          <p>Keep an existing <code>config.json</code> when replacing app files.</p>
        </li>
        <li>
          <span className="handheld-step-number" aria-hidden="true">03</span>
          <h4>Open Homebrew Menu</h4>
          <p>Launch <strong>birdROMs</strong> under Atmosphère. Full-memory mode (title override) is recommended. Then link your account below.</p>
        </li>
      </> : <>
        <li>
          <span className="handheld-step-number" aria-hidden="true">01</span>
          <h4>Download the app</h4>
          <p>Use the download button above to get <code>birdROMs.muxapp</code> from this server. Keep the file as it is; don&apos;t unzip it.</p>
        </li>
        <li>
          <span className="handheld-step-number" aria-hidden="true">02</span>
          <h4>Copy to your SD card</h4>
          <p>Put the file in <code>ARCHIVE</code> at the top of the card; create that folder if needed. With two cards, use the one holding your games. Put the card back.</p>
        </li>
        <li>
          <span className="handheld-step-number" aria-hidden="true">03</span>
          <h4>Install &amp; open</h4>
          <p>Open <strong>Applications → Archive Manager → birdROMs</strong> and press <strong>A</strong>. When installation finishes, launch <strong>Applications → birdROMs</strong>.</p>
        </li>
      </>}
    </ol>
  );
}

// Keep platform instructions aligned with the handheld repository's install guides.
export default function HandheldView() {
  const [platform, setPlatform] = useState("muos");
  const [info, setInfo] = useState(null);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const [code, setCode] = useState("");
  const [pairing, setPairing] = useState(false);
  const [pairMessage, setPairMessage] = useState("");
  const [pairError, setPairError] = useState("");
  const [retry, setRetry] = useState(0);
  const isSwitch = platform === "switch";

  useEffect(() => {
    let cancelled = false;
    setInfo(null);
    setError("");
    const request = platform === "switch" ? api.handheldInfo("switch") : api.handheldInfo();
    request.then(
      (next) => !cancelled && setInfo(next),
      (err) => !cancelled && setError(String(err.message || err))
    );
    return () => { cancelled = true; };
  }, [platform, retry]);

  async function approve(event) {
    event.preventDefault();
    const trimmed = code.trim();
    if (!trimmed || pairing) return;
    setPairing(true);
    setPairMessage("");
    setPairError("");
    try {
      await api.approveDevice(trimmed);
      setPairMessage("Device approved — it will connect shortly.");
      setCode("");
    } catch (err) {
      setPairError(String(err.message || err));
    } finally {
      setPairing(false);
    }
  }

  async function download() {
    setBusy(true);
    setError("");
    try {
      if (isSwitch) await api.downloadHandheldApp("switch");
      else await api.downloadHandheldApp();
    } catch (err) {
      setError(String(err.message || err));
    } finally {
      setBusy(false);
    }
  }

  const date = info?.published_at ? new Date(info.published_at) : null;
  const published = date && !Number.isNaN(date.getTime()) ? date.toLocaleDateString() : null;

  return (
    <section className="handheld-view" aria-label="Handheld app">
      <header className="handheld-heading">
        <h2>Get birdROMs on your handheld</h2>
        <p className="muted">Browse your library, choose your games, and download them straight to your device.</p>
      </header>

      <div className="handheld-platforms" role="group" aria-label="Choose your device">
        <button className={`handheld-platform ${!isSwitch ? "handheld-platform-active" : ""}`} aria-pressed={!isSwitch} disabled={busy} onClick={() => setPlatform("muos")}>
          <span><strong>muOS handheld</strong><span>Anbernic RG40XX, RG35XX &amp; similar</span></span>
          <span className="handheld-platform-indicator" aria-hidden="true">{!isSwitch ? "Selected" : ""}</span>
        </button>
        <button className={`handheld-platform ${isSwitch ? "handheld-platform-active" : ""}`} aria-pressed={isSwitch} disabled={busy} onClick={() => setPlatform("switch")}>
          <span><strong>Nintendo Switch</strong><span>Atmosphère · Homebrew Menu</span></span>
          <span className="handheld-platform-indicator" aria-hidden="true">{isSwitch ? "Selected" : ""}</span>
        </button>
      </div>

      <section className="handheld-release" aria-label={`${isSwitch ? "Switch" : "muOS"} app download`}>
        <div className="handheld-release-copy">
          <p className="handheld-package-type">{isSwitch ? "Nintendo Switch homebrew" : "muOS app package"}</p>
          <h3>{isSwitch ? "Download for RetroArch" : "Download for your handheld"}</h3>
          <p>{isSwitch ? "Download ROMs to your SD card for RetroArch. Runs as a standard .nro application." : "Install once with Archive Manager. Pair with this server and download games from your handheld."}</p>
        </div>
        <div className="handheld-release-download" aria-busy={busy || (!info && !error)}>
          {!info && !error ? <p className="muted">Checking this server for the latest app…</p> : null}
          {info?.available ? <>
            <span className="handheld-release-state">Ready to install</span>
            <dl className="handheld-release-meta">
              {info.version ? <div><dt>Version</dt><dd>{info.version}</dd></div> : null}
              {Number.isFinite(info.size) ? <div><dt>Size</dt><dd>{megabytes(info.size)}</dd></div> : null}
              {published ? <div><dt>Published</dt><dd>{published}</dd></div> : null}
            </dl>
            <button className="primary handheld-download-button" disabled={busy} onClick={download}>{busy ? "Downloading…" : `Download ${info.filename}`}</button>
            <span className="handheld-download-note">Prepared for this server · Pair after opening</span>
          </> : null}
          {info && !info.available ? <div className="handheld-unavailable"><strong>Not published yet</strong><p>The {isSwitch ? "Switch" : "muOS"} app has not been published yet. Ask whoever runs this server to publish a package.</p></div> : null}
          {error ? <div className="handheld-download-error"><p className="error" role="alert">{error}</p>{!info ? <button onClick={() => setRetry((value) => value + 1)}>Check again</button> : null}</div> : null}
        </div>
      </section>

      <section className="handheld-install" aria-labelledby="handheld-install-title">
        <div className="handheld-section-heading"><h3 id="handheld-install-title">Install in three steps</h3><span className="muted">{isSwitch ? "Nintendo Switch" : "muOS"}</span></div>
        <InstallSteps isSwitch={isSwitch} />
        {isSwitch ? <details className="handheld-transfer-note"><summary>Prefer to transfer without removing the SD card?</summary><p>Use your usual DBI or FTP setup to copy the same <code>switch/birdroms/</code> folder onto the card. Keep <code>birdroms.nro</code> and <code>server.json</code> together, and preserve your existing <code>config.json</code>.</p></details> : null}
      </section>

      <section className="handheld-link" aria-labelledby="handheld-link-title">
        <div className="handheld-link-copy">
          <h3 id="handheld-link-title">Link your account</h3>
          <p>Open birdROMs on your device. Scan its QR code with your phone, sign in, and approve. Or type the code shown on your device here.</p>
          {isSwitch ? <p className="handheld-privacy-note"><code>server.json</code> contains this server&apos;s address, not a device token. Your <code>config.json</code> is created after you approve pairing.</p> : null}
        </div>
        <form className="handheld-pair" onSubmit={approve} aria-label="Approve a device by code">
          <label htmlFor="handheld-pair-code">Code shown on your device</label>
          <div className="handheld-pair-controls">
            <input id="handheld-pair-code" type="text" value={code} onChange={(event) => setCode(event.target.value)} autoComplete="off" autoCapitalize="characters" spellCheck={false} aria-label="Pairing code" placeholder="ABC123" />
            <button className="primary" type="submit" aria-label="Approve device" disabled={pairing}>{pairing ? "Approving…" : "Approve device"}</button>
          </div>
          {pairMessage ? <p role="status">{pairMessage}</p> : null}
          {pairError ? <p className="error" role="alert">{pairError}</p> : null}
        </form>
      </section>

      <div className="handheld-reference-grid">
        <section className="handheld-reference" aria-labelledby="handheld-controls-title">
          <h3 id="handheld-controls-title">Pick. Select. Download.</h3>
          <dl className="handheld-controls">
            <div><dt><kbd>D-pad</kbd>{isSwitch ? " / stick" : ""}</dt><dd>Navigate</dd></div>
            <div><dt><kbd>A</kbd> / <kbd>B</kbd></dt><dd>Select / back</dd></div>
            <div><dt><kbd>Y</kbd></dt><dd>Select all / none</dd></div>
            <div><dt><kbd>L</kbd> / <kbd>R</kbd></dt><dd>Previous / next page</dd></div>
            <div><dt><kbd>{isSwitch ? "+" : "Start"}</kbd></dt><dd>Download selected</dd></div>
            {isSwitch ? <div><dt><kbd>−</kbd></dt><dd>Exit</dd></div> : null}
          </dl>
          {isSwitch ? <p>ROMs go to <code>sdmc:/retroarch/roms/</code>, with a folder for each console. Press <kbd>X</kbd> on home to choose another base directory; edit platform folders in <code>config.json</code>. RetroArch can use your chosen layout.</p> : null}
        </section>
        <section className="handheld-reference" aria-labelledby="handheld-updates-title">
          <h3 id="handheld-updates-title">Updates come from your server</h3>
          {isSwitch ? <>
            <p>The app checks your paired server in the background on launch. When a newer version is available, it downloads the update and restarts when supported. Otherwise, reopen birdROMs from Homebrew Menu.</p>
            <p><kbd>B</kbd> skips an update for this launch. Press <kbd>ZL</kbd> on home to check again. Your pairing, ROM location and platform mappings stay in <code>config.json</code>.</p>
          </> : <p>The handheld updates itself from this server. When you next open birdROMs, it downloads the new version and restarts. You stay linked to your account.</p>}
          <p className="handheld-privacy-note">Already installed? Keep your configuration when copying app files. Your games stay where you put them.</p>
        </section>
      </div>
    </section>
  );
}
