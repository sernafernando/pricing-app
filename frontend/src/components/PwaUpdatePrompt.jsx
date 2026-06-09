import Toast from './Toast';
import { usePwaUpdate } from '../hooks/usePwaUpdate';

/**
 * Global "new version available" prompt. Mount once at the app root.
 * Shows a non-intrusive bottom-right toast with an "Actualizar" button so the
 * user applies the update when convenient — never mid-form.
 */
export default function PwaUpdatePrompt() {
  const { needRefresh, applyUpdate, dismiss } = usePwaUpdate();

  if (!needRefresh) return null;

  return (
    <Toast
      toast={{ message: 'Hay una versión nueva disponible', type: 'info' }}
      onClose={dismiss}
      action={{ label: 'Actualizar', onClick: applyUpdate }}
    />
  );
}
