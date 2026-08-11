/**
 * EmpleadoMultiSelect — lista filtrable de empleados con selección múltiple.
 *
 * La nómina pasa los 100 registros, así que un `<select multiple>` es
 * inservible: hace falta filtro por texto y un "todos / ninguno" que opere
 * sobre lo FILTRADO (seleccionar 200 para después destildar 195 no es una
 * afordancia, es un castigo).
 *
 * Props:
 *   empleados     - array ({ id, legajo, nombre, apellido, nombre_completo })
 *   seleccionados - array de ids seleccionados (controlado)
 *   onChange      - function(nuevosIds)
 *   icono         - nodo opcional a la izquierda del buscador
 */
import { useState } from 'react';
import styles from './EmpleadoMultiSelect.module.css';

const etiqueta = (emp) => {
  const nombre = emp.nombre_completo || [emp.apellido, emp.nombre].filter(Boolean).join(', ');
  return emp.legajo ? `${emp.legajo} - ${nombre}` : nombre;
};

export default function EmpleadoMultiSelect({ empleados = [], seleccionados = [], onChange, icono }) {
  const [filtro, setFiltro] = useState('');

  const termino = filtro.trim().toLowerCase();
  const visibles = termino
    ? empleados.filter((emp) => etiqueta(emp).toLowerCase().includes(termino))
    : empleados;

  const idsVisibles = visibles.map((emp) => emp.id);
  const todosVisiblesElegidos =
    idsVisibles.length > 0 && idsVisibles.every((id) => seleccionados.includes(id));

  const alternarTodos = () => {
    if (todosVisiblesElegidos) {
      onChange(seleccionados.filter((id) => !idsVisibles.includes(id)));
      return;
    }
    onChange([...new Set([...seleccionados, ...idsVisibles])]);
  };

  const alternarUno = (id) => {
    onChange(
      seleccionados.includes(id)
        ? seleccionados.filter((otro) => otro !== id)
        : [...seleccionados, id]
    );
  };

  return (
    <div className={styles.container}>
      <div className={styles.toolbar}>
        <div className={styles.searchWrap}>
          {icono}
          <input
            className={styles.search}
            type="search"
            value={filtro}
            onChange={(e) => setFiltro(e.target.value)}
            placeholder="Buscar por legajo o nombre..."
            aria-label="Buscar empleado"
          />
        </div>
        <button
          type="button"
          className="btn-tesla ghost sm"
          onClick={alternarTodos}
          disabled={idsVisibles.length === 0}
        >
          {todosVisiblesElegidos ? 'Ninguno' : 'Todos'}
        </button>
        <span className={styles.contador}>{seleccionados.length} seleccionados</span>
      </div>

      <ul className={styles.lista}>
        {visibles.length === 0 && <li className={styles.vacio}>Sin empleados que coincidan</li>}
        {visibles.map((emp) => (
          <li key={emp.id}>
            <label className={styles.item}>
              <input
                type="checkbox"
                checked={seleccionados.includes(emp.id)}
                onChange={() => alternarUno(emp.id)}
              />
              {etiqueta(emp)}
            </label>
          </li>
        ))}
      </ul>
    </div>
  );
}
