/**
 * Shared resizable-table chrome for the ml-bot panel's four TanStack-backed
 * tables (Preguntas / Historial / Mensajes / Pendientes) — extracted in PR4
 * (ml-bot-panel-operador, design ADR-3) from the block that used to be
 * duplicated verbatim four times: the "Restablecer columnas" bar, the
 * `<table>` + `style={{ width: table.getTotalSize() }}` + `<colgroup>` +
 * `<thead>` + `getFlatHeaders()` + resize-grip `<span>`.
 *
 * `children` is the `<tbody>` (or, for Mensajes, more than one `<tbody>`
 * depending on loading state) — row/cell logic is NOT touched by this
 * extraction, it stays at each call site.
 */
import { flexRender } from '@tanstack/react-table';
import styles from '../../pages/MLQuestions.module.css';

export function ResizableTableShell({ table, hasCustomSizing, onResetSizing, striped = true, children }) {
  return (
    <>
      {hasCustomSizing && (
        <div className={styles.columnSizingBar}>
          <button type="button" className="btn-tesla ghost sm" onClick={onResetSizing}>
            Restablecer columnas
          </button>
        </div>
      )}

      <div className="table-container-tesla">
        <table
          className={striped ? `table-tesla striped ${styles.resizableTable}` : `table-tesla ${styles.resizableTable}`}
          style={{ width: table.getTotalSize() }}
        >
          <colgroup>
            {table.getVisibleLeafColumns().map((col) => (
              <col key={col.id} style={{ width: col.getSize() }} />
            ))}
          </colgroup>
          <thead className="table-tesla-head">
            <tr>
              {table.getFlatHeaders().map((h) => (
                <th key={h.id} style={{ position: 'relative' }}>
                  {flexRender(h.column.columnDef.header, h.getContext())}
                  {h.column.getCanResize() && (
                    <span
                      className={`${styles.resizeGrip} ${h.column.getIsResizing() ? styles.resizeGripActive : ''}`}
                      onMouseDown={h.getResizeHandler()}
                      onTouchStart={h.getResizeHandler()}
                      role="separator"
                      aria-orientation="vertical"
                      aria-label={`Redimensionar columna ${h.column.columnDef.header}`}
                    />
                  )}
                </th>
              ))}
            </tr>
          </thead>
          {children}
        </table>
      </div>
    </>
  );
}
