# Clientes y Ajustes · datos reales, y qué hay que tocar en el hub

Dos traductores nuevos —`frontend/hub/pantallas/clientes.js` y `frontend/hub/pantallas/ajustes.js`—
que dejan en el hub lo que la plataforma sabe de verdad de la cartera de clientes y del panel de
ajustes, en el mismo sitio y con la misma forma que el hub ya usaba (ver `pantallas/inicio.js`).
Nada de cifras inventadas: lo que no existe se declara con `ctx.sinDatos` y se queda a la vista.

## Cómo se alimenta cada pantalla

### Clientes (`rvClientes` + la ficha)

| Dato del hub | De dónde sale |
| --- | --- |
| `MOCK.CLIENTES` (lista y ficha) | `GET /api/empresas` (`ctx.estado.empresas`): `cod_empresa`, `nombre`,
| | `ejercicio_inicio` y `notas`. El **NIF** y los **servicios contratados** se leen de `notas`, que es donde
| | los tiene la plataforma (`"NIF B67700856 · contabilidad General · laboral · obligaciones"`): 389 de las
| | 391 empresas lo llevan. Si no está, se deja vacío. |
| Semáforo de `CLIENTES` (`estado`) | `GET /api/interno/cartera?year=` (sólo interno): `nivel_global` por cliente
| | → `alerta`=Incidencia, `aviso`=Atención, `ok`=Al día, `no_evaluable`/nada analizado=**Sin analizar**.
| | Un cliente con su propia cuenta usa `GET /api/analisis` de su empresa (sólo si el ejercicio está en caché). |
| `fichaContactos` | `GET /api/interno/usuarios`: qué cuentas de portal tienen acceso a cada empresa. |
| `fichaDatos` (análisis) | La fila de la cartera: `nivel_global`, `n_rojo` y `n_total`. |
| `MOCK.DOCS` y `MOCK.ENVIOS` (y `s.envios`) | Se vacían: no hay endpoint detrás. |
| `MOCK.IMPUESTOS` | No se toca: lo alimenta el traductor de la pantalla de Impuestos con lo que
| | calcula el módulo fiscal (303, 111 y 202 por trimestre). |
| `fichaCA` | Se vacía (el histórico estaba escrito a mano dentro de la pantalla). |

### Ajustes (`rvAj`)

| Dato del hub | De dónde sale |
| --- | --- |
| `s.ajUsers` | `GET /api/interno/usuarios`: `nombre`, `email`, `rol`, `activo`, `creado` y `empresas` (el
| | número de clientes asignados). |
| `s.ajErp`, `s.ajErpAt` y `s.ajCache` (tabla del ERP) | `GET /api/cache`: los ejercicios leídos, con sus
| | asientos, sus líneas y la fecha de la última lectura. El estado de conexión, de la caché y de `/api/salud`. |
| `s.ajUmbrales` (antes «Automatización IA») | `GET /api/interno/umbrales?cod_empresa=`: los 12 umbrales del
| | análisis del cliente en curso, con su valor, su unidad, para qué sirven y su origen. |
| `s.ajDespacho` | La sesión de la plataforma (`ctx.estado.usuario`): cuenta, correo, rol, estado y alta. |
| `ajCreate` (crear usuario) | `POST /api/interno/usuarios`, que genera la contraseña (se enseña una vez). |

## Lo que la plataforma no tiene (declarado con `ctx.sinDatos`)

Clientes:

- el estado de los clientes que no tienen el ejercicio leído (el análisis sólo cubre la caché);
- los documentos del expediente del cliente;
- los envíos de informes al cliente;
- el estado de presentación de cada modelo por cliente (la plataforma calcula los 303, 111 y 202; no
  registra qué se ha presentado, y la ficha de un cliente no tiene datos fiscales propios);
- el depósito de las cuentas anuales por ejercicio;
- el domicilio, la forma jurídica, el CNAE, el régimen de IVA, la plantilla, la facturación anual y el
  factor de escala del cliente, su asesor asignado y la persona de contacto con teléfono y correo.

Ajustes:

- los datos fiscales del despacho (razón social, NIF, dirección) y su correo de envío a clientes;
- el ejercicio por defecto, el plan contable y el pie de los informes;
- las preferencias de notificación por tipo de aviso;
- los interruptores de automatización de la IA;
- el último acceso de cada usuario (la plataforma guarda el alta de la cuenta).

## Parches para `frontend/hub/index.html`

Los parches son el texto exacto del fichero: se han generado extrayéndolo del propio `index.html` y
comprobando que cada uno aparece **una sola vez** (ver más abajo cómo se verificaron). Hay que aplicarlos
**en bloque**: por ejemplo, `ajAutoSw` y `ajNotifSw` desaparecen de `rvAj` y sólo dejan de usarse cuando se
aplican los parches de «Automatización IA» y «Notificaciones».

Dos avisos de coordinación con los demás traductores del hub, que se están escribiendo a la vez:

- La pestaña «Impuestos» de la ficha **no se toca aquí**: su matriz (`IMPUESTOS`) y la cabecera del
  «Próximo vencimiento» las cubre `pantallas/impuestos.js` con los parches P11, P12 y P13 de
  `impuestos.md`. Este traductor deja `IMPUESTOS` en paz justamente por eso, y la ficha lee `IMP_EST`
  con un valor por defecto para no romperse si esos parches aún no están puestos.
- El parche de las etiquetas `<script>` es el mismo sitio donde otros traductores (`impuestos.js`,
  `cuentas-anuales.js`, …) añaden las suyas: al aplicarlos hay que dejar una sola lista con **todas**
  las pantallas. Este parche añade sólo `pantallas/clientes.js` y `pantallas/ajustes.js`.

### 1. rvClientes() — la lista y la ficha

**Actual** (3951 caracteres)

