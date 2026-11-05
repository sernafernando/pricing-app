import { useEffect, useId, useState } from 'react';
import { sellInLotesAPI } from '../../services/sellInAPI';
import { usePermisos } from '../../contexts/PermisosContext';
import SegmentedControl from '../kit/SegmentedControl';
import StatusPill from '../kit/StatusPill';
import SellInModoPorDefecto from './SellInModoPorDefecto';
import { money } from './money';
import styles from './SellInModoCosto.module.css';


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

/** A manual block's unit value: the frozen cost minus the typed one, a discount or (negative) a surcharge. */
function efectoManual(valor) {
  const n = Number(valor);
  if (n > 0) return `Cada unidad descuenta ${money(n)} del costo (sell in)`;
  if (n < 0) return `Cada unidad suma ${money(-n)} al costo (recargo de sell in)`;
  return 'Sin sell in: el costo de cada unidad queda igual';
}

function Preview({ vista, pedido, antes, onConfirm, onCancel, saving }) {
  const id = useId();
  const { modo } = pedido;
  // The block's own value per unit; the next sale takes it only while the block has units (a past date's recorded
  // sales may have used it up, and a later purchase is next).
  const valorBloque = modo === 'manual' ? Number(vista.costo_base_unit) - Number(pedido.costo_unit) : null;
  const delBloque = modo === 'manual' && vista.del_bloque;
  let quedan = `Quedan ${vista.unidades_restantes} u a ${money(vista.descuento_unit)} de sell in c/u`;
  if (vista.descuento_unit == null) quedan = `Quedan ${vista.unidades_restantes} u sin sell in`;
  else if (delBloque) quedan = `Quedan ${vista.unidades_restantes} u a ${money(pedido.costo_unit)} c/u (manual)`;
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
        {modo === 'manual' && (
          <>
            <li>
              <span>Costo del producto congelado:</span> <b>{money(vista.costo_base_unit)}</b>
            </li>
            <li>
              <span>{efectoManual(valorBloque)}</span>
            </li>
          </>
        )}
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

// What the server stores for a unit cost: 18 digits, 6 of them decimals.
const COSTO_UNIT = /^\d{1,12}(\.\d{1,6})?$/;
// And for a quantity: the column's integer.
const CANTIDAD_MAX = 2 ** 31 - 1;

// The server's reasons a user can act on, in the screen's words; any other reason is shown as it comes.
const MOTIVOS = {
  'The product has no cost to freeze': 'el producto no tiene costo cargado para congelar.',
  "There is no USD rate to freeze the product's cost in pesos":
    'no hay tipo de cambio USD para pasar el costo del producto a pesos.',
};

function errorText(error, accion) {
  const status = error?.response?.status;
  if (status === 409) {
    return 'El producto cambió desde la vista previa (o alguien lo está modificando). Tocá «Ver cómo queda» de nuevo.';
  }
  if (status === 403) return 'No tenés permiso para ese cambio.';
  const data = error?.response?.data;
  const mensaje = data?.error?.message ?? data?.detail;
  const motivo = MOTIVOS[mensaje] ?? (typeof mensaje === 'string' ? mensaje : null);
  return motivo ? `${accion}: ${motivo}` : `${accion}. Probá de nuevo.`;
}

/**
 * The cost mode of a product's sell in, inside its lot viewer: the mode governing today (FIFO when none), the change
 * to FIFO / Ponderado (PPP) / Último precio / Manual from a date with its mandatory preview (`.../modos/vista-previa`,
 * then confirmed with the preview's fingerprint and the same figures), and the history. Manual takes the quantity and
 * unit cost left; the server freezes the product's cost against it. Each mode needs its own permission, FIFO any of
 * them, a past date also `sell_in.costo_retroactivo` (the server checks them again). Without `sell_in.ver` (403) it
 * renders nothing.
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
  const cantidadId = useId();
  const costoId = useId();
  const helpId = useId();
  const histId = useId();
  const [read, setRead] = useState({ status: 'loading', data: null });
  const [attempt, setAttempt] = useState(0);
  const [modo, setModo] = useState(null); // null: not picked, the selector shows the preselected mode
  const [porDefecto, setPorDefecto] = useState('fifo');
  const [editandoDefecto, setEditandoDefecto] = useState(false);
  const [desde, setDesde] = useState(today);
  const [cantidad, setCantidad] = useState('');
  const [costoUnit, setCostoUnit] = useState('');
  const [vista, setVista] = useState(null);
  const [pedido, setPedido] = useState(null); // what the preview was asked for: the confirm sends the same
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
  // Each mode needs its permission, FIFO any of them.
  const permitido = (value) => (value === 'fifo' ? puedeCambiar : puede[value]);
  // The admin's default opens preselected only when this user may set it (never Manual: it needs its own figures).
  const seleccion = modo ?? (porDefecto !== 'manual' && permitido(porDefecto) ? porDefecto : 'fifo');
  const esManual = seleccion === 'manual';
  const manualOk =
    Number.isInteger(Number(cantidad)) &&
    Number(cantidad) > 0 &&
    Number(cantidad) <= CANTIDAD_MAX &&
    COSTO_UNIT.test(costoUnit) &&
    Number(costoUnit) > 0;
  const esAdmin = ADMINS.includes(rol);
  const hoy = today();

  const drop = () => {
    setVista(null);
    setError(null);
  };

  const preview = async () => {
    // Freeze the previewed mode: a default read or saved later must not relabel the preview or what is confirmed.
    // A failed preview unfreezes it, so an untouched selector follows the default again.
    const elegidoAntes = modo;
    setModo(seleccion);
    setBusy('preview');
    setError(null);
    try {
      const cuerpo = esManual
        ? { modo: seleccion, desde, cantidad: Number(cantidad), costo_unit: costoUnit }
        : { modo: seleccion, desde };
      const { data } = await sellInLotesAPI.vistaPrevia(productItemId, cuerpo);
      setPedido(cuerpo);
      setVista(data);
    } catch (err) {
      setVista(null);
      setModo(elegidoAntes);
      setError(errorText(err, 'No se pudo calcular la vista previa'));
    } finally {
      setBusy(null);
    }
  };

  const confirm = async () => {
    setBusy('confirm');
    setError(null);
    try {
      await sellInLotesAPI.confirmarModo(productItemId, { ...pedido, huella: vista.huella });
      setVista(null);
      setModo(null);
      setCantidad('');
      setCostoUnit('');
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
            {esManual && (
              <div className={styles.manual}>
                <div className={styles.field}>
                  <label htmlFor={cantidadId} className={styles.label}>
                    Cantidad
                  </label>
                  <input
                    id={cantidadId}
                    className={styles.inputNum}
                    type="number"
                    min="1"
                    max={CANTIDAD_MAX}
                    step="1"
                    inputMode="numeric"
                    value={cantidad}
                    disabled={busy != null}
                    onChange={(event) => {
                      setCantidad(event.target.value);
                      drop();
                    }}
                  />
                </div>
                <div className={styles.field}>
                  <label htmlFor={costoId} className={styles.label}>
                    Costo unitario
                  </label>
                  <input
                    id={costoId}
                    className={styles.inputNum}
                    type="number"
                    min="0"
                    step="any"
                    inputMode="decimal"
                    value={costoUnit}
                    disabled={busy != null}
                    onChange={(event) => {
                      setCostoUnit(event.target.value);
                      drop();
                    }}
                  />
                </div>
              </div>
            )}
            <p className={styles.note}>{MODOS[seleccion].nota}</p>
            {!vista && (
              <div className={`${styles.actions} ${styles.divided}`}>
                <button
                  type="button"
                  className="btn-tesla outline sm"
                  disabled={!desde || busy === 'preview' || (esManual && !manualOk)}
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
        <Preview vista={vista} pedido={pedido} antes={antes} onConfirm={confirm} onCancel={drop} saving={busy === 'confirm'} />
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
                    {[
                      `desde ${day(fila.desde)}`,
                      fila.modo === 'manual' &&
                        `${fila.cantidad} u a ${money(fila.costo_unit)} (costo congelado ${money(fila.costo_base_unit)})`,
                      fila.usuario_nombre && `por ${fila.usuario_nombre}`,
                    ]
                      .filter(Boolean)
                      .join(' · ')}
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
