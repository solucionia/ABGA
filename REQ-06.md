# REQ-06 — Alertas Fiscales Trimestrales

**Categoría:** Automatización  
**Estado:** 🟡 En desarrollo  
**Workflow:** `workflows/REQ-06_alertas_fiscales.json`

---

## Descripción

Alertas y resúmenes fiscales informativos. Calcula y consolida de forma automatizada el estado real del devengo de impuestos (IVA, Retenciones, IS) y envía notificaciones periódicas a los clientes para evitar sorpresas en el cierre trimestral.

---

## Flujo del workflow

```
Schedule (día 15 de mes de cierre trimestral) / Manual
    → Calcular Período (trimestre, fecha límite, modelos)
    → Auth apiERP + Auth apiCON + Auth apiNOM (paralelo)
    → Merge Tokens (3 inputs) → Guardar Tokens
    → GET Companies
    → Loop por Empresa
        → GET Cliente → Extraer email
        → ¿Tiene email? → Skip si no
        → GET Apuntes IVA (cuentas 47x) + GET Apuntes Retenciones (475x) + GET Total Nóminas (paralelo)
        → Calcular Situación Fiscal
        → Preparar Prompt
        → Agente Claude → Email alerta HTML
        → Preparar Email (asunto con nivel alerta + fecha límite)
        → Enviar Email (Outlook)
        → Log en Excel (empresa, email, trimestre, total obligaciones, nivel alerta)
        → Siguiente empresa
```

---

## Trigger

- **Automático:** Cron `0 9 15 3,6,9,12 *` — día 15 de marzo, junio, septiembre y diciembre
- **Manual:** Para testing

---

## Cálculo fiscal

### IVA
- **Cuenta 477** (IVA repercutido) = Haber - Debe → saldo a ingresar
- **Cuenta 472** (IVA soportado deducible) = Debe - Haber → saldo a favor
- **Saldo neto IVA** = IVA repercutido - IVA soportado

### Retenciones IRPF
- **Cuentas 4751, 475** = Haber - Debe → retenciones a ingresar (Modelo 111)

### Impuesto de Sociedades
- Solo Q1 y Q3 → pago fraccionado (Modelo 202)
- Estimación conservadora basada en ingresos del período

### Modelos a presentar por trimestre
| Trimestre | Modelos | Fecha límite |
|-----------|---------|-------------|
| Q1 (ene-mar) | 303 + 111 + 202 | 20 de abril |
| Q2 (abr-jun) | 303 + 111 | 20 de julio |
| Q3 (jul-sep) | 303 + 111 + 202 | 20 de octubre |
| Q4 (oct-dic) | 303 + 111 + 390 | 30 de enero |

### Niveles de alerta
- 🔴 **ALTA:** IVA a ingresar > 3.000 EUR
- 🟡 **MEDIA:** Obligaciones fiscales normales
- 🔵 **INFO:** IVA a devolver u otras novedades

---

## APIs utilizadas

| API | Endpoint | Uso |
|-----|----------|-----|
| apiERP | `GET /api/Company/getCompanies` | Lista empresas |
| apiCON | `GET /api/clientes/` | Email cliente |
| apiCON | `GET /api/apuntes/` filtro cuentas 47x | Asientos IVA |
| apiCON | `GET /api/apuntes/` filtro cuentas 475x | Asientos retenciones |
| apiNOM | `GET /api/Payroll/totalNominas/{id}` | Total nóminas |

---

## Pendiente

- [ ] Sustituir `codigoEmpresa` por código real (BLOQ-01)
- [ ] Test con datos reales de IVA
- [ ] Confirmar modelos adicionales (115, 123, 130...)
- [ ] Activar en producción
