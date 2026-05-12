# Go-Live de PanolERP — Pasos finales

Fecha de preparación: **10 de mayo de 2026**

Este documento contiene **todo lo que falta** para abrir el sistema al público.
Hazlo en orden. Tiempo estimado total: **30–45 minutos**.

---

## 1. Variables de entorno en Render

Ve a tu Web Service en Render → pestaña **Environment** → agrega estas variables.
Cuando termines, haz click en **Save Changes** (Render redeploya automáticamente).

| Clave | Valor |
|-------|-------|
| `PANOL_SECRET_KEY` | `TXTpeh8DK4iVBVa5jNA3xuiPwZMRNyZtHj4HHDlojQ1Osbu0tfup5x0x3bdjI3sNooEp_hQ0TBc0qFECQzmPNA` |
| `PANOL_SYNC_TOKEN` | `wQUL-ZinTfYQ5onSgbiUOsOAAu0X_zzlS_SbUJeshzqfiqS_MSr6Y1Jbbxacfbc8` |
| `PANOL_NODO` | `admin_central` |
| `FLASK_ENV` | `production` |
| `FORCE_HTTPS` | `true` |
| `DATABASE_URL` | *(ya la entrega Render automáticamente al conectar la BD Postgres — no la sobreescribas)* |

> Las dos primeras son **secretas y únicas**. No las compartas por WhatsApp ni mail. Guárdalas en un gestor de contraseñas (KeePass, Bitwarden).

---

## 2. Subir las mejoras de seguridad a GitHub

Acabamos de agregar al código:
- **Bloqueo de cuenta** tras 5 intentos fallidos (15 min de espera).
- **Cambio obligatorio de contraseña** en el primer login (admin y pañoleros).
- **Migración automática** de columnas en la BD Postgres existente (no necesitas hacer nada manual).

Para subir los cambios:

```powershell
cd C:\Users\electronica9\Desktop\inventario

git add app.py
git commit -m "Hardening pre-go-live: lockout 5 intentos + forzar cambio de password inicial"
git push origin main
```

Render detectará el push y redesplegará automáticamente (~3–5 min).
En **Logs** del Web Service verás:

```
[MIGRACION] Aplicadas 3 columnas nuevas a usuario
[SEC] 9 usuarios marcados para cambio obligatorio de contraseña
✅ BD inicializada correctamente
```

---

## 3. Plan de pruebas pre-vuelo (15 min)

Hazlas en este orden, en la URL pública de Render. Si alguna falla, **no liberes el sistema** hasta arreglarla.

### 3.1 — Login admin con cambio forzado
1. Entra a `https://tu-app.onrender.com/login`.
2. User: `admin_central`, password: `admin123`.
3. ✅ Debe redirigirte a **/admin/cambiar_password** con el aviso "*Por seguridad, debes cambiar tu contraseña*".
4. Pon una contraseña fuerte (mínimo 8 chars, con mayús + minús + número). Anótala en tu gestor.
5. ✅ Debe llevarte al dashboard admin.
6. Logout.

### 3.2 — Lockout por intentos fallidos
1. En `/login`, intenta entrar con `admin_central` + password incorrecta.
2. Verás "*Te quedan 4 intentos*", luego 3, 2, 1...
3. Al 5° intento: "*🔒 Cuenta bloqueada por 15 minutos*".
4. ✅ Aunque pongas la password correcta, debe seguir bloqueado.
5. Espera 15 min (o resetea el lockout vía SQL — ver sección 5).

### 3.3 — Pañolero con cambio forzado
1. Login con `pañolero_electronica` + `pañol123`.
2. ✅ Te debe forzar a cambiar la contraseña.
3. Cambia y verifica que solo veas el inventario de Electrónica.
4. Repite para los otros pañoleros: `pañolero_mecanica_automotriz`, `pañolero_mecanica_industrial`, `pañolero_electricidad`, `pañolero_grafica`, `pañolero_acle`, `pañolero_oficina`, `pañolero_biblioteca`.

