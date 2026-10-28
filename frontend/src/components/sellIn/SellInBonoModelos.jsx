import { X } from 'lucide-react';
import { modelosConOtroTipo, valorDeModelo } from './sellInBonoValores';
import { formatMonto, formatPorcentaje } from './sellInFormat';
import styles from './SellInPanel.module.css';

/**
 * The models of a models bonus (T23b, like a sell-out campaign's per-product amounts): each one can have its
 * own value of the bonus's kind, an amount per unit in the bonus currency or a %; empty, it uses the bonus's.
 * Values of the other kind stay in the form (switching back restores them) but are not sent, and a note says
 * so. Read only, each model shows its own value when it has one. Controlled.
 */
export default function SellInBonoModelos({ valores, disabled, onChange }) {
  const porcentaje = valores.tipo === 'porcentaje';
  const campo = porcentaje ? 'porcentaje' : 'montoUnit';
  const otroTipo = modelosConOtroTipo(valores).length;
  const setValor = (itemId, valor) => onChange(valores.modelos.map((m) => (m.itemId === itemId ? { ...m, [campo]: valor } : m)));
  const propio = (modelo) => {
    const valor = valorDeModelo(modelo, valores.tipo);
    if (valor === '') return null;
    return porcentaje ? formatPorcentaje(valor) : formatMonto(valor, valores.moneda);
  };

  if (valores.modelos.length === 0) return null;
  return (
    <>
      <ul className={disabled ? styles.chips : styles.lineas} aria-label="Modelos del bono">
        {valores.modelos.map((modelo) =>
          disabled ? (
            <li key={modelo.itemId} className={styles.chip}>
              <span>{modelo.label}</span>
              {propio(modelo) && <span className={styles.mono}>{` · ${propio(modelo)}`}</span>}
            </li>
          ) : (
            <li key={modelo.itemId} className={styles.linea}>
              <span className={styles.lineaNombre}>{modelo.label}</span>
              <input
                type="number"
                min="0"
                max={porcentaje ? '100' : undefined}
                step={porcentaje ? '0.0001' : '0.01'}
                className={styles.inputSm}
                aria-label={`${porcentaje ? 'Porcentaje' : 'Monto'} de ${modelo.label}`}
                placeholder={porcentaje ? '% del bono' : `Monto (${valores.moneda})`}
                value={modelo[campo]}
                onChange={(e) => setValor(modelo.itemId, e.target.value)}
              />
              <button
                type="button"
                className={styles.close}
                aria-label={`Quitar modelo ${modelo.label}`}
                onClick={() => onChange(valores.modelos.filter((m) => m.itemId !== modelo.itemId))}
              >
                <X size={12} />
              </button>
            </li>
          ),
        )}
      </ul>
      {!disabled && <p className={styles.hint}>Los modelos sin valor propio usan el del bono.</p>}
      {!disabled && otroTipo > 0 && (
        <p className={styles.hint} role="status">
          {`Un bono ${porcentaje ? 'por porcentaje no lleva montos por unidad propios' : 'por unidad no lleva porcentajes propios'}: al guardar se ${
            otroTipo === 1 ? 'quita el de 1 modelo' : `quitan los de ${otroTipo} modelos`
          }.`}
        </p>
      )}
    </>
  );
}
