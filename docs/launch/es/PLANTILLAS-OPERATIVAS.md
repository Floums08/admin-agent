# Plantillas operativas

Copiar estas plantillas a un espacio privado por cliente. Estado inicial: **pendiente**. Completar sólo con observaciones reales; no introducir facturas, credenciales ni nombres de personas en este repositorio público.

Referencias: [guía de implementación](GUIA-IMPLEMENTACION.md) y [proceso de mejora continua](MEJORA-CONTINUA.md).

## A. Ficha de implantación

| Campo | Valor a completar |
|---|---|
| Identificador privado del cliente / entidad / país | |
| Responsable del servicio / cliente / técnico / suplentes | |
| Procesos incluidos y exclusiones | |
| Usuarios, roles y responsable de revisión | |
| Fuentes y conectores; tipo de cuenta y permisos | |
| Volumen mensual previsto y capacidad acumulada disponible | |
| Política de gastos y fecha de corte del registro financiero | |
| Hosting, región, dominio y acceso administrativo | |
| SHA de código / imágenes / manifiesto OCR | |
| Ubicación privada de condiciones de tratamiento y conservación | |
| Destino de backup / custodia separada de recuperación | |
| RPO / RTO / horario de servicio acordados | |
| Lote sintético y lote cliente autorizados, por separado | |
| Objetivo de calidad / tiempo / coste acordado antes de medir | |
| Fecha de aceptación y revisión a dos semanas / día 30 | |
| Ubicación privada de las pruebas | |

**Siguiente acción:** completar responsable, fecha y evidencia de cada condición aplicable G01–G16 del [expediente de lanzamiento](../06-GO-NO-GO.md). Conservar ese listado completo junto a esta ficha; esta tabla no lo sustituye.

## B. Acta de aceptación y lanzamiento

| Control | Estado: pendiente / correcto / fallo / fuera de alcance justificado | Evidencia privada y fecha | Revisor |
|---|---|---|---|
| Alcance y condiciones G01–G03 | Pendiente | | |
| Instancia/identidad, HTTPS y red G04–G05 | Pendiente | | |
| Roles, MFA, revocación y administración G06–G07 | Pendiente | | |
| Backup independiente y recuperación G08 | Pendiente | | |
| Aceptación funcional y formación G09–G10 | Pendiente | | |
| Operación, alertas y límites G11–G13 | Pendiente | | |
| Restitución G14 | Pendiente | | |
| OCR y conectores, si incluidos, G15–G16 | Pendiente | | |
| Finanzas y gastos: escenarios específicos si incluidos | Pendiente | | |

- Decisión: **NO LANZADO** / APLAZADO / AUTORIZADO PARA EL ALCANCE INDICADO.
- Fecha y hora con zona horaria:
- Versión y procesos autorizados:
- Límite de volumen y fecha de revisión:
- Incidencias abiertas y medidas aceptadas:
- Responsable del servicio, técnico y cliente; referencia de aprobación:
- Prueba de recuperación completa: snapshot, duración, resultado y punto de recuperación:
- Próxima acción y responsable:

Un fallo crítico sin resolver impide autorizar el flujo afectado. Una condición no comprobada no se marca correcta. Esta decisión no autoriza al software a enviar, pagar o contactar.

## C. Registro de observación y mejora

Una ficha por problema o hipótesis. Para observaciones del piloto de facturas, usar además el esquema de `admin_agent.pilot`; no sustituir sus valores controlados por texto libre.

