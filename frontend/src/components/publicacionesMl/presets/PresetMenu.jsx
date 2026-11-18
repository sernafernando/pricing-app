import { useEffect, useId, useRef, useState } from 'react';
import { Check, ChevronDown, Pencil, Save, SlidersHorizontal, Trash2, Users } from 'lucide-react';
import ModalTesla, { ModalFooterButtons } from '../../ModalTesla';
import { normalizePresetParams, samePresetParams } from '../../../hooks/usePublicacionesMLFilters';
import styles from './PresetMenu.module.css';

const DEFAULT_NAME = 'Predeterminado';

/** What to tell the user when a preset write fails. */
function describeError(error) {
  const status = error?.response?.status;
  if (status === 409) return 'Ya existe un preset con ese nombre.';
  if (status === 403) return 'No tenés permiso para modificar presets compartidos.';
  if (status === 404) return 'El preset ya no existe.';
  if (status === 422) return 'El preset es demasiado grande o tiene datos inválidos.';
  return 'No se pudo guardar el preset.';
}

/** The name prompt of "Guardar como nuevo" and "Renombrar"; it closes only with its X or Cancelar. */
function NameModal({ title, initialName = '', canShare = false, onCancel, onSave }) {
  const nameId = useId();
  const [nombre, setNombre] = useState(initialName);
  const [compartido, setCompartido] = useState(false);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState(null);

  const save = async () => {
    setSaving(true);
    setError(null);
    try {
      await onSave({ nombre: nombre.trim(), compartido });
    } catch (err) {
      setError(describeError(err));
      setSaving(false);
    }
  };

  return (
    <ModalTesla
      isOpen
      onClose={saving ? () => {} : onCancel}
      title={title}
      size="sm"
      closeOnOverlay={false}
      closeOnEsc={false}
      footer={
        <ModalFooterButtons
          onCancel={onCancel}
          onConfirm={save}
          confirmText="Guardar"
          confirmLoading={saving}
          confirmDisabled={nombre.trim() === '' || nombre.trim().length > 60}
        />
      }
    >
      <div className={styles.form}>
        <label htmlFor={nameId} className={styles.fieldLabel}>
          Nombre
        </label>
        <input
          id={nameId}
          className={styles.input}
          value={nombre}
          maxLength={60}
          onChange={(event) => setNombre(event.target.value)}
          onKeyDown={(event) => {
            if (event.key === 'Enter' && nombre.trim() !== '' && !saving) save();
          }}
        />
        {canShare && (
          <fieldset className={styles.fieldset}>
            <legend className={styles.fieldLabel}>Visible para</legend>
            <label className={styles.radio}>
              <input type="radio" name={`${nameId}-alcance`} checked={!compartido} onChange={() => setCompartido(false)} />
              Personal
            </label>
            <label className={styles.radio}>
              <input type="radio" name={`${nameId}-alcance`} checked={compartido} onChange={() => setCompartido(true)} />
              Compartido
            </label>
            <p className={styles.help}>Un preset compartido lo ven todos los que entran a esta vista.</p>
          </fieldset>
        )}
        {error && (
          <p role="alert" className={styles.error}>
            {error}
          </p>
        )}
      </div>
    </ModalTesla>
  );
}

function DeleteModal({ preset, onCancel, onDelete }) {
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState(null);
  const confirm = async () => {
    setSaving(true);
    setError(null);
    try {
      await onDelete();
    } catch (err) {
      setError(describeError(err) === 'No se pudo guardar el preset.' ? 'No se pudo eliminar el preset.' : describeError(err));
      setSaving(false);
    }
  };
  return (
    <ModalTesla
      isOpen
      onClose={saving ? () => {} : onCancel}
      title="Eliminar preset"
      size="sm"
      closeOnOverlay={false}
      closeOnEsc={false}
      footer={<ModalFooterButtons onCancel={onCancel} onConfirm={confirm} confirmText="Eliminar" confirmLoading={saving} confirmVariant="danger" />}
    >
      <p>
        ¿Eliminar el preset <strong>{preset.nombre}</strong>?
        {preset.compartido ? ' Es compartido: deja de estar para todos.' : ''}
      </p>
      {error && (
        <p role="alert" className={styles.error}>
          {error}
        </p>
      )}
    </ModalTesla>
  );
}

/**
 * The column presets of the view, next to the column picker (pubml-columnas-presets S3, S6, S8). A preset is the
 * columns (visibility and order) plus the URL params of the list (`presetParams`: filters, sort, modo, agrupar,
 * familias, equipo). "Predeterminado" is built in: the view's default columns and no filters (`defaultParams`, the
 * user's default layer). The button names the active preset, marked "modificado" when the columns or the params on
 * screen differ from it.
 *
 * `presets` is `usePresets`, `view` the page's `layoutView` (its `presetId` is the active preset), `canShare` the
 * `ml_publicaciones.presets_compartidos` permission. `onApplied` is called after a preset sets the URL.
 */