```html
  rvClientes(){
    const s = this.state, q = s.cliSearch.trim().toLowerCase(), EL = {ok:'Al día', warn:'Atención', err:'Incidencia'};
    const cliRows = CLIENTES.filter(c => !q || c.nombre.toLowerCase().includes(q) || c.nif.toLowerCase().includes(q) || c.ciudad.toLowerCase().includes(q)).map((c, i) => ({nombre:c.nombre, nif:c.nif, ciudad:c.ciudad, asesor:c.asesor, fact:eur(c.fact), estado:EL[c.estado], fg:T(c.estado).fg, bg:T(c.estado).bg, onClick:() => this.openFicha(c.id), rowBg: i % 2 ? 'var(--surface2)' : 'var(--surface)'}));
    const c = s.fichaId ? cli(s.fichaId) : CLIENTES[0];
    const TABS = [['datos','Datos'],['documentos','Documentos'],['envios','Envíos'],['impuestos','Impuestos'],['cuentas','Cuentas anuales']];
    const cEnv = s.envios.filter(e => e.cli === c.id);
    const fichaTabs = TABS.map(([k2, l]) => ({label:l, onClick:() => this.setState({fichaTab:k2}), fg: s.fichaTab === k2 ? 'var(--accent-strong)' : 'var(--muted)', bd: s.fichaTab === k2 ? 'var(--accent)' : 'transparent', count: k2 === 'documentos' ? DOCS.length : k2 === 'envios' ? cEnv.length + 3 : k2 === 'cuentas' ? 3 : ''}));
    const OR = {ia:['Clasificado por IA','ai'], cliente:['Subido por el cliente','accent'], asesor:['Subido por el despacho','muted']};
    return {
      cliSearch:s.cliSearch, setCliSearch:e => this.setState({cliSearch:e.target.value}), cliRows, cliCount:cliRows.length, cliEmpty:!cliRows.length, cliHas:cliRows.length > 0,
      ficha:{...c, factTxt:eur(c.fact), ini:c.nombre.split(' ').slice(0,2).map(w => w[0]).join(''), estadoTxt:EL[c.estado], fg:T(c.estado).fg, bg:T(c.estado).bg, empleadosTxt:String(c.empleados)},
      fichaDatos:[['Razón social', c.nombre], ['NIF', c.nif], ['Forma jurídica', c.forma], ['Actividad (CNAE)', c.cnae], ['Domicilio fiscal', c.ciudad], ['Régimen de IVA', c.iva], ['Plantilla', c.empleados + ' personas'], ['Cliente desde', c.alta], ['Facturación último ejercicio', eur(c.fact)], ['Asesor asignado', c.asesor]].map(([k2, v]) => ({k:k2, v})),
      fichaContactos:[{nombre:c.contacto, rol:'Administración', email:c.email, tel:c.telefono}, {nombre:'Gestoría laboral externa', rol:'Nóminas', email:'laboral@puigasociados.es', tel:'+34 972 410 223'}],
      fichaTabs, fT_datos:s.fichaTab === 'datos', fT_docs:s.fichaTab === 'documentos', fT_env:s.fichaTab === 'envios', fT_imp:s.fichaTab === 'impuestos', fT_ca:s.fichaTab === 'cuentas',
      fichaDocs:DOCS.map((d, i) => ({...d, origenTxt:OR[d.origen][0], fg:T(OR[d.origen][1]).fg, bg:T(OR[d.origen][1]).bg, rowBg: i % 2 ? 'var(--surface2)' : 'var(--surface)'})),
      fichaEnvios:[...cEnv.map(e => ({fecha:String(e.dia).padStart(2,'0') + '/09/2026', tipo:e.tipo, periodo:e.periodo, estado:ENV_EST[e.estado].l, fg:T(ENV_EST[e.estado].t).fg, bg:T(ENV_EST[e.estado].t).bg})),
        {fecha:'22/08/2026', tipo:'Cuenta de resultados', periodo:'Julio 2026', estado:'Abierto', fg:'var(--ok)', bg:'var(--ok-soft)'}, {fecha:'04/08/2026', tipo:'Balance de situación', periodo:'Julio 2026', estado:'Abierto', fg:'var(--ok)', bg:'var(--ok-soft)'}, {fecha:'21/07/2026', tipo:'Situación de impuestos', periodo:'2T 2026', estado:'Enviado', fg:'var(--muted)', bg:'var(--surface2)'}],
      fichaImp:IMPUESTOS.map(r => ({modelo:r.modelo, desc:r.desc, cells:r.c.map(k2 => ({l:IMP_EST[k2].l, fg:T(IMP_EST[k2].t).fg, bg: k2 === 'na' ? 'transparent' : T(IMP_EST[k2].t).bg}))})),
      fichaCA:[{ej:'2025',estado:'En preparación',fg:'var(--ai)',bg:'var(--ai-soft)',detalle:'Borrador de la IA en revisión · formato abreviado'},{ej:'2024',estado:'Depositadas',fg:'var(--ok)',bg:'var(--ok-soft)',detalle:'Registro Mercantil de La Rioja · 28/07/2025'},{ej:'2023',estado:'Depositadas',fg:'var(--ok)',bg:'var(--ok-soft)',detalle:'Registro Mercantil de La Rioja · 24/07/2024'}],
      fichaGoCA:() => this.go('memoria'),
      backToClientes:() => this.setState({fichaId:null}), fichaGoConc:() => { this.loadConc(c.id, '572.0001'); this.go('conciliacion'); }
    };
  }
```

**Propuesto** (4435 caracteres)

```html
  rvClientes(){
    const s = this.state, q = s.cliSearch.trim().toLowerCase(), EL = {ok:'Al día', warn:'Atención', err:'Incidencia', na:'Sin analizar'};
    // Los datos del cliente salen de la plataforma (datos.js › pantallas/clientes.js): el NIF del
    // campo de notas de la empresa y el estado del análisis de la cartera. Lo que la plataforma no
    // guarda (domicilio, forma jurídica, CNAE, IVA, plantilla, facturación, asesor, contacto) se
    // pinta con raya, nunca con un ejemplo.
    const cliRows = CLIENTES.filter(c => !q || c.nombre.toLowerCase().includes(q) || c.nif.toLowerCase().includes(q) || c.ciudad.toLowerCase().includes(q)).map((c, i) => ({nombre:c.nombre, nif:c.nif || '—', ciudad:c.ciudad || '—', asesor:c.asesor || '—', fact:c.fact == null ? '—' : eur(c.fact), estado:EL[c.estado] || EL.na, fg:T(c.estado).fg, bg:T(c.estado).bg, onClick:() => this.openFicha(c.id), rowBg: i % 2 ? 'var(--surface2)' : 'var(--surface)'}));
    const c = (s.fichaId ? cli(s.fichaId) : CLIENTES[0]) || {id:null, nombre:'', nif:'', servicios:'', forma:'', cnae:'', ciudad:'', iva:'', empleados:0, alta:'', asesor:'', fact:null, contacto:'', email:'', telefono:'', estado:'na', cuentas:[], cartera:null};
    const TABS = [['datos','Datos'],['documentos','Documentos'],['envios','Envíos'],['impuestos','Impuestos'],['cuentas','Cuentas anuales']];
    const cEnv = s.envios.filter(e => e.cli === c.id);
    const fichaTabs = TABS.map(([k2, l]) => ({label:l, onClick:() => this.setState({fichaTab:k2}), fg: s.fichaTab === k2 ? 'var(--accent-strong)' : 'var(--muted)', bd: s.fichaTab === k2 ? 'var(--accent)' : 'transparent', count: k2 === 'documentos' ? DOCS.length : k2 === 'envios' ? cEnv.length : ''}));
    const OR = {ia:['Clasificado por IA','ai'], cliente:['Subido por el cliente','accent'], asesor:['Subido por el despacho','muted']};
    return {
      cliSearch:s.cliSearch, setCliSearch:e => this.setState({cliSearch:e.target.value}), cliRows, cliCount:cliRows.length, cliEmpty:!cliRows.length, cliHas:cliRows.length > 0,
      ficha:{...c, factTxt:c.fact == null ? '—' : eur(c.fact), ini:(c.nombre || '').split(' ').slice(0,2).map(w => w[0]).join(''), estadoTxt:EL[c.estado] || EL.na, fg:T(c.estado).fg, bg:T(c.estado).bg, empleadosTxt:c.empleados ? String(c.empleados) : '—'},
      fichaDatos:[['Razón social', c.nombre], ['NIF', c.nif || '—'], ['Servicios contratados', c.servicios || '—'], ['Análisis del ejercicio', c.cartera ? c.cartera.nivel + ' · ' + c.cartera.rojo + ' de ' + c.cartera.total + ' comprobaciones en rojo' : 'sin analizar'], ['Forma jurídica', c.forma || '—'], ['Actividad (CNAE)', c.cnae || '—'], ['Domicilio fiscal', c.ciudad || '—'], ['Régimen de IVA', c.iva || '—'], ['Plantilla', c.empleados ? c.empleados + ' personas' : '—'], ['Primer ejercicio con datos', c.alta || '—'], ['Facturación último ejercicio', c.fact == null ? '—' : eur(c.fact)], ['Asesor asignado', c.asesor || '—']].map(([k2, v]) => ({k:k2, v})),
      fichaContactos:(c.cuentas || []).map(u => ({nombre:u.nombre, rol:u.rol, email:u.email, tel:'—'})),
      fichaTabs, fT_datos:s.fichaTab === 'datos', fT_docs:s.fichaTab === 'documentos', fT_env:s.fichaTab === 'envios', fT_imp:s.fichaTab === 'impuestos', fT_ca:s.fichaTab === 'cuentas',
      fichaDocs:DOCS.map((d, i) => ({...d, origenTxt:(OR[d.origen] || ['—','muted'])[0], fg:T((OR[d.origen] || [0,'muted'])[1]).fg, bg:T((OR[d.origen] || [0,'muted'])[1]).bg, rowBg: i % 2 ? 'var(--surface2)' : 'var(--surface)'})),
      fichaImp:IMPUESTOS.map(r => ({modelo:r.modelo, desc:r.desc, cells:r.c.map(k2 => ({l:(IMP_EST[k2] || {l:'—',t:'muted'}).l, fg:T((IMP_EST[k2] || {t:'muted'}).t).fg, bg: k2 === 'na' ? 'transparent' : T((IMP_EST[k2] || {t:'muted'}).t).bg}))})),
      fichaVacioDocs:!DOCS.length, fichaVacioEnv:!cEnv.length, fichaVacioCA:true,
      fichaEnvios:cEnv.map(e => ({fecha:e.fecha || String(e.dia).padStart(2,'0'), tipo:e.tipo, periodo:e.periodo, estado:ENV_EST[e.estado].l, fg:T(ENV_EST[e.estado].t).fg, bg:T(ENV_EST[e.estado].t).bg})),
      fichaCA:[],
      fichaGoCA:() => this.go('memoria'),
      // «Conciliar mayores» cambia de pantalla con ese cliente, sin fijar una cuenta a mano: la
      // pantalla de Conciliación ya elige la cuenta con lo que trae la plataforma (pantallas/conciliacion.js).
      backToClientes:() => this.setState({fichaId:null}), fichaGoConc:() => { this.setState({concCliente:c.id}); this.go('conciliacion'); }
    };
  }
```

