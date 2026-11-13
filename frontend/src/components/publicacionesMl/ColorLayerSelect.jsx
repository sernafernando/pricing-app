import { useEffect, useId, useRef, useState } from 'react';
import { ChevronDown } from 'lucide-react';
import { apiErrorMessage } from '../../utils/apiErrorMessage';
import { defaultLayer, showsGlobalReference } from './layerPreferences';
import styles from './ColorLayerSelect.module.css';

/**
 * The color layer the rows are painted with (S8): the global one ('') or one of the user's teams, the same layers
 * Productos paints; `equipos` / `loaded` are `useEquipos`' (the page shares them with F6/F7). Hidden while the user
 * has no team: the global layer is all there is. A team the user is not in (a link someone else shared) is dropped
 * once the teams are known: the backend refuses it with a 403.
 *
 * Its panel also holds the user's own preferences per layer (pubml-capa-default S2-S3), saved with
 * `onPreferences(equipoId, { por_defecto | mostrar_referencia_global })`: the tick of the layer the page opens on
 * (one; with no team ticked it is Global's, which cannot be unticked: tick another layer instead) and, on each team,
 * whether the global color reference shows on its rows.
 */
export default function ColorLayerSelect({ value, onChange, equipos, loaded, labelClassName, onPreferences }) {
  const [open, setOpen] = useState(false);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState(null);
  const containerRef = useRef(null);
  const triggerRef = useRef(null);
  const panelId = useId();
  const radioName = useId();
  const teams = equipos.filter((equipo) => !equipo.es_global);
  const globalTeam = equipos.find((equipo) => equipo.es_global);
  const unknown = loaded && value !== '' && !teams.some((equipo) => String(equipo.id) === value);
  const chosenDefault = defaultLayer(equipos);

  useEffect(() => {
    if (unknown) onChange('');
  }, [unknown, onChange]);

  useEffect(() => {
    if (!open) return undefined;
    const closeOutside = (event) => {
      if (containerRef.current && !containerRef.current.contains(event.target)) setOpen(false);
    };
    document.addEventListener('mousedown', closeOutside);
    return () => document.removeEventListener('mousedown', closeOutside);
  }, [open]);

  if (teams.length === 0 && !value) return null;

  const layers = [
    { layer: '', id: globalTeam?.id, nombre: 'Global' },
    ...teams.map((equipo) => ({ layer: String(equipo.id), id: equipo.id, nombre: equipo.nombre })),
  ];
  const current = layers.find((option) => option.layer === value) ?? layers[0];

  const save = async (id, preferences) => {
    if (id == null || !onPreferences) return;
    setSaving(true);
    setError(null);
    try {
      await onPreferences(id, preferences);
    } catch (err) {
      setError(apiErrorMessage(err, 'No se pudo guardar la preferencia'));
    } finally {
      setSaving(false);
    }
  };

  const close = () => {
    setOpen(false);
    triggerRef.current?.focus();
  };

  return (
    <div className={styles.layer} ref={containerRef}>
      <span className={labelClassName}>Capa</span>
      <div className={styles.anchor}>
        <button
          ref={triggerRef}
          type="button"
          className={styles.trigger}
          aria-label={`Capa de color: ${current.nombre}`}
          aria-haspopup="dialog"
          aria-expanded={open}
          aria-controls={open ? panelId : undefined}
          title="Capa de color por equipo"
          onClick={() => setOpen((was) => !was)}
        >
          <span className={styles.triggerText}>{current.nombre}</span>
          <ChevronDown size={14} aria-hidden="true" />
        </button>
        {open && (
          <div
            id={panelId}
            role="dialog"
            aria-label="Capas de color"
            className={styles.panel}
            onKeyDown={(event) => {
              if (event.key === 'Escape') {
                event.stopPropagation();
                close();
              }
            }}
          >
            <div className={styles.head} aria-hidden="true">
              <span>Capa</span>
              <span>Al entrar</span>
              <span>Ref. global</span>
            </div>
            {layers.map((option) => {
              const isDefault = option.layer === chosenDefault;
              return (
                <div key={option.layer || 'global'} className={styles.row} data-current={option.layer === value || undefined}>
                  <label className={styles.pick}>
                    <input
                      type="radio"
                      name={radioName}
                      checked={option.layer === value}
                      onChange={() => {
                        onChange(option.layer);
                        close();
                      }}
                    />
                    <span>{option.nombre}</span>
                  </label>
                  <input
                    type="checkbox"
                    className={styles.tick}
                    aria-label={`Abrir en ${option.nombre} al entrar`}
                    title={option.layer === '' && isDefault ? 'Para cambiarla, tildá otra capa' : 'Capa con la que abre la página'}
                    checked={isDefault}
                    disabled={saving || (option.layer === '' && isDefault)}
                    onChange={(event) => save(option.id, { por_defecto: event.target.checked })}
                  />
                  {option.layer === '' ? (
                    <span aria-hidden="true" />
                  ) : (
                    <input
                      type="checkbox"
                      className={styles.tick}
                      aria-label={`Ver la referencia de color global en ${option.nombre}`}
                      title="Marca, en las filas sin color del equipo, el color global"
                      checked={showsGlobalReference(equipos, option.layer)}
                      disabled={saving}
                      onChange={(event) => save(option.id, { mostrar_referencia_global: event.target.checked })}
                    />
                  )}
                </div>
              );
            })}
            {error && (
              <p className={styles.error} role="alert">
                {error}
              </p>
            )}
          </div>
        )}
      </div>
    </div>
  );
}
