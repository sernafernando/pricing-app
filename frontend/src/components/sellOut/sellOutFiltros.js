/** The Sell out tab's list filters (campanas-sistema S3): `filtro` is the DateRangeFilter preset, not sent. */
export const FILTROS_CAMPANAS_VACIOS = {
  q: '',
  estado: '',
  tipo: '',
  moneda: '',
  marca: '',
  grupo_id: '',
  desde: '',
  hasta: '',
  programa: '', // '' every program, 'sin' the campaigns without one, else a program id
  filtro: '',
};

/** The Programa select's value for the campaigns without a program. */
export const SIN_PROGRAMA = 'sin';

/**
 * The `GET /sell-out/campanas` params of the filters: only the ones set, `q` trimmed, `grupo_id` a number, and the
 * program as `programa_id` (a number) or `sin_programa: true`.
 */
export function paramsDeFiltros({ q, estado, tipo, moneda, marca, grupo_id, desde, hasta, programa }) {
  const params = { q: q?.trim(), estado, tipo, moneda, marca, grupo_id: grupo_id ? Number(grupo_id) : '', desde, hasta };
  if (programa === SIN_PROGRAMA) params.sin_programa = true;
  else if (programa) params.programa_id = Number(programa);
  return Object.fromEntries(Object.entries(params).filter(([, value]) => Boolean(value)));
}
