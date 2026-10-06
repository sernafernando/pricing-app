import { useTiendasOficialesStore } from '../store/tiendasOficialesStore';

// Mirrors the migration seed (`ml_tiendas_oficiales`), minus the new TP-Link id.
export const TIENDAS_FIXTURE = [
  { store_id: 57997, nombre: 'Gauss', clave: null, orden: 0, activa: true },
  { store_id: 2645, nombre: 'TP-Link', clave: 'tplink', orden: 1, activa: true },
  { store_id: 144, nombre: 'Forza/Verbatim', clave: null, orden: 3, activa: true },
  { store_id: 191942, nombre: 'Multi-marca', clave: null, orden: 4, activa: true },
];

/** Puts the shared store in the "already fetched" state so no request is made. */
export function seedTiendasOficiales(tiendas = TIENDAS_FIXTURE) {
  useTiendasOficialesStore.setState({ tiendas, loaded: true, loading: false });
}

export function resetTiendasOficiales() {
  useTiendasOficialesStore.setState({ tiendas: [], loaded: false, loading: false });
}
