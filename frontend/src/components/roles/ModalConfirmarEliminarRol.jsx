import { useRef } from 'react';
import ModalTesla from '../ModalTesla';
import styles from './ModalConfirmarEliminarRol.module.css';

/**
 * Confirmation dialog before deleting `rol`. Controlled: the parent owns the
 * DELETE call and renders it only while a role is pending deletion. While
 * `eliminando`, both buttons are disabled and Esc / Cancelar / X do nothing,
 * so the dialog cannot vanish mid-request.
 */
export default function ModalConfirmarEliminarRol({ rol, eliminando, onConfirmar, onCancelar }) {
  const cancelarRef = useRef(null);

  const cerrar = () => {
    if (!eliminando) onCancelar();
  };

  return (
    <ModalTesla
      isOpen
      onClose={cerrar}
      title="Eliminar rol"
      size="sm"
      closeOnOverlay={false}
      initialFocusRef={cancelarRef}
    >
      <p className={styles.mensaje}>
        {`¿Eliminar el rol "${rol.nombre}"? Esta accion no se puede deshacer.`}
      </p>
      <div className={styles.acciones}>
        <button
          ref={cancelarRef}
          type="button"
          disabled={eliminando}
          className="btn-tesla ghost sm"
          onClick={cerrar}
        >
          Cancelar
        </button>
        <button
          type="button"
          disabled={eliminando}
          className="btn-tesla outline-subtle-danger sm"
          onClick={onConfirmar}
        >
          {eliminando ? 'Eliminando...' : 'Eliminar'}
        </button>
      </div>
    </ModalTesla>
  );
}
