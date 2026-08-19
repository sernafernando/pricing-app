/**
 * TnPublishModal — publish form for a FALTA_PUBLICAR row (Sub-slice 3c,
 * rebuilt UI; decomposed in PR-6 — pure refactor, zero behavior change).
 *
 * The `row` prop is the ALREADY-ENRICHED reconciliation row returned by
 * `GET /tienda-nube-reconcile/reporte` — it carries `ml_title`, `ml_desc`,
 * `images` (ordered, empty slots already filtered server-side), `categoria`
 * and `subcategoria` directly. This modal reads those off the row it already
 * has; it does NOT call `/gbp-parser` or do any client-side EAN matching.
 *
 * This shell wires four hooks (`usePublishFields`, `useCategoryPicker`,
 * `useMarkupOffset`, `usePublishSubmit`, plus `useDescriptionEditor` for
 * TipTap) into six presentational sections. See
 * `frontend/src/components/tn-publisher/*` for each piece and
 * `openspec/changes/tn-publisher-module/design.md`'s file table for the
 * intended shape.
 *
 * Submit requires an inline Confirmar/Cancelar step (mirrors the Despublicar
 * pattern in `TiendaNubeReconcile.jsx` — NEVER `window.confirm`) and locks
 * the button while in flight to prevent a double-submit. Permission gating
 * (`admin.gestionar_tn_publicacion`) happens at the caller — this modal is
 * only ever rendered for operators holding it.
 */
import { useMemo, useRef } from 'react';
import ModalTesla from '../ModalTesla';
import { usePublishFields } from './hooks/usePublishFields';
import { useCategoryPicker } from './hooks/useCategoryPicker';
import { useMarkupOffset } from './hooks/useMarkupOffset';
import { usePublishSubmit } from './hooks/usePublishSubmit';
import { useDescriptionEditor } from './hooks/useDescriptionEditor';
import { useDraftFields, MEASUREMENT_FIELDS } from './hooks/useDraftFields';
import { useMeasurementProfile } from './hooks/useMeasurementProfile';
import ProductFieldsSection from './ProductFieldsSection';
import VariantFieldsSection from './VariantFieldsSection';
import CategorySection from './CategorySection';
import DescriptionEditor from './DescriptionEditor';
import ImageGallery from './ImageGallery';
import MeasurementSection from './MeasurementSection';
import styles from './TnPublishModal.module.css';

