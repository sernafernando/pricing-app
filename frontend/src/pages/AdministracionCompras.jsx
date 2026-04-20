import { useEffect, useState } from 'react';
import { useSearchParams } from 'react-router-dom';
import { ShoppingCart, FileText, Wallet, Users, RefreshCw, BookOpen } from 'lucide-react';
import { usePermisos } from '../contexts/PermisosContext';
import TabPedidosCompra from '../components/compras/TabPedidosCompra';
import TabOrdenesPago from '../components/compras/TabOrdenesPago';
import TabCCProveedores from '../components/compras/TabCCProveedores';
import TabReconciliacion from '../components/compras/TabReconciliacion';
import TabSaleDocumentCatalog from '../components/compras/TabSaleDocumentCatalog';
import styles from './AdministracionCompras.module.css';

// ── Tabs metadata ───────────────────────────────────────────────
const TABS = [
  {
    id: 'pedidos',
    label: 'Pedidos',
    icon: FileText,
    permiso: 'administracion.ver_ordenes_compra',
    Component: TabPedidosCompra,
  },
  {
    id: 'ordenes-pago',
    label: 'Órdenes de Pago',
    icon: Wallet,
    permiso: 'administracion.ver_ordenes_compra',
    Component: TabOrdenesPago,
  },
  {
    id: 'cc-proveedores',
    label: 'CC Proveedores',
    icon: Users,
    permiso: 'administracion.ver_cuentas_corrientes',
    Component: TabCCProveedores,
  },
  {
    id: 'reconciliacion',
    label: 'Reconciliación',
    icon: RefreshCw,
    permiso: 'administracion.ver_cuentas_corrientes',
    Component: TabReconciliacion,
  },
  {
    id: 'catalogo-sd',
    label: 'Catálogo SD',
    icon: BookOpen,
    permiso: 'administracion.ver_ordenes_compra',
    Component: TabSaleDocumentCatalog,
  },
];

export default function AdministracionCompras() {
  const { tienePermiso } = usePermisos();
  const [searchParams] = useSearchParams();

  // Tabs visibles según permiso (gating obligatorio por AGENTS.md).
  const visibleTabs = TABS.filter((t) => tienePermiso(t.permiso));

  // COMPRAS-7.6: soporte deep-link via query param `tab` (ej. `?tab=ordenes-pago&op_id=123`).
  const tabFromQuery = searchParams.get('tab');
  const initialTab =
    (tabFromQuery && visibleTabs.find((t) => t.id === tabFromQuery)?.id) || visibleTabs[0]?.id || null;

  const [activeTabId, setActiveTabId] = useState(initialTab);

  // Si el query param cambia mientras la página está abierta (ej: usuario
  // clickea "Ver OP" desde Caja en otra tab y vuelve), re-sincronizar.
  useEffect(() => {
    if (tabFromQuery && visibleTabs.some((t) => t.id === tabFromQuery) && tabFromQuery !== activeTabId) {
      setActiveTabId(tabFromQuery);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [tabFromQuery]);

  const activeTab = visibleTabs.find((t) => t.id === activeTabId);
  const ActiveComponent = activeTab?.Component;

  return (
    <div className={styles.container}>
      {/* Header */}
      <div className={styles.header}>
        <div className={styles.headerLeft}>
          <ShoppingCart size={24} />
          <h1 className={styles.title}>Administración — Compras</h1>
        </div>
        <div className={styles.breadcrumbs}>
          <span>Administración</span>
          <span className={styles.breadcrumbSep}>/</span>
          <span className={styles.breadcrumbActive}>Compras</span>
        </div>
      </div>

      {/* Tabs nav */}
      {visibleTabs.length > 0 ? (
        <>
          <nav className={styles.tabsNav} role="tablist">
            {visibleTabs.map((tab) => {
              const Icon = tab.icon;
              const isActive = tab.id === activeTabId;
              return (
                <button
                  key={tab.id}
                  role="tab"
                  aria-selected={isActive}
                  className={isActive ? styles.tabBtnActive : styles.tabBtn}
                  onClick={() => setActiveTabId(tab.id)}
                >
                  <Icon size={16} />
                  <span>{tab.label}</span>
                </button>
              );
            })}
          </nav>

          {/* Tab content — cada tab tiene su propio permission gate */}
          <div className={styles.tabContent}>
            {ActiveComponent && tienePermiso(activeTab.permiso) && <ActiveComponent />}
          </div>
        </>
      ) : (
        <div className={styles.emptyState}>
          No tenés permisos para ver ningún panel de Compras. Contactá al administrador.
        </div>
      )}
    </div>
  );
}
