/**
 * The "Costos TP" answer of `GET /ml-metricas/board` (backend P4): the KPI strip's `kpis.total_tp` block and
 * the row fields `total_tp` / `tp_incompletos`, laid over the shared board fixture. Three kinds of rows: a
 * known Total TP, a known one with incomplete lines, and an unknown one (every TP line without a TP cost).
 */
import { BOARD_RESPONSE } from '../../test/visual/metricasMlFixtures';

export const TP_KPIS = { value: 3125400.5, incompletos: 3 };

const ROW_TP = [
  { total_tp: 9850000.25, tp_incompletos: 0 },
  { total_tp: 1240000, tp_incompletos: 2 },
  { total_tp: null, tp_incompletos: 1 },
];

/** The board as the API answers it with `costos_tp=true`; rows past the third have no TP-store sale. */
export function withTp(board = BOARD_RESPONSE, kpi = TP_KPIS) {
  return {
    ...board,
    kpis: { ...board.kpis, total_tp: kpi },
    rows: board.rows.map((row, index) => ({ ...row, ...(ROW_TP[index] ?? { total_tp: null, tp_incompletos: 0 }) })),
  };
}
