import { useState } from 'react';
import { Search } from 'lucide-react';
import ModalTesla, { ModalFooterButtons } from '../ModalTesla';
import api from '../../services/api';
import { mensajeError } from '../ventasFueraPdf/formato';
import styles from './AsignarProductoModal.module.css';

/**
 * Assigns the real product to a PDF line (ODD `vpf-operaciones` S3): searches the ERP catalog with the same
 * GET /buscar-productos-erp ModalEditarCosto uses and calls `onAsignar(itemId, recordarMapeo)`. "Recordar para
 * próximas cargas" (on by default) makes the next uploads of that code resolve by themselves.
 */
export default function AsignarProductoModal({ linea, onClose, onAsignar }) {
  const [busqueda, setBusqueda] = useState('');
  const [resultados, setResultados] = useState(null);
  const [buscando, setBuscando] = useState(false);
  const [elegido, setElegido] = useState(null);
  const [recordar, setRecordar] = useState(true);
  const [guardando, setGuardando] = useState(false);
  const [error, setError] = useState(null);

  const buscar = async (event) => {
    event.preventDefault();
    if (busqueda.trim().length < 2) return;
    setBuscando(true);
    setError(null);
    try {
      const response = await api.get('/buscar-productos-erp', { params: { q: busqueda.trim() } });
      setResultados(response.data || []);
    } catch (err) {
      setError(mensajeError(err, 'No se pudo buscar en el catálogo'));
    } finally {
      setBuscando(false);
    }
  };

  const asignar = async () => {
    if (!elegido) return;
    setGuardando(true);
    setError(null);
    try {
      await onAsignar(elegido.item_id, recordar);
    } catch (err) {
      setError(mensajeError(err, 'No se pudo asignar el producto'));
      setGuardando(false);
    }
  };

  return (
    <ModalTesla
      isOpen
      onClose={onClose}
      closeOnOverlay={false}
      title="Asignar producto"
      subtitle={`Línea ${linea.renglon}: ${linea.articulo}`}
      size="md"
      footer={
        <ModalFooterButtons
          onCancel={onClose}
          onConfirm={asignar}
          confirmText="Asignar"
          confirmLoading={guardando}
          confirmDisabled={!elegido}
        />
      }
    >
      <div className={styles.cuerpo}>
        <form className={styles.busqueda} onSubmit={buscar} role="search">
          <input
            type="search"
            className={styles.input}
            aria-label="Buscar producto"
            placeholder="Código o descripción del producto"
            value={busqueda}
            onChange={(e) => setBusqueda(e.target.value)}
            autoFocus
          />
          <button type="submit" className={styles.buscar} disabled={busqueda.trim().length < 2 || buscando}>
            <Search size={14} aria-hidden="true" />
            {buscando ? 'Buscando…' : 'Buscar'}
          </button>
        </form>

        {error && (
          <p className={styles.error} role="alert">
            {error}
          </p>
        )}

        {resultados && resultados.length === 0 && <p className={styles.vacio}>No hay productos con esa búsqueda.</p>}
        {resultados && resultados.length > 0 && (
          <ul className={styles.resultados} aria-label="Productos encontrados">
            {resultados.map((producto) => (
              <li key={producto.item_id}>
                <button
                  type="button"
                  className={styles.resultado}
                  aria-pressed={elegido?.item_id === producto.item_id}
                  onClick={() => setElegido(producto)}
                >
                  <span className={styles.codigo}>{producto.codigo}</span>
                  <span className={styles.descripcion}>{producto.descripcion}</span>
                  {producto.marca && <span className={styles.marca}>{producto.marca}</span>}
                </button>
              </li>
            ))}
          </ul>
        )}

        <label className={styles.recordar}>
          <input type="checkbox" checked={recordar} onChange={(e) => setRecordar(e.target.checked)} />
          Recordar para próximas cargas
        </label>
        <p className={styles.ayuda}>
          Las próximas cargas con el mismo código (o el mismo artículo, si no tiene código) toman este producto solas.
        </p>
      </div>
    </ModalTesla>
  );
}
