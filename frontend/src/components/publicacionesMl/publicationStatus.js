// Spanish labels + tones for a publication's status, as the ML publications
// store (`ml_items`) reports it — the owner's source of truth for status
// everywhere. Every status chip (Publicaciones ML, the promotions tree, the
// product info modal) reads this one map so the same status never reads two
// ways. `gone`, `never_existed` and `no_ml_data` are the backend's own
// statuses on top of ML's (`ml_publication_status_service.py`).
const PUBLICATION_STATUSES = {
  active: { label: 'Activa', tone: 'success' },
  paused: { label: 'Pausada', tone: 'warning' },
  closed: { label: 'Cerrada', tone: 'danger' },
  under_review: { label: 'En revisión', tone: 'info' },
  inactive: { label: 'Inactiva', tone: 'neutral' },
  gone: { label: 'Eliminada', tone: 'danger' },
  never_existed: { label: 'No existe en ML', tone: 'danger' },
  no_ml_data: { label: 'Sin datos de ML', tone: 'neutral' },
};

/** A deleted publication: it vanished from ML (`gone`), or ML keeps it as `inactive` or `closed` with `deleted`
 * among its `sub_status` reasons. The backend's `filters.deleted()` is the same rule. */
export function isDeletedPublication(status, subStatus) {
  return status === 'gone' || Boolean(subStatus?.includes('deleted'));
}

/** `{label, tone}` for a status; an unknown ML status is shown verbatim, no status is `null`. A deleted
 * publication (`isDeletedPublication`) reads "Eliminada". */
export function publicationStatusInfo(status, subStatus) {
  if (!status) return null;
  if (isDeletedPublication(status, subStatus)) return PUBLICATION_STATUSES.gone;
  return PUBLICATION_STATUSES[status] || { label: status, tone: 'neutral' };
}

/** ML's `sub_status` reasons (e.g. `paused_by_seller`) as a tooltip; `undefined` when there are none. */
export function subStatusTitle(subStatus) {
  return subStatus?.length > 0 ? subStatus.join(', ') : undefined;
}
