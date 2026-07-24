/**
 * TnPublishModal — publish form for a FALTA_PUBLICAR row (Sub-slice 3c).
 *
 * The `row` prop is the ALREADY-ENRICHED reconciliation row returned by
 * `GET /tienda-nube-reconcile/reporte` — it carries `ml_desc`, `images`
 * (ordered, empty slots already filtered server-side), `categoria` and
 * `subcategoria` directly. This modal reads those off the row it already
 * has; it does NOT call `/gbp-parser` or do any client-side EAN matching
 * (that was a temporary workaround in the initial 3c cut, removed once the
 * backend response was extended to carry these fields per-row).
 *
 * On open:
 *   1. Calls `POST /tienda-nube-reconcile/categoria-sugerida` with the
 *      row's category text (`categoria` + `subcategoria`) and pre-selects
 *      the top-1 suggestion; empty result (embedder down) falls back to
 *      manual entry only, never an error.
 *   2. Pre-loads a TipTap WYSIWYG editor from `row.ml_desc`.
 *
 * Submit runs the editor's HTML through `sanitizeHtml.js` (defense-in-depth
 * alongside the server-side `nh3` pass in `tn_publish_service.py`), requires
 * an inline Confirmar/Cancelar step (mirrors the Despublicar pattern in
 * `TiendaNubeReconcile.jsx` — NEVER `window.confirm`), and disables the
 * submit button while in flight to prevent a double-submit.
 */

import { useState, useEffect, useMemo, useCallback } from 'react';
import { useEditor, EditorContent } from '@tiptap/react';
import StarterKit from '@tiptap/starter-kit';
import ModalTesla from './ModalTesla';
import { sanitizeHtml } from '../utils/sanitizeHtml';
import api from '../services/api';
import styles from './TnPublishModal.module.css';

function buildCategoryText(row) {
  if (!row) return '';
  return [row.categoria, row.subcategoria].filter(Boolean).join(' ').trim();
}

