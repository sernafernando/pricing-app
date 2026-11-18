import { useState, useRef, useEffect, useId } from 'react';
import { Columns3, GripVertical, RotateCcw } from 'lucide-react';
import { DndContext, closestCenter, KeyboardSensor, PointerSensor, useSensor, useSensors } from '@dnd-kit/core';
import { SortableContext, arrayMove, sortableKeyboardCoordinates, useSortable, verticalListSortingStrategy } from '@dnd-kit/sortable';
import { CSS as DndCss } from '@dnd-kit/utilities';
import styles from './ColumnPicker.module.css';

const columnLabel = (col) => col.columnDef.header || col.columnDef.headerAriaLabel || col.id;

// One checkbox row, the same with or without reorder: the visibility is TanStack's own handler.
function ColumnCheckbox({ col }) {
  return (
    <label className={styles.option}>
      <input type="checkbox" checked={col.getIsVisible()} onChange={col.getToggleVisibilityHandler()} />
      {columnLabel(col)}
    </label>
  );
}

// The drag handle: dnd-kit's pointer and keyboard listeners (Space lifts, arrows move, Space drops, Esc cancels).
function DragHandle({ label, sortable }) {
  return (
    <button type="button" className={styles.handle} aria-label={label} title={label} {...sortable.attributes} {...sortable.listeners}>
      <GripVertical size={14} aria-hidden="true" />
    </button>
  );
}

// Translate, not Transform: a block dropped over a taller or shorter one must not be stretched to its size.
const sortableStyle = ({ transform, transition }) => ({ transform: DndCss.Translate.toString(transform), transition });

/** A column inside its group: it moves only among the group's columns (the group's own DndContext). */
function SortableColumn({ col }) {
  const sortable = useSortable({ id: col.id });
  return (
    <li ref={sortable.setNodeRef} style={sortableStyle(sortable)} className={`${styles.row} ${sortable.isDragging ? styles.dragging : ''}`}>
      <DragHandle label={`Mover ${columnLabel(col)}`} sortable={sortable} />
      <ColumnCheckbox col={col} />
    </li>
  );
}

/** A block of the outer list: a whole group (its name and its columns) or a column without a group. */
function SortableBlock({ block, sensors, onMoveInGroup }) {
  const sortable = useSortable({ id: block.id });
  const className = `${styles.block} ${sortable.isDragging ? styles.dragging : ''}`;
  if (!block.group) {
    return (
      <li ref={sortable.setNodeRef} style={sortableStyle(sortable)} className={`${className} ${styles.row}`}>
        <DragHandle label={`Mover ${columnLabel(block.columns[0])}`} sortable={sortable} />
        <ColumnCheckbox col={block.columns[0]} />
      </li>
    );
  }
  return (
    <li ref={sortable.setNodeRef} style={sortableStyle(sortable)} className={className}>
      <div className={`${styles.row} ${styles.groupHeader}`}>
        <DragHandle label={`Mover grupo ${block.group}`} sortable={sortable} />
        <span className={styles.groupName}>{block.group}</span>
      </div>
      <DndContext id={`column-group-${block.group}`} sensors={sensors} collisionDetection={closestCenter} onDragEnd={onMoveInGroup(block)}>
        <SortableContext items={block.columns.map((col) => col.id)} strategy={verticalListSortingStrategy}>
          <ul className={styles.list} aria-label={`Columnas de ${block.group}`}>
            {block.columns.map((col) => (
              <SortableColumn key={col.id} col={col} />
            ))}
          </ul>
        </SortableContext>
      </DndContext>
    </li>
  );
}

// Each run of columns of the same `meta.group` is one block; a column without a group, its own.
function toBlocks(columns) {
  const blocks = [];
  for (const col of columns) {
    const group = col.columnDef.meta?.group ?? null;
    const last = blocks.at(-1);
    if (group && last?.group === group) last.columns.push(col);
    else blocks.push({ id: group ? `group:${group}` : `col:${col.id}`, group, columns: [col] });
  }
  return blocks;
}

const idsOf = (blocks) => blocks.flatMap((block) => block.columns.map((col) => col.id));

/**
 * The reorderable list (`onReorder`): groups move as a block in the outer DndContext (`column-blocks`), a group's
 * columns only inside it (its own `column-group-<name>` context). `onReorder` gets every listed id in the new order.
 */
function ReorderableColumns({ columns, onReorder }) {
  const sensors = useSensors(
    useSensor(PointerSensor, { activationConstraint: { distance: 4 } }),
    useSensor(KeyboardSensor, { coordinateGetter: sortableKeyboardCoordinates }),
  );
  const blocks = toBlocks(columns);

  const moveBlock = ({ active, over }) => {
    if (!over || active.id === over.id) return;
    const from = blocks.findIndex((block) => block.id === active.id);
    const to = blocks.findIndex((block) => block.id === over.id);
    if (from < 0 || to < 0) return;
    onReorder(idsOf(arrayMove(blocks, from, to)));
  };

  const moveInGroup = (group) => ({ active, over }) => {
    if (!over || active.id === over.id) return;
    const ids = group.columns.map((col) => col.id);
    const from = ids.indexOf(active.id);
    const to = ids.indexOf(over.id);
    if (from < 0 || to < 0) return;
    const moved = arrayMove(ids, from, to);
    onReorder(blocks.flatMap((block) => (block === group ? moved : block.columns.map((col) => col.id))));
  };

  return (
    <DndContext id="column-blocks" sensors={sensors} collisionDetection={closestCenter} onDragEnd={moveBlock}>
      <SortableContext items={blocks.map((block) => block.id)} strategy={verticalListSortingStrategy}>
        <ul className={styles.list} aria-label="Orden de las columnas">
          {blocks.map((block) => (
            <SortableBlock key={block.id} block={block} sensors={sensors} onMoveInGroup={moveInGroup} />
          ))}
        </ul>
      </SortableContext>
    </DndContext>
  );
}

