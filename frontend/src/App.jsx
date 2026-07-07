import { BrowserRouter, Routes, Route, Navigate } from 'react-router-dom';
import { lazy, Suspense, useEffect, useState } from 'react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { useAuthStore } from './store/authStore';
import { ThemeProvider } from './contexts/ThemeContext';
import { PermisosProvider } from './contexts/PermisosContext';
import Login from './pages/Login';
import AppLayout from './components/AppLayout';
import ProtectedRoute from './components/ProtectedRoute';
import ErrorBoundary from './components/ErrorBoundary';
import ModalCalculadora from './components/ModalCalculadora';
import SmartRedirect from './components/SmartRedirect';
import PwaUpdatePrompt from './components/PwaUpdatePrompt';
import FichajeMobile from './pages/FichajeMobile';
import './styles/design-tokens.css';
import './styles/components.css';
import './styles/buttons-tesla.css';
import './styles/modals-tesla.css';
import './styles/table-tesla.css';
import './styles/theme.css';

// --- lazy page components (code-split into assets/lazy/) ---
const Productos = lazy(() => import('./pages/Productos'));
const Tienda = lazy(() => import('./pages/Tienda'));
const Admin = lazy(() => import('./pages/Admin'));
const UltimosCambios = lazy(() => import('./pages/UltimosCambios'));
const PreciosListas = lazy(() => import('./pages/PreciosListas'));
const GestionPM = lazy(() => import('./pages/GestionPM'));
const GestionAlertas = lazy(() => import('./pages/GestionAlertas'));
const Banlist = lazy(() => import('./pages/Banlist'));
const ItemsSinMLA = lazy(() => import('./pages/ItemsSinMLA'));
const DashboardMetricasML = lazy(() => import('./pages/DashboardMetricasML'));
const DashboardTPLink = lazy(() => import('./pages/DashboardTPLink'));
const DashboardVentasFuera = lazy(() => import('./pages/DashboardVentasFuera'));
const DashboardTiendaNube = lazy(() => import('./pages/DashboardTiendaNube'));
const Calculos = lazy(() => import('./pages/Calculos'));
const TestStatsDinamicos = lazy(() => import('./pages/TestStatsDinamicos'));
const Notificaciones = lazy(() => import('./pages/Notificaciones'));
const PedidosPreparacion = lazy(() => import('./pages/PedidosPreparacion'));
const Produccion = lazy(() => import('./pages/Produccion'));
const Prearmado = lazy(() => import('./pages/Prearmado'));
const PrearmadasDisponibles = lazy(() => import('./pages/PrearmadasDisponibles'));
const Clientes = lazy(() => import('./pages/Clientes'));
const TurboRouting = lazy(() => import('./pages/TurboRouting'));
const CuentasCorrientes = lazy(() => import('./pages/CuentasCorrientes'));
const ConfigOperaciones = lazy(() => import('./pages/ConfigOperaciones'));
const Rma = lazy(() => import('./pages/Rma'));
const ControlDeposito = lazy(() => import('./pages/ControlDeposito'));
const ClaimsDashboard = lazy(() => import('./pages/ClaimsDashboard'));
const MLQuestions = lazy(() => import('./pages/MLQuestions'));
const ConsultasRanking = lazy(() => import('./pages/ConsultasRanking'));
const Traza = lazy(() => import('./pages/Traza'));
const FreeShippingAlerts = lazy(() => import('./pages/FreeShippingAlerts'));
const SeguimientoEnvios = lazy(() => import('./pages/SeguimientoEnvios'));
const Empleados = lazy(() => import('./pages/Empleados'));
const RRHHPresentismo = lazy(() => import('./pages/RRHHPresentismo'));
const RRHHSanciones = lazy(() => import('./pages/RRHHSanciones'));
const RRHHVacaciones = lazy(() => import('./pages/RRHHVacaciones'));
const RRHHCuentaCorriente = lazy(() => import('./pages/RRHHCuentaCorriente'));
const RRHHHorarios = lazy(() => import('./pages/RRHHHorarios'));
const RRHHSueldos = lazy(() => import('./pages/RRHHSueldos'));
const RRHHHorasExtras = lazy(() => import('./pages/RRHHHorasExtras'));
const RRHHReportes = lazy(() => import('./pages/RRHHReportes'));
const RRHHCumpleanos = lazy(() => import('./pages/RRHHCumpleanos'));
const Tickets = lazy(() => import('./pages/Tickets'));
const ReescribirLH = lazy(() => import('./pages/ReescribirLH'));
const TicketsAdmin = lazy(() => import('./pages/TicketsAdmin'));
const AdministracionProveedores = lazy(() => import('./pages/AdministracionProveedores'));
const AdministracionBancos = lazy(() => import('./pages/AdministracionBancos'));
const AdministracionImpuestos = lazy(() => import('./pages/AdministracionImpuestos'));
const AdministracionCaja = lazy(() => import('./pages/AdministracionCaja'));
const AdministracionCompras = lazy(() => import('./pages/AdministracionCompras'));
const DocumentDesigner = lazy(() => import('./pages/DocumentDesigner'));

