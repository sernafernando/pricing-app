/**
 * The ads of Métricas ML: the small derivations the screen makes over the board's `kpis.ads` block (backend
 * `KpiAds`). Nothing here decides what is subtracted -- the API does, and
 * says what it applied.
 */
/** The three positions of the toggle, in the order the control shows them. */
export const ADS_MODE_OPTIONS = [
  { value: 'off', label: 'Sin publicidad' },
  { value: 'mla', label: 'Restar Ads de publicaciones' },
  { value: 'todo', label: 'Restar toda la publicidad' },
];

export const ADS_MODE_HINTS = {
  off: 'No se resta publicidad de Total Gauss ni del markup.',
  mla: 'Resta del Total Gauss y del markup solo los Ads atribuidos a cada publicación.',
  todo: 'Resta del Total Gauss y del markup los Ads de cada publicación y además Display, Brand Ads y Ads sin producto.',
};

/** What the banner says was subtracted, by the position the API APPLIED. */
export const ADS_APPLIED_LABELS = {
  mla: 'Ads de publicaciones',
  todo: 'Ads de publicaciones, sin producto y cuenta',
};

/**
 * The explanation for a position the view could not honor: a filtered or
 * PM-scoped board cannot carry account-level spend, so "todo" is applied as
 * "mla". `null` while the applied position is the requested one.
 */
export function adsModeNotice(ads) {
  if (!ads || ads.requested === ads.applied) return null;
  return {
    message: 'Con filtros solo se restan los Ads de publicaciones',
    chip: `Aplicado: ${ADS_APPLIED_LABELS[ads.applied]}`,
  };
}

/** The figure before ads were subtracted: the adjusted `value` plus what came off it. */
export function originalAmount(value, subtracted) {
  if (value === null || value === undefined) return null;
  return Math.round((Number(value) + Number(subtracted || 0)) * 100) / 100;
}

/** The board's query for a position: absent at `off`, so the request is exactly the one made without ads. */
export function adsRequestParams(position) {
  return position && position !== 'off' ? { publicidad: position } : {};
}

const dayMonth = (iso) => `${iso.slice(8, 10)}/${iso.slice(5, 7)}`;
const days = (n) => (n === 1 ? '1 día' : `${n} días`);

/**
 * What the ads ledger admits about the period, for the chip of the ads block. A missing day is NOT zero spend:
 * it says so, instead of letting a short ledger read as a cheap month. `null` without coverage.
 */
export function adsCoverageNote(coverage) {
  if (!coverage) return null;
  if (!coverage.available) return { tone: 'warn', text: 'Sin datos de Ads para el período' };
  const missing = coverage.missing_days.length;
  const mismatch = coverage.mismatch_days.length;
  // Available without a date cannot vouch for the whole period: never a green "ok".
  if (!coverage.data_through) return { tone: 'warn', text: 'Datos de Ads sin fecha de corte' };
  const parts = [`Datos de Ads hasta el ${dayMonth(coverage.data_through)}`];
  if (missing) parts.push(missing === 1 ? 'falta 1 día' : `faltan ${missing} días`);
  if (mismatch) parts.push(`${days(mismatch)} con diferencias`);
  return { tone: missing || mismatch ? 'warn' : 'ok', text: parts.join(' · ') };
}
