/**
 * The user's own color layer preferences, as `GET /equipos` sends them on each layer (pubml-capa-default S2-S3).
 * Layers are the page's `equipo` values: '' is the global layer, a team is its id as a string.
 */

/** The layer Publicaciones ML opens on: the user's team marked `por_defecto`, otherwise the global one (''). */
export function defaultLayer(equipos) {
  const team = equipos.find((equipo) => !equipo.es_global && equipo.por_defecto);
  return team ? String(team.id) : '';
}

/** Whether the global color reference shows on `layer`: on unless the user turned it off for that team. */
export function showsGlobalReference(equipos, layer) {
  if (layer === '') return true;
  const team = equipos.find((equipo) => !equipo.es_global && String(equipo.id) === layer);
  return team?.mostrar_referencia_global !== false;
}
