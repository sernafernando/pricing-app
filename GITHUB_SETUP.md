# 🔒 GitHub Branch Protection Setup

Instrucciones paso a paso para configurar las protecciones de branches en GitHub.

## ⚠️ IMPORTANTE: Hacer Esto AHORA

Sin estas configuraciones, los contributors pueden pushear directo a `main` o `develop`, rompiendo el workflow.

---

## 📋 Checklist

- [ ] Cambiar default branch a `develop`
- [ ] Proteger `main` branch
- [ ] Proteger `develop` branch
- [ ] Verificar configuración

---

## Paso 1: Cambiar Default Branch a `develop`

**Por qué:** Para que los PRs vayan automáticamente a `develop` en lugar de `main`.

**Cómo:**

1. Ir a tu repo en GitHub: `https://github.com/sernafernando/pricing-app`
2. Click en **Settings** (arriba a la derecha)
3. En el menú izquierdo, click en **Branches**
4. En la sección **Default branch**, click en el ícono de flechas ↔️ al lado de `main`
5. Seleccionar **`develop`** del dropdown
6. Click **Update**
7. Confirmar en el modal que aparece

**Resultado:** Ahora cuando alguien hace fork o abre un PR, va a `develop` por default.

---

## Paso 2: Proteger `main` Branch

**Por qué:** `main` es producción. NADIE debe pushear directo.

**Cómo:**

1. En **Settings → Branches**, bajar a **Branch protection rules**
2. Click **Add rule** o **Add branch protection rule**
3. En **Branch name pattern**, escribir: `main`

### Configuraciones a habilitar:

#### ✅ Require a pull request before merging
- Tildar **Require a pull request before merging**
- Tildar **Require approvals**
  - Número de aprobaciones: **1**
- Tildar **Dismiss stale pull request approvals when new commits are pushed**

#### ✅ Require status checks to pass before merging
- Tildar **Require status checks to pass before merging**
- Tildar **Require branches to be up to date before merging**
- (Status checks específicos se agregan cuando tengas CI/CD configurado)

#### ✅ Require conversation resolution before merging
- Tildar esto (opcional pero recomendado)

#### ✅ Include administrators
- **⚠️ IMPORTANTE:** Tildar **Include administrators**
- Esto hace que VOS también tengas que seguir las reglas (buena práctica)

#### ✅ Restrict pushes
- Tildar **Restrict who can push to matching branches**
- NO agregar a nadie (nadie puede pushear directo)
- Solo merges via PR permitidos

#### ❌ Allow force pushes
- **Dejar destildado** (nunca force push a main)

#### ❌ Allow deletions
- **Dejar destildado** (no se puede borrar main)

4. Scroll abajo y click **Create** o **Save changes**

---

## Paso 3: Proteger `develop` Branch

**Por qué:** `develop` es el branch de integración. Los commits deben venir de PRs.

**Cómo:**

1. En **Settings → Branches**, click **Add rule** nuevamente
2. En **Branch name pattern**, escribir: `develop`

### Configuraciones a habilitar:

#### ✅ Require a pull request before merging
- Tildar **Require a pull request before merging**
- Tildar **Require approvals** (opcional)
  - Número de aprobaciones: **1** (o 0 si querés más flexibilidad)
- Tildar **Dismiss stale pull request approvals when new commits are pushed**

#### ✅ Require status checks to pass before merging
- Tildar **Require status checks to pass before merging**
- Tildar **Require branches to be up to date before merging**

#### ⚠️ Include administrators
- **Opcional** para `develop` (más flexible que `main`)
- Recomendado: Dejar destildado para que vos puedas mergear rápido si es necesario

#### ❌ Restrict pushes
- **Dejar destildado** para `develop` (más flexible)
- O tildar si querés forzar PRs siempre

#### ❌ Allow force pushes
- **Dejar destildado**

#### ❌ Allow deletions
- **Dejar destildado**

3. Click **Create** o **Save changes**

---

## Paso 4: Verificar Configuración

### Verificar Default Branch

1. Ir a la página principal del repo
2. Arriba del listado de archivos, debe decir: `develop` (no `main`)

### Verificar Protecciones

1. Settings → Branches → **Branch protection rules**
2. Deberías ver:
   ```
   main    [Edit] [Delete]
   develop [Edit] [Delete]
   ```

### Probar (Opcional)

Intentar pushear directo a `main`:

```bash
git checkout main
git pull origin main
echo "test" > test.txt
git add test.txt
git commit -m "test: intentar pushear a main"
git push origin main
```

**Resultado esperado:**
```
remote: error: GH006: Protected branch update failed for refs/heads/main.
```

¡Perfecto! Las protecciones funcionan.

---

## 🎯 Resumen de lo Configurado

| Branch | Default | Protected | Require PR | Require Approval | Force Push | Delete |
|--------|---------|-----------|-----------|------------------|-----------|--------|
| `main` | ❌ | ✅ | ✅ | ✅ (1) | ❌ | ❌ |
| `develop` | ✅ | ✅ | ✅ | ⚠️ (opcional) | ❌ | ❌ |

---

## 📝 Qué Hacer Después

### 1. Informar al Equipo

Enviar mensaje:

> 📢 **Cambio Importante en el Repo**
>
> Ahora usamos Git Flow:
> - `main` → Producción (protegido)
> - `develop` → Desarrollo activo (default para PRs)
>
> **TODOS los PRs deben ir a `develop`, NO a `main`.**
>
> Ver documentación completa: [BRANCHING.md](BRANCHING.md)

### 2. Actualizar CI/CD (Futuro)

Cuando configures GitHub Actions:
- Deploy a **staging** desde `develop`
- Deploy a **producción** desde `main`
- Tests en todos los PRs

### 3. Primer Release

Cuando quieras hacer el primer release oficial:

```bash
# 1. Asegurar que develop está estable
# 2. Crear PR de develop → main
# 3. Mergear después de review
# 4. Tag la versión

git checkout main
git pull origin main
git tag v1.0.0
git push origin v1.0.0
```

---

## ❓ Troubleshooting

### "No puedo pushear a main"

✅ **Correcto:** Eso significa que las protecciones funcionan. Usá PRs.

### "Mi PR dice que va a main, no a develop"

1. En la página del PR en GitHub
2. Click en **Edit** al lado del branch base
3. Cambiar de `main` a `develop`
4. Click fuera del dropdown

### "No puedo mergear mi PR"

Revisar:
- ¿Tenés aprobación necesaria?
- ¿Tu branch está actualizada con develop?
- ¿Los checks pasan (si los tenés configurados)?

---

## 🎉 Listo!

Tu repo ahora tiene protecciones profesionales. Nadie (ni vos) puede romper `main` accidentalmente.

**Próximos pasos:**
1. Configurar estas protecciones en GitHub (5 minutos)
2. Avisar al trainee y contributors
3. Disfrutar del workflow ordenado 🚀

---

**Última actualización:** Enero 2026
