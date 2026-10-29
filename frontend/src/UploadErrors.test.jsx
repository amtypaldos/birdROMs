import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { act, cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import App from "./App";

// Uses the real API client with a stubbed fetch, so the server's real error shapes are exercised.
const SENTENCE = "Super Mario World (U).smc is already in the library.";

function json(body, status = 200) {
  return { ok: status < 400, status, json: () => Promise.resolve(body), text: () => Promise.resolve(JSON.stringify(body)) };
}

beforeEach(() => {
  // Signed in by the session cookie (the stub answers /auth/me/); unsafe requests echo the CSRF cookie.
  document.cookie = "csrftoken=csrf-tok; path=/";
  vi.stubGlobal("fetch", vi.fn((url, options = {}) => {
    if (url.endsWith("/auth/me/")) return Promise.resolve(json({ id: 1, username: "root", email: "", role: "super_admin" }));
    if (url.endsWith("/auth/config/")) return Promise.resolve(json({ methods: ["local"] }));
    if (url.includes("/library/status/")) {
      return Promise.resolve(json({ backend: "local", writable: true, write_covers: true, running: false, last_scan: null }));
    }
    if (url.includes("/roms/platforms/")) return Promise.resolve(json([]));
    if (url.endsWith("/roms/") && options.method === "POST") return Promise.resolve(json({ file: [SENTENCE] }, 400));
    return Promise.resolve(json({ count: 0, next: null, previous: null, results: [] }));
  }));
});

afterEach(() => {
  cleanup();
  document.cookie = "csrftoken=; path=/; expires=Thu, 01 Jan 1970 00:00:00 GMT";
  vi.unstubAllGlobals();
});

describe("upload refusals with the real client", () => {
  it("shows the sentence in the upload panel", async () => {
    render(<App />);

    fireEvent.change(await screen.findByLabelText("ROM file"), { target: { files: [new File(["x"], "smw.smc")] } });
    fireEvent.click(screen.getByRole("button", { name: "Upload" }));

    expect(await screen.findByText(SENTENCE)).toBeInTheDocument();
    const upload = fetch.mock.calls.find(([url, options]) => url.endsWith("/roms/") && options?.method === "POST");
    expect(upload[1].credentials).toBe("include");
    expect(upload[1].headers["X-CSRFToken"]).toBe("csrf-tok");
    expect(upload[1].headers.Authorization).toBeUndefined();
  });

  it("shows the sentence in the bulk drop queue", async () => {
    render(<App />);
    await screen.findByLabelText("ROM file");

    const file = new File(["x"], "smw.smc");
    const data = { dataTransfer: { types: ["Files"], files: [file], items: [{ kind: "file" }] } };
    fireEvent.dragEnter(document.body, data);
    await act(async () => { fireEvent.drop(document.body, data); });

    await waitFor(() => expect(screen.getByText(`Failed: ${SENTENCE}`)).toBeInTheDocument());
  });
});