**Por qué** — La lista y la ficha salen de la plataforma (pantallas/clientes.js): el NIF y los servicios recuperados de las notas de la empresa, el estado del análisis de la cartera y las cuentas de portal. Se quitan los ejemplos que quedaban dentro de la propia pantalla: la facturación inventada (0,00 €), el contacto de gestoría con su correo, los tres envíos fijos, el «+3» y el «3» de los contadores de pestañas, el histórico de depósito de las cuentas anuales y el estado «Al día» que se daba por defecto (ahora, un cliente sin análisis previo se queda como «Sin analizar» y los que sí se han analizado llevan el nivel real de la cartera). También se protege la ficha contra una lista vacía, que antes reventaba la pantalla entera, y la búsqueda de `IMP_EST` se hace a prueba de códigos nuevos (los que escribe `pantallas/impuestos.js`). La matriz de la pestaña «Impuestos» de la ficha NO se vacía: la alimenta el traductor de la pantalla de Impuestos. Y «Conciliar mayores» deja de fijar la cuenta `572.0001` a mano: ahora cambia de pantalla con ese cliente y es la pantalla de Conciliación la que elige la cuenta con lo que trae la plataforma (lo contrario se rompía con el `CUENTAS` real).

### 2. Pestaña «Documentos» de la ficha (marcado)

**Actual** (2560 caracteres)

```html
<sc-if value="{{ fT_docs }}" hint-placeholder-val="{{ false }}">
  <section style="background:var(--surface);border:1px solid var(--border);border-radius:8px;overflow:hidden;animation:fadeIn .3s ease both;">
    <sc-raw-table role="table" style="width:100%;border-collapse:collapse;">
      <sc-raw-thead><sc-raw-tr>
        <sc-raw-th style="text-align:left;padding:8px 14px;font-size:11px;font-weight:600;color:var(--muted);text-transform:uppercase;letter-spacing:.04em;background:var(--surface2);border-bottom:1px solid var(--border);">Documento</sc-raw-th>
        <sc-raw-th style="text-align:left;padding:8px;font-size:11px;font-weight:600;color:var(--muted);text-transform:uppercase;letter-spacing:.04em;background:var(--surface2);border-bottom:1px solid var(--border);">Tipo</sc-raw-th>
        <sc-raw-th style="text-align:left;padding:8px;font-size:11px;font-weight:600;color:var(--muted);text-transform:uppercase;letter-spacing:.04em;background:var(--surface2);border-bottom:1px solid var(--border);">Fecha</sc-raw-th>
        <sc-raw-th style="text-align:left;padding:8px;font-size:11px;font-weight:600;color:var(--muted);text-transform:uppercase;letter-spacing:.04em;background:var(--surface2);border-bottom:1px solid var(--border);">Origen</sc-raw-th>
        <sc-raw-th style="text-align:right;padding:8px 14px;font-size:11px;font-weight:600;color:var(--muted);text-transform:uppercase;letter-spacing:.04em;background:var(--surface2);border-bottom:1px solid var(--border);">Tamaño</sc-raw-th>
      </sc-raw-tr></sc-raw-thead>
      <sc-raw-tbody>
        <sc-for list="{{ fichaDocs }}" as="d" hint-placeholder-count="6">
          <sc-raw-tr style="background:{{ d.rowBg }};">
            <sc-raw-td style="padding:9px 14px;border-bottom:1px solid var(--border);font-weight:500;">{{ d.nombre }}</sc-raw-td>
            <sc-raw-td style="padding:9px 8px;border-bottom:1px solid var(--border);color:var(--muted);">{{ d.tipo }}</sc-raw-td>
            <sc-raw-td style="padding:9px 8px;border-bottom:1px solid var(--border);">{{ d.fecha }}</sc-raw-td>
            <sc-raw-td style="padding:9px 8px;border-bottom:1px solid var(--border);"><span style="font-size:11px;font-weight:600;padding:2px 7px;border-radius:4px;background:{{ d.bg }};color:{{ d.fg }};">{{ d.origenTxt }}</span></sc-raw-td>
            <sc-raw-td style="padding:9px 14px;border-bottom:1px solid var(--border);text-align:right;color:var(--muted);">{{ d.tam }}</sc-raw-td>
          </sc-raw-tr>
        </sc-for>
      </sc-raw-tbody>
    </sc-raw-table>
  </section>
  </sc-if>
```

**Propuesto** (2827 caracteres)

```html
<sc-if value="{{ fT_docs }}" hint-placeholder-val="{{ false }}">
  <section style="background:var(--surface);border:1px solid var(--border);border-radius:8px;overflow:hidden;animation:fadeIn .3s ease both;">
    <sc-raw-table role="table" style="width:100%;border-collapse:collapse;">
      <sc-raw-thead><sc-raw-tr>
        <sc-raw-th style="text-align:left;padding:8px 14px;font-size:11px;font-weight:600;color:var(--muted);text-transform:uppercase;letter-spacing:.04em;background:var(--surface2);border-bottom:1px solid var(--border);">Documento</sc-raw-th>
        <sc-raw-th style="text-align:left;padding:8px;font-size:11px;font-weight:600;color:var(--muted);text-transform:uppercase;letter-spacing:.04em;background:var(--surface2);border-bottom:1px solid var(--border);">Tipo</sc-raw-th>
        <sc-raw-th style="text-align:left;padding:8px;font-size:11px;font-weight:600;color:var(--muted);text-transform:uppercase;letter-spacing:.04em;background:var(--surface2);border-bottom:1px solid var(--border);">Fecha</sc-raw-th>
        <sc-raw-th style="text-align:left;padding:8px;font-size:11px;font-weight:600;color:var(--muted);text-transform:uppercase;letter-spacing:.04em;background:var(--surface2);border-bottom:1px solid var(--border);">Origen</sc-raw-th>
        <sc-raw-th style="text-align:right;padding:8px 14px;font-size:11px;font-weight:600;color:var(--muted);text-transform:uppercase;letter-spacing:.04em;background:var(--surface2);border-bottom:1px solid var(--border);">Tamaño</sc-raw-th>
      </sc-raw-tr></sc-raw-thead>
      <sc-raw-tbody>
        <sc-for list="{{ fichaDocs }}" as="d" hint-placeholder-count="6">
          <sc-raw-tr style="background:{{ d.rowBg }};">
            <sc-raw-td style="padding:9px 14px;border-bottom:1px solid var(--border);font-weight:500;">{{ d.nombre }}</sc-raw-td>
            <sc-raw-td style="padding:9px 8px;border-bottom:1px solid var(--border);color:var(--muted);">{{ d.tipo }}</sc-raw-td>
            <sc-raw-td style="padding:9px 8px;border-bottom:1px solid var(--border);">{{ d.fecha }}</sc-raw-td>
            <sc-raw-td style="padding:9px 8px;border-bottom:1px solid var(--border);"><span style="font-size:11px;font-weight:600;padding:2px 7px;border-radius:4px;background:{{ d.bg }};color:{{ d.fg }};">{{ d.origenTxt }}</span></sc-raw-td>
            <sc-raw-td style="padding:9px 14px;border-bottom:1px solid var(--border);text-align:right;color:var(--muted);">{{ d.tam }}</sc-raw-td>
          </sc-raw-tr>
        </sc-for>
      </sc-raw-tbody>
  <sc-if value="{{ fichaVacioDocs }}" hint-placeholder-val="{{ false }}"><div style="padding:32px;text-align:center;color:var(--muted);">La plataforma no guarda los documentos del expediente de cada cliente: no hay endpoint de documentos ni de subidas.</div></sc-if>
    </sc-raw-table>
  </section>
  </sc-if>
```

**Por qué** — La pestaña de documentos se alimenta de DOCS, que el traductor deja vacío: sin un mensaje, la pestaña es una tabla con cabeceras y nada debajo. Se dice por qué está vacía.

