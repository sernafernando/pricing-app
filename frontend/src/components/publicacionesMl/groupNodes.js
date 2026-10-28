import { buildItemsParams } from '../../hooks/usePublicacionesMLFilters';

/**
 * The one place that reads `GET /ml-publications/view/groups` (router
 * `GroupNodeOut`, P7a) and builds the requests of the Agrupado tree, so the
 * tree depends only on what this returns.
 *
 * Node: `{kind, key, label, count, leaf, params, producto_item_id?, codigo?,
 * family_id?, item_id?}`. `key` travels back to the backend EXACTLY as it came
 * (brands and categories arrive percent-escaped: `%`, `,`); the label is what
 * is shown. `params` are the node's `/items` filters, ancestors included, to
 * put over the user's own; a `leaf`'s children are publications.
 *
 * Node aggregates (P7b): `negative_count`, `markup_min`, `markup_max`, sent
 * only with `ml_metricas.ver_ganancia`. A field the backend did not send is
 * `null` ("—" on screen), never a made-up 0. This is the only function that
 * names them, so a change of P7b's contract is a change here.
 */
export const GROUPS_PAGE = 100;
export const NO_GROUP = '__none__';

const KEY_ESCAPES = /%(25|2C)/g;
/** Inverse of the backend's `encode_key`: one pass, `%252C` is the text `%2C`. */
export const decodeKey = (key) => key.replace(KEY_ESCAPES, (_, hex) => String.fromCharCode(Number.parseInt(hex, 16)));
/** The backend's `encode_key`: a brand or category with `%` or `,` stays ONE value of a csv param. */
export const encodeKey = (text) => text.replace(/[%,]/g, (char) => (char === '%' ? '%25' : '%2C'));

const numberOrNull = (value) => (typeof value === 'number' ? value : null);

function readAggregates(raw, canSeeMargin) {
  if (!canSeeMargin) return { negativeCount: null, markup: null };
  const hasRange = 'markup_min' in raw || 'markup_max' in raw;
  return {
    negativeCount: numberOrNull(raw.negative_count),
    markup: hasRange ? { min: numberOrNull(raw.markup_min), max: numberOrNull(raw.markup_max) } : null,
  };
}

export function readNode(raw, { canSeeMargin }) {
  return {
    kind: raw.kind,
    key: raw.key ?? '',
    label: raw.label || decodeKey(raw.key ?? ''),
    count: raw.count ?? 0,
    leaf: raw.leaf === true,
    params: raw.params ?? {},
    withoutProduct: raw.kind === 'producto' && raw.key === NO_GROUP,
    productoItemId: raw.producto_item_id ?? null,
    codigo: raw.codigo ?? null,
    familyId: raw.family_id ?? null,
    itemId: raw.item_id ?? null,
    colorMarcado: raw.color_marcado ?? null,
    colorHintGlobal: raw.color_hint_global ?? null,
    ...readAggregates(raw, canSeeMargin),
  };
}

export function readGroupsPage(data, { canSeeMargin }) {
  return {
    level: data?.level ?? null,
    nodes: (data?.nodes ?? []).map((raw) => readNode(raw, { canSeeMargin })),
    total: data?.total ?? 0,
  };
}

/**
 * The user's filters as `/groups` and the leaves' `/items` take them. The sort,
 * the page and the markup filters are the list's: the tree has no sort, pages
 * by its own offset, and `/groups` does not apply the markup filters (its
 * counts would disagree with the list under them), so they are not sent.
 */
function filterParams(filters) {
  const params = buildItemsParams(filters, 0, { canSeeMargin: false });
  for (const key of ['orden', 'dir', 'limit', 'offset']) delete params[key];
  return params;
}

/** The children of the node `path` names (the roots for an empty path), in the tree grouped by `dimension`. */
export function buildGroupsParams(filters, { path, familias, dimension, offset }) {
  const params = { ...filterParams(filters), dimension, familias, limit: GROUPS_PAGE, offset };
  if (path.length > 0) params.path = path.join(',');
  return params;
}

// The color layer (`equipo_id`) picks which team's colors the rows carry: it narrows nothing on its own.
const LAYER_PARAM = 'equipo_id';
// The backend's status token for a deleted publication, hidden unless `estado` asks for it (`filters._status`).
const STATUS_GONE = 'gone';

/**
 * What the user's filters do to a leaf's publications: `filtered` when one narrows them, `listsDeleted` when
 * `estado` asks for the deleted ones (otherwise the backend hides them).
 */
export function leafScope(filters) {
  const { [LAYER_PARAM]: layer, ...narrowing } = filterParams(filters);
  void layer;
  return { filtered: Object.keys(narrowing).length > 0, listsDeleted: (filters.estado ?? []).includes(STATUS_GONE) };
}

/**
 * The publications of a leaf node: its params over the user's, one page of 100. `unfiltered` drops the user's
 * filters (the color layer stays: it is not one), `onlyDeleted` asks just the deleted ones of that scope (`estado`
 * becomes `gone`, the rest of the scope applies), `limit` is the page (1 to read only the `total`).
 */
export function buildLeafParams(filters, node, offset, { unfiltered = false, onlyDeleted = false, limit = GROUPS_PAGE } = {}) {
  const own = filterParams(filters);
  const scope = unfiltered ? (own[LAYER_PARAM] ? { [LAYER_PARAM]: own[LAYER_PARAM] } : {}) : own;
  return { ...scope, ...(onlyDeleted && { estado: STATUS_GONE }), ...node.params, limit, offset };
}
