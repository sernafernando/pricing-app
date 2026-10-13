import { useRef, useState } from 'react';
import ModalTesla from '../ModalTesla';
import styles from './ModalUsuario.module.css';

const MODOS = {
  crear: { titulo: 'Nuevo usuario', confirmar: 'Crear Usuario', guardando: 'Creando...' },
  editar: { titulo: 'Editar usuario', confirmar: 'Guardar', guardando: 'Guardar' },
};

/**
 * Create / edit user dialog of the Usuarios tab. Holds only the form fields;
 * the parent validates, calls the API and closes it on success. `error` is
 * shown inside the dialog so it is not hidden behind the overlay.
 *
 * `inicial` seeds the fields (`{ username, email, nombre, password?, rol_id }`);
 * the password field exists only when creating.
 */
export default function ModalUsuario({ modo, inicial, roles, guardando, error, onGuardar, onCerrar }) {
  const [form, setForm] = useState(inicial);
  const primerCampoRef = useRef(null);
  const textos = MODOS[modo];
  const tituloId = `modal-usuario-${modo}`;

  const cambiar = (campo) => (e) => setForm((prev) => ({ ...prev, [campo]: e.target.value }));

  const enviar = (e) => {
    e.preventDefault();
    onGuardar(form);
  };

  return (
    <ModalTesla
      isOpen
      onClose={onCerrar}
      title={<span id={tituloId}>{textos.titulo}</span>}
      size="sm"
      closeOnOverlay={false}
      initialFocusRef={primerCampoRef}
    >
      <form className={styles.form} aria-labelledby={tituloId} onSubmit={enviar} noValidate>
        {error && (
          <div className={styles.error} role="alert">
            {error}
          </div>
        )}

        <label className={styles.campo}>
          <span className={styles.etiqueta}>Usuario</span>
          <input
            ref={primerCampoRef}
            type="text"
            className={styles.input}
            placeholder={modo === 'crear' ? 'Nombre de usuario (requerido)' : 'Nombre de usuario'}
            value={form.username || ''}
            onChange={cambiar('username')}
          />
        </label>
        <label className={styles.campo}>
          <span className={styles.etiqueta}>Email</span>
          <input
            type="email"
            className={styles.input}
            placeholder="Email (opcional)"
            value={form.email || ''}
            onChange={cambiar('email')}
          />
        </label>
        <label className={styles.campo}>
          <span className={styles.etiqueta}>Nombre completo</span>
          <input
            type="text"
            className={styles.input}
            placeholder="Nombre completo"
            value={form.nombre || ''}
            onChange={cambiar('nombre')}
          />
        </label>
        {modo === 'crear' && (
          <label className={styles.campo}>
            <span className={styles.etiqueta}>Contraseña</span>
            <input
              type="password"
              className={styles.input}
              placeholder="Contraseña"
              value={form.password || ''}
              onChange={cambiar('password')}
            />
          </label>
        )}
        <label className={styles.campo}>
          <span className={styles.etiqueta}>Rol</span>
          <select
            className={styles.input}
            value={form.rol_id || ''}
            onChange={(e) => setForm((prev) => ({ ...prev, rol_id: parseInt(e.target.value) }))}
          >
            {modo === 'crear' && <option value="">Seleccionar rol...</option>}
            {roles.map((rol) => (
              <option key={rol.id} value={rol.id}>
                {rol.nombre}
              </option>
            ))}
          </select>
        </label>

        <div className={styles.acciones}>
          <button type="button" className="btn-tesla ghost sm" onClick={onCerrar}>
            Cancelar
          </button>
          <button type="submit" disabled={guardando} className="btn-tesla outline-subtle-success sm">
            {guardando ? textos.guardando : textos.confirmar}
          </button>
        </div>
      </form>
    </ModalTesla>
  );
}
