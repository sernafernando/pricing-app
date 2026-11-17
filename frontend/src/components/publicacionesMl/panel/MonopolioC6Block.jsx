import { TrendingUp } from 'lucide-react';
import { formatAmount } from '../../../utils/ventasMlFormat';
import styles from './panel.module.css';

/**
 * C6 raise-price suggestion block (below classic candidatas when both apply).
 */
export default function MonopolioC6Block({ oportunidad }) {
  if (!oportunidad) return null;
  const raiseBy = Math.max(0, oportunidad.precio_objetivo - oportunidad.our_price);
  return (
    <div className={styles.ponerPreciosMejores} role="region" aria-label="Oportunidad de monopolio">
      <p className={styles.ponerPreciosMejoresLead}>
        <TrendingUp size={14} aria-hidden="true" className={styles.mejoresIcon} />
        <span>
          Tenés oportunidad de aumentar el precio en ${formatAmount(raiseBy)} y mantener tu posición en el
          catálogo (2º a ${formatAmount(oportunidad.segundo_precio)}; objetivo $
          {formatAmount(oportunidad.precio_objetivo)}).
        </span>
      </p>
      <p className={styles.ponerPreciosOk} role="status">
        Gap actual ~ ${formatAmount(oportunidad.gap)}. Si no hay promo que asista, podés apuntar Premium cerca
        del objetivo (editable).
      </p>
    </div>
  );
}
