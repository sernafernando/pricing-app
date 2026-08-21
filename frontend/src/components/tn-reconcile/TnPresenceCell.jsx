import styles from '../../pages/TiendaNubeReconcile.module.css';
import { primaryTnMatch } from '../../pages/tiendaNubeReconcileHelpers';

// TN Presence Field requirement — replaces the old ambiguous single
// "Desconocido" label with four distinct, non-ambiguous states.
// "unknown" is NOT "we don't know if this exists in TN" — the backend only
// returns it when the TN row WAS resolved and its `published` flag simply
// has not been re-synced locally yet (see TiendaNubeProducto.published
// docstring). The label must communicate the actionable truth, never
// ignorance of the row's existence.
const TN_PRESENCE_LABELS = {
  published: 'Publicado en TN',
  draft: 'Borrador en TN',
  unknown: 'Existe en TN, publicación no sincronizada',
  not_in_tn: 'No está en Tienda Nube',
};

function tnPresenceLabelFor(presence) {
  return TN_PRESENCE_LABELS[presence] || TN_PRESENCE_LABELS.not_in_tn;
}

// Table redesign pass B: the old long, one-of-a-kind sentence per state
// (e.g. "Existe en TN, publicación no sincronizada") is replaced by a short
// coloured label — `tnPresenceLabelFor` (the long sentence) still backs the
// label's tooltip so the fuller explanation isn't lost, only demoted from
// "the whole cell" to "on hover/focus".
const TN_PRESENCE_SHORT_LABELS = {
  published: 'Publicado',
  draft: 'Borrador',
  unknown: 'Sin sincronizar',
  not_in_tn: 'No está',
};

const TN_PRESENCE_CLASS = {
  published: 'presenceGreen',
  draft: 'presenceOrange',
  unknown: 'presenceOrange',
  not_in_tn: 'presenceTertiary',
};

function tnPresenceShortLabelFor(presence) {
  return TN_PRESENCE_SHORT_LABELS[presence] || TN_PRESENCE_SHORT_LABELS.not_in_tn;
}

// Reason/cause taxonomy (Slice 1) — exhaustive-by-default code -> Spanish
// label map. An unrecognized/absent code renders as an empty cell, never a
// raw code and never "undefined" (R1.6/R1.7: rows with no reason must not
// regress, and a backend that hasn't shipped a new code yet must degrade
// safely rather than crash).
const REASON_LABELS = {
  DEAD_LINK: 'Enlace inexistente en Tienda Nube',
  SKU_MISMATCH: 'SKU no coincide con el EAN',
  NO_VARIANT_LINK: 'Sin vínculo de variante',
  // POR_CORREGIR's code. "Por corregir" (the verdict label) says neither
  // WHAT to correct nor WHERE — and every verdict in this table is
  // something to correct, so it distinguishes nothing. This names the
  // actual situation: same product, the SKU just needs canonicalizing.
  SKU_FORMAT: 'Mismo producto, hay que unificar el formato del SKU',
};

// Pass B: Motivo is no longer its own column — it renders inline, under the
// presence label, inside the "En Tienda Nube" cell, and simply renders
// nothing when there is no reason (there is no longer a standalone column
// to keep non-empty/aligned, so unlike the old ReasonCell there is no '—'
// placeholder).
/**
 * The two values an operator needs to decide WHAT to fix: the EAN GBP
 * expects and the SKU Tienda Nube actually holds.
 *
 * These used to live in a `title` attribute — visible only on hover, and
 * not at all with a keyboard or on a touch screen. The row said "SKU no
 * coincide con el EAN" and stopped there, which is the one thing the
 * operator already knew. Without the operands you cannot tell a one-digit
 * typo from a completely different product, and those need opposite
 * actions.
 *
 * Rendered verbatim in a monospace pair so the difference is legible at a
 * glance: a trailing space, a `_OTL`/`-OB` variant suffix, or a leading
 * zero all show up as themselves instead of being normalized away.
 */
function OperandosSku({ detail }) {
  if (!detail.expected_ean && !detail.tn_sku_found) return null;

  return (
    <span className={styles.motivoOperandos}>
      {detail.expected_ean && (
        <span className={styles.motivoOperando}>
          <span className={styles.motivoOperandoEtiqueta}>EAN GBP</span>
          <code className={styles.motivoValor}>{detail.expected_ean}</code>
        </span>
      )}
      {detail.tn_sku_found && (
        <span className={styles.motivoOperando}>
          <span className={styles.motivoOperandoEtiqueta}>SKU en TN</span>
          <code className={styles.motivoValor}>{detail.tn_sku_found}</code>
        </span>
      )}
    </span>
  );
}

function MotivoInline({ row }) {
  if (!row.reason) return null;
  // An unmapped code (a reason the backend added before this map caught up)
  // renders as its raw code rather than disappearing like "no reason at
  // all" would — degrading safely must not erase the signal.
  const label = REASON_LABELS[row.reason] || row.reason;

  const detail = row.reason_detail || {};
  // The claimed link ids stay in the tooltip: they matter when debugging a
  // stale pointer, but they are not what the operator reads to decide.
  const idsDeclarados = [];
  if (detail.claimed_tnr_id) idsDeclarados.push(`tnr_id declarado: ${detail.claimed_tnr_id}`);
  if (detail.claimed_tnr_variation_id) {
    idsDeclarados.push(`tnr_variationID declarado: ${detail.claimed_tnr_variation_id}`);
  }

  return (
    <span className={styles.motivoBloque}>
      <span className={styles.presenceMotivo} title={idsDeclarados.join(' · ') || undefined}>
        {label}
      </span>
      <OperandosSku detail={detail} />
    </span>
  );
}

/**
 * "En Tienda Nube" cell (pass B: merges the old Presencia en TN, Motivo and
 * Coincidencias TN (IDs) columns into one). No per-row action here —
 * `tn_presence == "unknown"`'s remediation is the single global sync
 * trigger in the page header (see `mostrarSincronizarTn`), never a per-row
 * button (would misrepresent the action's scope, see the original
 * `TnPresenceCell` reasoning this cell now carries forward).
 */
export default function TnPresenceCell({ row }) {
  const presenceClass = TN_PRESENCE_CLASS[row.tn_presence] || TN_PRESENCE_CLASS.not_in_tn;
  const primaryMatch = primaryTnMatch(row);
  const extraMatches = Math.max(0, (row.tn_matches?.length || 0) - 1);

  return (
    <div className={styles.presenceCell}>
      <span
        className={`${styles.presenceLabel} ${styles[presenceClass]}`}
        title={tnPresenceLabelFor(row.tn_presence)}
      >
        {tnPresenceShortLabelFor(row.tn_presence)}
      </span>
      <MotivoInline row={row} />
      {primaryMatch && (
        <div className={styles.presenceIds}>
          {primaryMatch.product_id}/{primaryMatch.variant_id}
          {extraMatches > 0 && <span className={styles.presenceExtra}> +{extraMatches}</span>}
        </div>
      )}
    </div>
  );
}
