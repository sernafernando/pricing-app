# 🌳 Branch Strategy - Pricing App

Este documento explica la estrategia de branches del proyecto para mantener un código estable y ordenado.

## 📋 Tabla de Contenidos

- [Overview](#overview)
- [Branch Structure](#branch-structure)
- [Workflow Completo](#workflow-completo)
- [Branch Protection Rules](#branch-protection-rules)
- [Ejemplos Prácticos](#ejemplos-prácticos)
- [Semantic Versioning](#semantic-versioning)
- [FAQs](#faqs)

---

## Overview

Pricing App usa una **estrategia Git Flow simplificada** con dos branches principales:

- **`main`** - Producción (código estable en producción)
- **`develop`** - Desarrollo (integración de features)

Y branches temporales para trabajo diario:

- **`feature/*`** - Nuevas funcionalidades
- **`fix/*`** - Correcciones de bugs
- **`refactor/*`** - Refactors sin cambios funcionales
- **`hotfix/*`** - Fixes urgentes en producción

---

## Branch Structure

```
main (production)
  │
  ├─ v1.0.0 (tag)
  ├─ v1.1.0 (tag)
  │
  └─ develop (development) ← DEFAULT BRANCH para PRs
       │
       ├─ feature/nueva-funcionalidad
       ├─ feature/agregar-dashboard
       │
       ├─ fix/corregir-calculo-markup
       ├─ fix/arreglar-login
       │
       └─ refactor/migrate-pydantic-v2
```

---

## Branch Structure Detallada

### 🔴 `main` - Production Branch

**Propósito:** Código en producción

**Características:**
- ✅ Siempre deployable
- ✅ Solo contiene código 100% estable y testeado
- ✅ Tagged con versiones semánticas (v1.0.0, v1.1.0, v2.0.0)
- ✅ Deploy automático a producción
- ❌ **NUNCA commitear directo**
- ❌ **NUNCA pushear directo**
- ❌ **NUNCA hacer force push**

**Cómo actualizar:**
- Solo mediante Pull Request desde `develop`
- O mediante `hotfix/*` en emergencias

**Quién puede mergear:**
- Solo maintainers/admins después de review y testing

---

### 🟢 `develop` - Development Branch

**Propósito:** Branch principal de desarrollo e integración

**Características:**
- ✅ Branch base para todas las features
- ✅ Código testeado pero no necesariamente production-ready
- ✅ Deploy automático a ambiente de staging/dev
- ✅ Se mergea a `main` cuando está listo para release
- ❌ NO commitear directo (usar feature branches)

**Cómo actualizar:**
- Mediante Pull Requests desde `feature/*`, `fix/*`, `refactor/*`

**Quién puede mergear:**
- Maintainers después de review de código

---

### 🔵 `feature/*` - Feature Branches

**Propósito:** Desarrollo de nuevas funcionalidades

**Naming:** `feature/descripcion-corta`

**Ejemplos:**
- `feature/agregar-dashboard-ventas`
- `feature/filtro-por-categoria`
- `feature/integracion-whatsapp`

**Ciclo de vida:**
```bash
# Crear desde develop
git checkout develop
git pull origin develop
git checkout -b feature/mi-feature

# Desarrollar
git add .
git commit -m "feat: agregar nueva funcionalidad"
git push origin feature/mi-feature

# Abrir PR a develop
# Después del merge, se borra
```

**Cuándo usar:**
- Nueva funcionalidad
- Nueva página/componente
- Nueva integración
- Cualquier cambio que agregue features

---

### 🟡 `fix/*` - Bug Fix Branches

**Propósito:** Corrección de bugs en develop

**Naming:** `fix/descripcion-del-bug`

**Ejemplos:**
- `fix/corregir-calculo-markup`
- `fix/arreglar-login-redirect`
- `fix/validacion-formulario`

**Ciclo de vida:**
```bash
# Crear desde develop
git checkout develop
git pull origin develop
git checkout -b fix/nombre-bug

# Corregir
git add .
git commit -m "fix: corregir bug en cálculo"
git push origin fix/nombre-bug

# Abrir PR a develop
# Después del merge, se borra
```

**Cuándo usar:**
- Bug no crítico en develop
- Error de lógica
- Problema de UI/UX
- Validaciones faltantes

---

### 🟠 `refactor/*` - Refactor Branches

**Propósito:** Mejoras de código sin cambiar funcionalidad

**Naming:** `refactor/descripcion-refactor`

**Ejemplos:**
- `refactor/migrate-pydantic-v2`
- `refactor/extraer-service-pricing`
- `refactor/simplificar-queries`

**Ciclo de vida:**
```bash
# Crear desde develop
git checkout develop
git pull origin develop
git checkout -b refactor/mi-refactor

# Refactorizar
git add .
git commit -m "refactor: extraer lógica a service"
git push origin refactor/mi-refactor

# Abrir PR a develop
# Después del merge, se borra
```

**Cuándo usar:**
- Mejorar código existente
- Extraer lógica duplicada
- Renombrar variables/funciones
- Optimizaciones de performance

---

### 🔴 `hotfix/*` - Hotfix Branches (Emergencias)

**Propósito:** Fixes urgentes en producción

**Naming:** `hotfix/descripcion-critica`

**Ejemplos:**
- `hotfix/security-vulnerability`
- `hotfix/critical-login-bug`
- `hotfix/payment-processing-error`

**Ciclo de vida:**
```bash
# Crear desde main (NO desde develop)
git checkout main
git pull origin main
git checkout -b hotfix/bug-critico

# Fix rápido
git add .
git commit -m "hotfix: arreglar bug crítico en producción"

# Push
git push origin hotfix/bug-critico

# Abrir PR a main (urgente)
# Después de merge a main, también mergear a develop
git checkout develop
git merge main
git push origin develop
```

**⚠️ IMPORTANTE:**
- Solo para bugs **CRÍTICOS** en producción
- Bypasea el flujo normal (va directo a `main`)
- Debe mergearse también a `develop` después

**Cuándo usar:**
- Sistema caído en producción
- Vulnerabilidad de seguridad
- Bug que bloquea a todos los usuarios
- Pérdida de datos

---

## Workflow Completo

### 1️⃣ Desarrollo Normal (Feature/Fix)

```bash
# 1. Sincronizar develop
git checkout develop
git pull origin develop

# 2. Crear branch
git checkout -b feature/mi-feature

# 3. Desarrollar y commitear
git add .
git commit -m "feat: agregar nueva funcionalidad"

# 4. Push
git push origin feature/mi-feature

# 5. Abrir PR a develop en GitHub
# 6. Esperar review y merge
# 7. Branch se borra automáticamente después del merge
```

### 2️⃣ Release a Producción

```bash
# 1. Cuando develop está estable y listo para release
git checkout main
git pull origin main

# 2. Crear PR desde develop a main en GitHub
# 3. Review exhaustivo
# 4. Merge (squash o merge commit)

# 5. Tag la nueva versión
git checkout main
git pull origin main
git tag v1.2.0
git push origin v1.2.0

# 6. Deploy automático a producción
```

### 3️⃣ Hotfix de Emergencia

```bash
# 1. Crear hotfix desde main
git checkout main
git pull origin main
git checkout -b hotfix/bug-critico

# 2. Fix rápido
git add .
git commit -m "hotfix: arreglar bug crítico"
git push origin hotfix/bug-critico

# 3. PR a main (urgente, bypass review si es crítico)
# 4. Merge a main

# 5. Mergear también a develop
git checkout develop
git pull origin develop
git merge main
git push origin develop

# 6. Tag y deploy
git checkout main
git tag v1.2.1
git push origin v1.2.1
```

---

## Branch Protection Rules

### GitHub Settings → Branches

#### **Protección para `main`:**

**Require a pull request before merging:**
- ✅ Require approvals: **1** (mínimo)
- ✅ Dismiss stale pull request approvals when new commits are pushed
- ✅ Require review from Code Owners (opcional)

**Require status checks to pass before merging:**
- ✅ Require branches to be up to date before merging
- ✅ Status checks: tests, linting (cuando estén configurados)

**Rules applied to everyone including administrators:**
- ✅ **Include administrators** (vos también seguís las reglas)

**Restrict pushes:**
- ✅ **Restrict who can push to matching branches**
- Solo admins pueden mergear PRs (nadie pushea directo)

**Allow force pushes:**
- ❌ **Deshabilitar** (nunca force push a main)

**Allow deletions:**
- ❌ **Deshabilitar** (no se puede borrar main)

---

#### **Protección para `develop`:**

**Require a pull request before merging:**
- ✅ Require approvals: **1** (opcional pero recomendado)
- ✅ Dismiss stale pull request approvals when new commits are pushed

**Require status checks to pass before merging:**
- ✅ Require branches to be up to date before merging
- ✅ Status checks: tests, linting

**Rules applied to everyone including administrators:**
- ⚠️ Opcional (más flexible que main)

**Allow force pushes:**
- ❌ **Deshabilitar**

---

### **Configurar Default Branch**

**GitHub Settings → Branches → Default branch:**
- Cambiar a **`develop`** (no `main`)
- Esto hace que los PRs vayan a `develop` por default

---

## Ejemplos Prácticos

### Ejemplo 1: Agregar Dashboard de Ventas

```bash
# 1. Crear branch
git checkout develop
git pull origin develop
git checkout -b feature/dashboard-ventas

# 2. Crear archivos
# frontend/src/pages/DashboardVentas.jsx
# backend/app/api/endpoints/ventas_dashboard.py

# 3. Commits incrementales
git add frontend/src/pages/DashboardVentas.jsx
git commit -m "feat: crear componente DashboardVentas"

git add backend/app/api/endpoints/ventas_dashboard.py
git commit -m "feat: agregar endpoint ventas dashboard"

# 4. Push
git push origin feature/dashboard-ventas

# 5. PR a develop en GitHub
# Título: "feat: agregar dashboard de ventas"
# Descripción: Qué hace, cómo testearlo, screenshots

# 6. Review, ajustes si es necesario, merge
# 7. Branch se borra automáticamente
```

### Ejemplo 2: Fix Bug en Cálculo de Markup

```bash
# 1. Crear branch
git checkout develop
git pull origin develop
git checkout -b fix/calculo-markup-rebate

# 2. Corregir bug
# backend/app/services/pricing_service.py

# 3. Commit
git add backend/app/services/pricing_service.py
git commit -m "fix: corregir cálculo de markup en rebate ML

El cálculo no consideraba comisiones de ML correctamente.
Ahora usa la comisión real desde tb_ml_categories."

# 4. Push
git push origin fix/calculo-markup-rebate

# 5. PR a develop
# 6. Merge después de review
```

### Ejemplo 3: Release v1.3.0 a Producción

```bash
# develop está estable, queremos deployar

# 1. Abrir PR en GitHub: develop → main
# Título: "Release v1.3.0"
# Descripción:
# - Feature 1
# - Feature 2
# - Bug fixes

# 2. Review exhaustivo del PR
# 3. Merge (squash o merge commit)

# 4. Tag localmente
git checkout main
git pull origin main
git tag v1.3.0
git push origin v1.3.0

# 5. Deploy automático (GitHub Actions, CI/CD)
```

### Ejemplo 4: Hotfix Crítico

```bash
# Bug crítico: login no funciona en producción

# 1. Crear hotfix desde main
git checkout main
git pull origin main
git checkout -b hotfix/critical-login-bug

# 2. Fix rápido
# backend/app/api/endpoints/auth.py
git add backend/app/api/endpoints/auth.py
git commit -m "hotfix: corregir validación JWT en login"

# 3. Push
git push origin hotfix/critical-login-bug

# 4. PR a main (marcar como URGENTE)
# 5. Merge inmediato (bypass review si es crítico)

# 6. Backport a develop
git checkout develop
git pull origin develop
git merge main
git push origin develop

# 7. Tag hotfix
git checkout main
git pull origin main
git tag v1.2.1
git push origin v1.2.1
```

---

## Semantic Versioning

Pricing App usa **Semantic Versioning 2.0.0**: `MAJOR.MINOR.PATCH`

### Formato: `vX.Y.Z`

- **MAJOR (X)** - Cambios incompatibles de API (breaking changes)
  - Ejemplo: `v1.0.0` → `v2.0.0`
  - Cuándo: Refactor completo, cambios de arquitectura

- **MINOR (Y)** - Nuevas funcionalidades compatibles
  - Ejemplo: `v1.0.0` → `v1.1.0`
  - Cuándo: Nueva feature, nuevo endpoint, nuevo componente

- **PATCH (Z)** - Bug fixes compatibles
  - Ejemplo: `v1.0.0` → `v1.0.1`
  - Cuándo: Bug fix, hotfix, pequeñas correcciones

### Ejemplos:

```bash
v1.0.0  # Release inicial
v1.1.0  # + Dashboard de ventas
v1.1.1  # Fix: cálculo de markup
v1.2.0  # + Integración WhatsApp
v2.0.0  # BREAKING: Migración a nueva arquitectura
```

### Crear Tags:

```bash
# Después de merge a main
git checkout main
git pull origin main

# Tag con mensaje
git tag -a v1.2.0 -m "Release v1.2.0: Dashboard de ventas y fixes"

# Push tag
git push origin v1.2.0

# Ver tags
git tag -l
```

---

## FAQs

### ❓ ¿Por qué no commitear directo a `develop`?

**Respuesta:** Porque queremos:
1. **Code review** - Otro par de ojos siempre encuentra bugs
2. **Testing** - CI/CD corre tests automáticos en el PR
3. **Historial limpio** - Commits organizados por feature
4. **Rollback fácil** - Si algo falla, revertir el merge

---

### ❓ ¿Cuándo crear un `hotfix/*` vs `fix/*`?

**`hotfix/*`** (desde `main`):
- ✅ Bug crítico en producción
- ✅ Sistema caído
- ✅ Pérdida de datos
- ✅ Vulnerabilidad de seguridad

**`fix/*`** (desde `develop`):
- ✅ Bug no crítico
- ✅ Bug descubierto en testing
- ✅ Error cosmético
- ✅ Validación faltante

**Regla:** Si no está en producción o no es urgente → `fix/*`

---

### ❓ ¿Puedo pushear directo a `develop` si soy admin?

**Respuesta:** NO. Aunque tengas permisos, SIEMPRE usar PRs porque:
1. Code review mejora la calidad
2. CI/CD valida los cambios
3. Historial de Git es más claro
4. Das el ejemplo al equipo

**Excepción:** Cambios triviales en docs (README typos) SOLO si estás 100% seguro.

---

### ❓ ¿Cómo sincronizo mi fork con upstream?

```bash
# Agregar upstream (una sola vez)
git remote add upstream https://github.com/ORG/pricing-app.git

# Sincronizar
git checkout develop
git fetch upstream
git merge upstream/develop
git push origin develop
```

---

### ❓ ¿Qué pasa si mi feature branch está desactualizada?

```bash
# Opción 1: Merge develop en tu branch
git checkout feature/mi-feature
git merge develop
git push origin feature/mi-feature

# Opción 2: Rebase (más limpio pero avanzado)
git checkout feature/mi-feature
git rebase develop
git push origin feature/mi-feature --force-with-lease
```

---

### ❓ ¿Cuándo mergear `develop` a `main`?

**Cuándo:**
- ✅ Develop tiene features completas y testeadas
- ✅ Todos los tests pasan
- ✅ No hay bugs críticos conocidos
- ✅ Review exhaustivo completado

**Frecuencia:**
- Cada 1-2 semanas (releases pequeños frecuentes)
- O cuando haya features importantes listas

---

### ❓ ¿Qué hago si accidentalmente commiteo en `main`?

```bash
# NO PUSHEES!

# Si no pusheaste todavía:
git reset --soft HEAD~1  # Deshace el último commit
git stash                # Guarda los cambios
git checkout develop     # Cambia a develop
git stash pop            # Recupera los cambios
# Ahora crear branch desde develop

# Si ya pusheaste (💀):
# Contactar al maintainer inmediatamente
# Probablemente necesites revertir:
git revert HEAD
git push origin main
```

---

## 📚 Recursos Adicionales

- [Git Flow Original (Atlassian)](https://www.atlassian.com/git/tutorials/comparing-workflows/gitflow-workflow)
- [Semantic Versioning](https://semver.org/)
- [Conventional Commits](https://www.conventionalcommits.org/)
- [GitHub Flow](https://docs.github.com/en/get-started/quickstart/github-flow)

---

## 🎯 Resumen Rápido

| Branch | Base | Merge a | Uso | Duración |
|--------|------|---------|-----|----------|
| `main` | - | - | Producción | Permanente |
| `develop` | `main` | `main` (release) | Desarrollo activo | Permanente |
| `feature/*` | `develop` | `develop` | Nueva funcionalidad | Temporal |
| `fix/*` | `develop` | `develop` | Bug fix | Temporal |
| `refactor/*` | `develop` | `develop` | Refactor | Temporal |
| `hotfix/*` | `main` | `main` + `develop` | Emergencia | Temporal |

---

**Última actualización:** Enero 2026
