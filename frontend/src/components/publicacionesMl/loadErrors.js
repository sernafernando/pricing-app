/**
 * What to tell the operator when a request of the publications screen fails.
 * The status decides; `messages` carries what only this request knows: what a
 * 404 means, what the user may not see, and the generic failure.
 *
 * @param {unknown} error
 * @param {{ notFound: string, forbidden: string, fallback: string }} messages
 */
export function describeLoadError(error, { notFound, forbidden, fallback }) {
  const status = error?.response?.status;
  if (status === 404) return notFound;
  if (status === 422) return 'El identificador de la publicación no es válido.';
  if (status === 403) return forbidden;
  if (status === 503) return 'La consulta tardó demasiado. Reintentá en unos segundos.';
  return fallback;
}