const queryClient = new QueryClient({
  defaultOptions: {
    queries: {
      retry: 1,
      staleTime: 30_000, // 30 s — avoids redundant refetches on tab switches
    },
  },
});

function PrivateRoute({ children }) {
  const isAuthenticated = useAuthStore((state) => state.isAuthenticated);
  return isAuthenticated ? children : <Navigate to="/login" />;
}

// --- uniform wrap: ErrorBoundary outside Suspense (matches DocumentDesigner's shape) ---
const routeFallback = (
  <div style={{ padding: '2rem', color: 'var(--cf-text-secondary)' }}>Cargando...</div>
);

// eslint-disable-next-line no-unused-vars -- Component is used as the JSX tag below
function lazyElement(Component) {
  return (
    <ErrorBoundary>
      <Suspense fallback={routeFallback}>
        <Component />
      </Suspense>
    </ErrorBoundary>
  );
}

// --- config: one entry per protected route (path preserved exactly) ---
const protectedRoutes = [
  { path: '/productos', component: Productos, permiso: 'productos.ver' },
  { path: '/tienda', component: Tienda, permiso: 'productos.ver_tienda' },
  { path: '/precios-listas', component: PreciosListas, permiso: 'productos.ver' },
  { path: '/ultimos-cambios', component: UltimosCambios, permiso: 'productos.ver_auditoria' },
  { path: '/admin', component: Admin, permiso: 'admin.ver_panel' },
  { path: '/gestion-pm', component: GestionPM, permiso: 'admin.gestionar_pms' },
  { path: '/gestion/alertas', component: GestionAlertas, permiso: 'alertas.gestionar' },
  { path: '/mla-banlist', component: Banlist, permiso: 'admin.gestionar_mla_banlist' },
  { path: '/dashboard-metricas-ml', component: DashboardMetricasML, permiso: 'ventas_ml.ver_dashboard' },
  { path: '/dashboard-tplink', component: DashboardTPLink, permiso: 'dashboard_tplink.ver' },
  { path: '/dashboard-ventas-fuera', component: DashboardVentasFuera, permiso: 'ventas_fuera.ver_dashboard' },
  { path: '/dashboard-tienda-nube', component: DashboardTiendaNube, permiso: 'ventas_tn.ver_dashboard' },
  { path: '/calculos', component: Calculos, permiso: 'reportes.ver_calculadora' },
  { path: '/items-sin-mla', component: ItemsSinMLA, permiso: 'admin.ver_items_sin_mla' },
  { path: '/test-stats-dinamicos', component: TestStatsDinamicos, permiso: 'admin.sincronizar' },
  { path: '/notificaciones', component: Notificaciones, permiso: 'reportes.ver_notificaciones' },
  { path: '/pedidos-preparacion', component: PedidosPreparacion, permiso: 'ordenes.ver_preparacion' },
  { path: '/produccion', component: Produccion, permiso: 'produccion.ver_combos' },
  { path: '/prearmado', component: Prearmado, permiso: 'produccion.prearmar_combos' },
  { path: '/prearmadas-disponibles', component: PrearmadasDisponibles, permiso: 'produccion.ver_prearmadas_stats' },
  { path: '/clientes', component: Clientes, permiso: 'clientes.ver' },
  { path: '/turbo-routing', component: TurboRouting, permiso: 'ordenes.gestionar_turbo_routing' },
  { path: '/cuentas-corrientes', component: CuentasCorrientes, permiso: 'reportes.ver_cuentas_corrientes' },
  { path: '/config-operaciones', component: ConfigOperaciones, permiso: 'envios_flex.config' },
  { path: '/rma', component: Rma, permiso: 'rma.ver' },
  { path: '/control-deposito', component: ControlDeposito, permiso: 'rma.control_deposito' },
  { path: '/claims', component: ClaimsDashboard, permiso: 'rma.ver' },
  { path: '/ml-preguntas', component: MLQuestions, permiso: 'ml_bot.ver' },
  { path: '/consultas/ranking', component: ConsultasRanking, permisos: ['consultas.ver_ranking', 'consultas.ver_mi_ranking'] },
  { path: '/traza', component: Traza, permiso: 'traza.ver' },
  { path: '/free-shipping-alerts', component: FreeShippingAlerts, permiso: 'alertas.ver_free_shipping' },
  { path: '/seguimiento-envios', component: SeguimientoEnvios, permiso: 'seguimiento_envios.ver' },
  { path: '/rrhh/empleados', component: Empleados, permiso: 'rrhh.ver' },
  { path: '/rrhh/presentismo', component: RRHHPresentismo, permiso: 'rrhh.ver' },
  { path: '/rrhh/sanciones', component: RRHHSanciones, permiso: 'rrhh.ver' },
  { path: '/rrhh/vacaciones', component: RRHHVacaciones, permiso: 'rrhh.ver' },
  { path: '/rrhh/cuenta-corriente', component: RRHHCuentaCorriente, permiso: 'rrhh.ver' },
  { path: '/rrhh/horarios', component: RRHHHorarios, permiso: 'rrhh.ver' },
  { path: '/rrhh/sueldos', component: RRHHSueldos, permiso: 'rrhh.ver' },
  { path: '/rrhh/horas-extras', component: RRHHHorasExtras, permiso: 'rrhh.ver_horas_extras' },
  { path: '/cumpleanos', component: RRHHCumpleanos },
  { path: '/rrhh/reportes', component: RRHHReportes, permiso: 'rrhh.ver' },
  // ── Administración (sector empresa) ────────────
  { path: '/administracion/proveedores', component: AdministracionProveedores, permiso: 'administracion.ver_proveedores' },
  { path: '/administracion/bancos', component: AdministracionBancos, permiso: 'administracion.ver_proveedores' },
  { path: '/administracion/impuestos', component: AdministracionImpuestos, permiso: 'administracion.ver_proveedores' },
  { path: '/administracion/caja', component: AdministracionCaja, permiso: 'administracion.ver_caja' },
  { path: '/administracion/compras', component: AdministracionCompras, permiso: 'administracion.ver_ordenes_compra' },
  { path: '/tickets', component: Tickets, permiso: 'tickets.ver' },
  { path: '/etiquetas/reescribir-lh', component: ReescribirLH, permiso: 'etiquetas.reescribir_lh' },
  { path: '/tickets/admin', component: TicketsAdmin, permiso: 'tickets.admin' },
  { path: '/document-designer', component: DocumentDesigner, permiso: 'documentos.disenar' },
];

