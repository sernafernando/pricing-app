/**
 * TnPublishModal — publish form for a FALTA_PUBLICAR row (Sub-slice 3c,
 * rebuilt UI).
 *
 * The `row` prop is the ALREADY-ENRICHED reconciliation row returned by
 * `GET /tienda-nube-reconcile/reporte` — it carries `ml_title`, `ml_desc`,
 * `images` (ordered, empty slots already filtered server-side), `categoria`
 * and `subcategoria` directly. This modal reads those off the row it already
 * has; it does NOT call `/gbp-parser` or do any client-side EAN matching.
 *
 * Form sections:
 *   1. Título — editable text input pre-loaded from `row.ml_title`. The
 *      edited value is submitted inside `product_data.name.es`, which is
 *      exactly where `tn_publish_service.publish_product` reads the product
 *      name from (TN payload + local mirror).
 *   2. Categoría — ALWAYS by NAME, never by raw numeric id. The top-N
 *      embedder suggestions from `POST /categoria-sugerida` are shown as
 *      radios (top-1 pre-selected); a debounced search box against
 *      `GET /categorias?q=` lets the operator pick ANY category by its
 *      `category_path` text. The chosen `tn_category_id` is tracked
 *      internally and submitted — the operator never types an id.
 *   3. Imágenes — dnd-kit sortable thumbnail grid (drag to reorder, per-image
 *      delete). The submitted `image_srcs` is the grid's final order minus
 *      deletions. Pointer + keyboard sensors (space to lift, arrows to move).
 *   4. Descripción — TipTap WYSIWYG pre-loaded from `row.ml_desc`, with a
 *      visible toolbar (bold / italic / underline / strike, H1–H3, paragraph,
 *      bullet + numbered lists). On submit the HTML runs through
 *      `sanitizeHtml` with headings opt-in allowed (matching the backend's
 *      nh3 allowlist, which already permits h1–h6) — defense-in-depth
 *      alongside the server-side pass in `tn_publish_service.py`.
 *   5. Precio de publicación (Slice 2, money path) — THIS IS THE FIX FOR THE
 *      PRODUCTION BUG: the payload used to omit price entirely
 *      (`{ name: { es: title } }`), so every product published through this
 *      modal reached the live storefront with no price. Two mutually
 *      exclusive bases, always labeled so the operator knows which business
 *      quantity is in play:
 *        - `row.precio_web_transferencia` (when `row.participa_web_transferencia`
 *          is true): a PLAIN SURCHARGE — `base * (1 + offset / 100)` — never
 *          the pricing engine's markup/margin machinery. `offset` defaults to
 *          25, editable per-publish, never persisted anywhere.
 *        - Otherwise: manual price entry, seeded from `row.precio_lista_ml`
 *          (the ML Clásica list price — a DIFFERENT business quantity, never
 *          silently substituted), freely editable by the operator.
 *      The submitted `product_data.price` is always the exact string shown
 *      in the preview — never recomputed silently between preview and
 *      submit. Publishing is blocked while the resulting price isn't a
 *      positive number (mirrors the backend's containment guard in
 *      `tn_publish_service.publish_product`, which is authoritative — this
 *      is UX, not the real check).
 *
 * Submit requires an inline Confirmar/Cancelar step (mirrors the Despublicar
 * pattern in `TiendaNubeReconcile.jsx` — NEVER `window.confirm`) and locks
 * the button while in flight to prevent a double-submit. Permission gating
 * (`admin.gestionar_tn_publicacion`) happens at the caller — this modal is
 * only ever rendered for operators holding it.
 */

import { useState, useEffect, useMemo, useCallback } from 'react';
import { useEditor, EditorContent, useEditorState } from '@tiptap/react';
import StarterKit from '@tiptap/starter-kit';
import {
  DndContext,
  closestCenter,
  PointerSensor,
  KeyboardSensor,
  useSensor,
  useSensors,
} from '@dnd-kit/core';
import {
  SortableContext,
  arrayMove,
  rectSortingStrategy,
  sortableKeyboardCoordinates,
  useSortable,
} from '@dnd-kit/sortable';
import { CSS as DndCss } from '@dnd-kit/utilities';
import {
  Bold,
  Italic,
  Underline,
  Strikethrough,
  Heading1,
  Heading2,
  Heading3,
  Pilcrow,
  List,
  ListOrdered,
  Search,
  GripVertical,
  X,
  Check,
} from 'lucide-react';
import ModalTesla from './ModalTesla';
import { sanitizeHtml } from '../utils/sanitizeHtml';
import { useDebounce } from '../hooks/useDebounce';
import api from '../services/api';
import styles from './TnPublishModal.module.css';

