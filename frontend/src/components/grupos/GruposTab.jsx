import { useState } from 'react';
import { Plus, ShieldAlert, Trash2 } from 'lucide-react';
import { offsetGruposAPI } from '../../services/offsetGruposAPI';
import { apiErrorMessage } from '../../utils/apiErrorMessage';
import { SplitPanelLayout } from '../kit';
import GrupoPanel from './GrupoPanel';
import GruposTable from './GruposTable';
import { NOTA_ALCANCE, nombresDeSubcategorias } from './grupoFormat';
import { useGrupos } from './useGrupos';
import pageStyles from '../../pages/SellIn.module.css';
import own from './Grupos.module.css';

/**
 * The "Grupos" tab of Sell in / Sell out (T30): the product groups sell-out campaigns reach, with the products
 * each reaches and the campaigns using it; "Editar" / "Nuevo grupo" open the side panel, and the checked groups go
 * at once with "Borrar seleccionados" (tactical S9). The page shows it with `grupos.ver`; `puedeEditar`
 * (`config.editar_constantes`, the permission of every group write) adds the panel and the checkboxes. A new
 * `version` (the page's "Actualizar") asks the groups again and keeps the open panel; `onGruposCambiados` tells the
 * page a group was created, changed or deleted, so the campaign form offers the current groups.
 */
const gruposTexto = (n) => (n === 1 ? '1 grupo' : `${n} grupos`);

