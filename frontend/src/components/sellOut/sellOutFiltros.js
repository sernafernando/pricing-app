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
  filtro: '',
};

/** The `GET /sell-out/campanas` params of the filters: only the ones set, `q` trimmed, `grupo_id` a number. */
export function paramsDeFiltros({ q, estado, tipo, moneda, marca, grupo_id, desde, hasta }) {
  const params = { q: q?.trim(), estado, tipo, moneda, marca, grupo_id: grupo_id ? Number(grupo_id) : '', desde, hasta };
  return Object.fromEntries(Object.entries(params).filter(([, value]) => Boolean(value)));
}
