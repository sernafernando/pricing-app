import { formatEntero, formatMonto } from './sellInFormat';
import styles from './SellInResumen.module.css';

/**
 * The summary cards, straight from `GET /sell-in/compras/resumen` (every
 * purchase matching the filters, not just this page). Amounts stay per
 * currency: USD is never converted into the ARS figure. `bonos` (optional,
 * `{ vigentes, marcas, compras }`, or `{ error: true }`) adds the active brand bonuses' cards.
 */
export default function SellInResumen({ resumen, bonos }) {
  if (!resumen) return null;
  const { conteo, monto_total: monto, unidades_total: unidades } = resumen;
  const cards = [
    { label: 'Sell in USD', value: formatMonto(monto.USD, 'USD'), sub: 'Monto total en dólares' },
    { label: 'Sell in ARS', value: formatMonto(monto.ARS, 'ARS'), sub: 'Monto total en pesos' },
    { label: 'Unidades cubiertas', value: formatEntero(unidades), sub: 'Unidades de las compras' },
    { label: 'Sell in que aplican', value: formatEntero(conteo.si), sub: `de ${formatEntero(conteo.todas)} cargados` },
  ];
  if (bonos?.error) {
    cards.push(
      { label: 'Bonos de marca vigentes', value: '—', sub: 'No se pudieron cargar' },
      { label: 'Compras alcanzadas', value: '—', sub: 'No se pudieron cargar' },
    );
  } else if (bonos) {
    cards.push(
      {
        label: 'Bonos de marca vigentes',
        value: formatEntero(bonos.vigentes),
        sub: `${formatEntero(bonos.marcas)} ${bonos.marcas === 1 ? 'marca' : 'marcas'}`,
      },
      { label: 'Compras alcanzadas', value: formatEntero(bonos.compras), sub: 'por bonos de marca' },
    );
  }
  return (
    <section className={styles.cards} aria-label="Resumen">
      {cards.map(({ label, value, sub }) => (
        <div key={label} className={styles.card}>
          <span className={styles.label}>{label}</span>
          <span className={styles.value}>{value}</span>
          <span className={styles.sub}>{sub}</span>
        </div>
      ))}
    </section>
  );
}
