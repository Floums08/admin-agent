# Guía de implementación de Admin Agent

Versión documental: 6 de octubre de 2026. Base revisada: aplicación 0.5.0, commit `cf52ccdf7a2297be14ad1ad8b88e5b07d2950e7d`. Dirigida al responsable del servicio y a quien administra el servidor.

**Objetivo:** implantar un piloto supervisado para una empresa, demostrar que sus documentos se procesan correctamente y decidir con pruebas si se amplía. El repositorio está preparado; todavía deben realizarse el despliegue y la aceptación del entorno del cliente.

Lecturas complementarias: [mejora continua](MEJORA-CONTINUA.md), [plantillas para completar](PLANTILLAS-OPERATIVAS.md) y [runbook técnico completo](../03-DEPLOIEMENT.md). Los nombres de pantallas se mantienen como aparecen actualmente en la interfaz francesa.

## 1. Elegir el alcance inicial

Empezar con una entidad, un país confirmado FR o ES y diez facturas autorizadas. Limitar el piloto a treinta expedientes acumulados, incluyendo la primera aceptación. Incorporar gastos y conciliación después de aprobar sus escenarios específicos; no hace falta activar todos los módulos para obtener un primer resultado útil.

| Capacidad disponible | Uso en el piloto | Límite que debe conocer el operador |
|---|---|---|
| Documentos y OCR | PDF, PNG y JPEG; texto nativo y OCR local FR/ES/EN; original y propuestas trazables | Confirmación humana; máximo 5 MiB y 5 páginas por documento |
| Control de facturas | Coherencia de importes, fechas y datos de una factura simple | Un tipo de IVA; no certifica conformidad fiscal ni resuelve regímenes especiales |
| Seguimiento financiero | Facturas de clientes/proveedores, saldo inicial, vencimiento, pagos parciales y litigios | Confirmar fecha de corte y saldo; modificar/reanalizar la fuente bloquea operaciones posteriores |
| Conciliación | CSV bancario, vista previa, importación confirmada, asignación manual y anulación trazada | Sin conexión bancaria directa; fuera de alcance abonos, comisiones, reintegros a empleados y flujos del factor |
| Gastos | OCR del recibo, contexto profesional, política aportada y control de duplicados | No ejecuta reembolso ni calcula automáticamente IVA deducible |
| Factoring | Simulación según condiciones introducidas y seguimiento manual documentado | No solicita ofertas, certifica elegibilidad ni formaliza cesiones; un anticipo no es un cobro del deudor |
| Conectores | Carpeta local, CSV, WebDAV/Nextcloud y Dolibarr mediante CLI | Lectura remota; importación explícita; cuenta y permisos reales pendientes de aceptación |

Hay cinco workflows ejecutables: `invoice-check`, `receivables-followup`, `bookkeeping-pack`, `admin-triage` y `expense-review`. Los otros siete skills son procedimientos guiados. La IA externa está desactivada en producción. El seguimiento de cobros de `receivables-followup` aún no se sincroniza automáticamente con el registro financiero.

Una aprobación significa «revisado internamente». El sistema no envía correos, contacta clientes, paga, declara ni firma.

## 2. Preparar el expediente privado del cliente

Copiar la [ficha de implantación](PLANTILLAS-OPERATIVAS.md) y el [formulario de referencia](../../../examples/client-onboarding.example.json) a un espacio privado. No completar estos datos en GitHub.

| Información necesaria | Quién la confirma | Resultado antes de continuar |
|---|---|---|
| Entidad, país, actividad y procesos incluidos | Responsable del cliente | Alcance y exclusiones escritos |
| Volumen, formatos, lenguas y fuentes disponibles | Operador y cliente | Diez piezas representativas autorizadas; incluir casos difíciles |
| Política de gastos y significado de pagos/litigios | Responsable de negocio | Reglas aportadas, con fecha y responsable; incógnitas explícitas |
| Usuarios y suplentes | Responsable del servicio | Lista nominativa y roles mínimos |
| Hosting, región, dominio y presupuesto | Responsable técnico y del servicio | VM e IP pública dedicadas; acceso administrativo |
| Instrucciones de tratamiento y conservación | Responsables designados | Condiciones de acceso, restitución y borrado aceptadas |
| Recuperación y soporte | Responsable técnico | RPO/RTO acordados, destino de backup independiente y horario de servicio |
| Criterio de éxito | Responsable del servicio | Calidad exigida y objetivo de tiempo fijados antes de medir |

