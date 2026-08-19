import { AlertTriangle } from 'lucide-react';
import styles from './FiltrosNoAplicablesAviso.module.css';

/**
 * Warns that the bulk operation about to run does NOT honour some of the
 * filters currently narrowing the listing — so it will touch a WIDER set of
 * products than the ones on screen.
 *
 * Why this exists: the export and mass-calculation endpoints accept a subset
 * of the listing's filters. The rest are dropped — some in these modals, some
 * server-side — and until now that happened in silence. On "Calcular PVP
 * masivo" that silence writes prices to products the operator never saw.
 *
 * The list below is the PROVEN subset, not an exhaustive audit: these two are
 * read from `filtrosActivos` by nobody in ExportModal / CalcularPVPModal /
 * CalcularWebModal (verified by reading all three). Other filters may also be
 * dropped further down; see the `ponytail:` markers in those modals.
 *
 * @param {{ filtrosActivos: object | undefined }} props
 */

const FILTROS_NO_SOPORTADOS = [
  { activo: (f) => f.filtroPxq === 'con_pxq', label: 'Con precios mayoristas' },
  { activo: (f) => Boolean(f.promo_tipos), label: 'Promos' },
];

export default function FiltrosNoAplicablesAviso({ filtrosActivos }) {
  if (!filtrosActivos) return null;

  const ignorados = FILTROS_NO_SOPORTADOS.filter(({ activo }) => activo(filtrosActivos)).map(({ label }) => label);

  if (ignorados.length === 0) return null;

  return (
    <div className={styles.aviso} role="alert">
      <AlertTriangle size={14} aria-hidden />
      <span>
        Esta operación <strong>no aplica</strong> {ignorados.length === 1 ? 'el filtro' : 'los filtros'}{' '}
        <strong>{ignorados.join(' + ')}</strong>: va a correr sobre un conjunto <strong>más amplio</strong> que el que
        ves en el listado.
      </span>
    </div>
  );
}