### 3. Pestaña «Envíos» de la ficha (marcado)

**Actual** (832 caracteres)

```html
<sc-if value="{{ fT_env }}" hint-placeholder-val="{{ false }}">
  <section style="background:var(--surface);border:1px solid var(--border);border-radius:8px;overflow:hidden;animation:fadeIn .3s ease both;">
    <sc-for list="{{ fichaEnvios }}" as="e" hint-placeholder-count="5">
      <div style="display:grid;grid-template-columns:110px minmax(0,1fr) auto;gap:12px;padding:10px 16px;border-bottom:1px solid var(--border);align-items:center;">
        <span style="color:var(--muted);">{{ e.fecha }}</span><span><strong style="font-weight:500;">{{ e.tipo }}</strong> <span style="color:var(--muted);">· {{ e.periodo }}</span></span>
        <span style="font-size:11px;font-weight:600;padding:3px 8px;border-radius:4px;background:{{ e.bg }};color:{{ e.fg }};">{{ e.estado }}</span>
      </div>
    </sc-for>
  </section>
  </sc-if>
```

**Propuesto** (1077 caracteres)

```html
<sc-if value="{{ fT_env }}" hint-placeholder-val="{{ false }}">
  <section style="background:var(--surface);border:1px solid var(--border);border-radius:8px;overflow:hidden;animation:fadeIn .3s ease both;">
    <sc-for list="{{ fichaEnvios }}" as="e" hint-placeholder-count="5">
      <div style="display:grid;grid-template-columns:110px minmax(0,1fr) auto;gap:12px;padding:10px 16px;border-bottom:1px solid var(--border);align-items:center;">
        <span style="color:var(--muted);">{{ e.fecha }}</span><span><strong style="font-weight:500;">{{ e.tipo }}</strong> <span style="color:var(--muted);">· {{ e.periodo }}</span></span>
        <span style="font-size:11px;font-weight:600;padding:3px 8px;border-radius:4px;background:{{ e.bg }};color:{{ e.fg }};">{{ e.estado }}</span>
      </div>
  <sc-if value="{{ fichaVacioEnv }}" hint-placeholder-val="{{ false }}"><div style="padding:32px;text-align:center;color:var(--muted);">La plataforma todavía no envía informes a los clientes: no hay endpoint ni registro de envíos.</div></sc-if>
    </sc-for>
  </section>
  </sc-if>
```

**Por qué** — La pestaña de envíos se alimenta de s.envios, que el traductor deja vacío (no hay registro de envíos). Sin el mensaje, la pestaña es una caja en blanco.

### 4. Pestaña «Cuentas anuales» de la ficha (marcado)

**Actual** (1049 caracteres)

```html
<sc-if value="{{ fT_ca }}" hint-placeholder-val="{{ false }}">
  <section style="background:var(--surface);border:1px solid var(--border);border-radius:8px;overflow:hidden;animation:fadeIn .3s ease both;">
    <sc-for list="{{ fichaCA }}" as="c" hint-placeholder-count="3">
      <div style="display:grid;grid-template-columns:90px minmax(0,1fr) auto;gap:12px;padding:12px 16px;border-bottom:1px solid var(--border);align-items:center;">
        <strong>Ejercicio {{ c.ej }}</strong><span style="color:var(--muted);">{{ c.detalle }}</span>
        <span style="font-size:11px;font-weight:600;padding:3px 8px;border-radius:4px;background:{{ c.bg }};color:{{ c.fg }};">{{ c.estado }}</span>
      </div>
    </sc-for>
    <div style="padding:12px 16px;"><button sc-camel-on-click="{{ fichaGoCA }}" style="height:34px;padding:0 14px;border:none;border-radius:6px;background:var(--btn);color:#fff;font-size:13px;font-weight:600;cursor:pointer;" style-hover="background:var(--btn-hover);">Abrir cuentas anuales 2025</button></div>
  </section>
  </sc-if>
```

**Propuesto** (1338 caracteres)

```html
<sc-if value="{{ fT_ca }}" hint-placeholder-val="{{ false }}">
  <section style="background:var(--surface);border:1px solid var(--border);border-radius:8px;overflow:hidden;animation:fadeIn .3s ease both;">
    <sc-for list="{{ fichaCA }}" as="c" hint-placeholder-count="3">
      <div style="display:grid;grid-template-columns:90px minmax(0,1fr) auto;gap:12px;padding:12px 16px;border-bottom:1px solid var(--border);align-items:center;">
        <strong>Ejercicio {{ c.ej }}</strong><span style="color:var(--muted);">{{ c.detalle }}</span>
        <span style="font-size:11px;font-weight:600;padding:3px 8px;border-radius:4px;background:{{ c.bg }};color:{{ c.fg }};">{{ c.estado }}</span>
      </div>
    </sc-for>
      <sc-if value="{{ fichaVacioCA }}" hint-placeholder-val="{{ false }}"><div style="padding:32px 16px;text-align:center;color:var(--muted);">La plataforma no guarda el depósito de las cuentas anuales: no hay registro de presentaciones en el Registro Mercantil.</div></sc-if>
    <div style="padding:12px 16px;"><button sc-camel-on-click="{{ fichaGoCA }}" style="height:34px;padding:0 14px;border:none;border-radius:6px;background:var(--btn);color:#fff;font-size:13px;font-weight:600;cursor:pointer;" style-hover="background:var(--btn-hover);">Abrir cuentas anuales {{ ejercicio }}</button></div>
  </section>
  </sc-if>
```

**Por qué** — La lista de depósitos era un histórico escrito a mano (Registro Mercantil de La Rioja con fechas fijas) y el botón abría siempre las cuentas del 2025. Ahora no hay filas, se explica por qué y el botón abre el ejercicio que se está viendo.

### 5. rvAj() — las cinco pestañas de Ajustes

**Actual** (4628 caracteres)

