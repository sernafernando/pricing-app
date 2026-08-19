/**
 * usePublishSubmit — the `POST /publicar` submit, in-flight guard and error
 * surface. PR-7 additive: `draftFields` (brand/barcode/cost/stock/
 * promotional_price/visibility/free_shipping/seo fields/tags/sku/
 * measurements) ride in `product_data`; ONLY weight/width/height/depth go through the
 * dedicated `overrides` key — the server 422s any other override key
 * against `OVERRIDABLE_FIELDS` (design D5/D11).
 */
import { useState, useCallback } from 'react';
import { sanitizeHtml } from '../../../utils/sanitizeHtml';
import api from '../../../services/api';
import { MEASUREMENT_FIELDS } from './useDraftFields';

// Headings the toolbar can produce — must survive the frontend sanitize pass
// (the backend's nh3 allowlist already permits h1–h6, so nothing is lost
// server-side either).
const DESCRIPTION_EXTRA_TAGS = ['h1', 'h2', 'h3'];

function buildOverrides(draftFields) {
  const overrides = {};
  MEASUREMENT_FIELDS.forEach((field) => {
    const raw = draftFields[field];
    if (raw !== '' && raw != null && !Number.isNaN(Number(raw))) {
      // String, never Number: the backend types `overrides` as
      // `Dict[str, str]` and Pydantic v2 does NOT coerce number -> str,
      // so a float here is a guaranteed 422 the operator only sees as
      // "Error al publicar el producto".
      overrides[field] = String(Number(raw));
    }
  });
  return overrides;
}

export function usePublishSubmit({
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
}) {
  const [confirming, setConfirming] = useState(false);
  const [submitting, setSubmitting] = useState(false);
  const [submitError, setSubmitError] = useState(null);

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
      // `price` here is the exact string already shown in the preview — never
      // recomputed here, so what the operator saw is what gets submitted.
      const productData = {
        name: { es: title.trim() },
        price: finalPrice,
        brand: draftFields.brand || null,
        visibility: draftFields.visibility,
        free_shipping: draftFields.freeShipping,
        seo_title: draftFields.seoTitle || null,
        seo_description: draftFields.seoDescription || null,
        tags: draftFields.tags || null,
        sku: draftFields.sku || null,
        barcode: draftFields.barcode || null,
        cost: draftFields.cost || null,
        stock: draftFields.stock || null,
        promotional_price: draftFields.promotionalPrice || null,
      };
      const response = await api.post('/tienda-nube-reconcile/publicar', {
        ean,
        product_data: productData,
        category_id: selectedCategory?.id ?? null,
        description_html: descriptionHtml,
        image_srcs: images.map((img) => img.src),
        offset_percent: hasWebPrice ? Number(offsetPercent) : null,
        price_base_source: priceBaseSource,
        overrides: buildOverrides(draftFields),
        profile_id: draftFields.appliedProfileId ?? null,
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
    draftFields,
  ]);

  return { confirming, submitting, submitError, handlePublishClick, handleCancelConfirm, handleConfirm };
}