export default function TnPublishModal({ row, isOpen, onClose, onPublished }) {
  const ean = row?.ean;
  const titleInputRef = useRef(null);

  const { title, setTitle, images, imageIds, handleDragEnd, deleteImage, manualPrice, setManualPrice } =
    usePublishFields(row);

  const {
    loadingSuggestion,
    loadError,
    suggestions,
    selectedCategory,
    setSelectedCategory,
    categoryQuery,
    setCategoryQuery,
    debouncedCategoryQuery,
    searchResults,
    searching,
    searchError,
    pickSearchResult,
    selectionOutsideSuggestions,
  } = useCategoryPicker({ isOpen, ean, row });

  const { editor, editorState } = useDescriptionEditor({ isOpen, ean, initialHtml: row?.ml_desc });

  const draftFields = useDraftFields(row);
  const {
    profiles,
    loadingProfiles,
    profileError,
    selectedProfileId,
    setSelectedProfileId,
    clearProfile,
  } = useMeasurementProfile({ isOpen, suggestedProfileId: row?.publish_draft?.suggested_profile_id ?? null });

  const publishFieldsError = row?.publish_fields_error ?? null;
  const missingMeasurementFields = MEASUREMENT_FIELDS.filter(
    (f) => draftFields[f] === '' || draftFields[f] == null
  );
  // The backend's own verdict for this row (D3 measurements AND D6 cost)
  // is authoritative — the local `missingMeasurementFields` check only keeps
  // the UI live while the operator edits. Ignoring `draft.blocked` let an
  // item the backend had blocked for an unresolvable USD cost sail through
  // to a publish that then failed (or shipped a null cost) with nothing
  // naming the missing rate.
  const draftBlocked = row?.publish_draft?.blocked === true;
  const draftBlockedReasons = row?.publish_draft?.blocked_reasons || [];
  const measurementsBlocked =
    publishFieldsError != null || missingMeasurementFields.length > 0 || draftBlocked;

  // Precio de publicación (Slice 2, money path) — see VariantFieldsSection
  // for the full two-base rule. `hasWebPrice` selects the surcharge path vs.
  // the manual-entry fallback.
  const hasWebPrice =
    row?.precio_web_transferencia != null &&
    row?.precio_web_transferencia !== '' &&
    row?.participa_web_transferencia === true;

  const { offsetPercent, setOffsetPercent, loadingOffset, offsetError } = useMarkupOffset({ isOpen, hasWebPrice });

  const basePrice = hasWebPrice ? Number(row.precio_web_transferencia) : null;
  const computedPrice = useMemo(() => {
    if (!hasWebPrice || basePrice == null || Number.isNaN(basePrice)) return null;
    // `null` (config not loaded / failed) and `''` (operator cleared the box)
    // are checked BEFORE Number(): both coerce to 0, which would quietly
    // publish at the bare base price instead of blocking.
    if (offsetPercent === null || offsetPercent === '') return null;
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

  const { confirming, submitting, submitError, handlePublishClick, handleCancelConfirm, handleConfirm } =
    usePublishSubmit({
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
      draftFields,
      monedaCosto: row?.moneda_costo ?? null,
      categoria: row?.categoria ?? null,
      subcategoria: row?.subcategoria ?? null,
    });

  const canPublish =
    selectedCategory != null &&
    title.trim().length > 0 &&
    !loadingSuggestion &&
    !submitting &&
    finalPriceIsValid &&
    !measurementsBlocked;

  if (!isOpen) return null;

  return (
    <ModalTesla
      isOpen={isOpen}
      onClose={onClose}
      title="Publicar producto en Tienda Nube"
      subtitle={ean ? `EAN ${ean}` : undefined}
      size="xl"
      initialFocusRef={titleInputRef}
    >
      {loadError && <div className={styles.errorBanner}>{loadError}</div>}
      {submitError && <div className={styles.errorBanner}>{submitError}</div>}

      <ProductFieldsSection
        title={title}
        onTitleChange={setTitle}
        brand={draftFields.brand}
        onBrandChange={(v) => draftFields.setField('brand', v)}
        visibility={draftFields.visibility}
        onVisibilityChange={(v) => draftFields.setField('visibility', v)}
        freeShipping={draftFields.freeShipping}
        onFreeShippingChange={(v) => draftFields.setField('freeShipping', v)}
        seoTitle={draftFields.seoTitle}
        onSeoTitleChange={(v) => draftFields.setField('seoTitle', v)}
        seoDescription={draftFields.seoDescription}
        onSeoDescriptionChange={(v) => draftFields.setField('seoDescription', v)}
        tags={draftFields.tags}
        onTagsChange={(v) => draftFields.setField('tags', v)}
        titleInputRef={titleInputRef}
      />

      <CategorySection
        loadingSuggestion={loadingSuggestion}
        suggestions={suggestions}
        selectedCategory={selectedCategory}
        setSelectedCategory={setSelectedCategory}
        selectionOutsideSuggestions={selectionOutsideSuggestions}
        categoryQuery={categoryQuery}
        setCategoryQuery={setCategoryQuery}
        debouncedCategoryQuery={debouncedCategoryQuery}
        searchResults={searchResults}
        searching={searching}
        searchError={searchError}
        pickSearchResult={pickSearchResult}
      />

      <ImageGallery images={images} imageIds={imageIds} onDragEnd={handleDragEnd} onDelete={deleteImage} />

      <DescriptionEditor editor={editor} editorState={editorState} />

      <VariantFieldsSection
        hasWebPrice={hasWebPrice}
        basePrice={basePrice}
        offsetPercent={offsetPercent}
        setOffsetPercent={setOffsetPercent}
        loadingOffset={loadingOffset}
        offsetError={offsetError}
        computedPrice={computedPrice}
        manualPrice={manualPrice}
        setManualPrice={setManualPrice}
        finalPriceIsValid={finalPriceIsValid}
        sku={draftFields.sku}
        onSkuChange={(v) => draftFields.setField('sku', v)}
        barcode={draftFields.barcode}
        onBarcodeChange={(v) => draftFields.setField('barcode', v)}
        cost={draftFields.cost}
        onCostChange={(v) => draftFields.setField('cost', v)}
        stock={draftFields.stock}
        onStockChange={(v) => draftFields.setField('stock', v)}
        promotionalPrice={draftFields.promotionalPrice}
        onPromotionalPriceChange={(v) => draftFields.setField('promotionalPrice', v)}
      />

      <MeasurementSection
        fields={draftFields}
        setField={draftFields.setField}
        profiles={profiles}
        loadingProfiles={loadingProfiles}
        profileError={profileError}
        selectedProfileId={selectedProfileId}
        setSelectedProfileId={setSelectedProfileId}
        onApplyProfile={draftFields.applyProfile}
        onClearProfile={clearProfile}
        missingFields={missingMeasurementFields}
        blocked={measurementsBlocked && !publishFieldsError}
        backendReasons={draftBlockedReasons}
        publishFieldsError={publishFieldsError}
      />

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