```html
  rvAj(){
    const s = this.state;
    const users = s.ajUsers || [
      {id:1, nombre:'Javier Roldán', email:'javier.roldan@abga.es', rol:'Socio', clientes:22, estado:'Activo', ult:'Hoy, 10:41'},
      {id:2, nombre:'Laura Sáez', email:'laura.saez@abga.es', rol:'Asesora', clientes:18, estado:'Activo', ult:'Hoy, 09:58'},
      {id:3, nombre:'Iván Morales', email:'ivan.morales@abga.es', rol:'Asesor', clientes:15, estado:'Activo', ult:'Ayer, 18:20'},
      {id:4, nombre:'María Dolores Ibáñez', email:'mdolores.ibanez@abga.es', rol:'Asesora', clientes:9, estado:'Activo', ult:'22/09/2026'}
    ];
    const tabs = [['despacho','Despacho'],['erp','Conexión con el ERP'],['usuarios','Usuarios'],['ia','Automatización IA'],['notif','Notificaciones']];
    const nw = s.ajNew;
    const tog = (grp, k) => () => this.setState(x => ({[grp]:{...x[grp], [k]:!x[grp][k]}, ajSaved:false}));
    const sw = (grp, k, l, d) => { const on = s[grp][k]; return {l, d, on, onClick:tog(grp, k), bg: on ? 'var(--accent)' : 'var(--border)', x: on ? '18px' : '2px', st: on ? 'Activado' : 'Desactivado'}; };
    const erpT = s.ajErp === 'ok' ? 'ok' : s.ajErp === 'test' ? 'accent' : 'err';
    return {
      ajTabs:tabs.map(([k, l]) => ({l, onClick:() => this.setState({ajTab:k}), bg: s.ajTab === k ? 'var(--accent-soft)' : 'transparent', fg: s.ajTab === k ? 'var(--accent-strong)' : 'var(--text)', fw: s.ajTab === k ? 600 : 400})),
      aT:{despacho:s.ajTab === 'despacho', erp:s.ajTab === 'erp', usuarios:s.ajTab === 'usuarios', ia:s.ajTab === 'ia', notif:s.ajTab === 'notif'},
      ajSaved:s.ajSaved, ajSave:() => { this.setState({ajSaved:true}); clearTimeout(this._ajT); this._ajT = setTimeout(() => this.setState({ajSaved:false}), 2500); },
      ajErpL:{ok:'Conectado', test:'Comprobando conexión…', err:'Sin conexión'}[s.ajErp], ajErpFg:T(erpT).fg, ajErpBg:T(erpT).bg, ajErpTesting:s.ajErp === 'test', ajErpAt:s.ajErpAt,
      ajTest:() => { this.setState({ajErp:'test'}); setTimeout(() => { const d = new Date(); this.setState({ajErp:'ok', ajErpAt:'27/09/2026 ' + String(d.getHours()).padStart(2, '0') + ':' + String(d.getMinutes()).padStart(2, '0')}); }, 1600); },
      ajSync:[['Diario de asientos','Cada 15 min','1.284 asientos hoy'],['Extractos bancarios','Cada hora','9 cuentas'],['Facturas emitidas y recibidas','Cada 15 min','312 este mes'],['Plan de cuentas','Diario, 02:00','PGC PYMES 2007']].map(([l, f, n]) => ({l, f, n})),
      ajUsers:users.map(u => ({...u, ini:u.nombre.split(' ').map(p => p[0]).slice(0, 2).join('')})),
      ajHasNew:!!nw, ajNoNew:!nw, ajNewD:nw || {nombre:'', email:'', rol:'Asesor'},
      ajOpenNew:() => this.setState({ajNew:{nombre:'', email:'', rol:'Asesor'}, ajTemp:null}), ajCancelNew:() => this.setState({ajNew:null}),
      ajSetN:e => this.setState({ajNew:{...s.ajNew, nombre:e.target.value}}), ajSetE:e => this.setState({ajNew:{...s.ajNew, email:e.target.value}}), ajSetR:e => this.setState({ajNew:{...s.ajNew, rol:e.target.value}}),
      ajNewOk:!!nw && nw.nombre.trim().length > 2 && /.+@.+\..+/.test(nw.email), ajNewBad:!(!!nw && nw.nombre.trim().length > 2 && /.+@.+\..+/.test(nw.email)),
      ajCreate:() => { const t = 'ABGA-' + Math.random().toString(36).slice(2, 6).toUpperCase() + '-' + Math.floor(1000 + Math.random() * 9000); this.setState({ajUsers:[...users, {id:Date.now(), nombre:nw.nombre.trim(), email:nw.email.trim(), rol:nw.rol, clientes:0, estado:'Pendiente de acceso', ult:'—'}], ajNew:null, ajTemp:{email:nw.email.trim(), pass:t}}); },
      ajHasTemp:!!s.ajTemp, ajTempD:s.ajTemp || {email:'', pass:''}, ajCloseTemp:() => this.setState({ajTemp:null}),
      ajUmbral:s.ajUmbral, ajUmbralL:s.ajUmbral + ' %', ajSetUmbral:e => this.setState({ajUmbral:+e.target.value, ajSaved:false}),
      ajAutoSw:[sw('ajAuto','conc','Casar partidas de conciliación','Aplica las propuestas de la IA por encima del umbral sin revisión'), sw('ajAuto','dup','Retener facturas duplicadas','Bloquea el pago hasta que un asesor lo confirme'), sw('ajAuto','memo','Redactar borradores de memoria','Genera la memoria a partir del cierre y la del año anterior'), sw('ajAuto','env','Enviar informes sin revisión','Los informes programados salen sin aprobación del asesor')],
      ajNotifSw:[sw('ajNotif','dup','Duplicados detectados','Aviso inmediato en la campana'), sw('ajNotif','env','Envíos con error','Aviso inmediato y correo'), sw('ajNotif','venc','Vencimientos fiscales','7 y 2 días antes de cada plazo'), sw('ajNotif','erp','Incidencias del ERP','Caídas y errores de sincronización'), sw('ajNotif','resumen','Resumen diario por correo','Cada día laborable a las 08:00')]
    };
  }
```

**Propuesto** (3651 caracteres)

```html
  rvAj(){
    const s = this.state;
    // Los usuarios salen de la plataforma (/api/interno/usuarios). El hub ya no lleva cuatro usuarios
    // de ejemplo a los que caer: si la consulta falla, la tabla sale vacía y lo dice el traductor.
    const users = s.ajUsers || [];
    const tabs = [['despacho','Tu cuenta'],['erp','Conexión con el ERP'],['usuarios','Usuarios'],['ia','Umbrales del análisis'],['notif','Notificaciones']];
    const nw = s.ajNew;
    const erpT = s.ajErp === 'ok' ? 'ok' : s.ajErp === 'test' ? 'accent' : 'err';
    return {
      ajTabs:tabs.map(([k, l]) => ({l, onClick:() => this.setState({ajTab:k}), bg: s.ajTab === k ? 'var(--accent-soft)' : 'transparent', fg: s.ajTab === k ? 'var(--accent-strong)' : 'var(--text)', fw: s.ajTab === k ? 600 : 400})),
      aT:{despacho:s.ajTab === 'despacho', erp:s.ajTab === 'erp', usuarios:s.ajTab === 'usuarios', ia:s.ajTab === 'ia', notif:s.ajTab === 'notif'},
      // Lo único que la plataforma sabe del despacho es la cuenta con la que estás dentro.
      ajDespacho:(s.ajDespacho || []).map(d => ({k:d.k, v:String(d.v)})),
      // El estado del ERP y la tabla de sincronización salen de la caché real que trae datos.js.
      ajErpL:{ok:'Conectado', test:'Comprobando conexión…', err:'Sin conexión'}[s.ajErp], ajErpFg:T(erpT).fg, ajErpBg:T(erpT).bg, ajErpTesting:s.ajErp === 'test', ajErpAt:s.ajErpAt,
      // «Probar conexión» vuelve a leer el estado real de la caché: no finge un retardo de 1,6 s.
      ajTest:() => { this.setState({ajErp:'test'}); ABGA.cargarPantalla('ajustes', true); },
      // La tabla «de sincronización» del ERP enseña lo que hay leído (marcado la pide como `ajSync`).
      ajSync:(s.ajCache || []).map(y => ({l:y.l, f:y.f, n:y.n})),
      ajUmbrales:(s.ajUmbrales || []).map(w => ({l:w.l, d:w.d, v:w.v, o:w.o})), ajUmbralCliente:s.ajUmbralCliente || '',
      ajUsers:users.map(u => ({...u, ini:String(u.nombre || u.email || '').split(' ').map(p => p[0]).slice(0,2).join('')})),
      ajHasNew:!!nw, ajNoNew:!nw, ajNewD:nw || {nombre:'', email:'', rol:'Cliente'},
      ajOpenNew:() => this.setState({ajNew:{nombre:'', email:'', rol:'Cliente'}, ajTemp:null}), ajCancelNew:() => this.setState({ajNew:null}),
      ajSetN:e => this.setState({ajNew:{...s.ajNew, nombre:e.target.value}}), ajSetE:e => this.setState({ajNew:{...s.ajNew, email:e.target.value}}), ajSetR:e => this.setState({ajNew:{...s.ajNew, rol:e.target.value}}),
      ajNewOk:!!nw && nw.nombre.trim().length > 2 && /.+@.+\..+/.test(nw.email), ajNewBad:!(!!nw && nw.nombre.trim().length > 2 && /.+@.+\..+/.test(nw.email)),
      // Crear el usuario es una llamada de verdad a la plataforma: la contraseña la genera ella y
      // sólo se enseña una vez. Antes se inventaba aquí y no servía para entrar en ninguna parte.
      ajCreate:async () => {
        const correo = nw.email.trim(), nombre = nw.nombre.trim();
        try {
          const r = await ABGA.pedir('/api/interno/usuarios', {cuerpo:{email:correo, nombre, rol:nw.rol === 'Equipo de ABGA' ? 'interno' : 'cliente'}});
          const lista = await ABGA.api.interno.usuarios();
          this.setState({ajUsers:lista.usuarios, ajNew:null, ajTemp:{email:r.email || correo, pass:r.password || '',
            aviso:r.password ? (r.aviso || 'Contraseña generada; no se vuelve a mostrar.') : 'El usuario ya existía: se ha actualizado sin cambiar su contraseña.'}});
        } catch (fallo) { ABGA.aviso('No se ha podido crear el usuario: ' + (fallo.message || fallo), 'error'); }
      },
      ajHasTemp:!!s.ajTemp, ajTempD:s.ajTemp || {email:'', pass:'', aviso:''}, ajCloseTemp:() => this.setState({ajTemp:null})
    };
  }
```

