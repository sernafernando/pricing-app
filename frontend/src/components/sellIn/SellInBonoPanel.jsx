import { useCallback, useEffect, useId, useState } from 'react';
import { Settings2, X } from 'lucide-react';
import { sellInBonosAPI } from '../../services/sellInAPI';
import { formatDateOnly } from '../../utils/dateUtils';
import { StatusPill } from '../kit';
import SellInBonoAlcance from './SellInBonoAlcance';
import SellInBonoForm from './SellInBonoForm';
import {
  BONO_VACIO,
  alcanceDeBono,
  bodyDeBono,
  bonoCompleto,
  errorDeModelos,
  errorDeTope,
  faltanDatos,
  restanteDeTope,
  valoresDeBono,
} from './sellInBonoValores';
import { apiMessage, formatEntero, formatMonto } from './sellInFormat';
import styles from './SellInPanel.module.css';

const MOTIVO_MAX = 500; // backend `SellInBonoAnularIn.motivo` (auditoria.comentario is VARCHAR(500))

/** What the bonus generated in another currency than its own (a purchase left there before a currency edit). */
const otrasMonedas = (bono) => (bono.montos_generados ?? []).filter((m) => m.moneda !== bono.moneda);

/**
 * A bonus in the right side panel (Stitch `03`), no modals; it reaches a brand, a category, some
 * models or one Compras operation, per unit or as a % of the invoiced net (`SellInBonoForm`). With no
 * `bonoId` it loads a new one; otherwise it reads the bonus and what it
 * reaches, and with `sell_in.gestionar` an active one can be edited (a full
 * replace) or voided after an inline confirmation. The backend's messages
 * (422/409/404) show inline. The worker applies the bonus by itself, so what
 * it reaches is read again after every save.
 */
