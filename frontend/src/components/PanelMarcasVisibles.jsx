import { useCallback, useEffect, useMemo, useState } from 'react';
import { Plus, Trash2 } from 'lucide-react';
import api from '../services/api';
import styles from './PanelMarcasVisibles.module.css';

const MAX_RESULTS = 50;

const errorMessage = (err, fallback) =>
  err?.response?.data?.detail || err?.response?.data?.error?.message || fallback;

const formatDate = (iso) => (iso ? new Date(iso).toLocaleDateString('es-AR') : '-');

function StockBadge({ conStock }) {
  return (
    <span className={conStock ? styles.stockOn : styles.stockOff}>{conStock ? 'con stock' : 'sin stock'}</span>
  );
}

/**
 * Admin panel: the exception list of brands kept visible without stock. A brand with no
 * product in stock is hidden from every brand filter and selector unless it is listed here.
 * The picker searches EVERY brand of the catalog, hidden ones included.
 */
export default function PanelMarcasVisibles() {
  const [excepciones, setExcepciones] = useState([]);
  const [marcas, setMarcas] = useState([]);
  const [loading, setLoading] = useState(true);
  const [busqueda, setBusqueda] = useState('');
  const [saving, setSaving] = useState(null);
  const [error, setError] = useState(null);

  const cargar = useCallback(async () => {
    try {
      const { data } = await api.get('/marcas-visibles');
      setExcepciones(data.excepciones);
      setMarcas(data.marcas);
    } catch (err) {
      setError(errorMessage(err, 'No se pudo cargar la lista de marcas'));
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    cargar();
  }, [cargar]);

  const resultados = useMemo(() => {
    const term = busqueda.trim().toLowerCase();
    if (!term) return [];
    return marcas.filter((m) => m.marca.toLowerCase().includes(term)).slice(0, MAX_RESULTS);
  }, [busqueda, marcas]);

  const agregar = async (marca) => {
    setSaving(marca);
    setError(null);
    try {
      await api.post('/marcas-visibles/excepciones', { marca });
      await cargar();
    } catch (err) {
      setError(errorMessage(err, 'No se pudo agregar la marca'));
    } finally {
      setSaving(null);
    }
  };

  const quitar = async (excepcion) => {
    setSaving(excepcion.marca);
    setError(null);
    try {
      await api.delete(`/marcas-visibles/excepciones/${excepcion.id}`);
      await cargar();
    } catch (err) {
      setError(errorMessage(err, 'No se pudo quitar la marca'));
    } finally {
      setSaving(null);
    }
  };

  return (
    <div className={styles.container}>
      <h2 className={styles.title}>Marcas sin stock visibles</h2>
      <p className={styles.desc}>
        Una marca sin ningún producto en stock no aparece en los filtros ni en los selectores del sistema. Las
        marcas de esta lista se siguen mostrando aunque se queden sin stock. En Métricas ML y Ventas ML una marca
        que vendió en el período que estás viendo también se muestra.
      </p>

      {error && <div className={styles.error} role="alert">{error}</div>}

      <div className={styles.picker}>
        <label className={styles.label} htmlFor="marcas-visibles-buscar">
          Agregar una marca
        </label>
        <input
          id="marcas-visibles-buscar"
          type="search"
          className={styles.input}
          placeholder="Buscar entre todas las marcas"
          value={busqueda}
          onChange={(e) => setBusqueda(e.target.value)}
          autoComplete="off"
        />
        {busqueda.trim() !== '' && (
          resultados.length === 0 ? (
            <div className={styles.hint}>No hay marcas que coincidan</div>
          ) : (
            <ul className={styles.results} aria-label="Marcas encontradas">
              {resultados.map((m) => (
                <li key={m.marca} className={styles.result}>
                  <span className={styles.resultName}>
                    {m.marca}
                    <StockBadge conStock={m.con_stock} />
                  </span>
                  {m.en_excepcion ? (
                    <span className={styles.added}>En la lista</span>
                  ) : (
                    <button
                      className={styles.btnAdd}
                      onClick={() => agregar(m.marca)}
                      disabled={saving !== null}
                      aria-label={`Agregar ${m.marca}`}
                    >
                      <Plus size={14} /> Agregar
                    </button>
                  )}
                </li>
              ))}
            </ul>
          )
        )}
      </div>

      {loading ? (
        <div className={styles.loading}>Cargando marcas...</div>
      ) : excepciones.length === 0 ? (
        <div className={styles.empty}>No hay marcas en la lista: todas las marcas sin stock están ocultas</div>
      ) : (
        <div className={styles.tableWrapper}>
          <table className={styles.table}>
            <thead>
              <tr>
                <th>Marca</th>
                <th>Stock actual</th>
                <th>Agregada por</th>
                <th>Fecha</th>
                <th aria-label="Acciones" />
              </tr>
            </thead>
            <tbody>
              {excepciones.map((e) => (
                <tr key={e.id}>
                  <td><strong>{e.marca}</strong></td>
                  <td><StockBadge conStock={e.con_stock} /></td>
                  <td>{e.creado_por || '-'}</td>
                  <td>{formatDate(e.created_at)}</td>
                  <td>
                    <button
                      className={styles.btnRemove}
                      onClick={() => quitar(e)}
                      disabled={saving !== null}
                      title="Quitar de la lista"
                      aria-label={`Quitar ${e.marca}`}
                    >
                      <Trash2 size={14} />
                    </button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}
