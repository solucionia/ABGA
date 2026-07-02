# 📋 TASKS — Proyecto IA ABGA

> Última actualización: Junio 2026  
> Proyecto: ABGA Consultores × SolucionIA.ai

---

## 🔥 Tareas urgentes (bloqueantes)

- [ ] **[BLOQ-01]** Obtener `cod_empresa` de ABGA en ERP K1970 — pedido a Iván por email
- [ ] **[BLOQ-02]** Confirmar si campo `Mail` está poblado en `/api/clientes/`
- [ ] **[BLOQ-03]** Recibir PDF ejemplo informe Autodespro de Iván
- [ ] **[BLOQ-04]** Confirmar formato extractos bancarios (REQ-01)
- [ ] **[BLOQ-05]** Confirmar estado cuenta WhatsApp Business de ABGA (REQ-07)
- [ ] **[BLOQ-06]** Confirmar años de histórico disponibles en ERP (REQ-02 y REQ-08)
- [ ] **[BLOQ-07]** Recibir ejemplo Memoria de Cuentas Anuales (REQ-08)

---

## ✅ REQ-03 — Informe Financiero Autodespro

**Estado:** 🟡 En desarrollo  
**Workflow:** `workflows/REQ-03_informe_autodespro.json`

### Completado
- [x] Diseño arquitectura del workflow
- [x] Nodo autenticación apiERP + apiCON
- [x] Loop por empresa con GET Companies
- [x] GET Subcuentas (Plan de Cuentas PGC)
- [x] GET Facturas del ejercicio
- [x] GET Apuntes del ejercicio
- [x] Nodo Code: cálculo estados financieros (PyG + Balance + 8 ratios)
- [x] Cálculo evolución mensual por facturas
- [x] Agente Claude Sonnet 4 con system prompt Autodespro
- [x] Estructura informe: portada, resumen ejecutivo, PyG PGC, balance, ratios, evolución, recomendaciones
- [x] Envío por Microsoft Outlook
- [x] Log en Excel SharePoint
- [x] JSON workflow listo para importar

### Pendiente
- [ ] Recibir PDF ejemplo Autodespro de Iván
- [ ] Ajustar formato visual según PDF real
- [ ] Sustituir `codigoEmpresa` por código real
- [ ] Test con datos reales de ABGA
- [ ] Validar cálculos con Iván
- [ ] Activar workflow en producción

---

## ✅ REQ-05 — Envío Balances y PyG

**Estado:** 🟡 En desarrollo  
**Workflow:** `workflows/REQ-05_envio_balances_pyg.json`

### Completado
- [x] Diseño arquitectura del workflow
- [x] Schedule Trigger trimestral (cron `0 9 28-31 3,6,9,12 *`)
- [x] Manual Trigger para testing
- [x] Nodo Calcular Período (trimestre + año dinámicos)
- [x] Auth apiERP + apiCON en paralelo con Merge Tokens
- [x] GET Companies (apiERP)
- [x] Loop por empresa (SplitInBatches)
- [x] GET Clientes con extracción de email
- [x] Nodo IF: skip empresas sin email
- [x] GET Facturas del ejercicio
- [x] GET Apuntes del ejercicio (llamadas en paralelo)
- [x] Nodo Code: cálculo ingresos, gastos, IVA, resultado, margen
- [x] Agente Claude con prompt PyG estructurado PGC
- [x] System prompt completo (8 secciones, CSS inline, reglas datos)
- [x] Envío por Microsoft Outlook desde comunicaciones@abgaconsultores.com
- [x] Log en Excel SharePoint
- [x] JSON workflow listo para importar

### Pendiente
- [ ] Sustituir `codigoEmpresa` por código real (esperar BLOQ-01)
- [ ] Confirmar campo Mail en clientes ERP (BLOQ-02)
- [ ] Test end-to-end con datos reales
- [ ] Validar formato HTML del informe con Iván
- [ ] Definir tabla específica en Excel para log de envíos
- [ ] Activar workflow en producción

