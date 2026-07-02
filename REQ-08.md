# REQ-08 — Memoria de Cuentas Anuales

**Categoría:** IA Generativa  
**Estado:** 🔴 Pendiente  
**Bloqueantes:** BLOQ-01, BLOQ-06, BLOQ-07

## Descripción
Generación automática de texto para la Memoria Anual. A partir de los datos numéricos de los balances y de las notas que introduce el asesor, redacta de forma coherente y conforme a normativa los distintos apartados del documento legal.

## Marco legal
- Plan General de Contabilidad (PGC 2007)
- Código de Comercio
- Orden JUS/206/2009

## Apartados de la Memoria a generar
1. Actividad de la empresa
2. Bases de presentación de las cuentas anuales
3. Normas de valoración aplicadas
4. Inmovilizado material e intangible
5. Inversiones financieras
6. Fondos propios
7. Situación fiscal
8. Ingresos y gastos
9. Información sobre el personal
10. Otras informaciones

## APIs a utilizar
- `apiCON /api/subcuentas/` — saldos cierre ejercicio
- `apiCON /api/facturas/` — datos facturación anual
- `apiNOM /api/Payroll/` — datos personal

## Pendiente
- Recibir plantilla Memoria de ejemplo de Iván
- Confirmar ejercicio a documentar
- Diseñar formulario para notas del asesor
