import { useCallback, useState } from 'react';
import useCheques from './useCheques';

/**
 * useChequesAplicables — cheques propios elegibles para "aplicar" a un
 * proveedor (S4 — compras-cheque-propio-aplicable-a-op).
 *
 * Elegible = tipo=propio, sin_orden_pago=true, proveedor_id=<proveedor>,
 * estado emitido O diferido.
 *
 * API CONSTRAINT: `listar_cheques` acepta un único `estado`, así que se hacen
 * DOS llamadas (emitido / diferido) y se mergean del lado del cliente. NO se
 * toca el backend por esto — la S4 es puramente frontend.
 *
 * Compartido entre PanelCheques (armar OP nueva) y TabCheques (aplicar un
 * cheque existente a una OP pendiente) para que ambos entry points miren
 * exactamente la misma definición de "elegible".
 */
export default function useChequesAplicables() {
  const { listar } = useCheques();
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState(null);

  const fetchElegibles = useCallback(
    async (proveedorId) => {
      if (!proveedorId) return [];
      setLoading(true);
      setError(null);
      try {
        const params = {
          tipo: 'propio',
          proveedor_id: proveedorId,
          sin_orden_pago: true,
          page_size: 200,
        };
        const [emitidos, diferidos] = await Promise.all([
          listar({ ...params, estado: 'emitido' }),
          listar({ ...params, estado: 'diferido' }),
        ]);
        const itemsEmitidos = emitidos?.items ?? (Array.isArray(emitidos) ? emitidos : []);
        const itemsDiferidos = diferidos?.items ?? (Array.isArray(diferidos) ? diferidos : []);
        return [...itemsEmitidos, ...itemsDiferidos];
      } catch (err) {
        setError(err);
        return [];
      } finally {
        setLoading(false);
      }
    },
    [listar],
  );

  return { fetchElegibles, loading, error };
}
