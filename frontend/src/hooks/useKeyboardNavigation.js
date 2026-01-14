import { useEffect } from 'react';

/**
 * Custom hook para manejar navegación por teclado en la tabla de productos
 * Consolidates 300+ lines of keyboard handling logic
 * 
 * @param {Object} params - Parámetros del hook
 * @param {Array} params.productos - Lista de productos
 * @param {Object} params.celdaActiva - Celda actualmente seleccionada {rowIndex, colIndex}
 * @param {Function} params.setCeldaActiva - Setter para celda activa
 * @param {boolean} params.modoNavegacion - Si está en modo navegación
 * @param {Function} params.setModoNavegacion - Setter para modo navegación
 * @param {boolean} params.editandoPrecio - Si está editando precio
 * @param {Function} params.setEditandoPrecio - Setter para editar precio
 * @param {boolean} params.editandoRebate - Si está editando rebate
 * @param {Function} params.setEditandoRebate - Setter para editar rebate
 * @param {boolean} params.editandoWebTransf - Si está editando web transferencia
 * @param {Function} params.setEditandoWebTransf - Setter para editar web transferencia
 * @param {Object} params.editandoCuota - Si está editando cuota
 * @param {Function} params.setEditandoCuota - Setter para editar cuota
 * @param {Array} params.columnasEditables - Columnas editables según vista activa
 * @param {boolean} params.puedeEditar - Si tiene permisos de edición
 * @param {Object} params.modals - Estado de modales abiertos
 * @param {Function} params.setters - Setters varios para estado
 */
