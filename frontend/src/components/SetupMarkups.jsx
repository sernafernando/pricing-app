import { useState, useEffect } from 'react';
import axios from 'axios';
import styles from './SetupMarkups.module.css';

export default function SetupMarkups() {
  const [brands, setBrands] = useState([]);
  const [loading, setLoading] = useState(false);
  const [busqueda, setBusqueda] = useState('');
  const [soloConMarkup, setSoloConMarkup] = useState(false);
  const [editandoMarkup, setEditandoMarkup] = useState(null);
  const [markupTemp, setMarkupTemp] = useState('');
  const [stats, setStats] = useState(null);
  const [toast, setToast] = useState(null);

  const cargarBrands = async () => {
    setLoading(true);
    try {
      const params = new URLSearchParams();
      if (busqueda) params.append('busqueda', busqueda);
      if (soloConMarkup) params.append('solo_con_markup', 'true');

      const response = await axios.get(
        `https://pricing.gaussonline.com.ar/api/markups-tienda/brands?${params}`,
        { headers: { Authorization: `Bearer ${localStorage.getItem('token')}` } }
      );
      setBrands(response.data);
    } catch (error) {
      console.error('Error cargando brands:', error);
      mostrarToast('Error al cargar marcas', 'error');
    } finally {
      setLoading(false);
    }
  };

  const cargarStats = async () => {
    try {
      const response = await axios.get(
        'https://pricing.gaussonline.com.ar/api/markups-tienda/stats',
        { headers: { Authorization: `Bearer ${localStorage.getItem('token')}` } }
      );
      setStats(response.data);
    } catch (error) {
      console.error('Error cargando stats:', error);
    }
  };

  const guardarMarkup = async (brand) => {
    if (!markupTemp || isNaN(parseFloat(markupTemp))) {
      mostrarToast('Ingresá un markup válido', 'error');
      return;
    }

    try {
      await axios.post(
        `https://pricing.gaussonline.com.ar/api/markups-tienda/brands/${brand.comp_id}/${brand.brand_id}/markup`,
        {
          comp_id: brand.comp_id,
          brand_id: brand.brand_id,
          brand_desc: brand.brand_desc,
          markup_porcentaje: parseFloat(markupTemp),
          activo: true
        },
        { headers: { Authorization: `Bearer ${localStorage.getItem('token')}` } }
      );

      mostrarToast('Markup guardado correctamente', 'success');
      setEditandoMarkup(null);
      setMarkupTemp('');
      cargarBrands();
      cargarStats();
    } catch (error) {
      console.error('Error guardando markup:', error);
      mostrarToast('Error al guardar markup', 'error');
    }
  };

  const eliminarMarkup = async (brand) => {
    if (!confirm(`¿Eliminar markup de ${brand.brand_desc}?`)) return;

    try {
      await axios.delete(
        `https://pricing.gaussonline.com.ar/api/markups-tienda/brands/${brand.comp_id}/${brand.brand_id}/markup`,
        { headers: { Authorization: `Bearer ${localStorage.getItem('token')}` } }
      );

      mostrarToast('Markup eliminado', 'success');
      cargarBrands();
      cargarStats();
    } catch (error) {
      console.error('Error eliminando markup:', error);
      mostrarToast('Error al eliminar markup', 'error');
    }
  };

  const mostrarToast = (mensaje, tipo) => {
    setToast({ mensaje, tipo });
    setTimeout(() => setToast(null), 3000);
  };

  const iniciarEdicion = (brand) => {
    setEditandoMarkup({ comp_id: brand.comp_id, brand_id: brand.brand_id });
    setMarkupTemp(brand.markup_porcentaje?.toString() || '');
  };

  const cancelarEdicion = () => {
    setEditandoMarkup(null);
    setMarkupTemp('');
  };

  useEffect(() => {
    cargarBrands();
    cargarStats();
  }, [busqueda, soloConMarkup]);

  return (
    <div className={styles.container}>
      {/* Header con estadísticas */}
      <div className={styles.header}>
        <h2 className={styles.title}>Configuración de Markups por Marca</h2>

        {stats && (
          <div className={styles.statsGrid}>
            <div className={styles.statCard}>
              <div className={styles.statIcon}>📊</div>
              <div className={styles.statContent}>
                <div className={styles.statLabel}>Total Marcas</div>
                <div className={styles.statValue}>{stats.total_marcas}</div>
              </div>
            </div>
            <div className={`${styles.statCard} ${styles.statSuccess}`}>
              <div className={styles.statIcon}>✅</div>
              <div className={styles.statContent}>
                <div className={styles.statLabel}>Con Markup</div>
                <div className={styles.statValue}>{stats.total_con_markup}</div>
              </div>
            </div>
            <div className={`${styles.statCard} ${styles.statWarning}`}>
              <div className={styles.statIcon}>❌</div>
              <div className={styles.statContent}>
                <div className={styles.statLabel}>Sin Markup</div>
                <div className={styles.statValue}>{stats.total_sin_markup}</div>
              </div>
            </div>
            <div className={`${styles.statCard} ${styles.statInfo}`}>
              <div className={styles.statIcon}>📈</div>
              <div className={styles.statContent}>
                <div className={styles.statLabel}>Markup Promedio</div>
                <div className={styles.statValue}>{stats.markup_promedio}%</div>
              </div>
            </div>
          </div>
        )}
      </div>

      {/* Filtros */}
      <div className={styles.filters}>
        <div className={styles.searchBox}>
          <span className={styles.searchIcon}>🔍</span>
          <input
            type="text"
            placeholder="Buscar marca..."
            value={busqueda}
            onChange={(e) => setBusqueda(e.target.value)}
            className={styles.searchInput}
          />
          {busqueda && (
            <button onClick={() => setBusqueda('')} className={styles.clearButton}>
              ✕
            </button>
          )}
        </div>

        <label className={styles.checkbox}>
          <input
            type="checkbox"
            checked={soloConMarkup}
            onChange={(e) => setSoloConMarkup(e.target.checked)}
          />
          <span>Solo con markup</span>
        </label>
      </div>

      {/* Tabla de marcas */}
      {loading ? (
        <div className={styles.loading}>
          <div className={styles.spinner}></div>
          <p>Cargando marcas...</p>
        </div>
      ) : (
        <div className={styles.tableContainer}>
          <table className={styles.table}>
            <thead>
              <tr>
                <th>Marca</th>
                <th>Markup (%)</th>
                <th>Estado</th>
                <th>Acciones</th>
              </tr>
            </thead>
            <tbody>
              {brands.length === 0 ? (
                <tr>
                  <td colSpan="4" className={styles.emptyState}>
                    <div className={styles.emptyIcon}>📦</div>
                    <p>No se encontraron marcas</p>
                  </td>
                </tr>
              ) : (
                brands.map((brand) => (
                  <tr key={`${brand.comp_id}-${brand.brand_id}`} className={styles.row}>
                    <td className={styles.brandName}>
                      <strong>{brand.brand_desc}</strong>
                      <span className={styles.brandId}>ID: {brand.brand_id}</span>
                    </td>
                    <td>
                      {editandoMarkup?.comp_id === brand.comp_id && editandoMarkup?.brand_id === brand.brand_id ? (
                        <div className={styles.editInput}>
                          <input
                            type="number"
                            step="0.1"
                            value={markupTemp}
                            onChange={(e) => setMarkupTemp(e.target.value)}
                            onKeyDown={(e) => {
                              if (e.key === 'Enter') guardarMarkup(brand);
                              if (e.key === 'Escape') cancelarEdicion();
                            }}
                            autoFocus
                            placeholder="0.0"
                          />
                          <span className={styles.percentSign}>%</span>
                        </div>
                      ) : (
                        <div
                          className={`${styles.markupDisplay} ${brand.markup_porcentaje ? styles.hasMarkup : styles.noMarkup}`}
                          onClick={() => iniciarEdicion(brand)}
                        >
                          {brand.markup_porcentaje ? (
                            <>
                              <span className={styles.markupValue}>{brand.markup_porcentaje}</span>
                              <span className={styles.percentSign}>%</span>
                            </>
                          ) : (
                            <span className={styles.addMarkup}>+ Agregar markup</span>
                          )}
                        </div>
                      )}
                    </td>
                    <td>
                      {brand.markup_id && (
                        <span className={`${styles.badge} ${brand.markup_activo ? styles.badgeActive : styles.badgeInactive}`}>
                          {brand.markup_activo ? 'Activo' : 'Inactivo'}
                        </span>
                      )}
                    </td>
                    <td>
                      {editandoMarkup?.comp_id === brand.comp_id && editandoMarkup?.brand_id === brand.brand_id ? (
                        <div className={styles.actions}>
                          <button
                            onClick={() => guardarMarkup(brand)}
                            className={`${styles.btn} ${styles.btnSave}`}
                            title="Guardar (Enter)"
                          >
                            ✓
                          </button>
                          <button
                            onClick={cancelarEdicion}
                            className={`${styles.btn} ${styles.btnCancel}`}
                            title="Cancelar (Esc)"
                          >
                            ✕
                          </button>
                        </div>
                      ) : (
                        <div className={styles.actions}>
                          <button
                            onClick={() => iniciarEdicion(brand)}
                            className={`${styles.btn} ${styles.btnEdit}`}
                            title="Editar markup"
                          >
                            ✏️
                          </button>
                          {brand.markup_id && (
                            <button
                              onClick={() => eliminarMarkup(brand)}
                              className={`${styles.btn} ${styles.btnDelete}`}
                              title="Eliminar markup"
                            >
                              🗑️
                            </button>
                          )}
                        </div>
                      )}
                    </td>
                  </tr>
                ))
              )}
            </tbody>
          </table>
        </div>
      )}

      {/* Toast */}
      {toast && (
        <div className={`${styles.toast} ${styles[`toast${toast.tipo === 'success' ? 'Success' : 'Error'}`]}`}>
          {toast.tipo === 'success' ? '✓' : '✕'} {toast.mensaje}
        </div>
      )}
    </div>
  );
}