export default function SellInBonoPanel({ bonoId = null, marcas, puedeGestionar, onSaved, onClose, onVerCompra, modoSwitch = null }) {
  const id = useId();
  const nuevo = bonoId === null;
  const [bono, setBono] = useState(null);
  const [valores, setValores] = useState(BONO_VACIO);
  const [alcance, setAlcance] = useState(null);
  const [alcanceError, setAlcanceError] = useState(null);
  const [error, setError] = useState(null);
  const [busy, setBusy] = useState(false);
  const [confirmando, setConfirmando] = useState(false);
  const [motivo, setMotivo] = useState('');

  // The bonus as stored: on load, and after a 409 (voided elsewhere) so the panel shows its real state.
  const leerBono = useCallback(
    (activo = () => true) =>
      sellInBonosAPI.detalle(bonoId).then(({ data }) => {
        if (!activo()) return;
        setBono(data);
        setValores(valoresDeBono(data));
      }),
    [bonoId],
  );

  // What the bonus reaches: on load and after every save (the worker re-applies it by itself).
  const leerAlcance = useCallback(
    (activo = () => true) => {
      setAlcanceError(null);
      return sellInBonosAPI
        .alcance(bonoId)
        .then(({ data }) => activo() && setAlcance(data))
        .catch((err) => activo() && setAlcanceError(apiMessage(err, 'No se pudo leer qué compras alcanza el bono.')));
    },
    [bonoId],
  );

  useEffect(() => {
    if (nuevo) return undefined;
    let active = true;
    leerBono(() => active).catch((err) => active && setError(apiMessage(err, 'No se pudo cargar el bono.')));
    leerAlcance(() => active);
    return () => {
      active = false;
    };
  }, [nuevo, leerBono, leerAlcance]);

  const aplicar = (data) => {
    setBono(data);
    setValores(valoresDeBono(data));
    onSaved(data);
  };

  const guardar = async () => {
    if (!bonoCompleto(valores)) {
      setError(faltanDatos(valores));
      return;
    }
    const invalido = errorDeModelos(valores) ?? errorDeTope(valores);
    if (invalido) {
      setError(invalido);
      return;
    }
    setBusy(true);
    setError(null);
    try {
      const body = bodyDeBono(valores);
      const { data } = nuevo ? await sellInBonosAPI.crear(body) : await sellInBonosAPI.editar(bonoId, body);
      if (nuevo) {
        onSaved(data);
        return;
      }
      aplicar(data);
      leerAlcance();
    } catch (err) {
      setError(apiMessage(err, 'No se pudo guardar el bono.'));
      if (!nuevo && err?.response?.status === 409) leerBono().catch(() => {});
    } finally {
      setBusy(false);
    }
  };

  const anular = async () => {
    setBusy(true);
    setError(null);
    try {
      const { data } = await sellInBonosAPI.anular(bonoId, motivo);
      setConfirmando(false);
      aplicar(data);
      leerAlcance();
    } catch (err) {
      setError(apiMessage(err, 'No se pudo anular el bono.'));
    } finally {
      setBusy(false);
    }
  };

  const activo = bono?.estado === 'activa';
  const restante = bono ? restanteDeTope(bono, formatEntero, formatMonto) : null;
  const editable = puedeGestionar && (nuevo || activo);
  const titulo = nuevo ? 'Nuevo sell in · Bono de marca' : bono ? bono.descripcion || `Bono · ${alcanceDeBono(bono)}` : 'Bono de marca';

  return (
    <div className={styles.panel}>
      <header className={styles.panelHeader}>
        <div>
          {bono && (
            <div className={styles.pills}>
              <StatusPill tone="purple">Bono de marca</StatusPill>
              <StatusPill tone={activo ? 'success' : 'danger'}>{activo ? 'Activo' : 'Anulado'}</StatusPill>
            </div>
          )}
          <h2>{titulo}</h2>
          {/* A timestamptz with its offset: formatted on the user's local (Argentina) day, never the UTC one. */}
          {bono?.created_at && <p className={styles.hint}>Creado el {formatDateOnly(bono.created_at)}</p>}
        </div>
        <button type="button" className={styles.close} aria-label="Cerrar" onClick={onClose} disabled={busy}>
          <X size={18} />
        </button>
      </header>
      {modoSwitch}

      <div className={styles.panelBody}>
        {error && (
          <p className={styles.error} role="alert">
            {error}
          </p>
        )}
        {!nuevo && !bono && !error && <p className={styles.hint}>Cargando…</p>}
        {(nuevo || bono) && (
          <section className={styles.section}>
            <h3>
              <Settings2 size={14} aria-hidden /> Definición
            </h3>
            <SellInBonoForm valores={valores} onChange={setValores} marcas={marcas} disabled={!editable} />
            {bono && (
              <p className={styles.hint}>
                <strong>{`${formatEntero(bono.compras_activas)} compras · ${formatEntero(bono.unidades)} u · ${formatMonto(bono.monto_generado, bono.moneda)} aplicados`}</strong>
              </p>
            )}
            {restante && <p className={styles.hint}>{`Tope: quedan ${restante}`}</p>}
            {bono && otrasMonedas(bono).length > 0 && (
              <p className={styles.hint}>{`Además ${otrasMonedas(bono)
                .map((m) => formatMonto(m.monto, m.moneda))
                .join(' y ')} en otra moneda (de antes de cambiarla).`}</p>
            )}
          </section>
        )}
        {alcanceError && (
          <p className={styles.error} role="alert">
            {alcanceError}
          </p>
        )}
        {bono && alcance && <SellInBonoAlcance alcance={alcance} onVerCompra={onVerCompra} />}
      </div>

      {editable && (
        <footer className={styles.panelFooter}>
          {confirmando ? (
            <div className={styles.confirm}>
              <label className={styles.field} htmlFor={`${id}-motivo`}>
                <span className={styles.label}>Motivo (opcional)</span>
                <textarea id={`${id}-motivo`} className={styles.textarea} maxLength={MOTIVO_MAX} value={motivo} onChange={(e) => setMotivo(e.target.value)} />
              </label>
              <p className={styles.hint}>Al anular el bono se anulan las compras que generó.</p>
              <div className={styles.confirmActions}>
                <button
                  type="button"
                  className="btn-tesla outline sm"
                  onClick={() => {
                    setConfirmando(false);
                    setMotivo('');
                  }}
                  disabled={busy}
                >
                  Cancelar
                </button>
                <button type="button" className="btn-tesla danger sm" onClick={anular} disabled={busy}>
                  Confirmar anulación
                </button>
              </div>
            </div>
          ) : nuevo ? (
            <>
              <button type="button" className="btn-tesla outline sm" onClick={onClose} disabled={busy}>
                Cancelar
              </button>
              <button type="button" className="btn-tesla primary sm" onClick={guardar} disabled={busy}>
                Guardar bono
              </button>
            </>
          ) : (
            <>
              <button type="button" className="btn-tesla outline sm" onClick={() => setConfirmando(true)} disabled={busy}>
                Anular bono
              </button>
              <button type="button" className="btn-tesla primary sm" onClick={guardar} disabled={busy}>
                Guardar cambios
              </button>
            </>
          )}
        </footer>
      )}
    </div>
  );
}