### 3.4 — Operación básica
1. Login pañolero → crear ítem → cargar Excel de muestra.
2. Login admin → crear estudiante → asignar préstamo → devolver.
3. ✅ Aparece todo en `/auditoria` con IP registrada.

### 3.5 — HTTPS y headers de seguridad
1. Abre `https://www.ssllabs.com/ssltest/` y pega tu URL — calificación esperada **A** o mejor.
2. Abre `https://securityheaders.com/` y pega tu URL — calificación **A** o mejor.
3. ✅ Confirma redirección automática `http://` → `https://`.

---

## 4. Credenciales iniciales — guarda este bloque temporal

Estas son las **credenciales semilla**. Después de la sección 3 ya estarán todas cambiadas.

| Usuario | Password inicial | Rol |
|---------|------------------|-----|
| `admin_central` | `admin123` | Admin |
| `pañolero_electronica` | `pañol123` | Pañolero Electrónica |
| `pañolero_mecanica_automotriz` | `pañol123` | Pañolero Mec. Automotriz |
| `pañolero_mecanica_industrial` | `pañol123` | Pañolero Mec. Industrial |
| `pañolero_electricidad` | `pañol123` | Pañolero Electricidad |
| `pañolero_grafica` | `pañol123` | Pañolero Gráfica |
| `pañolero_acle` | `pañol123` | Pañolero ACLE |
| `pañolero_oficina` | `pañol123` | Pañolero Oficina |
| `pañolero_biblioteca` | `pañol123` | Pañolero Biblioteca |

**El sistema ahora obliga a cambiar cada una en el primer login.** No es opcional. Cuando entregues credenciales a cada pañolero, dile:

> "*Tu usuario es `pañolero_<área>` y tu contraseña inicial es `pañol123`. Apenas entres, el sistema te va a pedir que la cambies por una propia. Pon una de mínimo 8 caracteres con al menos una mayúscula, una minúscula y un número.*"

---

## 5. Comandos útiles post-go-live

### Resetear lockout manual (vía Render Shell o psql)
Si un usuario quedó bloqueado y necesita acceso urgente:

```sql
UPDATE usuario SET failed_attempts=0, locked_until=NULL WHERE username='nombre_usuario';
```

### Forzar a un usuario a re-cambiar password
```sql
UPDATE usuario SET must_change_password=TRUE WHERE username='nombre_usuario';
```

### Ver últimos accesos
```sql
SELECT username, ultimo_login, failed_attempts, locked_until FROM usuario ORDER BY ultimo_login DESC;
```

### Ver auditoría reciente
```sql
SELECT u.username, a.accion, a.tabla, a.fecha, a.ip_address
FROM auditoria a LEFT JOIN usuario u ON a.usuario_id=u.id
ORDER BY a.fecha DESC LIMIT 50;
```

---

## 6. Post-go-live (primera semana)

- [ ] Día 1: revisar logs de Render por errores 500 → ajustar si aparece algo.
- [ ] Día 2: revisar `/auditoria` para confirmar uso real.
- [ ] Día 7: backup manual del Excel exportado (`/admin/exportar_completo`) y guardarlo offline.
- [ ] Mes 1: revisar facturación de Render. Si la BD se llena, escalar al plan de **$7/mes**.

---

## 7. Mejoras opcionales para más adelante

- 2FA para admin (código por correo).
- Cloudflare al frente como WAF + cache.
- Backups automáticos a Google Drive vía cron.
- Alertas de auditoría sospechosa (login fuera de horario, etc.).

---

## Estado del proyecto: **LISTO PARA GO-LIVE PÚBLICO** ✅

Todo el hardening crítico está aplicado. Solo falta que ejecutes las secciones 1, 2 y 3 de este documento.

Si algo falla, el log de Render es tu mejor amigo: `Render Dashboard → tu Web Service → Logs`.
