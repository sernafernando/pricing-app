import { useId, useState } from 'react';
import { X } from 'lucide-react';
import { StatusPill } from '../kit';
import { offsetGruposAPI } from '../../services/offsetGruposAPI';
import { apiErrorMessage } from '../../utils/apiErrorMessage';
import SellInBuscador from '../sellIn/SellInBuscador';
import { buscarProductos } from '../sellOut/sellOutBuscar';
import { NOTA_ALCANCE, productosTexto, resumenFiltro } from './grupoFormat';
import styles from '../sellIn/SellInPanel.module.css';
import own from './Grupos.module.css';

const FILTRO_VACIO = { marca: '', categoria: '', subcategoria_id: '', producto: null };

/**
 * One offset group in the side panel: name and description, its filter rows (add / remove), the products it
 * reaches and the campaigns using it, and delete. `grupo` null is a new group: "Crear grupo" calls `onCreado`.
 * Every change calls `onCambio` (the list and the preview are asked again). While an active campaign uses the
 * group, a filter change re-queues its money: the panel asks first, naming the campaigns and showing the products
 * reached before -> after (`alcancePrevio`, the same rule, nothing saved); without one it saves at once.
 */
export default function GrupoPanel({ grupo, opciones, subcategorias, onClose, onCreado, onCambio, onEliminado }) {
  const id = useId();
  const nuevo = !grupo;
  const [nombre, setNombre] = useState(grupo?.nombre ?? '');
  const [descripcion, setDescripcion] = useState(grupo?.descripcion ?? '');
  const [filtro, setFiltro] = useState(FILTRO_VACIO);
  const [error, setError] = useState(null);
  const [busy, setBusy] = useState(false);
  const [confirmando, setConfirmando] = useState(false);
  // `{ cambio, guardar, antes, despues }`: a filter change waiting for "Confirmar cambio".
  const [pendiente, setPendiente] = useState(null);
  const activas = (grupo?.campanas ?? []).filter((c) => c.estado === 'activa');

  const correr = async (accion, fallback) => {
    setBusy(true);
    setError(null);
    try {
      await accion();
    } catch (err) {
      setError(apiErrorMessage(err, fallback));
    } finally {
      setBusy(false);
    }
  };

  const guardarNombre = () =>
    correr(async () => {
      const body = { nombre: nombre.trim(), descripcion: descripcion.trim() || null };
      if (nuevo) {
        const { data } = await offsetGruposAPI.crear({ ...body, filtros: [] });
        onCreado(data);
      } else {
        await offsetGruposAPI.editar(grupo.id, body);
        await onCambio();
      }
    }, 'No se pudo guardar el grupo.');

  // Without an active campaign `guardar` runs at once; with one, the preview is asked and the change waits.
  const cambiarFiltros = (cambio, guardar) => {
    if (activas.length === 0) return guardar();
    return correr(async () => {
      const { data } = await offsetGruposAPI.alcancePrevio(grupo.id, cambio);
      setPendiente({ guardar, antes: data.antes, despues: data.despues });
    }, 'No se pudo calcular el alcance del cambio.');
  };

  const confirmarCambio = () => {
    const { guardar } = pendiente;
    setPendiente(null);
    return guardar();
  };

  const agregarFiltro = () => {
    const body = {
      marca: filtro.marca || null,
      categoria: filtro.categoria || null,
      subcategoria_id: filtro.subcategoria_id ? Number(filtro.subcategoria_id) : null,
      item_id: filtro.producto?.key ?? null,
    };
    return cambiarFiltros({ agregar: body }, () =>
      correr(async () => {
        await offsetGruposAPI.agregarFiltro(grupo.id, body);
        setFiltro(FILTRO_VACIO);
        await onCambio();
      }, 'No se pudo agregar el filtro.'),
    );
  };

  const quitarFiltro = (filtroId) =>
    cambiarFiltros({ quitar_filtro_id: filtroId }, () =>
      correr(async () => {
        await offsetGruposAPI.eliminarFiltro(grupo.id, filtroId);
        await onCambio();
      }, 'No se pudo quitar el filtro.'),
    );

  const nombresActivas = activas.map((c) => `«${c.nombre}»`).join(', ');
  const recalcula =
    activas.length === 1
      ? `Este cambio recalcula la campaña de sell out activa ${nombresActivas}.`
      : `Este cambio recalcula las campañas de sell out activas ${nombresActivas}.`;

  const eliminar = () =>
    correr(async () => {
      setConfirmando(false);
      await offsetGruposAPI.eliminar(grupo.id);
      onEliminado();
    }, 'No se pudo eliminar el grupo.');

  const filtroVacio = !filtro.marca && !filtro.categoria && !filtro.subcategoria_id && !filtro.producto;
  const set = (campo) => (event) => setFiltro((actual) => ({ ...actual, [campo]: event.target.value }));

  return (
    <div className={styles.panel}>
      <header className={styles.panelHeader}>
        <div>
          <h2>{nuevo ? 'Nuevo grupo' : grupo.nombre}</h2>
        </div>
        <button type="button" className={styles.close} aria-label="Cerrar" onClick={onClose} disabled={busy}>
          <X size={16} />
        </button>
      </header>

      <div className={styles.panelBody}>
        {error && (
          <p className={styles.error} role="alert">
            {error}
          </p>
        )}
        <section className={styles.section}>
          <label className={styles.field} htmlFor={`${id}-nombre`}>
            <span className={styles.label}>Nombre</span>
            <input id={`${id}-nombre`} className={styles.input} maxLength={100} value={nombre} onChange={(e) => setNombre(e.target.value)} />
          </label>
          <label className={styles.field} htmlFor={`${id}-descripcion`}>
            <span className={styles.label}>Descripción</span>
            <input id={`${id}-descripcion`} className={styles.input} maxLength={255} value={descripcion} onChange={(e) => setDescripcion(e.target.value)} />
          </label>
          <div className={own.acciones}>
            <button type="button" className="btn-tesla primary sm" onClick={guardarNombre} disabled={busy || !nombre.trim()}>
              {nuevo ? 'Crear grupo' : 'Guardar nombre'}
            </button>
          </div>
        </section>

        {!nuevo && (
          <>
            <section className={styles.section} aria-label="Filtros del grupo">
              <h3>Filtros</h3>
              <p className={styles.hint}>Un producto entra si cumple alguna fila; dentro de una fila, todos los campos elegidos.</p>
              {grupo.filtros.length === 0 && <p className={styles.hint}>Sin filtros: el grupo no alcanza productos.</p>}
              <ul className={own.filas}>
                {grupo.filtros.map((f) => {
                  const texto = resumenFiltro(f, subcategorias);
                  return (
                    <li key={f.id} className={own.fila}>
                      <span>{texto}</span>
                      <button type="button" className="btn-tesla ghost sm" aria-label={`Quitar ${texto}`} onClick={() => quitarFiltro(f.id)} disabled={busy || Boolean(pendiente)}>
                        Quitar
                      </button>
                    </li>
                  );
                })}
              </ul>
              <div className={own.nuevaFila}>
                <label className={styles.field} htmlFor={`${id}-marca`}>
                  <span className={styles.label}>Marca</span>
                  <select id={`${id}-marca`} className={styles.select} value={filtro.marca} onChange={set('marca')}>
                    <option value="">Cualquiera</option>
                    {(opciones?.marcas ?? []).map((m) => (
                      <option key={m} value={m}>
                        {m}
                      </option>
                    ))}
                  </select>
                </label>
                <label className={styles.field} htmlFor={`${id}-categoria`}>
                  <span className={styles.label}>Categoría</span>
                  <select id={`${id}-categoria`} className={styles.select} value={filtro.categoria} onChange={set('categoria')}>
                    <option value="">Cualquiera</option>
                    {(opciones?.categorias ?? []).map((c) => (
                      <option key={c} value={c}>
                        {c}
                      </option>
                    ))}
                  </select>
                </label>
                <label className={styles.field} htmlFor={`${id}-subcategoria`}>
                  <span className={styles.label}>Subcategoría</span>
                  <select id={`${id}-subcategoria`} className={styles.select} value={filtro.subcategoria_id} onChange={set('subcategoria_id')}>
                    <option value="">Cualquiera</option>
                    {(opciones?.subcategorias ?? []).map((s) => (
                      <option key={s.id} value={s.id}>
                        {s.nombre}
                      </option>
                    ))}
                  </select>
                </label>
                {filtro.producto ? (
                  <p className={own.fila}>
                    <span>{`Producto: ${filtro.producto.label}`}</span>
                    <button type="button" className="btn-tesla ghost sm" onClick={() => setFiltro((a) => ({ ...a, producto: null }))}>
                      Quitar producto elegido
                    </button>
                  </p>
                ) : (
                  <SellInBuscador
                    label="Producto"
                    placeholder="Buscar producto por código o descripción…"
                    buscar={buscarProductos}
                    onPick={(producto) => setFiltro((a) => ({ ...a, producto }))}
                    errorMessage="No se pudieron buscar productos."
                  />
                )}
                <div className={own.acciones}>
                  <button type="button" className="btn-tesla outline sm" onClick={agregarFiltro} disabled={busy || filtroVacio || Boolean(pendiente)}>
                    Agregar filtro
                  </button>
                </div>
              </div>
              {pendiente && (
                <div className={styles.confirm} role="group" aria-label="Confirmar cambio de filtros">
                  <p>{recalcula}</p>
                  <p>{`Productos alcanzados: ${pendiente.antes} → ${pendiente.despues}.`}</p>
                  <div className={styles.confirmActions}>
                    <button type="button" className="btn-tesla outline sm" onClick={() => setPendiente(null)} disabled={busy}>
                      Cancelar
                    </button>
                    <button type="button" className="btn-tesla primary sm" onClick={confirmarCambio} disabled={busy}>
                      Confirmar cambio
                    </button>
                  </div>
                </div>
              )}
            </section>

            <section className={styles.section} aria-label="Alcance del grupo">
              <h3>Alcance</h3>
              <p>{productosTexto(grupo.productos)}</p>
              <p className={own.nota}>{NOTA_ALCANCE}</p>
              <h3>Campañas de sell out</h3>
              {grupo.campanas.length === 0 ? (
                <p className={styles.hint}>Ninguna campaña usa este grupo.</p>
              ) : (
                <ul className={own.filas}>
                  {grupo.campanas.map((c) => (
                    <li key={c.id} className={own.fila}>
                      <span>{c.nombre}</span>
                      <StatusPill tone={c.estado === 'activa' ? 'success' : 'danger'}>{c.estado === 'activa' ? 'Activa' : 'Anulada'}</StatusPill>
                    </li>
                  ))}
                </ul>
              )}
            </section>
          </>
        )}
      </div>

      {!nuevo && (
        <footer className={styles.panelFooter}>
          {confirmando ? (
            <div className={styles.confirm}>
              <p className={styles.hint}>Un grupo que usa una campaña de sell out o un offset no se puede eliminar.</p>
              <div className={styles.confirmActions}>
                <button type="button" className="btn-tesla outline sm" onClick={() => setConfirmando(false)} disabled={busy}>
                  Cancelar
                </button>
                <button type="button" className="btn-tesla danger sm" onClick={eliminar} disabled={busy}>
                  Confirmar eliminación
                </button>
              </div>
            </div>
          ) : (
            <button type="button" className="btn-tesla outline sm" onClick={() => setConfirmando(true)} disabled={busy}>
              Eliminar grupo
            </button>
          )}
        </footer>
      )}
    </div>
  );
}
