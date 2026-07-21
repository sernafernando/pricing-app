import { useState } from 'react';
import api from '../services/api';

/**
 * Manages product selection state and color-marking actions.
 * Mirrors useTiendaSelection — receives { productos, setProductos, cargarStats, showToast }.
 */
export function useProductosSeleccion({ productos, setProductos, cargarStats, showToast, equipoActivoId }) {
  const [productosSeleccionados, setProductosSeleccionados] = useState(new Set());
  const [ultimoSeleccionado, setUltimoSeleccionado] = useState(null);
  const [colorDropdownAbierto, setColorDropdownAbierto] = useState(null);

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
        '/productos/actualizar-color-lote',
        {
          item_ids: Array.from(productosSeleccionados),
          color: color,
          equipo_id: equipoActivoId || undefined
        }
      );

      setProductos(prods => prods.map(p =>
        productosSeleccionados.has(p.item_id)
          ? { ...p, color_marcado: color }
          : p
      ));

      limpiarSeleccion();
      cargarStats();
    } catch {
      showToast('Error al actualizar colores en lote', 'error');
    }
  };

  const cambiarColorProducto = async (itemId, color) => {
    try {
      await api.patch(
        `/productos/${itemId}/color`,
        { color, equipo_id: equipoActivoId || undefined }
      );

      // Actualizar estado local en lugar de recargar
      setProductos(prods => prods.map(p =>
        p.item_id === itemId
          ? { ...p, color_marcado: color }
          : p
      ));

      setColorDropdownAbierto(null);

      // Recargar stats para reflejar cambios en contadores
      cargarStats();
    } catch {
      showToast('Error al cambiar el color', 'error');
    }
  };

  const cambiarColorRapido = async (itemId, color) => {
    try {
      await api.patch(
        `/productos/${itemId}/color`,
        { color, equipo_id: equipoActivoId || undefined }
      );

      // Actualizar estado local en lugar de recargar
      setProductos(prods => prods.map(p =>
        p.item_id === itemId
          ? { ...p, color_marcado: color }
          : p
      ));

      // Recargar stats para reflejar cambios en contadores
      cargarStats();
    } catch {
      // silenced
    }
  };

  return {
    productosSeleccionados,
    ultimoSeleccionado,
    colorDropdownAbierto,
    setColorDropdownAbierto,
    toggleSeleccion,
    seleccionarTodos,
    limpiarSeleccion,
    pintarLote,
    cambiarColorProducto,
    cambiarColorRapido,
  };
}
