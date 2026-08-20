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
            backendReasons={draftBlockedReasons}
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
