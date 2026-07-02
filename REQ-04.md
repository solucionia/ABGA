# REQ-04 — Duplicidad de Facturas

**Categoría:** Auditoría / IA  
**Estado:** 🔴 Pendiente  
**Bloqueantes:** BLOQ-01

## Descripción
Control de riesgos y auditoría de facturas recibidas y emitidas. Detecta facturas duplicadas a partir de la coincidencia simultánea de varios parámetros (CIF, importe, fecha, base, numeración similar o errores de OCR).

## APIs a utilizar
- `apiCON /api/facturas/` — facturas contables
- `apiREC /api/invoices/` — facturas de facturación

## Algoritmo de detección
- CIF proveedor/cliente (coincidencia exacta)
- Importe total (tolerancia ±0.01 EUR)
- Fecha (tolerancia ±3 días)
- Base imponible (coincidencia exacta)
- Número de factura (distancia Levenshtein ≤ 2)
- Corrección errores OCR en numeración

## Niveles de riesgo
- PROBABLE: 4+ parámetros coinciden
- POSIBLE: 3 parámetros coinciden
- REVISAR: 2 parámetros críticos coinciden
