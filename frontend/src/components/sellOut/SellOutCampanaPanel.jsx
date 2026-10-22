import { useEffect, useState } from 'react';
import { X } from 'lucide-react';
import { sellOutAPI } from '../../services/sellOutAPI';
import { formatDateOnly } from '../../utils/dateUtils';
import { StatusPill } from '../kit';
import { apiMessage, formatEntero, formatMonto } from '../sellIn/sellInFormat';
import SellOutCampanaForm from './SellOutCampanaForm';
import { CANAL_LABELS, TC_MODO_LABELS, beneficio, recalculo } from './sellOutFormat';
import { CAMPANA_VACIA, bodyDeCampana, faltantes, valoresDeCampana } from './sellOutValores';
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
 * A sell-out campaign in the side panel (feature sell-in-sell-out T8), no modals. With no `campanaId` it
 * loads a new one. Otherwise it reads it fresh from `GET /sell-out/campanas/{id}`: its terms, what it
 * credited by channel and its recalculation state; with `sell_out.gestionar` an active one is edited in
 * place (a full replace). The backend's messages (422/409) show inline; a 409 reads the campaign again.
 */
export default function SellOutCampanaPanel({ campanaId, grupos = [], puedeGestionar = false, onSaved, onClose }) {
  const nuevo = campanaId === null;
  const [campana, setCampana] = useState(null);
  const [valores, setValores] = useState(CAMPANA_VACIA);
  const [error, setError] = useState(null);
  const [busy, setBusy] = useState(false);

  const mostrar = (data) => {
    setCampana(data);
    setValores(valoresDeCampana(data));
  };

  useEffect(() => {
    if (nuevo) return undefined;
    let active = true;
    setCampana(null);
    setError(null);
    sellOutAPI
      .detalle(campanaId)
      .then(({ data }) => active && mostrar(data))
      .catch((err) => active && setError(apiMessage(err, 'No se pudo cargar la campaña.')));
    return () => {
      active = false;
    };
  }, [nuevo, campanaId]);

  const guardar = async () => {
    const faltan = faltantes(valores);
    if (faltan.length) {
      setError(`Faltan datos: ${faltan.join(', ')}.`);
      return;
    }
    setBusy(true);
    setError(null);
    try {
      const body = bodyDeCampana(valores);
      const { data } = nuevo ? await sellOutAPI.crear(body) : await sellOutAPI.editar(campanaId, body);
      if (!nuevo) mostrar(data);
      onSaved(data);
    } catch (err) {
      setError(apiMessage(err, 'No se pudo guardar la campaña.'));
      if (!nuevo && err?.response?.status === 409) {
        sellOutAPI
          .detalle(campanaId)
          .then(({ data }) => mostrar(data))
          .catch(() => {});
      }
    } finally {
      setBusy(false);
    }
  };

  const editable = puedeGestionar && (nuevo || campana?.estado === 'activa');
  // Editing shows the form; what the form does not hold (origin, recalculation, caps left) stays below it.
  const soloLectura = new Set(['Topes', 'Origen', 'Recálculo']);
  const campos = campana
    ? [
        ['Beneficio', beneficio(campana)],
        ['Vigencia', `${formatDateOnly(campana.fecha_desde, DIA)} – ${formatDateOnly(campana.fecha_hasta, DIA)}`],
        ['Tipo de cambio', campana.moneda === 'USD' ? TC_MODO_LABELS[campana.tc_modo] ?? '—' : 'No aplica (ARS)'],
        ['Alcance', (campana.grupos ?? []).map((g) => g.nombre).join(', ') || '—'],
        ['Topes', topes(campana)],
        ['Monto con IVA', campana.monto_incluye_iva ? 'Sí' : 'No'],
        ['Acumulable', campana.acumulable ? 'Sí' : 'No'],
        ['Origen', campana.offset_origen_id != null ? `Migrada del offset #${campana.offset_origen_id}` : 'Cargada a mano'],
        ['Recálculo', recalculo(campana.resumen?.recalculo)],
      ]
    : [];
  const visibles = editable ? campos.filter(([label]) => soloLectura.has(label)) : campos;
  const canales = campana?.resumen?.por_canal ?? [];

  return (
    <div className={panelStyles.panel}>
      <header className={panelStyles.panelHeader}>
        <h2>{nuevo ? 'Nueva campaña de sell out' : campana ? campana.nombre : 'Campaña de sell out'}</h2>
        <button type="button" className={panelStyles.close} aria-label="Cerrar" onClick={onClose} disabled={busy}>
          <X size={18} />
        </button>
      </header>

      <div className={panelStyles.panelBody}>
        {error && (
          <p className={panelStyles.error} role="alert">
            {error}
          </p>
        )}
        {!nuevo && !campana && !error && <p className={panelStyles.hint}>Cargando…</p>}
        {editable && (
          <section className={panelStyles.section} aria-label="Definición">
            <SellOutCampanaForm valores={valores} onChange={setValores} grupos={grupos} />
          </section>
        )}
        {campana && (
          <>
            <div className={panelStyles.pills}>
              <StatusPill tone={campana.estado === 'activa' ? 'success' : 'danger'}>
                {campana.estado === 'activa' ? 'Activa' : 'Anulada'}
              </StatusPill>
            </div>
            {!editable && campana.descripcion && <p className={panelStyles.hint}>{campana.descripcion}</p>}
            <dl className={panelStyles.campos}>
              {visibles.map(([label, value]) => (
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

      {editable && (
        <footer className={panelStyles.panelFooter}>
          <button type="button" className="btn-tesla outline sm" onClick={onClose} disabled={busy}>
            Cancelar
          </button>
          <button type="button" className="btn-tesla primary sm" onClick={guardar} disabled={busy}>
            {nuevo ? 'Guardar campaña' : 'Guardar cambios'}
          </button>
        </footer>
      )}
    </div>
  );
}
