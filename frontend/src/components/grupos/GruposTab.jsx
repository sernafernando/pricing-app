import { useState } from 'react';
import { Plus, ShieldAlert } from 'lucide-react';
import { SplitPanelLayout } from '../kit';
import GrupoPanel from './GrupoPanel';
import GruposTable from './GruposTable';
import { NOTA_ALCANCE, nombresDeSubcategorias } from './grupoFormat';
import { useGrupos } from './useGrupos';
import pageStyles from '../../pages/SellIn.module.css';
import own from './Grupos.module.css';

/**
 * The "Grupos" tab of Sell in / Sell out (T30): the product groups sell-out campaigns reach, with the products
 * each reaches and the campaigns using it; "Editar" / "Nuevo grupo" open the side panel. Shown with
 * `config.editar_constantes`, the permission of every group endpoint it calls. A new `version` (the page's
 * "Actualizar") asks the groups again and keeps the open panel.
 */
export default function GruposTab({ version = 0 }) {
  const { grupos, opciones, error, errorOpciones, recargar } = useGrupos(version);
  // `{ id, inicial }`: `id` null is a new group; `inicial` is what "Crear grupo" answered, until the list has it.
  const [panel, setPanel] = useState(null);
  const subcategorias = nombresDeSubcategorias(opciones);
  const grupo = panel?.id != null ? (grupos?.find((g) => g.id === panel.id) ?? panel.inicial) : null;

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
              recargar();
            }}
            onCambio={recargar}
            onEliminado={() => {
              setPanel(null);
              recargar();
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
          <button type="button" className="btn-tesla primary sm" onClick={() => setPanel({ id: null })}>
            <Plus size={14} /> Nuevo grupo
          </button>
        </div>
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
        {grupos && <GruposTable grupos={grupos} subcategorias={subcategorias} selectedId={panel?.id ?? null} onSelect={(id) => setPanel({ id })} />}
      </section>
    </SplitPanelLayout>
  );
}
