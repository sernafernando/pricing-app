/**
 * useDescriptionEditor — TipTap editor instance + toolbar-active-state
 * selector + the initial-content load effect, moved verbatim out of the
 * pre-decomposition `TnPublishModal.jsx` (non-goal to touch TipTap in this
 * PR). Split into its own hook file (sibling to `DescriptionEditor.jsx`) so
 * `react-refresh/only-export-components` stays happy — see repo convention
 * in `frontend/AGENTS.md`.
 */
import { useEffect } from 'react';
import { useEditor, useEditorState } from '@tiptap/react';
import StarterKit from '@tiptap/starter-kit';

export function useDescriptionEditor({ isOpen, ean, initialHtml }) {
  const editor = useEditor({
    extensions: [StarterKit],
    content: '',
  });

  // Re-render the toolbar when marks/nodes under the cursor change.
  const editorState = useEditorState({
    editor,
    selector: (ctx) => ({
      bold: ctx.editor?.isActive('bold') ?? false,
      italic: ctx.editor?.isActive('italic') ?? false,
      underline: ctx.editor?.isActive('underline') ?? false,
      strike: ctx.editor?.isActive('strike') ?? false,
      h1: ctx.editor?.isActive('heading', { level: 1 }) ?? false,
      h2: ctx.editor?.isActive('heading', { level: 2 }) ?? false,
      h3: ctx.editor?.isActive('heading', { level: 3 }) ?? false,
      paragraph: ctx.editor?.isActive('paragraph') ?? false,
      bulletList: ctx.editor?.isActive('bulletList') ?? false,
      orderedList: ctx.editor?.isActive('orderedList') ?? false,
    }),
  });

  useEffect(() => {
    if (!isOpen || !ean) return;
    if (initialHtml) editor?.commands.setContent(initialHtml);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [isOpen, ean]);

  return { editor, editorState };
}
