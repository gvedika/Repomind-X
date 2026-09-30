const { setTimeout: sleep } = require("node:timers/promises");

/**
 * Re-run an async operation with exponential backoff until it succeeds or attempts run out.
 */
async function withRetry(operation, attempts = 3, baseDelayMs = 100) {
  let lastError;
  for (let attempt = 0; attempt < attempts; attempt += 1) {
    try {
      return await operation(attempt);
    } catch (error) {
      lastError = error;
      await sleep(baseDelayMs * 2 ** attempt);
    }
  }
  throw lastError;
}

function chunk(items, size) {
  const out = [];
  for (let i = 0; i < items.length; i += size) out.push(items.slice(i, i + size));
  return out;
}

module.exports = { withRetry, chunk };
