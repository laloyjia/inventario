# Checklist de seguridad antes del go-live

Este documento lista todo lo que **debes hacer** antes de poner el sistema accesible
en internet abierto. Marca cada paso al completarlo.

## Antes de subir el código a GitHub

- [ ] **Revisa que `.env` NO esté en el repo**. Solo `.env.example`. Si por error subiste el `.env`, ROTÁ todos los secretos.
- [ ] **Borra `instance/inventario.db` del repo** si lo subiste. Las BD nunca van al repo.
- [ ] **Borra archivos `.bak` de la BD** del repo (los hay de fases anteriores).
- [ ] **Verifica que `venv/` NO esté en el repo** (debe estar en `.gitignore`).

## Variables de entorno en Render/Railway

Ingresa estas como variables de entorno en el panel del proveedor (no las quemes en código):

- [ ] **`PANOL_SECRET_KEY`**: string aleatorio de **al menos 64 caracteres**.
  Genera uno con: `python -c "import secrets; print(secrets.token_urlsafe(64))"`
- [ ] **`DATABASE_URL`**: la entrega Render automáticamente al conectar la BD PostgreSQL.
- [ ] **`FLASK_ENV=production`** (activa cookies seguras y HTTPS forzado).
- [ ] **`FORCE_HTTPS=true`** (redirige todo HTTP a HTTPS).
- [ ] **`PANOL_NODO=admin_central`** (en cloud no hay sync, este es el único nodo).
- [ ] **`PANOL_SYNC_TOKEN=<otro string random largo>`** (aunque no uses sync, no dejes el default).

## Cambiar contraseñas por defecto

El sistema viene sembrado con contraseñas conocidas. **CÁMBIALAS antes del go-live**.

- [ ] **`admin_central`** — login default `admin123`. Cambia desde el panel admin a algo robusto (mínimo 12 chars, mezcla mayúsculas, minúsculas, números, símbolos).
- [ ] **`pañolero_*`** (los 8) — default `pañol123`. Cambia cada uno desde "Gestión de Pañoleros" → editar.
- [ ] **Si das credenciales por mail/papel a los pañoleros**, exígeles que cambien la contraseña en el primer login (futuro: agregar este flujo).

## Endurecimiento del código (ya configurado)

Estas cosas ya están en `app.py`, solo verifica que las variables de entorno las activen:

- [x] Cookies con flags `Secure` (solo HTTPS), `HttpOnly` (no accesibles desde JS), `SameSite=Lax` (mitiga CSRF).
- [x] `pool_pre_ping` en SQLAlchemy (detecta conexiones de BD muertas).
- [x] HTTPS forzado vía Flask-Talisman si está disponible.
- [x] Rate limiter global vía Flask-Limiter (500 req/hora por IP).
- [x] Sesión expira a las 8 horas.
- [x] Auditoría loggea IP de cada acción.

## Posibles ajustes adicionales

Si el sistema crece o sufre ataques, considera:

- [ ] **Bloqueo tras N intentos fallidos de login** (lockout de cuenta por X minutos).
- [ ] **2FA para admin** (código por mail o app autenticadora).
- [ ] **CDN/WAF al frente** (Cloudflare gratuito) → protege contra DDoS, escaneos automáticos.
- [ ] **Backups automáticos diarios** programados a otro proveedor (Render hace internos pero conviene tener uno externo).
- [ ] **Monitoreo de errores** (Sentry, Logtail) — te avisan si la app crashea.

## Cosas que NO debes hacer

- ❌ NO uses `app.run(debug=True)` en producción. Esto expone una consola Python remota.
- ❌ NO subas `inventario.db` al repo de GitHub.
- ❌ NO compartas el `DATABASE_URL` por mensajería sin cifrar.
- ❌ NO uses la misma contraseña para `PANOL_SECRET_KEY` y `PANOL_SYNC_TOKEN`.
- ❌ NO permitas que los pañoleros usen `admin_central`. El admin solo lo usa el responsable TI/Director TP.
- ❌ NO dejes "admin123" como contraseña ni un solo día en producción.
- ❌ NO compartas pantalla con el `.env` visible.

## Pre-vuelo: prueba antes del go-live público

- [ ] Crear un pañolero de prueba y hacer login → verificar que solo vea su área.
- [ ] Crear un ítem, prestarlo, devolverlo → debe quedar en auditoría.
- [ ] Cargar Excel de muestra → debe funcionar.
- [ ] Login con contraseña incorrecta 10 veces → debe bloquearte (rate limit).
- [ ] Verificar que la URL del sitio fuerce `https://` (no `http://`).
- [ ] Verificar header `Strict-Transport-Security` con curl o herramientas online (securityheaders.com).
- [ ] Cerrar sesión → intentar volver con el botón "Atrás" del navegador → debe pedir login otra vez.

## Después del go-live

- [ ] Anota las credenciales finales del admin en un gestor de contraseñas (KeePass, Bitwarden), NO en un Word.
- [ ] Establece un calendario de revisión de auditoría (semanal o quincenal).
- [ ] Revisa la facturación del proveedor cloud el primer mes para ajustar plan.
- [ ] Comunica a los usuarios el URL final, sus credenciales, y un canal para reportar problemas.
