import { useState } from 'react';
import { Truck, ClipboardCheck } from 'lucide-react';
import { usePermisos } from '../contexts/PermisosContext';
import EnviosVistaFlag from '../components/EnviosVistaFlag';
import CheckColectaReadonly from '../components/CheckColectaReadonly';
import styles from './SeguimientoEnvios.module.css';
import { registrarPagina } from '../registry/tabRegistry';

registrarPagina({
  pagePath: '/seguimiento-envios',
  pageLabel: 'Seguimiento Envíos',
  tabs: [
    { tabKey: 'envios', label: 'Envíos' },
    { tabKey: 'check-colecta', label: 'Check Colecta' },
  ],
});

export default function SeguimientoEnvios() {
  const [tabActiva, setTabActiva] = useState('envios');
  const { tienePermiso } = usePermisos();

  return (
    <div className={styles.container}>
      <div className={styles.tabsContainer}>
        {tienePermiso('seguimiento_envios.ver') && (
          <button
            className={`${styles.tabBtn} ${tabActiva === 'envios' ? styles.tabActiva : ''}`}
            onClick={() => setTabActiva('envios')}
          >
            <Truck size={16} />
            Envíos
          </button>
        )}
        {tienePermiso('seguimiento_envios.ver') && (
          <button
            className={`${styles.tabBtn} ${tabActiva === 'check-colecta' ? styles.tabActiva : ''}`}
            onClick={() => setTabActiva('check-colecta')}
          >
            <ClipboardCheck size={16} />
            Check Colecta
          </button>
        )}
      </div>

      {tienePermiso('seguimiento_envios.ver') && tabActiva === 'envios' && <EnviosVistaFlag />}
      {tienePermiso('seguimiento_envios.ver') && tabActiva === 'check-colecta' && <CheckColectaReadonly />}
    </div>
  );
}
