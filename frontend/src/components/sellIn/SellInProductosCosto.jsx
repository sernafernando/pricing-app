import { useEffect, useState } from 'react';
import { sellInLotesAPI } from '../../services/sellInAPI';
import { formatEntero, formatMonto } from './sellInFormat';
import styles from './SellInProductosCosto.module.css';

/** The labels the cost-mode panel (`SellInModoCosto`) uses; no mode row is FIFO, the default. */
const MODOS = { fifo: 'FIFO', ponderado: 'Ponderado (PPP)', ultimo: 'Último precio', manual: 'Manual' };

const modoLabel = (modo) => (modo ? (MODOS[modo] ?? modo) : 'FIFO (por defecto)');

const fecha = (iso) => {
  const [y, m, d] = String(iso).split('-');
  return `${d}/${m}/${y}`;
};

/**
 * Sell in's Productos list (`GET /sell-in/productos/costos`, one request for the whole list): every product with
 * units left in its lots, with its "Modo de costo", units, what the next sale takes per unit and its latest purchase,
 * and the total units under it. A row's product opens its lots and cost mode (`onVer(fila)`). A new `version` reads
 * the list again.
 *
 * @param {object} props
 * @param {(fila: object) => void} props.onVer
 * @param {number} [props.version]
 */
export default function SellInProductosCosto({ onVer, version = 0 }) {
  const [read, setRead] = useState({ status: 'loading', productos: [] });
  const [attempt, setAttempt] = useState(0);

  useEffect(() => {
    let current = true;
    sellInLotesAPI
      .productos()
      .then(({ data }) => current && setRead({ status: 'ready', productos: data.productos ?? [] }))
      .catch(() => current && setRead({ status: 'error', productos: [] }));
    return () => {
      current = false;
    };
  }, [version, attempt]);

  if (read.status === 'loading' && read.productos.length === 0) {
    return (
      <p className={styles.nota} role="status">
        Cargando productos…
      </p>
    );
  }
  if (read.status === 'error') {
    return (
      <div className={styles.error} role="alert">
        <span>No se pudieron cargar los productos.</span>
        <button
          type="button"
          className="btn-tesla outline sm"
          onClick={() => {
            setRead({ status: 'loading', productos: [] });
            setAttempt((n) => n + 1);
          }}
        >
          Reintentar
        </button>
      </div>
    );
  }
  if (read.productos.length === 0) {
    return <p className={styles.nota}>Ningún producto tiene unidades en lotes de sell in.</p>;
  }

  const total = read.productos.reduce((sum, x) => sum + x.unidades, 0);
  return (
    <section className={styles.card}>
      <div className={styles.scroller}>
        <table className={styles.table} aria-label="Productos con lotes de sell in">
          <thead>
            <tr>
              <th scope="col">Producto</th>
              <th scope="col">Modo de costo</th>
              <th scope="col" className={styles.num}>
                Unidades
              </th>
              <th scope="col" className={styles.num}>
                Sell in por unidad
              </th>
              <th scope="col" className={styles.num}>
                Últ. compra
              </th>
            </tr>
          </thead>
          <tbody>
            {read.productos.map((fila) => (
              <tr key={fila.item_id}>
                <td>
                  <button
                    type="button"
                    className={styles.producto}
                    aria-label={`Ver lotes y modo de costo de ${fila.descripcion ?? fila.codigo}`}
                    onClick={() => onVer(fila)}
                  >
                    <span className={styles.nombre}>{fila.descripcion}</span>
                    <span className={styles.codigo}>{fila.codigo}</span>
                  </button>
                </td>
                <td>
                  <span className={styles.pill}>{modoLabel(fila.modo)}</span>
                </td>
                <td className={styles.num}>{formatEntero(fila.unidades)} u</td>
                <td className={styles.num}>{formatMonto(fila.sell_in_unit, 'ARS')}</td>
                <td className={styles.num}>{fecha(fila.ultima_compra)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <div className={`${styles.total} ${styles.num}`}>{formatEntero(total)} u</div>
    </section>
  );
}
