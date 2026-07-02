# REQ-01 — Cotejo y Conciliación de Mayores

**Categoría:** Core Contable  
**Estado:** 🔴 Pendiente  
**Bloqueantes:** BLOQ-01, BLOQ-04

## Descripción
Conciliación automática que compara los asientos del libro mayor del ERP con fuentes externas (bancos y registros analíticos) y empareja importes, fechas y conceptos aunque existan pequeñas desviaciones.

## APIs a utilizar
- `apiCON /api/apuntes/` — asientos del período
- `apiCON /api/subcuentas/` — saldos por cuenta

## Pendiente confirmación de Iván
- Formato extractos bancarios (PDF, Excel, OFX, CSV, MT940)
- Canal de entrega de extractos
- Bancos principales de ABGA
