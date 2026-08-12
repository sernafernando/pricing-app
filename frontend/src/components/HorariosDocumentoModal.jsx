/**
 * HorariosDocumentoModal — genera el REGISTRO DE HORARIOS imprimible.
 *
 * Un PDF con un registro por empleado seleccionado, para entregar junto con el
 * recibo de sueldo. Un rango de un mes entra en una página; los más largos los
 * pagina pdfme solo. Los datos salen de
 * `GET /api/rrhh/reportes/horarios-documento` y el PDF lo arma pdfme en el
 * browser vía `useDocumentGenerator`.
 *
 * Props:
 *   isOpen      - boolean
 *   onClose     - function
 *   empleados   - array de empleados de la página ({ id, legajo, nombre, apellido })
 *   fechaDesde  - string YYYY-MM-DD, rango actual de la página
 *   fechaHasta  - string YYYY-MM-DD
 */
import { useEffect, useState } from 'react';
import { AlertCircle, FileDown, Loader2, Search } from 'lucide-react';
import { rrhhAPI } from '../services/api';
import { useDocumentGenerator } from '../hooks/useDocumentGenerator';
import { withOptionalLastColumn } from '../utils/pdfmeTableColumns';
import ModalTesla from './ModalTesla';
import EmpleadoMultiSelect from './EmpleadoMultiSelect';
import styles from './HorariosDocumentoModal.module.css';

export const CONTEXTO = 'horarios_empleado';

const detalleDeError = (err, fallback) => {
  const detail = err?.response?.data?.detail;
  return typeof detail === 'string' ? detail : fallback;
};

export default function HorariosDocumentoModal({
  isOpen,
  onClose,
  empleados = [],
  fechaDesde,
  fechaHasta,
}) {
  const { templates, loading: loadingTemplates, generating, error: errorPdf, fetchTemplates, generatePdf } =
    useDocumentGenerator(CONTEXTO);

  const [seleccionados, setSeleccionados] = useState([]);
  const [desde, setDesde] = useState(fechaDesde || '');
  const [hasta, setHasta] = useState(fechaHasta || '');
  const [incluirHoras, setIncluirHoras] = useState(true);
  const [templateId, setTemplateId] = useState('');
  const [cargandoDatos, setCargandoDatos] = useState(false);
  const [errorDatos, setErrorDatos] = useState(null);

  // Al abrir: templates frescos y el rango que el usuario ya tenía en pantalla.
  useEffect(() => {
    if (!isOpen) return;
    fetchTemplates();
    setDesde(fechaDesde || '');
    setHasta(fechaHasta || '');
    setSeleccionados([]);
    setErrorDatos(null);
  }, [isOpen, fechaDesde, fechaHasta, fetchTemplates]);

  // Derivado, no estado: con un solo template no hay nada que elegir.
  const templateElegido = templateId || (templates.length === 1 ? String(templates[0].id) : '');

  const handleGenerar = async () => {
    setErrorDatos(null);

    if (!templateElegido) {
      setErrorDatos('Elegí un template para generar el documento');
      return;
    }

    setCargandoDatos(true);
    try {
      const { data } = await rrhhAPI.reporteHorariosDocumento({
        fecha_desde: desde,
        fecha_hasta: hasta,
        empleado_ids: seleccionados,
      });
      const filas = data?.empleados || [];

      if (filas.length === 0) {
        setErrorDatos('El rango elegido no devolvió días para esos empleados');
        return;
      }

      // Sin tope de días: el template declara UNA tabla y pdfme la pagina
      // solo. Un rango de tres meses sale como un documento de varias páginas
      // en vez de rebotar.
      await generatePdf(
        Number(templateElegido),
        filas.map((e) => ({
          ...e,
          fecha_desde: data.fecha_desde,
          fecha_hasta: data.fecha_hasta,
          incluir_horas: incluirHoras,
        })),
        { transformTemplate: (template) => withOptionalLastColumn(template, incluirHoras) }
      );
    } catch (err) {
      setErrorDatos(detalleDeError(err, 'Error al obtener los horarios'));
    } finally {
      setCargandoDatos(false);
    }
  };

  const ocupado = cargandoDatos || generating;
  const error = errorDatos || errorPdf;

  return (
    <ModalTesla
      isOpen={isOpen}
      onClose={onClose}
      title="Registro de horarios"
      subtitle="Un registro por empleado, para entregar con el recibo de sueldo"
      size="lg"
      closeOnOverlay={false}
      footer={
        <div className={styles.footer}>
          <button type="button" className="btn-tesla ghost" onClick={onClose} disabled={ocupado}>
            Cancelar
          </button>
          <button
            type="button"
            className="btn-tesla outline-subtle-primary"
            onClick={handleGenerar}
            disabled={ocupado || seleccionados.length === 0}
          >
            {ocupado ? <Loader2 size={14} className={styles.spin} /> : <FileDown size={14} />}
            {ocupado ? 'Generando...' : `Generar (${seleccionados.length})`}
          </button>
        </div>
      }
    >
      <div className={styles.container}>
        <div className={styles.rango}>
          <div className={styles.field}>
            <label className={styles.fieldLabel} htmlFor="horarios-desde">
              Fecha desde
            </label>
            <input
              id="horarios-desde"
              className={styles.input}
              type="date"
              value={desde}
              onChange={(e) => setDesde(e.target.value)}
            />
          </div>
          <div className={styles.field}>
            <label className={styles.fieldLabel} htmlFor="horarios-hasta">
              Fecha hasta
            </label>
            <input
              id="horarios-hasta"
              className={styles.input}
              type="date"
              value={hasta}
              onChange={(e) => setHasta(e.target.value)}
            />
          </div>
        </div>

        <EmpleadoMultiSelect
          empleados={empleados}
          seleccionados={seleccionados}
          onChange={setSeleccionados}
          icono={<Search size={14} />}
        />

        <label className={styles.checkboxRow}>
          <input
            type="checkbox"
            checked={incluirHoras}
            onChange={(e) => setIncluirHoras(e.target.checked)}
          />
          Incluir cuenta de horas diaria
        </label>

        {templates.length > 1 && (
          <div className={styles.field}>
            <label className={styles.fieldLabel} htmlFor="horarios-template">
              Template
            </label>
            <select
              id="horarios-template"
              className={styles.select}
              value={templateElegido}
              onChange={(e) => setTemplateId(e.target.value)}
            >
              <option value="">Seleccionar template...</option>
              {templates.map((t) => (
                <option key={t.id} value={t.id}>
                  {t.nombre}
                </option>
              ))}
            </select>
          </div>
        )}

        {loadingTemplates && (
          <p className={styles.hint}>
            <Loader2 size={14} className={styles.spin} /> Cargando templates...
          </p>
        )}
        {!loadingTemplates && templates.length === 0 && (
          <p className={styles.hint}>
            No hay templates activos para este documento. Un usuario con permiso de diseño tiene que
            crear uno.
          </p>
        )}

        {error && (
          <div className={styles.error} role="alert">
            <AlertCircle size={16} />
            <span>{error}</span>
          </div>
        )}
      </div>
    </ModalTesla>
  );
}
