# 💰 Pricing App - Sistema de Gestión de Precios

Sistema integral de gestión de precios para productos ERP con integración a Mercado Libre, control de rebates, web transferencia y auditoría completa.

## 📋 Tabla de Contenidos

- [Características](#-características)
- [Tecnologías](#-tecnologías)
- [Requisitos](#-requisitos)
- [Instalación](#-instalación)
- [Configuración](#-configuración)
- [Uso](#-uso)
- [Navegación por Teclado](#-navegación-por-teclado-keyboard-shortcuts)
- [Estructura del Proyecto](#-estructura-del-proyecto)
- [API Endpoints](#-api-endpoints)
- [Roles y Permisos](#-roles-y-permisos)
- [Despliegue](#-despliegue)

## ✨ Características

### Gestión de Precios
- 📊 Visualización de productos con precios Clásica, Rebate, Ofertas y Web Transferencia
- ✏️ Edición inline de precios con validación
- 🎨 Sistema de marcado de colores para productos
- 📈 Cálculo automático de markups (Clásica, Rebate, Oferta, Web Transf.)
- 🔄 Sincronización con sistema ERP

### Rebates y Ofertas
- 🎯 Gestión de rebates de Mercado Libre con porcentajes personalizables
- 💎 Tracking de mejores ofertas activas
- 🚫 Sistema de Out of Cards para control de inventario
- 📅 Gestión de fechas de vigencia de ofertas

### Filtros Avanzados
- 🔍 Búsqueda inteligente por código, descripción, marca
- 🏷️ Filtros por marcas, subcategorías y PMs (Product Managers)
- 🎨 Filtro por colores de marcado
- 📊 Filtros de markup (positivo/negativo) por tipo de precio
- 📝 Filtros de auditoría por usuario, acción y fecha
- 💾 Filtros de stock y estado de precios

### Exportación y Cálculos
- 📥 Exportación a Excel de Rebate ML
- 📥 Exportación de precios Clásica con porcentaje adicional
- 📥 Exportación de Web Transferencia
- 🧮 Cálculo masivo de precios Web Transferencia
- 🚫 Banlist de MLAs para excluir de exportaciones

### Auditoría
- 📋 Historial completo de cambios de precios
- 👤 Tracking de usuario que realizó cada modificación
- 🕐 Timestamps de todas las operaciones
- 🔎 Filtros avanzados de auditoría

### Product Managers
- 👥 Asignación de PMs a marcas
- 🎯 Filtrado automático de productos por PM
- 📊 Gestión centralizada de asignaciones

### Usuarios y Seguridad
- 🔐 Sistema de autenticación con JWT
- 👥 Roles: Superadmin, Admin, Gerente, Pricing
- 🔒 Permisos granulares por funcionalidad
- 🔑 Cambio de contraseñas por administradores

## 🛠️ Tecnologías

### Backend
- **Python 3.11+**
- **FastAPI** - Framework web moderno y rápido
- **SQLAlchemy** - ORM para PostgreSQL
- **PostgreSQL** - Base de datos relacional
- **Pydantic** - Validación de datos
- **python-jose** - Manejo de JWT
- **passlib** - Hashing de contraseñas
- **openpyxl** - Generación de archivos Excel

### Frontend
- **React 18** - Biblioteca UI
- **Vite** - Build tool y dev server
- **Axios** - Cliente HTTP
- **Zustand** - State management
- **React Router** - Routing
- **CSS Variables** - Theming (Dark/Light mode)

## 📦 Requisitos

- Python 3.11 o superior
- Node.js 18+ y npm
- PostgreSQL 14+
- Sistema operativo: Linux (producción) / Windows/Mac (desarrollo)

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
DATABASE_URL=postgresql://pricing_user:password@localhost/pricing_db
SECRET_KEY=tu_secret_key_super_seguro_y_largo
ALGORITHM=HS256
ACCESS_TOKEN_EXPIRE_MINUTES=43200
```

**Frontend (.env)**
```env
VITE_API_URL=http://localhost:8002/api
```

### Migraciones

```bash
# Ejecutar scripts SQL en orden
psql -U pricing_user -d pricing_db -f backend/sql/create_tables.sql
psql -U pricing_user -d pricing_db -f backend/create_marcas_pm_table.sql
psql -U pricing_user -d pricing_db -f backend/create_mla_banlist_table.sql
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
```

**Frontend:**
```bash
npm run build
# Servir archivos estáticos desde /var/www/html/pricing-app/frontend/dist
```

## ⌨️ Navegación por Teclado (Keyboard Shortcuts)

El sistema incluye un completo sistema de navegación por teclado diseñado para maximizar la productividad.

### 🎯 Navegación en Tabla

| Atajo | Acción |
|-------|--------|
| <kbd>Enter</kbd> | Activar modo navegación |
| <kbd>Tab</kbd> | Siguiente columna de precio |
| <kbd>Shift</kbd> + <kbd>Tab</kbd> | Columna anterior |
| <kbd>↑</kbd> <kbd>↓</kbd> <kbd>←</kbd> <kbd>→</kbd> | Navegar por celdas (una a la vez) |
| <kbd>Shift</kbd> + <kbd>↑</kbd> | Ir al inicio de la tabla |
| <kbd>Shift</kbd> + <kbd>↓</kbd> | Ir al final de la tabla |
| <kbd>Re Pág</kbd> (PageUp) | Subir 10 filas |
| <kbd>Av Pág</kbd> (PageDown) | Bajar 10 filas |
| <kbd>Home</kbd> | Ir a primera columna |
| <kbd>End</kbd> | Ir a última columna |
| <kbd>Enter</kbd> o <kbd>Espacio</kbd> | Editar celda activa |
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
│   │   │   ├── endpoints/
│   │   │   │   ├── productos.py      # CRUD de productos y precios
│   │   │   │   ├── usuarios.py       # Gestión de usuarios
│   │   │   │   ├── auth.py          # Autenticación JWT
│   │   │   │   ├── marcas_pm.py     # Asignación de PMs
│   │   │   │   ├── mla_banlist.py   # Banlist de MLAs
│   │   │   │   └── auditoria.py     # Historial de cambios
│   │   │   └── deps.py              # Dependencias compartidas
│   │   ├── core/
│   │   │   ├── database.py          # Configuración DB
│   │   │   └── security.py          # Hashing y JWT
│   │   ├── models/                  # Modelos SQLAlchemy
│   │   │   ├── producto.py
│   │   │   ├── usuario.py
│   │   │   ├── auditoria.py
│   │   │   ├── marca_pm.py
│   │   │   └── mla_banlist.py
│   │   └── main.py                  # App FastAPI
│   ├── requirements.txt
│   └── .env
├── frontend/
│   ├── src/
│   │   ├── components/
│   │   │   ├── Navbar.jsx           # Barra de navegación
│   │   │   ├── ThemeToggle.jsx      # Toggle tema oscuro
│   │   │   ├── ExportModal.jsx      # Modal de exportación
│   │   │   ├── CalcularWebModal.jsx # Cálculo masivo
│   │   │   └── PricingModal.jsx     # Edición de precios
│   │   ├── pages/
│   │   │   ├── Login.jsx            # Página de login
│   │   │   ├── Productos.jsx        # Tabla principal
│   │   │   ├── Admin.jsx            # Panel admin
│   │   │   ├── GestionPM.jsx        # Gestión de PMs
│   │   │   ├── MLABanlist.jsx       # Gestión banlist
│   │   │   ├── PreciosListas.jsx    # Precios por lista
│   │   │   └── UltimosCambios.jsx   # Auditoría
│   │   ├── store/
│   │   │   └── authStore.js         # Zustand store
│   │   ├── styles/
│   │   │   └── theme.css            # Variables CSS tema
│   │   ├── App.jsx
│   │   └── main.jsx
│   ├── package.json
│   └── vite.config.js
└── README.md
```

## 🔌 API Endpoints

### Autenticación
- `POST /api/login` - Iniciar sesión
- `GET /api/me` - Obtener usuario actual

### Productos
- `GET /api/productos` - Listar productos (con filtros)
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

### Usuarios
- `GET /api/usuarios` - Listar usuarios
- `POST /api/usuarios` - Crear usuario
- `PATCH /api/usuarios/{id}` - Actualizar usuario
- `PATCH /api/usuarios/{id}/password` - Cambiar contraseña
- `GET /api/usuarios/pms` - Listar PMs

### Product Managers
- `GET /api/marcas-pm` - Listar asignaciones PM-Marca
- `POST /api/marcas-pm/asignar` - Asignar PM a marca
- `GET /api/marcas-pm/marcas` - Listar todas las marcas

### Banlist MLAs
- `GET /api/mla-banlist` - Listar MLAs baneados
- `POST /api/mla-banlist` - Agregar MLA a banlist
- `DELETE /api/mla-banlist/{id}` - Eliminar MLA de banlist

### Auditoría
- `GET /api/auditoria` - Historial de cambios
- `GET /api/auditoria/usuarios` - Usuarios con cambios
- `GET /api/auditoria/tipos-accion` - Tipos de acciones

### Filtros
- `GET /api/marcas` - Listar marcas disponibles
- `GET /api/subcategorias` - Listar subcategorías

## 👥 Roles y Permisos

### SUPERADMIN
- ✅ Acceso total al sistema
- ✅ Gestión de usuarios
- ✅ Cambio de contraseñas
- ✅ Asignación de PMs
- ✅ Gestión de banlist
- ✅ Edición de todos los precios
- ✅ Exportaciones
- ✅ Visualización de auditoría

### ADMIN
- ✅ Gestión de usuarios
- ✅ Cambio de contraseñas
- ✅ Asignación de PMs
- ✅ Gestión de banlist
- ✅ Edición de todos los precios
- ✅ Exportaciones
- ✅ Visualización de auditoría

### GERENTE
- ✅ Edición de precios
- ✅ Exportaciones
- ✅ Visualización de auditoría
- ❌ Gestión de usuarios
- ❌ Asignación de PMs

### PRICING
- ✅ Edición de precios
- ✅ Exportaciones
- ❌ Visualización de auditoría
- ❌ Gestión de usuarios
- ❌ Asignación de PMs

## 🚀 Despliegue

### Configuración de Systemd (Backend)

```ini
# /etc/systemd/system/pricing-api.service
[Unit]
Description=Pricing API FastAPI
After=network.target

[Service]
Type=simple
User=www-data
WorkingDirectory=/var/www/html/pricing-app/backend
Environment="PATH=/var/www/html/pricing-app/backend/venv/bin"
ExecStart=/var/www/html/pricing-app/backend/venv/bin/uvicorn app.main:app --host 127.0.0.1 --port 8002 --workers 4
Restart=always

[Install]
WantedBy=multi-user.target
```

### Nginx (Reverse Proxy)

```nginx
server {
    listen 443 ssl;
    server_name pricing.gaussonline.com.ar;

    ssl_certificate /etc/letsencrypt/live/pricing.gaussonline.com.ar/fullchain.pem;
    ssl_certificate_key /etc/letsencrypt/live/pricing.gaussonline.com.ar/privkey.pem;

    # Frontend
    location / {
        root /var/www/html/pricing-app/frontend/dist;
        try_files $uri $uri/ /index.html;
    }

    # Backend API
    location /api {
        proxy_pass http://127.0.0.1:8002;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
    }
}
```

### Build Frontend

```bash
cd frontend
npm run build
sudo cp -r dist/* /var/www/html/pricing-app/frontend/dist/
```

## 🎨 Temas

El sistema incluye soporte para tema oscuro y claro. El toggle se encuentra en la navbar.

**Variables CSS disponibles:**
- `--bg-primary`, `--bg-secondary`, `--bg-tertiary`
- `--text-primary`, `--text-secondary`, `--text-inverse`
- `--brand-primary`, `--success`, `--error`, `--warning`, `--info`
- `--border-primary`, `--border-secondary`
- `--shadow-sm`, `--shadow-md`, `--shadow-lg`

## 📝 Licencia

Proyecto privado - Gauss Online © 2025

## 👨‍💻 Desarrolladores

Desarrollado con ❤️ por el equipo de Gauss Online con la asistencia de Claude (Anthropic).

## 📞 Soporte

Para soporte o consultas, contactar al equipo de desarrollo interno.

---

**Última actualización:** Noviembre 2025