// --- render helper: preserves the ProtectedRoute wrapping shape ---
function renderProtectedRoute({ path, component, permiso, permisos }) {
  const el = lazyElement(component);
  const guarded = (permiso || permisos)
    ? <ProtectedRoute permiso={permiso} permisos={permisos}>{el}</ProtectedRoute>
    : el; // routes with no per-route permission rely on the outer AppLayout guard
  return <Route key={path} path={path} element={guarded} />;
}

function App() {
  const checkAuth = useAuthStore((state) => state.checkAuth);
  const token = useAuthStore((state) => state.token);
  const isAuthenticated = useAuthStore((state) => state.isAuthenticated);
  const [mostrarCalculadora, setMostrarCalculadora] = useState(false);

  useEffect(() => {
    if (token) {
      checkAuth();
    }
  }, [token, checkAuth]);

  useEffect(() => {
    const handleKeyDown = (e) => {
      // Ctrl+P o Cmd+P para abrir calculadora
      if ((e.ctrlKey || e.metaKey) && e.key === 'p' && isAuthenticated) {
        e.preventDefault();
        setMostrarCalculadora(true);
      }
    };

    window.addEventListener('keydown', handleKeyDown);
    return () => window.removeEventListener('keydown', handleKeyDown);
  }, [isAuthenticated]);

  return (
    <QueryClientProvider client={queryClient}>
    <ThemeProvider>
      <PwaUpdatePrompt />
      <PermisosProvider>
        <BrowserRouter
          future={{
            v7_startTransition: true,
            v7_relativeSplatPath: true
          }}
        >
          <ModalCalculadora
            isOpen={mostrarCalculadora}
            onClose={() => setMostrarCalculadora(false)}
          />
          <Routes>
          <Route path="/login" element={<Login />} />
          <Route path="/fichaje" element={<FichajeMobile />} />
          <Route path="/" element={<ProtectedRoute><SmartRedirect /></ProtectedRoute>} />
          <Route element={
            <ProtectedRoute>
              <AppLayout />
            </ProtectedRoute>
          }>
            {protectedRoutes.map(renderProtectedRoute)}
          </Route>
          </Routes>
        </BrowserRouter>
      </PermisosProvider>
    </ThemeProvider>
    </QueryClientProvider>
  );
}

export default App;
