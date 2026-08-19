/**
 * usePublishSubmit — the `POST /publicar` submit, in-flight guard and error
 * surface, moved verbatim out of the pre-decomposition `TnPublishModal.jsx`.
 */
import { useState, useCallback } from 'react';
import { sanitizeHtml } from '../../../utils/sanitizeHtml';
import api from '../../../services/api';

// Headings the toolbar can produce — must survive the frontend sanitize pass
// (the backend's nh3 allowlist already permits h1–h6, so nothing is lost
// server-side either).
const DESCRIPTION_EXTRA_TAGS = ['h1', 'h2', 'h3'];

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

  return { confirming, submitting, submitError, handlePublishClick, handleCancelConfirm, handleConfirm };
}
