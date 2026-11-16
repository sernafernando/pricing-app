import { useEffect, useRef, useState } from 'react';
import { productoSpecsAPI } from '../../services/api';
import { specActual } from './fichaEdits';
import m from './maestro.module.css';
import f from './Ficha.module.css';

const TAG = { ml: 'ML', erp_name: 'ERP', combo: 'Combo', manual: 'Manual' };
const TAG_CLS = { ml: m.oMl, erp_name: m.oGbp, combo: m.oTn, manual: m.oManual };
// The spec units as the mock writes them.
const UNIDAD = { pulgadas: 'pulg.' };

function Spec({ campo, info, edits, editable, onValor, onNoAplica, sugerencias, onSugerir }) {
  const { na, valor, editado, naEditado } = specActual(campo, edits);
  const vacio = valor.trim() === '';
  const manualSinGuardar = editado && !na;
  const tag = na ? 'No aplica' : manualSinGuardar ? 'Manual · sin guardar' : vacio ? 'Sin dato' : TAG[campo.origen] ?? 'Manual';
  const tagCls = na ? m.oNa : manualSinGuardar ? m.oManual : vacio ? m.oNone : TAG_CLS[campo.origen] ?? m.oManual;
  const unidad = !na && info?.unidad ? UNIDAD[info.unidad] ?? info.unidad : null;
  const categorico = info?.tipo === 'categorico';
  const listId = categorico ? `spec-valores-${campo.campo}` : undefined;
  const inpCls = [m.inp, unidad && m.inpUnit, (editado || naEditado) && m.inpDirty, vacio && m.inpEmpty].filter(Boolean).join(' ');

  return (
    <div className={f.spec} data-spec={campo.campo}>
      <span className={f.campoHead}>
        <span>{campo.etiqueta}</span>
        <span className={`${m.tag} ${tagCls}`}>{tag}</span>
      </span>
      <span className={m.inpWrap}>
        <input
          className={inpCls}
          value={valor}
          placeholder={na ? 'No aplica' : 'Sin dato'}
          aria-label={`${campo.grupo} ${campo.etiqueta}`}
          disabled={na || !editable}
          list={listId}
          inputMode={info?.tipo === 'numerico' ? 'decimal' : undefined}
          onFocus={categorico ? () => onSugerir(campo.campo) : undefined}
          onChange={(e) => onValor(campo.campo, e.target.value)}
        />
        {unidad && <span className={m.unit}>{unidad}</span>}
      </span>
      {categorico && (
        <datalist id={listId}>
          {(sugerencias[campo.campo] ?? []).map((v) => (
            <option key={String(v)} value={String(v)} />
          ))}
        </datalist>
      )}
      <label className={m.na}>
        <input className={m.chk} type="checkbox" checked={na} disabled={!editable} onChange={() => onNoAplica(campo.campo, !na)} />
        No aplica
      </label>
    </div>
  );
}

/**
 * The ficha's "Specs técnicas" tab (notebooks and PCs): the fields grouped by component, each with its origin
 * (ML, ERP name, combo, manual) and "No aplica" so an empty field that does not apply still counts as complete.
 * Categorical fields suggest the normalized values; a new value is checked by the server.
 *
 * @param {object} props
 * @param {object} props.specs The read of `GET /producto-specs/{item_id}`.
 * @param {Record<string, object>} props.info `/producto-specs/campos` by field name (type and unit).
 */
export default function FichaSpecs({ specs, info, edits, onValor, onNoAplica }) {
  const [sugerencias, setSugerencias] = useState({});
  const grupos = [...new Set(specs.campos.map((c) => c.grupo))];

  const montado = useRef(true);
  useEffect(() => {
    montado.current = true;
    return () => {
      montado.current = false;
    };
  }, []);

  const sugerir = (campo) => {
    if (campo in sugerencias) return;
    setSugerencias((prev) => ({ ...prev, [campo]: [] }));
    productoSpecsAPI
      .valores(campo)
      .then(({ data }) => montado.current && setSugerencias((prev) => ({ ...prev, [campo]: data })))
      .catch(() => {});
  };

  return (
    <div className={f.cuerpo}>
      {grupos.map((grupo) => {
        const campos = specs.campos.filter((c) => c.grupo === grupo);
        const listos = campos.filter((c) => {
          const actual = specActual(c, edits);
          return actual.na || actual.valor.trim() !== '';
        }).length;
        return (
          <fieldset key={grupo} className={f.seccion} aria-label={`${grupo} ${listos} / ${campos.length}`}>
            <legend className={f.legend}>
              {grupo} <span className={`${m.mono} ${f.legendFrac}`}>{`${listos} / ${campos.length}`}</span>
            </legend>
            <div className={f.grillaSpecs}>
              {campos.map((campo) => (
                <Spec
                  key={campo.campo}
                  campo={campo}
                  info={info[campo.campo]}
                  edits={edits}
                  editable={specs.can_edit}
                  onValor={onValor}
                  onNoAplica={onNoAplica}
                  sugerencias={sugerencias}
                  onSugerir={sugerir}
                />
              ))}
            </div>
          </fieldset>
        );
      })}
    </div>
  );
}
