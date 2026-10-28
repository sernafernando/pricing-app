import { productosPropiosAPI } from '../../../services/api';
import DataForm from './DataForm';

/**
 * Edit the product's copied data and save it whole (`PUT /productos-propios/{item_id}/datos`): the title, the
 * description (blank saves none), the copied pictures (remove, reorder; no new ones) and the copied attributes (edit
 * the value, remove). Nothing outside the copy can be added: the server only takes what was copied.
 *
 * @param {object} props
 * @param {number} props.itemId
 * @param {object} props.datos The copy as the server last answered it.
 * @param {(product: object) => void} props.onSaved Receives the product as the server answered the save.
 * @param {() => void} props.onCancel
 */
export default function ProductDataForm({ itemId, datos, onSaved, onCancel }) {
  const submit = (form) =>
    productosPropiosAPI.saveDatos(itemId, {
      titulo: form.titulo,
      descripcion: form.descripcion.trim() ? form.descripcion : null,
      fotos: form.fotos.map((foto) => foto.id),
      atributos: form.atributos.map((atributo) => ({ id: atributo.id, value_name: atributo.value_name })),
    });
  return (
    <DataForm
      datos={datos}
      submit={submit}
      forbidden="No tenés permiso para editar los datos del producto."
      onSaved={onSaved}
      onCancel={onCancel}
    />
  );
}
