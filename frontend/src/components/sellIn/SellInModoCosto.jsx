import { useEffect, useId, useState } from 'react';
import { sellInLotesAPI } from '../../services/sellInAPI';
import { usePermisos } from '../../contexts/PermisosContext';
import SegmentedControl from '../kit/SegmentedControl';
import StatusPill from '../kit/StatusPill';
import SellInModoPorDefecto from './SellInModoPorDefecto';
import styles from './SellInModoCosto.module.css';

const MONEY = new Intl.NumberFormat('es-AR', { minimumFractionDigits: 2, maximumFractionDigits: 2 });
/** ARS with its sign in front of the symbol: "-$ 18.240,50". */
const money = (value) => {
  const n = Number(value);
  return `${n < 0 ? '-' : ''}$ ${MONEY.format(Math.abs(n))}`;
};

/** 'YYYY-MM-DD' (or an ISO datetime) as dd/mm/yyyy, without going through a Date (no time zone shift). */
function day(value) {
  const match = /^(\d{4})-(\d{2})-(\d{2})/.exec(value ?? '');
  return match ? `${match[3]}/${match[2]}/${match[1]}` : '-';
}

/** Today in the browser's local time as 'YYYY-MM-DD', the format of a date input. */
function today() {
  const now = new Date();
  const pad = (n) => String(n).padStart(2, '0');
  return `${now.getFullYear()}-${pad(now.getMonth() + 1)}-${pad(now.getDate())}`;
}

const PERMISO = {
  ponderado: 'sell_in.costo_ponderado',
  ultimo: 'sell_in.costo_ultimo',
  manual: 'sell_in.costo_manual',
};
const RETROACTIVO = 'sell_in.costo_retroactivo';

const MODOS = {
  fifo: { label: 'FIFO', nota: 'FIFO: cada venta toma primero el lote de compra más viejo.' },
  ponderado: {
    label: 'Ponderado (PPP)',
    nota: 'Ponderado (PPP): todas las unidades quedan a un mismo descuento de sell in por unidad.',
  },
  ultimo: {
    label: 'Último precio',
    nota: 'Último precio: todas las unidades quedan al descuento de sell in por unidad del lote más nuevo.',
  },
  manual: { label: 'Manual', nota: 'Manual: cargás la cantidad y el costo unitario que quedan.' },
};
const ORDEN = ['fifo', 'ponderado', 'ultimo', 'manual'];
const ADMINS = ['ADMIN', 'SUPERADMIN'];

/** What the preview says about ARS the lots hold that no unit hands out (positive) or handed beyond them (negative). */
function SinAsignar({ valor }) {
  const n = Number(valor);
  if (!n) return null;
  const texto =
    n > 0
      ? `Con este modo ${money(n)} de los lotes quedan sin asignar a ninguna unidad.`
      : `Con este modo se asignan ${money(-n)} más de lo que tienen los lotes.`;
  return <p className={styles.warning}>{texto}</p>;
}

function Preview({ vista, modo, antes, onConfirm, onCancel, saving }) {
  const id = useId();
  const quedan =
    vista.descuento_unit == null
      ? `Quedan ${vista.unidades_restantes} u sin sell in`
      : `Quedan ${vista.unidades_restantes} u a ${money(vista.descuento_unit)} de sell in c/u`;
  // FIFO keeps each lot's own value, so "after" is one figure only for the pooled modes.
  const comparar = modo !== 'fifo' && vista.descuento_unit != null;
  return (
    <section className={styles.preview} aria-labelledby={id} aria-live="polite">
      <h4 id={id}>Así queda</h4>
      <ul className={styles.facts}>
        <li>
          <span>Ventas ya registradas que cambian:</span> <b>{vista.ventas_cambian}</b>
        </li>
        <li>
          <span>Diferencia total:</span> <b>{money(vista.diferencia_ars)}</b>
        </li>
        <li>
          <b>{quedan}</b>
        </li>
      </ul>
      <SinAsignar valor={vista.sin_asignar_despues} />
      {comparar && (
        <table className={styles.mini}>
          <thead>
            <tr>
              <th scope="col">Descuento sell in por unidad</th>
              <th scope="col">Antes</th>
              <th scope="col">{`Después (${MODOS[modo].label})`}</th>
            </tr>
          </thead>
          <tbody>
            {antes.proxima != null && (
              <tr>
                <th scope="row">Próxima unidad</th>
                <td>{money(antes.proxima)}</td>
                <td>{money(vista.descuento_unit)}</td>
              </tr>
            )}
            {antes.nueva != null && (
              <tr>
                <th scope="row">Unidad más nueva</th>
                <td>{money(antes.nueva)}</td>
                <td>{money(vista.descuento_unit)}</td>
              </tr>
            )}
          </tbody>
        </table>
      )}
      <div className={styles.actions}>
        <button type="button" className="btn-tesla primary sm" onClick={onConfirm} disabled={saving}>
          {saving ? 'Guardando…' : 'Confirmar cambio'}
        </button>
        <button type="button" className="btn-tesla outline sm" onClick={onCancel} disabled={saving}>
          Cancelar
        </button>
      </div>
    </section>
  );
}

