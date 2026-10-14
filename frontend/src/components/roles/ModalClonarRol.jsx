/**
 * Modal to clone `rol` into a new role (nuevo_codigo, nuevo_nombre, descripcion).
 * Controlled: the parent owns `datos` and the API call. Render it only while open.
 */
export default function ModalClonarRol({ rol, datos, onChange, guardando, onClonar, onCancelar }) {
  return (
    <div style={{
      position: 'fixed',
      top: 0,
      left: 0,
      right: 0,
      bottom: 0,
      background: 'rgba(0,0,0,0.5)',
      display: 'flex',
      alignItems: 'center',
      justifyContent: 'center',
      zIndex: 1000
    }}>
      <div style={{
        background: 'var(--bg-primary)',
        padding: '24px',
        borderRadius: '12px',
        width: '400px',
        maxWidth: '90%',
        border: '1px solid var(--border-primary)'
      }}>
        <h3 style={{ margin: '0 0 16px', color: 'var(--text-primary)' }}>Clonar Rol: {rol.nombre}</h3>
        <div style={{ display: 'flex', flexDirection: 'column', gap: '12px' }}>
          <input
            type="text"
            placeholder="Codigo del nuevo rol"
            value={datos.nuevo_codigo}
            onChange={(e) => onChange({ ...datos, nuevo_codigo: e.target.value.toUpperCase() })}
            style={{ padding: '10px', borderRadius: '6px', border: '1px solid var(--border-secondary)', background: 'var(--bg-primary)', color: 'var(--text-primary)' }}
          />
          <input
            type="text"
            placeholder="Nombre del nuevo rol"
            value={datos.nuevo_nombre}
            onChange={(e) => onChange({ ...datos, nuevo_nombre: e.target.value })}
            style={{ padding: '10px', borderRadius: '6px', border: '1px solid var(--border-secondary)', background: 'var(--bg-primary)', color: 'var(--text-primary)' }}
          />
          <textarea
            placeholder="Descripcion (opcional)"
            value={datos.descripcion}
            onChange={(e) => onChange({ ...datos, descripcion: e.target.value })}
            rows={2}
            style={{ padding: '10px', borderRadius: '6px', border: '1px solid var(--border-secondary)', background: 'var(--bg-primary)', color: 'var(--text-primary)', resize: 'vertical' }}
          />
          <div style={{ display: 'flex', gap: '8px', marginTop: '8px' }}>
            <button
              onClick={onClonar}
              disabled={guardando}
              className="btn-tesla outline-subtle-primary"
              style={{ flex: 1 }}
            >
              {guardando ? 'Clonando...' : 'Clonar'}
            </button>
            <button
              onClick={onCancelar}
              className="btn-tesla ghost"
            >
              Cancelar
            </button>
          </div>
        </div>
      </div>
    </div>
  );
}