**Por qué** — De los tres bloques inventados de Ajustes (usuarios, sincronización del ERP y umbrales de la IA) sólo quedan los que la plataforma puede alimentar: los usuarios reales del portal, el estado del ERP y los ejercicios leídos de la caché, y los umbrales que de verdad usa el análisis. Se van los cuatro usuarios de ejemplo, la tabla de sincronización con volúmenes a ojo, el umbral de confianza de la IA (no existe en ninguna parte), los once interruptores que no cambiaban nada, el «Probar conexión» que fingía un retardo y el «✓ Cambios guardados» de un guardado que no guardaba. Crear un usuario pasa a ser una llamada real: la contraseña la genera la plataforma y se enseña una vez.

### 6. Ajustes › «Datos del despacho» (marcado)

**Actual** (3592 caracteres)

```html
<sc-if value="{{ aT.despacho }}" hint-placeholder-val="{{ true }}">
                <div style="display:flex;flex-direction:column;gap:14px;animation:fadeIn .25s ease both;">
                  <h2 style="margin:0;font-size:15px;font-weight:600;">Datos del despacho</h2>
                  <div style="display:grid;grid-template-columns:repeat(auto-fit,minmax(220px,1fr));gap:12px;">
                    <div><label for="aj-rs" style="display:block;font-size:12px;color:var(--muted);margin-bottom:4px;">Razón social</label><input id="aj-rs" type="text" value="ABGA Consultores, S.L." style="width:100%;box-sizing:border-box;height:38px;padding:0 10px;border:1px solid var(--border);border-radius:6px;background:var(--surface);color:var(--text);font-size:13px;" style-focus="border-color:var(--accent);outline:none;"></div>
                    <div><label for="aj-nif" style="display:block;font-size:12px;color:var(--muted);margin-bottom:4px;">NIF</label><input id="aj-nif" type="text" value="B47210386" style="width:100%;box-sizing:border-box;height:38px;padding:0 10px;border:1px solid var(--border);border-radius:6px;background:var(--surface);color:var(--text);font-size:13px;font-family:'IBM Plex Mono',monospace;" style-focus="border-color:var(--accent);outline:none;"></div>
                    <div><label for="aj-dir" style="display:block;font-size:12px;color:var(--muted);margin-bottom:4px;">Dirección</label><input id="aj-dir" type="text" value="C/ Santiago 14, 2.º · 47001 Valladolid" style="width:100%;box-sizing:border-box;height:38px;padding:0 10px;border:1px solid var(--border);border-radius:6px;background:var(--surface);color:var(--text);font-size:13px;" style-focus="border-color:var(--accent);outline:none;"></div>
                    <div><label for="aj-mail" style="display:block;font-size:12px;color:var(--muted);margin-bottom:4px;">Correo de envío a clientes</label><input id="aj-mail" type="email" value="informes@abga.es" style="width:100%;box-sizing:border-box;height:38px;padding:0 10px;border:1px solid var(--border);border-radius:6px;background:var(--surface);color:var(--text);font-size:13px;" style-focus="border-color:var(--accent);outline:none;"></div>
                    <div><label for="aj-ej" style="display:block;font-size:12px;color:var(--muted);margin-bottom:4px;">Ejercicio por defecto</label><sc-raw-select id="aj-ej" style="width:100%;height:38px;padding:0 10px;border:1px solid var(--border);border-radius:6px;background:var(--surface);color:var(--text);font-size:13px;"><option>2026</option><option>2025</option></sc-raw-select></div>
                    <div><label for="aj-pgc" style="display:block;font-size:12px;color:var(--muted);margin-bottom:4px;">Plan contable</label><sc-raw-select id="aj-pgc" style="width:100%;height:38px;padding:0 10px;border:1px solid var(--border);border-radius:6px;background:var(--surface);color:var(--text);font-size:13px;"><option>PGC PYMES 2007</option><option>PGC 2007 (normal)</option></sc-raw-select></div>
                  </div>
                  <div><label for="aj-pie" style="display:block;font-size:12px;color:var(--muted);margin-bottom:4px;">Pie de los informes</label><textarea id="aj-pie" rows="2" style="width:100%;box-sizing:border-box;padding:8px 10px;border:1px solid var(--border);border-radius:6px;background:var(--surface);color:var(--text);font-size:13px;resize:vertical;" style-focus="border-color:var(--accent);outline:none;">ABGA Consultores · Informe elaborado a partir de la contabilidad del cliente. Documento confidencial.</textarea></div>
                </div>
              </sc-if>
```

**Propuesto** (1138 caracteres)

```html
<sc-if value="{{ aT.despacho }}" hint-placeholder-val="{{ true }}">
                <div style="display:flex;flex-direction:column;gap:14px;animation:fadeIn .25s ease both;">
                  <h2 style="margin:0;font-size:15px;font-weight:600;">Tu cuenta</h2>
                <div style="display:grid;grid-template-columns:repeat(auto-fit,minmax(220px,1fr));border:1px solid var(--border);border-radius:6px;overflow:hidden;">
                  <sc-for list="{{ ajDespacho }}" as="d" hint-placeholder-count="6"><div style="padding:10px 14px;border-bottom:1px solid var(--border);"><div style="font-size:11px;color:var(--muted);">{{ d.k }}</div><div style="font-weight:500;margin-top:2px;">{{ d.v }}</div></div></sc-for>
                </div>
                <div style="font-size:11.5px;color:var(--muted);">La plataforma no guarda los datos fiscales del despacho, ni el correo de envío a clientes, ni el ejercicio o el plan contable por defecto, ni el pie de los informes: cada informe sale con los datos del cliente y del ejercicio que elijas. No hay nada que editar en esta pestaña.</div>
                </div>
              </sc-if>
```

**Por qué** — Los seis campos de «Datos del despacho» venían con valores fijos en el propio HTML (razón social, NIF, dirección, correo de envío, ejercicio por defecto, plan contable y pie de los informes) y no había ningún endpoint detrás. Se cambian por los datos reales de la sesión (cuenta, correo, rol, estado, alta y clientes asignados) y se dice lo que la plataforma no guarda, en lugar de enseñar un NIF y una dirección que nadie ha comprobado.

### 7. Ajustes › «Automatización IA» (marcado)

**Actual** (2101 caracteres)

```html
<sc-if value="{{ aT.ia }}" hint-placeholder-val="{{ false }}">
                <div style="display:flex;flex-direction:column;gap:14px;animation:fadeIn .25s ease both;">
                  <h2 style="margin:0;font-size:15px;font-weight:600;">Automatización IA</h2>
                  <div style="padding:12px 14px;border:1px solid var(--border);border-radius:6px;background:var(--surface2);">
                    <div style="display:flex;justify-content:space-between;align-items:baseline;gap:8px;"><label for="aj-um" style="font-size:13px;font-weight:600;">Umbral de confianza para aplicar sin revisión</label><strong style="font-size:18px;color:var(--ai);">{{ ajUmbralL }}</strong></div>
                    <input id="aj-um" type="range" min="70" max="99" step="1" value="{{ ajUmbral }}" sc-camel-on-change="{{ ajSetUmbral }}" style="width:100%;margin-top:8px;accent-color:var(--ai);height:24px;">
                    <div style="font-size:11.5px;color:var(--muted);">Las propuestas por debajo de este valor quedan como tareas pendientes para el asesor.</div>
                  </div>
                  <sc-for list="{{ ajAutoSw }}" as="w" hint-placeholder-count="4">
                    <div style="display:flex;justify-content:space-between;align-items:center;gap:12px;padding:10px 0;border-bottom:1px solid var(--border);">
                      <div><div style="font-size:13px;font-weight:500;">{{ w.l }}</div><div style="font-size:11.5px;color:var(--muted);">{{ w.d }}</div></div>
                      <button role="switch" aria-checked="{{ w.on }}" aria-label="{{ w.l }}" sc-camel-on-click="{{ w.onClick }}" style="position:relative;width:40px;height:24px;border:none;border-radius:12px;background:{{ w.bg }};cursor:pointer;flex-shrink:0;transition:background .2s ease;padding:0;"><span style="position:absolute;top:2px;left:{{ w.x }};width:20px;height:20px;border-radius:50%;background:#fff;box-shadow:0 1px 3px rgba(0,0,0,.25);transition:left .2s cubic-bezier(.2,.8,.2,1);"></span></button>
                    </div>
                  </sc-for>
                </div>
              </sc-if>
```

