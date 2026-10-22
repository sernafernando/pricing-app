import { useEffect, useState } from 'react';
import { X } from 'lucide-react';
import { sellOutAPI } from '../../services/sellOutAPI';
import { formatDateOnly } from '../../utils/dateUtils';
import { StatusPill } from '../kit';
import { apiMessage, formatEntero, formatMonto } from '../sellIn/sellInFormat';
import { CANAL_LABELS, TC_MODO_LABELS, beneficio, recalculo } from './sellOutFormat';
import panelStyles from '../sellIn/SellInPanel.module.css';
import tableStyles from '../sellIn/SellInTable.module.css';

const DIA = { day: '2-digit', month: '2-digit', year: 'numeric' };

function topes(campana) {
  const { resumen } = campana;
  const partes = [];
  if (campana.tope_unidades != null) {
    partes.push(`${formatEntero(campana.tope_unidades)} u (quedan ${formatEntero(resumen?.tope_unidades_restantes)})`);
  }
  if (campana.tope_monto != null) {
    partes.push(
      `${formatMonto(campana.tope_monto, campana.moneda)} (quedan ${formatMonto(resumen?.tope_monto_restante, campana.moneda)})`,
    );
  }
  return partes.length ? partes.join(' · ') : 'Sin tope';
}

/**
 * One sell-out campaign in the side panel, read fresh from `GET /sell-out/campanas/{id}` (feature
 * sell-in-sell-out T8): its terms, what it credited by channel and its recalculation state.
 */
export default function SellOutCampanaPanel({ campanaId, onClose }) {
  const [campana, setCampana] = useState(null);
  const [error, setError] = useState(null);

  useEffect(() => {
    let active = true;
    setCampana(null);
    setError(null);
    sellOutAPI
      .detalle(campanaId)
      .then(({ data }) => active && setCampana(data))
      .catch((err) => active && setError(apiMessage(err, 'No se pudo cargar la campaña.')));
    return () => {
      active = false;
    };
  }, [campanaId]);

  const campos = campana
    ? [
        ['Beneficio', beneficio(campana)],
        ['Vigencia', `${formatDateOnly(campana.fecha_desde, DIA)} – ${formatDateOnly(campana.fecha_hasta, DIA)}`],
        ['Tipo de cambio', campana.moneda === 'USD' ? TC_MODO_LABELS[campana.tc_modo] ?? '—' : 'No aplica (ARS)'],
        ['Alcance', campana.grupos.map((g) => g.nombre).join(', ') || '—'],
        ['Topes', topes(campana)],
        ['Monto con IVA', campana.monto_incluye_iva ? 'Sí' : 'No'],
        ['Acumulable', campana.acumulable ? 'Sí' : 'No'],
        ['Origen', campana.offset_origen_id ? `Migrada del offset #${campana.offset_origen_id}` : 'Cargada a mano'],
        ['Recálculo', recalculo(campana.resumen?.recalculo)],
      ]
    : [];
  const canales = campana?.resumen?.por_canal ?? [];

  return (
    <div className={panelStyles.panel}>
      <header className={panelStyles.panelHeader}>
        <h2>{campana ? campana.nombre : 'Campaña de sell out'}</h2>
        <button type="button" className={panelStyles.close} aria-label="Cerrar" onClick={onClose}>
          <X size={18} />
        </button>
      </header>

      <div className={panelStyles.panelBody}>
        {error && (
          <p className={panelStyles.error} role="alert">
            {error}
          </p>
        )}
        {!campana && !error && <p className={panelStyles.hint}>Cargando…</p>}
        {campana && (
          <>
            <div className={panelStyles.pills}>
              <StatusPill tone={campana.estado === 'activa' ? 'success' : 'danger'}>
                {campana.estado === 'activa' ? 'Activa' : 'Anulada'}
              </StatusPill>
            </div>
            {campana.descripcion && <p className={panelStyles.hint}>{campana.descripcion}</p>}
            <dl className={panelStyles.campos}>
              {campos.map(([label, value]) => (
                <div key={label} className={panelStyles.campo}>
                  <dt>{label}</dt>
                  <dd>{value}</dd>
                </div>
              ))}
            </dl>
            <section className={panelStyles.section} aria-label="Acreditado por canal">
              <h3>Acreditado por canal</h3>
              {canales.length === 0 ? (
                <p className={panelStyles.hint}>Todavía no acreditó ventas.</p>
              ) : (
                <table className={tableStyles.table}>
                  <thead>
                    <tr>
                      <th>Canal</th>
                      <th className={tableStyles.num}>Ventas</th>
                      <th className={tableStyles.num}>Unidades</th>
                      <th className={tableStyles.num}>Monto</th>
                    </tr>
                  </thead>
                  <tbody>
                    {canales.map((c) => (
                      <tr key={c.canal}>
                        <td>{CANAL_LABELS[c.canal] ?? c.canal}</td>
                        <td className={tableStyles.num}>{formatEntero(c.lineas)}</td>
                        <td className={tableStyles.num}>{formatEntero(c.unidades)}</td>
                        <td className={tableStyles.num}>{formatMonto(c.monto, campana.moneda)}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              )}
            </section>
          </>
        )}
      </div>
    </div>
  );
}
