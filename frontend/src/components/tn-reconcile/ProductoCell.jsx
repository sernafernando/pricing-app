import { useState, useMemo } from 'react';
import styles from '../../pages/TiendaNubeReconcile.module.css';
import { stripHtmlToText } from '../../utils/htmlText';
import { rowIdentity } from '../../pages/tiendaNubeReconcileHelpers';

const DESC_SNIPPET_LENGTH = 140;
const THUMB_PREVIEW_SIZE = 220;

/**
 * Product identity cell: thumbnail (hover/focus → larger preview), title and
 * a truncated description the operator can expand in place. Makes each row
 * recognizable at a glance instead of an anonymous EAN.
 */

export default function ProductoCell({ row }) {
  const [expanded, setExpanded] = useState(false);
  const [previewPos, setPreviewPos] = useState(null);

  const thumbSrc = Array.isArray(row.images) && row.images.length > 0 ? row.images[0] : null;
  const descText = useMemo(() => stripHtmlToText(row.ml_desc), [row.ml_desc]);
  // Identity fallback (PR5): products never published to ML have no
  // `ml_title` — they'd otherwise render as an anonymous EAN even though the
  // ERP already has a description for them (GBP report 78's `Descripción`
  // column, exposed as `erp_desc`). Never fabricated: only used when
  // `ml_title` is absent, and visibly labeled so it's never mistaken for a
  // real ML title.
  const { text: titleText, fromErp: usingErpFallback } = rowIdentity(row);

  // POR_CORREGIR (linked, but the TN SKU differs from the GBP EAN only by
  // leading zeros/formatting): show both values side by side so the
  // operator sees exactly what needs canonicalizing. Every other verdict
  // renders the EAN alone. Only rendered when there is an actual TN match
  // to compare against — a POR_CORREGIR row without a resolved match
  // renders its EAN exactly as any other verdict does.
  const tnSku = row.tn_matches?.[0]?.variant_sku;
  const showEanCompare = row.verdict === 'POR_CORREGIR' && Boolean(tnSku);

  const showPreview = (target) => {
    const rect = target.getBoundingClientRect();
    // Fixed-position preview (escapes the table's overflow container);
    // clamped so it never renders below the viewport.
    const top = Math.min(rect.top, Math.max(8, window.innerHeight - THUMB_PREVIEW_SIZE - 16));
    setPreviewPos({ top, left: rect.right + 10 });
  };

  const altText = titleText ? `Miniatura de ${titleText}` : `Miniatura del EAN ${row.ean}`;
  const isTruncated = descText.length > DESC_SNIPPET_LENGTH;

  return (
    <div className={styles.productoCell}>
      {thumbSrc && (
        /* Keyboard-focusable so the preview is reachable without a mouse;
           role="img" + aria-label give it a meaningful announcement (a bare
           focusable span announces nothing). The inner <img> is
           presentational (alt="" + aria-hidden) so screen readers hear ONE
           description, not two. */
        <span
          className={styles.thumbWrap}
          tabIndex={0}
          role="img"
          aria-label={altText}
          onMouseEnter={(e) => showPreview(e.currentTarget)}
          onMouseLeave={() => setPreviewPos(null)}
          onFocus={(e) => showPreview(e.currentTarget)}
          onBlur={() => setPreviewPos(null)}
        >
          <img src={thumbSrc} alt="" aria-hidden="true" className={styles.thumb} loading="lazy" />
          {previewPos && (
            <img
              src={thumbSrc}
              alt=""
              aria-hidden="true"
              className={styles.thumbPreview}
              style={{ top: previewPos.top, left: previewPos.left }}
            />
          )}
        </span>
      )}
      <div className={styles.prodText}>
        {titleText && (
          <div className={styles.prodTitle} title={titleText}>
            {usingErpFallback && <span className={styles.prodTitleErpTag}>ERP</span>}
            {titleText}
          </div>
        )}
        {descText &&
          (isTruncated ? (
            <button
              type="button"
              className={`${styles.prodDesc} ${expanded ? styles.prodDescExpanded : ''}`}
              title={descText}
              aria-expanded={expanded}
              aria-label={expanded ? 'Contraer descripción' : 'Expandir descripción'}
              onClick={() => setExpanded((v) => !v)}
            >
              {expanded ? descText : `${descText.slice(0, DESC_SNIPPET_LENGTH)}…`}
            </button>
          ) : (
            <span className={`${styles.prodDesc} ${styles.prodDescStatic}`}>{descText}</span>
          ))}
        {showEanCompare ? (
          <div className={styles.eanCompareCell}>
            <div>EAN: {row.ean}</div>
            <div>SKU TN: {tnSku}</div>
          </div>
        ) : (
          <div className={styles.prodEan}>{row.ean}</div>
        )}
      </div>
    </div>
  );
}
