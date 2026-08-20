/**
 * PublisherLeftPane — the left column of cards (PR-9 design item b), moved
 * out of `TnPublishModal.jsx` verbatim (prop-passthrough only, zero
 * behavior change) purely to keep the shell under the ~200-line ceiling.
 */
import ProductFieldsSection from './ProductFieldsSection';
import VariantFieldsSection from './VariantFieldsSection';
import CategorySection from './CategorySection';
import DescriptionSeoCard from './DescriptionSeoCard';
import ImageGallery from './ImageGallery';
import MeasurementSection from './MeasurementSection';
import styles from './TnPublishModal.module.css';
import shellStyles from './TnPublisherShell.module.css';

export default function PublisherLeftPane({
  loadError,
  submitError,
  title,
  setTitle,
  titleInputRef,
  draftFields,
  row,
  profiles,
  loadingProfiles,
  profileError,
  selectedProfileId,
  setSelectedProfileId,
  clearProfile,
  hasWebPrice,
  basePrice,
  offsetPercent,
  setOffsetPercent,
  loadingOffset,
  offsetError,
  manualPrice,
  setManualPrice,
  finalPriceIsValid,
  loadingSuggestion,
  suggestions,
  suggestionEmptyReason,
  selectedCategory,
  setSelectedCategory,
  selectionOutsideSuggestions,
  categoryQuery,
  setCategoryQuery,
  debouncedCategoryQuery,
  searchResults,
  searching,
  searchError,
  pickSearchResult,
  catalogEmpty,
  catalogCapHit,
  syncingCategories,
  syncResult,
  syncError,
  syncCategories,
  images,
  imageIds,
  handleDragEnd,
  deleteImage,
  editor,
  editorState,
}) {
  return (
    <div className={shellStyles.leftPane}>
      {loadError && <div className={styles.errorBanner}>{loadError}</div>}
      {submitError && <div className={styles.errorBanner}>{submitError}</div>}

      <ProductFieldsSection
        title={title}
        onTitleChange={setTitle}
        titleInputRef={titleInputRef}
        brand={draftFields.brand}
        onBrandChange={(v) => draftFields.setField('brand', v)}
        barcode={draftFields.barcode}
        onBarcodeChange={(v) => draftFields.setField('barcode', v)}
        sku={draftFields.sku}
        onSkuChange={(v) => draftFields.setField('sku', v)}
        visibility={draftFields.visibility}
        onVisibilityChange={(v) => draftFields.setField('visibility', v)}
        freeShipping={draftFields.freeShipping}
        onFreeShippingChange={(v) => draftFields.setField('freeShipping', v)}
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
        categoria={row?.categoria}
      />

      <VariantFieldsSection
        hasWebPrice={hasWebPrice}
        basePrice={basePrice}
        offsetPercent={offsetPercent}
        setOffsetPercent={setOffsetPercent}
        loadingOffset={loadingOffset}
        offsetError={offsetError}
        manualPrice={manualPrice}
        setManualPrice={setManualPrice}
        finalPriceIsValid={finalPriceIsValid}
        cost={draftFields.cost}
        onCostChange={(v) => draftFields.setField('cost', v)}
        stock={draftFields.stock}
        onStockChange={(v) => draftFields.setField('stock', v)}
        promotionalPrice={draftFields.promotionalPrice}
        onPromotionalPriceChange={(v) => draftFields.setField('promotionalPrice', v)}
      />

      <CategorySection
        loadingSuggestion={loadingSuggestion}
        suggestions={suggestions}
        suggestionEmptyReason={suggestionEmptyReason}
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
        catalogCapHit={catalogCapHit}
        syncingCategories={syncingCategories}
        syncResult={syncResult}
        syncError={syncError}
        syncCategories={syncCategories}
      />

      <div className={shellStyles.card}>
        <h3 className={shellStyles.cardTitle}>Imágenes</h3>
        <ImageGallery images={images} imageIds={imageIds} onDragEnd={handleDragEnd} onDelete={deleteImage} />
      </div>

      <DescriptionSeoCard
        editor={editor}
        editorState={editorState}
        seoTitle={draftFields.seoTitle}
        onSeoTitleChange={(v) => draftFields.setField('seoTitle', v)}
        seoDescription={draftFields.seoDescription}
        onSeoDescriptionChange={(v) => draftFields.setField('seoDescription', v)}
        tags={draftFields.tags}
        onTagsChange={(v) => draftFields.setField('tags', v)}
      />
    </div>
  );
}
