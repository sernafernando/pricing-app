import styles from './FormularioRol.module.css';

/**
 * Create / edit role form (codigo, nombre, descripcion), rendered inside the role
 * drawer, whose title says "Nuevo Rol" / "Editar Rol". Controlled: the parent
 * owns `form` and the API calls. In edit mode the codigo is locked. `bloqueado`
 * disables the submit while another save (the permissions matrix) is in flight.
 */
export default function FormularioRol({ form, onChange, esEdicion, guardando, bloqueado = false, onGuardar, onCancelar }) {
  return (
    <div className={styles.formulario}>
      <input
        type="text"
        placeholder="Codigo (ej: VENDEDOR)"
        value={form.codigo}
        onChange={(e) => onChange({ ...form, codigo: e.target.value.toUpperCase() })}
        disabled={esEdicion}
        className={styles.campo}
      />
      <input
        type="text"
        placeholder="Nombre"
        value={form.nombre}
        onChange={(e) => onChange({ ...form, nombre: e.target.value })}
        className={styles.campo}
      />
      <textarea
        placeholder="Descripcion (opcional)"
        value={form.descripcion}
        onChange={(e) => onChange({ ...form, descripcion: e.target.value })}
        rows={2}
        className={styles.descripcion}
      />
      <div className={styles.acciones}>
        <button
          onClick={onGuardar}
          disabled={guardando || bloqueado}
          className={`btn-tesla outline-subtle-success ${styles.guardar}`}
        >
          {guardando ? 'Guardando...' : (esEdicion ? 'Actualizar' : 'Crear')}
        </button>
        <button
          onClick={onCancelar}
          className="btn-tesla outline-subtle-danger"
        >
          Cancelar
        </button>
      </div>
    </div>
  );
}
