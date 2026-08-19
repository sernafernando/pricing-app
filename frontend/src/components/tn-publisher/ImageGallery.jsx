/**
 * ImageGallery — `SortableImageTile` + dnd-kit sortable thumbnail grid
 * (drag to reorder, per-image delete), moved verbatim out of the
 * pre-decomposition `TnPublishModal.jsx`.
 */
import {
  DndContext,
  closestCenter,
  PointerSensor,
  KeyboardSensor,
  useSensor,
  useSensors,
} from '@dnd-kit/core';
import { SortableContext, rectSortingStrategy, sortableKeyboardCoordinates, useSortable } from '@dnd-kit/sortable';
import { CSS as DndCss } from '@dnd-kit/utilities';
import { GripVertical, X } from 'lucide-react';
import styles from './TnPublishModal.module.css';

/** One sortable image tile: drag handle (pointer + keyboard) + delete. */
function SortableImageTile({ image, index, onDelete }) {
  const { attributes, listeners, setNodeRef, transform, transition, isDragging } = useSortable({
    id: image.id,
  });

  return (
    <li
      ref={setNodeRef}
      className={`${styles.imageTile} ${isDragging ? styles.imageTileDragging : ''}`}
      style={{ transform: DndCss.Transform.toString(transform), transition }}
    >
      <button
        type="button"
        className={styles.imageDragHandle}
        aria-label={`Reordenar imagen ${index + 1}`}
        {...attributes}
        {...listeners}
      >
        <GripVertical size={14} aria-hidden="true" />
      </button>
      <img src={image.src} alt={`Imagen ${index + 1} del producto`} className={styles.imageThumb} loading="lazy" />
      <span className={styles.imageOrder} aria-hidden="true">
        {index + 1}
      </span>
      <button
        type="button"
        className={styles.imageDelete}
        aria-label={`Eliminar imagen ${index + 1}`}
        onClick={() => onDelete(image.id)}
      >
        <X size={13} aria-hidden="true" />
      </button>
    </li>
  );
}

export default function ImageGallery({ images, imageIds, onDragEnd, onDelete }) {
  const sensors = useSensors(
    useSensor(PointerSensor, { activationConstraint: { distance: 4 } }),
    useSensor(KeyboardSensor, { coordinateGetter: sortableKeyboardCoordinates })
  );

  return (
    <div className={styles.section} data-testid="tn-publish-field-images">
      <h3 className={styles.sectionTitle}>Imágenes ({images.length})</h3>
      {images.length === 0 ? (
        <p className={styles.fieldHint}>Sin imágenes para publicar.</p>
      ) : (
        <>
          <p className={styles.fieldHint}>
            Arrastrá para reordenar (o con teclado: espacio para levantar, flechas para mover). La primera
            imagen es la portada.
          </p>
          <DndContext sensors={sensors} collisionDetection={closestCenter} onDragEnd={onDragEnd}>
            <SortableContext items={imageIds} strategy={rectSortingStrategy}>
              <ul className={styles.imageGrid} aria-label="Imágenes del producto (ordenables)">
                {images.map((image, index) => (
                  <SortableImageTile key={image.id} image={image} index={index} onDelete={onDelete} />
                ))}
              </ul>
            </SortableContext>
          </DndContext>
        </>
      )}
    </div>
  );
}
