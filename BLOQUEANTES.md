# ⚠️ BLOQUEANTES — Datos pendientes de ABGA

> Documento de seguimiento de la información técnica pendiente de confirmar con Iván Baños (ABGA Consultores).  
> Email enviado: Junio 2026

---

## 🔴 BLOQ-01 — Código de empresa en ERP K1970

**Bloquea:** REQ-01, REQ-02, REQ-03, REQ-04, REQ-05, REQ-06, REQ-07, REQ-08  
**Estado:** ⏳ Pendiente respuesta de Iván

**Descripción:**  
El campo `cod_empresa` en la autenticación de apiCON requiere el código numérico interno de ABGA en Cegid K1970. Todos los workflows fallan con `Error 3 - No tiene acceso a la empresa indicada` hasta que se proporcione este dato.

**Dónde usar:**  
Nodo `Auth apiCON` en todos los workflows — sustituir `codigoEmpresa` por el valor real.

```
// Antes
"cod_empresa": "codigoEmpresa"

// Después (ejemplo)
"cod_empresa": "69"
```

---

## 🟡 BLOQ-02 — Emails de clientes en ERP

**Bloquea:** REQ-05, REQ-06, REQ-03  
**Estado:** ⏳ Pendiente respuesta de Iván

**Descripción:**  
Los workflows de envío asumen que el campo `Mail` del endpoint `GET /api/clientes/` está poblado para todos los clientes de ABGA. Si no está poblado, los envíos no funcionarán.

**Pregunta a Iván:**  
¿Los clientes de ABGA tienen email registrado en el ERP? ¿En qué campo exacto?

---

## 🟡 BLOQ-03 — PDF ejemplo informe Autodespro

**Bloquea:** REQ-03 (ajuste final)  
**Estado:** ⏳ Pendiente respuesta de Iván

**Descripción:**  
El workflow REQ-03 genera un informe con formato estándar PGC. Para replicar exactamente el formato Autodespro que usa actualmente ABGA necesitamos ver un ejemplo real.

**Qué necesitamos:**  
Un PDF de ejemplo del informe Autodespro que ABGA envía actualmente a sus clientes (puede ser con datos ficticios).

---

## 🟡 BLOQ-04 — Formato extractos bancarios

**Bloquea:** REQ-01  
**Estado:** ⏳ Pendiente respuesta de Iván

**Preguntas:**
1. ¿En qué formato llegan los extractos bancarios? (Excel, PDF, OFX, CSV, MT940...)
2. ¿Cómo llegan? ¿Por email, descarga manual del portal del banco, o hay open banking?
3. ¿Con qué bancos trabaja ABGA principalmente?

---

## 🟡 BLOQ-05 — WhatsApp Business de ABGA

**Bloquea:** REQ-07  
**Estado:** ⏳ Pendiente respuesta de Iván

**Preguntas:**
1. ¿Tiene ABGA ya una cuenta de WhatsApp Business creada y aprobada por Meta?
2. ¿Hay un número de teléfono dedicado para el agente o habría que crear uno nuevo?

**Nota:** La aprobación de Meta puede tardar días/semanas. Iniciar el proceso cuanto antes aunque el desarrollo del REQ-07 sea posterior.

---

## 🟡 BLOQ-06 — Histórico de datos en ERP

**Bloquea:** REQ-02, REQ-08  
**Estado:** ⏳ Pendiente respuesta de Iván

**Descripción:**  
Para el módulo de proyecciones (REQ-02) se necesitan mínimo 2 años de histórico contable. Para la Memoria Anual (REQ-08) se necesita el cierre del ejercicio anterior.

**Pregunta:**  
¿Cuántos años de datos históricos hay registrados en el ERP K1970?

---

## 🟡 BLOQ-07 — Plantilla Memoria de Cuentas Anuales

**Bloquea:** REQ-08  
**Estado:** ⏳ Pendiente respuesta de Iván

**Descripción:**  
Para generar la Memoria Anual conforme a normativa necesitamos ver el formato que usa actualmente ABGA.

**Qué necesitamos:**  
Una Memoria de Cuentas Anuales de ejemplo (puede ser con datos ficticios o de un ejercicio anterior).

---

## 📬 Historial de comunicaciones

| Fecha | Medio | Asunto | Estado |
|-------|-------|--------|--------|
| 28 mayo 2026 | Email (Iván → Pedro) | Solicitud inicial del proyecto con lista de 8 automatizaciones y envío de APIs | ✅ Recibido |
| Junio 2026 | Email (Pedro → Iván) | Solicitud `cod_empresa` + 9 datos técnicos adicionales | ⏳ Sin respuesta |

---

*Actualizar este documento cuando se reciban respuestas de Iván.*