**Responsabilidades:** el operador prepara; el revisor compara con la fuente; el técnico gestiona acceso, despliegue y recuperación; el responsable del servicio decide alcance y lanzamiento. Pueden acumularse funciones en un equipo pequeño, dejando por escrito quién revisa cada cambio. La aplicación permite que un operador apruebe su propio expediente: la doble revisión es actualmente organizativa.

## 3. Repetir primero con datos ficticios

En un puesto Linux de pruebas: Python 3.11+, Docker local y Compose 2.24.4 o superior para el piloto. Ejecutar desde la raíz del repositorio, sin mezclar datos de clientes:

```bash
python3 -m venv .venv
. .venv/bin/activate
python -m pip install -r requirements-production.txt -r requirements-ocr.txt
python scripts/pilot_local.py init
python -m admin_agent.ops user-add \
  --config runtime/invoice-pilot/client.json \
  --username piloto.admin --role admin
python scripts/pilot_local.py up
python scripts/pilot_local.py status
python scripts/pilot_local.py certificate
```

La creación de usuario pide contraseña e información para enrolar TOTP. Repetir `user-add` para las personas operadoras/revisoras con `--role operator`. En el cliente real se usarán cuentas nominativas.

Abrir `https://pilot.localhost:8443`. La orden `certificate` exporta el certificado público de la autoridad local; el administrador del puesto debe configurar su confianza. No desactivar la comprobación TLS. El piloto escucha en el equipo local y no crea hosting público.

Para la aceptación básica de facturas, generar el lote de diez piezas y usar su registro de observaciones:

```bash
python scripts/pilot_fixtures.py --output runtime/pilot-fixtures
```

Seguir el [protocolo del piloto](../08-PILOTE-FACTURES.md) para registrar observaciones; generar piezas no registra resultados automáticamente.

Para probar también finanzas y gastos, usar el lote ampliado de 18 piezas. Su generación en Linux requiere Poppler y fuentes DejaVu; la validación exige Tesseract FR/ES/EN y `prlimit` en el host:

```bash
python -m pip install reportlab==4.4.9
python scripts/test_document_pack.py \
  --output runtime/jeu-test-2026-10-06 --as-of 2026-10-06
python scripts/validate_test_document_pack.py \
  --pack runtime/jeu-test-2026-10-06 \
  --report runtime/jeu-test-2026-10-06/qa/validation.json
```

Usar una ruta nueva para cada lote. Estos scripts no cargan documentos en la instancia; el validador usa una base temporal y simula revisión humana. Para comprobar la interfaz, importar manualmente los documentos siguiendo el [guía de pruebas](../10-JEU-TEST-FICTIF.md), conservando las anomalías intencionadas.

Los dos lotes son distintos: diez piezas para el piloto de facturas y 18 para finanzas/gastos. Mantener sus resultados y cohortes separados. Los datos ficticios nunca cuentan como evidencia de calidad sobre documentos del cliente.

## 4. Preparar la infraestructura del cliente

Arquitectura de referencia: una VM y una dirección pública por cliente, Caddy como entrada HTTPS, aplicación y worker OCR en redes privadas y una base SQLite exclusiva. Una segunda instancia con Caddy no puede ocupar los mismos puertos de la VM.

El técnico debe preparar Linux, Docker Engine/Compose mantenidos, Git, Python 3.11+ con venv, restic, systemd y utilidades Linux; DNS correcto; reloj sincronizado; cifrado del disco; SSH restringido y administración nominativa. Exponer únicamente los accesos acordados, con 80/443 para Caddy. Los puertos 8765 y 8766 no se publican.

Las reservas máximas de Compose son 512 MiB para aplicación, 768 MiB para OCR y 256 MiB para proxy. No representan el tamaño suficiente de una VM: añadir sistema, copias y margen medido. Documentar disco libre, carga y duración del OCR durante la aceptación.