// Headings the toolbar can produce — must survive the frontend sanitize pass
// (the backend's nh3 allowlist already permits h1–h6, so nothing is lost
// server-side either).
const DESCRIPTION_EXTRA_TAGS = ['h1', 'h2', 'h3'];

function buildCategoryText(row) {
  if (!row) return '';
  return [row.categoria, row.subcategoria].filter(Boolean).join(' ').trim();
}

/** One sortable image tile: drag handle (pointer + keyboard) + delete. */
function SortableImageTile({ image, index, onDelete }) {
  const { attributes, listeners, setNodeRef, transform, transition, isDragging } = useSortable({
    id: image.id,
  });

  return (
    <li
      ref={setNodeRef}
      className={`${styles.imageTile} ${isDragging ? styles.imageTileDragging : ''}`}
      style={{ transform: DndCss.Transform.toString(transform), transition }}
    >
      <button
        type="button"
        className={styles.imageDragHandle}
        aria-label={`Reordenar imagen ${index + 1}`}
        {...attributes}
        {...listeners}
      >
        <GripVertical size={14} aria-hidden="true" />
      </button>
      <img src={image.src} alt={`Imagen ${index + 1} del producto`} className={styles.imageThumb} loading="lazy" />
      <span className={styles.imageOrder} aria-hidden="true">
        {index + 1}
      </span>
      <button
        type="button"
        className={styles.imageDelete}
        aria-label={`Eliminar imagen ${index + 1}`}
        onClick={() => onDelete(image.id)}
      >
        <X size={13} aria-hidden="true" />
      </button>
    </li>
  );
}

/** Toolbar button with pressed state for the TipTap editor. */
function ToolbarButton({ label, active, disabled, onClick, children }) {
  return (
    <button
      type="button"
      className={`${styles.toolbarBtn} ${active ? styles.toolbarBtnActive : ''}`}
      aria-label={label}
      title={label}
      aria-pressed={Boolean(active)}
      disabled={disabled}
      onClick={onClick}
    >
      {children}
    </button>
  );
}