function errorText(error, accion) {
  const status = error?.response?.status;
  if (status === 409) {
    return 'El producto cambió desde la vista previa (o alguien lo está modificando). Tocá «Ver cómo queda» de nuevo.';
  }
  if (status === 403) return 'No tenés permiso para ese cambio.';
  const detail = error?.response?.data?.detail;
  return typeof detail === 'string' ? `${accion}: ${detail}` : `${accion}. Probá de nuevo.`;
}

/**
 * The cost mode of a product's sell in, inside its lot viewer: the mode governing today (FIFO when none), the change
 * to FIFO / Ponderado (PPP) / Último precio from a date with its mandatory preview (`.../modos/vista-previa`, then
 * confirmed with the preview's fingerprint), and the history. Each mode needs its own permission, FIFO any of them, a
 * past date also `sell_in.costo_retroactivo` (the server checks them again). Manual is shown but not available yet:
 * the server does not save it. Without `sell_in.ver` (403) it renders nothing.
 *
 * @param {object} props
 * @param {number} props.productItemId The ERP product.
 * @param {object[]} props.lotes The viewer's lots, for the "before" unit values of the preview.
 * @param {object|null} props.proxima The viewer's next sale.
 * @param {Function} props.onChanged Called after a change is saved, so the viewer reloads its lots.
 */
