import { useEffect, useLayoutEffect, useRef, useState } from 'react';
import { FilterX, History, X } from 'lucide-react';
import api from '../../services/api';
import { EMPTY_AUDIT_FILTERS, activeAuditChips, hasAuditFilter, kindLabel } from './auditFilters';
import chipStyles from './ProductFilters.module.css';
import styles from './AuditFilters.module.css';

/** The URL's moment as a `datetime-local` value: a bare date is the whole day (from 00:00, or until 23:59). */
const inputMoment = (value, endOfDay) => {
  const moment = value.replace(' ', 'T');
  if (!moment || moment.includes('T')) return moment;
  return `${moment}T${endOfDay ? '23:59' : '00:00'}`;
};

// The room the panel keeps from the screen's right edge.
const PANEL_MARGIN = 16;

/**
 * The "Auditoría:" group of the Publicaciones ML filter card: Productos' "Filtros de Auditoría" (user who changed
 * the product, kind of change, date range), behind one button like the presence filters, so the card does not grow
 * a row. The users and kinds are asked when the panel opens, or when the URL already names a user (its chip needs
 * the name). One removable chip per active value and a control that clears them all stay in the row.
 *
 * @param {{filters: object, setFilters: (updates: object) => void, labelClassName?: string}} props
 */
export default function AuditFilters({ filters, setFilters, labelClassName }) {
  const [open, setOpen] = useState(false);
  const [options, setOptions] = useState(null);
  const containerRef = useRef(null);
  const panelRef = useRef(null);
  const needsOptions = open || filters.audit_usuarios.length > 0;

  useEffect(() => {
    if (!needsOptions || options) return undefined;
    let alive = true;
    Promise.all([api.get('/auditoria/usuarios'), api.get('/auditoria/tipos-accion')])
      .then(([users, kinds]) => {
        if (alive) setOptions({ users: users.data?.usuarios ?? [], kinds: kinds.data?.tipos ?? [] });
      })
      .catch(() => alive && setOptions({ users: [], kinds: [], failed: true }));
    return () => {
      alive = false;
    };
  }, [needsOptions, options]);

  // The panel opens from the button's left edge; near the screen's right edge it slides left just enough to stay in.
  useLayoutEffect(() => {
    const panel = panelRef.current;
    if (!open || !panel) return;
    panel.style.left = '';
    const overflow = panel.getBoundingClientRect().right - (document.documentElement.clientWidth - PANEL_MARGIN);
    if (overflow > 0) panel.style.left = `${-overflow}px`;
  }, [open, options]);

  useEffect(() => {
    if (!open) return undefined;
    const closeOutside = (event) => {
      if (containerRef.current && !containerRef.current.contains(event.target)) setOpen(false);
    };
    document.addEventListener('mousedown', closeOutside);
    return () => document.removeEventListener('mousedown', closeOutside);
  }, [open]);

  const closeOnEscape = (event) => {
    if (event.key === 'Escape' && open) {
      event.stopPropagation();
      setOpen(false);
    }
  };

  const usersById = Object.fromEntries((options?.users ?? []).map((user) => [String(user.id), user.nombre]));
  const chips = hasAuditFilter(filters) ? activeAuditChips(filters, usersById) : [];
  const toggle = (key, value) =>
    setFilters({
      [key]: filters[key].includes(value) ? filters[key].filter((v) => v !== value) : [...filters[key], value],
    });
  const label = chips.length > 0 ? `Filtros de auditoría (${chips.length} activos)` : 'Filtros de auditoría';

  return (
    <div className={chipStyles.group}>
      <span className={labelClassName}>Auditoría:</span>
      <div className={styles.anchor} ref={containerRef} onKeyDown={closeOnEscape}>
        <button
          type="button"
          className="btn-tesla outline sm"
          data-filter="auditoria"
          aria-expanded={open}
          aria-label={label}
          title={label}
          onClick={() => {
            // a failed load is asked again on the next opening
            if (options?.failed) setOptions(null);
            setOpen((was) => !was);
          }}
        >
          <History size={14} aria-hidden="true" />
          Auditoría
          {chips.length > 0 && <span className={styles.count}>{chips.length}</span>}
        </button>
        {open && (
          <div ref={panelRef} className={styles.panel} role="group" aria-label="Filtros de auditoría">
            {!options && <p className={styles.note}>Cargando…</p>}
            {options?.failed && <p className={styles.note}>No se pudieron cargar los usuarios y tipos.</p>}
            {options && !options.failed && (
              <>
                <fieldset className={styles.section}>
                  <legend className={styles.legend}>Usuario que modificó</legend>
                  <div className={styles.list}>
                    {options.users.map((user) => (
                      <label key={user.id} className={styles.option}>
                        <input
                          type="checkbox"
                          checked={filters.audit_usuarios.includes(String(user.id))}
                          onChange={() => toggle('audit_usuarios', String(user.id))}
                        />
                        {user.nombre}
                      </label>
                    ))}
                  </div>
                </fieldset>
                <fieldset className={styles.section}>
                  <legend className={styles.legend}>Tipo de modificación</legend>
                  <div className={styles.list}>
                    {options.kinds.map((kind) => (
                      <label key={kind} className={styles.option}>
                        <input
                          type="checkbox"
                          checked={filters.audit_tipos.includes(kind)}
                          onChange={() => toggle('audit_tipos', kind)}
                        />
                        {kindLabel(kind)}
                      </label>
                    ))}
                  </div>
                </fieldset>
              </>
            )}
            <fieldset className={styles.section}>
              <legend className={styles.legend}>Rango de fechas</legend>
              <label className={styles.date}>
                Desde
                <input
                  type="datetime-local"
                  className={styles.input}
                  value={inputMoment(filters.audit_desde, false)}
                  onChange={(event) => setFilters({ audit_desde: event.target.value })}
                />
              </label>
              <label className={styles.date}>
                Hasta
                <input
                  type="datetime-local"
                  className={styles.input}
                  value={inputMoment(filters.audit_hasta, true)}
                  onChange={(event) => setFilters({ audit_hasta: event.target.value })}
                />
              </label>
            </fieldset>
          </div>
        )}
      </div>
      {chips.length > 0 && (
        <ul className={chipStyles.chips} aria-label="Filtros de auditoría activos">
          {chips.map((chip) => (
            <li key={chip.id}>
              <button
                type="button"
                className={chipStyles.chip}
                aria-label={`Quitar ${chip.label}`}
                title={`Quitar ${chip.label}`}
                onClick={() => setFilters(chip.remove)}
              >
                {chip.label}
                <X size={12} aria-hidden="true" />
              </button>
            </li>
          ))}
          <li>
            <button type="button" className="btn-tesla ghost sm" onClick={() => setFilters(EMPTY_AUDIT_FILTERS)}>
              <FilterX size={14} aria-hidden="true" />
              Limpiar auditoría
            </button>
          </li>
        </ul>
      )}
    </div>
  );
}
