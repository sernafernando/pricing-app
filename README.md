# 💰 Pricing App - Sistema de Gestión de Precios e E-commerce

Sistema integral de gestión de precios, inventario, ventas y logística para operaciones de e-commerce. Integra múltiples canales de venta (Mercado Libre, Tienda Nube), sincronización con ERP, análisis de rentabilidad y sistema de routing logístico.

> **¿Querés contribuir?** Lee la [**Guía de Contribución**](CONTRIBUTING.md) para aprender cómo colaborar con el proyecto.

## 📋 Tabla de Contenidos

- [Características](#-características)
- [Tecnologías](#-tecnologías)
- [Requisitos](#-requisitos)
- [Instalación](#-instalación)
- [Configuración](#-configuración)
- [Uso](#-uso)
- [Contribuir](#-contribuir)
- [Navegación por Teclado](#-navegación-por-teclado-keyboard-shortcuts)
- [Estructura del Proyecto](#-estructura-del-proyecto)
- [Sistema de Agentes AI](#-sistema-de-agentes-ai)
- [API Endpoints](#-api-endpoints)
- [Roles y Permisos](#-roles-y-permisos)
- [Despliegue](#-despliegue)

## ✨ Características

### 🎯 Gestión de Precios y Productos

- 📊 Visualización de productos con múltiples tipos de precio (Clásica, Rebate, Ofertas, Web Transferencia)
- ✏️ Edición inline de precios con validación en tiempo real
- 🎨 Sistema de marcado por colores para categorización visual
- 📈 Cálculo automático de markups por tipo de precio
- 🔄 Sincronización bidireccional con sistema ERP
- 💾 Sistema de versionado y auditoría de cambios de precios
- 🏷️ Gestión de listas de precios personalizadas

### 📊 Analytics y Métricas

#### Dashboard MercadoLibre
- 📈 Métricas de ventas pre-calculadas con agregación diaria
- 📊 Análisis de rentabilidad por marca, categoría y subcategoría
- 💰 Tracking de comisiones y costos de envío ML
- 📉 Análisis de markup promedio por canal
- 🎯 Filtrado por PM (Product Manager) asignado
- 📅 Comparación de períodos (día, semana, mes, año)
- 🏪 Filtrado por tienda oficial

#### Dashboard Tienda Nube
- 📊 Métricas de ventas agregadas por marca y categoría
- 💵 Análisis de rentabilidad y márgenes
- 🔄 Sincronización automática de órdenes
- 📈 Tracking de performance por producto

#### Dashboard Ventas Fuera ML
- 💼 Análisis de ventas en canales propios
- 📊 Rentabilidad por marca y producto
- 🎯 Top productos más vendidos
- 💰 Tracking de costos y márgenes

### 🚛 Logística y Fulfillment

#### Turbo Routing (Sistema de Envíos)
- 📍 Geocodificación automática de direcciones con Mapbox
- 🗺️ Generación automática de zonas de reparto con K-Means clustering
- 👤 Gestión de motoqueros y asignaciones
- 🔄 Asignación automática y manual de envíos
- 📊 Estadísticas de performance por motoquero
- 🚫 Banlist de envíos problemáticos
- 📦 Tracking de envíos en tiempo real

#### Pedidos de Preparación
- 📋 Listado de pedidos pendientes de preparación
- 🔍 Filtrado por estado, fecha y vendedor
- ✅ Gestión de estados de preparación
- 📦 Exportación de pedidos para logística

### 💵 Análisis de Rentabilidad

#### Offsets de Ganancia
- 📊 Sistema de ajustes de costos por marca, categoría, subcategoría o producto
- 🎯 Tipos de offset: monto fijo, por unidad, porcentaje del costo
- 📈 Cálculo de rentabilidad real con offsets aplicados
- 🔄 Gestión de grupos y filtros de offsets
- 📉 Tracking de consumo de offsets

#### Rentabilidad Multi-Canal
- 📊 Análisis unificado de rentabilidad por canal (ML, TN, Ventas Directas)
- 💰 Desglose de costos: producto, comisiones, envío, offsets
- 📈 Markup real vs. markup objetivo
- 🎯 Cards de rentabilidad por marca/categoría/producto

### 🔄 Integraciones y Sincronización

#### MercadoLibre
- 🔐 OAuth 2.0 flow completo
- 📦 Sincronización de productos publicados
- 🛒 Tracking de órdenes y shipping
- 📊 Métricas de ventas en tiempo real
- 🔄 Webhooks para actualizaciones automáticas
- 🏪 Soporte para múltiples tiendas oficiales

#### Tienda Nube
- 🛒 Sincronización de órdenes
- 📦 Actualización de inventario
- 💵 Tracking de ventas

#### ERP (GBP Parser)
- 📊 Sincronización de tablas maestras (items, clientes, vendedores)
- 💰 Actualización de costos y precios
- 📦 Tracking de stock en tiempo real
- 🔄 Sincronización incremental optimizada
- 📋 Importación de transacciones comerciales

### 👥 Gestión de Usuarios y Permisos

- 🔐 Sistema de autenticación con JWT
- 👥 Roles jerárquicos: Superadmin, Admin, Gerente, Pricing, Viewer
- 🔒 Permisos granulares por funcionalidad
- 🎯 Asignación de PMs a marcas específicas
- 🔑 Gestión de contraseñas por administradores
- 📊 Permisos contextuales por módulo

### 🎨 Experiencia de Usuario

- 🌓 Dark mode completo con diseño Tesla
- ⌨️ Navegación por teclado optimizada para productividad
- 📱 Diseño responsive
- 🔔 Sistema de notificaciones en tiempo real
- 📊 Stats dinámicos en navbar
- 🎨 Design tokens para consistencia visual

### 🛠️ Herramientas Avanzadas

- 📥 Múltiples formatos de exportación (Excel, CSV)
- 🧮 Calculadora de precios con markup inteligente
- 📋 Sistema de banlist para productos y MLAs
- 🔍 Búsqueda avanzada con múltiples filtros
- 📊 Auditoría completa de cambios
- 🚫 Gestión de vendedores excluidos
- 📦 Sistema de pre-armados manuales

## 🛠️ Tecnologías

### Backend
- **Python 3.11+**
- **FastAPI** - Framework web moderno y rápido
- **SQLAlchemy 2.0** - ORM para PostgreSQL con async support
- **Alembic** - Migraciones de base de datos
- **PostgreSQL 14+** - Base de datos relacional
- **Pydantic v2** - Validación de datos y settings
- **python-jose** - Manejo de JWT
- **passlib + bcrypt** - Hashing de contraseñas
- **httpx** - Cliente HTTP async para APIs externas
- **openpyxl** - Generación de archivos Excel
- **scikit-learn** - K-Means clustering para zonas de reparto
- **redis** - Cache y rate limiting (opcional)

### Frontend
- **React 18** - Biblioteca UI con Concurrent Features
- **Vite 5** - Build tool ultra rápido
- **Axios** - Cliente HTTP
- **Zustand** - State management ligero
- **React Router v6** - Routing declarativo
- **CSS Modules** - Scoped styles
- **Tesla Design System** - Design tokens y componentes reutilizables

### DevOps & Tools
- **Systemd** - Gestión de servicios (backend)
- **Nginx** - Reverse proxy y servidor estático
- **Let's Encrypt** - Certificados SSL
- **Git** - Control de versiones
- **GitHub** - Hosting y CI/CD

## 📦 Requisitos

- Python 3.11 o superior
- Node.js 18+ y npm
- PostgreSQL 14+
- Sistema operativo: Linux (producción) / Windows/Mac (desarrollo)
- Mapbox API key (para geocoding en Turbo Routing)
- MercadoLibre App credentials (para integración ML)

## 🚀 Instalación

### Backend

```bash
# Navegar al directorio backend
cd backend

# Crear entorno virtual
python3.11 -m venv venv

# Activar entorno virtual
# En Linux/Mac:
source venv/bin/activate
# En Windows:
venv\Scripts\activate

# Instalar dependencias
pip install -r requirements.txt

# Configurar variables de entorno
cp .env.example .env
# Editar .env con tus credenciales

# Ejecutar migraciones Alembic
alembic upgrade head
```

### Frontend

```bash
# Navegar al directorio frontend
cd frontend

# Instalar dependencias
npm install

# Configurar variables de entorno
cp .env.example .env
# Editar .env con la URL del API
```

## ⚙️ Configuración

### Base de Datos

```sql
-- Crear base de datos
CREATE DATABASE pricing_db;

-- Crear usuario
CREATE USER pricing_user WITH PASSWORD 'tu_password_seguro';

-- Otorgar permisos
GRANT ALL PRIVILEGES ON DATABASE pricing_db TO pricing_user;
```

### Variables de Entorno

**Backend (.env)**
```env
# Database
DATABASE_URL=postgresql://pricing_user:password@localhost/pricing_db

# JWT
SECRET_KEY=tu_secret_key_super_seguro_y_largo_min_32_chars
ALGORITHM=HS256
ACCESS_TOKEN_EXPIRE_MINUTES=10080

# ERP API
ERP_BASE_URL=https://tu-erp.com
ERP_PRODUCTOS_ENDPOINT=/consulta?intExpgr_id=64
ERP_STOCK_ENDPOINT=/consulta?opName=ItemStock&intStor_id=1&intItem_id=-1

# MercadoLibre
ML_CLIENT_ID=tu_ml_client_id
ML_CLIENT_SECRET=tu_ml_client_secret
ML_USER_ID=tu_ml_user_id
ML_REFRESH_TOKEN=tu_ml_refresh_token

# Mapbox (para Turbo Routing)
MAPBOX_ACCESS_TOKEN=pk.ey...

# Google Sheets (opcional)
GOOGLE_SHEETS_ID=tu_sheet_id
GOOGLE_SERVICE_ACCOUNT_FILE=app/credentials/service-account.json

# Environment
ENVIRONMENT=production
```

**Frontend (.env)**
```env
VITE_API_URL=http://localhost:8002/api
```

### Migraciones

El proyecto usa **Alembic** para migraciones de base de datos:

```bash
# Ver historial de migraciones
alembic history

# Aplicar todas las migraciones pendientes
alembic upgrade head

# Crear nueva migración automática
alembic revision --autogenerate -m "descripción del cambio"

# Revertir última migración
alembic downgrade -1
```

## 🎯 Uso

### Desarrollo

**Backend:**
```bash
cd backend
source venv/bin/activate
uvicorn app.main:app --reload --host 0.0.0.0 --port 8002
```

**Frontend:**
```bash
cd frontend
npm run dev
```

Acceder a: `http://localhost:5173`

### Producción

**Backend (con systemd):**
```bash
sudo systemctl start pricing-api
sudo systemctl enable pricing-api
sudo systemctl status pricing-api
```

**Frontend:**
```bash
npm run build
# Servir archivos estáticos desde /var/www/html/pricing-app/frontend/dist
```

### Scripts de Sincronización

El proyecto incluye múltiples scripts en `backend/app/scripts/` para sincronización de datos:

```bash
# Sincronización completa de tablas maestras ERP
python app/scripts/sync_erp_master_tables_full.py

# Sincronización incremental de tablas maestras
python app/scripts/sync_erp_master_tables_incremental.py

# Sincronización de órdenes ML
python app/scripts/sync_ml_orders_incremental.py

# Sincronización de publicaciones ML
python app/scripts/sync_ml_publications_incremental.py

# Agregar métricas ML (diario, corre vía cron)
python app/scripts/agregar_metricas_ml_incremental.py

# Agregar métricas ventas fuera ML
python app/scripts/agregar_metricas_fuera_ml.py

# Agregar métricas Tienda Nube
python app/scripts/agregar_metricas_tienda_nube.py
```

## 🤝 Contribuir

¿Querés contribuir al proyecto? ¡Genial! Tenemos una guía completa para ayudarte.

### Para Empezar

1. **Lee la [Guía de Contribución](CONTRIBUTING.md)** - Documento completo con setup, workflow y convenciones
2. **Familiarizate con el proyecto** - Explora el código, lee el [AGENTS.md](AGENTS.md)
3. **Busca un issue** - O crea uno nuevo para discutir tu idea
4. **Hace un fork** - Y seguí el workflow de la guía

### Quick Start para Contributors

```bash
# 1. Fork y clonar
git clone https://github.com/TU_USUARIO/pricing-app.git
cd pricing-app

# 2. Agregar upstream
git remote add upstream https://github.com/TU_ORG/pricing-app.git

# 3. Crear branch
git checkout -b feature/mi-feature

# 4. Hacer cambios, commitear
git add .
git commit -m "feat: descripción del cambio"

# 5. Push y crear PR
git push origin feature/mi-feature
```

### Qué Contribuir

- 🐛 **Bug fixes** - Arreglar bugs reportados en Issues
- ✨ **Features** - Nuevas funcionalidades (discutir primero en un Issue)
- 📚 **Documentación** - Mejorar docs, READMEs, skills
- ♻️ **Refactors** - Mejorar código existente
- 🎨 **UI/UX** - Mejoras visuales y de experiencia

### Convenciones Rápidas

**Commits:**
```bash
feat: agregar nueva funcionalidad
fix: corregir bug
refactor: refactorizar código
docs: actualizar documentación
style: formateo de código
chore: tareas de mantenimiento
```

**Código:**
- Backend: `snake_case` para archivos/funciones, `PascalCase` para clases
- Frontend: `PascalCase` para componentes, `camelCase` para funciones/variables
- Siempre testear localmente antes de crear PR

### Recursos

- [CONTRIBUTING.md](CONTRIBUTING.md) - Guía completa paso a paso
- [AGENTS.md](AGENTS.md) - Guidelines y sistema de skills
- [Issues](https://github.com/TU_ORG/pricing-app/issues) - Bugs y features

### Preguntas?

- Abrí un Issue con la etiqueta "question"
- Comentá en un PR existente
- Contactá al maintainer

---

## ⌨️ Navegación por Teclado (Keyboard Shortcuts)

El sistema incluye un completo sistema de navegación por teclado diseñado para maximizar la productividad.

### 🎯 Navegación en Tabla

| Atajo | Acción |
|-------|--------|
| <kbd>Enter</kbd> | Activar modo navegación |
| <kbd>↑</kbd> <kbd>↓</kbd> <kbd>←</kbd> <kbd>→</kbd> | Navegar por celdas (una a la vez) |
| <kbd>Shift</kbd> + <kbd>↑</kbd> | Ir al inicio de la tabla |
| <kbd>Shift</kbd> + <kbd>↓</kbd> | Ir al final de la tabla |
| <kbd>Re Pág</kbd> (PageUp) | Subir 10 filas |
| <kbd>Av Pág</kbd> (PageDown) | Bajar 10 filas |
| <kbd>Home</kbd> | Ir a primera columna |
| <kbd>End</kbd> | Ir a última columna |
| <kbd>Enter</kbd> o <kbd>Espacio</kbd> | Editar celda activa |
| <kbd>Tab</kbd> (en edición) | Navegar entre campos del formulario |
| <kbd>Esc</kbd> | Salir de edición (mantiene navegación) |

**Nota:** Solo puedes navegar por las 4 columnas de precios: Precio Clásica, Precio Rebate, Mejor Oferta y Web Transf.

### ⚡ Acciones Rápidas (en fila activa)

| Atajo | Acción |
|-------|--------|
| <kbd>1</kbd> | Marcar como Rojo |
| <kbd>2</kbd> | Marcar como Amarillo |
| <kbd>3</kbd> | Marcar como Verde |
| <kbd>4</kbd> | Marcar como Azul |
| <kbd>5</kbd> | Marcar como Naranja |
| <kbd>6</kbd> | Marcar como Violeta |
| <kbd>7</kbd> | Marcar como Rosa |
| <kbd>8</kbd> | Marcar como Gris |
| <kbd>9</kbd> | Marcar como Cyan |
| <kbd>R</kbd> | Toggle Rebate ON/OFF |
| <kbd>W</kbd> | Toggle Web Transferencia ON/OFF |
| <kbd>O</kbd> | Toggle Out of Cards |

### 🔍 Filtros Rápidos

| Atajo | Acción |
|-------|--------|
| <kbd>Ctrl</kbd> + <kbd>F</kbd> | Focus en búsqueda |
| <kbd>Alt</kbd> + <kbd>M</kbd> | Toggle filtro Marcas |
| <kbd>Alt</kbd> + <kbd>S</kbd> | Toggle filtro Subcategorías |
| <kbd>Alt</kbd> + <kbd>P</kbd> | Toggle filtro PMs |
| <kbd>Alt</kbd> + <kbd>C</kbd> | Toggle filtro Colores |
| <kbd>Alt</kbd> + <kbd>A</kbd> | Toggle filtro Auditoría |
| <kbd>Alt</kbd> + <kbd>F</kbd> | Toggle filtros avanzados |

### 🌐 Acciones Globales

| Atajo | Acción |
|-------|--------|
| <kbd>Ctrl</kbd> + <kbd>E</kbd> | Abrir modal de exportar |
| <kbd>Ctrl</kbd> + <kbd>K</kbd> | Calcular Web Transferencia masivo |
| <kbd>?</kbd> | Mostrar/ocultar ayuda de shortcuts |

### 💡 Tips de Uso

1. **Modo Navegación**: Presiona <kbd>Enter</kbd> para activar el modo navegación. Verás un indicador en la parte inferior de la pantalla.

2. **Feedback Visual**: La celda activa se resalta con un borde azul pulsante y la fila completa tiene un fondo sutil.

3. **Edición Rápida**: Una vez en la celda deseada, presiona <kbd>Espacio</kbd> para editarla inmediatamente.

4. **Colores Rápidos**: Selecciona un producto y presiona un número del 1 al 9 para asignar un color sin necesidad del mouse.

5. **Escape Universal**: <kbd>Esc</kbd> siempre te saca de cualquier modo de edición o cierra paneles abiertos.

## 📁 Estructura del Proyecto

```
pricing-app/
├── backend/
│   ├── app/
│   │   ├── api/
│   │   │   ├── endpoints/          # Endpoints de la API
│   │   │   │   ├── auth.py         # Autenticación JWT
│   │   │   │   ├── productos.py    # CRUD de productos
│   │   │   │   ├── pricing.py      # Gestión de precios
│   │   │   │   ├── usuarios.py     # Gestión de usuarios
│   │   │   │   ├── roles.py        # Gestión de roles
│   │   │   │   ├── permisos.py     # Gestión de permisos
│   │   │   │   ├── ventas_ml.py    # Métricas ventas ML
│   │   │   │   ├── ventas_fuera_ml.py   # Métricas ventas propias
│   │   │   │   ├── ventas_tienda_nube.py # Métricas Tienda Nube
│   │   │   │   ├── dashboard_ml.py  # Dashboard ML pre-calculado
│   │   │   │   ├── rentabilidad.py  # Análisis de rentabilidad
│   │   │   │   ├── offsets_ganancia.py  # Offsets de costos
│   │   │   │   ├── turbo_routing.py # Sistema de routing logístico
│   │   │   │   ├── pedidos_preparacion.py # Pedidos pendientes
│   │   │   │   ├── clientes.py      # Gestión de clientes
│   │   │   │   ├── marcas_pm.py     # Asignación de PMs
│   │   │   │   ├── auditoria.py     # Historial de cambios
│   │   │   │   ├── mla_banlist.py   # Banlist de MLAs
│   │   │   │   ├── produccion_banlist.py # Banlist producción
│   │   │   │   ├── sync_ml.py       # Sincronización ML
│   │   │   │   ├── erp_sync.py      # Sincronización ERP
│   │   │   │   ├── gbp_parser.py    # Parser de ERP
│   │   │   │   ├── notificaciones.py # Sistema de notificaciones
│   │   │   │   ├── configuracion.py # Configuración global
│   │   │   │   └── ...
│   │   │   └── deps.py              # Dependencias compartidas
│   │   ├── core/
│   │   │   ├── config.py            # Configuración (Pydantic Settings)
│   │   │   ├── database.py          # Conexión DB
│   │   │   └── security.py          # Hashing y JWT
│   │   ├── models/                  # Modelos SQLAlchemy
│   │   │   ├── usuario.py
│   │   │   ├── producto.py
│   │   │   ├── venta_ml.py
│   │   │   ├── ml_venta_metrica.py
│   │   │   ├── motoquero.py
│   │   │   ├── zona_reparto.py
│   │   │   ├── asignacion_turbo.py
│   │   │   ├── offset_ganancia.py
│   │   │   └── ...
│   │   ├── services/                # Lógica de negocio
│   │   │   ├── pricing_service.py
│   │   │   ├── ml_service.py
│   │   │   ├── permisos_service.py
│   │   │   ├── geocoding_service.py
│   │   │   ├── kmeans_zone_service.py
│   │   │   ├── auto_assignment_service.py
│   │   │   └── ...
│   │   ├── utils/                   # Utilidades
│   │   │   ├── ml_metrics_calculator.py
│   │   │   └── ...
│   │   ├── scripts/                 # Scripts de sincronización
│   │   │   ├── sync_erp_master_tables_incremental.py
│   │   │   ├── sync_ml_orders_incremental.py
│   │   │   ├── agregar_metricas_ml_incremental.py
│   │   │   ├── agregar_metricas_fuera_ml.py
│   │   │   ├── sync_sale_orders_all.py
│   │   │   └── ...
│   │   └── main.py                  # App FastAPI
│   ├── alembic/
│   │   ├── versions/                # Migraciones DB
│   │   └── env.py
│   ├── requirements.txt
│   └── .env
├── frontend/
│   ├── src/
│   │   ├── components/
│   │   │   ├── Navbar.jsx           # Barra de navegación
│   │   │   ├── ThemeToggle.jsx      # Toggle tema oscuro
│   │   │   ├── ModalTesla.jsx       # Modal genérico Tesla Design
│   │   │   ├── PricingModal.jsx     # Edición de precios
│   │   │   ├── ExportModal.jsx      # Modal de exportación
│   │   │   ├── CalcularWebModal.jsx # Cálculo masivo
│   │   │   └── turbo/               # Componentes Turbo Routing
│   │   ├── pages/
│   │   │   ├── Login.jsx            # Login
│   │   │   ├── Productos.jsx        # Tabla principal de productos
│   │   │   ├── DashboardMetricasML.jsx  # Dashboard ML
│   │   │   ├── DashboardVentasFuera.jsx # Dashboard ventas propias
│   │   │   ├── DashboardTiendaNube.jsx  # Dashboard TN
│   │   │   ├── TurboRouting.jsx     # Sistema de routing
│   │   │   ├── PedidosPreparacion.jsx   # Pedidos pendientes
│   │   │   ├── Clientes.jsx         # Gestión de clientes
│   │   │   ├── Admin.jsx            # Panel admin
│   │   │   ├── GestionPM.jsx        # Gestión de PMs
│   │   │   ├── MLABanlist.jsx       # Gestión banlist
│   │   │   ├── Banlist.jsx          # Banlist producción
│   │   │   ├── PreciosListas.jsx    # Precios por lista
│   │   │   ├── UltimosCambios.jsx   # Auditoría
│   │   │   ├── Notificaciones.jsx   # Centro de notificaciones
│   │   │   └── ...
│   │   ├── contexts/
│   │   │   ├── ThemeContext.jsx     # Dark mode
│   │   │   └── PermisosContext.jsx  # Permisos usuario
│   │   ├── hooks/
│   │   │   ├── useDebounce.js
│   │   │   ├── usePermisos.js
│   │   │   └── useServerPagination.js
│   │   ├── store/
│   │   │   └── authStore.js         # Zustand auth store
│   │   ├── services/
│   │   │   └── api.js               # Axios instance
│   │   ├── styles/
│   │   │   ├── design-tokens.css    # Design tokens
│   │   │   ├── buttons-tesla.css    # Botones Tesla
│   │   │   ├── modals-tesla.css     # Modales Tesla
│   │   │   ├── table-tesla.css      # Tablas Tesla
│   │   │   └── theme.css            # Variables tema
│   │   ├── App.jsx
│   │   └── main.jsx
│   ├── package.json
│   ├── vite.config.js
│   └── .env
├── skills/                          # Skills para agentes AI
│   ├── pricing-app-backend/
│   ├── pricing-app-frontend/
│   ├── pricing-app-ml-integration/
│   ├── pricing-app-pricing-logic/
│   ├── pricing-app-permissions/
│   └── pricing-app-design/
├── AGENTS.md                        # Guidelines para agentes AI
└── README.md
```

## 🤖 Sistema de Agentes AI

Este proyecto incluye un sistema completo de **Skills para Agentes AI** que permite a herramientas como Claude Code, Cursor, y otros agentes entender y trabajar con el codebase de forma consistente y eficiente.

### 📚 Arquitectura del Sistema

El sistema se compone de dos elementos principales:

#### 1. AGENTS.md - Guidelines Centrales

El archivo [`AGENTS.md`](AGENTS.md) en la raíz del proyecto contiene:

- **Guidelines cross-project** - Normas generales que aplican a todo el proyecto
- **Tabla de Skills disponibles** - Lista completa de skills genéricos y específicos del proyecto
- **Auto-invoke rules** - Tabla de acciones que automáticamente deben invocar skills específicos
- **Convenciones de código** - Naming, estructura, commit messages
- **Checklist de seguridad** - Para nuevos endpoints y features

#### 2. Skills Directory - Conocimiento Especializado

La carpeta [`skills/`](skills/) contiene skills modulares en formato markdown:

**Skills Genéricos (reutilizables):**
- `typescript` - Patrones TypeScript strict
- `react-19` - React 19 con React Compiler
- `zustand-5` - State management con Zustand
- `pytest` - Testing patterns con pytest
- `nextjs-15`, `tailwind-4`, `playwright`, etc.

**Skills Específicos de Pricing App:**
- [`pricing-app-backend`](skills/pricing-app-backend/SKILL.md) - FastAPI + SQLAlchemy + Alembic patterns
- [`pricing-app-frontend`](skills/pricing-app-frontend/SKILL.md) - React + Zustand + CSS Modules + Tesla Design
- [`pricing-app-ml-integration`](skills/pricing-app-ml-integration/SKILL.md) - MercadoLibre API patterns
- [`pricing-app-pricing-logic`](skills/pricing-app-pricing-logic/SKILL.md) - Pricing calculations y markup
- [`pricing-app-permissions`](skills/pricing-app-permissions/SKILL.md) - Sistema híbrido de permisos
- [`pricing-app-design`](skills/pricing-app-design/SKILL.md) - Tesla Design System patterns

### 🎯 Cómo Funciona

#### Auto-invoke (Invocación Automática)

Cuando un agente AI detecta ciertas acciones, **automáticamente** debe cargar el skill correspondiente:

```markdown
| Acción                              | Skill                          |
|-------------------------------------|--------------------------------|
| Creating/modifying FastAPI endpoints | pricing-app-backend           |
| Creating/modifying React components  | pricing-app-frontend          |
| Working with MercadoLibre API        | pricing-app-ml-integration    |
| Calculating product prices           | pricing-app-pricing-logic     |
| Implementing permission checks       | pricing-app-permissions       |
```

Ejemplo: Si estás creando un nuevo endpoint FastAPI, el agente automáticamente carga `pricing-app-backend` para seguir los patrones del proyecto (estructura de endpoints, manejo de errores, permisos, etc.).

#### Skill Sync

El proyecto incluye un mecanismo de sincronización que mantiene las tablas de auto-invoke en `AGENTS.md` actualizadas automáticamente desde los metadatos de cada skill:

```bash
# Regenerar tablas de auto-invoke en AGENTS.md
./skills/skill-sync/assets/sync.sh

# Ver qué cambiaría sin aplicar
./skills/skill-sync/assets/sync.sh --dry-run

# Sincronizar solo skills con scope específico
./skills/skill-sync/assets/sync.sh --scope pricing-app
```

### 📖 Estructura de un Skill

Cada skill es un archivo markdown con la siguiente estructura:

```markdown
# Skill Name

## Trigger
Cuándo debe invocarse este skill automáticamente.

## Context
Información de contexto sobre el proyecto/tecnología.

## Rules
Reglas y patrones específicos a seguir.

## Examples
Ejemplos de código comentados.

## Anti-patterns
Qué NO hacer y por qué.

## Metadata (opcional)
---
metadata:
  scope: pricing-app
  auto_invoke:
    - "Creating FastAPI endpoints"
    - "Working with SQLAlchemy models"
---
```

### 🚀 Beneficios

1. **Consistencia** - Todos los agentes siguen los mismos patrones
2. **Onboarding rápido** - Nuevos agentes entienden el proyecto inmediatamente
3. **Context-aware** - El agente sabe qué skill cargar según la tarea
4. **Modular** - Skills reutilizables entre proyectos
5. **Mantenible** - Documentación viva que evoluciona con el código
6. **Auto-sync** - Las tablas de auto-invoke se regeneran automáticamente

### 📝 Creando un Nuevo Skill

Si necesitás agregar un nuevo skill:

1. **Crear el directorio y archivo:**
   ```bash
   mkdir -p skills/mi-nuevo-skill
   touch skills/mi-nuevo-skill/SKILL.md
   ```

2. **Definir estructura básica** con trigger, context, rules, examples

3. **Agregar metadata** para auto-invoke (opcional):
   ```yaml
   ---
   metadata:
     scope: pricing-app
     auto_invoke:
       - "Working with my new feature"
   ---
   ```

4. **Sincronizar AGENTS.md:**
   ```bash
   ./skills/skill-sync/assets/sync.sh
   ```

O usar el skill `skill-creator` para que un agente lo haga por vos:
```bash
# El agente AI puede invocar el skill-creator para crear un nuevo skill
invoke_skill("skill-creator", "Create a skill for FastAPI testing patterns")
```

### 🔗 Links Útiles

- [AGENTS.md completo](AGENTS.md) - Guidelines y tablas de auto-invoke
- [Skill Sync README](skills/skill-sync/SKILL.md) - Documentación del sistema de sincronización
- [Skill Creator README](skills/skill-creator/SKILL.md) - Cómo crear skills automáticamente

### 💡 Casos de Uso

#### Para Desarrolladores Humanos
- **Onboarding**: Leer `AGENTS.md` y los skills relevantes antes de contribuir
- **Consulta**: Usar skills como referencia rápida de patrones del proyecto
- **Documentación**: Mantener skills actualizados cuando cambien los patrones

#### Para Agentes AI
- **Context loading**: Cargar skills automáticamente según la tarea
- **Pattern matching**: Seguir los patrones definidos en los skills
- **Code generation**: Generar código consistente con el proyecto
- **Refactoring**: Aplicar cambios masivos siguiendo las reglas del skill

---

## 🔌 API Endpoints

### Autenticación
- `POST /api/login` - Iniciar sesión
- `GET /api/me` - Obtener usuario actual

### Productos y Precios
- `GET /api/productos` - Listar productos (con filtros y paginación)
- `GET /api/productos/stats` - Estadísticas generales
- `PATCH /api/productos/{item_id}` - Actualizar precio
- `PATCH /api/productos/{item_id}/rebate` - Actualizar rebate
- `PATCH /api/productos/{item_id}/web-transferencia` - Actualizar web transf
- `PATCH /api/productos/{item_id}/out-of-cards` - Toggle out of cards
- `PATCH /api/productos/{item_id}/color` - Cambiar color de marcado
- `POST /api/productos/calcular-web-masivo` - Cálculo masivo web transf
- `POST /api/productos/exportar-rebate` - Exportar rebates ML
- `GET /api/exportar-clasica` - Exportar precios clásica
- `GET /api/exportar-web-transferencia` - Exportar web transf

### Usuarios y Permisos
- `GET /api/usuarios` - Listar usuarios
- `POST /api/usuarios` - Crear usuario
- `PATCH /api/usuarios/{id}` - Actualizar usuario
- `PATCH /api/usuarios/{id}/password` - Cambiar contraseña
- `GET /api/usuarios/pms` - Listar PMs
- `GET /api/roles` - Listar roles disponibles
- `GET /api/permisos` - Listar permisos disponibles
- `GET /api/permisos/usuario/{user_id}` - Permisos de un usuario
- `POST /api/permisos/usuario/{user_id}` - Actualizar permisos

### Métricas y Analytics

#### Dashboard MercadoLibre
- `GET /api/dashboard-ml/metricas-diarias` - Métricas agregadas por día
- `GET /api/dashboard-ml/metricas-por-marca` - Métricas por marca
- `GET /api/dashboard-ml/metricas-por-categoria` - Métricas por categoría
- `GET /api/dashboard-ml/metricas-por-subcategoria` - Métricas por subcategoría
- `GET /api/dashboard-ml/top-productos` - Top productos más vendidos
- `GET /api/dashboard-ml/comparacion-periodos` - Comparación entre períodos

#### Ventas Fuera ML
- `GET /api/ventas-fuera-ml` - Métricas de ventas propias
- `GET /api/ventas-fuera-ml/stats` - Estadísticas generales
- `GET /api/ventas-fuera-ml/por-marca` - Desglose por marca
- `GET /api/ventas-fuera-ml/top-productos` - Top productos

#### Ventas Tienda Nube
- `GET /api/ventas-tienda-nube` - Métricas TN
- `GET /api/ventas-tienda-nube/stats` - Estadísticas generales

### Rentabilidad
- `GET /api/rentabilidad/cards` - Cards de rentabilidad
- `GET /api/rentabilidad/desglose/{card_id}` - Desglose detallado
- `GET /api/offsets-ganancia` - Listar offsets
- `POST /api/offsets-ganancia` - Crear offset
- `PATCH /api/offsets-ganancia/{id}` - Actualizar offset
- `DELETE /api/offsets-ganancia/{id}` - Eliminar offset

### Turbo Routing
- `GET /api/turbo/envios/pendientes` - Envíos pendientes de asignación
- `GET /api/turbo/envios/todos` - Todos los envíos
- `GET /api/turbo/motoqueros` - Listar motoqueros
- `POST /api/turbo/motoqueros` - Crear motoquero
- `PUT /api/turbo/motoqueros/{id}` - Actualizar motoquero
- `DELETE /api/turbo/motoqueros/{id}` - Eliminar motoquero
- `GET /api/turbo/zonas` - Listar zonas de reparto
- `POST /api/turbo/zonas` - Crear zona
- `POST /api/turbo/zonas/auto-generar` - Auto-generar zonas con K-Means
- `POST /api/turbo/asignar-automatico` - Asignación automática
- `POST /api/turbo/asignacion/manual` - Asignación manual
- `GET /api/turbo/estadisticas` - Estadísticas de routing
- `POST /api/turbo/geocoding/batch` - Geocodificar lote de envíos
- `GET /api/turbo/banlist` - Banlist de envíos
- `POST /api/turbo/banlist` - Agregar a banlist

### Pedidos y Logística
- `GET /api/pedidos-preparacion` - Pedidos pendientes
- `PATCH /api/pedidos-preparacion/{id}/estado` - Cambiar estado
- `GET /api/pedidos-export` - Exportar pedidos para logística

### Clientes
- `GET /api/clientes` - Listar clientes
- `GET /api/clientes/{id}` - Detalle de cliente
- `POST /api/clientes` - Crear cliente
- `PATCH /api/clientes/{id}` - Actualizar cliente

### Product Managers
- `GET /api/marcas-pm` - Listar asignaciones PM-Marca
- `POST /api/marcas-pm/asignar` - Asignar PM a marca
- `DELETE /api/marcas-pm/{id}` - Eliminar asignación
- `GET /api/marcas-pm/marcas` - Listar todas las marcas

### Banlist
- `GET /api/mla-banlist` - Listar MLAs baneados
- `POST /api/mla-banlist` - Agregar MLA a banlist
- `DELETE /api/mla-banlist/{id}` - Eliminar MLA de banlist
- `GET /api/produccion-banlist` - Banlist de producción
- `POST /api/produccion-banlist` - Agregar a banlist producción
- `DELETE /api/produccion-banlist/{id}` - Eliminar de banlist

### Auditoría
- `GET /api/auditoria` - Historial de cambios
- `GET /api/auditoria/usuarios` - Usuarios con cambios
- `GET /api/auditoria/tipos-accion` - Tipos de acciones

### Sincronización
- `POST /api/sync/erp` - Sincronizar datos ERP
- `POST /api/sync-ml/items` - Sincronizar items ML
- `POST /api/sync-ml/orders` - Sincronizar órdenes ML
- `GET /api/sync/status` - Estado de sincronizaciones

### Configuración
- `GET /api/configuracion` - Obtener configuración global
- `PATCH /api/configuracion` - Actualizar configuración

### Notificaciones
- `GET /api/notificaciones` - Listar notificaciones del usuario
- `PATCH /api/notificaciones/{id}/leida` - Marcar como leída
- `POST /api/notificaciones/leer-todas` - Marcar todas como leídas

## 👥 Roles y Permisos

### SUPERADMIN
- ✅ Acceso total al sistema
- ✅ Gestión de usuarios y roles
- ✅ Cambio de contraseñas
- ✅ Gestión de permisos granulares
- ✅ Asignación de PMs
- ✅ Gestión de banlist
- ✅ Edición de todos los precios
- ✅ Exportaciones
- ✅ Visualización de auditoría
- ✅ Configuración global
- ✅ Acceso a todos los dashboards

### ADMIN
- ✅ Gestión de usuarios (excepto superadmins)
- ✅ Cambio de contraseñas
- ✅ Asignación de PMs
- ✅ Gestión de banlist
- ✅ Edición de todos los precios
- ✅ Exportaciones
- ✅ Visualización de auditoría
- ✅ Acceso a todos los dashboards
- ❌ Modificar configuración global

### GERENTE
- ✅ Edición de precios
- ✅ Exportaciones
- ✅ Visualización de auditoría
- ✅ Acceso a dashboards de ventas
- ✅ Gestión de pedidos
- ❌ Gestión de usuarios
- ❌ Asignación de PMs

### PRICING
- ✅ Edición de precios
- ✅ Exportaciones
- ✅ Visualización de productos
- ❌ Visualización de auditoría
- ❌ Gestión de usuarios
- ❌ Asignación de PMs
- ❌ Acceso a dashboards de rentabilidad

### VIEWER (Product Manager)
- ✅ Visualización de productos de sus marcas asignadas
- ✅ Dashboards filtrados por sus marcas
- ❌ Edición de precios
- ❌ Exportaciones
- ❌ Gestión de usuarios

## 🚀 Despliegue

### Configuración de Systemd (Backend)

```ini
# /etc/systemd/system/pricing-api.service
[Unit]
Description=Pricing API FastAPI
After=network.target postgresql.service

[Service]
Type=simple
User=www-data
WorkingDirectory=/var/www/html/pricing-app/backend
Environment="PATH=/var/www/html/pricing-app/backend/venv/bin"
ExecStart=/var/www/html/pricing-app/backend/venv/bin/uvicorn app.main:app --host 127.0.0.1 --port 8002 --workers 4
Restart=always
RestartSec=5

[Install]
WantedBy=multi-user.target
```

```bash
# Activar y arrancar servicio
sudo systemctl daemon-reload
sudo systemctl enable pricing-api
sudo systemctl start pricing-api
sudo systemctl status pricing-api

# Ver logs
sudo journalctl -u pricing-api -f
```

### Nginx (Reverse Proxy)

```nginx
server {
    listen 443 ssl http2;
    server_name pricing.tudominio.com;

    ssl_certificate /etc/letsencrypt/live/pricing.tudominio.com/fullchain.pem;
    ssl_certificate_key /etc/letsencrypt/live/pricing.tudominio.com/privkey.pem;
    ssl_protocols TLSv1.2 TLSv1.3;
    ssl_ciphers HIGH:!aNULL:!MD5;

    # Frontend (archivos estáticos)
    location / {
        root /var/www/html/pricing-app/frontend/dist;
        try_files $uri $uri/ /index.html;
        
        # Cache de assets
        location ~* \.(js|css|png|jpg|jpeg|gif|ico|svg|woff|woff2|ttf|eot)$ {
            expires 1y;
            add_header Cache-Control "public, immutable";
        }
    }

    # Backend API
    location /api {
        proxy_pass http://127.0.0.1:8002;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
        
        # Timeouts
        proxy_connect_timeout 60s;
        proxy_send_timeout 60s;
        proxy_read_timeout 60s;
    }

    # Security headers
    add_header X-Frame-Options "SAMEORIGIN" always;
    add_header X-Content-Type-Options "nosniff" always;
    add_header X-XSS-Protection "1; mode=block" always;
    add_header Referrer-Policy "no-referrer-when-downgrade" always;
}

# Redirect HTTP to HTTPS
server {
    listen 80;
    server_name pricing.tudominio.com;
    return 301 https://$server_name$request_uri;
}
```

### Build y Deploy Frontend

```bash
cd frontend
npm run build
sudo cp -r dist/* /var/www/html/pricing-app/frontend/dist/
sudo chown -R www-data:www-data /var/www/html/pricing-app/frontend/dist
```

### Cron Jobs para Sincronización

```bash
# Editar crontab
crontab -e

# Sincronización incremental cada 15 minutos
*/15 * * * * cd /var/www/html/pricing-app/backend && /var/www/html/pricing-app/backend/venv/bin/python app/scripts/sync_erp_master_tables_incremental.py >> /var/log/pricing-app/sync.log 2>&1

# Métricas ML diarias (corre a las 2 AM)
0 2 * * * cd /var/www/html/pricing-app/backend && /var/www/html/pricing-app/backend/venv/bin/python app/scripts/agregar_metricas_ml_incremental.py >> /var/log/pricing-app/metricas.log 2>&1

# Sincronización órdenes ML cada hora
0 * * * * cd /var/www/html/pricing-app/backend && /var/www/html/pricing-app/backend/venv/bin/python app/scripts/sync_ml_orders_incremental.py >> /var/log/pricing-app/ml-sync.log 2>&1
```

## 🎨 Temas

El sistema incluye soporte completo para tema oscuro y claro basado en **Tesla Design System**. El toggle se encuentra en la navbar.

**Variables CSS disponibles:**

```css
/* Colores de fondo */
--bg-primary, --bg-secondary, --bg-tertiary

/* Colores de texto */
--text-primary, --text-secondary, --text-inverse

/* Colores de marca */
--brand-primary, --success, --error, --warning, --info

/* Bordes */
--border-primary, --border-secondary

/* Sombras */
--shadow-sm, --shadow-md, --shadow-lg

/* Spacing */
--spacing-xs, --spacing-sm, --spacing-md, --spacing-lg, --spacing-xl

/* Typography */
--font-family-primary, --font-size-base, --font-weight-normal
```

## 🔒 Seguridad

### Buenas Prácticas Implementadas

- ✅ Autenticación JWT con tokens de corta duración
- ✅ Contraseñas hasheadas con bcrypt (12 rounds)
- ✅ Validación de inputs con Pydantic
- ✅ Protección CSRF (SameSite cookies)
- ✅ Rate limiting en endpoints críticos
- ✅ CORS configurado solo para dominios autorizados
- ✅ SQL injection prevention (ORM)
- ✅ XSS prevention (sanitización de inputs)
- ✅ HTTPS obligatorio en producción
- ✅ Security headers (Nginx)
- ✅ Logs de auditoría completos

### Checklist de Seguridad para Nuevos Endpoints

- [ ] Endpoint requiere autenticación (`Depends(get_current_user)`)
- [ ] Operaciones sensibles verifican permisos (`verificar_permiso()`)
- [ ] Inputs validados con Pydantic schemas
- [ ] Queries usan ORM o prepared statements
- [ ] Errores no exponen información sensible
- [ ] Rate limiting configurado si es necesario
- [ ] Logs de auditoría agregados

## 📊 Performance

### Backend Optimizations

- ✅ Async/await para operaciones I/O
- ✅ Connection pooling de PostgreSQL
- ✅ Paginación server-side en todos los listados
- ✅ Indexes en columnas frecuentemente consultadas
- ✅ Eager loading con `joinedload()` para evitar N+1 queries
- ✅ Cache en memoria para datos estáticos (marcas, categorías)
- ✅ Agregaciones pre-calculadas para dashboards

### Frontend Optimizations

- ✅ React.memo para componentes costosos
- ✅ Debounce en búsquedas (300ms)
- ✅ Lazy loading de rutas con React.lazy
- ✅ Virtualización de tablas largas (>100 items)
- ✅ Images optimizadas (WebP, lazy loading)
- ✅ Code splitting por ruta
- ✅ CSS Modules para scoped styles (sin overhead de runtime)

## 🐛 Debugging

### Backend

```bash
# Logs en desarrollo
uvicorn app.main:app --reload --log-level debug

# Logs en producción
sudo journalctl -u pricing-api -f --since "10 minutes ago"

# Ver queries SQL
# En .env: DATABASE_URL con echo=True
# o usar logging de SQLAlchemy
```

### Frontend

```bash
# Dev server con source maps
npm run dev

# Build con source maps
npm run build -- --sourcemap

# Analizar bundle size
npm run build -- --mode analyze
```

## 📝 Convenciones de Código

### Backend (Python)

- **Naming:** `snake_case` para archivos, funciones y variables
- **Models:** PascalCase para clases SQLAlchemy
- **Type hints:** Obligatorios en funciones públicas
- **Docstrings:** Google style para funciones complejas
- **Imports:** Agrupados (stdlib, third-party, local) y ordenados alfabéticamente

### Frontend (JavaScript/React)

- **Componentes:** PascalCase para archivos y nombres (`ProductosList.jsx`)
- **Hooks/Utils:** camelCase para archivos (`useDebounce.js`)
- **CSS Modules:** Mismo nombre que componente (`ProductosList.module.css`)
- **Naming:** camelCase para variables/funciones, PascalCase para componentes
- **Destructuring:** Preferir destructuring de props

## 📚 Recursos Adicionales

- [FastAPI Documentation](https://fastapi.tiangolo.com/)
- [React Documentation](https://react.dev/)
- [SQLAlchemy 2.0 Documentation](https://docs.sqlalchemy.org/en/20/)
- [Pydantic v2 Documentation](https://docs.pydantic.dev/2.0/)
- [Alembic Documentation](https://alembic.sqlalchemy.org/)

## 📞 Soporte

Para soporte o consultas, contactar al equipo de desarrollo interno.

## 📝 Licencia

Proyecto privado - Gauss Online © 2026

## 👨‍💻 Desarrolladores

Desarrollado con ❤️ por el equipo de Gauss Online con la asistencia de Claude (Anthropic).

---

**Última actualización:** Enero 2026