export default function PresetMenu({
  presets,
  view,
  presetParams,
  applyPresetParams,
  defaultParams = {},
  canShare = false,
  onApplied,
  buttonClassName = 'btn-tesla outline sm',
}) {
  const popoverId = useId();
  const [open, setOpen] = useState(false);
  const [dialog, setDialog] = useState(null);
  const [error, setError] = useState(null);
  const containerRef = useRef(null);
  const triggerRef = useRef(null);

  useEffect(() => {
    if (!open) return undefined;
    function handleClickOutside(event) {
      if (containerRef.current && !containerRef.current.contains(event.target)) setOpen(false);
    }
    function handleKeyDown(event) {
      if (event.key === 'Escape') {
        setOpen(false);
        triggerRef.current?.focus();
      }
    }
    document.addEventListener('mousedown', handleClickOutside);
    document.addEventListener('keydown', handleKeyDown);
    return () => {
      document.removeEventListener('mousedown', handleClickOutside);
      document.removeEventListener('keydown', handleKeyDown);
    };
  }, [open]);

  const active = presets.items.find((preset) => preset.id === view.presetId) ?? null;
  const activeName = active?.nombre ?? DEFAULT_NAME;
  const modified = active
    ? !view.matches(active.payload?.columns) || !samePresetParams(presetParams, active.payload?.params)
    : !view.matches(null) || !samePresetParams(presetParams, defaultParams);
  const payload = () => ({ columns: view.current, params: normalizePresetParams(presetParams) });

  const apply = (preset) => {
    view.applyLayout(preset?.payload?.columns ?? null, preset?.id ?? null);
    applyPresetParams(preset ? (preset.payload?.params ?? {}) : defaultParams);
    onApplied?.();
    setOpen(false);
  };

  const openDialog = (next) => {
    setOpen(false);
    setError(null);
    setDialog(next);
  };

  const saveChanges = async () => {
    setError(null);
    try {
      await presets.update(active.id, { payload: payload() });
      setOpen(false);
    } catch (err) {
      setError(describeError(err));
    }
  };

  const saveNew = async ({ nombre, compartido }) => {
    const preset = await presets.create({ nombre, compartido: canShare && compartido, payload: payload() });
    view.setPresetId(preset.id);
    setDialog(null);
  };

  const rename = async (preset, { nombre }) => {
    await presets.update(preset.id, { nombre });
    setDialog(null);
  };

  const remove = async (preset) => {
    await presets.remove(preset.id);
    if (preset.id === view.presetId) view.setPresetId(null);
    setDialog(null);
  };

  const entries = [{ id: null, nombre: DEFAULT_NAME, builtIn: true }, ...presets.items];

  return (
    <div className={styles.container} ref={containerRef}>
      <button
        type="button"
        ref={triggerRef}
        className={`${buttonClassName} ${styles.trigger}`}
        aria-label={`Preset: ${activeName}${modified ? ' (modificado)' : ''}`}
        title="Presets de columnas y filtros"
        aria-expanded={open}
        aria-controls={popoverId}
        onClick={() => setOpen((prev) => !prev)}
      >
        <SlidersHorizontal size={14} aria-hidden="true" />
        <span className={styles.triggerLabel}>Preset:</span>
        <span className={styles.triggerName}>{activeName}</span>
        {modified && <span className={styles.modified}>modificado</span>}
        <ChevronDown size={12} aria-hidden="true" />
      </button>
      {open && (
        <div id={popoverId} className={styles.popover} role="dialog" aria-label="Presets">
          <p className={styles.title}>
            Preset activo: <span className={styles.activeName}>{activeName}</span>
            {modified && <span className={styles.modified}>modificado</span>}
          </p>
          <ul className={styles.list}>
            {entries.map((preset) => {
              const isActive = preset.builtIn ? !active : preset.id === active?.id;
              return (
                <li key={preset.id ?? 'default'} className={styles.item} data-active={isActive ? '' : undefined}>
                  <button
                    type="button"
                    className={styles.apply}
                    aria-label={`Aplicar ${preset.nombre}`}
                    aria-current={isActive ? 'true' : undefined}
                    onClick={() => apply(preset.builtIn ? null : preset)}
                  >
                    <span className={styles.check} aria-hidden="true">
                      {isActive && <Check size={14} />}
                    </span>
                    <span className={styles.name} title={preset.nombre}>{preset.nombre}</span>
                    {preset.compartido && (
                      <span className={styles.tag}>
                        <Users size={11} aria-hidden="true" />
                        Compartido
                      </span>
                    )}
                  </button>
                  {preset.editable && (
                    <>
                      <button
                        type="button"
                        className={styles.iconButton}
                        aria-label={`Renombrar ${preset.nombre}`}
                        title="Renombrar"
                        onClick={() => openDialog({ kind: 'rename', preset })}
                      >
                        <Pencil size={13} aria-hidden="true" />
                      </button>
                      <button
                        type="button"
                        className={styles.iconButton}
                        aria-label={`Eliminar ${preset.nombre}`}
                        title="Eliminar"
                        onClick={() => openDialog({ kind: 'delete', preset })}
                      >
                        <Trash2 size={13} aria-hidden="true" />
                      </button>
                    </>
                  )}
                </li>
              );
            })}
          </ul>
          {error && (
            <p role="alert" className={styles.error}>
              {error}
            </p>
          )}
          <div className={styles.actions}>
            {active?.editable && (
              <button type="button" className="btn-tesla outline-subtle-primary sm" disabled={!modified} onClick={saveChanges}>
                <Save size={14} aria-hidden="true" />
                Guardar cambios
              </button>
            )}
            <button type="button" className="btn-tesla ghost sm" onClick={() => openDialog({ kind: 'new' })}>
              Guardar como nuevo
            </button>
          </div>
        </div>
      )}
      {dialog?.kind === 'new' && (
        <NameModal title="Guardar como nuevo preset" canShare={canShare} onCancel={() => setDialog(null)} onSave={saveNew} />
      )}
      {dialog?.kind === 'rename' && (
        <NameModal
          title="Renombrar preset"
          initialName={dialog.preset.nombre}
          onCancel={() => setDialog(null)}
          onSave={(values) => rename(dialog.preset, values)}
        />
      )}
      {dialog?.kind === 'delete' && (
        <DeleteModal preset={dialog.preset} onCancel={() => setDialog(null)} onDelete={() => remove(dialog.preset)} />
      )}
    </div>
  );
}
