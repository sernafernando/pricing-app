import { useRef, useState } from 'react';
import { Copy } from 'lucide-react';
import { marcasPmAPI } from '../../services/api';
import { ModalAlert } from '../ModalTesla';
import { parKey } from '../parKey';
import { extraerError } from '../../pages/misSubPMsHelpers';
import styles from './CopiarSubPM.module.css';

function agruparPorMarca(lista) {
  const porMarca = new Map();
  for (const par of lista) {
    if (!porMarca.has(par.marca)) porMarca.set(par.marca, []);
    porMarca.get(par.marca).push(par.categoria);
  }
  return [...porMarca.entries()]
    .sort(([a], [b]) => a.localeCompare(b))
    .map(([marca, categorias]) => [marca, [...categorias].sort((a, b) => a.localeCompare(b))]);
}

/**
 * CopiarSubPM — "Copiar a otro usuario como sub-PM" on the Sub-PMs screen.
 *
 * Copies the selected user's pairs (`pares`: the ones they hold as PM plus
 * their saved sub-PM pairs) to another user as sub-PM. Picking the target
 * reads their current grants and previews exactly which pairs get added;
 * nothing is written until "Sí, copiar".
 *
 * The write goes through the existing atomic bulk PUT, which REPLACES the
 * target's whole set, so the target's current grants are read fresh again
 * right before writing and kept — same contract as `VistaPorMarca`. If a
 * read fails, nothing is written. While `disabled` (unsaved changes on the
 * selected user) neither the panel opens nor "Sí, copiar" runs, since the
 * copy is built from what is saved. A pair whose titular is the target is
 * never copied: a titular is never a sub-PM of their own pairs.
 *
 * `onCopiado(usuarioId)` tells the parent which user changed.
 */