**Propuesto** (2387 caracteres)

```html
<sc-if value="{{ aT.ia }}" hint-placeholder-val="{{ false }}">
                <div style="display:flex;flex-direction:column;gap:14px;animation:fadeIn .25s ease both;">
                  <h2 style="margin:0 0 4px;font-size:15px;font-weight:600;">Umbrales del análisis</h2>
                  <div style="font-size:11.5px;color:var(--muted);margin-bottom:6px;">Los que la plataforma usa para decidir cuándo salta cada comprobación, del cliente en curso ({{ ajUmbralCliente }}). Se ajustan por cliente.</div>
                  <sc-raw-table role="table" style="width:100%;border-collapse:collapse;font-size:13px;">
                    <sc-raw-thead><sc-raw-tr>
                      <sc-raw-th style="text-align:left;padding:8px 10px;font-size:11px;font-weight:600;color:var(--muted);border-bottom:1px solid var(--border);">Comprobación</sc-raw-th>
                      <sc-raw-th style="text-align:right;padding:8px 10px;font-size:11px;font-weight:600;color:var(--muted);border-bottom:1px solid var(--border);">Umbral</sc-raw-th>
                      <sc-raw-th style="text-align:left;padding:8px 10px;font-size:11px;font-weight:600;color:var(--muted);border-bottom:1px solid var(--border);">Origen</sc-raw-th>
                    </sc-raw-tr></sc-raw-thead>
                    <sc-raw-tbody><sc-for list="{{ ajUmbrales }}" as="w" hint-placeholder-count="12"><sc-raw-tr>
                      <sc-raw-td style="padding:9px 10px;border-bottom:1px solid var(--border);"><div style="font-weight:500;">{{ w.l }}</div><div style="font-size:11.5px;color:var(--muted);">{{ w.d }}</div></sc-raw-td>
                      <sc-raw-td style="padding:9px 10px;border-bottom:1px solid var(--border);text-align:right;white-space:nowrap;"><strong>{{ w.v }}</strong></sc-raw-td>
                      <sc-raw-td style="padding:9px 10px;border-bottom:1px solid var(--border);color:var(--muted);">{{ w.o }}</sc-raw-td>
                    </sc-raw-tr></sc-for></sc-raw-tbody>
                  </sc-raw-table>
                  <div style="font-size:11.5px;color:var(--muted);margin-top:8px;">La plataforma no guarda ninguna preferencia de automatización de la IA (casar partidas, retener duplicados, redactar memorias o enviar informes sin revisión): esos interruptores no tenían nada detrás. Estos umbrales sí, y se ajustan por cliente desde aquí.</div>
                </div>
                </sc-if>
```

**Por qué** — El bloque «Automatización IA» era lo más inventado de la pantalla: un umbral de confianza del 90 % que no existe, cuatro interruptores que no cambiaban nada y un «Guardar cambios» que sólo pintaba «✓ Cambios guardados». Se cambia por los doce umbrales reales del análisis del cliente en curso (/api/interno/umbrales): valor con su unidad, para qué sirve y si está por defecto.

### 8. Ajustes › «Notificaciones» (marcado)

**Actual** (1285 caracteres)

```html
<sc-if value="{{ aT.notif }}" hint-placeholder-val="{{ false }}">
                <div style="display:flex;flex-direction:column;gap:6px;animation:fadeIn .25s ease both;">
                  <h2 style="margin:0 0 8px;font-size:15px;font-weight:600;">Notificaciones</h2>
                  <sc-for list="{{ ajNotifSw }}" as="w" hint-placeholder-count="5">
                    <div style="display:flex;justify-content:space-between;align-items:center;gap:12px;padding:10px 0;border-bottom:1px solid var(--border);">
                      <div><div style="font-size:13px;font-weight:500;">{{ w.l }}</div><div style="font-size:11.5px;color:var(--muted);">{{ w.d }}</div></div>
                      <button role="switch" aria-checked="{{ w.on }}" aria-label="{{ w.l }}" sc-camel-on-click="{{ w.onClick }}" style="position:relative;width:40px;height:24px;border:none;border-radius:12px;background:{{ w.bg }};cursor:pointer;flex-shrink:0;transition:background .2s ease;padding:0;"><span style="position:absolute;top:2px;left:{{ w.x }};width:20px;height:20px;border-radius:50%;background:#fff;box-shadow:0 1px 3px rgba(0,0,0,.25);transition:left .2s cubic-bezier(.2,.8,.2,1);"></span></button>
                    </div>
                  </sc-for>
                </div>
              </sc-if>
```

**Propuesto** (792 caracteres)

```html
<sc-if value="{{ aT.notif }}" hint-placeholder-val="{{ false }}">
                <div style="display:flex;flex-direction:column;gap:6px;animation:fadeIn .25s ease both;">
                  <h2 style="margin:0 0 8px;font-size:15px;font-weight:600;">Notificaciones</h2>
                  <div style="padding:14px;border:1px dashed var(--border);border-radius:6px;color:var(--muted);font-size:13px;">La plataforma no guarda preferencias de notificación por usuario ni por tipo de aviso. Los avisos que genera (errores del ERP, informes parciales, módulos sin datos) se ven en la campana y en Inicio, y quedan registrados para el panel interno. No hay nada que configurar aquí todavía, así que no se pintan interruptores que no cambien nada.</div>
                </div>
                </sc-if>
```

**Por qué** — Los cinco interruptores de notificaciones (duplicados, envíos con error, vencimientos, incidencias del ERP y resumen diario por correo) no tenían nada detrás: ni preferencias por usuario ni envío de correos desde la plataforma. Se sustituyen por lo que sí hace (avisos en la campana y registro interno) en lugar de dejar interruptores que no cambian nada.

### 9. Ajustes › cabeceras de la tabla del ERP (marcado)

**Actual** (496 caracteres)

```html
<sc-raw-th style="text-align:left;padding:8px 10px;font-size:11px;font-weight:600;color:var(--muted);border-bottom:1px solid var(--border);">Datos sincronizados</sc-raw-th><sc-raw-th style="text-align:left;padding:8px 10px;font-size:11px;font-weight:600;color:var(--muted);border-bottom:1px solid var(--border);">Frecuencia</sc-raw-th><sc-raw-th style="text-align:right;padding:8px 10px;font-size:11px;font-weight:600;color:var(--muted);border-bottom:1px solid var(--border);">Volumen</sc-raw-th>
```

**Propuesto** (510 caracteres)

```html
<sc-raw-th style="text-align:left;padding:8px 10px;font-size:11px;font-weight:600;color:var(--muted);border-bottom:1px solid var(--border);">Cliente y ejercicio</sc-raw-th><sc-raw-th style="text-align:left;padding:8px 10px;font-size:11px;font-weight:600;color:var(--muted);border-bottom:1px solid var(--border);">Asientos y líneas</sc-raw-th><sc-raw-th style="text-align:right;padding:8px 10px;font-size:11px;font-weight:600;color:var(--muted);border-bottom:1px solid var(--border);">Última lectura</sc-raw-th>
```

**Por qué** — La tabla ya no lista sincronizaciones con su frecuencia y su volumen (inventados: «Cada 15 min», «1.284 asientos hoy»), sino los ejercicios que hay leídos del ERP en la caché, con sus asientos, sus líneas y cuándo se leyeron. Los encabezados tienen que decir eso.

### 10. Ajustes › cabecera «Último acceso» de la tabla de usuarios (marcado)

**Actual** (167 caracteres)

```html
<sc-raw-th style="text-align:right;padding:8px 10px;font-size:11px;font-weight:600;color:var(--muted);border-bottom:1px solid var(--border);">Último acceso</sc-raw-th>
```

**Propuesto** (171 caracteres)

```html
<sc-raw-th style="text-align:right;padding:8px 10px;font-size:11px;font-weight:600;color:var(--muted);border-bottom:1px solid var(--border);">Alta de la cuenta</sc-raw-th>
```

**Por qué** — /api/interno/usuarios devuelve cuándo se creó la cuenta y si está activa, pero no el último acceso: la plataforma no lo guarda. La columna pasa a decir lo que de verdad se pinta (y en el traductor queda declarado con ctx.sinDatos).

