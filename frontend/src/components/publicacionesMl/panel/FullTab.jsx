import { amount, count, date, orNull } from './format';
import { replenishmentDisabled } from './detailModel';
import { Field, Fields, Section } from './PanelParts';
import cellStyles from '../cells.module.css';
import styles from './panel.module.css';

const STATUS_MESSAGES = {
  not_found: 'Mercado Libre no tiene datos de reposición para esta publicación.',
  error: 'No se pudo consultar la reposición.',
  never_fetched: 'Todavía no se consultó la reposición.',
};
const DISABLED_MESSAGE =
  'La reposición de Full no se sincroniza: está desactivada en la sincronización de publicaciones.';

function StockSection({ row, detail }) {
  const stock = row.stock ?? {};
  return (
    <Section title="Stock">
      <Fields>
        <Field label="Full">{count(stock.full)}</Field>
        <Field label="Propio">{count(stock.own)}</Field>
        <Field label="Actualizado">{date(detail.stockAsOf ?? stock.as_of)}</Field>
      </Fields>
    </Section>
  );
}

function ReplenishmentSection({ detail, disabled }) {
  const report = detail.replenishment;
  if (report == null) {
    return (
      <Section title="Reposición">
        <p className={styles.note}>
          {detail.isFull
            ? 'Todavía no hay datos de reposición para esta publicación.'
            : 'Esta publicación no es Full: no hay reposición.'}
        </p>
      </Section>
    );
  }
  const partial = report.status === 'partial';
  // With the report off, why there is nothing is the news; a "never fetched" next to it adds nothing.
  const message = disabled ? DISABLED_MESSAGE : STATUS_MESSAGES[report.status];
  return (
    <Section title="Reposición">
      {partial && (
        <span
          className={cellStyles.badge}
          title={
            report.contentMissing
              ? `Mercado Libre devolvió una respuesta incompleta. Falta: ${report.contentMissing}`
              : 'Mercado Libre devolvió una respuesta incompleta'
          }
        >
          Datos parciales
        </span>
      )}
      {message && <p className={styles.note}>{message}</p>}
      {disabled && STATUS_MESSAGES[report.status] && report.status !== 'never_fetched' && (
        <p className={styles.note}>{STATUS_MESSAGES[report.status]}</p>
      )}
      <Fields>
        <Field label="Últimos 7 días">{count(report.units7d)}</Field>
        <Field label="Últimos 14 días">{count(report.units14d)}</Field>
        <Field label="Últimos 21 días">{count(report.units21d)}</Field>
        <Field label="Últimos 30 días">{count(report.units30d)}</Field>
        <Field label="GMV 30 días">
          {report.gmv30d == null ? null : [amount(report.gmv30d), report.currency].filter(Boolean).join(' ')}
        </Field>
        <Field label="Días sin stock (21 días)">{count(report.daysOutOfStock21d)}</Field>
        <Field label="Urgencia de envío">{orNull(report.shippingUrgency)}</Field>
        <Field label="Stock total en Full">{count(report.totalStock)}</Field>
        <Field label="Consultado">{date(report.fetchedAt)}</Field>
      </Fields>
    </Section>
  );
}

/** Full: stock in Full and Propio, and the replenishment report of the publication's user product. */
export default function FullTab({ detail, dataState }) {
  return (
    <>
      <StockSection row={detail.row} detail={detail} />
      <ReplenishmentSection detail={detail} disabled={replenishmentDisabled(dataState)} />
    </>
  );
}