export default function GruposTab({ version = 0, onGruposCambiados = () => {}, puedeEditar = true }) {
  const { grupos, opciones, error, errorOpciones, recargar } = useGrupos(version);
  const [marcados, setMarcados] = useState(() => new Set());
  const [confirmandoBorrado, setConfirmandoBorrado] = useState(false);
  const [borrando, setBorrando] = useState(false);
  const [errorBorrado, setErrorBorrado] = useState(null);
  // `{ eliminados, rechazados }` of the last "Borrar seleccionados", until the next one.
  const [resultado, setResultado] = useState(null);
  // Only the checked groups the list still has: one deleted elsewhere drops out of the count.
  const seleccionados = (grupos ?? []).filter((g) => marcados.has(g.id)).map((g) => g.id);
  const marcar = (ids, marcar) =>
    setMarcados((actual) => {
      const siguiente = new Set(actual);
      ids.forEach((id) => (marcar ? siguiente.add(id) : siguiente.delete(id)));
      return siguiente;
    });
  const borrarSeleccionados = async () => {
    setBorrando(true);
    setErrorBorrado(null);
    try {
      const { data } = await offsetGruposAPI.eliminarVarios(seleccionados);
      setResultado(data);
      setMarcados(new Set());
      setConfirmandoBorrado(false);
      if (data.eliminados.length > 0) onGruposCambiados();
      await recargar();
    } catch (err) {
      setErrorBorrado(apiErrorMessage(err, 'No se pudieron borrar los grupos.'));
      setConfirmandoBorrado(false);
    } finally {
      setBorrando(false);
    }
  };
  // `{ id, inicial }`: `id` null is a new group; `inicial` is what "Crear grupo" answered, until the list has it.
  const [panel, setPanel] = useState(null);
  const subcategorias = nombresDeSubcategorias(opciones);
  // Returns the reload: the panel stays busy until the list and the preview are current.
  const cambiaron = () => {
    onGruposCambiados();
    return recargar();
  };
  const grupo = panel?.id != null ? (grupos?.find((g) => g.id === panel.id) ?? panel.inicial) : null;
  // Once the list has the created group, `inicial` is dropped: a later reload without it closes the panel too.
  if (panel?.inicial && grupos?.some((g) => g.id === panel.id)) setPanel({ id: panel.id });
  // A reload without the open group (someone else deleted it) closes the panel instead of turning it into "Nuevo".
  if (panel?.id != null && grupos && !grupo) setPanel(null);

  return (
    <SplitPanelLayout
      open={Boolean(panel)}
      onClose={() => setPanel(null)}
      width="lg"
      ariaLabel="Grupo"
      panel={
        panel && (
          <GrupoPanel
            key={panel.id ?? 'nuevo'}
            grupo={grupo}
            opciones={opciones}
            subcategorias={subcategorias}
            onClose={() => setPanel(null)}
            onCreado={(creado) => {
              setPanel({ id: creado.id, inicial: { productos: 0, campanas: [], filtros: [], ...creado } });
              cambiaron();
            }}
            onCambio={cambiaron}
            onEliminado={() => {
              setPanel(null);
              cambiaron();
            }}
          />
        )
      }
    >
      <section aria-labelledby="grupos-titulo">
        <h2 id="grupos-titulo" className={pageStyles.srOnly}>
          Grupos de productos
        </h2>
        <div className={own.toolbar}>
          <p className={own.nota}>{NOTA_ALCANCE}</p>
          {puedeEditar && (
            <div className={own.toolbarAcciones}>
              {seleccionados.length > 0 && !confirmandoBorrado && (
                <button type="button" className="btn-tesla outline sm" onClick={() => setConfirmandoBorrado(true)} disabled={borrando}>
                  <Trash2 size={14} /> Borrar seleccionados ({seleccionados.length})
                </button>
              )}
              <button type="button" className="btn-tesla primary sm" onClick={() => setPanel({ id: null })}>
                <Plus size={14} /> Nuevo grupo
              </button>
            </div>
          )}
        </div>
        {confirmandoBorrado && seleccionados.length > 0 && (
          <div className={own.confirmar} role="group" aria-label="Confirmar borrado">
            <span>¿Borrar {gruposTexto(seleccionados.length)}? Un grupo que usa una campaña de sell out o un offset no se borra.</span>
            <button type="button" className="btn-tesla outline sm" onClick={() => setConfirmandoBorrado(false)} disabled={borrando}>
              Cancelar
            </button>
            <button type="button" className="btn-tesla danger sm" onClick={borrarSeleccionados} disabled={borrando}>
              Borrar {gruposTexto(seleccionados.length)}
            </button>
          </div>
        )}
        {errorBorrado && (
          <div className={pageStyles.errorBar} role="alert">
            <ShieldAlert size={16} /> {errorBorrado}
          </div>
        )}
        {resultado && (
          <div className={own.resultado} role="status">
            {resultado.eliminados.length > 0 && (
              <p>{resultado.eliminados.length === 1 ? 'Se borró 1 grupo.' : `Se borraron ${resultado.eliminados.length} grupos.`}</p>
            )}
            {resultado.rechazados.length > 0 && (
              <>
                <p>{resultado.rechazados.length === 1 ? 'No se borró 1 grupo: ' : `No se borraron ${resultado.rechazados.length} grupos: `}</p>
                <ul>
                  {resultado.rechazados.map((r) => (
                    <li key={r.id}>
                      {r.nombre ?? `#${r.id}`}: {r.motivo}
                    </li>
                  ))}
                </ul>
              </>
            )}
          </div>
        )}
        {error && (
          <div className={pageStyles.errorBar} role="alert">
            <ShieldAlert size={16} /> {error}
          </div>
        )}
        {errorOpciones && !error && (
          <div className={pageStyles.errorBar} role="alert">
            <ShieldAlert size={16} /> {errorOpciones}
          </div>
        )}
        {!grupos && !error && <p className={pageStyles.loading}>Cargando grupos…</p>}
        {grupos && (
          <GruposTable
            grupos={grupos}
            subcategorias={subcategorias}
            selectedId={panel?.id ?? null}
            onSelect={puedeEditar ? (id) => setPanel({ id }) : undefined}
            marcados={marcados}
            onMarcar={marcar}
          />
        )}
      </section>
    </SplitPanelLayout>
  );
}
