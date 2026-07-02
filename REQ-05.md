# REQ-05 — Envío Automático de Balances y PyG

**Categoría:** Automatización  
**Estado:** 🟡 En desarrollo  
**Workflow:** `workflows/REQ-05_envio_balances_pyg.json`

---

## Descripción

Distribución automatizada vía email de los estados financieros (PyG y Balance de Situación) extraídos del ERP, empaquetados en HTML y enviados de forma masiva pero segmentada a cada cliente de ABGA.

---

## Flujo del workflow

```
Schedule (último día trimestre 9:00) / Manual
    → Calcular Período (trimestre, año)
    → Auth apiERP + Auth apiCON (paralelo)
    → Merge Tokens → Guardar Tokens
    → GET Companies
    → Loop por Empresa
        → GET Cliente → Extraer email
        → ¿Tiene email? → Skip si no
        → GET Facturas + GET Apuntes (paralelo)
        → Preparar Prompt (cálculo ingresos, gastos, IVA, resultado)
        → Agente Claude → Informe HTML PyG
        → Preparar Email
        → Enviar Email (Outlook)
        → Log en Excel (SharePoint)
        → Siguiente empresa
```

---

## Trigger

- **Automático:** Cron `0 9 28-31 3,6,9,12 *` — último día hábil de cada trimestre
- **Manual:** Para testing y envíos bajo demanda

---

## APIs utilizadas

| API | Endpoint | Uso |
|-----|----------|-----|
| apiERP | `GET /api/Company/getCompanies` | Lista empresas |
| apiCON | `GET /api/clientes/` | Email cliente |
| apiCON | `GET /api/facturas/` | Facturas ejercicio |
| apiCON | `GET /api/apuntes/` | Asientos ejercicio |

---

## Pendiente

- [ ] Sustituir `codigoEmpresa` por código real (BLOQ-01)
- [ ] Confirmar campo Mail en clientes ERP (BLOQ-02)
- [ ] Test end-to-end con datos reales
- [ ] Validar formato HTML con Iván
