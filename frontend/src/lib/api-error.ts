/**
 * Turning an API error into something safe to render.
 *
 * FastAPI's `detail` is a plain string for `HTTPException`, but for a 422 it is an array of
 * validation objects (`{ type, loc, msg, input, ctx }`). Components were assigning `detail`
 * straight into React state and rendering it, so any 422 crashed the component with React error
 * #31 — "objects are not valid as a React child" — instead of showing the user what was wrong.
 */

interface ValidationDetail {
  msg?: unknown;
  loc?: unknown;
}

function isValidationDetail(value: unknown): value is ValidationDetail {
  return typeof value === "object" && value !== null && "msg" in value;
}

/** The `detail` of an error response, whatever shape it arrived in. */
function extractDetail(err: unknown): unknown {
  if (typeof err !== "object" || err === null) return undefined;
  const response = (err as { response?: { data?: { detail?: unknown } } }).response;
  return response?.data?.detail;
}

/**
 * A human-readable message for `err`, falling back to `fallback` when there is nothing useful.
 *
 * Always returns a string, so the result is safe to render directly.
 */
export function errorDetailText(err: unknown, fallback: string): string {
  const detail = extractDetail(err);

  if (typeof detail === "string" && detail.trim()) return detail;

  if (Array.isArray(detail)) {
    const messages = detail
      .filter(isValidationDetail)
      .map((entry) => {
        const field = Array.isArray(entry.loc) ? entry.loc[entry.loc.length - 1] : undefined;
        const msg = typeof entry.msg === "string" ? entry.msg : "";
        if (!msg) return "";
        // "quantity_required: Input should be greater than 0" reads better than the bare message,
        // which on its own gives no clue which field was rejected.
        return field !== undefined && field !== "body" ? `${String(field)}: ${msg}` : msg;
      })
      .filter(Boolean);

    if (messages.length) return messages.join("; ");
  }

  return fallback;
}
