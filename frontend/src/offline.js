// fetch() rejects (with a TypeError) only when no response arrived at all: the device is offline, the server is
// unreachable, or the request was blocked. HTTP error statuses are not network errors.
export const OFFLINE_MESSAGE = "You're offline. birdROMs needs a connection to load and download ROMs.";

export function offlineError() {
  const error = new Error(OFFLINE_MESSAGE);
  error.isNetworkError = true;
  return error;
}

export function isNetworkError(err) {
  return Boolean(err && err.isNetworkError);
}