export default function TnPublishModal({ row, isOpen, onClose, onPublished }) {
  const [loadingSuggestion, setLoadingSuggestion] = useState(true);
  const [loadError, setLoadError] = useState(null);

  // Título — pre-loaded from ml_title, freely editable.
  const [title, setTitle] = useState(() => row?.ml_title || '');

  // Category selection is ALWAYS an object { id, path } (or null) — there is
  // no numeric-id entry anywhere in this form.
  const [suggestions, setSuggestions] = useState([]);
  const [selectedCategory, setSelectedCategory] = useState(null);

  // Name search against GET /categorias?q= (debounced).
  const [categoryQuery, setCategoryQuery] = useState('');
  const debouncedCategoryQuery = useDebounce(categoryQuery, 300);
  const [searchResults, setSearchResults] = useState([]);
  const [searching, setSearching] = useState(false);
  const [searchError, setSearchError] = useState(null);

  // Imágenes — ordered, deletable. Ids are index-seeded so duplicate srcs
  // can never collide as dnd-kit ids.
  const [images, setImages] = useState(() =>
    (Array.isArray(row?.images) ? row.images : []).map((src, idx) => ({ id: `img-${idx}`, src }))
  );

  const [confirming, setConfirming] = useState(false);
  const [submitting, setSubmitting] = useState(false);
  const [submitError, setSubmitError] = useState(null);

  // Precio de publicación (Slice 2, money path). `hasWebPrice` selects the
  // surcharge path vs. the manual-entry fallback — see the file header
  // docstring for the two-base rule. `offsetPercent` is a modal-local
  // preset only (default 25) — it is NEVER persisted anywhere server-side.
  const hasWebPrice =
    row?.precio_web_transferencia != null &&
    row?.precio_web_transferencia !== '' &&
    row?.participa_web_transferencia === true;
  const [offsetPercent, setOffsetPercent] = useState(25);
  const [manualPrice, setManualPrice] = useState(() =>
    row?.precio_lista_ml != null ? String(row.precio_lista_ml) : ''
  );

  const editor = useEditor({
    extensions: [StarterKit],
    content: '',
  });

  // Re-render the toolbar when marks/nodes under the cursor change.
  const editorState = useEditorState({
    editor,
    selector: (ctx) => ({
      bold: ctx.editor?.isActive('bold') ?? false,
      italic: ctx.editor?.isActive('italic') ?? false,
      underline: ctx.editor?.isActive('underline') ?? false,
      strike: ctx.editor?.isActive('strike') ?? false,
      h1: ctx.editor?.isActive('heading', { level: 1 }) ?? false,
      h2: ctx.editor?.isActive('heading', { level: 2 }) ?? false,
      h3: ctx.editor?.isActive('heading', { level: 3 }) ?? false,
      paragraph: ctx.editor?.isActive('paragraph') ?? false,
      bulletList: ctx.editor?.isActive('bulletList') ?? false,
      orderedList: ctx.editor?.isActive('orderedList') ?? false,
    }),
  });

  const ean = row?.ean;

  const sensors = useSensors(
    useSensor(PointerSensor, { activationConstraint: { distance: 4 } }),
    useSensor(KeyboardSensor, { coordinateGetter: sortableKeyboardCoordinates })
  );

  // One-shot load: only the category suggestion needs a fetch — the product
  // fields (ml_title/ml_desc/images/categoria) already arrived on `row`.
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
          setSelectedCategory(
            top ? { id: top.tn_category_id, path: top.category_path_text } : null
          );
        } else {
          setSuggestions([]);
          setSelectedCategory(null);
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

  // Debounced category NAME search — the manual path that replaces the old
  // raw-id input. Empty/short queries clear the results without a request.
  useEffect(() => {
    const q = debouncedCategoryQuery.trim();
    if (!isOpen || q.length < 2) {
      setSearchResults([]);
      setSearching(false);
      setSearchError(null);
      return;
    }
    let cancelled = false;
    async function search() {
      setSearching(true);
      setSearchError(null);
      try {
        const response = await api.get('/tienda-nube-reconcile/categorias', {
          params: { q, limit: 20 },
        });
        if (!cancelled) setSearchResults(Array.isArray(response.data) ? response.data : []);
      } catch (err) {
        if (!cancelled) {
          setSearchResults([]);
          setSearchError(err?.response?.data?.error?.message || err?.message || 'No se pudieron buscar categorías');
        }
      } finally {
        if (!cancelled) setSearching(false);
      }
    }
    search();
    return () => {
      cancelled = true;
    };
  }, [debouncedCategoryQuery, isOpen]);

  const pickSearchResult = useCallback((result) => {
    setSelectedCategory({ id: result.tn_category_id, path: result.category_path });
    setCategoryQuery('');
    setSearchResults([]);
  }, []);

  const handleDragEnd = useCallback((event) => {
    const { active, over } = event;
    if (!over || active.id === over.id) return;
    setImages((prev) => {
      const oldIndex = prev.findIndex((img) => img.id === active.id);
      const newIndex = prev.findIndex((img) => img.id === over.id);
      if (oldIndex === -1 || newIndex === -1) return prev;
      return arrayMove(prev, oldIndex, newIndex);
    });
  }, []);

  const deleteImage = useCallback((id) => {
    setImages((prev) => prev.filter((img) => img.id !== id));
  }, []);

  const imageIds = useMemo(() => images.map((img) => img.id), [images]);

  // True when the current selection came from the search box (it's not one
  // of the embedder suggestions) — rendered as its own checked option so the
  // operator always SEES what is selected.
  const selectionOutsideSuggestions = useMemo(
    () =>
      selectedCategory != null &&
      !suggestions.some((s) => s.tn_category_id === selectedCategory.id),
    [selectedCategory, suggestions]
  );

  // Precio de publicación — plain surcharge over the base price (NOT the
  // pricing engine's markup/margin computation). Recomputed on every
  // offsetPercent/base change so the preview and the submitted value are
  // always exactly the same string.
  const basePrice = hasWebPrice ? Number(row.precio_web_transferencia) : null;
  const computedPrice = useMemo(() => {
    if (!hasWebPrice || basePrice == null || Number.isNaN(basePrice)) return null;
    const offset = Number(offsetPercent);
    if (Number.isNaN(offset)) return null;
    return (basePrice * (1 + offset / 100)).toFixed(2);
  }, [hasWebPrice, basePrice, offsetPercent]);

  const finalPrice = hasWebPrice
    ? computedPrice
    : manualPrice !== '' && !Number.isNaN(Number(manualPrice))
      ? Number(manualPrice).toFixed(2)
      : null;
  const finalPriceIsValid = finalPrice != null && Number(finalPrice) > 0;
  const priceBaseSource = hasWebPrice ? 'web_transferencia' : 'manual';

  const canPublish =
    selectedCategory != null &&
    title.trim().length > 0 &&
    !loadingSuggestion &&
    !submitting &&
    finalPriceIsValid;

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
      const descriptionHtml = sanitizeHtml(editor?.getHTML() || '', {
        extraTags: DESCRIPTION_EXTRA_TAGS,
      });
      // Explicit TN-create payload — only the fields the backend/TN consume.
      // The edited title goes in name.es, the exact path
      // `tn_publish_service.publish_product` reads for the TN payload and the
      // local mirror. Reconcile-only row fields (verdict, tn_matches, tn_presence,
      // …) are deliberately NOT spread in — `publish_product` does
      // `payload = dict(product_data)`, so they would leak into the TN create.
      // `price` here is the exact string already shown in the preview — never
      // recomputed here, so what the operator saw is what gets submitted.
      // NOTE: `publish_product` moves this price onto the TN variant (along
      // with `ean` as the variant `sku`) before it reaches TN — the TN read
      // path only ever reads `variant["price"]`, and the idempotency/
      // read-back logic depends on the variant having a SKU. This root-level
      // field is just the transport shape into the backend, not the final
      // TN payload shape.
      // Sent as a STRING (never a JS number). To be precise about what that
      // buys: the surcharge itself was already computed in float64, so this
      // does NOT make the arithmetic exact — it is rounded to the cent at
      // that point and correct there. What the string protects is everything
      // downstream: JSON transport and the backend's `Decimal(str(...))`
      // boundary receive the exact cents shown to the operator, with no
      // second float round-trip on the way in.
      const productData = { name: { es: title.trim() }, price: finalPrice };
      const response = await api.post('/tienda-nube-reconcile/publicar', {
        ean,
        product_data: productData,
        category_id: selectedCategory?.id ?? null,
        description_html: descriptionHtml,
        image_srcs: images.map((img) => img.src),
        offset_percent: hasWebPrice ? Number(offsetPercent) : null,
        price_base_source: priceBaseSource,
      });
      setConfirming(false);
      onPublished?.(ean, response.data);
    } catch (err) {
      setSubmitError(err?.response?.data?.error?.message || err?.message || 'Error al publicar el producto');
    } finally {
      setSubmitting(false);
    }
  }, [
    submitting,
    editor,
    ean,
    title,
    selectedCategory,
    images,
    onPublished,
    finalPrice,
    hasWebPrice,
    offsetPercent,
    priceBaseSource,
  ]);

  if (!isOpen) return null;

  return (
    <ModalTesla
      isOpen={isOpen}
      onClose={onClose}
      title="Publicar producto en Tienda Nube"
      subtitle={ean ? `EAN ${ean}` : undefined}
      size="xl"
    >
      {loadError && <div className={styles.errorBanner}>{loadError}</div>}
      {submitError && <div className={styles.errorBanner}>{submitError}</div>}

      {/* ------------------------------------------------------ Título --- */}
      <div className={styles.section}>
        <label className={styles.sectionTitle} htmlFor="tn-publish-title">
          Título
        </label>
        <input
          id="tn-publish-title"
          type="text"
          className={styles.titleInput}
          value={title}
          maxLength={255}
          placeholder="Título del producto en Tienda Nube"
          onChange={(e) => setTitle(e.target.value)}
        />
        {title.trim().length === 0 && (
          <p className={styles.fieldHint}>El título no puede quedar vacío.</p>
        )}
      </div>

      {/* --------------------------------------------------- Categoría --- */}
      <div className={styles.section}>
        <h3 className={styles.sectionTitle}>Categoría</h3>
        {loadingSuggestion ? (
          <p className={styles.fieldHint}>Buscando categoría sugerida...</p>
        ) : (
          <>
            {suggestions.length > 0 && (
              <div role="radiogroup" aria-label="Categoría TN sugerida" className={styles.categoryList}>
                {suggestions.map((s, idx) => (
                  <label key={s.tn_category_id} className={styles.categoryOption}>
                    <input
                      type="radio"
                      name="tn-category"
                      checked={selectedCategory?.id === s.tn_category_id}
                      onChange={() =>
                        setSelectedCategory({ id: s.tn_category_id, path: s.category_path_text })
                      }
                    />
                    <span className={idx === 0 ? styles.categoryTop : ''}>
                      {s.category_path_text}
                      <span className={styles.categorySimilarity}> ({Math.round(s.similarity * 100)}%)</span>
                    </span>
                  </label>
                ))}
                {selectionOutsideSuggestions && (
                  <label className={styles.categoryOption}>
                    <input type="radio" name="tn-category" checked readOnly />
                    <span className={styles.categoryTop}>{selectedCategory.path}</span>
                    <span className={styles.categoryPickedTag}>elegida por búsqueda</span>
                  </label>
                )}
              </div>
            )}

            <div className={styles.categorySearchBlock}>
              <label className={styles.searchLabel} htmlFor="tn-category-search">
                {suggestions.length > 0 ? 'Buscar otra categoría por nombre' : 'Buscar categoría por nombre'}
              </label>
              <div className={styles.searchInputWrap}>
                <Search size={14} className={styles.searchIcon} aria-hidden="true" />
                <input
                  id="tn-category-search"
                  type="search"
                  className={styles.searchInput}
                  value={categoryQuery}
                  placeholder="Ej.: Electrónica > Auriculares"
                  autoComplete="off"
                  onChange={(e) => setCategoryQuery(e.target.value)}
                />
              </div>
              {searching && <p className={styles.fieldHint}>Buscando categorías...</p>}
              {searchError && <p className={styles.fieldError}>{searchError}</p>}
              {!searching && searchResults.length > 0 && (
                <ul className={styles.searchResults}>
                  {searchResults.map((result) => (
                    <li key={result.tn_category_id}>
                      <button
                        type="button"
                        className={styles.searchResultBtn}
                        onClick={() => pickSearchResult(result)}
                      >
                        {result.category_path}
                      </button>
                    </li>
                  ))}
                </ul>
              )}
              {!searching &&
                searchResults.length === 0 &&
                debouncedCategoryQuery.trim().length >= 2 &&
                !searchError && <p className={styles.fieldHint}>Sin resultados para esa búsqueda.</p>}
            </div>

            {selectedCategory != null ? (
              <p className={styles.selectedCategory}>
                <Check size={13} aria-hidden="true" />
                <span>
                  Categoría seleccionada: <strong>{selectedCategory.path}</strong>
                </span>
              </p>
            ) : (
              <p className={styles.fieldHint}>
                Elegí una categoría sugerida o buscala por nombre para poder publicar.
              </p>
            )}
          </>
        )}
      </div>

      {/* ---------------------------------------------------- Imágenes --- */}
      <div className={styles.section}>
        <h3 className={styles.sectionTitle}>Imágenes ({images.length})</h3>
        {images.length === 0 ? (
          <p className={styles.fieldHint}>Sin imágenes para publicar.</p>
        ) : (
          <>
            <p className={styles.fieldHint}>
              Arrastrá para reordenar (o con teclado: espacio para levantar, flechas para mover). La
              primera imagen es la portada.
            </p>
            <DndContext sensors={sensors} collisionDetection={closestCenter} onDragEnd={handleDragEnd}>
              <SortableContext items={imageIds} strategy={rectSortingStrategy}>
                <ul className={styles.imageGrid} aria-label="Imágenes del producto (ordenables)">
                  {images.map((image, index) => (
                    <SortableImageTile key={image.id} image={image} index={index} onDelete={deleteImage} />
                  ))}
                </ul>
              </SortableContext>
            </DndContext>
          </>
        )}
      </div>

      {/* ------------------------------------------------- Descripción --- */}
      <div className={styles.section}>
        <h3 className={styles.sectionTitle}>Descripción</h3>
        <div className={styles.editorShell}>
          <div className={styles.toolbar} role="toolbar" aria-label="Formato de la descripción">
            <ToolbarButton
              label="Negrita"
              active={editorState?.bold}
              onClick={() => editor?.chain().focus().toggleBold().run()}
            >
              <Bold size={15} aria-hidden="true" />
            </ToolbarButton>
            <ToolbarButton
              label="Cursiva"
              active={editorState?.italic}
              onClick={() => editor?.chain().focus().toggleItalic().run()}
            >
              <Italic size={15} aria-hidden="true" />
            </ToolbarButton>
            <ToolbarButton
              label="Subrayado"
              active={editorState?.underline}
              onClick={() => editor?.chain().focus().toggleUnderline().run()}
            >
              <Underline size={15} aria-hidden="true" />
            </ToolbarButton>
            <ToolbarButton
              label="Tachado"
              active={editorState?.strike}
              onClick={() => editor?.chain().focus().toggleStrike().run()}
            >
              <Strikethrough size={15} aria-hidden="true" />
            </ToolbarButton>
            <span className={styles.toolbarDivider} aria-hidden="true" />
            <ToolbarButton
              label="Título 1"
              active={editorState?.h1}
              onClick={() => editor?.chain().focus().toggleHeading({ level: 1 }).run()}
            >
              <Heading1 size={15} aria-hidden="true" />
            </ToolbarButton>
            <ToolbarButton
              label="Título 2"
              active={editorState?.h2}
              onClick={() => editor?.chain().focus().toggleHeading({ level: 2 }).run()}
            >
              <Heading2 size={15} aria-hidden="true" />
            </ToolbarButton>
            <ToolbarButton
              label="Título 3"
              active={editorState?.h3}
              onClick={() => editor?.chain().focus().toggleHeading({ level: 3 }).run()}
            >
              <Heading3 size={15} aria-hidden="true" />
            </ToolbarButton>
            <ToolbarButton
              label="Párrafo"
              active={editorState?.paragraph && !editorState?.bulletList && !editorState?.orderedList}
              onClick={() => editor?.chain().focus().setParagraph().run()}
            >
              <Pilcrow size={15} aria-hidden="true" />
            </ToolbarButton>
            <span className={styles.toolbarDivider} aria-hidden="true" />
            <ToolbarButton
              label="Lista con viñetas"
              active={editorState?.bulletList}
              onClick={() => editor?.chain().focus().toggleBulletList().run()}
            >
              <List size={15} aria-hidden="true" />
            </ToolbarButton>
            <ToolbarButton
              label="Lista numerada"
              active={editorState?.orderedList}
              onClick={() => editor?.chain().focus().toggleOrderedList().run()}
            >
              <ListOrdered size={15} aria-hidden="true" />
            </ToolbarButton>
          </div>
          <EditorContent editor={editor} className={styles.editorContent} />
        </div>
      </div>

      {/* ------------------------------------------------- Precio ------- */}
      <div className={styles.section}>
        <h3 className={styles.sectionTitle}>Precio de publicación</h3>
        {hasWebPrice ? (
          <>
            <p className={styles.fieldHint}>
              Base: precio web transferencia (${basePrice.toFixed(2)})
            </p>
            <label className={styles.searchLabel} htmlFor="tn-publish-offset">
              Recargo (%)
            </label>
            <input
              id="tn-publish-offset"
              type="number"
              className={styles.titleInput}
              value={offsetPercent}
              min={0}
              step="0.01"
              onChange={(e) => setOffsetPercent(e.target.value === '' ? '' : Number(e.target.value))}
            />
            <p className={styles.selectedCategory}>
              <Check size={13} aria-hidden="true" />
              <span>
                Precio final a publicar: <strong>${computedPrice ?? '—'}</strong>
              </span>
            </p>
          </>
        ) : (
          <>
            <p className={styles.fieldHint}>
              Base: precio lista ML (Clásica) — no hay precio web transferencia para
              este producto. Editá el precio antes de publicar.
            </p>
            <label className={styles.searchLabel} htmlFor="tn-publish-manual-price">
              Precio de publicación
            </label>
            <input
              id="tn-publish-manual-price"
              type="number"
              className={styles.titleInput}
              value={manualPrice}
              min={0}
              step="0.01"
              onChange={(e) => setManualPrice(e.target.value)}
            />
          </>
        )}
        {!finalPriceIsValid && (
          <p className={styles.fieldError}>El precio de publicación debe ser mayor a cero.</p>
        )}
      </div>

      {/* ------------------------------------------------------ Submit --- */}
      {confirming ? (
        <div className={styles.confirmBar}>
          <span className={styles.confirmQuestion}>¿Publicar este producto en Tienda Nube?</span>
          <button
            type="button"
            className="btn-tesla outline-subtle-success sm"
            disabled={submitting}
            onClick={handleConfirm}
          >
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
