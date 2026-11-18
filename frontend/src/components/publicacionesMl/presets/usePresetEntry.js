import { useEffect, useMemo, useState } from 'react';
import { sanitizeLayout } from './columnLayout';

/**
 * What the remembered preset does when a view opens (pubml-columnas-presets S6, owner: "Gana el link"):
 *  - a URL with filters or a sort (`hasListParams`, read when the view opens) wins: its params stay, the preset gives
 *    only its columns (when the view has no saved layout of its own) and shows as modified;
 *  - otherwise the remembered preset's params are applied (filters, sort, modo, agrupar, familias and its layer, S8).
 * The saved layout of the view (`store.columns`) is the user's last word on columns either way.
 * `pending` holds the rows (the page adds it to the layer wait) until a preset may still change the URL, so the first
 * request already carries the preset's filters. `onApplied` lets the page drop its default-layer step.
 */
export default function usePresetEntry({ vista, store, presets, hasListParams, applyPresetParams, onApplied }) {
  const [entry, setEntry] = useState(() => ({ vista, hadParams: hasListParams, done: false }));
  // A new view is a new entry, decided on the URL as it is right now.
  const current = useMemo(
    () => (entry.vista === vista ? entry : { vista, hadParams: hasListParams, done: false }),
    [entry, vista, hasListParams],
  );
  if (entry !== current) setEntry(current);

  const ready = store.loaded && presets.loaded;
  useEffect(() => {
    if (current.done || !ready) return;
    const remembered = presets.items.find((preset) => preset.id === store.presetId);
    if (remembered) {
      if (!store.columns && remembered.payload?.columns) store.save(sanitizeLayout(remembered.payload.columns), remembered.id, { persist: false });
      if (!current.hadParams) {
        applyPresetParams(remembered.payload?.params ?? {}, { replace: true });
        onApplied?.();
      }
    }
    setEntry({ ...current, done: true });
  }, [current, ready, presets.items, store, applyPresetParams, onApplied]);

  return { pending: !current.done && !current.hadParams };
}
