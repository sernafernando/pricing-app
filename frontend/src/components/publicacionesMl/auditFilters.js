/**
 * Productos' audit filter on Publicaciones ML: who changed the linked product, what kind of change and when. The URL
 * keys are Productos' (`audit_usuarios`, `audit_tipos`, `audit_desde`, `audit_hasta`); what each asks the backend
 * lives in `usePublicacionesMLFilters`. The users and kinds come from `GET /auditoria/usuarios` and
 * `GET /auditoria/tipos-accion`, as in Productos.
 */
export const EMPTY_AUDIT_FILTERS = { audit_usuarios: [], audit_tipos: [], audit_desde: '', audit_hasta: '' };

/** Productos' label of a kind: `modificar_precio_clasica` -> "Modificar Precio Clasica". */
export const kindLabel = (kind) =>
  kind
    .split('_')
    .map((part) => part.charAt(0).toUpperCase() + part.slice(1))
    .join(' ');

/** `2026-10-20T09:00` (or a bare date) -> `20/10/2026 09:00`. */
const momentLabel = (value) => {
  const [day, hour] = value.split(/[T ]/);
  const [y, m, d] = day.split('-');
  return hour ? `${d}/${m}/${y} ${hour.slice(0, 5)}` : `${d}/${m}/${y}`;
};

export const hasAuditFilter = (filters) =>
  filters.audit_usuarios.length > 0 || filters.audit_tipos.length > 0 || Boolean(filters.audit_desde || filters.audit_hasta);

/** One chip per active value, and the `setFilters` update that clears it. `usersById` names the users. */
export function activeAuditChips(filters, usersById) {
  const without = (key, value) => ({ [key]: filters[key].filter((v) => v !== value) });
  return [
    ...filters.audit_usuarios.map((id) => ({
      id: `u${id}`,
      label: `Usuario: ${usersById[id] ?? `#${id}`}`,
      remove: without('audit_usuarios', id),
    })),
    ...filters.audit_tipos.map((kind) => ({
      id: `t${kind}`,
      label: `Tipo: ${kindLabel(kind)}`,
      remove: without('audit_tipos', kind),
    })),
    ...(filters.audit_desde
      ? [{ id: 'desde', label: `Desde: ${momentLabel(filters.audit_desde)}`, remove: { audit_desde: '' } }]
      : []),
    ...(filters.audit_hasta
      ? [{ id: 'hasta', label: `Hasta: ${momentLabel(filters.audit_hasta)}`, remove: { audit_hasta: '' } }]
      : []),
  ];
}