---

## ✅ REQ-06 — Alertas Fiscales Trimestrales

**Estado:** 🟡 En desarrollo  
**Workflow:** `workflows/REQ-06_alertas_fiscales.json`

### Completado
- [x] Diseño arquitectura del workflow
- [x] Schedule Trigger día 15 de cada mes de cierre trimestral
- [x] Nodo Calcular Período (trimestre, fecha límite, modelos a presentar)
- [x] Auth apiERP + apiCON + apiNOM en paralelo (3 tokens)
- [x] Merge Tokens con numberInputs: 3
- [x] GET Companies + Loop por empresa
- [x] GET Apuntes cuentas 47x (IVA repercutido cuenta 477, soportado 472)
- [x] GET Apuntes cuentas 475x (retenciones IRPF)
- [x] GET Total Nóminas (apiNOM) con continueOnFail
- [x] Nodo Code: cálculo fiscal completo (IVA, retenciones, IS, alertas)
- [x] Sistema de alertas por niveles: ALTA / MEDIA / INFO
- [x] Detección automática pago fraccionado IS (Q1 y Q3 → Modelo 202)
- [x] Cálculo dinámico fechas límite por trimestre
- [x] Agente Claude con system prompt alerta fiscal
- [x] Asunto email con nivel alerta y fecha límite
- [x] Envío por Microsoft Outlook
- [x] Log en Excel SharePoint con nivel de alerta
- [x] JSON workflow listo para importar

### Pendiente
- [ ] Sustituir `codigoEmpresa` por código real (esperar BLOQ-01)
- [ ] Test con datos reales de IVA
- [ ] Validar cálculos fiscales con Iván
- [ ] Confirmar modelos adicionales que gestiona ABGA (Modelo 115, 123...)
- [ ] Activar workflow en producción

---

## 🔴 REQ-01 — Cotejo y Conciliación de Mayores

**Estado:** 🔴 Pendiente  
**Dependencias:** BLOQ-01, BLOQ-04

### Por hacer
- [ ] Confirmar formato extractos bancarios con Iván (PDF, Excel, OFX, CSV)
- [ ] Confirmar canal de entrega extractos (email, descarga manual, open banking)
- [ ] Diseñar arquitectura del workflow
- [ ] Implementar parser de extractos bancarios
- [ ] Implementar GET Apuntes + GET Subcuentas del período
- [ ] Algoritmo de matching: importe + fecha + concepto con tolerancia
- [ ] Lógica de fuzzy matching para diferencias pequeñas
- [ ] Nodo Code: identificar asientos sin contrapartida bancaria
- [ ] Generar informe de discrepancias
- [ ] Notificación al asesor de ABGA (no al cliente final)
- [ ] Log de conciliaciones en Excel

---

## 🔴 REQ-02 — Proyecciones y Predicciones

**Estado:** 🔴 Pendiente  
**Dependencias:** BLOQ-01, BLOQ-06

### Por hacer
- [ ] Confirmar años de histórico disponibles en ERP
- [ ] Confirmar partidas presupuestarias que quiere proyectar Iván
- [ ] Evaluar modelo predictivo: Prophet vs LSTM vs regresión simple
- [ ] Diseñar arquitectura del workflow
- [ ] Implementar extracción histórico multi-ejercicio via apiCON
- [ ] Implementar modelo de proyección (Code node o servicio externo)
- [ ] Generar proyecciones por cuenta/grupo PGC
- [ ] Visualización de proyecciones en informe HTML
- [ ] Definir horizonte temporal (6 meses, 12 meses, 24 meses)
- [ ] Test y validación con Iván

---

## 🔴 REQ-04 — Detección de Facturas Duplicadas

**Estado:** 🔴 Pendiente  
**Dependencias:** BLOQ-01

