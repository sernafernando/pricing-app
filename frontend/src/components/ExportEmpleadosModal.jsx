import { useState } from 'react';
import { X, FileSpreadsheet } from 'lucide-react';
import { rrhhAPI } from '../services/api';
import styles from './ExportEmpleadosModal.module.css';

const EXPORT_CATEGORIES = [
  { key: 'datos_personales', label: 'Datos personales', desc: 'Nombre, DNI, CUIL, fecha nac., teléfono, email, emergencia' },
  { key: 'datos_laborales', label: 'Datos laborales', desc: 'Legajo, puesto, área, estado, fechas ingreso/egreso' },
  { key: 'direccion', label: 'Dirección', desc: 'Calle, número, localidad, provincia, CP' },
  { key: 'datos_bancarios', label: 'Datos bancarios', desc: 'Banco, CBU, alias, tipo cuenta, nro. cuenta' },
  { key: 'baja', label: 'Baja', desc: 'Motivo de baja, detalle' },
];

const ALL_CHECKED = EXPORT_CATEGORIES.reduce((acc, cat) => ({ ...acc, [cat.key]: true }), {});

export default function ExportEmpleadosModal({ onClose, filtros }) {
  const [categorias, setCategorias] = useState({ ...ALL_CHECKED });
  const [exporting, setExporting] = useState(false);
  const [error, setError] = useState(null);

  const handleToggleAll = (checked) => {
    setCategorias(
      EXPORT_CATEGORIES.reduce((acc, cat) => ({ ...acc, [cat.key]: checked }), {}),
    );
  };

  const handleExport = async () => {
    const selected = Object.entries(categorias)
      .filter(([, v]) => v)
      .map(([k]) => k);

    if (selected.length === 0) {
      setError('Seleccioná al menos una categoría');
      return;
    }

    setExporting(true);
    setError(null);
    try {
      const params = { categorias: selected.join(',') };
      if (filtros?.estado) params.estado = filtros.estado;
      if (filtros?.area) params.area = filtros.area;
      if (filtros?.puesto) params.puesto = filtros.puesto;
      if (filtros?.search) params.search = filtros.search;

      const { data } = await rrhhAPI.exportarEmpleadosExcel(params);
      const url = window.URL.createObjectURL(data);
      const link = document.createElement('a');
      link.href = url;
      link.download = `empleados_${new Date().toISOString().slice(0, 10)}.xlsx`;
      link.click();
      window.URL.revokeObjectURL(url);
      onClose();
    } catch (err) {
      setError(err.response?.data?.detail || 'Error al exportar');
    } finally {
      setExporting(false);
    }
  };

  return (
    <div className="modal-overlay-tesla">
      <div className="modal-tesla">
        <div className="modal-header-tesla">
          <h2 className="modal-title-tesla">Exportar empleados a Excel</h2>
          <button className="btn-close-tesla" onClick={onClose} aria-label="Cerrar"><X size={14} /></button>
        </div>
        <div className="modal-body-tesla">
          <p className={styles.hint}>
            Seleccioná las categorías de datos a incluir en la exportación.
            Se aplicarán los filtros activos (estado, área, puesto, búsqueda).
          </p>

          {error && <div className={styles.error}>{error}</div>}

          <div className={styles.categories}>
            <label className={styles.categoryAll}>
              <input
                type="checkbox"
                checked={Object.values(categorias).every(Boolean)}
                onChange={(e) => handleToggleAll(e.target.checked)}
              />
              <strong>Todas las categorías</strong>
            </label>

            {EXPORT_CATEGORIES.map((cat) => (
              <label key={cat.key} className={styles.categoryItem}>
                <input
                  type="checkbox"
                  checked={categorias[cat.key]}
                  onChange={(e) => setCategorias((prev) => ({ ...prev, [cat.key]: e.target.checked }))}
                />
                <div>
                  <strong>{cat.label}</strong>
                  <span className={styles.categoryDesc}>{cat.desc}</span>
                </div>
              </label>
            ))}
          </div>
        </div>
        <div className="modal-footer-tesla">
          <button className={styles.btnCancel} onClick={onClose}>Cancelar</button>
          <button
            className={styles.btnExport}
            onClick={handleExport}
            disabled={exporting}
          >
            <FileSpreadsheet size={14} />
            {exporting ? 'Exportando...' : 'Exportar'}
          </button>
        </div>
      </div>
    </div>
  );
}
