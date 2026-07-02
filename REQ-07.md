# REQ-07 — Agente WhatsApp Business

**Categoría:** Canal Digital  
**Estado:** 🔴 Pendiente  
**Bloqueantes:** BLOQ-01, BLOQ-05

## Descripción
Agente conversacional inteligente conectado a la API oficial de WhatsApp Business. Autentica al cliente, resuelve consultas frecuentes sobre su estado fiscal y contable y consulta el ERP para devolver datos básicos en tiempo real bajo demanda.

## Stack técnico
- WhatsApp Business API (Meta)
- Webhook n8n
- Claude Sonnet 4 (agente conversacional)
- apiCON + apiREC para consultas en tiempo real

## Consultas que puede resolver
- Estado de facturas pendientes
- Saldo IVA del trimestre actual
- Próximas fechas de presentación fiscal
- Resultado del último período
- Estado de nóminas

## Pendiente
- Aprobación Meta para WhatsApp Business
- Número de teléfono dedicado
- Diseño mapa de intenciones
