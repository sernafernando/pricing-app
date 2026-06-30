import { useState, useCallback, useEffect } from 'react';
import api from '../services/api';
import { isValidNumericInput } from '../utils/productosFormat';

export function useProductosInlineEditing({
  productos,
  setProductos,
  cargarProductos,
  cargarStats,
  showToast,
  filtros,
}) {
  const [editandoPrecio, setEditandoPrecio] = useState(null);
  const [precioTemp, setPrecioTemp] = useState('');
  const [editandoCuota, setEditandoCuota] = useState(null);
  const [cuotaTemp, setCuotaTemp] = useState('');
  const [modoVista, setModoVista] = useState('normal'); // 'normal', 'cuotas', 'pvp'
  const [recalcularCuotasAuto, setRecalcularCuotasAuto] = useState(() => {
    const saved = localStorage.getItem('recalcularCuotasAuto');
    return saved === null ? true : JSON.parse(saved);
  });
  const [mostrarModalMarkupNegativo, setMostrarModalMarkupNegativo] = useState(false);
  const [datosGuardadoPendiente, setDatosGuardadoPendiente] = useState(null);
  const [recalculandoCuotasMasivo, setRecalculandoCuotasMasivo] = useState(false);

  // Persist recalcularCuotasAuto preference
  useEffect(() => {
    localStorage.setItem('recalcularCuotasAuto', JSON.stringify(recalcularCuotasAuto));
  }, [recalcularCuotasAuto]);

  const consultarMarkup = useCallback(async (itemId, precio, listaTipo = 'web', pricelistId = null) => {
    try {
      const pricelist_id = pricelistId || (listaTipo === 'pvp' ? 12 : 4);
      const response = await api.get(
        '/precios/calcular-markup',
        {
          params: {
            item_id: itemId,
            precio: precio,
            pricelist_id: pricelist_id
          }
        }
      );
      return response.data;
    } catch {
      showToast('No se pudo validar el markup. Revisa la consola.', 'error');
      return null;
    }
  }, [showToast]);

  const iniciarEdicion = useCallback((producto) => {
    setEditandoPrecio(producto.item_id);
    const precioInicial = modoVista === 'pvp' ? (producto.precio_pvp || '') : (producto.precio_lista_ml || '');
    setPrecioTemp(precioInicial);
  }, [modoVista]);

  const iniciarEdicionCuota = useCallback((producto, tipo) => {
    setEditandoCuota({ item_id: producto.item_id, tipo });
    const campoPrecio = `precio_${tipo}_cuotas`;
    setCuotaTemp(producto[campoPrecio] || '');
  }, []);

  const guardarCuota = useCallback(async (itemId, tipo, esPVP = false, forzar = false) => {
    try {
      const precioNormalizado = parseFloat(cuotaTemp.toString().replace(',', '.'));

      if (!forzar && precioNormalizado > 0) {
        const pricelistMap = {
          'web': { '3': 17, '6': 14, '9': 13, '12': 23 },
          'pvp': { '3': 18, '6': 19, '9': 20, '12': 21 }
        };
        const listaTipo = esPVP ? 'pvp' : 'web';
        const pricelistId = pricelistMap[listaTipo][tipo];

        if (pricelistId) {
          const markupData = await consultarMarkup(itemId, precioNormalizado, listaTipo, pricelistId);

          if (markupData && markupData.markup < 0) {
            const producto = productos.find(p => p.item_id === itemId);
            setDatosGuardadoPendiente({
              itemId,
              tipo,
              esPVP,
              precio: precioNormalizado,
              producto,
              markup: markupData.markup,
              listaTipo,
              esCuota: true
            });
            setMostrarModalMarkupNegativo(true);
            return;
          }
        }
      }

      const response = await api.post(
        '/precios/set-cuota',
        null,
        {
          params: {
            item_id: itemId,
            tipo_cuota: tipo,
            precio: precioNormalizado,
            lista_tipo: esPVP ? 'pvp' : 'web'
          }
        }
      );

      let campoPrecio, campoMarkup;
      if (esPVP) {
        campoPrecio = tipo === 'clasica' ? 'precio_pvp' : `precio_pvp_${tipo}_cuotas`;
        campoMarkup = tipo === 'clasica' ? 'markup_pvp' : `markup_pvp_${tipo}_cuotas`;
      } else {
        campoPrecio = tipo === 'clasica' ? 'precio_lista_ml' : `precio_${tipo}_cuotas`;
        campoMarkup = tipo === 'clasica' ? 'markup' : `markup_${tipo}_cuotas`;
      }

      setProductos(prods => prods.map(p =>
        p.item_id === itemId
          ? {
              ...p,
              [campoPrecio]: precioNormalizado,
              [campoMarkup]: response.data[campoMarkup]
            }
          : p
      ));

      setEditandoCuota(null);
      cargarStats();
    } catch (error) {
      showToast('Error al guardar precio de cuota: ' + (error.response?.data?.detail || error.message), 'error');
    }
  }, [cuotaTemp, productos, consultarMarkup, setProductos, cargarStats, showToast]);

  const recalcularCuotasDesdeClasica = useCallback(async (producto, listaTipo) => {
    const precioBase = listaTipo === 'pvp' ? producto.precio_pvp : producto.precio_lista_ml;

    if (!precioBase || Number(precioBase) <= 0) {
      showToast(`Este producto no tiene Precio ${listaTipo === 'pvp' ? 'PVP' : 'Web'} para recalcular cuotas`, 'error');
      return;
    }

    try {
      const response = await api.post(
        '/precios/recalcular-cuotas',
        null,
        {
          params: {
            item_id: producto.item_id,
            lista_tipo: listaTipo
          }
        }
      );

      if (listaTipo === 'pvp') {
        setProductos((prods) => prods.map((p) =>
          p.item_id === producto.item_id
            ? {
                ...p,
                precio_pvp_3_cuotas: response.data.precio_pvp_3_cuotas,
                precio_pvp_6_cuotas: response.data.precio_pvp_6_cuotas,
                precio_pvp_9_cuotas: response.data.precio_pvp_9_cuotas,
                precio_pvp_12_cuotas: response.data.precio_pvp_12_cuotas,
                markup_pvp_3_cuotas: response.data.markup_pvp_3_cuotas,
                markup_pvp_6_cuotas: response.data.markup_pvp_6_cuotas,
                markup_pvp_9_cuotas: response.data.markup_pvp_9_cuotas,
                markup_pvp_12_cuotas: response.data.markup_pvp_12_cuotas
              }
            : p
        ));
      } else {
        setProductos((prods) => prods.map((p) =>
          p.item_id === producto.item_id
            ? {
                ...p,
                precio_3_cuotas: response.data.precio_3_cuotas,
                precio_6_cuotas: response.data.precio_6_cuotas,
                precio_9_cuotas: response.data.precio_9_cuotas,
                precio_12_cuotas: response.data.precio_12_cuotas,
                markup_3_cuotas: response.data.markup_3_cuotas,
                markup_6_cuotas: response.data.markup_6_cuotas,
                markup_9_cuotas: response.data.markup_9_cuotas,
                markup_12_cuotas: response.data.markup_12_cuotas
              }
            : p
        ));
      }

      showToast(`Cuotas ${listaTipo === 'pvp' ? 'PVP' : 'Web'} recalculadas`, 'success');
      cargarStats();
    } catch (error) {
      showToast(`Error al recalcular cuotas: ${error.response?.data?.detail || error.message}`, 'error');
    }
  }, [setProductos, cargarStats, showToast]);

  const recalcularCuotasMasivo = useCallback(async () => {
    const listaTipo = modoVista === 'pvp' ? 'pvp' : 'web';

    const {
      debouncedSearch,
      filtroStock,
      filtroPrecio,
      marcasSeleccionadas,
      subcategoriasSeleccionadas,
      pmsSeleccionados,
      filtroRebate,
      filtroOferta,
      filtroWebTransf,
      filtroTiendaNube,
      filtroMarkupClasica,
      filtroMarkupRebate,
      filtroMarkupOferta,
      filtroMarkupWebTransf,
      filtroOutOfCards,
      coloresSeleccionados,
      filtroMLA,
      filtroEstadoMLA,
      filtroNuevos,
    } = filtros;

    const hayFiltros = debouncedSearch || filtroStock !== 'todos' || filtroPrecio !== 'todos' ||
      marcasSeleccionadas.length > 0 || subcategoriasSeleccionadas.length > 0 ||
      pmsSeleccionados.length > 0 || filtroRebate || filtroOferta || filtroWebTransf ||
      filtroTiendaNube || filtroMarkupClasica || filtroMarkupRebate || filtroMarkupOferta ||
      filtroMarkupWebTransf || filtroOutOfCards || coloresSeleccionados.length > 0 ||
      filtroMLA || filtroEstadoMLA || filtroNuevos;

    setRecalculandoCuotasMasivo(true);
    try {
      const body = { lista_tipo: listaTipo };

      if (hayFiltros) {
        body.filtros = {};
        if (debouncedSearch) body.filtros.search = debouncedSearch;
        if (filtroStock === 'con_stock') body.filtros.con_stock = true;
        if (filtroStock === 'sin_stock') body.filtros.con_stock = false;
        if (filtroPrecio === 'con_precio') body.filtros.con_precio = true;
        if (filtroPrecio === 'sin_precio') body.filtros.con_precio = false;
        if (marcasSeleccionadas.length > 0) body.filtros.marcas = marcasSeleccionadas.join(',');
        if (subcategoriasSeleccionadas.length > 0) body.filtros.subcategorias = subcategoriasSeleccionadas.join(',');
        if (filtroRebate === 'con_rebate') body.filtros.con_rebate = true;
        if (filtroRebate === 'sin_rebate') body.filtros.con_rebate = false;
        if (filtroOferta === 'con_oferta') body.filtros.con_oferta = true;
        if (filtroOferta === 'sin_oferta') body.filtros.con_oferta = false;
        if (filtroWebTransf === 'con_web_transf') body.filtros.con_web_transf = true;
        if (filtroWebTransf === 'sin_web_transf') body.filtros.con_web_transf = false;
        if (filtroOutOfCards === 'con_out_of_cards') body.filtros.out_of_cards = true;
        if (filtroOutOfCards === 'sin_out_of_cards') body.filtros.out_of_cards = false;
        if (filtroMarkupClasica === 'positivo') body.filtros.markup_clasica_positivo = true;
        if (filtroMarkupClasica === 'negativo') body.filtros.markup_clasica_positivo = false;
        if (coloresSeleccionados.length > 0) body.filtros.colores = coloresSeleccionados.join(',');
        if (pmsSeleccionados.length > 0) body.filtros.pms = pmsSeleccionados.join(',');
        if (filtroMLA === 'con_mla') body.filtros.con_mla = true;
        if (filtroMLA === 'sin_mla') body.filtros.con_mla = false;
        if (filtroEstadoMLA === 'activa') body.filtros.estado_mla = 'activa';
        if (filtroEstadoMLA === 'pausada') body.filtros.estado_mla = 'pausada';
        if (filtroNuevos === 'ultimos_7_dias') body.filtros.nuevos_ultimos_7_dias = true;
      }

      const response = await api.post('/productos/recalcular-cuotas-masivo', body);

      const { procesados, errores } = response.data;
      const mensajeErrores = errores > 0 ? ` (${errores} con errores)` : '';
      showToast(
        `Cuotas ${listaTipo.toUpperCase()} recalculadas: ${procesados} productos${mensajeErrores}`,
        errores > 0 ? 'warning' : 'success'
      );

      cargarProductos();
      cargarStats();
    } catch (error) {
      showToast(`Error al recalcular cuotas masivamente: ${error.response?.data?.detail || error.message}`, 'error');
    } finally {
      setRecalculandoCuotasMasivo(false);
    }
  }, [modoVista, filtros, cargarProductos, cargarStats, showToast]);

  const guardarPrecio = useCallback(async (itemId, forzar = false) => {
    try {
      const precioNormalizado = parseFloat(precioTemp.toString().replace(',', '.'));

      if (!isValidNumericInput(precioNormalizado) || precioNormalizado < 0) {
        showToast('El precio debe ser un número válido mayor o igual a 0', 'error');
        return;
      }

      const producto = productos.find(p => p.item_id === itemId);
      const shouldRecalcularCuotas = producto?.recalcular_cuotas_auto !== null
        ? producto.recalcular_cuotas_auto
        : recalcularCuotasAuto;

      if (!forzar && precioNormalizado > 0) {
        const markupData = await consultarMarkup(itemId, precioNormalizado, modoVista === 'pvp' ? 'pvp' : 'web');

        if (markupData && markupData.markup < 0) {
          setDatosGuardadoPendiente({
            itemId,
            precio: precioNormalizado,
            producto,
            markup: markupData.markup,
            listaTipo: modoVista === 'pvp' ? 'pvp' : 'web'
          });
          setMostrarModalMarkupNegativo(true);
          return;
        }
      }

      if (modoVista === 'pvp') {
        const response = await api.post(
          '/precios/set-rapido',
          null,
          {
            params: {
              item_id: itemId,
              precio: precioNormalizado,
              recalcular_cuotas: shouldRecalcularCuotas,
              lista_tipo: 'pvp'
            }
          }
        );

        if (response.data.precios_borrados) {
          setProductos(prods => prods.map(p =>
            p.item_id === itemId
              ? {
                  ...p,
                  precio_pvp: null,
                  markup_pvp: null,
                  precio_pvp_3_cuotas: null,
                  precio_pvp_6_cuotas: null,
                  precio_pvp_9_cuotas: null,
                  precio_pvp_12_cuotas: null,
                  markup_pvp_3_cuotas: null,
                  markup_pvp_6_cuotas: null,
                  markup_pvp_9_cuotas: null,
                  markup_pvp_12_cuotas: null
                }
              : p
          ));
          showToast('Precios PVP borrados', 'success');
        } else {
          setProductos(prods => prods.map(p =>
            p.item_id === itemId
              ? {
                  ...p,
                  precio_pvp: precioNormalizado,
                  markup_pvp: response.data.markup_pvp,
                  precio_pvp_3_cuotas: response.data.precio_pvp_3_cuotas || p.precio_pvp_3_cuotas,
                  precio_pvp_6_cuotas: response.data.precio_pvp_6_cuotas || p.precio_pvp_6_cuotas,
                  precio_pvp_9_cuotas: response.data.precio_pvp_9_cuotas || p.precio_pvp_9_cuotas,
                  precio_pvp_12_cuotas: response.data.precio_pvp_12_cuotas || p.precio_pvp_12_cuotas,
                  markup_pvp_3_cuotas: response.data.markup_pvp_3_cuotas !== undefined ? response.data.markup_pvp_3_cuotas : p.markup_pvp_3_cuotas,
                  markup_pvp_6_cuotas: response.data.markup_pvp_6_cuotas !== undefined ? response.data.markup_pvp_6_cuotas : p.markup_pvp_6_cuotas,
                  markup_pvp_9_cuotas: response.data.markup_pvp_9_cuotas !== undefined ? response.data.markup_pvp_9_cuotas : p.markup_pvp_9_cuotas,
                  markup_pvp_12_cuotas: response.data.markup_pvp_12_cuotas !== undefined ? response.data.markup_pvp_12_cuotas : p.markup_pvp_12_cuotas,
                  tiene_precio: true
                }
              : p
          ));
        }

        setEditandoPrecio(null);
        cargarStats();
        return;
      }

      // Modo web
      const response = await api.post(
        '/precios/set-rapido',
        null,
        {
          params: {
            item_id: itemId,
            precio: precioNormalizado,
            recalcular_cuotas: shouldRecalcularCuotas
          }
        }
      );

      if (response.data.precios_borrados) {
        setProductos(prods => prods.map(p =>
          p.item_id === itemId
            ? {
                ...p,
                precio_lista_ml: null,
                markup: null,
                precio_3_cuotas: null,
                precio_6_cuotas: null,
                precio_9_cuotas: null,
                precio_12_cuotas: null,
                markup_3_cuotas: null,
                markup_6_cuotas: null,
                markup_9_cuotas: null,
                markup_12_cuotas: null,
                precio_web_transferencia: null,
                markup_web_real: null,
                precio_rebate: null,
                markup_rebate: null,
                markup_oferta: null
              }
            : p
        ));
        showToast('Precios Web borrados', 'success');
      } else {
        setProductos(prods => prods.map(p =>
          p.item_id === itemId
            ? {
                ...p,
                precio_lista_ml: precioNormalizado,
                markup: response.data.markup,
                precio_3_cuotas: response.data.precio_3_cuotas || p.precio_3_cuotas,
                precio_6_cuotas: response.data.precio_6_cuotas || p.precio_6_cuotas,
                precio_9_cuotas: response.data.precio_9_cuotas || p.precio_9_cuotas,
                precio_12_cuotas: response.data.precio_12_cuotas || p.precio_12_cuotas,
                markup_3_cuotas: response.data.markup_3_cuotas !== undefined ? response.data.markup_3_cuotas : p.markup_3_cuotas,
                markup_6_cuotas: response.data.markup_6_cuotas !== undefined ? response.data.markup_6_cuotas : p.markup_6_cuotas,
                markup_9_cuotas: response.data.markup_9_cuotas !== undefined ? response.data.markup_9_cuotas : p.markup_9_cuotas,
                markup_12_cuotas: response.data.markup_12_cuotas !== undefined ? response.data.markup_12_cuotas : p.markup_12_cuotas,
                precio_rebate: response.data.precio_rebate !== null && response.data.precio_rebate !== undefined ? response.data.precio_rebate : p.precio_rebate,
                precio_web_transferencia: response.data.precio_web_transferencia !== null && response.data.precio_web_transferencia !== undefined ? response.data.precio_web_transferencia : p.precio_web_transferencia,
                markup_web_real: response.data.markup_web_real !== null && response.data.markup_web_real !== undefined ? response.data.markup_web_real : p.markup_web_real,
                tiene_precio: true
              }
            : p
        ));
      }

      setEditandoPrecio(null);
      cargarStats();
    } catch {
      showToast('Error al guardar precio', 'error');
    }
  }, [precioTemp, productos, recalcularCuotasAuto, modoVista, consultarMarkup, setProductos, cargarStats, showToast]);

  const confirmarGuardadoMarkupNegativo = useCallback(async () => {
    if (!datosGuardadoPendiente) return;

    setMostrarModalMarkupNegativo(false);

    if (datosGuardadoPendiente.esCuota) {
      await guardarCuota(
        datosGuardadoPendiente.itemId,
        datosGuardadoPendiente.tipo,
        datosGuardadoPendiente.esPVP,
        true
      );
    } else {
      await guardarPrecio(datosGuardadoPendiente.itemId, true);
    }

    setDatosGuardadoPendiente(null);
  }, [datosGuardadoPendiente, guardarCuota, guardarPrecio]);

  const cancelarMarkupNegativo = useCallback(() => {
    setMostrarModalMarkupNegativo(false);
    setDatosGuardadoPendiente(null);
  }, []);

  return {
    // State
    editandoPrecio,
    setEditandoPrecio,
    precioTemp,
    setPrecioTemp,
    editandoCuota,
    setEditandoCuota,
    cuotaTemp,
    setCuotaTemp,
    modoVista,
    setModoVista,
    recalcularCuotasAuto,
    setRecalcularCuotasAuto,
    mostrarModalMarkupNegativo,
    setMostrarModalMarkupNegativo,
    datosGuardadoPendiente,
    setDatosGuardadoPendiente,
    recalculandoCuotasMasivo,
    // Functions
    consultarMarkup,
    iniciarEdicion,
    iniciarEdicionCuota,
    guardarCuota,
    guardarPrecio,
    recalcularCuotasDesdeClasica,
    recalcularCuotasMasivo,
    confirmarGuardadoMarkupNegativo,
    cancelarMarkupNegativo,
  };
}
