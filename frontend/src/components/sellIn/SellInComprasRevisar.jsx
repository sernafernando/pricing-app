import { useEffect, useState } from 'react';
import { AlertTriangle } from 'lucide-react';
import ModalTesla from '../ModalTesla';
import { costoSiSospechasAPI } from '../../services/sellInAPI';
import { formatEntero } from './sellInFormat';
import styles from './SellInComprasRevisar.module.css';

/** The state filter: pending first (what needs a decision), then the decided ones and every row. */
const ESTADOS = [
  { value: 'pendiente', label: 'Pendientes' },
  { value: 'excluida', label: 'Excluidas' },
  { value: 'aceptada', label: 'Aceptadas' },
  { value: '', label: 'Todas' },
];
const ESTADO_LABEL = { pendiente: 'Pendiente', aceptada: 'Aceptada', excluida: 'Excluida' };
const FUENTE_LABEL = { costo_si: 'costo SI', lista: 'costo de lista' };
const ACCIONES = {
  aceptar: {
    titulo: 'Aceptar la compra',
    texto:
      'La compra entra al costo promedio y se recalcula la historia del producto desde la fecha de la factura, con sus ventas y markups.',
    boton: 'Aceptar',
    clase: 'primary',
  },
  excluir: {
    titulo: 'Mantener excluida',
    texto: 'La compra sigue fuera del costo promedio. Si la factura se corrige en el ERP, vuelve a revisarse sola.',
    boton: 'Mantener excluida',
    clase: 'outline',
  },
};

// A suspicious price can be a fraction of a cent: up to 5 decimals (the stored precision), at least 2.
const PRECIO = new Intl.NumberFormat('es-AR', { minimumFractionDigits: 2, maximumFractionDigits: 5 });
const RATIO = new Intl.NumberFormat('es-AR', { maximumSignificantDigits: 2 });

const precio = (valor, moneda) => `${moneda === 'USD' ? 'USD' : '$'} ${PRECIO.format(Number(valor))}`;
const fecha = (iso) => {
  const [y, m, d] = String(iso).slice(0, 10).split('-');
  return `${d}/${m}/${y}`;
};
/** "0,00072×" reads badly: below 1 it is "1/1.394 de la referencia", above it "12× la referencia". */
export function ratioLabel(ratio) {
  const r = Number(ratio);
  if (!(r > 0)) return '—';
  return r < 1 ? `1/${formatEntero(Math.round(1 / r))} de la referencia` : `${RATIO.format(r)}× la referencia`;
}

/**
 * "Compras a revisar" (owner L29): the purchases held out of costo SI because their unit price is below 1/10 or above
 * 10x the costo SI right before the invoice (or the list cost when there is none). Each row shows the product, the
 * invoice, the price against its reference and the decision. With `puedeRevisar` (`costo_si.revisar`) a reviewer
 * accepts it (it enters the average and the product is recomputed) or keeps it excluded, after a confirmation with an
 * optional note; without it the list is read only. A decision calls `onDecidido` (the tab's badge reads again).
 *
 * @param {object} props
 * @param {boolean} props.puedeRevisar
 * @param {() => void} [props.onDecidido]
 * @param {number} [props.version] A new value reads the list again.
 */
