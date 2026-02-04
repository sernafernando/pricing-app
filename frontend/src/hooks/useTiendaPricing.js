import { useState } from 'react';
import api from '../services/api';

/**
 * Custom hook para manejar TODA la lógica de edición de precios en la vista Tienda.
 * Incluye: web transferencia, cuotas, precio gremio, colores, rebate, out-of-cards.
 *
 * @param {Object} params
 * @param {Function} params.setProductos - Setter del array de productos (viene de useTiendaData)
 * @param {Array} params.productos - Array actual de productos (para búsquedas por item_id)
 * @param {Function} params.cargarProductos - Recarga productos desde el servidor
 * @param {Function} params.cargarStats - Recarga estadísticas
 * @param {Function} params.showToast - Función de notificación
 */
export function useTiendaPricing({
  setProductos,
  productos,
  cargarProductos,
  cargarStats,
  showToast,
}) {

  // === ESTADOS DE EDICIÓN ===
  const [editandoPrecio, setEditandoPrecio] = useState(null);
  const [, setPrecioTemp] = useState('');
  const [editandoRebate, setEditandoRebate] = useState(null);
  const [, setRebateTemp] = useState({ participa: false, porcentaje: 3.8 });
  const [editandoWebTransf, setEditandoWebTransf] = useState(null);
  const [webTransfTemp, setWebTransfTemp] = useState({ participa: false, porcentaje: 6.0, preservar: false });
  const [editandoCuota, setEditandoCuota] = useState(null);
  const [cuotaTemp, setCuotaTemp] = useState('');
  const [editandoPrecioGremio, setEditandoPrecioGremio] = useState(null);
  const [modoEdicionGremio, setModoEdicionGremio] = useState('precio');
  const [precioGremioTemp, setPrecioGremioTemp] = useState({ sin_iva: '', con_iva: '', markup: '' });

  // === WEB TRANSFERENCIA ===

  const iniciarEdicionWebTransf = (producto) => {
    setEditandoWebTransf(producto.item_id);
    setWebTransfTemp({
      participa: producto.participa_web_transferencia || false,
      porcentaje: producto.porcentaje_markup_web || 6.0,
      preservar: producto.preservar_porcentaje_web || false
    });
  };

  const guardarWebTransf = async (itemId) => {
    try {
      // Normalizar: reemplazar coma por punto
      const porcentajeNumerico = parseFloat(webTransfTemp.porcentaje.toString().replace(',', '.')) || 0;

      const response = await api.patch(
        `/productos/${itemId}/web-transferencia`,
        null,
        {
          params: {
            participa: webTransfTemp.participa,
            porcentaje_markup: porcentajeNumerico,
            preservar_porcentaje: webTransfTemp.preservar
          }
        }
      );

      setProductos(prods => prods.map(p =>
        p.item_id === itemId
          ? {
              ...p,
              participa_web_transferencia: webTransfTemp.participa,
              porcentaje_markup_web: porcentajeNumerico,
              preservar_porcentaje_web: webTransfTemp.preservar,
              precio_web_transferencia: response.data.precio_web_transferencia,
              markup_web_real: response.data.markup_web_real
            }
          : p
      ));

      setEditandoWebTransf(null);
    } catch {
      showToast('Error al guardar web transferencia', 'error');
    }
  };

  // === COLORES ===

  const cambiarColorProducto = async (itemId, color) => {
    try {
      await api.patch(
        `/productos/${itemId}/color-tienda`,
        { color }
      );

      setProductos(prods => prods.map(p =>
        p.item_id === itemId
          ? { ...p, color_marcado_tienda: color }
          : p
      ));

      cargarStats();
    } catch {
      showToast('Error al cambiar el color', 'error');
    }
  };

  const cambiarColorRapido = async (itemId, color) => {
    try {
      await api.patch(
        `/productos/${itemId}/color-tienda`,
        { color }
      );

      setProductos(prods => prods.map(p =>
        p.item_id === itemId
          ? { ...p, color_marcado_tienda: color }
          : p
      ));

      cargarStats();
    } catch {
      showToast('Error cambiando color', 'error');
    }
  };

  // === CUOTAS ===

  const iniciarEdicionCuota = (producto, tipo) => {
    setEditandoCuota({ item_id: producto.item_id, tipo });
    const campoPrecio = `precio_${tipo}_cuotas`;
    setCuotaTemp(producto[campoPrecio] || '');
  };

  const guardarCuota = async (itemId, tipo) => {
    try {
      const precioNormalizado = parseFloat(cuotaTemp.toString().replace(',', '.'));

      const response = await api.post(
        `/precios/set-cuota`,
        null,
        {
          params: {
            item_id: itemId,
            tipo_cuota: tipo,
            precio: precioNormalizado
          }
        }
      );

      const campoPrecio = `precio_${tipo}_cuotas`;
      const campoMarkup = `markup_${tipo}_cuotas`;

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
    } catch {
      showToast('Error al guardar precio de cuota', 'error');
    }
  };

  // === PRECIO GREMIO ===

  const calcularPrecioDesdeMarkup = (producto, markupPorcentaje) => {
    if (!producto.costo_ars || producto.costo_ars <= 0) {
      return { sin_iva: 0, con_iva: 0 };
    }

    const costo_ars = parseFloat(producto.costo_ars);
    const varios_porcentaje = 7; // Constante del sistema
    const markup_decimal = parseFloat(markupPorcentaje) / 100;
    const iva_decimal = (producto.iva || 21) / 100;

    // Fórmula: Precio sin IVA = Costo × (1 + Varios%) × (1 + Markup%)
    const precio_sin_iva = costo_ars * (1 + varios_porcentaje / 100) * (1 + markup_decimal);
    const precio_con_iva = precio_sin_iva * (1 + iva_decimal);

    return {
      sin_iva: precio_sin_iva,
      con_iva: precio_con_iva
    };
  };

  const calcularMarkupDesdePrecios = (costoArs, precioSinIva) => {
    if (!costoArs || costoArs <= 0) return null;

    const varios_porcentaje = 7;
    const precio_base = precioSinIva / (1 + varios_porcentaje / 100);
    const markup = ((precio_base / costoArs) - 1) * 100;

    return markup;
  };

  const iniciarEdicionPrecioGremio = (producto, event) => {
    if (event?.ctrlKey || event?.metaKey) {
      // MODO MARKUP
      setModoEdicionGremio('markup');
      setEditandoPrecioGremio(producto.item_id);
      setPrecioGremioTemp({
        sin_iva: '',
        con_iva: '',
        markup: producto.markup_gremio?.toFixed(1) || ''
      });
    } else {
      // MODO PRECIO (normal)
      setModoEdicionGremio('precio');
      setEditandoPrecioGremio(producto.item_id);
      setPrecioGremioTemp({
        sin_iva: producto.precio_gremio_sin_iva || '',
        con_iva: producto.precio_gremio_con_iva || '',
        markup: ''
      });
    }
  };

  const guardarPrecioGremio = async (itemId) => {
    try {
      const producto = productos.find(p => p.item_id === itemId);

      let precioSinIva, precioConIva;

      if (modoEdicionGremio === 'precio') {
        precioSinIva = parseFloat(precioGremioTemp.sin_iva.toString().replace(',', '.'));
        precioConIva = parseFloat(precioGremioTemp.con_iva.toString().replace(',', '.'));

        if (isNaN(precioSinIva) && isNaN(precioConIva)) {
          showToast('⚠️ Ingresá al menos un precio válido', 'error');
          return;
        }

        if (isNaN(precioSinIva)) {
          const iva_decimal = (producto.iva || 21) / 100;
          precioSinIva = precioConIva / (1 + iva_decimal);
        }
        if (isNaN(precioConIva)) {
          const iva_decimal = (producto.iva || 21) / 100;
          precioConIva = precioSinIva * (1 + iva_decimal);
        }

      } else {
        const markup = parseFloat(precioGremioTemp.markup.toString().replace(',', '.'));

        if (isNaN(markup)) {
          showToast('⚠️ Ingresá un markup válido', 'error');
          return;
        }

        const precios = calcularPrecioDesdeMarkup(producto, markup);
        precioSinIva = precios.sin_iva;
        precioConIva = precios.con_iva;
      }

      if (precioSinIva < 0 || precioConIva < 0) {
        showToast('⚠️ Los precios no pueden ser negativos', 'error');
        return;
      }

      await api.patch(
        `/productos/${itemId}/precio-gremio-override?precio_sin_iva=${precioSinIva}&precio_con_iva=${precioConIva}`,
        null
      );

      const markupCalculado = calcularMarkupDesdePrecios(producto.costo_ars, precioSinIva);

      setProductos(prods => prods.map(p =>
        p.item_id === itemId
          ? {
              ...p,
              precio_gremio_sin_iva: precioSinIva,
              precio_gremio_con_iva: precioConIva,
              markup_gremio: markupCalculado,
              tiene_override_gremio: true
            }
          : p
      ));

      setEditandoPrecioGremio(null);
      showToast(`✅ Precio gremio actualizado ${modoEdicionGremio === 'markup' ? '(desde markup)' : ''}`);

    } catch {
      showToast('❌ Error al guardar precio gremio', 'error');
    }
  };

  const eliminarPrecioGremioManual = async (itemId) => {
    try {
      await api.delete(
        `/productos/${itemId}/precio-gremio-override`
      );

      await cargarProductos();
      showToast('✅ Precio manual eliminado, vuelve al cálculo automático');
    } catch {
      showToast('❌ Error al eliminar precio manual', 'error');
    }
  };

  const eliminarTodosPreciosGremioManuales = async () => {
    if (!window.confirm('⚠️ ¿Estás seguro de eliminar TODOS los precios gremio manuales?\n\nTodos los productos volverán al cálculo automático.')) {
      return;
    }

    try {
      const response = await api.delete(
        `/productos/precio-gremio-override/todos`
      );

      await cargarProductos();
      showToast(`✅ ${response.data.message}`);
    } catch {
      showToast('❌ Error al eliminar precios manuales', 'error');
    }
  };

  // === TOGGLES RÁPIDOS (usados por teclado y UI) ===

  const toggleRebateRapido = async (producto) => {
    try {
      if (!producto.participa_rebate) {
        await api.patch(
          `/productos/${producto.item_id}/rebate`,
          {
            participa_rebate: true,
            porcentaje_rebate: producto.porcentaje_rebate || 3.8
          }
        );

        setProductos(prods => prods.map(p =>
          p.item_id === producto.item_id
            ? {
                ...p,
                participa_rebate: true,
                porcentaje_rebate: producto.porcentaje_rebate || 3.8
              }
            : p
        ));

        setEditandoRebate(producto.item_id);
        setRebateTemp({
          participa: true,
          porcentaje: producto.porcentaje_rebate || 3.8
        });

        setTimeout(() => {
          const input = document.querySelector('.rebate-edit input[type="number"]');
          if (input) {
            input.focus();
            input.select();
          }
        }, 100);

        cargarStats();
      } else {
        await api.patch(
          `/productos/${producto.item_id}/rebate`,
          {
            participa_rebate: false,
            porcentaje_rebate: producto.porcentaje_rebate || 3.8
          }
        );

        setProductos(prods => prods.map(p =>
          p.item_id === producto.item_id
            ? {
                ...p,
                participa_rebate: false,
                precio_rebate: null
              }
            : p
        ));

        cargarStats();
      }
    } catch {
      showToast('Error al cambiar rebate', 'error');
    }
  };

  const toggleWebTransfRapido = async (producto) => {
    try {
      const response = await api.patch(
        `/productos/${producto.item_id}/web-transferencia`,
        {
          participa: !producto.participa_web_transferencia,
          porcentaje: producto.porcentaje_markup_web || 6.0
        }
      );

      setProductos(prods => prods.map(p =>
        p.item_id === producto.item_id
          ? {
              ...p,
              participa_web_transferencia: !producto.participa_web_transferencia,
              precio_web_transferencia: response.data.precio_web_transferencia,
              markup_web_real: response.data.markup_web_real
            }
          : p
      ));

      cargarStats();
    } catch {
      showToast('Error al cambiar web transferencia', 'error');
    }
  };

  const toggleOutOfCardsRapido = async (producto) => {
    try {
      if (producto.out_of_cards) {
        await api.patch(
          `/productos/${producto.item_id}/out-of-cards`,
          { out_of_cards: false }
        );

        setProductos(prods => prods.map(p =>
          p.item_id === producto.item_id
            ? { ...p, out_of_cards: false }
            : p
        ));

        if (editandoRebate === producto.item_id) {
          setEditandoRebate(null);
        }

        cargarStats();
        return;
      }

      let rebateResponse = null;
      if (!producto.participa_rebate) {
        rebateResponse = await api.patch(
          `/productos/${producto.item_id}/rebate`,
          {
            participa_rebate: true,
            porcentaje_rebate: producto.porcentaje_rebate || 3.8
          }
        );
      }

      await api.patch(
        `/productos/${producto.item_id}/out-of-cards`,
        { out_of_cards: true }
      );

      setProductos(prods => prods.map(p =>
        p.item_id === producto.item_id
          ? {
              ...p,
              out_of_cards: true,
              participa_rebate: true,
              precio_rebate: rebateResponse?.data?.precio_rebate || p.precio_rebate,
              porcentaje_rebate: rebateResponse?.data?.porcentaje_rebate || p.porcentaje_rebate
            }
          : p
      ));

      setEditandoRebate(producto.item_id);
      setRebateTemp({
        participa: true,
        porcentaje: producto.porcentaje_rebate || 3.8
      });

      setTimeout(() => {
        const input = document.querySelector('.rebate-edit input[type="number"]');
        if (input) {
          input.focus();
          input.select();
        }
      }, 100);

      cargarStats();
    } catch {
      showToast('Error al cambiar out of cards', 'error');
    }
  };

  // === EDICIÓN DESDE TECLADO (puente entre keyboard hook y funciones de edición) ===

  const iniciarEdicionDesdeTeclado = (producto, columna) => {
    if (columna === 'precio_clasica') {
      setEditandoPrecio(producto.item_id);
      setPrecioTemp(producto.precio_lista_ml || '');
    } else if (columna === 'precio_gremio') {
      // Precio Gremio es solo lectura - no se edita directamente
    } else if (columna === 'precio_web_transf') {
      setEditandoWebTransf(producto.item_id);
      setWebTransfTemp({
        participa: producto.participa_web_transferencia || false,
        porcentaje: producto.porcentaje_markup_web || 6.0
      });
    } else if (columna === 'cuotas_3') {
      iniciarEdicionCuota(producto, '3');
    } else if (columna === 'cuotas_6') {
      iniciarEdicionCuota(producto, '6');
    } else if (columna === 'cuotas_9') {
      iniciarEdicionCuota(producto, '9');
    } else if (columna === 'cuotas_12') {
      iniciarEdicionCuota(producto, '12');
    }
  };

  return {
    // Estado de edición (leído por JSX y keyboard handler)
    editandoPrecio, setEditandoPrecio,
    editandoRebate, setEditandoRebate,
    editandoWebTransf, setEditandoWebTransf,
    webTransfTemp, setWebTransfTemp,
    editandoCuota, setEditandoCuota,
    cuotaTemp, setCuotaTemp,
    editandoPrecioGremio, setEditandoPrecioGremio,
    modoEdicionGremio, setModoEdicionGremio,
    precioGremioTemp, setPrecioGremioTemp,
    setPrecioTemp, setRebateTemp,

    // Funciones de edición
    iniciarEdicionWebTransf,
    guardarWebTransf,
    cambiarColorProducto,
    cambiarColorRapido,
    iniciarEdicionCuota,
    guardarCuota,
    calcularPrecioDesdeMarkup,
    calcularMarkupDesdePrecios,
    iniciarEdicionPrecioGremio,
    guardarPrecioGremio,
    eliminarPrecioGremioManual,
    eliminarTodosPreciosGremioManuales,
    toggleRebateRapido,
    toggleWebTransfRapido,
    toggleOutOfCardsRapido,
    iniciarEdicionDesdeTeclado,
  };
}
