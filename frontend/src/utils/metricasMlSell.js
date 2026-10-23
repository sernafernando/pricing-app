import { formatUnits } from './metricasMlFormat';

const ventas = (n) => `${formatUnits(n)} ${n === 1 ? 'venta' : 'ventas'}`;

/** The sold lines a sell out total leaves out: a USD sell out without its rate yet is never summed as 0. */
export const sellOutPendingTitle = (n) => `${ventas(n)} con sell out en dólares sin tipo de cambio: no se suman`;

/** The sold lines whose sell out uses a rate that is still an estimate. */
export const sellOutEstimatedTitle = (n) => `${ventas(n)} con tipo de cambio estimado`;