export function useKeyboardNavigation({
  productos,
  celdaActiva,
  setCeldaActiva,
  modoNavegacion,
  setModoNavegacion,
  editandoPrecio,
  setEditandoPrecio,
  editandoRebate,
  setEditandoRebate,
  editandoWebTransf,
  setEditandoWebTransf,
  editandoCuota,
  setEditandoCuota,
  columnasEditables,
  puedeEditar,
  modals,
  setters,
  vistaModoCuotas,
  setVistaModoCuotas,
  recalcularCuotasAuto,
  setRecalcularCuotasAuto,
  vistaModoPrecioGremioUSD,
  setVistaModoPrecioGremioUSD,
  puedeCalcularWebMasivo,
  iniciarEdicionPrecioGremio,
  iniciarEdicionCuota,
  iniciarEdicionWebTransf
}) {
  useEffect(() => {
    const handleKeyDown = async (e) => {
      // Si hay un modal abierto, NO procesar shortcuts de la página
      const hayModalAbierto = modals.mostrarExportModal || modals.mostrarCalcularWebModal || 
                              modals.mostrarModalConfig || modals.mostrarModalInfo || 
                              modals.mostrarShortcutsHelp;

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
        setters.setPanelFiltroActivo(null);
        setters.setColorDropdownAbierto(null);
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
        setters.setMostrarShortcutsHelp(!modals.mostrarShortcutsHelp);
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
          setters.setProductoInfo(producto.item_id);
          setters.setMostrarModalInfo(true);
        }
        return;
      }

      // Alt+M: Toggle filtro de marcas
      if (e.altKey && e.key === 'm') {
        e.preventDefault();
        setters.setPanelFiltroActivo(setters.panelFiltroActivo === 'marcas' ? null : 'marcas');
        return;
      }

      // Alt+S: Toggle filtro de subcategorías
      if (e.altKey && e.key === 's') {
        e.preventDefault();
        setters.setPanelFiltroActivo(setters.panelFiltroActivo === 'subcategorias' ? null : 'subcategorias');
        return;
      }

      // Alt+A: Toggle filtro de auditoría
      if (e.altKey && e.key === 'a') {
        e.preventDefault();
        setters.setPanelFiltroActivo(setters.panelFiltroActivo === 'auditoria' ? null : 'auditoria');
        return;
      }

      // Alt+P: Toggle filtro de PMs
      if (e.altKey && e.key === 'p') {
        e.preventDefault();
        setters.setPanelFiltroActivo(setters.panelFiltroActivo === 'pms' ? null : 'pms');
        return;
      }

      // Alt+C o Alt+F: Toggle filtros avanzados
      if (e.altKey && (e.key === 'c' || e.key === 'f')) {
        e.preventDefault();
        setters.setMostrarFiltrosAvanzados(!setters.mostrarFiltrosAvanzados);
        return;
      }

      // Alt+V: Toggle Vista Normal / Vista Cuotas
      if (e.altKey && e.key === 'v') {
        e.preventDefault();
        setVistaModoCuotas(!vistaModoCuotas);
        if (celdaActiva) {
          setCeldaActiva({ ...celdaActiva, colIndex: 0 });
        }
        return;
      }

      // Alt+R: Toggle Auto-recalcular cuotas
      if (e.altKey && e.key === 'r') {
        e.preventDefault();
        const nuevoValor = !recalcularCuotasAuto;
        setRecalcularCuotasAuto(nuevoValor);
        localStorage.setItem('recalcularCuotasAuto', JSON.stringify(nuevoValor));
        return;
      }

      // Alt+D: Toggle Precio Gremio ARS / USD
      if (e.altKey && e.key === 'd') {
        e.preventDefault();
        setVistaModoPrecioGremioUSD(!vistaModoPrecioGremioUSD);
        return;
      }

      // Ctrl+E: Abrir modal de export
      if (e.ctrlKey && e.key === 'e') {
        e.preventDefault();
        setters.setMostrarExportModal(true);
        return;
      }

      // Ctrl+K: Abrir modal de calcular web
      if (e.ctrlKey && e.key === 'k' && puedeCalcularWebMasivo) {
        e.preventDefault();
        setters.setMostrarCalcularWebModal(true);
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
        if (e.key === 'Enter' && !editandoPrecio && !editandoRebate && !editandoWebTransf && !editandoCuota && puedeEditar) {
          e.preventDefault();
          const producto = productos[rowIndex];
          const columna = columnasEditables[colIndex];

          if (columna === 'precio_gremio') {
            iniciarEdicionPrecioGremio(producto, e);
          } else if (columna === 'precio_web_transf') {
            iniciarEdicionWebTransf(producto);
          } else if (columna.startsWith('cuotas_')) {
            const tipo = columna.replace('cuotas_', '');
            iniciarEdicionCuota(producto, tipo);
          }
          return;
        }

        // Espacio: igual que Enter
        if (e.key === ' ' && !editandoPrecio && !editandoRebate && !editandoWebTransf && !editandoCuota && puedeEditar) {
          e.preventDefault();
          const producto = productos[rowIndex];
          const columna = columnasEditables[colIndex];

          if (columna === 'precio_gremio') {
            iniciarEdicionPrecioGremio(producto, e);
          } else if (columna === 'precio_web_transf') {
            iniciarEdicionWebTransf(producto);
          } else if (columna.startsWith('cuotas_')) {
            const tipo = columna.replace('cuotas_', '');
            iniciarEdicionCuota(producto, tipo);
          }
          return;
        }

        // Arrow keys para navegar
        if (e.key === 'ArrowUp') {
          e.preventDefault();
          if (rowIndex > 0) {
            setCeldaActiva({ ...celdaActiva, rowIndex: rowIndex - 1 });
            setTimeout(() => {
              document.querySelector(`[data-row="${rowIndex - 1}"][data-col="${colIndex}"]`)?.scrollIntoView({
                block: 'nearest',
                behavior: 'smooth'
              });
            }, 0);
          }
        }

        if (e.key === 'ArrowDown') {
          e.preventDefault();
          if (rowIndex < productos.length - 1) {
            setCeldaActiva({ ...celdaActiva, rowIndex: rowIndex + 1 });
            setTimeout(() => {
              document.querySelector(`[data-row="${rowIndex + 1}"][data-col="${colIndex}"]`)?.scrollIntoView({
                block: 'nearest',
                behavior: 'smooth'
              });
            }, 0);
          }
        }

        if (e.key === 'ArrowLeft') {
          e.preventDefault();
          if (colIndex > 0) {
            setCeldaActiva({ ...celdaActiva, colIndex: colIndex - 1 });
          }
        }

        if (e.key === 'ArrowRight') {
          e.preventDefault();
          if (colIndex < columnasEditables.length - 1) {
            setCeldaActiva({ ...celdaActiva, colIndex: colIndex + 1 });
          }
        }
      }
    };

    window.addEventListener('keydown', handleKeyDown);
    return () => window.removeEventListener('keydown', handleKeyDown);
  }, [
    productos,
    celdaActiva,
    modoNavegacion,
    editandoPrecio,
    editandoRebate,
    editandoWebTransf,
    editandoCuota,
    columnasEditables,
    puedeEditar,
    modals,
    vistaModoCuotas,
    recalcularCuotasAuto,
    vistaModoPrecioGremioUSD,
    puedeCalcularWebMasivo,
    setCeldaActiva,
    setModoNavegacion,
    setEditandoPrecio,
    setEditandoRebate,
    setEditandoWebTransf,
    setEditandoCuota,
    setVistaModoCuotas,
    setRecalcularCuotasAuto,
    setVistaModoPrecioGremioUSD,
    setters,
    iniciarEdicionPrecioGremio,
    iniciarEdicionCuota,
    iniciarEdicionWebTransf
  ]);
}
