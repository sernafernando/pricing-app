/**
 * Create / edit role form (codigo, nombre, descripcion). Controlled: the parent
 * owns `form` and the API calls. In edit mode the codigo is locked.
 */
export default function FormularioRol({ form, onChange, esEdicion, guardando, onGuardar, onCancelar }) {
  return (
    <div style={{
      background: 'var(--bg-secondary)',
      padding: '16px',
      borderRadius: '8px',
      marginBottom: '16px',
      border: '1px solid var(--border-primary)'
    }}>
      <h4 style={{ margin: '0 0 12px 0', color: 'var(--text-primary)' }}>
        {esEdicion ? 'Editar Rol' : 'Nuevo Rol'}
      </h4>
      <div style={{ display: 'flex', flexDirection: 'column', gap: '10px' }}>
        <input
          type="text"
          placeholder="Codigo (ej: VENDEDOR)"
          value={form.codigo}
          onChange={(e) => onChange({ ...form, codigo: e.target.value.toUpperCase() })}
          disabled={esEdicion}
          style={{
            padding: '8px',
            borderRadius: '4px',
            border: '1px solid var(--border-secondary)',
            background: esEdicion ? 'var(--bg-tertiary)' : 'var(--bg-primary)',
            color: 'var(--text-primary)'
          }}
        />
        <input
          type="text"
          placeholder="Nombre"
          value={form.nombre}
          onChange={(e) => onChange({ ...form, nombre: e.target.value })}
          style={{ padding: '8px', borderRadius: '4px', border: '1px solid var(--border-secondary)', background: 'var(--bg-primary)', color: 'var(--text-primary)' }}
        />
        <textarea
          placeholder="Descripcion (opcional)"
          value={form.descripcion}
          onChange={(e) => onChange({ ...form, descripcion: e.target.value })}
          rows={2}
          style={{ padding: '8px', borderRadius: '4px', border: '1px solid var(--border-secondary)', background: 'var(--bg-primary)', color: 'var(--text-primary)', resize: 'vertical' }}
        />
        <div style={{ display: 'flex', gap: '8px' }}>
          <button
            onClick={onGuardar}
            disabled={guardando}
            className="btn-tesla outline-subtle-success"
            style={{ flex: 1 }}
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
    </div>
  );
}
