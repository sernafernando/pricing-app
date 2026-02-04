import { useState } from 'react';
import api from '../services/api';

/**
 * Custom hook para manejar la selección múltiple y operaciones por lote en Tienda.
 * Incluye: toggle selección, seleccionar todos, limpiar, pintar lote.
 *
 * @param {Object} params
 * @param {Array} params.productos - Array actual de productos
 * @param {Function} params.setProductos - Setter del array de productos
 * @param {Function} params.cargarStats - Recarga estadísticas
 * @param {Function} params.showToast - Función de notificación
 */
export function useTiendaSelection({
  productos,
  setProductos,
  cargarStats,
  showToast,
}) {

  const [productosSeleccionados, setProductosSeleccionados] = useState(new Set());
  const [ultimoSeleccionado, setUltimoSeleccionado] = useState(null);

  const toggleSeleccion = (itemId, shiftKey) => {
    const nuevaSeleccion = new Set(productosSeleccionados);

    if (shiftKey && ultimoSeleccionado !== null) {
      // Selección con Shift: seleccionar rango
      const indices = productos.map(p => p.item_id);
      const indiceActual = indices.indexOf(itemId);
      const indiceUltimo = indices.indexOf(ultimoSeleccionado);

      const inicio = Math.min(indiceActual, indiceUltimo);
      const fin = Math.max(indiceActual, indiceUltimo);

      for (let i = inicio; i <= fin; i++) {
        nuevaSeleccion.add(indices[i]);
      }
    } else {
      // Toggle individual
      if (nuevaSeleccion.has(itemId)) {
        nuevaSeleccion.delete(itemId);
      } else {
        nuevaSeleccion.add(itemId);
      }
    }

    setProductosSeleccionados(nuevaSeleccion);
    setUltimoSeleccionado(itemId);
  };

  const seleccionarTodos = () => {
    if (productosSeleccionados.size === productos.length) {
      setProductosSeleccionados(new Set());
    } else {
      setProductosSeleccionados(new Set(productos.map(p => p.item_id)));
    }
  };

  const limpiarSeleccion = () => {
    setProductosSeleccionados(new Set());
    setUltimoSeleccionado(null);
  };

  const pintarLote = async (color) => {
    try {

      await api.post(
        `/productos/actualizar-color-tienda-lote`,
        {
          item_ids: Array.from(productosSeleccionados),
          color: color
        }
      );

      setProductos(prods => prods.map(p =>
        productosSeleccionados.has(p.item_id)
          ? { ...p, color_marcado_tienda: color }
          : p
      ));

      limpiarSeleccion();
      cargarStats();
    } catch {
      showToast('Error al actualizar colores en lote', 'error');
    }
  };

  return {
    productosSeleccionados,
    toggleSeleccion,
    seleccionarTodos,
    limpiarSeleccion,
    pintarLote,
  };
}
