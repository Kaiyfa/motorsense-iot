// Shared fetch helper and the page error notice (no page-specific state).

export function showError(message) {
  const box = document.getElementById('error-notice');
  if (!box) return;
  if (message) {
    box.textContent = message;
    box.hidden = false;
  } else {
    box.hidden = true;
  }
}

// Fetch JSON; raise readable errors (HTTP status, expired login, network).
export async function getJSON(url, timeoutMs = 8000) {
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), timeoutMs);
  let response;
  try {
    response = await fetch(url, { headers: { Accept: 'application/json' }, signal: controller.signal,
      credentials: 'same-origin' });
  } catch (err) {
    throw new Error(err.name === 'AbortError' ? `no answer from ${url} within ${timeoutMs / 1000} s`
      : `network error while loading ${url}`);
  } finally {
    clearTimeout(timer);
  }
  if (response.redirected && response.url.includes('/login')) {
    throw new Error('your login session has expired; reload the page to log in again');
  }
  if (!response.ok) throw new Error(`HTTP ${response.status} from ${url}`);
  const type = response.headers.get('content-type') || '';
  if (!type.includes('application/json')) throw new Error(`unexpected response from ${url}`);
  return response.json();
}