export default function SellInModoCosto({ productItemId, lotes, proxima, onChanged }) {
  const { tienePermiso, rol } = usePermisos();
  const headingId = useId();
  const desdeId = useId();
  const helpId = useId();
  const histId = useId();
  const [read, setRead] = useState({ status: 'loading', data: null });
  const [attempt, setAttempt] = useState(0);
  const [modo, setModo] = useState(null); // null: not picked, the selector shows the preselected mode
  const [porDefecto, setPorDefecto] = useState('fifo');
  const [editandoDefecto, setEditandoDefecto] = useState(false);
  const [desde, setDesde] = useState(today);
  const [vista, setVista] = useState(null);
  const [busy, setBusy] = useState(null); // 'preview' | 'confirm'
  const [error, setError] = useState(null);

  useEffect(() => {
    let current = true;
    sellInLotesAPI
      .modos(productItemId)
      .then(({ data }) => current && setRead({ status: 'ready', data }))
      .catch((err) => current && setRead({ status: err?.response?.status === 403 ? 'forbidden' : 'error', data: null }));
    return () => {
      current = false;
    };
  }, [productItemId, attempt]);

  useEffect(() => {
    let current = true;
    // Unreadable: the selector just opens on FIFO.
    sellInLotesAPI
      .modoPorDefecto()
      .then(({ data }) => current && setPorDefecto(data.modo))
      .catch(() => {});
    return () => {
      current = false;
    };
  }, []);

  if (read.status === 'forbidden') return null;

  const puede = {
    ponderado: tienePermiso(PERMISO.ponderado),
    ultimo: tienePermiso(PERMISO.ultimo),
    manual: tienePermiso(PERMISO.manual),
  };
  const puedeCambiar = puede.ponderado || puede.ultimo || puede.manual;
  const retroactivo = tienePermiso(RETROACTIVO);
  // Manual cannot be saved yet; any other mode needs its permission, FIFO any of them.
  const permitido = (value) => value !== 'manual' && (value === 'fifo' ? puedeCambiar : puede[value]);
  // The admin's default opens preselected only when this user may set it; otherwise FIFO.
  const seleccion = modo ?? (permitido(porDefecto) ? porDefecto : 'fifo');
  const esAdmin = ADMINS.includes(rol);
  const hoy = today();

  const drop = () => {
    setVista(null);
    setError(null);
  };

  const preview = async () => {
    setBusy('preview');
    setError(null);
    try {
      const { data } = await sellInLotesAPI.vistaPrevia(productItemId, { modo: seleccion, desde });
      setVista(data);
    } catch (err) {
      setVista(null);
      setError(errorText(err, 'No se pudo calcular la vista previa'));
    } finally {
      setBusy(null);
    }
  };

  const confirm = async () => {
    setBusy('confirm');
    setError(null);
    try {
      await sellInLotesAPI.confirmarModo(productItemId, { modo: seleccion, desde, huella: vista.huella });
      setVista(null);
      setModo(null);
      setAttempt((n) => n + 1);
      onChanged?.();
    } catch (err) {
      setVista(null);
      setError(errorText(err, 'No se pudo guardar el cambio'));
    } finally {
      setBusy(null);
    }
  };

  let body;
  let previewCard = null;
  let historyCard = null;
  if (read.status === 'loading') {
    body = (
      <p className={styles.note} role="status">
        Cargando modo de costo…
      </p>
    );
  } else if (read.status === 'error') {
    body = (
      <div className={styles.error} role="alert">
        <span>No se pudo cargar el modo de costo.</span>
        <button
          type="button"
          className="btn-tesla outline sm"
          onClick={() => {
            setRead({ status: 'loading', data: null });
            setAttempt((n) => n + 1);
          }}
        >
          Reintentar
        </button>
      </div>
    );
  } else {
    const { vigente = null, historial = [] } = read.data ?? {};
    const actual = vigente ? `${MODOS[vigente.modo]?.label ?? vigente.modo} desde ${day(vigente.desde)}` : 'FIFO (por defecto)';
    const conUnidades = lotes.filter((lote) => lote.restantes > 0);
    const antes = {
      proxima: proxima?.descuento_unit ?? null,
      nueva: conUnidades.length > 1 ? conUnidades[conUnidades.length - 1].descuento_unit : null,
    };
    const options = ORDEN.map((value) => {
      if (value === 'manual') {
        return { value, label: MODOS[value].label, disabled: true, title: 'La carga manual todavía no está disponible' };
      }
      const ok = permitido(value);
      return {
        value,
        label: MODOS[value].label,
        // Locked while a request runs, so a preview never lands under another mode's name.
        disabled: !ok || busy != null,
        title: ok ? undefined : `Necesitás el permiso ${PERMISO[value]}`,
      };
    });

    body = (
      <div className={styles.wrap}>
        <div className={styles.modebar}>
          <span className={styles.modebarLabel}>Modo actual</span>{' '}
          <StatusPill tone={vigente ? 'info' : 'neutral'} variant="soft">
            {actual}
          </StatusPill>
        </div>

        {puedeCambiar && (
          <>
            <div className={styles.field}>
              <span className={styles.label}>Cambiar a</span>
              <SegmentedControl
                label="Cambiar a"
                options={options}
                value={seleccion}
                onChange={(value) => {
                  setModo(value);
                  drop();
                }}
              />
            </div>
            <div className={styles.field}>
              <label htmlFor={desdeId} className={styles.label}>
                Desde
              </label>
              <input
                id={desdeId}
                className={styles.input}
                type="date"
                value={desde}
                min={retroactivo ? undefined : hoy}
                disabled={busy != null}
                aria-describedby={helpId}
                onChange={(event) => {
                  setDesde(event.target.value);
                  drop();
                }}
              />
              <span id={helpId} className={styles.help}>
                {retroactivo
                  ? 'Una fecha pasada recalcula las ventas ya registradas desde ese día.'
                  : 'Para una fecha pasada necesitás el permiso de costo retroactivo.'}
              </span>
            </div>
            <p className={styles.note}>{MODOS[seleccion].nota}</p>
            {!vista && (
              <div className={`${styles.actions} ${styles.divided}`}>
                <button
                  type="button"
                  className="btn-tesla outline sm"
                  disabled={!desde || busy === 'preview'}
                  onClick={preview}
                >
                  {busy === 'preview' ? 'Calculando…' : 'Ver cómo queda'}
                </button>
              </div>
            )}
            {error && (
              <p className={styles.error} role="alert">
                {error}
              </p>
            )}
          </>
        )}
      </div>
    );
    if (puedeCambiar && vista) {
      previewCard = (
        <Preview vista={vista} modo={seleccion} antes={antes} onConfirm={confirm} onCancel={drop} saving={busy === 'confirm'} />
      );
    }
    if (historial.length > 0) {
      historyCard = (
        <section className={styles.card} aria-labelledby={histId}>
          <header className={styles.head}>
            <h4 id={histId} className={styles.title}>
              Historial
            </h4>
          </header>
          <div className={styles.body}>
            <ul className={styles.hist} aria-label="Historial de modos">
              {historial.map((fila) => (
                <li key={fila.id}>
                  <span className={styles.histDate}>{day(fila.created_at)}</span>
                  <StatusPill tone="neutral" variant="soft">
                    {MODOS[fila.modo]?.label ?? fila.modo}
                  </StatusPill>
                  <span className={styles.histMeta}>
                    {`desde ${day(fila.desde)}${fila.usuario_nombre ? ` · por ${fila.usuario_nombre}` : ''}`}
                  </span>
                </li>
              ))}
            </ul>
          </div>
        </section>
      );
    }
  }

  return (
    <>
      <section className={styles.card} aria-labelledby={headingId}>
        <header className={`${styles.head} ${styles.headRow}`}>
          <div className={styles.headText}>
            <h4 id={headingId} className={styles.title}>
              Modo de costo
            </h4>
            <p className={styles.hint}>Define con qué descuento de sell in salen las unidades cuando vendés.</p>
          </div>
          {esAdmin && (
            <button type="button" className="btn-tesla outline sm" onClick={() => setEditandoDefecto(true)}>
              Modo por defecto
            </button>
          )}
        </header>
        <div className={styles.body}>{body}</div>
      </section>
      {previewCard}
      {historyCard}
      {editandoDefecto && (
        <SellInModoPorDefecto
          actual={porDefecto}
          options={ORDEN.filter((value) => value !== 'manual').map((value) => ({ value, label: MODOS[value].label }))}
          onClose={() => setEditandoDefecto(false)}
          onSaved={(value) => {
            setPorDefecto(value);
            setEditandoDefecto(false);
          }}
        />
      )}
    </>
  );
}
