import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { publicacionesMlAPI } from '../../services/api';
import { buildGroupsParams, buildLeafParams, readGroupsPage } from './groupNodes';
import { flattenTree } from './groupTree';

/**
 * State of the Agrupado tree (publicaciones-ml-vista P12a): which nodes are
 * open and what each one loaded. Everything is lazy -- the roots on mount, the
 * children of a node when it opens, the next 100 on "Ver más" -- and one
 * request per click. Anything that changes what the tree is made of (the user's
 * filters, the family toggle, the permission) starts over, collapsed, and an
 * answer to a request of the previous tree is dropped.
 *
 * A branch is `{path, leaf, node, status, rows, total, error}`; see
 * `groupTree.js` for the rows `TableShell` is given.
 */
const ROOT = { path: [], leaf: false, node: null };

/**
 * Pages are by offset, so a row that moved between two requests can come in both:
 * it stays once (a publication by its MLA, a node by its key).
 */
function appendPage(rows, page, leaf) {
  const idOf = (row) => (leaf ? row.item_id : row.key);
  const seen = new Set(rows.map(idOf));
  return [...rows, ...page.filter((row) => !seen.has(idOf(row)))];
}

export default function useGroupTree({ filters, familias, canSeeMargin }) {
  const [branches, setBranches] = useState({});
  const [expanded, setExpanded] = useState(() => new Set());
  const generation = useRef(0);
  // The pages being fetched (`key@offset`): a second click before the answer asks for nothing.
  const inflight = useRef(new Set());
  const latest = useRef({ filters, familias, canSeeMargin });
  // Declared before the effect that loads the roots, so that effect reads this render's values.
  useEffect(() => {
    latest.current = { filters, familias, canSeeMargin };
  }, [filters, familias, canSeeMargin]);

  // What the roots are asked with: the selection, the page and the like do not restart the tree.
  const treeKey = JSON.stringify([buildGroupsParams(filters, { path: [], familias, offset: 0 }), canSeeMargin]);

  const fetchPage = useCallback((key, branch, offset) => {
    const { filters: current, familias: withFamilies, canSeeMargin: margin } = latest.current;
    const mine = generation.current;
    const { path, leaf, node } = branch;
    const page = `${key}@${offset}`;
    const pending = inflight.current;
    if (pending.has(page)) return;
    pending.add(page);
    setBranches((all) => ({
      ...all,
      [key]: { rows: [], total: 0, ...all[key], path, leaf, node, status: offset === 0 ? 'loading' : 'more', error: null },
    }));
    const request = leaf
      ? publicacionesMlAPI.items(buildLeafParams(current, node, offset))
      : publicacionesMlAPI.groups(buildGroupsParams(current, { path, familias: withFamilies, offset }));
    request
      .then((response) => {
        pending.delete(page);
        if (mine !== generation.current) return;
        const loaded = leaf
          ? { rows: response.data?.items ?? [], total: response.data?.total ?? 0 }
          : (({ nodes, total }) => ({ rows: nodes, total }))(readGroupsPage(response.data, { canSeeMargin: margin }));
        setBranches((all) => ({
          ...all,
          [key]: { ...all[key], status: 'ready', rows: offset === 0 ? loaded.rows : appendPage(all[key].rows, loaded.rows, leaf), total: loaded.total },
        }));
      })
      .catch((error) => {
        pending.delete(page);
        if (mine !== generation.current) return;
        setBranches((all) => ({ ...all, [key]: { ...all[key], status: 'error', error } }));
      });
  }, []);

  useEffect(() => {
    generation.current += 1;
    inflight.current = new Set();
    setExpanded(new Set());
    setBranches({});
    fetchPage('', ROOT, 0);
  }, [treeKey, fetchPage]);

  const toggle = useCallback(
    (row) => {
      if (expanded.has(row.pathKey)) {
        setExpanded((current) => {
          const next = new Set(current);
          next.delete(row.pathKey);
          return next;
        });
        return;
      }
      setExpanded((current) => new Set(current).add(row.pathKey));
      const loaded = branches[row.pathKey];
      if (!loaded || (loaded.status === 'error' && loaded.rows.length === 0)) {
        fetchPage(row.pathKey, { path: row.path, leaf: row.node.leaf, node: row.node }, 0);
      }
    },
    [expanded, branches, fetchPage],
  );

  // "Ver más" and "Reintentar" ask for what the branch does not have yet.
  const loadMore = useCallback(
    (pathKey) => {
      const branch = branches[pathKey];
      if (branch) fetchPage(pathKey, branch, branch.rows.length);
    },
    [branches, fetchPage],
  );

  const rows = useMemo(() => flattenTree({ branches, expanded }), [branches, expanded]);
  return { rows, toggle, loadMore };
}
