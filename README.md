# 🤖 Proyecto IA — ABGA Consultores

> Automatización e inteligencia artificial para asesoría contable y fiscal  
> Cliente: **ABGA Consultores** (Iván Baños) · Madrid  
> Desarrollado por: **SolucionIA.ai** (Pedro)  
> Inicio: Junio 2026

---

## 📋 Descripción

Sistema de automatización completo para ABGA Consultores, despacho de asesoría contable y fiscal con ERP propio **Cegid K1970** (Diez Software). El proyecto comprende **8 módulos funcionales** que automatizan desde el envío de informes financieros hasta un agente conversacional de WhatsApp.

---

## 🏗️ Arquitectura del sistema

```
┌─────────────────────────────────────────────────────────┐
│                    ERP Cegid K1970                       │
│  ┌──────────┐ ┌──────────┐ ┌──────────┐ ┌──────────┐   │
│  │ apiCON   │ │ apiREC   │ │ apiERP   │ │ apiNOM   │   │
│  │Contab.   │ │Facturac. │ │Base ERP  │ │Nóminas   │   │
│  └────┬─────┘ └────┬─────┘ └────┬─────┘ └────┬─────┘   │
└───────┼────────────┼────────────┼─────────────┼─────────┘
        │            │            │             │
        └────────────┴────────────┴─────────────┘
                              │
                    ┌─────────▼─────────┐
                    │      n8n           │
                    │  (Automatización)  │
                    └─────────┬─────────┘
                              │
              ┌───────────────┼───────────────┐
              │               │               │
    ┌─────────▼──────┐ ┌──────▼──────┐ ┌─────▼──────────┐
    │ Claude Sonnet 4│ │MS Outlook   │ │MS Excel        │
    │ (IA + informes)│ │(Envío email)│ │(SharePoint log)│
    └────────────────┘ └─────────────┘ └────────────────┘
```

---

## 📦 Stack tecnológico

| Componente | Tecnología |
|------------|------------|
| Automatización | n8n (self-hosted) |
| IA / LLM | Claude Sonnet 4 (Anthropic) + GPT-4o (OpenAI) |
| ERP | Cegid K1970 / Diez Software |
| Email | Microsoft Outlook (Graph API) |
| Almacenamiento | Microsoft OneDrive |
| Registro | Microsoft Excel (SharePoint) |
| Canal digital | WhatsApp Business API (Meta) |

---

## 🗂️ Módulos del proyecto

| ID | Módulo | Categoría | Estado |
|----|--------|-----------|--------|
| [REQ-01](./docs/REQ-01.md) | Cotejo y conciliación de mayores | Core Contable | 🔴 Pendiente |
| [REQ-02](./docs/REQ-02.md) | Proyecciones y predicciones | IA Analítica | 🔴 Pendiente |
| [REQ-03](./docs/REQ-03.md) | Informe financiero Autodespro | Reportería | 🟡 En desarrollo |
| [REQ-04](./docs/REQ-04.md) | Detección de facturas duplicadas | Auditoría / IA | 🔴 Pendiente |
| [REQ-05](./docs/REQ-05.md) | Envío balances y PyG | Automatización | 🟡 En desarrollo |
| [REQ-06](./docs/REQ-06.md) | Alertas fiscales trimestrales | Automatización | 🟡 En desarrollo |
| [REQ-07](./docs/REQ-07.md) | Agente WhatsApp Business | Canal Digital | 🔴 Pendiente |
| [REQ-08](./docs/REQ-08.md) | Memoria de cuentas anuales | IA Generativa | 🔴 Pendiente |

**Leyenda:** 🟢 Completado · 🟡 En desarrollo · 🔴 Pendiente · ⏸️ Bloqueado

---

## 🔑 APIs disponibles

Todas las APIs son REST con autenticación Bearer token. Documentación en `/api-docs/`.

| API | Base URL | Auth | Endpoints clave |
|-----|----------|------|-----------------|
| apiCON | `http://apicon.diezsoftware.com` | OAuth2 form-urlencoded | `/subcuentas/`, `/facturas/`, `/apuntes/`, `/clientes/` |
| apiREC | `https://apirec.diezsoftware.com` | Bearer token | `/invoices/`, `/customers/`, `/concepts/` |
| apiERP | `http://apierp.diezsoftware.com` | Bearer token | `/Company/getCompanies` |
| apiNOM | `https://apinom.diezsoftware.com` | Bearer token | `/Employees/`, `/Payroll/` |

> ⚠️ **Importante:** El campo `cod_empresa` en apiCON requiere el código numérico real de ABGA — pendiente de confirmar con Iván Baños.

---

## 🔧 Configuración n8n

### Credenciales requeridas

```
Microsoft Outlook:  pjf6Zx2OeH55DmSj  ("Microsoft comunicaciones abgb")
Microsoft Excel:    c9sEIzloOWrlt9EB
Anthropic:          ZLK1U10HmfnpD128  ("Team agent")
```

### Importar workflows

1. Abrir n8n → Settings → Import workflow
2. Seleccionar el JSON correspondiente de `/workflows/`
3. Sustituir `codigoEmpresa` por el código real en los nodos de autenticación

---

## 📁 Estructura del repositorio

```
abga-ia/
├── README.md                    # Este archivo
├── TASKS.md                     # Tareas y estado del proyecto
├── BLOQUEANTES.md               # Datos pendientes de ABGA
│
├── workflows/                   # JSONs importables en n8n
│   ├── REQ-03_informe_autodespro.json
│   ├── REQ-05_envio_balances_pyg.json
│   ├── REQ-06_alertas_fiscales.json
│   └── REQ-existente_procesado_facturas.json
│
├── docs/                        # Documentación por módulo
│   ├── REQ-01.md
│   ├── REQ-02.md
│   ├── REQ-03.md
│   ├── REQ-04.md
│   ├── REQ-05.md
│   ├── REQ-06.md
│   ├── REQ-07.md
│   └── REQ-08.md
│
├── api-docs/                    # Colecciones Postman originales
│   ├── apiCON_K1970.postman_collection.json
│   ├── apiREC_K1970.postman_collection.json
│   ├── apiERP_K1970.postman_collection.json
│   └── apiNOM_K1970.postman_collection.json
│
└── prompts/                     # Prompts de Claude por módulo
    ├── REQ-03_prompt_informe.md
    ├── REQ-05_prompt_pyg.md
    └── REQ-06_prompt_alerta_fiscal.md
```

---

## ⚠️ Bloqueantes activos

Ver [BLOQUEANTES.md](./BLOQUEANTES.md) para el detalle completo.

1. **`cod_empresa` de ABGA en K1970** — bloquea todos los módulos
2. **Campo `Mail` en clientes ERP** — bloquea REQ-05 y REQ-06
3. **PDF ejemplo Autodespro** — bloquea ajuste final de REQ-03
4. **Extractos bancarios** — bloquea REQ-01
5. **WhatsApp Business cuenta** — bloquea REQ-07

---

## 📬 Contacto cliente

**Iván Baños Belinchón**  
ABGA Consultores · Calle Saturnino Calleja 6, 1ºC · 28002 Madrid  
Tel: 913 788 740  
Email: comunicaciones@abgaconsultores.com

---

*Proyecto gestionado por SolucionIA.ai · Mascoverso S.L. · CIF B16864043 · elisa@solucionia.ai*