El software usado evita tarifas por llamada OCR, pero hosting, almacenamiento, backups y mantenimiento siguen teniendo coste. Registrar su coste completo antes de fijar una tarifa de servicio.

## 5. Instalar una versión fija y crear los accesos

Los ejemplos siguientes usan `acme`, `Empresa Ejemplo` y `admin.example.com`. Sustituirlos de forma coherente. El directorio del cliente debe ser nuevo. Ejecutar en el servidor autorizado, desde `/opt/admin-agent`:

```bash
sudo git clone https://github.com/Floums08/admin-agent.git /opt/admin-agent
cd /opt/admin-agent
sudo git switch --detach cf52ccdf7a2297be14ad1ad8b88e5b07d2950e7d
sudo python3 -m venv .venv
sudo .venv/bin/python -m pip install -r requirements-production.txt
sudo .venv/bin/python -m admin_agent.ops init-client \
  --client-id acme --name "Empresa Ejemplo" \
  --domain admin.example.com \
  --directory /opt/admin-agent/runtime/acme
sudo .venv/bin/python -m admin_agent.ops user-add \
  --config runtime/acme/client.json --username nombre.apellido --role admin
```

El commit anterior es la base revisada de esta guía; para una entrega posterior, reemplazarlo por el SHA completo de la versión aceptada y revisar su CI. No actualizar producción automáticamente desde `main`.

Crear cuentas `operator` y `reader` según necesidad. Enrolar MFA desde un terminal privado. Contraseñas, QR/URI TOTP y archivos de enrolamiento no deben aparecer en pruebas públicas. El rol `admin` dispone del export global; `reader` sólo consulta.

En `runtime/acme/client.env`, asignar etiquetas únicas de versión a `APP_IMAGE` y `OCR_IMAGE`. Mantener los secretos en los archivos privados creados por la inicialización y preparar su recuperación separada.

```bash
sudo docker compose --env-file runtime/acme/client.env -p admin-acme config --quiet
sudo docker compose --env-file runtime/acme/client.env -p admin-acme build --pull
sudo docker compose --env-file runtime/acme/client.env -p admin-acme up -d
sudo docker compose --env-file runtime/acme/client.env -p admin-acme ps
sudo docker compose --env-file runtime/acme/client.env -p admin-acme images
sudo docker compose --env-file runtime/acme/client.env -p admin-acme exec -T ocr cat /app/ocr-packages.txt
```

Guardar SHA, identificadores/digests de imágenes, versiones del host y manifiesto OCR en el expediente privado. Verificar desde un puesto autorizado HTTPS, identidad de empresa, login+MFA, permisos y cierre de sesión. `/healthz` y `/readyz` son comprobaciones parciales, no una aceptación completa.

## 6. Activar backups y probar una recuperación completa

Antes de usar documentos reales:

1. Crear un repositorio restic independiente para este cliente y un acceso limitado a ese almacenamiento.
2. Copiar `deploy/backup.env.example` a `/etc/admin-agent/acme-backup.env` con permisos 0600 y completar sus rutas/credenciales mediante edición protegida.
3. Crear caché privada y área temporal sobre `tmpfs`. Inicializar el repositorio remoto sólo si es nuevo.
4. Instalar el servicio y timer de `deploy/systemd/`, ejecutar una copia y comprobar el snapshot remoto.
5. Configurar y probar la detección de fallo o antigüedad excesiva de copia. El repositorio no configura un canal de alertas externo.
6. Recuperar un snapshot identificado hacia una ruta nueva y hacer la prueba completa en un entorno aislado.

Las instrucciones exactas de instalación, variables y comandos de systemd/restic están en los apartados 6 y 7 del [runbook técnico](../03-DEPLOIEMENT.md). El timer de ejemplo es diario a las 02:30 UTC con hasta diez minutos aleatorios; adaptarlo al RPO acordado.

