import { RotateCcw, Ban, Pencil, Trash2, HelpCircle, X } from 'lucide-react';
import { extractPlaceholders } from '../hooks/usePlaceholders';
import styles from '../pages/RRHHSanciones.module.css';

/**
 * Modal de configuración de sanciones con 2 tabs: Tipos y Textos predefinidos.
 */
export default function SancionesConfigModal({ config, knownPlaceholders, onShowPlaceholderHelp }) {
  const {
    closeConfigModal,
    configTab, setConfigTab,
    tiposSancion,
    editingTipo, tipoForm, setTipoForm, tipoSaving, tipoError,
    openEditTipo, openNewTipo, handleSaveTipo, handleToggleTipoActivo,
    textosPredefinidos, textosPredLoading,
    editingTexto, textoForm, setTextoForm, textoSaving, textoError,
    deleteConfirmTexto, setDeleteConfirmTexto,
    openEditTexto, openNewTexto, handleSaveTexto, handleDeleteTexto,
  } = config;

  return (
    <>
      <div className="modal-overlay-tesla">
        <div className="modal-tesla lg" onClick={(e) => e.stopPropagation()}>
          <div className="modal-header-tesla">
            <h2 className="modal-title-tesla">Configurar sanciones</h2>
            <button className="btn-close-tesla" onClick={closeConfigModal} aria-label="Cerrar modal">
              <X size={14} />
            </button>
          </div>
          <div className="modal-body-tesla">
            {/* Tabs */}
            <div className={styles.configTabs}>
              <button
                className={configTab === 'tipos' ? styles.configTabActive : styles.configTab}
                onClick={() => setConfigTab('tipos')}
              >
                Tipos de sancion
              </button>
              <button
                className={configTab === 'textos' ? styles.configTabActive : styles.configTab}
                onClick={() => setConfigTab('textos')}
              >
                Textos predefinidos
              </button>
            </div>

            {/* Tab: Tipos */}
            {configTab === 'tipos' && (
              <div className={styles.tabContent}>
                <table className={styles.table}>
                  <thead>
                    <tr>
                      <th>Orden</th>
                      <th>Nombre</th>
                      <th>Descuento</th>
                      <th>Estado</th>
                      <th>Acciones</th>
                    </tr>
                  </thead>
                  <tbody>
                    {tiposSancion.map((t) => (
                      <tr key={t.id} className={t.activo ? undefined : styles.rowInactive}>
                        <td>{t.orden}</td>
                        <td>{t.nombre}</td>
                        <td>{t.requiere_descuento ? 'Si' : 'No'}</td>
                        <td>
                          <span className={t.activo ? styles.statusActiva : styles.statusAnulada}>
                            {t.activo ? 'Activo' : 'Inactivo'}
                          </span>
                        </td>
                        <td>
                          <div className={styles.actions}>
                            <button className={styles.btnView} onClick={() => openEditTipo(t)} title="Editar">
                              <Pencil size={14} />
                            </button>
                            <button
                              className={t.activo ? styles.btnAnular : styles.btnView}
                              onClick={() => handleToggleTipoActivo(t)}
                              title={t.activo ? 'Desactivar' : 'Activar'}
                            >
                              {t.activo ? <Ban size={14} /> : <RotateCcw size={14} />}
                            </button>
                          </div>
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
                <div className={styles.configForm}>
                  <h3 className={styles.configFormTitle}>
                    {editingTipo ? `Editar: ${editingTipo.nombre}` : 'Nuevo tipo de sancion'}
                  </h3>
                  <div className={styles.formRow}>
                    <div className={styles.formGroup}>
                      <label>Nombre</label>
                      <input type="text" className={styles.input} value={tipoForm.nombre} onChange={(e) => setTipoForm({ ...tipoForm, nombre: e.target.value })} placeholder="Ej: Apercibimiento" />
                    </div>
                    <div className={styles.formGroup}>
                      <label>Orden</label>
                      <input type="number" className={styles.input} value={tipoForm.orden} onChange={(e) => setTipoForm({ ...tipoForm, orden: Number(e.target.value) })} min={0} />
                    </div>
                  </div>
                  <div className={styles.formGroup}>
                    <label>Descripcion</label>
                    <input type="text" className={styles.input} value={tipoForm.descripcion} onChange={(e) => setTipoForm({ ...tipoForm, descripcion: e.target.value })} placeholder="Descripcion breve" />
                  </div>
                  <label className={styles.checkboxLabel}>
                    <input type="checkbox" checked={tipoForm.requiere_descuento} onChange={(e) => setTipoForm({ ...tipoForm, requiere_descuento: e.target.checked })} />
                    Requiere descuento salarial
                  </label>
                  {tipoError && <div className={styles.formError}>{tipoError}</div>}
                  <div className={styles.configFormActions}>
                    {editingTipo && <button className={styles.btnCancel} onClick={openNewTipo}>Cancelar edicion</button>}
                    <button className={styles.btnSave} onClick={handleSaveTipo} disabled={tipoSaving}>
                      {tipoSaving ? 'Guardando...' : editingTipo ? 'Guardar cambios' : 'Crear tipo'}
                    </button>
                  </div>
                </div>
              </div>
            )}

            {/* Tab: Textos predefinidos */}
            {configTab === 'textos' && (
              <div className={styles.tabContent}>
                {textosPredLoading ? (
                  <div className={styles.loading}>Cargando textos...</div>
                ) : (
                  <table className={styles.table}>
                    <thead>
                      <tr>
                        <th>Orden</th>
                        <th>Nombre</th>
                        <th>Placeholders</th>
                        <th>Estado</th>
                        <th>Acciones</th>
                      </tr>
                    </thead>
                    <tbody>
                      {textosPredefinidos.map((t) => (
                        <tr key={t.id} className={t.activo ? undefined : styles.rowInactive}>
                          <td>{t.orden}</td>
                          <td>{t.nombre}</td>
                          <td>
                            <div className={styles.phBadges}>
                              {extractPlaceholders(t.texto).map((ph) => (
                                <code key={ph} className={ph in knownPlaceholders ? styles.phKnown : styles.phCustom}>
                                  {ph}
                                </code>
                              ))}
                              {extractPlaceholders(t.texto).length === 0 && <span className={styles.hintSmall}>sin placeholders</span>}
                            </div>
                          </td>
                          <td>
                            <span className={t.activo ? styles.statusActiva : styles.statusAnulada}>
                              {t.activo ? 'Activo' : 'Inactivo'}
                            </span>
                          </td>
                          <td>
                            <div className={styles.actions}>
                              <button className={styles.btnView} onClick={() => openEditTexto(t)} title="Editar">
                                <Pencil size={14} />
                              </button>
                              {t.activo && (
                                <button className={styles.btnAnular} onClick={() => setDeleteConfirmTexto(t)} title="Desactivar">
                                  <Trash2 size={14} />
                                </button>
                              )}
                            </div>
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                )}
                <div className={styles.configForm}>
                  <h3 className={styles.configFormTitle}>
                    {editingTexto ? `Editar: ${editingTexto.nombre}` : 'Nuevo texto predefinido'}
                  </h3>
                  <div className={styles.formRow}>
                    <div className={styles.formGroup}>
                      <label>Nombre / Motivo</label>
                      <input type="text" className={styles.input} value={textoForm.nombre} onChange={(e) => setTextoForm({ ...textoForm, nombre: e.target.value })} placeholder="Ej: Llegada tarde" />
                    </div>
                    <div className={styles.formGroup}>
                      <label>Orden</label>
                      <input type="number" className={styles.input} value={textoForm.orden} onChange={(e) => setTextoForm({ ...textoForm, orden: Number(e.target.value) })} min={0} />
                    </div>
                  </div>
                  <div className={styles.formGroup}>
                    <div className={styles.labelRow}>
                      <label>Texto con placeholders</label>
                      <button type="button" className={styles.btnHelp} onClick={onShowPlaceholderHelp} title="Ver placeholders disponibles">
                        <HelpCircle size={14} />
                      </button>
                    </div>
                    <textarea
                      className={styles.textarea}
                      value={textoForm.texto}
                      onChange={(e) => setTextoForm({ ...textoForm, texto: e.target.value })}
                      rows={6}
                      placeholder="Ej: Se notifica a {nombre_empleado} legajo {legajo} que..."
                    />
                    {textoForm.texto && (
                      <div className={styles.placeholderPreview}>
                        <span className={styles.previewLabel}>Placeholders detectados:</span>
                        {extractPlaceholders(textoForm.texto).map((ph) => (
                          <code key={ph} className={ph in knownPlaceholders ? styles.phKnown : styles.phCustom}>
                            {`{${ph}}`}
                          </code>
                        ))}
                        {extractPlaceholders(textoForm.texto).length === 0 && (
                          <span className={styles.hintSmall}>
                            Ninguno. Usa {'{nombre}'} para agregar.
                          </span>
                        )}
                      </div>
                    )}
                  </div>
                  {textoError && <div className={styles.formError}>{textoError}</div>}
                  <div className={styles.configFormActions}>
                    {editingTexto && <button className={styles.btnCancel} onClick={openNewTexto}>Cancelar edicion</button>}
                    <button className={styles.btnSave} onClick={handleSaveTexto} disabled={textoSaving}>
                      {textoSaving ? 'Guardando...' : editingTexto ? 'Guardar cambios' : 'Crear texto'}
                    </button>
                  </div>
                </div>
              </div>
            )}
          </div>
          <div className="modal-footer-tesla">
            <button className={styles.btnCancel} onClick={closeConfigModal}>
              Cerrar
            </button>
          </div>
        </div>
      </div>

      {/* Delete confirm texto modal */}
      {deleteConfirmTexto && (
        <div className="modal-overlay-tesla">
          <div className="modal-tesla" onClick={(e) => e.stopPropagation()}>
            <div className="modal-header-tesla">
              <h2 className="modal-title-tesla">Desactivar texto predefinido</h2>
              <button className="btn-close-tesla" onClick={() => setDeleteConfirmTexto(null)} aria-label="Cerrar modal"><X size={14} /></button>
            </div>
            <div className="modal-body-tesla">
              <p className={styles.hintText}>
                Se desactivara el texto <strong>{deleteConfirmTexto.nombre}</strong>. Las sanciones existentes que lo usen no se veran afectadas.
              </p>
            </div>
            <div className="modal-footer-tesla">
              <button className={styles.btnCancel} onClick={() => setDeleteConfirmTexto(null)}>Cancelar</button>
              <button className={styles.btnAnular} onClick={handleDeleteTexto}>Desactivar</button>
            </div>
          </div>
        </div>
      )}
    </>
  );
}
