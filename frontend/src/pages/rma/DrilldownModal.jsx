/**
 * DrilldownModal.jsx
 *
 * Tesla-pattern modal for the RMA drill-down view.
 * Fetches GET /rma-seguimiento/stats/drill-down and renders:
 *   - Equipos table: serial_number | ean | producto_desc | numero_caso
 *   - Expandable status timeline per row (from rma_caso_historial)
 *
 * RULE: closes ONLY via the X button or "Cerrar" — no overlay click-to-close.
 *
 * Props:
 *   selectedSegment  {{ dimension: string, valor: string, bucket: object }}
 *   dateField        {'fecha_caso'|'recepcion_fecha'}
 *   dateFrom         {string}  YYYY-MM-DD
 *   dateTo           {string}  YYYY-MM-DD
 *   proveedorTopN    {number}  default 8
 *   onClose          {Function}
 */
import { useState } from 'react';
import { useQuery } from '@tanstack/react-query';
import { X, ChevronDown, ChevronUp, Clock, ArrowRight } from 'lucide-react';
import api from '../../services/api';
import styles from './DrilldownModal.module.css';

const DIMENSION_LABELS = {
  estado_recepcion: 'Estado Recepción',
  causa_devolucion: 'Causa Devolución',
  apto_venta: 'Apto para Venta',
  estado_proceso: 'Estado Proceso',
  estado_proveedor: 'Estado Proveedor',
  proveedor: 'Proveedor',
};

const FIELD_LABELS = {
  estado_recepcion_id: 'Estado Recepción',
  causa_devolucion_id: 'Causa Devolución',
  apto_venta_id: 'Apto Venta',
  estado_revision_id: 'Estado Revisión',
  estado_proceso_id: 'Estado Proceso',
  estado_proveedor_id: 'Estado Proveedor',
  estado_caso_id: 'Estado Caso',
};

function TimelineEvent({ event }) {
  const fieldLabel = FIELD_LABELS[event.campo] || event.campo;
  const date = event.created_at
    ? new Date(event.created_at).toLocaleString('es-AR', {
        dateStyle: 'short',
        timeStyle: 'short',
      })
    : '—';

  return (
    <div className={styles.timelineEvent}>
      <Clock size={11} className={styles.timelineIcon} aria-hidden="true" />
      <span className={styles.timelineField}>{fieldLabel}</span>
      {event.valor_anterior && (
        <>
          <span className={styles.timelineFrom}>{event.valor_anterior}</span>
          <ArrowRight size={10} className={styles.timelineArrow} aria-hidden="true" />
        </>
      )}
      <span className={styles.timelineTo}>{event.valor_nuevo || '—'}</span>
      <span className={styles.timelineMeta}>
        {event.usuario_nombre && <span>{event.usuario_nombre}</span>}
        <span>{date}</span>
      </span>
    </div>
  );
}

function EquipoRow({ equipo }) {
  const [expanded, setExpanded] = useState(false);
  const hasTimeline = Array.isArray(equipo.timeline) && equipo.timeline.length > 0;

  return (
    <>
      <tr
        className={`${styles.equipoRow} ${hasTimeline ? styles.expandable : ''}`}
        onClick={() => hasTimeline && setExpanded((v) => !v)}
      >
        <td className={styles.cellMono}>{equipo.serial_number || '—'}</td>
        <td className={styles.cellMono}>{equipo.ean || '—'}</td>
        <td className={styles.cellDesc}>{equipo.producto_desc || '—'}</td>
        <td className={styles.cellCaso}>{equipo.numero_caso}</td>
        <td className={styles.cellExpand}>
          {hasTimeline && (
            <button
              className={styles.expandBtn}
              aria-label={expanded ? 'Ocultar timeline de estados' : 'Ver timeline de estados'}
              onClick={(e) => {
                e.stopPropagation();
                setExpanded((v) => !v);
              }}
            >
              {expanded ? <ChevronUp size={14} /> : <ChevronDown size={14} />}
            </button>
          )}
        </td>
      </tr>
      {expanded && hasTimeline && (
        <tr className={styles.timelineRow}>
          <td colSpan={5} className={styles.timelineCell}>
            <div className={styles.timeline}>
              {equipo.timeline.map((event, i) => (
                <TimelineEvent key={i} event={event} />
              ))}
            </div>
          </td>
        </tr>
      )}
    </>
  );
}

export default function DrilldownModal({
  selectedSegment,
  dateField,
  dateFrom,
  dateTo,
  proveedorTopN = 8,
  onClose,
}) {
  const { dimension, valor, bucket } = selectedSegment;

  const { data, isLoading, error } = useQuery({
    queryKey: [
      'rma-metrics-drilldown',
      dimension,
      valor,
      dateField,
      dateFrom,
      dateTo,
      proveedorTopN,
    ],
    queryFn: () =>
      api
        .get('/rma-seguimiento/stats/drill-down', {
          params: {
            dimension,
            valor,
            date_field: dateField,
            date_from: dateFrom,
            date_to: dateTo,
            proveedor_top_n: proveedorTopN,
          },
        })
        .then((r) => r.data),
    enabled: Boolean(dimension) && Boolean(valor),
  });

  const dimensionLabel = DIMENSION_LABELS[dimension] || dimension;
  const bucketLabel = bucket?.valor || valor;
  const equiposCount = data?.equipos?.length ?? 0;

  return (
    <div className="modal-overlay-tesla">
      <div className={`modal-tesla lg ${styles.modal}`}>

        {/* Header */}
        <div className="modal-header-tesla">
          <div>
            <h2 className="modal-title-tesla">
              {dimensionLabel}:{' '}
              <em className={styles.bucketLabel}>{bucketLabel}</em>
            </h2>
            {data && (
              <p className="modal-subtitle-tesla">
                {equiposCount} equipo{equiposCount !== 1 ? 's' : ''} en el período
              </p>
            )}
          </div>
          <button
            className="btn-close-tesla"
            onClick={onClose}
            aria-label="Cerrar modal"
          >
            <X size={18} />
          </button>
        </div>

        {/* Body */}
        <div className="modal-body-tesla compact">
          {isLoading && (
            <div className={styles.stateMsg}>Cargando equipos...</div>
          )}

          {error && !isLoading && (
            <div className={styles.stateError}>
              Error al cargar el detalle. Intentá de nuevo.
            </div>
          )}

          {data && equiposCount === 0 && (
            <div className={styles.stateMsg}>
              No hay equipos para este filtro en el período seleccionado.
            </div>
          )}

          {data && equiposCount > 0 && (
            <div className="table-container-tesla">
              <table className="table-tesla striped">
                <thead className="table-tesla-head">
                  <tr>
                    <th>Serie</th>
                    <th>EAN</th>
                    <th>Producto</th>
                    <th>Caso</th>
                    <th style={{ width: '40px' }} aria-label="Timeline" />
                  </tr>
                </thead>
                <tbody className="table-tesla-body">
                  {data.equipos.map((equipo) => (
                    <EquipoRow key={equipo.item_id} equipo={equipo} />
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </div>

        {/* Footer */}
        <div className="modal-footer-tesla">
          <button className="btn-tesla secondary" onClick={onClose}>
            Cerrar
          </button>
        </div>
      </div>
    </div>
  );
}