export default function TnPublishModal({ row, isOpen, onClose, onPublished }) {
  const [loadingSuggestion, setLoadingSuggestion] = useState(true);
  const [loadError, setLoadError] = useState(null);

  const [suggestions, setSuggestions] = useState([]);
  const [categorySelection, setCategorySelection] = useState(null); // 'manual' or tn_category_id
  const [manualCategoryId, setManualCategoryId] = useState('');

  const [confirming, setConfirming] = useState(false);
  const [submitting, setSubmitting] = useState(false);
  const [submitError, setSubmitError] = useState(null);

  const editor = useEditor({
    extensions: [StarterKit],
    content: '',
  });

  const ean = row?.ean;
  const imageSrcs = useMemo(() => (Array.isArray(row?.images) ? row.images : []), [row]);

  // One-shot load: only the category suggestion needs a fetch now — the
  // product fields (ml_desc/images/categoria) already arrived on `row`.
  // Never re-fetches on re-render — only when `ean` changes.
  useEffect(() => {
    if (!isOpen || !ean) return;
    let cancelled = false;

    if (row?.ml_desc) editor?.commands.setContent(row.ml_desc);

    async function load() {
      setLoadingSuggestion(true);
      setLoadError(null);
      try {
        const categoryText = buildCategoryText(row);
        if (categoryText) {
          const sugResponse = await api.post('/tienda-nube-reconcile/categoria-sugerida', {
            category_text: categoryText,
            top_n: 5,
          });
          if (cancelled) return;
          const list = sugResponse.data?.suggestions || [];
          setSuggestions(list);
          const top = sugResponse.data?.top;
          setCategorySelection(top ? top.tn_category_id : null);
        } else {
          setSuggestions([]);
          setCategorySelection(null);
        }
      } catch (err) {
        if (!cancelled) {
          setLoadError(err?.response?.data?.error?.message || err?.message || 'No se pudo sugerir una categoría');
        }
      } finally {
        if (!cancelled) setLoadingSuggestion(false);
      }
    }

    load();
    return () => {
      cancelled = true;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [isOpen, ean]);

  const resolvedCategoryId = useMemo(() => {
    if (categorySelection === 'manual' || (categorySelection === null && suggestions.length === 0)) {
      const parsed = parseInt(manualCategoryId, 10);
      return Number.isFinite(parsed) ? parsed : null;
    }
    return typeof categorySelection === 'number' ? categorySelection : null;
  }, [categorySelection, manualCategoryId, suggestions.length]);

  const canPublish = Boolean(resolvedCategoryId) && !loadingSuggestion;

  const handlePublishClick = useCallback(() => {
    setConfirming(true);
    setSubmitError(null);
  }, []);

  const handleCancelConfirm = useCallback(() => {
    setConfirming(false);
  }, []);

  const handleConfirm = useCallback(async () => {
    if (submitting) return; // never double-submit
    setSubmitting(true);
    setSubmitError(null);
    try {
      const descriptionHtml = sanitizeHtml(editor?.getHTML() || '');
      const productData = row ? { ...row } : {};
      const response = await api.post('/tienda-nube-reconcile/publicar', {
        ean,
        product_data: productData,
        category_id: resolvedCategoryId,
        description_html: descriptionHtml,
        image_srcs: imageSrcs,
      });
      setConfirming(false);
      onPublished?.(ean, response.data);
    } catch (err) {
      setSubmitError(err?.response?.data?.error?.message || err?.message || 'Error al publicar el producto');
    } finally {
      setSubmitting(false);
    }
  }, [submitting, editor, row, ean, resolvedCategoryId, imageSrcs, onPublished]);

  if (!isOpen) return null;

  return (
    <ModalTesla isOpen={isOpen} onClose={onClose} title="Publicar producto en Tienda Nube" size="lg">
      {loadError && <div className={styles.errorBanner}>{loadError}</div>}
      {submitError && <div className={styles.errorBanner}>{submitError}</div>}

      <div className={styles.section}>
        <h3 className={styles.sectionTitle}>Categoría sugerida</h3>
        {suggestions.length > 0 ? (
          <div role="radiogroup" aria-label="Categoría TN">
            {suggestions.map((s) => (
              <label key={s.tn_category_id} className={styles.categoryOption}>
                <input
                  type="radio"
                  name="tn-category"
                  checked={categorySelection === s.tn_category_id}
                  onChange={() => setCategorySelection(s.tn_category_id)}
                />
                <span className={s.tn_category_id === suggestions[0].tn_category_id ? styles.categoryTop : ''}>
                  {s.category_path_text} ({Math.round(s.similarity * 100)}%)
                </span>
              </label>
            ))}
            <label className={styles.categoryOption}>
              <input
                type="radio"
                name="tn-category"
                checked={categorySelection === 'manual'}
                onChange={() => setCategorySelection('manual')}
              />
              Otra categoría (ingresar ID manualmente)
            </label>
            {categorySelection === 'manual' && (
              <div className={styles.manualCategoryRow}>
                <label htmlFor="tn-manual-category-id">ID de categoría manual</label>
                <input
                  id="tn-manual-category-id"
                  type="number"
                  value={manualCategoryId}
                  onChange={(e) => setManualCategoryId(e.target.value)}
                />
              </div>
            )}
          </div>
        ) : (
          <div className={styles.manualCategoryRow}>
            <label htmlFor="tn-manual-category-id">ID de categoría TN (manual)</label>
            <input
              id="tn-manual-category-id"
              type="number"
              value={manualCategoryId}
              onChange={(e) => setManualCategoryId(e.target.value)}
            />
          </div>
        )}
      </div>

      <div className={styles.section}>
        <h3 className={styles.sectionTitle}>Descripción</h3>
        <div className={styles.editorShell}>
          <EditorContent editor={editor} />
        </div>
      </div>

      <div className={styles.section}>
        <h3 className={styles.sectionTitle}>Imágenes ({imageSrcs.length})</h3>
        <div className={styles.imageList}>{imageSrcs.length === 0 ? '—' : imageSrcs.join(', ')}</div>
      </div>

      {confirming ? (
        <div className={styles.confirmBar}>
          <button type="button" className="btn-tesla outline-subtle-success sm" disabled={submitting} onClick={handleConfirm}>
            Confirmar
          </button>
          <button type="button" className="btn-tesla ghost sm" disabled={submitting} onClick={handleCancelConfirm}>
            Cancelar
          </button>
        </div>
      ) : (
        <button type="button" className="btn-tesla outline sm" disabled={!canPublish} onClick={handlePublishClick}>
          Publicar
        </button>
      )}
    </ModalTesla>
  );
}
