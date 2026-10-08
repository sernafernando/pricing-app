/**
 * The Agrupado tree as the flat list of rows `TableShell` renders
 * (publicaciones-ml-vista P12a). Pure: the loaded `branches` and the
 * `expanded` set in, rows out.
 *
 * A branch is the children of one node, addressed by `branchKey(path)` (the
 * keys of the ancestors, root first, as they came from the backend; `''` is the
 * roots). Its `rows` are nodes, or publications when the node is a leaf.
 *   branch: { status: 'loading'|'ready'|'more'|'error', rows, total, error }
 * `more` = the next page is loading, `error` with rows = that page failed.
 *
 * Row types: `node`, `item` (a publication, keyed by its MLA so the page's
 * selection works), `more` ("Ver más"), `state` (loading / error / empty of a
 * branch, shown under the node that asked).
 */
export const branchKey = (path) => path.join(',');

function pushBranch(out, branches, expanded, path, depth) {
  const key = branchKey(path);
  const branch = branches[key];
  if (!branch) return;

  if (branch.rows.length === 0 && branch.status === 'loading') {
    out.push({ type: 'state', id: `s:${key}`, state: 'loading', pathKey: key, depth });
    return;
  }
  if (branch.rows.length === 0 && branch.status === 'error') {
    out.push({ type: 'state', id: `s:${key}`, state: 'error', error: branch.error, pathKey: key, depth });
    return;
  }
  if (branch.rows.length === 0) {
    // An empty root is the table's own empty message.
    if (path.length > 0) out.push({ type: 'state', id: `s:${key}`, state: 'empty', pathKey: key, depth });
    return;
  }

  for (const row of branch.rows) {
    if (branch.leaf) {
      out.push({ type: 'item', id: row.item_id, item: row, depth, parentKey: key });
      continue;
    }
    const childPath = [...path, row.key];
    const childKey = branchKey(childPath);
    const open = expanded.has(childKey);
    out.push({ type: 'node', id: `n:${childKey}`, node: row, path: childPath, pathKey: childKey, depth, expanded: open });
    if (open) pushBranch(out, branches, expanded, childPath, depth + 1);
  }

  if (branch.status === 'error') {
    out.push({ type: 'state', id: `s:${key}`, state: 'error', error: branch.error, pathKey: key, depth });
  } else if (branch.rows.length < branch.total) {
    out.push({
      type: 'more',
      id: `m:${key}`,
      pathKey: key,
      remaining: branch.total - branch.rows.length,
      loading: branch.status === 'more',
      depth,
    });
  }
}

export function flattenTree({ branches, expanded }) {
  const out = [];
  pushBranch(out, branches, expanded, [], 0);
  return out;
}

/** What to tell the operator when a branch cannot be loaded. */
export function describeTreeError(error) {
  const status = error?.response?.status;
  if (status === 503) return 'La consulta tardó demasiado. Probá con filtros más acotados o reintentá.';
  if (status === 403) return 'No tenés permiso para ver las publicaciones.';
  if (status === 422) return 'Filtro inválido.';
  return 'No se pudo cargar este nivel.';
}
