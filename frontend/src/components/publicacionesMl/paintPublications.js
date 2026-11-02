import { publicacionesMlAPI } from '../../services/api';

// The backend's cap per request (`PUT /ml-publications/colors`, MAX_STATUS_ITEM_IDS).
const PAINT_BATCH = 500;

/**
 * Paints `itemIds` (MLAs) on their own on one layer (`equipoId`, null = the global one), or with a null `color` takes
 * their own color off so they show their product's again (seleccion-por-publicacion S3). Batches of at most `PAINT_BATCH`
 * (never a last one of one), one after another: each one that lands is reported to `onBatch`, shaped as the `publicacion_color:changed` event,
 * so it shows at once; the first one that fails throws and the rest are not sent.
 */
export async function paintPublications(itemIds, color, equipoId, onBatch) {
  for (let start = 0; start < itemIds.length; ) {
    // Never leave a last batch of one: the backend checks one MLA with the one-row permission, not the batch one.
    const size = itemIds.length - start === PAINT_BATCH + 1 ? PAINT_BATCH - 1 : PAINT_BATCH;
    const batch = itemIds.slice(start, start + size);
    start += size;
    await publicacionesMlAPI.paintColors({ item_ids: batch, color, ...(equipoId !== null && { equipo_id: equipoId }) });
    onBatch?.({ data: { is_global: equipoId === null, equipo_id: equipoId, item_ids: batch, color } });
  }
}
