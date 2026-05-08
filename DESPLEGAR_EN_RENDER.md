# Guía paso a paso: desplegar PanolERP en Render.com

Esta guía te lleva **desde cero** hasta tener tu sistema funcionando en internet con
HTTPS, base de datos en la nube y URL pública. Tiempo estimado: **40–60 minutos**.

Costo: **$0/mes** para empezar (tier gratuito de Render). Cuando crezca: ~$7/mes.

---

## PASO 1 — Cuenta de GitHub (5 min)

GitHub es donde guardarás tu código. Render lee de ahí cada vez que haces un cambio.

1. Ve a [github.com](https://github.com) y crea una cuenta gratuita.
2. Verifica el email.
3. Crea un nuevo repositorio:
   - Click "New" en la esquina superior izquierda.
   - Nombre: `panolerp` (o el que quieras).
   - **Privado** (importante: no lo dejes público).
   - Click "Create repository".
4. NO crees README ni .gitignore desde la web; lo subiremos desde tu PC.

## PASO 2 — Subir tu código a GitHub (10 min)

Necesitas Git instalado. Si no lo tienes: [git-scm.com/download/win](https://git-scm.com/download/win)

En PowerShell, en la carpeta del proyecto:

```powershell
cd C:\Users\electronica9\Desktop\inventario

# 1. Inicializar repo
git init
git config user.email "tu@email.com"
git config user.name "Tu Nombre"

# 2. Verificar que .gitignore existe (debe estar)
type .gitignore

# 3. Agregar archivos al repo (excluye lo que está en .gitignore)
git add .
git status     # revisa que NO aparezcan instance/*.db ni venv/

# 4. Primer commit
git commit -m "Versión inicial PanolERP para despliegue cloud"

# 5. Conectar con GitHub (cambia TU_USER por tu usuario de GitHub)
git remote add origin https://github.com/TU_USER/panolerp.git
git branch -M main
git push -u origin main
```

GitHub te pedirá login. Si tienes 2FA, usa un token (Settings → Developer Settings → Personal Access Tokens).

Verifica en tu repo de GitHub que aparezcan los archivos. La carpeta `instance/` y `venv/`
NO deben estar (eso confirma que `.gitignore` funcionó).

## PASO 3 — Cuenta en Render.com (3 min)

1. Ve a [render.com](https://render.com) y haz click en "Get Started".
2. **Inicia sesión con GitHub** (más fácil porque ya conectas el repo).
3. Render te pide permisos para leer tus repos: dáselos al repo `panolerp` solamente.

## PASO 4 — Crear la base de datos PostgreSQL (5 min)

1. En el dashboard de Render, click "New +" → **"PostgreSQL"**.
2. Configuración:
   - Name: `panolerp-db`
   - Database: `panolerp`
   - User: `panolerp_user`
   - Region: la más cercana a Chile → **Oregon (US West)** o **Ohio (US East)**.
   - Instance Type: **Free** (90 días gratis, después hay que migrar a $7/mes).
3. Click "Create Database". Espera 1–2 min.
4. Cuando esté lista, copia la **"External Database URL"** y guárdala — la necesitas para el siguiente paso.

⚠️ La External URL la usas para correr `migrar_a_postgres.py` desde tu PC. La Internal
URL la usa la app cuando ya está desplegada (más rápida porque no sale a internet).

## PASO 5 — Crear el Web Service (10 min)

1. En el dashboard de Render, click "New +" → **"Web Service"**.
2. Selecciona el repo `panolerp` que conectaste antes.
3. Configuración:
   - Name: `panolerp` (será parte del URL final: `panolerp.onrender.com`)
   - Region: **misma que la BD** (importante para latencia).
   - Branch: `main`
   - Runtime: **Python 3**
   - Build Command: `pip install -r requirements.txt`
   - Start Command: `gunicorn app:app --workers 2 --threads 2 --timeout 120 --bind 0.0.0.0:$PORT`
   - Instance Type: **Free**.

4. **Variables de entorno** (sección "Environment" / "Add Environment Variable"):
   - `PANOL_SECRET_KEY` = (genera con `python -c "import secrets; print(secrets.token_urlsafe(64))"` en tu PC y pega el resultado)
   - `PANOL_NODO` = `admin_central`
   - `PANOL_SYNC_TOKEN` = (otro string random largo)
   - `FLASK_ENV` = `production`
   - `FORCE_HTTPS` = `true`
   - `DATABASE_URL` = (click "Add from Database" → selecciona `panolerp-db`, Render conecta automáticamente)

5. Click "Create Web Service". Render hace el primer deploy (3-5 min).

## PASO 6 — Migrar tu BD local a PostgreSQL (5 min)

Tu BD actual con los items, estudiantes y pañoleros está en `instance/inventario.db`.
Hay que pasarla a la PostgreSQL de la nube.

En PowerShell (carpeta del proyecto):

```powershell
# Activar entorno virtual
venv\Scripts\activate

# Instalar driver PostgreSQL si falta
pip install psycopg2-binary

# Configurar URL EXTERNA (la que copiaste en paso 4)
$env:DATABASE_URL="postgresql://panolerp_user:xxxxx@dpg-xxx.oregon-postgres.render.com/panolerp"

# Correr migración
python migrar_a_postgres.py
```

El script te pide confirmación, te lista las tablas creadas y te dice cuántas filas migró
por cada tabla. Al final verás `✅ Migración completa`.

## PASO 7 — Probar el sitio (2 min)

1. En el dashboard de Render, abre tu Web Service. Verás el URL: `https://panolerp.onrender.com`
2. Abre ese URL en tu navegador.
3. Login con `admin_central / admin123`.
4. **Cambia la contraseña inmediatamente** desde "Gestión de Pañoleros" (editas tu propio user).

⚠️ El **plan free de Render duerme la app después de 15 min de inactividad**. La primera
request después de eso tarda 30-60 seg en despertar. Si quieres siempre activa: $7/mes.

## PASO 8 — Configurar dominio propio (opcional, 10 min)

Si compras un dominio (ej. `panolcolegio.cl` ~$10 USD/año en NIC.cl):

1. En Render: Web Service → Settings → "Custom Domains" → Add.
2. Render te da un CNAME. Vas al panel de tu proveedor de dominio y agregas un registro CNAME apuntando ahí.
3. Render genera el certificado SSL automáticamente (5-10 min después).
4. Listo: tu sistema vive en `https://panolerp.tucolegio.cl`.

## PASO 9 — Antes de soltar a los pañoleros

Revisa el archivo `CHECKLIST_SEGURIDAD.md` y marca cada paso. En particular:
- Cambiar TODAS las contraseñas default.
- Probar login con credenciales malas (debe bloquearte tras varios intentos).
- Verificar que la URL fuerce HTTPS.

---

## Cuando hagas cambios al código

```powershell
git add .
git commit -m "descripción del cambio"
git push
```

Render detecta el push y despliega automáticamente. Toma 2–3 min.

## Si algo falla en producción

1. En Render → tu Web Service → tab "Logs" → ahí ves errores en tiempo real.
2. Si el deploy falla, los logs te dicen qué archivo o paquete falla.
3. Para hacer rollback: Settings → "Manual Deploy" → elige una versión anterior.

## Costos a futuro

- **Free tier (gratis):**
  - Web Service duerme tras 15 min sin tráfico.
  - PostgreSQL gratis solo 90 días, después se elimina.
  - Suficiente para pruebas y piloto.
- **Starter ($7/mes web + $7/mes db = $14/mes total):**
  - Web Service siempre activo.
  - PostgreSQL persistente con backups diarios automáticos.
  - **Recomendado cuando ya estés en producción real con los pañoleros usándolo.**
- **Si necesitas más recursos** (muchos usuarios o áreas): Standard ($25/mes web).

---

## Alternativas si Render no te convence

- **Railway.app**: similar, gratis tienes $5 USD de crédito/mes. UX más amigable.
- **Fly.io**: más técnico pero más generoso con recursos.
- **PythonAnywhere**: orientado a Python, plan gratis para una app pequeña.
- **VPS (DigitalOcean / Linode / Hetzner)**: más barato a largo plazo pero requiere
  administrar Linux, certificados SSL, backups manualmente. Si tienes un sysadmin, esta
  es la opción más profesional.

---

## ¿Y la sincronización entre nodos?

En cloud **no la necesitas**. Todos los pañoleros entran al mismo URL desde sus PCs y
ven la misma BD en tiempo real. Los archivos `sync_cliente.py`, `iniciar_admin.bat`,
`iniciar_nodo.bat`, `sincronizar.bat` y `CONFIGURAR_SINCRONIZACION.md` quedan ahí por si
en el futuro decides volver a tener nodos locales con sync, pero en cloud son innecesarios.
