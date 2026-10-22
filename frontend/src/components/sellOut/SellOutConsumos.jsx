import { useEffect, useState } from 'react';
import { sellOutAPI } from '../../services/sellOutAPI';
import { formatDateOnly } from '../../utils/dateUtils';
import { Pagination } from '../kit';
import { apiMessage, formatEntero, formatMonto, formatNumero } from '../sellIn/sellInFormat';
import { CANAL_LABELS } from './sellOutFormat';
import panelStyles from '../sellIn/SellInPanel.module.css';
import tableStyles from '../sellIn/SellInTable.module.css';

const DIA = { day: '2-digit', month: '2-digit', year: 'numeric' };
const PAGE_SIZE = 25;

/**
 * What a sell-out campaign credited, sale line by sale line (`GET /sell-out/campanas/{id}/consumos`, T8d),
 * newest first as the API returns them. A return inside the campaign is netted into its sale's line, so units
 * and amounts can be negative. USD campaigns also show each line's rate and its ARS amount.
 */
export default function SellOutConsumos({ campanaId }) {
  const [offset, setOffset] = useState(0);
  const [pagina, setPagina] = useState(null);
  const [error, setError] = useState(null);

  useEffect(() => {
    let active = true;
    setError(null);
    sellOutAPI
      .consumos(campanaId, { page: Math.floor(offset / PAGE_SIZE) + 1, page_size: PAGE_SIZE })
      .then(({ data }) => active && setPagina(data))
      .catch((err) => {
        if (!active) return;
        setPagina(null); // never leave the previous page on screen as if it were the one asked for
        setError(apiMessage(err, 'No se pudieron cargar las ventas acreditadas.'));
      });
    return () => {
      active = false;
    };
  }, [campanaId, offset]);

  const usd = pagina?.moneda === 'USD';
  return (
    <section className={panelStyles.section} aria-label="Ventas acreditadas">
      <h3>Ventas acreditadas</h3>
      {error && (
        <p className={panelStyles.error} role="alert">
          {error}
        </p>
      )}
      {!pagina && !error && <p className={panelStyles.hint}>Cargando…</p>}
      {pagina && pagina.total === 0 && <p className={panelStyles.hint}>Todavía no hay ventas acreditadas.</p>}
      {pagina && pagina.total > 0 && (
        <>
          {usd && pagina.ars_estimado && (
            <p className={panelStyles.hint}>Los montos en pesos están estimados con el dólar BNA hasta que se defina el tipo de cambio de cobro.</p>
          )}
          <div className={tableStyles.scroller}>
            <table className={tableStyles.table}>
              <thead>
                <tr>
                  <th>Fecha</th>
                  <th>Canal</th>
                  <th>Producto</th>
                  <th className={tableStyles.num}>Unidades</th>
                  <th className={tableStyles.num}>Monto</th>
                  {usd && <th className={tableStyles.num}>Tipo de cambio</th>}
                  {usd && <th className={tableStyles.num}>Monto en pesos</th>}
                </tr>
              </thead>
              <tbody>
                {pagina.items.map((linea) => (
                  <tr key={linea.id}>
                    <td>{formatDateOnly(linea.fecha_venta, DIA)}</td>
                    <td>{CANAL_LABELS[linea.canal] ?? linea.canal}</td>
                    <td>
                      <div>{linea.descripcion || `Producto ${linea.item_id}`}</div>
                      {linea.codigo && <div className={tableStyles.sub}>{linea.codigo}</div>}
                    </td>
                    <td className={tableStyles.num}>{formatEntero(linea.unidades)}</td>
                    <td className={tableStyles.num}>{formatMonto(linea.monto, pagina.moneda)}</td>
                    {usd && <td className={tableStyles.num}>{formatNumero(linea.tc_venta)}</td>}
                    {usd && <td className={tableStyles.num}>{formatMonto(linea.monto_ars, 'ARS')}</td>}
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          <Pagination
            total={pagina.total}
            offset={offset}
            pageSize={PAGE_SIZE}
            onOffsetChange={setOffset}
            pageSizeOptions={[PAGE_SIZE]}
            summary={<span>{`${formatEntero(pagina.total)} ventas`}</span>}
          />
        </>
      )}
    </section>
  );
}
