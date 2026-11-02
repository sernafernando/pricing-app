import { publicacionesMlAPI } from '../../services/api';

// The backend's cap per request (`PUT /ml-publications/colors`, MAX_STATUS_ITEM_IDS).
export const PAINT_BATCH = 500;

/**
 * Paints `itemIds` (MLAs) on their own on one layer (`equipoId`, null = the global one), or with a null `color` takes
 * their own color off so they show their product's again (seleccion-por-publicacion S3). Batches of `PAINT_BATCH`,
 * one after another: each one that lands is reported to `onBatch`, shaped as the `publicacion_color:changed` event,
 * so it shows at once; the first one that fails throws and the rest are not sent.
 */
export async function paintPublications(itemIds, color, equipoId, onBatch) {
  for (let start = 0; start < itemIds.length; start += PAINT_BATCH) {
    const batch = itemIds.slice(start, start + PAINT_BATCH);
    await publicacionesMlAPI.paintColors({ item_ids: batch, color, ...(equipoId !== null && { equipo_id: equipoId }) });
    onBatch?.({ data: { is_global: equipoId === null, equipo_id: equipoId, item_ids: batch, color } });
  }
}
