import styles from '../../pages/TiendaNubeReconcile.module.css';
import ProductoCell from './ProductoCell';
import TnPresenceCell from './TnPresenceCell';
import StockCell from './StockCell';

const VERDICT_LABELS = {
  FALTA_VINCULAR: 'Falta vincular',
  FALTA_PUBLICAR: 'Falta publicar',
  MAL_VINCULADO: 'Mal vinculado',
  MAL_PUBLICADO: 'Mal publicado',
  DUPLICADO: 'Duplicado',
  // Match-accuracy follow-up: linked, but the TN SKU differs from the GBP
  // EAN only by leading zeros/formatting — needs a human to canonicalize
  // it, never auto-corrected. Own group, distinct from OK and MAL_PUBLICADO.
  POR_CORREGIR: 'Por corregir',
  OK: 'OK',
};

// One distinct colour per verdict (previously FALTA_PUBLICAR/MAL_VINCULADO/
// POR_CORREGIR all shared the same orange, and MAL_PUBLICADO/DUPLICADO
// shared the same red — the badge colour carried no signal).
const VERDICT_BADGE_CLASS = {
  FALTA_VINCULAR: 'badgeInfo',
  FALTA_PUBLICAR: 'badgeSuccess',
  MAL_VINCULADO: 'badgeWarning',
  MAL_PUBLICADO: 'badgeDanger',
  DUPLICADO: 'badgePurple',
  POR_CORREGIR: 'badgeTeal',
  OK: 'badge',
};

function verdictLabelFor(verdictId) {
  return VERDICT_LABELS[verdictId] || verdictId;
}

// Picks WHICH tn_match the unpublish action targets: prefer a match TN
// itself reports as `published: true` (the one actually live and worth
// unpublishing); fall back to the first match if none is explicitly
// published=true (published is nullable/unknown — see the `published`
// column docstring).
export function despublicarTargetProductId(row) {
  const published = row.tn_matches.find((tn) => tn.published === true);
  if (published) return published.product_id;
  return row.tn_matches[0]?.product_id ?? null;
}

// Single source of truth for the reporte table's columns: both the header
// (via TanStack) AND the body cells render from this list, so adding/
// removing a column can never desync header and body.
// Table redesign pass B: collapsed from 9 columns to 5. `EAN` moved into
// `Producto`; `Presencia en TN` + `Motivo` + `Coincidencias TN (IDs)` merged
// into `En Tienda Nube`; `Despublicar` dropped outright — the flag it showed
// (`row.despublicar` as Sí/—) is redundant with the presence label plus the
// action already living in the Acciones menu, and carries no information a
// human needs at a glance that those two don't already cover.
export const COLUMNS = [
  {
    id: 'producto',
    header: 'Producto',
    size: 340,
    cell: (row) => <ProductoCell row={row} />,
  },
  {
    id: 'verdict',
    header: 'Veredicto',
    size: 140,
    cell: (row) => (
      <span className={`${styles.badge} ${styles[VERDICT_BADGE_CLASS[row.verdict]] || ''}`}>
        {verdictLabelFor(row.verdict)}
      </span>
    ),
  },
  {
    id: 'tn_presence',
    header: 'En Tienda Nube',
    size: 260,
    cell: (row) => <TnPresenceCell row={row} />,
  },
  {
    id: 'stock',
    header: 'Stock',
    size: 100,
    sortable: true,
    cell: (row) => <StockCell row={row} />,
  },
  { id: 'acciones', header: 'Acciones', size: 190, cell: null }, // rendered specially — RowActionsCell (primary + overflow menu)
];
