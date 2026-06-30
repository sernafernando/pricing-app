import { useState } from 'react';
import api from '../services/api';
import { isValidNumericInput } from '../utils/productosFormat';

/**
 * Manages quick toggles (rebate, web-transf, out-of-cards) and inline edit state
 * for rebate and web-transf fields.
 *
 * Decision ADR-4: editandoRebate + rebateTemp live here (co-located with toggles).
 * toggleOutOfCardsRapido writes editandoRebate directly — internal cross-write,
 * no injection. Mirrors useTiendaPricing pattern exactly.
 *
 * Receives: { productos, setProductos, cargarStats, showToast }
 */
export function useProductosToggles({ setProductos, cargarStats, showToast }) {
  const [editandoRebate, setEditandoRebate] = useState(null);
  const [rebateTemp, setRebateTemp] = useState({ participa: false, porcentaje: 3.8 });
  const [editandoWebTransf, setEditandoWebTransf] = useState(null);
  const [webTransfTemp, setWebTransfTemp] = useState({ participa: false, porcentaje: 6.0, preservar: false });

  const iniciarEdicionRebate = (producto) => {
    setEditandoRebate(producto.item_id);
    setRebateTemp({
      participa: producto.participa_rebate || false,
      porcentaje: producto.porcentaje_rebate !== null && producto.porcentaje_rebate !== undefined
        ? producto.porcentaje_rebate
        : 3.8
    });
  };

  const guardarRebate = async (itemId) => {
    try {
      // Normalizar: reemplazar coma por punto
      const porcentajeNormalizado = parseFloat(rebateTemp.porcentaje.toString().replace(',', '.'));

      // Validar que sea un número válido entre 0 y 100
      if (!isValidNumericInput(porcentajeNormalizado) || porcentajeNormalizado < 0 || porcentajeNormalizado > 100) {
        showToast('El porcentaje de rebate debe ser un número entre 0 y 100', 'error');
        return;
      }

      await api.patch(
        `/productos/${itemId}/rebate`,
        {
          participa_rebate: rebateTemp.participa,
          porcentaje_rebate: porcentajeNormalizado
        }
      );

      setProductos(prods => prods.map(p =>
        p.item_id === itemId
          ? {
              ...p,
              participa_rebate: rebateTemp.participa,
              porcentaje_rebate: porcentajeNormalizado,
              precio_rebate: rebateTemp.participa && p.precio_lista_ml
                ? p.precio_lista_ml / (1 - porcentajeNormalizado / 100)
                : null
            }
          : p
      ));

      setEditandoRebate(null);
    } catch {
      showToast('Error al guardar rebate', 'error');
    }
  };

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
      showToast('Error al guardar', 'error');
    }
  };

  const toggleRebateRapido = async (producto) => {
    try {
      // Si el rebate está desactivado, activarlo y abrir modo edición
      if (!producto.participa_rebate) {
        const response = await api.patch(
          `/productos/${producto.item_id}/rebate`,
          {
            participa_rebate: true,
            porcentaje_rebate: producto.porcentaje_rebate || 3.8
          }
        );

        // Actualizar estado local en lugar de recargar
        setProductos(prods => prods.map(p =>
          p.item_id === producto.item_id
            ? {
                ...p,
                participa_rebate: true,
                porcentaje_rebate: producto.porcentaje_rebate || 3.8,
                precio_rebate: response.data.precio_rebate,
                markup_rebate: response.data.markup_rebate
              }
            : p
        ));

        // Abrir modo edición
        setEditandoRebate(producto.item_id);
        setRebateTemp({
          participa: true,
          porcentaje: producto.porcentaje_rebate || 3.8
        });

        // Hacer focus en el input de porcentaje
        setTimeout(() => {
          const input = document.querySelector('.rebate-edit input[type="number"]');
          if (input) {
            input.focus();
            input.select();
          }
        }, 100);

        // Recargar stats para reflejar cambios en contadores
        cargarStats();
      } else {
        // Si está activado, desactivarlo
        await api.patch(
          `/productos/${producto.item_id}/rebate`,
          {
            participa_rebate: false,
            porcentaje_rebate: producto.porcentaje_rebate || 3.8
          }
        );

        // Actualizar estado local en lugar de recargar
        setProductos(prods => prods.map(p =>
          p.item_id === producto.item_id
            ? {
                ...p,
                participa_rebate: false,
                precio_rebate: null,
                markup_rebate: null
              }
            : p
        ));

        // Cerrar modo edición si estaba abierto
        if (editandoRebate === producto.item_id) {
          setEditandoRebate(null);
        }

        // Recargar stats para reflejar cambios en contadores
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

      // Actualizar estado local en lugar de recargar
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

      // Recargar stats para reflejar cambios en contadores
      cargarStats();
    } catch {
      showToast('Error al cambiar Web/Transferencia', 'error');
    }
  };

  const toggleOutOfCardsRapido = async (producto) => {
    try {
      // Si ya tiene out_of_cards, desactivarlo
      if (producto.out_of_cards) {
        await api.patch(
          `/productos/${producto.item_id}/out-of-cards`,
          { out_of_cards: false }
        );

        // Actualizar estado local en lugar de recargar
        setProductos(prods => prods.map(p =>
          p.item_id === producto.item_id
            ? { ...p, out_of_cards: false }
            : p
        ));

        // Cerrar modo edición si estaba abierto (internal cross-write — ADR-4)
        if (editandoRebate === producto.item_id) {
          setEditandoRebate(null);
        }

        // Recargar stats para reflejar cambios en contadores
        cargarStats();
        return;
      }

      // Si NO tiene out_of_cards, activarlo
      // Primero, si el rebate NO está activo, activarlo
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

      // Marcar out_of_cards = true
      await api.patch(
        `/productos/${producto.item_id}/out-of-cards`,
        { out_of_cards: true }
      );

      // Actualizar estado local en lugar de recargar
      setProductos(prods => prods.map(p =>
        p.item_id === producto.item_id
          ? {
              ...p,
              participa_rebate: true,
              porcentaje_rebate: producto.porcentaje_rebate || 3.8,
              out_of_cards: true,
              ...(rebateResponse && {
                precio_rebate: rebateResponse.data.precio_rebate,
                markup_rebate: rebateResponse.data.markup_rebate
              })
            }
          : p
      ));

      // Abrir modo edición (internal cross-write into rebate state — ADR-4)
      setEditandoRebate(producto.item_id);
      setRebateTemp({
        participa: true,
        porcentaje: producto.porcentaje_rebate || 3.8
      });

      // Hacer focus en el input de porcentaje
      setTimeout(() => {
        const input = document.querySelector('.rebate-edit input[type="number"]');
        if (input) {
          input.focus();
          input.select();
        }
      }, 100);

      // Recargar stats para reflejar cambios en contadores
      cargarStats();
    } catch {
      showToast('Error al cambiar Out of Cards', 'error');
    }
  };

  return {
    editandoRebate,
    setEditandoRebate,
    rebateTemp,
    setRebateTemp,
    editandoWebTransf,
    setEditandoWebTransf,
    webTransfTemp,
    setWebTransfTemp,
    iniciarEdicionRebate,
    guardarRebate,
    iniciarEdicionWebTransf,
    guardarWebTransf,
    toggleRebateRapido,
    toggleWebTransfRapido,
    toggleOutOfCardsRapido,
  };
}
