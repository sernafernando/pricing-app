/**
 * The text to show for a failed API call: the app's error envelope (`error.message`), else a string `detail`, else
 * `fallback`. A `detail` that is not a string (FastAPI's list of field errors) never reaches the UI as an object.
 */
export function apiErrorMessage(err, fallback) {
  const data = err?.response?.data;
  if (data?.error?.message) return data.error.message;
  if (typeof data?.detail === 'string' && data.detail) return data.detail;
  return fallback;
}
