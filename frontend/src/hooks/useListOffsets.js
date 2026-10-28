import { useMemo } from 'react';
import { useOffsetsVigentes } from './useOffsetsVigentes';
import { useUsdRate } from './useUsdRate';

/**
 * The offsets the list's clásica cells apply (Productos' "markup con offsets"),
 * as the Precios tab applies them: the Mercado Libre channel only, and the USD
 * rate pricing converts costs with (`tipoCambio` null until it arrives, never an
 * assumed one). Read only when `enabled`; null while they load, when none is
 * current, or when they cannot be read. The same object until the offsets or the
 * rate change, so the columns built from it stay stable.
 */
export function useListOffsets(enabled) {
  const contexto = useOffsetsVigentes(enabled);
  const current = Boolean(contexto && contexto.offsets.length > 0);
  const rate = useUsdRate(current);
  return useMemo(() => (current ? { ...contexto, canal: 'ml', tipoCambio: rate ?? null } : null), [current, contexto, rate]);
}
