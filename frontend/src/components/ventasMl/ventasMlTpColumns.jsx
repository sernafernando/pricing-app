import styles from '../../pages/VentasML.module.css';
import RecalculatingBadge from './RecalculatingBadge';
import { COLUMNS } from './ventasMlColumns';
import { Money, MarkupChip, ProvisionalPill } from './ventasMlCells';
import { moneyTitle } from '../../utils/ventasMlFormat';
import { moneyTone } from '../../utils/ventasMlTone';

// TP mode (`tpMode.js`): the same table with Total TP where Total Gauss
// was, so column ids, order and the locked ones stay identical. The picker
// derives from the list, so no Gauss entry exists in TP mode either.
const TOTAL_TP_COLUMN = {
  id: 'total_tp',
  header: 'Total TP',
  size: 135,
  minSize: 110,
  numeric: true,
  enableHiding: false,
  cell: (ctx) => {
    const entity = ctx.kind === 'group' ? ctx.group : ctx.order;
    const metricsState = ctx.kind === 'group' ? ctx.metricsState : ctx.order.metrics_state || 'ok';
    if (metricsState !== 'ok') {
      return <RecalculatingBadge state={metricsState} />;
    }
    // No TP cost (no list-8 price): the figure is unknown, never 0.
    if (entity.tp_incompleto || entity.total_tp === null || entity.total_tp === undefined) {
      return (
        <>
          <span className={styles.amount} data-money>
            —
          </span>
          <span className={styles.subline} title="Falta el costo TP de algún producto">
            incompleto
          </span>
        </>
      );
    }
    const markup = ctx.kind === 'group' ? ctx.loneOrder?.markup_tp : ctx.order.markup_tp;
    const tone = moneyTone(entity.total_tp);
    return (
      <>
        <Money
          value={entity.total_tp}
          currencyId={entity.currency_id}
          tone={tone === 'negative' ? 'negative' : tone === 'positive' ? 'positive' : null}
        />
        {(markup !== null && markup !== undefined) || entity.total_tp_provisional ? (
          <span className={styles.moneyMeta}>
            <MarkupChip value={markup} />
            {entity.total_tp_provisional && <ProvisionalPill falta={entity.total_tp_provisional_falta} />}
          </span>
        ) : null}
      </>
    );
  },
  cellProps: (ctx) => {
    const entity = ctx.kind === 'group' ? ctx.group : ctx.order;
    const metricsState = ctx.kind === 'group' ? ctx.metricsState : ctx.order.metrics_state || 'ok';
    return { title: moneyTitle(entity.total_tp, entity.currency_id, metricsState) };
  },
};

export const TP_COLUMNS = COLUMNS.map((column) => (column.id === 'total_gauss' ? TOTAL_TP_COLUMN : column));