### Por hacer
- [ ] Diseñar arquitectura del workflow
- [ ] GET Facturas apiCON + GET Invoices apiREC
- [ ] Algoritmo multivariable: CIF + importe + fecha + base imponible
- [ ] Implementar distancia Levenshtein para numeración similar
- [ ] Tolerancia configurable en importes (±0.01 EUR)
- [ ] Tolerancia configurable en fechas (±3 días)
- [ ] Corrección errores OCR en números de factura
- [ ] Clasificación por nivel de riesgo: PROBABLE / POSIBLE / REVISAR
- [ ] Informe de duplicados sospechosos para el asesor
- [ ] Log en Excel SharePoint
- [ ] Alerta por email al asesor de ABGA (no al cliente)
- [ ] Test con datos reales

---

## 🔴 REQ-07 — Agente WhatsApp Business

**Estado:** 🔴 Pendiente  
**Dependencias:** BLOQ-01, BLOQ-05

### Por hacer
- [ ] Confirmar estado cuenta WhatsApp Business de ABGA
- [ ] Iniciar proceso de aprobación Meta si no está activa
- [ ] Diseñar flujo conversacional (mapa de intenciones)
- [ ] Definir consultas que puede responder el agente
- [ ] Implementar webhook WhatsApp Business en n8n
- [ ] Sistema de autenticación de clientes por teléfono + CIF
- [ ] Integración GET Clientes apiCON para validar identidad
- [ ] Integración GET Facturas para consultas de estado
- [ ] Integración alertas fiscales para consultas de impuestos
- [ ] Agente Claude con memoria de conversación
- [ ] Manejo de intenciones no reconocidas (fallback al asesor)
- [ ] Log de conversaciones en Excel
- [ ] Test con usuarios piloto

---

## 🔴 REQ-08 — Memoria de Cuentas Anuales

**Estado:** 🔴 Pendiente  
**Dependencias:** BLOQ-01, BLOQ-06, BLOQ-07

### Por hacer
- [ ] Recibir plantilla/ejemplo Memoria Anual de Iván
- [ ] Mapear apartados legales obligatorios (PGC + Código de Comercio)
- [ ] Diseñar arquitectura del workflow
- [ ] GET datos balance cierre ejercicio via apiCON
- [ ] Formulario para que el asesor introduzca notas adicionales
- [ ] Prompt Claude con estructura legal de la Memoria
- [ ] Generar texto de cada apartado: actividad, bases presentación, normas valoración, inmovilizado, deudas, situación fiscal, etc.
- [ ] Revisión humana obligatoria antes de entrega
- [ ] Exportar a Word/PDF para firma
- [ ] Validación legal con Iván
- [ ] Test con cuentas anuales reales

---

## 🏗️ Infraestructura y DevOps

- [ ] Securizar credenciales en n8n Credentials Store (sacar de texto plano en workflows)
- [ ] Cambiar apiCON de HTTP a HTTPS (actualmente sin cifrado)
- [ ] Configurar alertas de error en n8n (email al equipo SolucionIA)
- [ ] Crear tabla Excel dedicada `Tabla_Envios_REQ05_06` en SharePoint
- [ ] Crear tabla Excel dedicada `Tabla_Alertas_Fiscales` en SharePoint
- [ ] Documentar todos los IDs de credenciales n8n
- [ ] Configurar backup de workflows n8n

---

## 📊 Resumen de progreso

| Módulo | Completado | Pendiente | Total |
|--------|-----------|-----------|-------|
| REQ-03 | 13 | 6 | 19 |
| REQ-05 | 16 | 6 | 22 |
| REQ-06 | 19 | 5 | 24 |
| REQ-01 | 0 | 11 | 11 |
| REQ-02 | 0 | 10 | 10 |
| REQ-04 | 0 | 12 | 12 |
| REQ-07 | 0 | 13 | 13 |
| REQ-08 | 0 | 10 | 10 |
| Infra | 0 | 7 | 7 |
| **TOTAL** | **48** | **80** | **128** |

**Progreso global: 38% completado**