/**
 * ColumnPicker — ventas-ml-columnas T6/T7.
 *
 * A popover listing every column the `table` instance knows about
 * (`table.getAllLeafColumns()`), each with a checkbox wired to TanStack's
 * own `column.getToggleVisibilityHandler()` -- the SAME visibility state
 * the header/body render from, so there is no separate "picker state" that
 * could drift from what the table actually shows.
 *
 * Columns with `enableHiding: false` are left out of the list entirely:
 * offering a checkbox TanStack itself refuses to uncheck would be a dead
 * control. Which ones those are lives in `ventasMlColumns.jsx` and is NOT
 * repeated here -- the list grew once already (Producto and Total Gauss for
 * the information they carry, then alerta, orden and neto for the CONTROLS
 * they hold) and a copy of it here would just rot.
 *
 * `label`, `icon` and `groupLabel` let the same picker list other things a page shows or hides (the KPI
 * cards' "Indicadores"); each instance gets its own popover id, so two can sit side by side. `iconOnly` shows just
 * the icon, the label then naming the button and its tooltip; `buttonClassName` replaces the trigger's look.
 *
 * Opt-in, for a page that keeps a column order (Publicaciones ML, pubml-columnas-presets S1): `onReorder(ids)` adds
 * drag handles (pointer and keyboard) -- groups (`columnDef.meta.group`) move as a block, their columns only inside
 * them -- and gets the listed ids in their new order; `onReset` adds "Restablecer". Without them the picker is the
 * plain list of checkboxes every other page has.
 */
export default function ColumnPicker({
  table,
  label = 'Columnas',
  icon = Columns3,
  groupLabel = 'Elegir columnas visibles',
  iconOnly = false,
  buttonClassName = 'btn-tesla outline sm',
  onReorder,
  onReset,
}) {
  const Icon = icon;
  const popoverId = useId();
  const [open, setOpen] = useState(false);
  const containerRef = useRef(null);
  const triggerRef = useRef(null);

  useEffect(() => {
    if (!open) return undefined;
    function handleClickOutside(event) {
      if (containerRef.current && !containerRef.current.contains(event.target)) {
        setOpen(false);
      }
    }
    // Escape closes it and returns focus to the trigger, the behaviour any
    // keyboard user expects from something opened with `aria-expanded`.
    // Without it the only way out is a mouse click elsewhere.
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

  const toggleableColumns = table.getAllLeafColumns().filter((col) => col.getCanHide());

  return (
    <div className={styles.container} ref={containerRef}>
      {/* NO `aria-haspopup` on this trigger. In ARIA, `aria-haspopup="true"`
          is literally `"menu"` -- announcing to a screen reader the very
          contract the popover below deliberately does NOT claim.
          `aria-expanded` plus `aria-controls` say what is actually true: this
          button shows and hides that group. */}
      <button
        type="button"
        ref={triggerRef}
        className={iconOnly ? `${buttonClassName} icon-only` : buttonClassName}
        aria-label={iconOnly ? label : undefined}
        title={iconOnly ? label : undefined}
        aria-expanded={open}
        aria-controls={popoverId}
        onClick={() => setOpen((prev) => !prev)}
      >
        <Icon size={14} />
        {!iconOnly && label}
      </button>
      {/* `role="group"`, NOT `role="menu"`: a `menu` expects
          `menuitemcheckbox` children with full arrow-key navigation, and these
          are plain `<label><input type="checkbox">` pairs. Claiming `menu`
          tells a screen reader to expect a keyboard contract this popover does
          not implement, which is worse than claiming nothing. A group of
          native checkboxes is already announced correctly. */}
      {open && (
        <div
          id={popoverId}
          className={onReorder ? `${styles.popover} ${styles.popoverReorder}` : styles.popover}
          role="group"
          aria-label={groupLabel}
        >
          {onReorder ? (
            <>
              <p className={styles.hint}>Arrastrá para ordenar. Con teclado: espacio, flechas y espacio.</p>
              <ReorderableColumns columns={toggleableColumns} onReorder={onReorder} />
            </>
          ) : (
            toggleableColumns.map((col) => <ColumnCheckbox key={col.id} col={col} />)
          )}
          {onReset && (
            <button type="button" className={`btn-tesla ghost sm ${styles.reset}`} onClick={onReset}>
              <RotateCcw size={14} aria-hidden="true" />
              Restablecer
            </button>
          )}
        </div>
      )}
    </div>
  );
}