### 11. Ajustes › desplegable de rol al crear un usuario (marcado)

**Actual** (332 caracteres)

```html
<sc-raw-select id="aj-nr" value="{{ ajNewD.rol }}" sc-camel-on-change="{{ ajSetR }}" style="width:100%;height:38px;padding:0 10px;border:1px solid var(--border);border-radius:6px;background:var(--surface);color:var(--text);font-size:13px;"><option>Asesor</option><option>Socio</option><option>Administración</option></sc-raw-select>
```

**Propuesto** (311 caracteres)

```html
<sc-raw-select id="aj-nr" value="{{ ajNewD.rol }}" sc-camel-on-change="{{ ajSetR }}" style="width:100%;height:38px;padding:0 10px;border:1px solid var(--border);border-radius:6px;background:var(--surface);color:var(--text);font-size:13px;"><option>Cliente</option><option>Equipo de ABGA</option></sc-raw-select>
```

**Por qué** — La plataforma sólo entiende dos roles: `cliente` (entra en su empresa) e `interno` (entra en toda la cartera). «Asesor» y «Socio» no existen como rol, así que crear un usuario «Asesor» habría creado una cuenta de cliente. El desplegable ofrece los dos roles reales.

### 12. Ajustes › aviso de contraseña temporal (marcado)

**Actual** (257 caracteres)

```html
<div style="font-size:12px;margin-top:3px;">Contraseña temporal: <strong style="font-family:'IBM Plex Mono',monospace;font-size:14px;letter-spacing:.04em;">{{ ajTempD.pass }}</strong> · se pedirá cambiarla en el primer acceso. No se volverá a mostrar.</div>
```

**Propuesto** (406 caracteres)

```html
<div style="font-size:12px;margin-top:3px;"><sc-if value="{{ ajTempD.pass }}" hint-placeholder-val="{{ true }}">Contraseña generada por la plataforma: <strong style="font-family:'IBM Plex Mono',monospace;font-size:14px;letter-spacing:.04em;">{{ ajTempD.pass }}</strong> · no se volverá a mostrar.</sc-if><sc-if value="{{ ajTempD.aviso }}" hint-placeholder-val="{{ true }}">{{ ajTempD.aviso }}</sc-if></div>
```

**Por qué** — La contraseña ya no se inventa en el navegador (era un Math.random que no servía para entrar): la genera la plataforma y viaja en la respuesta del alta, junto con su propio aviso. Y no se pide cambiarla en el primer acceso, porque la plataforma no lo hace.

### 13. Ajustes › botón «Guardar cambios» (marcado)

**Actual** (560 caracteres)

```html
            <div style="display:flex;align-items:center;gap:10px;">
              <sc-if value="{{ ajSaved }}" hint-placeholder-val="{{ false }}"><span style="font-size:12px;font-weight:600;color:var(--ok);animation:fadeIn .2s ease both;">✓ Cambios guardados</span></sc-if>
              <button sc-camel-on-click="{{ ajSave }}" style="height:36px;padding:0 14px;border:none;border-radius:6px;background:var(--btn);color:#fff;font-size:13px;font-weight:600;cursor:pointer;" style-hover="background:var(--btn-hover);">Guardar cambios</button>
            </div>
```

**Propuesto** (233 caracteres)

```html
            <div style="display:flex;align-items:center;gap:10px;">
              <span style="font-size:12px;color:var(--muted);">Lo que se ve aquí es lo que hay en la plataforma: no hay ajustes que guardar</span>
            </div>
```

**Por qué** — «Guardar cambios» sólo pintaba «✓ Cambios guardados» durante 2,5 s: no guardaba nada, porque no hay ningún endpoint de ajustes del despacho. Un botón que promete guardar y no guarda es peor que no tenerlo: se cambia por lo que de verdad pasa.

### 14. Ajustes › estado inicial en el constructor (estado)

**Actual** (247 caracteres)

```html
      ajTab:'despacho', ajErp:'ok', ajErpAt:'23/09/2026 10:40', ajUsers:null, ajNew:null, ajTemp:null, ajUmbral:90, ajAuto:{conc:true, dup:true, env:false, memo:true}, ajNotif:{dup:true, env:true, venc:true, erp:true, resumen:false}, ajSaved:false
```

**Propuesto** (162 caracteres)

```html
      ajTab:'despacho', ajErp:'test', ajErpAt:'—', ajUsers:null, ajNew:null, ajTemp:null,
      ajCache:null, ajUmbrales:null, ajUmbralCliente:'', ajDespacho:null
```

**Por qué** — El estado inicial de Ajustes venía con datos inventados: el ERP «conectado» desde el 23/09/2026 a las 10:40 (hasta que se pulsaba «Probar conexión», que fingía comprobarlo) y un umbral de IA del 90 %. Ahora arranca en «comprobando» y sin valores, y lo que se ve lo pone el traductor con lo que responde la plataforma (caché, umbrales y sesión).

### 15. Etiquetas <script> de los dos traductores

**Actual** (43 caracteres)

```html
<script src="pantallas/envios.js"></script>
```

**Propuesto** (134 caracteres)

```html
<script src="pantallas/envios.js"></script>
<script src="pantallas/clientes.js"></script>
<script src="pantallas/ajustes.js"></script>
```

**Por qué** — Sin estas dos etiquetas los traductores no se registran y las pantallas de Clientes y Ajustes se quedan con los datos de ejemplo del hub. Van después de datos.js, como inicio.js y envios.js.

## Cómo se ha comprobado

- `node --check frontend/hub/pantallas/clientes.js` y `.../ajustes.js`: sin errores.
- Cada parche se aplica sobre una copia de `index.html` (los 15, en orden) y se vuelve a extraer el
  `<script type="text/x-dc">` completo para pasarlo por `node --check`: sigue siendo JavaScript válido.
- Recuento de etiquetas (`sc-if`, `sc-for`, `sc-raw-table`, `sc-raw-tbody`, `sc-raw-thead`) del fichero
  entero antes y después: cuadran (ver `index.html` parcheado, ninguna etiqueta queda sin cerrar).

## Notas

- **Privacidad**: `GET /api/empresas` devuelve `pin_hash` en cada empresa. La lista que se deja en el hub
  se construye campo a campo, así que el PIN no llega ni a la pantalla ni al estado de la aplicación.
- **La cartera tarda**: `/api/interno/cartera` analiza las 50 comprobaciones de cada cliente con el
  ejercicio leído (31 s con los 4 clientes en caché de 2025). Es una llamada del panel interno y va
  detrás del aviso «Cargando datos de la plataforma…». Si algún día molesta, se puede servir en segundo
  plano y refrescar la tabla después.
- **`CLIENTES` se reconstruye entero** en cada carga de la pantalla (391 filas para el usuario interno).
  Es lo que permite que el semáforo y el NIF sean reales, y de paso garantiza que `pin_hash` no entre.
- **Dos campos que otras pantallas leen de `CLIENTES`**: `factor:1` («no escalar», para que el informe
  financiero no multiplique por 0 —ver el parche 1 de `informe.md`—) y `nif`, que ahora sí lleva el NIF
  real recuperado de las notas (antes iba vacío y la cabecera de Cuentas anuales y la de Impuestos lo
  daban por perdido).
- **Lo que sigue inventado y no es de estas dos pantallas**: los otros traductores del hub se
  encargan de sus propias listas de ejemplo (`CUENTAS` la rellena `conciliacion.js`, `VENC` la rellena
  `impuestos.js`, `DUPS` la rellena `duplicados.js`, `DOCS` y `ENVIOS` las vacía este traductor). Lo
  que queda del hub original sin traductor es lo que ninguna pantalla reclama todavía.
- **La ficha abre con la primera empresa de la lista** cuando no hay ninguna seleccionada, y si el cliente
  de la ficha desaparece (o la lista viene vacía) el traductor devuelve el hub a la lista de clientes:
  antes, con `CLIENTES` vacío, la pantalla se rompía al pintar la ficha.
- El ajuste de los umbrales por cliente **ya está en la API** (`POST /api/interno/umbrales`), y la capa de
  datos ya lo tiene (`api.interno.ajustarUmbral`): la pestaña los enseña en modo lectura. Editar un umbral
  desde ahí es el siguiente paso natural, no hace falta tocar el traductor.
