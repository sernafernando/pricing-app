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
import { useRef } from 'react';
import ModalTesla from '../ModalTesla';
import { usePublishFields } from './hooks/usePublishFields';
import { useCategoryPicker } from './hooks/useCategoryPicker';
import { usePublishPricing } from './hooks/usePublishPricing';
import { usePublishSubmit } from './hooks/usePublishSubmit';
import { useDescriptionEditor } from './hooks/useDescriptionEditor';
import { useDraftFields, MEASUREMENT_FIELDS } from './hooks/useDraftFields';
import { useMeasurementProfile } from './hooks/useMeasurementProfile';
import PublisherHeader from './PublisherHeader';
import PublisherLeftPane from './PublisherLeftPane';
import RightSummaryPane from './RightSummaryPane';
import shellStyles from './TnPublisherShell.module.css';

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
    catalogEmpty,
    syncingCategories,
    syncResult,
    syncError,
    syncCategories,
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
  // Defect 1 fix: `publish_draft.blocked`/`blocked_reasons` are a SNAPSHOT
  // of the backend's verdict when `/reporte` loaded — they never recompute
  // as the operator edits. Using that stale snapshot to gate the button
  // left a resolved measurement block (the operator typed the weight in)
  // stuck forever, with a banner naming fields the panel already shows as
  // filled in. The backend now splits the two DIFFERENT block classes
  // explicitly (`cost_blocked`, additive to `blocked`/`blocked_reasons`):
  //   - measurements: the operator CAN fix them right here — the LIVE
  //     `missingMeasurementFields` (computed from `draftFields`) is
  //     authoritative, never the stale snapshot.
  //   - cost (D6, unresolvable USD `TipoCambio`): the operator CANNOT fix
  //     this in the modal — the backend's `cost_blocked` verdict stays
  //     authoritative and keeps blocking regardless of what the operator
  //     types.
  const costBlocked = row?.publish_draft?.cost_blocked === true;
  const costBlockReason = row?.publish_draft?.cost_block_reason ?? null;
  const measurementsBlocked =
    publishFieldsError != null || missingMeasurementFields.length > 0 || costBlocked;

  // Precio de publicación (Slice 2, money path) — see VariantFieldsSection
  // for the full two-base rule, extracted into `usePublishPricing`.
  const {
    hasWebPrice,
    basePrice,
    offsetPercent,
    setOffsetPercent,
    loadingOffset,
    offsetError,
    finalPrice,
    finalPriceIsValid,
    priceBaseSource,
  } = usePublishPricing({ isOpen, row, manualPrice });

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

  const suggestedProfile = profiles.find((p) => p.id === selectedProfileId) ?? null;

  return (
    <ModalTesla
      isOpen={isOpen}
      onClose={onClose}
      title={<PublisherHeader title={title} ean={ean} thumbSrc={images[0]?.src} />}
      size="full"
      bodyClassName={shellStyles.shellBody}
      initialFocusRef={titleInputRef}
    >
      <div className={shellStyles.twoPane}>
        <PublisherLeftPane
          loadError={loadError}
          submitError={submitError}
          title={title}
          setTitle={setTitle}
          titleInputRef={titleInputRef}
          draftFields={draftFields}
          row={row}
          profiles={profiles}
          loadingProfiles={loadingProfiles}
          profileError={profileError}
          selectedProfileId={selectedProfileId}
          setSelectedProfileId={setSelectedProfileId}
          clearProfile={clearProfile}
          hasWebPrice={hasWebPrice}
          basePrice={basePrice}
          offsetPercent={offsetPercent}
          setOffsetPercent={setOffsetPercent}
          loadingOffset={loadingOffset}
          offsetError={offsetError}
          manualPrice={manualPrice}
          setManualPrice={setManualPrice}
          finalPriceIsValid={finalPriceIsValid}
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
          catalogEmpty={catalogEmpty}
          syncingCategories={syncingCategories}
          syncResult={syncResult}
          syncError={syncError}
          syncCategories={syncCategories}
          images={images}
          imageIds={imageIds}
          handleDragEnd={handleDragEnd}
          deleteImage={deleteImage}
          editor={editor}
          editorState={editorState}
        />

        <div className={shellStyles.rightPane}>
          <RightSummaryPane
            selectedCategory={selectedCategory}
            draftFields={draftFields}
            publishDraftFields={row?.publish_draft?.fields}
            monedaCosto={row?.moneda_costo}
            finalPrice={finalPrice}
            measurementsBlocked={measurementsBlocked}
            publishFieldsError={publishFieldsError}
            missingMeasurementFields={missingMeasurementFields}
            backendReasons={costBlockReason ? [costBlockReason] : []}
            suggestedProfile={suggestedProfile}
            onApplyProfile={draftFields.applyProfile}
            canPublish={canPublish}
            confirming={confirming}
            submitting={submitting}
            onPublishClick={handlePublishClick}
            onConfirm={handleConfirm}
            onCancelConfirm={handleCancelConfirm}
          />
        </div>
      </div>
    </ModalTesla>
  );
}
