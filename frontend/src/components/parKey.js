/**
 * Builds the collision-proof identity key for a (marca, categoria) pair.
 *
 * MUST be used everywhere a pair identity key is needed — including by the
 * Slice 4 container to build the `checked` Set it passes into `ParesTable`
 * — so a naive `${marca}|${categoria}` template string is never reinvented.
 * Marca and categoria values come from the ERP and are entered by people:
 * nothing guarantees they never contain a `|`. Marca "A|B" + categoria "C"
 * and marca "A" + categoria "B|C" would collide under a template-string
 * key, silently toggling the wrong row and corrupting the grant/revoke
 * diff. JSON encoding escapes the separator problem away instead of trying
 * to pick a "safe" delimiter.
 *
 * Kept in its own module (not exported from ParesTable.jsx) because
 * react-refresh/only-export-components forbids a component file from
 * exporting anything besides components — matches the existing
 * `components/promociones/treeNodeUtils.js` pattern in this codebase.
 */
export function parKey(marca, categoria) {
  return JSON.stringify([marca, categoria]);
}
