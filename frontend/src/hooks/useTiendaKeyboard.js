import { useState, useEffect } from 'react';

/**
 * Custom hook para manejar TODA la navegación por teclado y atajos en la vista Tienda.
 * Incluye: clipboard shortcuts (Ctrl+F1/F2/F3), navegación por celdas, colores rápidos,
 * toggle rebate/webTransf/outOfCards, shortcuts de filtros y vistas.
 *
 * @param {Object} params
 * @param {Object} params.pricing - State y funciones del hook useTiendaPricing
 * @param {Object} params.selection - Funciones del hook useTiendaSelection
 * @param {Object} params.data - State y funciones del hook useTiendaData
 * @param {Object} params.ui - State y setters de UI del componente Tienda
 * @param {Object} params.permissions - Permisos del usuario
 * @param {Function} params.showToast - Función de notificación
 */
export function useTiendaKeyboard({
  pricing,
  selection,
  data,
  ui,
  permissions,
  showToast,
}) {

  // === ESTADO DE NAVEGACIÓN (propio del hook) ===
  const [celdaActiva, setCeldaActiva] = useState(null);
  const [modoNavegacion, setModoNavegacion] = useState(false);
  const [mostrarShortcutsHelp, setMostrarShortcutsHelp] = useState(false);

  // Columnas navegables según vista activa
  const columnasNavegablesNormal = ['precio_clasica', 'precio_gremio', 'precio_web_transf', 'web_tarjeta'];
  const columnasNavegablesCuotas = ['precio_clasica', 'cuotas_3', 'cuotas_6', 'cuotas_9', 'cuotas_12'];
  const columnasEditables = ui.vistaModoCuotas ? columnasNavegablesCuotas : columnasNavegablesNormal;

  // === CLIPBOARD SHORTCUTS (Ctrl+F1/F2/F3) ===
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

        const { editandoPrecio, editandoRebate, editandoWebTransf, editandoCuota } = pricing;
        const { productos } = data;

        const enModoEdicion = editandoPrecio || editandoRebate || editandoWebTransf || editandoCuota;
        const hayProductoSeleccionado = celdaActiva !== null && celdaActiva.rowIndex !== null;

        if (!enModoEdicion && !hayProductoSeleccionado) {
          showToast('Debes posicionarte sobre un producto para usar este atajo (Enter para activar navegación)', 'error');
          return;
        }

        let producto = null;

        if (enModoEdicion) {
          let itemId = null;
          if (editandoPrecio) itemId = editandoPrecio;
          else if (editandoRebate) itemId = editandoRebate;
          else if (editandoWebTransf) itemId = editandoWebTransf;
          else if (editandoCuota) itemId = editandoCuota.item_id;

          if (itemId) {
            producto = productos.find(p => p.item_id === itemId);
          }
        } else if (hayProductoSeleccionado) {
          producto = productos[celdaActiva.rowIndex];
        }

        if (!producto) {
          showToast('Producto no encontrado', 'error');
          return;
        }

        if (!producto.codigo) {
          showToast('El producto no tiene código asignado', 'error');
          return;
        }

        const itemCode = producto.codigo;

        if (accion === 1) {
          navigator.clipboard.writeText(itemCode).then(() => {
            showToast(`✅ Código copiado: ${itemCode}`);
          }).catch(() => {
            showToast('❌ Error al copiar al portapapeles', 'error');
          });
        }

        if (accion === 2) {
          const url = `https://listado.mercadolibre.com.ar/${itemCode}_OrderId_PRICE_NoIndex_True`;
          navigator.clipboard.writeText(url).then(() => {
            showToast(`✅ Enlace 1 copiado: ${itemCode}`);
          }).catch(() => {
            showToast('❌ Error al copiar al portapapeles', 'error');
          });
        }

        if (accion === 3) {
          const url = `https://www.mercadolibre.com.ar/publicaciones/listado/promos?filters=official_store-57997&page=1&search=${itemCode}&sort=lowest_price`;
          navigator.clipboard.writeText(url).then(() => {
            showToast(`✅ Enlace 2 copiado: ${itemCode}`);
          }).catch(() => {
            showToast('❌ Error al copiar al portapapeles', 'error');
          });
        }
      }
    };

    window.addEventListener('keydown', handleKeyDown, { capture: true });
    return () => window.removeEventListener('keydown', handleKeyDown, { capture: true });
  }, [pricing.editandoPrecio, pricing.editandoRebate, pricing.editandoWebTransf, pricing.editandoCuota, data.productos, celdaActiva, showToast]);

  // === MAIN KEYBOARD NAVIGATION ===
  useEffect(() => {
    const handleKeyDown = async (e) => {
      const {
        editandoPrecio, editandoRebate, editandoWebTransf, editandoCuota,
        setEditandoPrecio, setEditandoRebate, setEditandoWebTransf,
        iniciarEdicionDesdeTeclado, cambiarColorRapido,
        toggleRebateRapido, toggleWebTransfRapido, toggleOutOfCardsRapido,
      } = pricing;

      const { productos, setProductos, cargarStats } = data;
      const { toggleSeleccion } = selection;
      const { puedeEditar, puedeMarcarColor, puedeEditarWebTransf, puedeCalcularWebMasivo } = permissions;

      // Variable para evitar repetir el patrón de guards
      const enModoEdicion = editandoPrecio || editandoRebate || editandoWebTransf || editandoCuota;

      // Si hay un modal abierto, NO procesar shortcuts de la página
      const hayModalAbierto = ui.mostrarExportModal || ui.mostrarCalcularWebModal || ui.mostrarModalConfig || ui.mostrarModalInfo || mostrarShortcutsHelp;

      if (hayModalAbierto) {
        return;
      }

      // ESC: Salir de edición o modo navegación
      if (e.key === 'Escape') {
        e.preventDefault();
        if (editandoPrecio || editandoRebate || editandoWebTransf) {
          setEditandoPrecio(null);
          setEditandoRebate(null);
          setEditandoWebTransf(null);
          return;
        }
        setCeldaActiva(null);
        setModoNavegacion(false);
        ui.setPanelFiltroActivo(null);
        ui.setColorDropdownAbierto(null);
        return;
      }

      // Si estamos editando una celda
      if (editandoPrecio || editandoRebate || editandoWebTransf) {
        if (e.key === 'Tab') {
          e.preventDefault();
          e.stopPropagation();

          let editContainer = document.activeElement?.closest('.inline-edit, .rebate-edit, .web-transf-edit');

          if (!editContainer) {
            if (editandoPrecio) {
              editContainer = document.querySelector('.inline-edit');
            } else if (editandoRebate) {
              editContainer = document.querySelector('.rebate-edit');
            } else if (editandoWebTransf) {
              editContainer = document.querySelector('.web-transf-edit');
            }
          }

          if (editContainer) {
            const focusable = Array.from(editContainer.querySelectorAll('input, button')).filter(el => {
              return el.offsetParent !== null && !el.disabled;
            });
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

      // Mostrar ayuda de shortcuts (?)
      if (e.key === '?' && !e.ctrlKey && !e.altKey) {
        e.preventDefault();
        setMostrarShortcutsHelp(!mostrarShortcutsHelp);
        return;
      }

      // Ctrl+F: Focus en búsqueda
      if (e.ctrlKey && e.key === 'f') {
        e.preventDefault();
        document.querySelector('.search-bar input')?.focus();
        return;
      }

      // Ctrl+I: Abrir info del producto seleccionado
      if ((e.ctrlKey || e.metaKey) && e.key === 'i') {
        e.preventDefault();
        if (celdaActiva && productos[celdaActiva.rowIndex]) {
          const producto = productos[celdaActiva.rowIndex];
          ui.setProductoInfo(producto.item_id);
          ui.setMostrarModalInfo(true);
        }
        return;
      }

      // Alt+M: Toggle filtro de marcas
      if (e.altKey && e.key === 'm') {
        e.preventDefault();
        ui.setPanelFiltroActivo(ui.panelFiltroActivo === 'marcas' ? null : 'marcas');
        return;
      }

      // Alt+S: Toggle filtro de subcategorías
      if (e.altKey && e.key === 's') {
        e.preventDefault();
        ui.setPanelFiltroActivo(ui.panelFiltroActivo === 'subcategorias' ? null : 'subcategorias');
        return;
      }

      // Alt+A: Toggle filtro de auditoría
      if (e.altKey && e.key === 'a') {
        e.preventDefault();
        ui.setPanelFiltroActivo(ui.panelFiltroActivo === 'auditoria' ? null : 'auditoria');
        return;
      }

      // Alt+P: Toggle filtro de PMs
      if (e.altKey && e.key === 'p') {
        e.preventDefault();
        ui.setPanelFiltroActivo(ui.panelFiltroActivo === 'pms' ? null : 'pms');
        return;
      }

      // Alt+C: Toggle filtros avanzados
      if (e.altKey && e.key === 'c') {
        e.preventDefault();
        ui.setMostrarFiltrosAvanzados(!ui.mostrarFiltrosAvanzados);
        return;
      }

      // Alt+F: Toggle filtros avanzados
      if (e.altKey && e.key === 'f') {
        e.preventDefault();
        ui.setMostrarFiltrosAvanzados(!ui.mostrarFiltrosAvanzados);
        return;
      }

      // Alt+V: Toggle Vista Normal / Vista Cuotas
      if (e.altKey && e.key === 'v') {
        e.preventDefault();
        ui.setVistaModoCuotas(!ui.vistaModoCuotas);
        if (celdaActiva) {
          setCeldaActiva({ ...celdaActiva, colIndex: 0 });
        }
        return;
      }

      // Alt+R: Toggle Auto-recalcular cuotas
      if (e.altKey && e.key === 'r') {
        e.preventDefault();
        const nuevoValor = !ui.recalcularCuotasAuto;
        ui.setRecalcularCuotasAuto(nuevoValor);
        localStorage.setItem('recalcularCuotasAuto', JSON.stringify(nuevoValor));
        return;
      }

      // Alt+D: Toggle Precio Gremio ARS / USD
      if (e.altKey && e.key === 'd') {
        e.preventDefault();
        ui.setVistaModoPrecioGremioUSD(!ui.vistaModoPrecioGremioUSD);
        return;
      }

      // Ctrl+E: Abrir modal de export
      if (e.ctrlKey && e.key === 'e') {
        e.preventDefault();
        ui.setMostrarExportModal(true);
        return;
      }

      // Ctrl+K: Abrir modal de calcular web
      if (e.ctrlKey && e.key === 'k' && puedeCalcularWebMasivo) {
        e.preventDefault();
        ui.setMostrarCalcularWebModal(true);
        return;
      }

      // Enter: Activar modo navegación en la tabla
      if (e.key === 'Enter' && !modoNavegacion && productos.length > 0) {
        e.preventDefault();
        setModoNavegacion(true);
        setCeldaActiva({ rowIndex: 0, colIndex: 0 });
        return;
      }

      // Navegación en modo tabla
      if (modoNavegacion && celdaActiva) {
        const { rowIndex, colIndex } = celdaActiva;

        // Enter: Editar celda activa
        if (e.key === 'Enter' && !enModoEdicion && puedeEditar) {
          e.preventDefault();
          const producto = productos[rowIndex];
          const columna = columnasEditables[colIndex];
          iniciarEdicionDesdeTeclado(producto, columna);
          return;
        }

        // Flechas: Navegación por celdas
        if (e.key === 'ArrowRight' && !enModoEdicion) {
          e.preventDefault();
          if (colIndex < columnasEditables.length - 1) {
            setCeldaActiva({ rowIndex, colIndex: colIndex + 1 });
          }
          return;
        }

        if (e.key === 'ArrowLeft' && !enModoEdicion) {
          e.preventDefault();
          if (colIndex > 0) {
            setCeldaActiva({ rowIndex, colIndex: colIndex - 1 });
          }
          return;
        }

        if (e.key === 'ArrowDown' && !enModoEdicion) {
          e.preventDefault();
          if (e.shiftKey) {
            if (rowIndex < productos.length - 1) {
              const siguienteItemId = productos[rowIndex + 1].item_id;
              toggleSeleccion(siguienteItemId, true);
              setCeldaActiva({ rowIndex: rowIndex + 1, colIndex });
            }
          } else if (e.ctrlKey || e.metaKey) {
            if (rowIndex < productos.length - 1) {
              setCeldaActiva({ rowIndex: rowIndex + 1, colIndex });
            }
          } else if (rowIndex < productos.length - 1) {
            setCeldaActiva({ rowIndex: rowIndex + 1, colIndex });
          }
          return;
        }

        if (e.key === 'ArrowUp' && !enModoEdicion) {
          e.preventDefault();
          if (e.shiftKey) {
            if (rowIndex > 0) {
              const anteriorItemId = productos[rowIndex - 1].item_id;
              toggleSeleccion(anteriorItemId, true);
              setCeldaActiva({ rowIndex: rowIndex - 1, colIndex });
            }
          } else if (e.ctrlKey || e.metaKey) {
            if (rowIndex > 0) {
              setCeldaActiva({ rowIndex: rowIndex - 1, colIndex });
            }
          } else if (rowIndex > 0) {
            setCeldaActiva({ rowIndex: rowIndex - 1, colIndex });
          }
          return;
        }

        // PageUp: Subir 10 filas
        if (e.key === 'PageUp' && !enModoEdicion) {
          e.preventDefault();
          const newRow = Math.max(0, rowIndex - 10);
          setCeldaActiva({ rowIndex: newRow, colIndex });
          return;
        }

        // PageDown: Bajar 10 filas
        if (e.key === 'PageDown' && !enModoEdicion) {
          e.preventDefault();
          const newRow = Math.min(productos.length - 1, rowIndex + 10);
          setCeldaActiva({ rowIndex: newRow, colIndex });
          return;
        }

        // Home: Ir a primera columna
        if (e.key === 'Home' && !enModoEdicion) {
          e.preventDefault();
          setCeldaActiva({ rowIndex, colIndex: 0 });
          return;
        }

        // End: Ir a última columna
        if (e.key === 'End' && !enModoEdicion) {
          e.preventDefault();
          setCeldaActiva({ rowIndex, colIndex: columnasEditables.length - 1 });
          return;
        }

        // Espacio: Editar precio en celda activa
        if (e.key === ' ' && !enModoEdicion && puedeEditar) {
          e.preventDefault();
          const producto = productos[rowIndex];
          const columna = columnasEditables[colIndex];
          iniciarEdicionDesdeTeclado(producto, columna);
          return;
        }

        // Números 1-7: Selección rápida de colores
        const activeElement = document.activeElement;
        const isInputFocused = activeElement && (activeElement.tagName === 'INPUT' || activeElement.tagName === 'TEXTAREA');
        if (!enModoEdicion && /^[0-7]$/.test(e.key) && !e.ctrlKey && !e.altKey && !e.metaKey && !isInputFocused) {
          e.preventDefault();
          e.stopPropagation();
          if (puedeMarcarColor && productos[rowIndex]) {
            const colores = [null, 'rojo', 'naranja', 'amarillo', 'verde', 'azul', 'purpura', 'gris'];
            const colorIndex = parseInt(e.key);
            if (colorIndex < colores.length) {
              const producto = productos[rowIndex];
              const colorSeleccionado = colores[colorIndex];
              cambiarColorRapido(producto.item_id, colorSeleccionado);
            }
          }
          return;
        }

        // R: Toggle rebate
        if (e.key === 'r' && !editandoPrecio && !editandoWebTransf && puedeEditar) {
          e.preventDefault();
          const producto = productos[rowIndex];
          await toggleRebateRapido(producto);
          return;
        }

        // W: Toggle web transferencia
        if (e.key === 'w' && !enModoEdicion && puedeEditarWebTransf) {
          e.preventDefault();
          const producto = productos[rowIndex];
          await toggleWebTransfRapido(producto);
          return;
        }

        // O: Toggle out of cards
        if (e.key === 'o' && !editandoPrecio && !editandoWebTransf && puedeEditar) {
          e.preventDefault();
          const producto = productos[rowIndex];
          await toggleOutOfCardsRapido(producto);
          return;
        }
      }
    };

    window.addEventListener('keydown', handleKeyDown);
    return () => window.removeEventListener('keydown', handleKeyDown);
  }, [pricing, data, selection, ui, permissions, modoNavegacion, celdaActiva, mostrarShortcutsHelp, showToast]);

  // === AUTO-SCROLL para seguir la celda activa ===
  useEffect(() => {
    if (modoNavegacion && celdaActiva) {
      const tbody = document.querySelector('.table-tesla-body');
      if (tbody) {
        const filas = tbody.querySelectorAll('tr');
        const filaActiva = filas[celdaActiva.rowIndex];
        if (filaActiva) {
          filaActiva.scrollIntoView({
            behavior: 'auto',
            block: 'nearest',
            inline: 'nearest'
          });
        }
      }
    }
  }, [celdaActiva, modoNavegacion]);

  return {
    celdaActiva, setCeldaActiva,
    modoNavegacion, setModoNavegacion,
    mostrarShortcutsHelp, setMostrarShortcutsHelp,
    columnasEditables,
  };
}