export default function SellInComprasRevisar({ puedeRevisar, onDecidido, version = 0 }) {
  const [estado, setEstado] = useState('pendiente');
  const [read, setRead] = useState({ status: 'loading', filas: [] });
  const [attempt, setAttempt] = useState(0);
  const [accion, setAccion] = useState(null); // { tipo: 'aceptar' | 'excluir', fila }

  useEffect(() => {
    let current = true;
    setRead((prev) => ({ ...prev, status: 'loading' }));
    costoSiSospechasAPI
      .listar(estado ? { estado } : {})
      .then(({ data }) => current && setRead({ status: 'ready', filas: data ?? [] }))
      .catch(() => current && setRead({ status: 'error', filas: [] }));
    return () => {
      current = false;
    };
  }, [estado, version, attempt]);

  const decidido = () => {
    setAccion(null);
    setAttempt((a) => a + 1);
    onDecidido?.();
  };

  return (
    <>
      <section className={styles.filtros} aria-label="Filtros de compras a revisar">
        <label className={styles.campo}>
          <span className={styles.label}>Estado</span>
          <select className={styles.control} value={estado} onChange={(e) => setEstado(e.target.value)}>
            {ESTADOS.map((e) => (
              <option key={e.value || 'todas'} value={e.value}>
                {e.label}
              </option>
            ))}
          </select>
        </label>
        <p className={styles.ayuda}>
          Compras con un precio unitario menor a 1/10 o mayor a 10 veces el costo SI vigente antes de la factura (o el
          costo de lista si no hay). No entran al costo promedio hasta que alguien las acepte.
        </p>
      </section>

      <section className={styles.card}>
        {read.status === 'error' ? (
          <div className={styles.error} role="alert">
            <span>No se pudieron cargar las compras a revisar.</span>
            <button type="button" className="btn-tesla outline sm" onClick={() => setAttempt((a) => a + 1)}>
              Reintentar
            </button>
          </div>
        ) : read.status === 'loading' && read.filas.length === 0 ? (
          <p className={styles.nota} role="status">
            Cargando compras…
          </p>
        ) : read.filas.length === 0 ? (
          <p className={styles.nota}>No hay compras {estado ? ESTADOS.find((e) => e.value === estado).label.toLowerCase() : ''}.</p>
        ) : (
          <div className={styles.scroller}>
            <table className={styles.table} aria-label="Compras con precio sospechoso">
              <thead>
                <tr>
                  <th scope="col">Producto</th>
                  <th scope="col">Factura</th>
                  <th scope="col" className={styles.num}>
                    Cantidad
                  </th>
                  <th scope="col" className={styles.num}>
                    Precio unitario
                  </th>
                  <th scope="col" className={styles.num}>
                    Referencia
                  </th>
                  <th scope="col">Desvío</th>
                  <th scope="col">Estado</th>
                  <th scope="col" className={styles.acciones}>
                    <span className={styles.srOnly}>Acciones</span>
                  </th>
                </tr>
              </thead>
              <tbody>
                {read.filas.map((fila) => (
                  <tr key={fila.id}>
                    <td>
                      <span className={styles.apilado}>
                        <span className={styles.nombre}>{fila.descripcion ?? `Producto ${fila.item_id}`}</span>
                        <span className={styles.codigo}>{fila.codigo ?? fila.item_id}</span>
                      </span>
                    </td>
                    <td>
                      <span className={styles.apilado}>
                        <span className={styles.mono}>{fila.factura ?? fila.ct_transaction}</span>
                        <span className={styles.secundario}>{fecha(fila.fecha)}</span>
                      </span>
                    </td>
                    <td className={styles.num}>{formatEntero(fila.cantidad)} u</td>
                    <td className={`${styles.num} ${styles.precio}`}>{precio(fila.precio, fila.moneda)}</td>
                    <td className={styles.num}>
                      <span className={styles.apilado}>
                        <span>{precio(fila.referencia, fila.moneda)}</span>
                        <span className={styles.secundario}>{FUENTE_LABEL[fila.fuente_ref] ?? fila.fuente_ref}</span>
                      </span>
                    </td>
                    <td>
                      <span className={styles.desvio}>
                        <AlertTriangle size={12} aria-hidden="true" /> {ratioLabel(fila.ratio)}
                      </span>
                    </td>
                    <td>
                      <span className={styles.apilado}>
                        <span className={`${styles.estado} ${styles[fila.estado] ?? ''}`}>
                          {ESTADO_LABEL[fila.estado] ?? fila.estado}
                        </span>
                        {fila.revisor && (
                          <span className={styles.secundario}>
                            {fila.revisor} · {fecha(fila.revisado_at)}
                          </span>
                        )}
                      </span>
                    </td>
                    <td className={styles.acciones}>
                      {puedeRevisar && (
                        <span className={styles.botones}>
                          {fila.estado !== 'aceptada' && (
                            <button
                              type="button"
                              className="btn-tesla outline sm"
                              aria-label={`Aceptar la compra de ${fila.descripcion ?? fila.item_id}, factura ${fila.factura ?? fila.ct_transaction}`}
                              onClick={() => setAccion({ tipo: 'aceptar', fila })}
                            >
                              Aceptar
                            </button>
                          )}
                          {fila.estado !== 'excluida' && (
                            <button
                              type="button"
                              className="btn-tesla outline sm"
                              aria-label={`Mantener excluida la compra de ${fila.descripcion ?? fila.item_id}, factura ${fila.factura ?? fila.ct_transaction}`}
                              onClick={() => setAccion({ tipo: 'excluir', fila })}
                            >
                              Mantener excluida
                            </button>
                          )}
                        </span>
                      )}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </section>

      {accion && (
        <Confirmar
          accion={accion}
          onClose={(vencida) => {
            setAccion(null);
            if (vencida) setAttempt((a) => a + 1); // a corrected invoice: show its new price before a new decision
          }}
          onDone={decidido}
        />
      )}
    </>
  );
}

function Confirmar({ accion, onClose, onDone }) {
  const { tipo, fila } = accion;
  const textos = ACCIONES[tipo];
  const [nota, setNota] = useState(fila.nota ?? '');
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState(null);
  const [vencida, setVencida] = useState(false); // a 409: the row changed, the list must be read again
  const cerrar = () => onClose(vencida);

  const confirmar = async () => {
    setSaving(true);
    setError(null);
    try {
      await costoSiSospechasAPI[tipo](fila.id, fila.precio, nota);
      onDone();
    } catch (err) {
      const status = err?.response?.status;
      if (status === 409) setVencida(true);
      setError(
        status === 409
          ? 'La factura se corrigió desde que se cargó la lista. Al cerrar se recarga con el precio nuevo.'
          : status === 403
            ? 'No tenés permiso para revisar compras.'
            : 'No se pudo guardar la decisión. Probá de nuevo.',
      );
      setSaving(false);
    }
  };

  return (
    <ModalTesla
      isOpen
      onClose={cerrar}
      title={textos.titulo}
      subtitle={`${fila.descripcion ?? `Producto ${fila.item_id}`} · factura ${fila.factura ?? fila.ct_transaction}`}
      size="sm"
      footer={
        <div className={styles.modalAcciones}>
          <button type="button" className="btn-tesla outline sm" onClick={cerrar} disabled={saving}>
            Cancelar
          </button>
          <button type="button" className={`btn-tesla ${textos.clase} sm`} onClick={confirmar} disabled={saving}>
            {saving ? 'Guardando…' : textos.boton}
          </button>
        </div>
      }
    >
      <div className={styles.modal}>
        <p className={styles.resumen}>
          {formatEntero(fila.cantidad)} u a <strong>{precio(fila.precio, fila.moneda)}</strong> contra{' '}
          {precio(fila.referencia, fila.moneda)} de {FUENTE_LABEL[fila.fuente_ref] ?? fila.fuente_ref} (
          {ratioLabel(fila.ratio)}).
        </p>
        <p className={styles.secundario}>{textos.texto}</p>
        <label className={styles.campo}>
          <span className={styles.label}>Nota (opcional)</span>
          <textarea
            className={styles.textarea}
            rows={2}
            maxLength={500}
            value={nota}
            onChange={(e) => setNota(e.target.value)}
          />
        </label>
        {error && (
          <p className={styles.errorTexto} role="alert">
            {error}
          </p>
        )}
      </div>
    </ModalTesla>
  );
}
