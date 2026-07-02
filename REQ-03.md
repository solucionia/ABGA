# REQ-03 — Informe Financiero Autodespro

**Categoría:** Reportería  
**Estado:** 🟡 En desarrollo  
**Workflow:** `workflows/REQ-03_informe_autodespro.json`

---

## Descripción

Generación automatizada de informes económicos detallados bajo el estándar del modelo "Autodespro", consolidando balance, cuenta de pérdidas y ganancias y ratios clave del ERP en un formato visual listo para entregar al cliente.

---

## Flujo del workflow

```
Schedule (1 de cada mes 8:00) / Manual
    → Calcular Período (mes, trimestre, año)
    → Auth apiERP + Auth apiCON (paralelo)
    → Merge Tokens → Guardar Tokens
    → GET Companies (apiERP)
    → Loop por Empresa
        → GET Cliente (email, CIF, nombre)
        → ¿Tiene email? → Skip si no
        → GET Subcuentas (saldos PGC) + GET Facturas + GET Apuntes (paralelo)
        → Calcular Estados Financieros (PyG + Balance + Ratios)
        → Agente Claude → Informe HTML Autodespro
        → Enviar Email (Outlook)
        → Log en Excel (SharePoint)
        → Siguiente empresa
```

---

## APIs utilizadas

| API | Endpoint | Uso |
|-----|----------|-----|
| apiERP | `GET /api/Company/getCompanies` | Lista de empresas |
| apiCON | `GET /api/clientes/` | Email y datos del cliente |
| apiCON | `GET /api/subcuentas/` | Saldos plan de cuentas PGC |
| apiCON | `GET /api/facturas/` | Facturas del ejercicio |
| apiCON | `GET /api/apuntes/` | Asientos contables |

---

## Cálculos financieros

### Cuenta de Resultados (PyG PGC)
- **Ingresos:** Cuentas grupo 7 (70x ventas, 75x otros ingresos)
- **Aprovisionamientos:** Cuentas grupo 60, 61
- **Gastos personal:** Cuentas grupo 64
- **Otros gastos explotación:** Cuentas grupo 62, 63, 65
- **Amortizaciones:** Cuentas grupo 68
- **EBIT** = Ingresos - Gastos explotación
- **EBITDA** = EBIT + Amortizaciones
- **Resultado neto** = RAI - IS estimado (25%)

### Balance de Situación
- **Activo no corriente:** Grupos 20, 21, 22, 25, 26
- **Activo corriente:** Grupos 30-35 (existencias), 43-44 (clientes), 57 (tesorería)
- **Patrimonio neto:** Grupos 10, 11, 12
- **Pasivo no corriente:** Grupos 15, 16, 17
- **Pasivo corriente:** Grupos 40, 41, 47, 52, 53

### Ratios calculados
| Ratio | Fórmula | Verde | Naranja | Rojo |
|-------|---------|-------|---------|------|
| Margen neto | Resultado neto / Ingresos × 100 | >10% | 5-10% | <5% |
| Margen EBITDA | EBITDA / Ingresos × 100 | >15% | 8-15% | <8% |
| Ratio gastos | Gastos / Ingresos × 100 | <70% | 70-85% | >85% |
| Liquidez | Activo corriente / Pasivo corriente | >1.5 | 1-1.5 | <1 |
| Endeudamiento | Deudas / Activo total × 100 | <50% | 50-70% | >70% |
| ROE | Resultado neto / PN × 100 | >10% | 5-10% | <5% |

---

## Estructura del informe HTML

1. Portada (logo ABGA, empresa, período)
2. Resumen ejecutivo (análisis 4-5 líneas)
3. Cuenta de Pérdidas y Ganancias (tabla PGC completa)
4. Balance de Situación (dos columnas: activo / pasivo+PN)
5. Ratios e indicadores (grid 6 tarjetas con semáforos)
6. Evolución mensual (tabla por mes)
7. Análisis y recomendaciones (4 puntos accionables)
8. Pie de página ABGA

---

## Pendiente

- [ ] Recibir PDF ejemplo Autodespro de Iván para ajustar formato
- [ ] Sustituir `codigoEmpresa` por código real
- [ ] Test con datos reales de ABGA
