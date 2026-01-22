# 🤝 Guía de Contribución - Pricing App

Bienvenido al proyecto Pricing App. Esta guía te va a enseñar paso a paso cómo contribuir al proyecto, especialmente si sos trainee o estás empezando.

## 📋 Tabla de Contenidos

- [Requisitos Previos](#-requisitos-previos)
- [Setup Inicial (Primera Vez)](#-setup-inicial-primera-vez)
- [Flujo de Trabajo para Contribuir](#-flujo-de-trabajo-para-contribuir)
- [Convenciones de Código](#-convenciones-de-código)
- [Usando Cursor para Desarrollo](#-usando-cursor-para-desarrollo)
- [Creando un Pull Request](#-creando-un-pull-request)
- [Code Review](#-code-review)
- [Tipos de Contribuciones](#-tipos-de-contribuciones)
- [Ayuda y Soporte](#-ayuda-y-soporte)

---

## 🛠️ Requisitos Previos

Antes de empezar, asegurate de tener instalado lo siguiente en tu máquina Windows:

### Software Necesario

1. **Git para Windows**
   - Descargar de: https://git-scm.com/download/win
   - Durante instalación, elegir "Git Bash" como terminal
   - Verificar instalación: Abrir PowerShell y escribir `git --version`

2. **Python 3.11+**
   - Descargar de: https://www.python.org/downloads/
   - ⚠️ **IMPORTANTE**: Durante instalación, tildar "Add Python to PATH"
   - Verificar: `python --version` en PowerShell

3. **Node.js 18+**
   - Descargar de: https://nodejs.org/ (versión LTS)
   - Verificar: `node --version` y `npm --version`

4. **PostgreSQL 14+**
   - Descargar de: https://www.postgresql.org/download/windows/
   - Durante instalación, anotar el password que elijas
   - Verificar: Abrir pgAdmin (se instala con PostgreSQL)

5. **Cursor IDE**
   - Descargar de: https://cursor.sh/
   - Es un fork de VS Code con AI integrado
   - Instalar extensiones recomendadas (ver abajo)

### Extensiones de Cursor Recomendadas

Abrir Cursor, ir a Extensions (Ctrl+Shift+X) y buscar:

- **Python** (Microsoft) - Soporte para Python
- **Pylance** (Microsoft) - IntelliSense para Python
- **ESLint** - Linter para JavaScript/React
- **Prettier** - Formateo de código
- **GitLens** - Visualización de Git avanzada
- **Thunder Client** - Para probar APIs (opcional)

### Configurar Git

Abrir PowerShell o Git Bash y configurar tu identidad:

```bash
git config --global user.name "Tu Nombre"
git config --global user.email "tu-email@ejemplo.com"
```

---

## 🚀 Setup Inicial (Primera Vez)

### Paso 1: Fork del Repositorio

1. Ir a https://github.com/TU_ORG/pricing-app (reemplazar con la URL real)
2. Hacer click en el botón **"Fork"** arriba a la derecha
3. Esto crea una copia del repo en tu cuenta de GitHub

### Paso 2: Clonar tu Fork

Abrir PowerShell o Git Bash en la carpeta donde querés tener el proyecto:

```bash
# Clonar tu fork (reemplazar TU_USUARIO con tu username de GitHub)
git clone https://github.com/TU_USUARIO/pricing-app.git

# Entrar al directorio
cd pricing-app

# Agregar el repo original como "upstream" (para mantener sincronizado)
git remote add upstream https://github.com/TU_ORG/pricing-app.git

# Verificar que quedó bien configurado
git remote -v
```

Deberías ver algo como:
```
origin    https://github.com/TU_USUARIO/pricing-app.git (fetch)
origin    https://github.com/TU_USUARIO/pricing-app.git (push)
upstream  https://github.com/TU_ORG/pricing-app.git (fetch)
upstream  https://github.com/TU_ORG/pricing-app.git (push)
```

### Paso 3: Abrir el Proyecto en Cursor

1. Abrir Cursor
2. File → Open Folder
3. Seleccionar la carpeta `pricing-app` que clonaste
4. Cursor va a detectar el proyecto y cargar todo

### Paso 4: Setup del Backend (Python + FastAPI)

Abrir una terminal en Cursor (Terminal → New Terminal) o PowerShell en la carpeta del proyecto:

```bash
# Navegar al directorio backend
cd backend

# Crear entorno virtual
python -m venv venv

# Activar entorno virtual (WINDOWS)
venv\Scripts\activate

# Deberías ver (venv) al inicio de tu línea de comando

# Instalar dependencias
pip install -r requirements.txt
```

⚠️ **Si `pip install` da error**, puede ser que necesites actualizar pip:
```bash
python -m pip install --upgrade pip
pip install -r requirements.txt
```

#### Configurar Base de Datos

1. Abrir pgAdmin
2. Crear una nueva base de datos llamada `pricing_db_dev`
3. Crear archivo `.env` en la carpeta `backend/`:

```bash
# En la carpeta backend/, crear archivo .env
# Copiar este contenido y ajustar los valores:

DATABASE_URL=postgresql://postgres:TU_PASSWORD@localhost/pricing_db_dev
SECRET_KEY=desarrollo-secreto-cambiar-en-produccion-min-32-chars
ALGORITHM=HS256
ACCESS_TOKEN_EXPIRE_MINUTES=10080

# ERP API (pedirle al maintainer las credenciales reales)
ERP_BASE_URL=http://localhost
ERP_PRODUCTOS_ENDPOINT=/consulta?intExpgr_id=64
ERP_STOCK_ENDPOINT=/consulta?opName=ItemStock&intStor_id=1&intItem_id=-1

# MercadoLibre (opcional para desarrollo)
ML_CLIENT_ID=
ML_CLIENT_SECRET=
ML_USER_ID=
ML_REFRESH_TOKEN=

# Mapbox (opcional para Turbo Routing)
MAPBOX_ACCESS_TOKEN=

# Environment
ENVIRONMENT=development
```

#### Ejecutar Migraciones de Base de Datos

Con el entorno virtual activado:

```bash
# Aplicar migraciones
alembic upgrade head
```

Si funciona, ¡perfecto! Si da error, pedí ayuda al maintainer.

#### Arrancar el Backend

```bash
# Con el entorno virtual activado
uvicorn app.main:app --reload --host 0.0.0.0 --port 8002
```

Deberías ver algo como:
```
INFO:     Uvicorn running on http://0.0.0.0:8002
INFO:     Application startup complete.
```

Abrir navegador en http://localhost:8002/docs y deberías ver la documentación automática de FastAPI.

**✅ Backend corriendo!**

### Paso 5: Setup del Frontend (React + Vite)

Abrir **OTRA terminal** en Cursor (el backend debe seguir corriendo en la primera):

```bash
# Navegar al directorio frontend
cd frontend

# Instalar dependencias
npm install
```

#### Configurar Variables de Entorno

Crear archivo `.env` en la carpeta `frontend/`:

```bash
VITE_API_URL=http://localhost:8002/api
```

#### Arrancar el Frontend

```bash
npm run dev
```

Deberías ver:
```
  VITE v5.x.x  ready in XXX ms

  ➜  Local:   http://localhost:5173/
  ➜  Network: use --host to expose
```

Abrir navegador en http://localhost:5173 y deberías ver la app.

**✅ Frontend corriendo!**

---

## 🔄 Flujo de Trabajo para Contribuir

### Paso 1: Sincronizar con el Repo Original

Antes de empezar a trabajar, SIEMPRE sincronizá tu fork con el repo original:

```bash
# Ir a la rama main
git checkout main

# Traer cambios del repo original
git fetch upstream

# Mergear cambios en tu main local
git merge upstream/main

# Subir cambios a tu fork en GitHub
git push origin main
```

### Paso 2: Crear una Nueva Branch

**NUNCA trabajes directamente en `main`**. Siempre crear una branch nueva:

```bash
# Nombre descriptivo según el tipo de cambio
git checkout -b feature/nombre-descriptivo
# o
git checkout -b fix/nombre-del-bug
# o
git checkout -b refactor/nombre-del-refactor
```

Ejemplos:
```bash
git checkout -b feature/agregar-filtro-por-categoria
git checkout -b fix/corregir-calculo-markup
git checkout -b refactor/migrate-pydantic-v2
```

### Paso 3: Hacer tus Cambios

Acá es donde trabajás. Algunas buenas prácticas:

1. **Commits pequeños y frecuentes** - No esperar a terminar todo para hacer commit
2. **Mensajes descriptivos** - Explicar QUÉ y POR QUÉ
3. **Seguir convenciones** - Ver sección [Convenciones de Código](#-convenciones-de-código)

#### Hacer Commits

```bash
# Ver qué archivos cambiaste
git status

# Agregar archivos específicos
git add backend/app/api/endpoints/productos.py
git add frontend/src/pages/Productos.jsx

# O agregar todos los cambios (cuidado, revisar antes con git status)
git add .

# Hacer commit con mensaje descriptivo
git commit -m "feat: agregar filtro por categoría en productos"
```

### Paso 4: Testear Localmente

Antes de hacer push, SIEMPRE testear que funcione:

**Backend:**
```bash
# Backend debe estar corriendo sin errores
# Probar endpoints en http://localhost:8002/docs
```

**Frontend:**
```bash
# Frontend debe estar corriendo sin errores de consola
# Probar la funcionalidad manualmente en el navegador
# Abrir DevTools (F12) y revisar que no haya errores
```

**Checklist:**
- [ ] Backend arranca sin errores
- [ ] Frontend arranca sin errores
- [ ] La funcionalidad que agregaste/modificaste funciona
- [ ] No hay errores en la consola del navegador
- [ ] No rompiste ninguna funcionalidad existente

### Paso 5: Push a tu Fork

```bash
# Subir tu branch a tu fork en GitHub
git push origin feature/nombre-descriptivo
```

Si es la primera vez que pusheas esta branch, Git te va a dar un mensaje con un comando. Copiá y pegá ese comando.

---

## 📝 Convenciones de Código

### Mensajes de Commit

Seguimos **Conventional Commits**:

```
<tipo>[scope]: <descripción>

[cuerpo opcional]
[footer opcional]
```

**Tipos:**
- `feat` - Nueva feature
- `fix` - Corrección de bug
- `refactor` - Refactor (ni bug ni feature)
- `docs` - Cambios en documentación
- `style` - Formateo, punto y coma faltante, etc (no afecta lógica)
- `test` - Agregar tests
- `chore` - Cambios en build, herramientas, etc

**Ejemplos:**
```bash
git commit -m "feat: agregar endpoint de exportación de productos"
git commit -m "fix: corregir cálculo de markup en rebate ML"
git commit -m "refactor: extraer lógica de pricing a service"
git commit -m "docs: actualizar README con nuevas features"
git commit -m "style: formatear código con black"
git commit -m "chore: actualizar dependencias de frontend"
```

### Estilo de Código

#### Backend (Python)

- **Naming:**
  - Archivos: `snake_case.py`
  - Funciones/variables: `snake_case`
  - Clases: `PascalCase`
  
- **Type hints:** Obligatorios en funciones públicas
  ```python
  def calcular_markup(precio: float, costo: float) -> float:
      return ((precio - costo) / costo) * 100
  ```

- **Docstrings:** Para funciones complejas
  ```python
  def funcion_compleja(param1: str, param2: int) -> dict:
      """
      Descripción breve de lo que hace.
      
      Args:
          param1: Descripción del parámetro
          param2: Descripción del parámetro
          
      Returns:
          Diccionario con resultado
      """
      pass
  ```

#### Frontend (JavaScript/React)

- **Naming:**
  - Componentes: `PascalCase.jsx` (ej: `ProductosList.jsx`)
  - Hooks/Utils: `camelCase.js` (ej: `useDebounce.js`)
  - CSS Modules: `PascalCase.module.css` (mismo nombre que componente)

- **Componentes funcionales:**
  ```jsx
  function MiComponente({ prop1, prop2 }) {
    // Lógica
    
    return (
      <div>
        {/* JSX */}
      </div>
    );
  }
  
  export default MiComponente;
  ```

- **Destructuring:** Preferir destructuring de props
  ```jsx
  // ✅ Bien
  function Producto({ nombre, precio }) { ... }
  
  // ❌ Evitar
  function Producto(props) {
    const nombre = props.nombre;
    const precio = props.precio;
  }
  ```

### Estructura de Archivos

**Backend - Nuevo Endpoint:**
```
backend/app/api/endpoints/
├── mi_nuevo_endpoint.py    # Endpoints
```

**Frontend - Nuevo Componente:**
```
frontend/src/
├── components/
│   ├── MiComponente.jsx
│   └── MiComponente.module.css
├── pages/
│   ├── MiPagina.jsx
│   └── MiPagina.module.css
```

---

## 🤖 Usando Cursor para Desarrollo

Cursor es un IDE con **AI integrado** que te ayuda a programar. Acá te explico cómo usarlo en este proyecto.

### 🎯 Setup Automático con `.cursorrules`

**¡Buenas noticias!** Este proyecto tiene un archivo `.cursorrules` en la raíz que Cursor **lee automáticamente** al iniciar cualquier conversación.

**Qué hace el `.cursorrules`:**
- ✅ Recuerda a Cursor cargar los skills relevantes según tu tarea
- ✅ Enforza Pydantic v2 syntax (NUNCA v1)
- ✅ Enforza `datetime.now(UTC)` en lugar de `utcnow()` deprecated
- ✅ Recuerda checks de permisos en operaciones de escritura
- ✅ Provee convenciones de naming y estructura del proyecto
- ✅ Lista common pitfalls a evitar

**¿Qué significa esto para vos?**

Cursor ya sabe las reglas del proyecto. NO necesitás configurar nada extra.

**Best Practice:**

Aunque Cursor lee `.cursorrules` automáticamente, es mejor ser **explícito** cuando pedís algo:

```
❌ Menos claro:
"Crear un endpoint para productos"

✅ Más claro:
"Crear un endpoint para listar productos con paginación.
Usa el skill pricing-app-backend."
```

Ser explícito ayuda a:
1. Cursor a cargar el contexto completo del skill
2. Vos a entender qué patrones se están usando
3. Debugging si algo no funciona como esperabas

### Cursor AI (Ctrl+K o Ctrl+L)

Cursor tiene dos modos principales:

1. **Ctrl+K** - Inline editing (editar código existente)
2. **Ctrl+L** - Chat (hacer preguntas, generar código nuevo)

### Usando el Sistema de Skills

Este proyecto tiene **Skills** (documentación para agentes AI) que le enseñan a Cursor cómo trabajar con nuestro código.

#### Cargar Skills Automáticamente

Cuando trabajés en una tarea específica, mencioná el skill relevante en el chat:

**Ejemplo 1: Crear un endpoint nuevo**
```
Yo: Necesito crear un endpoint para listar clientes con paginación.
Usa el skill pricing-app-backend.

Cursor: [carga el skill y genera código siguiendo los patrones del proyecto]
```

**Ejemplo 2: Crear un componente React**
```
Yo: Crear un componente de tabla para mostrar productos.
Usa el skill pricing-app-frontend.

Cursor: [genera componente con CSS Modules y Tesla Design]
```

#### Skills Disponibles

- `pricing-app-backend` - Para trabajo en backend (FastAPI, SQLAlchemy)
- `pricing-app-frontend` - Para trabajo en frontend (React, Zustand)
- `pricing-app-permissions` - Para sistema de permisos
- `pricing-app-pricing-logic` - Para cálculos de precios
- `pricing-app-ml-integration` - Para integración con MercadoLibre
- `pricing-app-design` - Para estilos y Tesla Design System

**Ver todos los skills en:** [`AGENTS.md`](AGENTS.md)

### Ejemplos de Uso de Cursor

#### Ejemplo 1: Agregar un Filtro Nuevo

**Pregunta a Cursor (Ctrl+L):**
```
Necesito agregar un filtro por rango de precios en la página de productos.
Usa el skill pricing-app-frontend.

Debe:
1. Agregar inputs para precio min/max en la sección de filtros
2. Actualizar la query cuando cambien los valores
3. Seguir el estilo Tesla Design System
```

**Cursor va a:**
- Cargar el skill `pricing-app-frontend`
- Ver cómo están hechos los otros filtros
- Generar código consistente con el proyecto

#### Ejemplo 2: Crear un Endpoint

**Pregunta a Cursor:**
```
Crear endpoint GET /api/productos/stats que retorne:
- Total de productos
- Total con stock
- Total sin stock
- Promedio de markup

Usa el skill pricing-app-backend.
```

**Cursor va a:**
- Crear el endpoint en el archivo correcto
- Usar las dependencias correctas (get_db, get_current_user)
- Seguir la estructura de otros endpoints del proyecto
- Agregar validación de permisos si es necesario

#### Ejemplo 3: Refactorizar Código

**Seleccionar código, Ctrl+K, escribir:**
```
Refactorizar esta función para usar async/await y separar la lógica de negocio en un service.
```

### Tips para Usar Cursor Efectivamente

1. **Sé específico** - Mientras más detallado, mejor el resultado
2. **Menciona los skills** - Ayuda a Cursor a seguir los patrones del proyecto
3. **Itera** - Si el resultado no es perfecto, pedile que ajuste
4. **Revisá el código** - SIEMPRE revisar lo que genera antes de commitear
5. **Preguntá por qué** - Si no entendés algo, preguntale a Cursor que te explique

### ⚠️ Cosas a Evitar con Cursor

- ❌ No commitear código generado sin entenderlo
- ❌ No aceptar cambios que rompan convenciones del proyecto
- ❌ No usar Cursor como "black box" - aprender de lo que genera
- ❌ No generar código sin testear primero

### 🔧 Troubleshooting Cursor

**Problema: Cursor no sigue las reglas del proyecto**

✅ **Solución:**
1. Verificá que el archivo `.cursorrules` existe en la raíz del proyecto
2. Reiniciá Cursor (a veces necesita reload)
3. Mencioná explícitamente el skill: "Usa el skill pricing-app-backend"
4. Si sigue sin funcionar, copiá manualmente el contenido del skill en el chat

**Problema: Cursor genera código con sintaxis Pydantic v1**

✅ **Solución:**
```
Cursor, estás usando sintaxis Pydantic v1 deprecated.
Este proyecto usa Pydantic v2.

NUNCA uses:
- class Config:
- .dict()
- .json()

SIEMPRE usa:
- model_config = ConfigDict(...)
- .model_dump()
- .model_dump_json()

Reescribí el código con Pydantic v2.
```

**Problema: No sé qué skill usar**

✅ **Solución:**

Consultá esta tabla rápida:

| Estoy trabajando en... | Skill a usar |
|------------------------|--------------|
| Endpoint FastAPI | `pricing-app-backend` |
| Componente React | `pricing-app-frontend` |
| API MercadoLibre | `pricing-app-ml-integration` |
| Cálculo de precios | `pricing-app-pricing-logic` |
| Sistema de permisos | `pricing-app-permissions` |
| Estilos/diseño | `pricing-app-design` |

Ver lista completa en [`AGENTS.md`](AGENTS.md).

---

## 🔀 Creando un Pull Request

### Paso 1: Verificar tus Cambios

Antes de abrir el PR, revisar:

```bash
# Ver todos los commits de tu branch
git log --oneline main..HEAD

# Ver todos los archivos que cambiaste
git diff main...HEAD --name-only

# Ver el diff completo
git diff main...HEAD
```

**Checklist antes de crear PR:**
- [ ] Todos los commits tienen mensajes descriptivos
- [ ] El código funciona localmente (backend + frontend)
- [ ] No hay errores en consola
- [ ] Seguiste las convenciones de código
- [ ] No incluiste archivos de configuración personal (.env, .vscode, etc)

### Paso 2: Push Final

```bash
# Asegurar que tu branch esté actualizada
git push origin feature/nombre-descriptivo
```

### Paso 3: Abrir el PR en GitHub

1. Ir a tu fork en GitHub: `https://github.com/TU_USUARIO/pricing-app`
2. GitHub va a mostrar un banner amarillo con "Compare & pull request" - hacer click
3. Verificar que:
   - **Base repository:** TU_ORG/pricing-app (el repo original)
   - **Base branch:** `main`
   - **Head repository:** TU_USUARIO/pricing-app (tu fork)
   - **Compare branch:** `feature/nombre-descriptivo` (tu branch)

### Paso 4: Escribir Descripción del PR

Usar este template:

```markdown
## Descripción

Breve descripción de qué hace este PR.

## Tipo de cambio

- [ ] Bug fix (cambio que arregla un issue)
- [ ] Nueva feature (cambio que agrega funcionalidad)
- [ ] Breaking change (fix o feature que causa que funcionalidad existente no funcione como antes)
- [ ] Refactor (cambio que no arregla bug ni agrega feature)
- [ ] Documentación

## ¿Cómo se probó?

Describir cómo probaste los cambios:

- [ ] Backend arranca sin errores
- [ ] Frontend arranca sin errores
- [ ] Probé manualmente la funcionalidad
- [ ] No hay errores en consola del navegador

## Screenshots (si aplica)

Si hay cambios visuales, agregar screenshots.

## Checklist

- [ ] Mi código sigue las convenciones del proyecto
- [ ] Revisé mi propio código antes de crear el PR
- [ ] Comenté partes complejas del código
- [ ] Mis commits siguen Conventional Commits
- [ ] Probé que funcione localmente
```

### Paso 5: Crear el PR

Hacer click en **"Create pull request"**.

---

## 👀 Code Review

### Qué Esperar

1. **Feedback del maintainer** - Va a revisar tu código y puede:
   - Aprobar y mergear ✅
   - Pedir cambios 🔄
   - Hacer comentarios/preguntas 💬

2. **Cambios solicitados** - Si te piden cambios:
   ```bash
   # Hacer los cambios en tu branch local
   # ... editar archivos ...
   
   # Commitear los cambios
   git add .
   git commit -m "fix: aplicar feedback de code review"
   
   # Push (el PR se actualiza automáticamente)
   git push origin feature/nombre-descriptivo
   ```

3. **Merge** - Cuando el PR sea aprobado, el maintainer lo va a mergear.

### Cómo Responder a Feedback

**✅ Bueno:**
```
Gracias por el feedback. Tenés razón, cambié la validación para usar Pydantic.
Pusheé los cambios en commit abc123.
```

**❌ Evitar:**
```
ok
```

Siempre agradecer el feedback y explicar qué cambios hiciste.

---

## 🎯 Tipos de Contribuciones

### Contribuciones Aceptadas

- ✅ **Bug fixes** - Arreglar bugs existentes
- ✅ **Nuevas features** - Solo si se discutieron primero en un issue
- ✅ **Refactors** - Mejorar código existente sin cambiar funcionalidad
- ✅ **Documentación** - Mejorar README, CONTRIBUTING, skills, etc
- ✅ **Tests** - Agregar tests (cuando exista el framework de testing)
- ✅ **Performance** - Optimizaciones

### Antes de Empezar una Feature Grande

Si querés agregar algo grande (no un bug fix simple), **PRIMERO abrir un Issue** para discutir:

1. Ir a Issues en GitHub
2. Click en "New Issue"
3. Explicar:
   - Qué querés agregar
   - Por qué es útil
   - Cómo lo implementarías

Esperar feedback del maintainer antes de empezar a codear.

### Contribuciones que NO se Aceptan

- ❌ Cambios sin issue previo (para features grandes)
- ❌ Código que rompe funcionalidad existente
- ❌ Cambios que no siguen las convenciones
- ❌ PRs sin descripción o contexto
- ❌ Código sin testear

---

## ❓ Ayuda y Soporte

### Dónde Pedir Ayuda

1. **Issues de GitHub** - Para bugs o preguntas sobre el proyecto
2. **PR Comments** - Para preguntas sobre tu PR específico
3. **Slack/Discord** (si aplica) - Para preguntas rápidas

### Preguntas Frecuentes

#### "No puedo instalar las dependencias de Python"

Intentar:
```bash
python -m pip install --upgrade pip
pip install -r requirements.txt
```

Si sigue fallando, ver qué package específico falla y googlear el error.

#### "Alembic da error al migrar"

Asegurate que:
1. PostgreSQL esté corriendo
2. La base de datos `pricing_db_dev` existe
3. El `DATABASE_URL` en `.env` es correcto

#### "El frontend no conecta con el backend"

Verificar:
1. Backend esté corriendo en `http://localhost:8002`
2. Frontend tenga `VITE_API_URL=http://localhost:8002/api` en `.env`
3. No haya CORS errors en consola del navegador

#### "Git me pide usuario/password cada vez"

Configurar SSH keys o usar credential helper:
```bash
git config --global credential.helper wincred
```

#### "Cursor no carga los skills"

Los skills se cargan cuando los mencionás explícitamente en el chat:
```
Usa el skill pricing-app-backend.
```

O asegurate que el archivo `AGENTS.md` existe en la raíz del proyecto.

---

## 🎓 Recursos para Aprender

### Si sos nuevo en Git/GitHub

- [Git Tutorial - Atlassian](https://www.atlassian.com/git/tutorials)
- [GitHub Skills](https://skills.github.com/)
- [Learn Git Branching](https://learngitbranching.js.org/) (interactivo)

### Si sos nuevo en Python/FastAPI

- [FastAPI Tutorial](https://fastapi.tiangolo.com/tutorial/)
- [Python Official Tutorial](https://docs.python.org/3/tutorial/)
- [Real Python](https://realpython.com/) (tutoriales prácticos)

### Si sos nuevo en React

- [React Official Tutorial](https://react.dev/learn)
- [React con Vite](https://vitejs.dev/guide/)

### Documentación del Proyecto

- [README.md](README.md) - Overview del proyecto
- [AGENTS.md](AGENTS.md) - Sistema de skills y guidelines
- [Skills Directory](skills/) - Skills específicos por tecnología

---

## 📜 Licencia

Al contribuir a este proyecto, aceptás que tus contribuciones serán licenciadas bajo la misma licencia del proyecto.

---

## 🙏 Agradecimientos

Gracias por contribuir al proyecto. Cada PR, por más chico que sea, ayuda a mejorar la aplicación.

Si tenés dudas, no dudes en preguntar. **No hay preguntas tontas.** Todos empezamos desde cero.

¡Happy coding! 🚀
