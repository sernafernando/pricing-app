/**
 * DescriptionEditor — TipTap WYSIWYG + visible toolbar (bold / italic /
 * underline / strike, H1–H3, paragraph, bullet + numbered lists), moved
 * VERBATIM out of the pre-decomposition `TnPublishModal.jsx` (non-goal to
 * touch TipTap in this PR).
 */
import { EditorContent } from '@tiptap/react';
import {
  Bold,
  Italic,
  Underline,
  Strikethrough,
  Heading1,
  Heading2,
  Heading3,
  Pilcrow,
  List,
  ListOrdered,
} from 'lucide-react';
import styles from './TnPublishModal.module.css';

/** Toolbar button with pressed state for the TipTap editor. */
function ToolbarButton({ label, active, disabled, onClick, children }) {
  return (
    <button
      type="button"
      className={`${styles.toolbarBtn} ${active ? styles.toolbarBtnActive : ''}`}
      aria-label={label}
      title={label}
      aria-pressed={Boolean(active)}
      disabled={disabled}
      onClick={onClick}
    >
      {children}
    </button>
  );
}

export default function DescriptionEditor({ editor, editorState }) {
  return (
    <div className={styles.section} data-testid="tn-publish-field-description">
      <h3 className={styles.sectionTitle}>Descripción</h3>
      <div className={styles.editorShell}>
        <div className={styles.toolbar} role="toolbar" aria-label="Formato de la descripción">
          <ToolbarButton
            label="Negrita"
            active={editorState?.bold}
            onClick={() => editor?.chain().focus().toggleBold().run()}
          >
            <Bold size={15} aria-hidden="true" />
          </ToolbarButton>
          <ToolbarButton
            label="Cursiva"
            active={editorState?.italic}
            onClick={() => editor?.chain().focus().toggleItalic().run()}
          >
            <Italic size={15} aria-hidden="true" />
          </ToolbarButton>
          <ToolbarButton
            label="Subrayado"
            active={editorState?.underline}
            onClick={() => editor?.chain().focus().toggleUnderline().run()}
          >
            <Underline size={15} aria-hidden="true" />
          </ToolbarButton>
          <ToolbarButton
            label="Tachado"
            active={editorState?.strike}
            onClick={() => editor?.chain().focus().toggleStrike().run()}
          >
            <Strikethrough size={15} aria-hidden="true" />
          </ToolbarButton>
          <span className={styles.toolbarDivider} aria-hidden="true" />
          <ToolbarButton
            label="Título 1"
            active={editorState?.h1}
            onClick={() => editor?.chain().focus().toggleHeading({ level: 1 }).run()}
          >
            <Heading1 size={15} aria-hidden="true" />
          </ToolbarButton>
          <ToolbarButton
            label="Título 2"
            active={editorState?.h2}
            onClick={() => editor?.chain().focus().toggleHeading({ level: 2 }).run()}
          >
            <Heading2 size={15} aria-hidden="true" />
          </ToolbarButton>
          <ToolbarButton
            label="Título 3"
            active={editorState?.h3}
            onClick={() => editor?.chain().focus().toggleHeading({ level: 3 }).run()}
          >
            <Heading3 size={15} aria-hidden="true" />
          </ToolbarButton>
          <ToolbarButton
            label="Párrafo"
            active={editorState?.paragraph && !editorState?.bulletList && !editorState?.orderedList}
            onClick={() => editor?.chain().focus().setParagraph().run()}
          >
            <Pilcrow size={15} aria-hidden="true" />
          </ToolbarButton>
          <span className={styles.toolbarDivider} aria-hidden="true" />
          <ToolbarButton
            label="Lista con viñetas"
            active={editorState?.bulletList}
            onClick={() => editor?.chain().focus().toggleBulletList().run()}
          >
            <List size={15} aria-hidden="true" />
          </ToolbarButton>
          <ToolbarButton
            label="Lista numerada"
            active={editorState?.orderedList}
            onClick={() => editor?.chain().focus().toggleOrderedList().run()}
          >
            <ListOrdered size={15} aria-hidden="true" />
          </ToolbarButton>
        </div>
        <EditorContent editor={editor} className={styles.editorContent} />
      </div>
    </div>
  );
}
