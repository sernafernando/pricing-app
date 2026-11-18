/**
 * The column layout of a Publicaciones ML view (pubml-columnas-presets S1, S2): which columns show and in which
 * order, as the server keeps it (`{ visibility: { key: bool }, order: [key] }`, `GET/PUT /ml-publications/layouts`).
 *
 * A saved layout is a hint, never a contract: the columns a view has change with permissions, filters (the SKU
 * divergence column), the price mode and new releases. So every reading here starts from the view's own columns in
 * their default order and only takes from the save what still makes sense:
 *  - an unknown or removed key is ignored;
 *  - a column the save does not know goes right after the one it follows by default;
 *  - the first column (Publicación / Producto) stays first and always shows;
 *  - a group (Ventas, Markup, Stock...) moves as one block and its columns only move inside it.
 */

// The server's key rule (`^[a-z0-9_]{1,64}$`) and its cap per map/list.
const KEY_PATTERN = /^[a-z0-9_]{1,64}$/;
const MAX_KEYS = 200;

const validKey = (key) => typeof key === 'string' && KEY_PATTERN.test(key);

/**
 * `defaultIds` in the order of `savedIds`; an id `savedIds` lacks goes right after the id it follows in
 * `defaultIds` (or first, when it leads). Ids only in `savedIds` are dropped.
 */
export function mergeOrder(defaultIds, savedIds) {
  const rank = new Map();
  (Array.isArray(savedIds) ? savedIds : []).forEach((id, index) => {
    if (!rank.has(id)) rank.set(id, index);
  });
  const result = defaultIds.filter((id) => rank.has(id)).sort((a, b) => rank.get(a) - rank.get(b));
  defaultIds.forEach((id, index) => {
    if (rank.has(id)) return;
    const before = defaultIds.slice(0, index).reverse().find((previous) => result.includes(previous));
    result.splice(before === undefined ? 0 : result.indexOf(before) + 1, 0, id);
  });
  return result;
}

/**
 * The blocks the columns after the first one move in: each run of columns of the same `group` is one block
 * (`group:<name>`), each column without a group its own (`col:<key>`).
 */
export function columnBlocks(columns) {
  const blocks = [];
  for (const column of columns.slice(1)) {
    const last = blocks.at(-1);
    if (column.group && last?.group === column.group) last.keys.push(column.key);
    else blocks.push({ id: column.group ? `group:${column.group}` : `col:${column.key}`, group: column.group ?? null, keys: [column.key] });
  }
  return blocks;
}

/** The keys of `columns` in the saved order, under the rules above. */
export function resolveOrder(columns, savedOrder) {
  if (columns.length === 0) return [];
  const saved = Array.isArray(savedOrder) ? savedOrder.filter(validKey) : [];
  const position = new Map(saved.map((key, index) => [key, index]));
  const blocks = columnBlocks(columns);
  // A block ranks by its first column in the save; one the save does not know stays where it goes by default.
  const blockRank = (block) => Math.min(...block.keys.map((key) => position.get(key) ?? Infinity));
  const ranked = blocks.filter((block) => blockRank(block) !== Infinity).sort((a, b) => blockRank(a) - blockRank(b));
  const blockOrder = mergeOrder(
    blocks.map((block) => block.id),
    ranked.map((block) => block.id),
  );
  const byId = new Map(blocks.map((block) => [block.id, block]));
  return [columns[0].key, ...blockOrder.flatMap((id) => mergeOrder(byId.get(id).keys, saved))];
}

/** Every column's visibility: the saved choice, else the default (`defaults[key]`, visible when absent). */
export function resolveVisibility(columns, defaults = {}, savedVisibility) {
  const saved = savedVisibility && typeof savedVisibility === 'object' ? savedVisibility : {};
  return Object.fromEntries(
    columns.map((column, index) => {
      if (index === 0) return [column.key, true];
      const choice = saved[column.key];
      return [column.key, typeof choice === 'boolean' ? choice : (defaults[column.key] ?? true)];
    }),
  );
}

/** A layout as the server may send it, or null when it is not one. */
export function sanitizeLayout(raw) {
  if (!raw || typeof raw !== 'object' || Array.isArray(raw)) return null;
  const visibility = Object.fromEntries(
    Object.entries(raw.visibility && typeof raw.visibility === 'object' ? raw.visibility : {}).filter(
      ([key, value]) => validKey(key) && typeof value === 'boolean',
    ),
  );
  const order = [...new Set(Array.isArray(raw.order) ? raw.order.filter(validKey) : [])];
  return { visibility, order };
}

/**
 * `order` with the keys of `previous` it lacks (columns of another price mode, a filter's column...) kept right
 * after the key they followed, so a view's other shapes keep their places too.
 */
function carryOrder(order, previous) {
  const result = [...order];
  previous.forEach((key, index) => {
    if (result.includes(key)) return;
    const before = previous.slice(0, index).reverse().find((earlier) => result.includes(earlier));
    result.splice(before === undefined ? 0 : result.indexOf(before) + 1, 0, key);
  });
  return result;
}

/** The body a layout is saved with: the current choices over the saved ones, within the server's limits. */
export function layoutPayload(saved, visibility, order) {
  // The current columns always fit; keys only the saved layout still carries fill what is left of the cap.
  const isEntry = ([key, value]) => validKey(key) && typeof value === 'boolean';
  const current = Object.entries(visibility).filter(isEntry).slice(0, MAX_KEYS);
  const carried = Object.entries(saved?.visibility ?? {})
    .filter((entry) => isEntry(entry) && !(entry[0] in visibility))
    .slice(0, MAX_KEYS - current.length);
  const currentOrder = new Set(order.filter(validKey));
  let room = MAX_KEYS - currentOrder.size;
  return {
    visibility: Object.fromEntries([...current, ...carried]),
    order: carryOrder(order, saved?.order ?? [])
      .filter(validKey)
      .filter((key) => currentOrder.has(key) || room-- > 0),
  };
}

const sameList = (a, b) => a.length === b.length && a.every((item, index) => item === b[index]);

/** Whether `saved` shows `columns` exactly as `visibility` and `order` do. */
export function layoutMatches(columns, defaults, saved, visibility, order) {
  const layout = sanitizeLayout(saved);
  const theirs = resolveVisibility(columns, defaults, layout?.visibility);
  return sameList(resolveOrder(columns, layout?.order), order) && columns.every((column) => theirs[column.key] === visibility[column.key]);
}