export default function CopiarSubPM({ origen, pares, usuarios, disabled, onCopiado }) {
  const [abierto, setAbierto] = useState(false);
  const [destinoId, setDestinoId] = useState('');
  const [previa, setPrevia] = useState(null); // { estado: 'cargando' | 'error' | 'lista', nuevos }
  const [ocupado, setOcupado] = useState(false);
  const [alerta, setAlerta] = useState(null); // { tipo, texto }
  // Latest picked target, so a slow preview for a superseded pick is dropped.
  const destinoRef = useRef(null);

  const destino = usuarios.find((u) => u.id === Number(destinoId)) || null;

  const paresNuevos = (actuales, usuarioId) => {
    const tiene = new Set(actuales.map((p) => parKey(p.marca, p.categoria)));
    return pares.filter((par) => par.usuario_id !== usuarioId && !tiene.has(parKey(par.marca, par.categoria)));
  };

  const cerrar = () => {
    destinoRef.current = null;
    setAbierto(false);
    setDestinoId('');
    setPrevia(null);
  };

  const elegirDestino = async (valor) => {
    setDestinoId(valor);
    setAlerta(null);
    if (valor === '') {
      destinoRef.current = null;
      setPrevia(null);
      return;
    }
    const id = Number(valor);
    destinoRef.current = id;
    setPrevia({ estado: 'cargando', nuevos: [] });
    try {
      const { data } = await marcasPmAPI.obtenerGrantsUsuario(id);
      if (destinoRef.current !== id) return;
      setPrevia({ estado: 'lista', nuevos: paresNuevos(data?.pares || [], id) });
    } catch (err) {
      console.error('Error al leer los sub-PMs del usuario destino', err);
      if (destinoRef.current !== id) return;
      setPrevia({ estado: 'error', nuevos: [] });
    }
  };

  const copiar = async () => {
    if (!destino) return;
    const id = destino.id;
    setOcupado(true);
    setAlerta(null);
    try {
      const { data: actuales } = await marcasPmAPI.obtenerGrantsUsuario(id);
      const deseados = new Map();
      for (const p of actuales?.pares || []) deseados.set(parKey(p.marca, p.categoria), { marca: p.marca, categoria: p.categoria });
      for (const par of paresNuevos(actuales?.pares || [], id)) {
        deseados.set(parKey(par.marca, par.categoria), { marca: par.marca, categoria: par.categoria });
      }
      const { data } = await marcasPmAPI.asignarSubPMsBulk(id, [...deseados.values()]);
      const texto =
        data.otorgados === 0
          ? `${destino.nombre} ya era sub-PM de todos esos pares.`
          : `${destino.nombre} ahora es sub-PM de ${data.otorgados} ${data.otorgados === 1 ? 'par' : 'pares'} más.`;
      setAlerta({ tipo: 'success', texto });
      cerrar();
      onCopiado(id);
    } catch (err) {
      console.error('Error al copiar los pares como sub-PM', err);
      const { texto, rechazados } = extraerError(err, 'Error al copiar los pares');
      const detalle = rechazados.length
        ? ` Rechazados: ${rechazados.map((p) => `${p.marca} / ${p.categoria}`).join(', ')}.`
        : '';
      setAlerta({ tipo: 'error', texto: `${texto} No se aplicó ningún cambio.${detalle}` });
    } finally {
      setOcupado(false);
    }
  };

  const cantidad = previa?.nuevos.length ?? 0;

  return (
    <div className={styles.contenedor}>
      {alerta && <ModalAlert type={alerta.tipo}>{alerta.texto}</ModalAlert>}

      {!abierto ? (
        <button
          type="button"
          className="btn-tesla ghost sm"
          onClick={() => setAbierto(true)}
          disabled={disabled}
          title={disabled ? 'Guardá o descartá los cambios de este usuario primero' : undefined}
        >
          <Copy size={14} aria-hidden="true" />
          Copiar a otro usuario como sub-PM
        </button>
      ) : (
        <div className={styles.panel}>
          <div className={styles.fila}>
            <label className={styles.label} htmlFor="copiarSubPMDestino">
              Copiar a
            </label>
            <select
              id="copiarSubPMDestino"
              className={styles.select}
              value={destinoId}
              onChange={(e) => elegirDestino(e.target.value)}
              disabled={ocupado}
            >
              <option value="">Elegí un usuario...</option>
              {usuarios.map((u) => (
                <option key={u.id} value={u.id}>{u.nombre}</option>
              ))}
            </select>
            <span className={styles.ayuda}>
              Recibe como sub-PM los {pares.length} {pares.length === 1 ? 'par' : 'pares'} de {origen}; conserva los que ya tiene.
            </span>
          </div>

          {previa?.estado === 'cargando' && <p className={styles.nota}>Leyendo los pares actuales...</p>}
          {previa?.estado === 'error' && destino && (
            <p className={styles.error}>No se pudieron leer los pares actuales de {destino.nombre}; no se copió nada.</p>
          )}
          {previa?.estado === 'lista' && destino && (
            <div className={styles.resumen} data-testid="copiarResumen">
              {cantidad === 0 ? (
                <p className={styles.nota}>{destino.nombre} ya es sub-PM de todos esos pares; no hay nada para agregar.</p>
              ) : (
                <>
                  <p className={styles.titulo}>
                    Se le agregan a {destino.nombre} <strong>{cantidad}</strong> {cantidad === 1 ? 'par' : 'pares'} como sub-PM:
                  </p>
                  <ul className={styles.marcas}>
                    {agruparPorMarca(previa.nuevos).map(([marca, categorias]) => (
                      <li key={marca} className={styles.marca}>
                        <span className={styles.marcaNombre}>{marca}</span>
                        <span className={styles.categorias}>
                          {categorias.map((categoria) => (
                            <span key={categoria} className={styles.categoria}>{categoria}</span>
                          ))}
                        </span>
                      </li>
                    ))}
                  </ul>
                </>
              )}
            </div>
          )}

          <div className={styles.acciones}>
            {previa?.estado === 'lista' && cantidad > 0 && (
              <button
                type="button"
                className="btn-tesla outline-subtle-primary sm"
                onClick={copiar}
                disabled={ocupado || disabled}
                title={disabled ? 'Guardá o descartá los cambios de este usuario primero' : undefined}
              >
                {ocupado ? 'Copiando...' : 'Sí, copiar'}
              </button>
            )}
            <button type="button" className="btn-tesla ghost sm" onClick={cerrar} disabled={ocupado}>
              Cancelar
            </button>
          </div>
        </div>
      )}
    </div>
  );
}