| Campo | Valor |
|---|---|
| ID / fecha / autor / proceso / versión | |
| Cohorte: sintética o cliente autorizado | |
| Referencia privada del caso y evidencia | |
| Resultado esperado, fijado independientemente | |
| Resultado observado antes de corrección | |
| Consecuencia y alcance conocido / desconocido | |
| Causa: documento / OCR / regla / skill / interfaz / operación / desconocida | |
| Severidad y contención necesaria | |
| Frecuencia: casos afectados / casos examinados | |
| Tiempo observado; aclarar total y subduraciones | |
| Hipótesis de mejora y criterio de aceptación | |
| Impacto / frecuencia / confianza / esfuerzo, si aplica | |
| Responsable / revisor / siguiente acción / fecha objetivo | |
| Reproducción ficticia / prueba de regresión / lote de reserva | |
| Condición de reversión | |
| Resultado después / evidencia / decisión | |

Ejemplo exclusivamente ficticio: «QA-DEMO-001: una imagen confunde O y 0 en una referencia; 1 caso de 8 imágenes revisadas; operador corrige; evaluar reconocimiento en un lote reservado de referencias alfanuméricas». Este ejemplo no prueba una incidencia de cliente ni establece una mejora ya realizada.

## D. Revisión semanal

Periodo: ____; cliente/proceso: ____; SHA: ____; asistentes: ____.

| Medida | Numerador | Denominador | Resultado | No medidos / limitación |
|---|---|---|---|---|
| Campos correctos antes de corrección | | | | |
| Abstenciones correctas, separadas | | No aplica | | |
| Cobertura de evaluación | | | | |
| Expedientes auditados con error crítico | | | | |
| Documentos con corrección | | | | |
| Conciliaciones correctas auditadas | | | | |
| Pares de tiempos comparables y minutos netos | | | | |
| Bloqueos y mayor antigüedad | | | | |
| Consumo de cada cuota / límite | | | | |
| Copia externa: fecha/edad; recuperación: fecha/duración | | | | |
| Coste completo por expediente, si medido | | | | |

- Tres principales causas observadas:
- Mejora seleccionada 1: responsable, aceptación, fecha:
- Mejora seleccionada 2, sólo si hay capacidad:
- Trabajo detenido o aplazado y motivo:
- Riesgo/capacidad que puede impedir el siguiente lote:
- Decisión sobre alcance y volumen:
- Próxima revisión:

Separar clientes, sintético/real y versiones. Mantener datos ausentes como «no disponible» y no sumar revisión/corrección de nuevo al tiempo total asistido.

## E. Ficha de entrega y recuperación

| Campo | Valor |
|---|---|
| Cambio y problema que resuelve | |
| SHA anterior / candidato; imágenes anteriores / nuevas | |
| Archivos y skills afectados; huellas si aplica | |
| Tests ejecutados / resultados / pruebas omitidas | |
| Enlace CI del SHA exacto y revisión independiente | |
| Resultado de preproducción y casos de reserva | |
| Backup previo: cliente, snapshot, fecha y verificación | |
| Compatibilidad de esquema/datos para volver atrás | |
| Operaciones que podrían perderse al restaurar | |
| Responsable, ventana y comunicación interna prevista | |
| Criterio de reversión y procedimiento elegido | |
| Prueba posterior: MFA, roles, original, análisis, finanzas y export | |
| Observación del primer lote y decisión de cierre | |

Si la vuelta de imagen no es compatible, documentar recuperación a base nueva, restablecimiento de accesos y revisión de operaciones posteriores al snapshot. No guardar secretos en esta ficha.

## F. Registro de incidente

- ID, proceso, versión y responsable:
- Fecha/hora de detección y periodo posiblemente afectado:
- Síntoma, impacto y evidencia privada:
- Datos/usuarios afectados confirmados; incertidumbres:
- Contención realizada, por quién y cuándo:
- Estado de copias y punto de recuperación:
- Diagnóstico y causa:
- Corrección y prueba de regresión:
- Validación de integridad, permisos y recuperación:
- Decisión de reapertura, alcance y responsable:
- Acciones de prevención, plazo y próxima comprobación:
- Decisiones de comunicación realizadas por personas habilitadas, si corresponden:

Esta ficha no ejecuta avisos, correos ni comunicaciones externas.
