# PROBAR_POWERSHELL.ps1 — Pruebas manuales con PowerShell
#
# CÓMO USARLO:
# 1. Asegúrate de que `python run.py` está corriendo en otra ventana
# 2. Abre PowerShell aquí y corre:    .\PROBAR_POWERSHELL.ps1
# 3. O copia y pega los bloques que quieras probar uno por uno

$BASE = "http://127.0.0.1:8080"

# Mantener cookies en una sesión
$session = New-Object Microsoft.PowerShell.Commands.WebRequestSession

Write-Host "`n=== 1. LOGIN ADMIN CENTRAL ==="
$body = @{ username = 'admin_central'; password = 'admin123' }
$r = Invoke-WebRequest -Uri "$BASE/login" -Method POST -Body $body -WebSession $session -MaximumRedirection 0 -ErrorAction SilentlyContinue
Write-Host "Status: $($r.StatusCode)  (esperado 302)"

Write-Host "`n=== 2. DASHBOARD ADMIN ==="
$r = Invoke-WebRequest -Uri "$BASE/dashboard_admin" -WebSession $session
Write-Host "Status: $($r.StatusCode)  (esperado 200)"
foreach ($esp in @('Electrónica', 'ACLE', 'Oficina', 'Biblioteca')) {
    if ($r.Content -match $esp) { Write-Host "  [OK] $esp visible" }
    else { Write-Host "  [FALLA] $esp NO visible" }
}

Write-Host "`n=== 3. LOGOUT + LOGIN PAÑOLERO ELECTRÓNICA ==="
Invoke-WebRequest -Uri "$BASE/logout" -WebSession $session | Out-Null
$body = @{ username = 'pañolero_electronica'; password = 'pañol123' }
Invoke-WebRequest -Uri "$BASE/login" -Method POST -Body $body -WebSession $session -MaximumRedirection 0 -ErrorAction SilentlyContinue | Out-Null
Write-Host "Login: OK"

Write-Host "`n=== 4. AGREGAR ITEM ==="
$body = @{
    nombre = 'Multímetro Digital'; codigo_barras = 'TEST-MM-001'
    categoria = 'Herramienta'; cantidad = 5; ubicacion = 'Estante A1'
}
$r = Invoke-WebRequest -Uri "$BASE/agregar" -Method POST -Body $body -WebSession $session -MaximumRedirection 0 -ErrorAction SilentlyContinue
Write-Host "Status: $($r.StatusCode)  (esperado 302)"

Write-Host "`n=== 5. AGREGAR ESTUDIANTE ==="
$body = @{
    rut_matricula = 'TEST-12345-6'; nombre = 'Juan de Prueba'; curso = '4to A'
}
$r = Invoke-WebRequest -Uri "$BASE/agregar_estudiante" -Method POST -Body $body -WebSession $session -MaximumRedirection 0 -ErrorAction SilentlyContinue
Write-Host "Status: $($r.StatusCode)  (esperado 302)"

Write-Host "`n=== 6. CREAR ORDEN DE TRABAJO ==="
$body = @{
    titulo = 'OT prueba PS1'; profesional_cargo = 'Profesor PS'
    descripcion = 'Reparación tablero'
    herramientas_utilizadas = "Destornillador x1`nTester x1"
    repuestos_utilizados = 'Resistencia 1k x10'
}
$r = Invoke-WebRequest -Uri "$BASE/agregar_ot" -Method POST -Body $body -WebSession $session -MaximumRedirection 0 -ErrorAction SilentlyContinue
Write-Host "Status: $($r.StatusCode)  (esperado 302)"

Write-Host "`n=== 7. PRÉSTAMO EXTERNO ==="
$body = @{
    codigo_item = 'TEST-MM-001'; cantidad = 1; tipo_persona = 'externo'
    persona_retira = 'Visitante'; profesor_cargo = 'Prof. X'
    especialidad_destino = 'Otra'; tipo_movimiento = 'prestamo'
}
$r = Invoke-WebRequest -Uri "$BASE/agregar_prestamo_externo" -Method POST -Body $body -WebSession $session -MaximumRedirection 0 -ErrorAction SilentlyContinue
Write-Host "Status: $($r.StatusCode)  (esperado 302)"

Write-Host "`n=== 8. EXPORTAR EXCEL ==="
$r = Invoke-WebRequest -Uri "$BASE/exportar_excel" -WebSession $session -OutFile inventario_exportado.xlsx
Write-Host "Excel guardado: inventario_exportado.xlsx"

Write-Host "`n=== 9. LOGIN BIBLIOTECA + AGREGAR LIBRO ==="
Invoke-WebRequest -Uri "$BASE/logout" -WebSession $session | Out-Null
$body = @{ username = 'pañolero_biblioteca'; password = 'pañol123' }
Invoke-WebRequest -Uri "$BASE/login" -Method POST -Body $body -WebSession $session -MaximumRedirection 0 -ErrorAction SilentlyContinue | Out-Null

$body = @{
    nombre = 'Cien años de soledad'
    autor = 'Gabriel García Márquez'
    isbn = '978-84-376-0494-7'
    editorial = 'Sudamericana'
    anio_publicacion = '1967'
    cantidad = 3
    ubicacion = 'Estante Lit'
}
$r = Invoke-WebRequest -Uri "$BASE/agregar_libro" -Method POST -Body $body -WebSession $session -MaximumRedirection 0 -ErrorAction SilentlyContinue
Write-Host "Agregar libro Status: $($r.StatusCode)  (esperado 302)"

Write-Host "`n=== 10. CATÁLOGO BIBLIOTECA ==="
$r = Invoke-WebRequest -Uri "$BASE/biblioteca" -WebSession $session
if ($r.Content -match 'Cien años') { Write-Host "[OK] El libro aparece en el catálogo" }

Write-Host "`n=== 11. JSON DE ATRASADOS ==="
$r = Invoke-WebRequest -Uri "$BASE/biblioteca/atrasados" -WebSession $session
Write-Host "Respuesta: $($r.Content)"

Write-Host "`n=== 12. LOGIN OFICINA + REGISTRAR CONSUMO ==="
Invoke-WebRequest -Uri "$BASE/logout" -WebSession $session | Out-Null
$body = @{ username = 'pañolero_oficina'; password = 'pañol123' }
Invoke-WebRequest -Uri "$BASE/login" -Method POST -Body $body -WebSession $session -MaximumRedirection 0 -ErrorAction SilentlyContinue | Out-Null

# Primero alta del consumible
$body = @{
    nombre = 'Resma A4'; codigo_barras = 'OFI-RESMA'
    categoria = 'Oficina'; cantidad = 50; ubicacion = 'Bodega'
}
Invoke-WebRequest -Uri "$BASE/agregar" -Method POST -Body $body -WebSession $session -MaximumRedirection 0 -ErrorAction SilentlyContinue | Out-Null

# Ahora consumo
$body = @{
    codigo_item = 'OFI-RESMA'; cantidad = 2
    persona_retira = 'Inspectoría'; motivo = 'Secretaría'
}
$r = Invoke-WebRequest -Uri "$BASE/registrar_consumo" -Method POST -Body $body -WebSession $session -MaximumRedirection 0 -ErrorAction SilentlyContinue
Write-Host "Consumo Status: $($r.StatusCode)  (esperado 302)"

Write-Host "`n=== TERMINADO ==="
Invoke-WebRequest -Uri "$BASE/logout" -WebSession $session | Out-Null