Registrar, como mínimo: cliente, ID de snapshot, fecha, prueba de recuperación desde fuera de la VM, integridad de base, original recuperado, saldos/asignaciones comparados y duración completa. La copia incluye originales, extracciones, expedientes y registro financiero en SQLite. No incluye automáticamente los secretos del host ni la configuración/caché de los conectores.

La restauración desactiva las cuentas recuperadas. Verificar qué personas siguen autorizadas; restablecer contraseña y MFA y después habilitarlas, utilizando la configuración de recuperación. Medir también este tiempo en el RTO. No arrancar un segundo Caddy en los puertos de la VM activa ni sobrescribir su base para hacer el ensayo.

El [control `preflight`](../03-DEPLOIEMENT.md) aporta evidencia técnica. Su salida conserva `launch_ready: false`, incluso si `technical_ready` es verdadero: la decisión depende también de la aceptación humana.

## 7. Configurar únicamente las entradas necesarias

| Entrada | Primera acción | Prueba antes de aceptarla |
|---|---|---|
| Documentos manuales | Importar original en **Documents** | Abrir original, extraer, corregir/confirmar y generar expediente |
| Carpeta o CSV de facturas | Preparar configuración CLI privada y vista previa | Correspondencia de columnas, duplicados y estados desconocidos |
| WebDAV/Nextcloud | Cuenta de prueba con permisos mínimos y servidor HTTPS permitido | Lectura, paginación, fallo de autenticación y retirada de acceso |
| Dolibarr | Clave dedicada de lectura y esquema confirmado | Referencias, estados, duplicados y revocación |
| Banco | Exportar CSV con `transaction_id,date,amount,currency,reference` | Vista previa, confirmación, repetición idéntica y conflicto de ID |

El CSV bancario se carga en **Finances → Banque & rapprochements**, no en el conector CSV de facturas. Las importaciones remotas se ejecutan explícitamente desde el host. La versión actual rechaza destinos de red privados; no prometer conexión a un Nextcloud exclusivamente interno.

La [guía de conectores](../07-OCR-ET-CONNECTEURS.md) contiene la configuración y las órdenes de cada adaptador. Guardar la configuración fuera de Git y no programar sincronizaciones hasta definir y probar ese requisito.

## 8. Ejecutar la aceptación por proceso

Mantener resultados esperados preparados por el revisor antes de usar la aplicación. Registrar tanto los errores iniciales como las correcciones; un documento corregido correctamente no demuestra OCR perfecto.

| Proceso | Ensayo mínimo | Criterio de aceptación |
|---|---|---|
| Acceso | Admin, operador y lector; MFA, sesión revocada, export | Operaciones permitidas/rechazadas según rol, incluso al modificar una petición |
| Factura/OCR | PDF nativo, imagen FR/ES, total incorrecto, fecha invertida, duplicado | Fuente verificable, campos revisados y anomalías bloqueadas |
| Gastos | Normal, pagado por empresa, ya reembolsado, fuera de política, fecha ausente, duplicado | Bloqueos esperados; no inventar fecha ni estado de pago |
| Registro de facturas | Saldo inicial, fecha de corte, pago parcial, litigio y fuente modificada | Saldo exacto; restricciones coherentes; histórico conservado |
| Banco | Reimportación, ID conflictivo, signo/divisa erróneos, importe ambiguo, anulación | Sin duplicación ni asignación automática ambigua; anulación trazada |
| Factoring | Parámetros conocidos, factura disputada y anticipo del factor | Cálculo reproducible y exclusiones; anticipo separado del cobro cliente |
| Recuperación | Snapshot remoto, nueva base, cuentas y documento original | Integridad, acceso recuperado y tiempo medido |
| Restitución | Export administrativo y originales separados | Datos y referencias verificables; destinatario definido |

Para el registro financiero, confirmar que el saldo inicial incluye los movimientos hasta el final de la fecha de corte. Los movimientos de esa fecha o anteriores no se vuelven a imputar. Comparar siempre el sentido cliente/proveedor y la moneda.

Después de registrar una factura, editar o reanalizar su expediente fuente invalida la base de operaciones posteriores; no hay una función de actualización del saldo inicial o de revinculación de esa fuente. Escalar este caso al responsable, conservar la trazabilidad y aplicar el [procedimiento financiero](../09-FINANCE-ET-FRAIS.md).

