# Configurar sincronización entre PCs

Esquema: **un PC actúa como ADMIN CENTRAL**, los demás son **NODOS**. Cada nodo
mantiene su propia BD local y empuja sus cambios al admin cada N minutos.

## Esquema de red

```
   [Pañol Electrónica]  ──┐
   [Pañol Mec. Auto]    ──┤    POST /api/sync/push
   [Pañol Mec. Ind]     ──┼──→ ADMIN CENTRAL :8080
   [Pañol Electricidad] ──┤        (10.0.0.10)
   [Pañol Gráfica]      ──┤
   [ACLE]               ──┤
   [Oficina]            ──┤
   [Biblioteca]         ──┘
```

El admin central ve TODO. Cada nodo solo ve lo suyo, pero pasa sus cambios al admin.

## Paso 1: configurar el ADMIN CENTRAL

En el PC que será el admin (uno solo, idealmente el del Director TP o secretaría):

1. Copia toda la carpeta `inventario` al PC.
2. Crea un archivo `iniciar_admin.bat` en la raíz con este contenido:

```bat
@echo off
title PanolERP - ADMIN CENTRAL
set PANOL_NODO=admin_central
set PANOL_SYNC_TOKEN=PON_AQUI_UN_SECRETO_LARGO_Y_RANDOM_2026
set PANOL_SECRET_KEY=otra_clave_random_para_sesiones_2026
REM NO definimos PANOL_ADMIN_URL → este PC ES el admin
venv\Scripts\activate
python run.py
```

3. Anota la **IP de este PC** en la red local (ej. `192.168.1.10`). Para verla:
   `ipconfig` en CMD → busca "IPv4" en la interfaz LAN.

4. Asegúrate de que el firewall permita conexiones entrantes al puerto 8080:
   - Panel de control → Firewall de Windows → Configuración avanzada
   - Reglas de entrada → Nueva regla → Puerto → TCP 8080 → Permitir.

5. Ejecuta `iniciar_admin.bat`. La primera vez verás los mensajes de inicialización.

## Paso 2: configurar cada NODO (PC de pañolero)

Para cada PC de pañolero, copia la carpeta `inventario` y crea un `iniciar_nodo.bat`:

```bat
@echo off
title PanolERP - PAÑOL ELECTRÓNICA
set PANOL_NODO=panol_electronica
set PANOL_ADMIN_URL=http://192.168.1.10:8080
set PANOL_SYNC_TOKEN=PON_AQUI_UN_SECRETO_LARGO_Y_RANDOM_2026
set PANOL_SECRET_KEY=clave_random_local_diferente
venv\Scripts\activate
python run.py
```

**Importante**:
- `PANOL_NODO` único por PC (uno por especialidad/área).
- `PANOL_SYNC_TOKEN` debe ser **idéntico** en admin y todos los nodos.
- `PANOL_ADMIN_URL` apunta al IP del admin central.

Nombres sugeridos para `PANOL_NODO`:
- `panol_electronica`
- `panol_mecanica_automotriz`
- `panol_mecanica_industrial`
- `panol_electricidad`
- `panol_grafica`
- `acle`
- `oficina`
- `biblioteca`

## Paso 3: probar que el admin recibe

En el PC del nodo, una vez configurado, abre CMD en la carpeta y ejecuta:

```bat
venv\Scripts\activate
python sync_cliente.py --status
```

Deberías ver algo como:
```
=== Estado de sincronización del nodo 'panol_electronica' ===
  BD local:        ...\instance\inventario.db
  Admin central:   http://192.168.1.10:8080
  Cambios pendientes:  0
  Cambios enviados:    0
  Cambios con error:   0

  Admin: VIVO ✅
```

Si dice **"Admin NO responde"**, revisa firewall del admin y la IP.

## Paso 4: enviar cambios manualmente

Cada vez que quieras empujar al admin lo acumulado en este nodo:

```bat
python sync_cliente.py
```

Mostrará algo como:
```
[2026-05-08T01:30:42] Enviados: 12/12, errores: 0
```

## Paso 5: automatizar con Tarea programada de Windows

Para que el push corra cada 5 minutos sin intervención:

1. Abre **Programador de tareas** (busca "Task Scheduler" en el menú).
2. Acción → Crear tarea básica.
3. Nombre: `PanolERP Sync`.
4. Activador: `Cuando inicie sesión` o `Diariamente` con repetición cada 5 min.
5. Acción: `Iniciar un programa`.
   - Programa: `C:\Users\TU_USER\Desktop\inventario\venv\Scripts\python.exe`
   - Argumentos: `sync_cliente.py`
   - Iniciar en: `C:\Users\TU_USER\Desktop\inventario`
6. En Configuración: marca "Ejecutar tarea aunque el usuario no haya iniciado sesión".

A partir de ahora cada 5 minutos enviará lo pendiente al admin.

## Diagnóstico de problemas

### "Token inválido"
Los `PANOL_SYNC_TOKEN` no coinciden entre admin y nodo. Verifica que sean idénticos.

### "Admin NO responde"
- ¿Está corriendo `iniciar_admin.bat`?
- ¿La IP del admin es correcta? Si el admin se reconecta a la red, su IP puede cambiar; conviene asignarle IP fija desde el router.
- ¿El firewall del admin permite el puerto 8080?

### "Item local X no encontrado en admin"
Significa que un préstamo se está sincronizando antes que su item. Solución: ejecuta el cliente dos veces seguidas — la segunda vez ya encontrará los items.

### Reset de cambios fallidos
Si quieres reintentar todos los cambios marcados como `error`:
```sql
sqlite3 instance/inventario.db
UPDATE sync_log SET push_status='pendiente' WHERE push_status='error';
.quit
```

## Qué se sincroniza, qué no

**Sí se sincroniza** del nodo al admin:
- Items (catálogo + stock)
- Estudiantes
- Préstamos (a alumnos)
- Préstamos externos / consumos (oficina)
- Órdenes de trabajo

**No se sincroniza** (cada PC mantiene lo suyo):
- Auditoría (queda en cada nodo + se replica indirectamente con cada push)
- Usuarios del sistema (admin/pañoleros se gestionan localmente)
- Configuración del sistema

## Backup y respaldo

Recomendación fuerte: en el PC del admin central, programa una tarea que copie
`instance/inventario.db` a `instance/backups/inventario_YYYYMMDD.db` cada noche.
La BD del admin tiene el inventario completo de las 8 áreas.
