import { useState, useEffect, useCallback } from 'react';
import api from '../services/api';

/**
 * useProductosKeyboard — keyboard navigation and shortcuts for Productos.
 *
 * Mirrors useTiendaKeyboard: receives grouped objects, uses granular dep arrays
 * + listener re-bind strategy so closures are always fresh (ADR-5).
 *
 * Owns:  celdaActiva, modoNavegacion, mostrarShortcutsHelp, iniciarEdicionDesdeTeclado
 * Returns: those states/setters + columnasEditables
 */
export function useProductosKeyboard({
  data,
  editing,
  toggles,
  seleccion,
  ui,
  permissions,
  showToast,
}) {
  const [celdaActiva, setCeldaActiva] = useState(null);
  const [modoNavegacion, setModoNavegacion] = useState(false);
  const [mostrarShortcutsHelp, setMostrarShortcutsHelp] = useState(false);

  // Columnas navegables según la vista activa
  const columnasNavegablesNormal = ['precio_clasica', 'precio_rebate', 'mejor_oferta', 'precio_web_transf'];
  const columnasNavegablesCuotas = ['precio_clasica', 'cuotas_3', 'cuotas_6', 'cuotas_9', 'cuotas_12'];
  const columnasNavegablesPVP = ['precio_pvp', 'pvp_cuotas_3', 'pvp_cuotas_6', 'pvp_cuotas_9', 'pvp_cuotas_12'];
  const columnasEditables =
    editing.modoVista === 'cuotas' ? columnasNavegablesCuotas :
    editing.modoVista === 'pvp' ? columnasNavegablesPVP :
    columnasNavegablesNormal;

  // Bridge: map column name → starter (consumes editing + toggles, bridge lives here per design §5)
  const iniciarEdicionDesdeTeclado = useCallback((producto, columna) => {
    if (columna === 'precio_clasica') {
      editing.setEditandoPrecio(producto.item_id);
      editing.setPrecioTemp(producto.precio_lista_ml || '');
    } else if (columna === 'precio_rebate') {
      toggles.setEditandoRebate(producto.item_id);
      toggles.setRebateTemp({
        participa: producto.participa_rebate || false,
        porcentaje: producto.porcentaje_rebate || 3.8,
      });
    } else if (columna === 'precio_web_transf') {
      toggles.setEditandoWebTransf(producto.item_id);
      toggles.setWebTransfTemp({
        participa: producto.participa_web_transferencia || false,
        porcentaje: producto.porcentaje_markup_web || 6.0,
      });
    } else if (columna === 'cuotas_3') {
      editing.iniciarEdicionCuota(producto, '3');
    } else if (columna === 'cuotas_6') {
      editing.iniciarEdicionCuota(producto, '6');
    } else if (columna === 'cuotas_9') {
      editing.iniciarEdicionCuota(producto, '9');
    } else if (columna === 'cuotas_12') {
      editing.iniciarEdicionCuota(producto, '12');
    }
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [
    editing.setEditandoPrecio, editing.setPrecioTemp,
    editing.iniciarEdicionCuota,
    toggles.setEditandoRebate, toggles.setRebateTemp,
    toggles.setEditandoWebTransf, toggles.setWebTransfTemp,
  ]);

  // Clipboard shortcuts: Ctrl+F1/F2/F3 and Ctrl+Shift+1/2/3
  useEffect(() => {
    const handleKeyDown = (e) => {
      let accion = null;

      if (e.ctrlKey && (e.key === 'F1' || e.key === 'F2' || e.key === 'F3')) {
        accion = e.key === 'F1' ? 1 : e.key === 'F2' ? 2 : 3;
      }
      if (e.ctrlKey && e.shiftKey) {
        if (e.key === '!' || e.code === 'Digit1') accion = 1;
        if (e.key === '"' || e.key === '@' || e.code === 'Digit2') accion = 2;
        if (e.key === '·' || e.key === '#' || e.code === 'Digit3') accion = 3;
      }

      if (accion) {
        e.preventDefault();
        e.stopPropagation();

        const enModoEdicion = editing.editandoPrecio || toggles.editandoRebate || toggles.editandoWebTransf || editing.editandoCuota;
        const hayProductoSeleccionado = celdaActiva !== null && celdaActiva.rowIndex !== null;

        if (!enModoEdicion && !hayProductoSeleccionado) {
          showToast('Debes posicionarte sobre un producto para usar este atajo (Enter para activar navegación)', 'error');
          return;
        }

        let producto = null;
        if (enModoEdicion) {
          let itemId = null;
          if (editing.editandoPrecio) itemId = editing.editandoPrecio;
          else if (toggles.editandoRebate) itemId = toggles.editandoRebate;
          else if (toggles.editandoWebTransf) itemId = toggles.editandoWebTransf;
          else if (editing.editandoCuota) itemId = editing.editandoCuota.item_id;
          if (itemId) producto = data.productos.find(p => p.item_id === itemId);
        } else if (hayProductoSeleccionado) {
          producto = data.productos[celdaActiva.rowIndex];
        }

        if (!producto) { showToast('Producto no encontrado', 'error'); return; }
        if (!producto.codigo) { showToast('El producto no tiene código asignado', 'error'); return; }

        const itemCode = producto.codigo;
        if (accion === 1) {
          navigator.clipboard.writeText(itemCode).then(() => showToast(`✅ Código copiado: ${itemCode}`)).catch(() => showToast('❌ Error al copiar al portapapeles', 'error'));
        }
        if (accion === 2) {
          const url = `https://listado.mercadolibre.com.ar/${itemCode}_OrderId_PRICE_NoIndex_True`;
          navigator.clipboard.writeText(url).then(() => showToast(`✅ Enlace 1 copiado: ${itemCode}`)).catch(() => showToast('❌ Error al copiar al portapapeles', 'error'));
        }
        if (accion === 3) {
          const url = `https://www.mercadolibre.com.ar/publicaciones/listado/promos?page=1&search=${itemCode}&sort=lowest_price`;
          navigator.clipboard.writeText(url).then(() => showToast(`✅ Enlace 2 copiado: ${itemCode}`)).catch(() => showToast('❌ Error al copiar al portapapeles', 'error'));
        }
      }
    };

    window.addEventListener('keydown', handleKeyDown, { capture: true });
    return () => window.removeEventListener('keydown', handleKeyDown, { capture: true });
  }, [
    editing.editandoPrecio, editing.editandoCuota,
    toggles.editandoRebate, toggles.editandoWebTransf,
    data.productos, celdaActiva, showToast,
  ]);

  // Main navigation handler
  useEffect(() => {
    const handleKeyDown = async (e) => {
      const hayModalAbierto = ui.mostrarExportModal || ui.mostrarCalcularWebModal || ui.mostrarCalcularPVPModal || ui.mostrarModalConfig || ui.mostrarModalInfo || mostrarShortcutsHelp;

      if (hayModalAbierto) return;

      if (e.key === 'Escape') {
        e.preventDefault();
        if (editing.editandoPrecio || toggles.editandoRebate || toggles.editandoWebTransf) {
          editing.setEditandoPrecio(null);
          toggles.setEditandoRebate(null);
          toggles.setEditandoWebTransf(null);
          return;
        }
        setCeldaActiva(null);
        setModoNavegacion(false);
        ui.setPanelFiltroActivo(null);
        seleccion.setColorDropdownAbierto(null);
        return;
      }

      if (editing.editandoPrecio || toggles.editandoRebate || toggles.editandoWebTransf) {
        if (e.key === 'Tab') {
          e.preventDefault();
          e.stopPropagation();
          let editContainer = document.activeElement?.closest('.inline-edit, .rebate-edit, .web-transf-edit');
          if (!editContainer) {
            if (editing.editandoPrecio) editContainer = document.querySelector('.inline-edit');
            else if (toggles.editandoRebate) editContainer = document.querySelector('.rebate-edit');
            else if (toggles.editandoWebTransf) editContainer = document.querySelector('.web-transf-edit');
          }
          if (editContainer) {
            const focusable = Array.from(editContainer.querySelectorAll('input, button')).filter(el => el.offsetParent !== null && !el.disabled);
            const currentIndex = focusable.indexOf(document.activeElement);
            if (e.shiftKey) {
              const prevIndex = currentIndex <= 0 ? focusable.length - 1 : currentIndex - 1;
              focusable[prevIndex]?.focus();
            } else {
              const nextIndex = currentIndex >= focusable.length - 1 ? 0 : currentIndex + 1;
              focusable[nextIndex]?.focus();
            }
          }
          return;
        }
        return;
      }

      if (e.key === '?' && !e.ctrlKey && !e.altKey) {
        e.preventDefault();
        setMostrarShortcutsHelp(!mostrarShortcutsHelp);
        return;
      }

      if (e.ctrlKey && e.key === 'f') {
        e.preventDefault();
        document.querySelector('.search-bar input')?.focus();
        return;
      }

      if ((e.ctrlKey || e.metaKey) && e.key === 'i') {
        e.preventDefault();
        if (celdaActiva && data.productos[celdaActiva.rowIndex]) {
          const producto = data.productos[celdaActiva.rowIndex];
          ui.setProductoInfo(producto.item_id);
          ui.setMostrarModalInfo(true);
        }
        return;
      }

      if (e.altKey && e.key === 'm') {
        e.preventDefault();
        ui.setPanelFiltroActivo(ui.panelFiltroActivo === 'marcas' ? null : 'marcas');
        return;
      }

      if (e.altKey && e.key === 's') {
        e.preventDefault();
        ui.setPanelFiltroActivo(ui.panelFiltroActivo === 'subcategorias' ? null : 'subcategorias');
        return;
      }

      if (e.altKey && e.key === 'a') {
        e.preventDefault();
        ui.setPanelFiltroActivo(ui.panelFiltroActivo === 'auditoria' ? null : 'auditoria');
        return;
      }

      if (e.altKey && e.key === 'p') {
        e.preventDefault();
        ui.setPanelFiltroActivo(ui.panelFiltroActivo === 'pms' ? null : 'pms');
        return;
      }

      if (e.altKey && e.key === 'c') {
        e.preventDefault();
        ui.setMostrarFiltrosAvanzados(!ui.mostrarFiltrosAvanzados);
        return;
      }

      if (e.altKey && e.key === 'f') {
        e.preventDefault();
        ui.setMostrarFiltrosAvanzados(!ui.mostrarFiltrosAvanzados);
        return;
      }

      if (e.altKey && e.key === 'v') {
        e.preventDefault();
        const siguienteModo =
          editing.modoVista === 'normal' ? 'cuotas' :
          editing.modoVista === 'cuotas' ? 'pvp' :
          'normal';
        editing.setModoVista(siguienteModo);
        if (celdaActiva) setCeldaActiva({ ...celdaActiva, colIndex: 0 });
        return;
      }

      if (e.altKey && e.key === 'r') {
        e.preventDefault();
        const nuevoValor = !editing.recalcularCuotasAuto;
        editing.setRecalcularCuotasAuto(nuevoValor);
        localStorage.setItem('recalcularCuotasAuto', JSON.stringify(nuevoValor));
        return;
      }

      if (e.ctrlKey && e.key === 'e') {
        e.preventDefault();
        ui.setMostrarExportModal(true);
        return;
      }

      if (e.ctrlKey && e.key === 'k' && permissions.puedeCalcularWebMasivo) {
        e.preventDefault();
        ui.setMostrarCalcularWebModal(true);
        return;
      }

      if (e.ctrlKey && e.shiftKey && e.key === 'P' && permissions.puedeCalcularPVPMasivo) {
        e.preventDefault();
        ui.setMostrarCalcularPVPModal(true);
        return;
      }

      if (e.key === 'Enter' && !modoNavegacion && data.productos.length > 0) {
        e.preventDefault();
        setModoNavegacion(true);
        setCeldaActiva({ rowIndex: 0, colIndex: 0 });
        return;
      }

      if (modoNavegacion && celdaActiva) {
        const { rowIndex, colIndex } = celdaActiva;

        if (e.key === 'Enter' && !editing.editandoPrecio && !toggles.editandoRebate && !toggles.editandoWebTransf && !editing.editandoCuota && permissions.puedeEditar) {
          e.preventDefault();
          const producto = data.productos[rowIndex];
          const columna = columnasEditables[colIndex];
          iniciarEdicionDesdeTeclado(producto, columna);
          return;
        }

        if (e.key === 'ArrowRight' && !editing.editandoPrecio && !toggles.editandoRebate && !toggles.editandoWebTransf && !editing.editandoCuota) {
          e.preventDefault();
          if (colIndex < columnasEditables.length - 1) setCeldaActiva({ rowIndex, colIndex: colIndex + 1 });
          return;
        }

        if (e.key === 'ArrowLeft' && !editing.editandoPrecio && !toggles.editandoRebate && !toggles.editandoWebTransf && !editing.editandoCuota) {
          e.preventDefault();
          if (colIndex > 0) setCeldaActiva({ rowIndex, colIndex: colIndex - 1 });
          return;
        }

        if (e.key === 'ArrowDown' && !editing.editandoPrecio && !toggles.editandoRebate && !toggles.editandoWebTransf && !editing.editandoCuota) {
          e.preventDefault();
          if (e.shiftKey) {
            if (rowIndex < data.productos.length - 1) {
              const siguienteItemId = data.productos[rowIndex + 1].item_id;
              seleccion.toggleSeleccion(siguienteItemId, true);
              setCeldaActiva({ rowIndex: rowIndex + 1, colIndex });
            }
          } else if (e.ctrlKey || e.metaKey) {
            if (rowIndex < data.productos.length - 1) setCeldaActiva({ rowIndex: rowIndex + 1, colIndex });
          } else if (rowIndex < data.productos.length - 1) {
            setCeldaActiva({ rowIndex: rowIndex + 1, colIndex });
          }
          return;
        }

        if (e.key === 'ArrowUp' && !editing.editandoPrecio && !toggles.editandoRebate && !toggles.editandoWebTransf && !editing.editandoCuota) {
          e.preventDefault();
          if (e.shiftKey) {
            if (rowIndex > 0) {
              const anteriorItemId = data.productos[rowIndex - 1].item_id;
              seleccion.toggleSeleccion(anteriorItemId, true);
              setCeldaActiva({ rowIndex: rowIndex - 1, colIndex });
            }
          } else if (e.ctrlKey || e.metaKey) {
            if (rowIndex > 0) setCeldaActiva({ rowIndex: rowIndex - 1, colIndex });
          } else if (rowIndex > 0) {
            setCeldaActiva({ rowIndex: rowIndex - 1, colIndex });
          }
          return;
        }

        if (e.key === 'PageUp' && !editing.editandoPrecio && !toggles.editandoRebate && !toggles.editandoWebTransf && !editing.editandoCuota) {
          e.preventDefault();
          setCeldaActiva({ rowIndex: Math.max(0, rowIndex - 10), colIndex });
          return;
        }

        if (e.key === 'PageDown' && !editing.editandoPrecio && !toggles.editandoRebate && !toggles.editandoWebTransf && !editing.editandoCuota) {
          e.preventDefault();
          setCeldaActiva({ rowIndex: Math.min(data.productos.length - 1, rowIndex + 10), colIndex });
          return;
        }

        if (e.key === 'Home' && !editing.editandoPrecio && !toggles.editandoRebate && !toggles.editandoWebTransf && !editing.editandoCuota) {
          e.preventDefault();
          setCeldaActiva({ rowIndex, colIndex: 0 });
          return;
        }

        if (e.key === 'End' && !editing.editandoPrecio && !toggles.editandoRebate && !toggles.editandoWebTransf && !editing.editandoCuota) {
          e.preventDefault();
          setCeldaActiva({ rowIndex, colIndex: columnasEditables.length - 1 });
          return;
        }

        if (e.key === ' ' && !editing.editandoPrecio && !toggles.editandoRebate && !toggles.editandoWebTransf && !editing.editandoCuota && permissions.puedeEditar) {
          e.preventDefault();
          const producto = data.productos[rowIndex];
          const columna = columnasEditables[colIndex];
          iniciarEdicionDesdeTeclado(producto, columna);
          return;
        }

        const activeElement = document.activeElement;
        const isInputFocused = activeElement && (activeElement.tagName === 'INPUT' || activeElement.tagName === 'TEXTAREA');
        if (!editing.editandoPrecio && !toggles.editandoRebate && !toggles.editandoWebTransf && /^[0-7]$/.test(e.key) && !e.ctrlKey && !e.altKey && !e.metaKey && !isInputFocused) {
          e.preventDefault();
          e.stopPropagation();
          if (permissions.puedeMarcarColor && data.productos[rowIndex]) {
            const colores = [null, 'rojo', 'naranja', 'amarillo', 'verde', 'azul', 'purpura', 'gris'];
            const colorIndex = parseInt(e.key);
            if (colorIndex < colores.length) {
              const producto = data.productos[rowIndex];
              const colorSeleccionado = colores[colorIndex];
              seleccion.cambiarColorRapido(producto.item_id, colorSeleccionado);
            }
          }
          return;
        }

        if (e.key === 'r' && !editing.editandoPrecio && !toggles.editandoWebTransf && permissions.puedeToggleRebate) {
          e.preventDefault();
          const producto = data.productos[rowIndex];
          if (toggles.editandoRebate === producto.item_id) {
            await api.patch(`/productos/${producto.item_id}/rebate`, {
              participa_rebate: false,
              porcentaje_rebate: producto.porcentaje_rebate || 3.8,
            });
            data.setProductos(prods => prods.map(p =>
              p.item_id === producto.item_id
                ? { ...p, participa_rebate: false, precio_rebate: null, markup_rebate: null }
                : p
            ));
            toggles.setEditandoRebate(null);
            data.cargarStats();
          } else {
            toggles.toggleRebateRapido(producto);
          }
          return;
        }

        if (e.key === 'w' && !editing.editandoPrecio && !toggles.editandoRebate && !toggles.editandoWebTransf && permissions.puedeToggleWebTransf) {
          e.preventDefault();
          const producto = data.productos[rowIndex];
          toggles.toggleWebTransfRapido(producto);
          return;
        }

        if (e.key === 'o' && !editing.editandoPrecio && !toggles.editandoWebTransf && permissions.puedeToggleOutOfCards) {
          e.preventDefault();
          const producto = data.productos[rowIndex];
          if (toggles.editandoRebate === producto.item_id && producto.out_of_cards) {
            await api.patch(`/productos/${producto.item_id}/out-of-cards`, { out_of_cards: false });
            data.setProductos(prods => prods.map(p =>
              p.item_id === producto.item_id ? { ...p, out_of_cards: false } : p
            ));
            toggles.setEditandoRebate(null);
            data.cargarStats();
          } else {
            toggles.toggleOutOfCardsRapido(producto);
          }
          return;
        }
      }
    };

    window.addEventListener('keydown', handleKeyDown);
    return () => window.removeEventListener('keydown', handleKeyDown);
    // Granular deps listed; passing whole grouped objects would recreate callback every render.
    // Re-bind strategy (Tienda ADR-5) ensures fresh closures — no stale-closure bugs.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [
    modoNavegacion, celdaActiva, mostrarShortcutsHelp,
    data.productos,
    editing.editandoPrecio, editing.editandoCuota, editing.modoVista, editing.recalcularCuotasAuto,
    toggles.editandoRebate, toggles.editandoWebTransf,
    ui.panelFiltroActivo, ui.mostrarFiltrosAvanzados,
    ui.mostrarExportModal, ui.mostrarCalcularWebModal, ui.mostrarCalcularPVPModal,
    ui.mostrarModalConfig, ui.mostrarModalInfo,
    permissions.puedeEditar, permissions.puedeMarcarColor,
    permissions.puedeToggleRebate, permissions.puedeToggleWebTransf, permissions.puedeToggleOutOfCards,
    permissions.puedeCalcularWebMasivo, permissions.puedeCalcularPVPMasivo,
    iniciarEdicionDesdeTeclado,
    columnasEditables,
  ]);

  // Auto-scroll to keep active cell visible
  useEffect(() => {
    if (modoNavegacion && celdaActiva) {
      const tbody = document.querySelector('.table-tesla-body');
      if (tbody) {
        const filas = tbody.querySelectorAll('tr');
        const filaActiva = filas[celdaActiva.rowIndex];
        if (filaActiva) {
          filaActiva.scrollIntoView({ behavior: 'auto', block: 'nearest', inline: 'nearest' });
        }
      }
    }
  }, [celdaActiva, modoNavegacion]);

  return {
    celdaActiva,
    setCeldaActiva,
    modoNavegacion,
    setModoNavegacion,
    mostrarShortcutsHelp,
    setMostrarShortcutsHelp,
    columnasEditables,
  };
}