El lote ficticio del 5 de octubre aportó 18 casos documentales y nueve escenarios financieros superados, con 125 de 127 propuestas de campos exactas y dos nombres corregidos. Son resultados de ese lote; no sustituyen las diez piezas autorizadas del cliente ni prueban fotos reales.

## 9. Decidir el lanzamiento y operar el primer mes

Completar las condiciones G01–G16 del [expediente de lanzamiento](../06-GO-NO-GO.md) y el acta en español de las [plantillas](PLANTILLAS-OPERATIVAS.md). Cada condición necesita responsable, fecha y evidencia. Las condiciones opcionales sólo se excluyen si el módulo queda fuera del alcance.

No abrir el servicio si hay un fallo crítico de acceso, aislamiento, importe/estado financiero, restauración o condiciones de tratamiento sin resolver. La aprobación debe indicar versión, procesos, volumen, responsables y fecha de revisión. Publicar código no abre un cliente.

| Momento | Trabajo | Resultado |
|---|---|---|
| Preparación | Alcance, responsables, infraestructura y repetición sintética | Expediente listo para aceptación |
| Antes del primer dato real | HTTPS/MFA, backup remoto recuperado y condiciones aceptadas | Entorno cualificado para el lote autorizado |
| Primera semana | Diez piezas reales, revisión de todas y tiempos observados | Lista de errores y coste operativo inicial |
| Fin de semana 2 | Evaluar calidad, bloqueos y tiempo; máximo treinta expedientes | Continuar, ajustar alcance o detener |
| Hasta día 30 | Mejoras pequeñas verificadas y revisión de capacidad | Decisión de ampliación basada en datos |

El calendario es una secuencia de trabajo propuesta, no un plazo garantizado. Cada día, comprobar acceso, backup, espacio y expedientes pendientes. Revisar todos los documentos durante el piloto. Usar el [proceso de mejora continua](MEJORA-CONTINUA.md) para escoger el siguiente cambio.

## 10. Mantener capacidad y preparar la salida

| Recurso | Límite actual por instancia |
|---|---|
| Expedientes | 100 acumulados |
| Originales | 100 y 100 MiB en total |
| Extracciones | Cinco exitosas por original; histórico de 20 MiB |
| Facturas registradas | 100 |
| Operaciones bancarias / imports | 1.000 / 100 |
| Asignaciones / eventos financieros | 3.000 / 10.000 |
| Un CSV bancario | 200 filas y 60.000 bytes |

Son límites acumulados; no hay archivado automático que libere capacidad. Proponer una revisión al 70% y detener nuevos lotes al 85% hasta disponer de un plan aceptado, sin elevar límites ni borrar auditoría para continuar. Son umbrales operativos propuestos, todavía no alertas programadas.

Al terminar el servicio: congelar nuevas entradas, preparar export y originales, comprobar recepción por el responsable autorizado, retirar accesos y aplicar el plan de conservación a instancia, exportaciones y backups. El export JSON no contiene por sí solo todos los binarios originales. El borrado de un volumen no es un procedimiento completo de restitución ni de cierre.

## Evidencia y mantenimiento de esta guía

- Estado funcional y limitaciones: [README](../../../README.md), [roadmap](../../ROADMAP.md), [finanzas/gastos](../09-FINANCE-ET-FRAIS.md).
- CLI e infraestructura: [ops.py](../../../admin_agent/ops.py), [Compose](../../../compose.yaml), [despliegue](../03-DEPLOIEMENT.md).
- Pruebas históricas: [QA](../../QA.md), [lote ampliado](../10-JEU-TEST-FICTIF.md).
- CI de la base revisada: [ejecución 37315977049](https://github.com/Floums08/admin-agent/actions/runs/37315977049), finalizada correctamente el 5 de octubre de 2026.

Esta guía no modifica software ni acredita un despliegue cliente. Revisar comandos y límites al cambiar de versión. Mantener evidencias operativas privadas y publicar únicamente documentación, código y ejemplos ficticios.
