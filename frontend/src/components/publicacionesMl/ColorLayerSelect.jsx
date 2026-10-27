import { useEffect } from 'react';
import styles from './ColorLayerSelect.module.css';

/**
 * The color layer the rows are painted with (S8): the global one ('') or one of the user's teams, the same layers
 * Productos paints; `equipos` / `loaded` are `useEquipos`' (the page shares them with F6/F7). Hidden while the user has no team: the global layer is all there is. A team the user is not in
 * (a link someone else shared) is dropped once the teams are known: the backend refuses it with a 403.
 */
export default function ColorLayerSelect({ value, onChange, equipos, loaded, labelClassName }) {
  const teams = equipos.filter((equipo) => !equipo.es_global);
  const unknown = loaded && value !== '' && !teams.some((equipo) => String(equipo.id) === value);

  useEffect(() => {
    if (unknown) onChange('');
  }, [unknown, onChange]);

  if (teams.length === 0 && !value) return null;

  return (
    <label className={styles.layer}>
      <span className={labelClassName}>Capa:</span>
      <select
        className={styles.select}
        aria-label="Capa de color"
        title="Capa de color por equipo"
        value={value}
        onChange={(event) => onChange(event.target.value)}
      >
        <option value="">Global</option>
        {teams.map((equipo) => (
          <option key={equipo.id} value={String(equipo.id)}>
            {equipo.nombre}
          </option>
        ))}
      </select>
    </label>
  );
}
