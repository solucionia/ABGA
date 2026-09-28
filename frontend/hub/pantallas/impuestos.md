# Impuestos · qué datos entran y qué parches hacen falta

`pantallas/impuestos.js` traduce la pantalla «Impuestos» a lo que la plataforma sabe de verdad: los
módulos fiscales por **empresa y ejercicio**. Los parches de este documento alinean el diseño con
esos datos. Los marcados **obligatorio** son necesarios para que la pantalla enseñe lo calculado y
no lo de ejemplo; el orden es el de aplicación.

Dos van juntos: **P11** (`IMP_EST`) y **P12** (`IMPUESTOS`). El traductor rellena la matriz de la
ficha de clientes con códigos de estado nuevos y la ficha los busca en `IMP_EST`; si se carga el
traductor sin cambiar `IMP_EST`, la ficha pintaría `IMP_EST[k2].l` de un código que no existe.

Datos que se piden (todos por `POST /api/informe`, con los parámetros del módulo en `params`):

| Módulo | Por qué |
|---|---|
| `fiscal` (trimestre) | IVA, retenciones, pago fraccionado, obligaciones y vencimientos del trimestre de esa empresa y ejercicio |
| `libro_iva` (trimestre) | base imponible derivada del IVA repercutido (el ERP no trae la base) |
| `libro_retenciones` (trimestre) | retenciones de trabajo, de profesionales y otras, y su base derivada |
| `sumas_saldos` (nivel 4) | saldo de las cuentas 472/477/4751/4752, las mismas que usa el módulo fiscal |

El `fiscal` se pide de la empresa en pantalla y de las demás empresas de la cartera **que ya tengan
el ejercicio leído** en el inventario local de la caché (mirarlo no despierta al ERP); de esas sólo
el módulo fiscal, para no multiplicar consultas. Tope: 30 empresas. Los libros y el balance, sólo de
la empresa que se está mirando.

Estado que deja el traductor (lo que leen los parches de abajo):

    impModelo   '303'|'111'|'202'            modelo de la pestaña abierta
    impFilas    [{id, nombre, nif, asesor, modelo, importe, tipo, est, estL, tono, grupo, ...}]
    impCas      {'<empresa>|<modelo>': [[clave, etiqueta, valor, tipo], ...]}   tipo: importe|numero|porcentaje|texto
    impMeta     {trimestre, periodo, periodoTxt, fechaLimite, fechaLimiteTexto, dias, plazoTxt,
                 obligacionTotal, conObligacion, empresas, generado}
    impEst      {}       (los estados de presentación inventados se vacían)
    impBusy     {}
    VENC        vencimientos reales del trimestre (modelo, desc, fecha, iso, humano, aplica, nota)
    IMPUESTOS   matriz modelo × [1T..4T + anual] con los códigos de IMP_EST de más abajo

---

## P1 · Cargar el traductor — obligatorio

**Actual**
```
<script src="pantallas/inicio.js"></script>
<script src="pantallas/envios.js"></script>
```
**Propuesto**
```html
<script src="pantallas/inicio.js"></script>
<script src="pantallas/envios.js"></script>
<script src="pantallas/impuestos.js"></script>
```
**Motivo** `datos.js` sabe registrar el traductor, pero el fichero tiene que cargarlo el navegador:
sin esta línea `ABGA.registrar('impuestos', …)` nunca se ejecuta y la pantalla sigue con los datos
de ejemplo.

## P2 · `rvImp()` — obligatorio

**Actual**
```
  rvImp(){
    const s = this.state, m = s.impModelo, V = VENC.find(v => v.modelo === m);
    const def = i => i < 2 ? 'presentado' : i < 4 ? 'preparado' : 'pendiente';
    const rows = CLIENTES.map((c, i) => {
      const d = this.impDatos(c, m); if (!d) return null;
      const est = s.impEst[m + c.id] || def(i), busy = !!s.impBusy[m + c.id];
      const tone = est === 'presentado' ? 'ok' : est === 'preparado' ? 'accent' : 'warn';
      return {id:c.id, nombre:c.nombre, nif:c.nif, asesor:c.asesor, res:eur(d.res), resFg: d.res < 0 ? 'var(--ok)' : 'var(--text)', tipo: d.res < 0 ? 'A compensar' : 'A ingresar', est, estL:{presentado:'Presentado', preparado:'Preparado · revisar', pendiente:'Pendiente'}[est], fg:T(tone).fg, bg:T(tone).bg, busy, notBusy:!busy,
        canPrep: est === 'pendiente' && !busy, canPres: est === 'preparado', isPres: est === 'presentado', csv:'CSV ' + (c.nif.slice(1, 5) + m + 'K7Q').toUpperCase(),
        sel: s.impSel === c.id, rowBg: s.impSel === c.id ? 'var(--accent-soft)' : 'transparent', delay:(i * 40) + 'ms',
        onOpen:() => this.setState({impSel:c.id}), onPrep:e => { e.stopPropagation(); this.impPreparar([c.id]); }, onPres:e => { e.stopPropagation(); this.setState(x => ({impEst:{...x.impEst, [m + c.id]:'presentado'}})); }};
    }).filter(Boolean);
    const vis = rows.filter(r => s.impFiltro === 'todos' || r.est === s.impFiltro);
    const cnt = k => rows.filter(r => r.est === k).length;
    const pend = rows.filter(r => r.est === 'pendiente' && !r.busy);
    const selC = rows.find(r => r.id === s.impSel), selD = selC ? this.impDatos(cli(selC.id), m) : null;
    const fmtCas = v => Number.isInteger(v) && v < 100 ? String(v) + (m === '202' && v === 17 ? ' %' : '') : eur(v);
    const pctDone = rows.length ? Math.round(cnt('presentado') / rows.length * 100) : 0, pctPrep = rows.length ? Math.round(cnt('preparado') / rows.length * 100) : 0;
    return {
      impTabs:VENC.map(v => ({l:'Modelo ' + v.modelo, d:v.desc, on:v.modelo === m, bg: v.modelo === m ? 'var(--surface)' : 'transparent', bc: v.modelo === m ? 'var(--accent)' : 'var(--border)', fg: v.modelo === m ? 'var(--text)' : 'var(--muted)', onClick:() => this.setState({impModelo:v.modelo, impSel:null, impFiltro:'todos'})})),
      impV:V, impDias:27, impRows:vis, impHasRows:vis.length > 0, impEmpty:!vis.length,
      impFiltros:[['todos','Todos', rows.length],['pendiente','Pendientes', cnt('pendiente')],['preparado','Preparados', cnt('preparado')],['presentado','Presentados', cnt('presentado')]].map(([k, l, n]) => ({l:l + ' · ' + n, onClick:() => this.setState({impFiltro:k}), bg: s.impFiltro === k ? 'var(--surface)' : 'transparent', fg: s.impFiltro === k ? 'var(--text)' : 'var(--muted)', sh: s.impFiltro === k ? 'var(--shadow)' : 'none'})),
      impStats:[['Presentados', cnt('presentado'), 'ok'], ['Preparados por revisar', cnt('preparado'), 'accent'], ['Pendientes de preparar', cnt('pendiente'), 'warn']].map(([l, n, t], i) => ({l, n, fg:T(t).fg, delay:(i * 60) + 'ms'})),
      impBarDone:pctDone + '%', impBarPrep:pctPrep + '%', impPctTxt:pctDone + ' % presentado',
      impCanAll:pend.length > 0, impAllL:'Preparar ' + pend.length + ' pendientes con IA', impPrepAll:() => this.impPreparar(pend.map(r => r.id)),
      impHasSel:!!selC, impSelC:selC || {nombre:'', nif:'', estL:'', fg:'', bg:'', canPres:false, canPrep:false, isPres:false, csv:'', res:'', tipo:''},
      impCas:selD ? selD.cas.map(([k, l, v]) => ({k, l, v:fmtCas(v)})) : [], impCloseSel:() => this.setState({impSel:null})
    };
  }
```
**Propuesto** (va dentro de la clase, con la misma sangría que el método actual)
```js
  rvImp(){
    const s = this.state, m = s.impModelo, meta = s.impMeta || {};
    const V = VENC.find(v => v.modelo === m) || {modelo:m, desc:'', aplica:false};
    const filas = (s.impFilas || []).filter(r => r.modelo === m);
    const EST = {a_ingresar:{l:'A ingresar · calculado',t:'accent'}, a_compensar:{l:'A compensar o a devolver',t:'ok'},
                 sin_obligacion:{l:'Sin obligación en el trimestre',t:'muted'}, sin_apuntes:{l:'Sin apuntes en el trimestre',t:'warn'},
                 na:{l:'No aplica en este trimestre',t:'muted'}};
    const rows = filas.map((r, i) => {
      const e = EST[r.est] || EST.na;
      return {id:r.id, nombre:r.nombre, nif:r.nif, asesor:r.asesor, res:eur(r.importe), resFg: r.importe < 0 ? 'var(--ok)' : 'var(--text)', tipo:r.tipo, est:r.est, estL:r.estL || e.l, grupo:r.grupo, fg:T(r.tono || e.t).fg, bg:T(r.tono || e.t).bg, busy:false, notBusy:true,
        canVer:true, canPrep:false, canPres:false, isPres:false, csv:'',
        sel: s.impSel === r.id, rowBg: s.impSel === r.id ? 'var(--accent-soft)' : 'transparent', delay:(i * 40) + 'ms',
        onOpen:() => this.setState({impSel:r.id}), onPrep:e2 => e2.stopPropagation(), onPres:e2 => e2.stopPropagation()};
    });
    const vis = rows.filter(r => s.impFiltro === 'todos' || r.grupo === s.impFiltro);
    const cnt = g => filas.filter(r => r.grupo === g).length;
    const selC = rows.find(r => r.id === s.impSel);
    const cas = (s.impCas || {})[(selC ? selC.id : '') + '|' + m] || [];
    const fmtCas = c => c[3] === 'texto' ? String(c[2] || '') : c[3] === 'numero' ? INT.format(c[2]) : c[3] === 'porcentaje' ? String(c[2]) + ' %' : eur(c[2]);
    const gen = String(meta.generado || '').slice(0, 10).split('-').reverse().join('/');
    const pctIng = filas.length ? Math.round(cnt('a_ingresar') / filas.length * 100) : 0, pctComp = filas.length ? Math.round(cnt('a_compensar') / filas.length * 100) : 0;
    return {
      impTabs:VENC.map(v => ({l:'Modelo ' + v.modelo, d:v.desc, on:v.modelo === m, bg: v.modelo === m ? 'var(--surface)' : 'transparent', bc: v.modelo === m ? 'var(--accent)' : 'var(--border)', fg: v.modelo === m ? 'var(--text)' : 'var(--muted)', onClick:() => this.setState({impModelo:v.modelo, impSel:null, impFiltro:'todos'})})),
      impV:V, impDias: meta.dias === null || meta.dias === undefined ? '' : meta.dias, impRows:vis, impHasRows:vis.length > 0, impEmpty:!vis.length,
      impFiltros:[['todos','Todos', filas.length],['a_ingresar','A ingresar', cnt('a_ingresar')],['a_compensar','A compensar', cnt('a_compensar')],['sin_obligacion','Sin obligación', cnt('sin_obligacion')]].map(([k, l, n]) => ({l:l + ' · ' + n, onClick:() => this.setState({impFiltro:k}), bg: s.impFiltro === k ? 'var(--surface)' : 'transparent', fg: s.impFiltro === k ? 'var(--text)' : 'var(--muted)', sh: s.impFiltro === k ? 'var(--shadow)' : 'none'})),
      impStats:[['Con obligación a ingresar', cnt('a_ingresar'), 'accent'], ['A compensar o a devolver', cnt('a_compensar'), 'ok'], ['Sin obligación o sin apuntes', cnt('sin_obligacion'), 'muted']].map(([l, n, t], i) => ({l, n, fg:T(t).fg, delay:(i * 60) + 'ms'})),
      impBarDone:pctIng + '%', impBarPrep:pctComp + '%', impPctTxt: filas.length ? pctIng + ' % con obligación a ingresar (' + filas.length + (filas.length === 1 ? ' empresa)' : ' empresas)') : 'Sin empresas que calcular',
      impCanAll:false, impAllL:'', impPrepAll:() => {},
      impHasSel:!!selC, impSelC: selC ? Object.assign({}, selC, {fuente:'Calculado por el módulo fiscal' + (gen ? ' · ' + gen : '')}) : {nombre:'', nif:'', estL:'', fg:'', bg:'', canVer:false, res:'', tipo:'', fuente:''},
      impCas: cas.map(c => ({k:c[0], l:c[1], v:fmtCas(c)})), impCloseSel:() => this.setState({impSel:null})
    };
  }
```
**Motivo** los renglones ya no se fabrican aquí: los deja el traductor en `impFilas` (una fila por
empresa de la cartera y modelo, con el importe y el estado calculados por el módulo fiscal). El
estado «presentado/preparado/pendiente» pasa a ser lo calculado, el filtro y las tres tarjetas se
cuentan por grupo real, y la barra mide la parte de la cartera con obligación a ingresar. `VENC` se
lee con `|| {}` porque el traductor lo deja vacío cuando el ejercicio no está leído.

## P3 · Estado inicial — obligatorio

**Actual**
```
impModelo:'303', impEst:{}, impBusy:{}, impSel:null, impFiltro:'todos',
```
**Propuesto**
```js
impModelo:'', impFilas:[], impCas:{}, impMeta:{}, impEst:{}, impBusy:{}, impSel:null, impFiltro:'todos',
```
**Motivo** `impEst` y `impBusy` guardaban el estado de presentación y la «preparación por IA», que no
existen: se vacían y se dejan a la vista los sitios donde el traductor deja lo calculado (`impFilas`,
`impCas`, `impMeta`), para que la primera pintada ya tenga la forma final.

## P4 · `impDatos()` e `impPreparar()` — obligatorio

**Actual**
```
  impDatos(c, mod){
    const tri = c.fact / 4, f = c.factor;
    if (mod === '303') { if (c.iva.startsWith('Exenta')) return null; const dev = tri * 0.21, ded = tri * 0.62 * 0.21 * (0.9 + f * 0.1); return {cas:[['01–09','Base imponible régimen general',tri],['27','Total cuota devengada',dev],['45','Total cuota deducible',ded],['71','Resultado de la liquidación',dev - ded]], res:dev - ded}; }
    if (mod === '111') { const b = c.empleados * 7400; return {cas:[['01','Perceptores rendimientos del trabajo',c.empleados],['02','Importe de las percepciones',b],['03','Importe de las retenciones',b * 0.14],['30','Resultado a ingresar',b * 0.14]], res:b * 0.14}; }
    if (mod === '115') { if (c.empleados < 8) return null; const b = 3 * (1400 + f * 900); return {cas:[['01','Número de perceptores',1],['02','Base de las retenciones',b],['03','Retenciones e ingresos a cuenta',b * 0.19],['04','Resultado a ingresar',b * 0.19]], res:b * 0.19}; }
    if (mod === '130') { if (c.forma !== 'Empresaria individual' && c.forma !== 'Comunidad de bienes') return null; const r = tri * 3 * 0.11; return {cas:[['01','Ingresos computables',tri * 3],['02','Gastos fiscalmente deducibles',tri * 3 * 0.89],['03','Rendimiento neto',r],['19','Resultado a ingresar',r * 0.2]], res:r * 0.2}; }
    if (mod === '202') { if (c.forma === 'Empresaria individual' || c.forma === 'Comunidad de bienes') return null; const bi = c.fact * 0.08 * (8 / 12); return {cas:[['03','Base del pago fraccionado',bi],['04','Porcentaje aplicable',17],['13','Pago fraccionado',bi * 0.17],['16','Resultado a ingresar',bi * 0.17]], res:bi * 0.17}; }
    return null;
  }
  impPreparar(ids){
    const m = this.state.impModelo;
    this.setState(x => { const b = {...x.impBusy}; ids.forEach(id => b[m + id] = true); return {impBusy:b}; });
    ids.forEach((id, i) => setTimeout(() => this.setState(x => { const b = {...x.impBusy}; delete b[m + id]; return {impBusy:b, impEst:{...x.impEst, [m + id]:'preparado'}}; }), 900 + i * 350));
  }
```
**Propuesto** (se borran los dos métodos: no hay reemplazo)
**Motivo** aquí estaba toda la invención: el resultado de cada modelo salía de la facturación, la
plantilla y la forma jurídica del cliente con porcentajes escritos a mano, y «preparar» sólo ponía
una etiqueta tras un `setTimeout`. Los importes buenos (472, 477, 4751, base del 202) los calcula el
módulo fiscal y el traductor los deja en `impCas`; ningún otro método los usa.

## P5 · Cabecera de la pantalla — obligatorio

**Actual**
```
<div><h1 style="margin:0;font-size:20px;font-weight:600;">Impuestos</h1><div style="color:var(--muted);margin-top:3px;">Modelos del 3.er trimestre 2026 · plazo hasta el 20/10/2026 · quedan {{ impDias }} días</div></div>
```
**Propuesto**
```html
<div><h1 style="margin:0;font-size:20px;font-weight:600;">Impuestos</h1><div style="color:var(--muted);margin-top:3px;">Modelos del {{ impPeriodoTxt }} · {{ impPlazoTxt }}</div></div>
```
**Motivo** «3.er trimestre 2026», «20/10/2026» y «quedan 27 días» están escritos a mano. Ahora sale
el trimestre de verdad del ejercicio en pantalla y el plazo real del módulo: p. ej.
«Modelos del 4T 2025 (octubre–diciembre) · plazo vencido el 20 de enero de 2026 (hace 250 días)».

## P6 · Columna «Asesor» — obligatorio

**Actual** (dos trozos: la cabecera y la celda)
```
<sc-raw-th style="text-align:left;padding:8px 10px;font-size:11px;font-weight:600;color:var(--muted);border-bottom:1px solid var(--border);">Asesor</sc-raw-th>

<sc-raw-td style="padding:9px 10px;border-bottom:1px solid var(--border);color:var(--muted);">{{ r.asesor }}</sc-raw-td>
```
**Propuesto** (se quitan las dos líneas: no hay reemplazo)
**Motivo** `GET /api/empresas` no devuelve el asesor de cada empresa: la columna saldría siempre
vacía. Se declara con `ctx.sinDatos` en lugar de dejar un hueco mudo.

## P7 · «La IA está preparando…» — obligatorio

**Actual**
```
<sc-if value="{{ r.busy }}" hint-placeholder-val="{{ false }}"><span style="display:inline-flex;align-items:center;gap:6px;font-size:11px;font-weight:600;color:var(--ai);"><span style="width:12px;height:12px;border-radius:50%;border:2px solid var(--ai-soft);border-top-color:var(--ai);animation:spin .8s linear infinite;"></span>La IA está preparando…</span></sc-if>
```
**Propuesto** (se quita el bloque: no hay reemplazo)
**Motivo** la plataforma no prepara declaraciones: no hay nada que esté «preparando» y el indicador
nunca se enciende. El estado real de cada fila ya lo enseña la etiqueta de al lado.

## P8 · Botones «Presentar» y CSV — obligatorio

**Actual**
```
                          <sc-if value="{{ r.canPres }}" hint-placeholder-val="{{ false }}"><button sc-camel-on-click="{{ r.onPres }}" style="height:30px;padding:0 10px;border:none;border-radius:5px;background:var(--btn);color:#fff;font-size:12px;font-weight:600;cursor:pointer;" style-hover="background:var(--btn-hover);">Presentar</button></sc-if>
                          <sc-if value="{{ r.isPres }}" hint-placeholder-val="{{ false }}"><span style="font-size:11px;color:var(--muted);font-family:'IBM Plex Mono',monospace;">{{ r.csv }}</span></sc-if>
```
**Propuesto**
```html
<sc-if value="{{ r.canVer }}" hint-placeholder-val="{{ true }}"><button sc-camel-on-click="{{ r.onOpen }}" style="height:30px;padding:0 10px;border:1px solid var(--border);border-radius:5px;background:var(--surface);color:var(--text);font-size:12px;cursor:pointer;" style-hover="border-color:var(--accent);">Ver desglose</button></sc-if>
```
**Motivo** no hay presentación telemática, ni acuse, ni CSV: el «CSV 303K7Q» se montaba con los
cuatro dígitos del NIF y el modelo. En su sitio queda abrir el desglose real (lo mismo que hace
pulsar la fila) y el `ctx.sinDatos` declara lo que no existe.

## P9 · Texto de la tabla vacía

**Actual**
```
<div style="padding:32px;text-align:center;color:var(--muted);">No hay clientes en este estado.</div>
```
**Propuesto**
```html
<div style="padding:32px;text-align:center;color:var(--muted);">No hay ninguna empresa en este estado.</div>
```
**Motivo** los renglones son empresas de la cartera que ya tienen el ejercicio calculado, no clientes
de la ficha.

## P10 · Pie del desglose

**Actual**
```
<span style="font-size:11px;color:var(--muted);">Calculado desde el ERP · 23/09/2026</span>
```
**Propuesto**
```html
<span style="font-size:11px;color:var(--muted);">{{ impSelC.fuente }}</span>
```
**Motivo** la fecha era fija. La fuente real es el módulo fiscal del ejercicio leído y su sello de
generación, que ahora viaja en `impSelC.fuente` («Calculado por el módulo fiscal · 27/09/2026»).

## P11 · `IMP_EST` — obligatorio si se aplica este traductor

**Actual**
```
const IMP_EST = {ok:{l:'Presentado',t:'ok'},ai:{l:'Preparado por IA',t:'ai'},pend:{l:'Pendiente',t:'warn'},na:{l:'—',t:'muted'},venc:{l:'Vencido',t:'err'}};
```
**Propuesto**
```js
const IMP_EST = {con_obligacion:{l:'Con obligación',t:'accent'},a_compensar:{l:'A compensar',t:'ok'},sin_obligacion:{l:'Sin obligación',t:'muted'},sin_apuntes:{l:'Sin apuntes',t:'warn'},na:{l:'—',t:'muted'}};
```
**Motivo** «Presentado», «Preparado por IA» y «Vencido» son estados de presentación que la
plataforma no registra; los nuevos son los que el traductor deja en `IMPUESTOS`: si hay obligación
calculada en el trimestre, si sale a compensar, si no hay obligación o si no hay apuntes. Aviso: el
traductor escribe esos códigos en `IMPUESTOS` y la ficha hace `IMP_EST[k2].l`, así que **los dos
cambios van juntos** (el código `na` se mantiene porque el markup lo usa para el fondo transparente).

## P12 · Constante `IMPUESTOS` — obligatorio

**Actual**
```
const IMPUESTOS = [
  {modelo:'303',desc:'IVA trimestral',c:['ok','ok','ai','pend','na']},
  {modelo:'111',desc:'Retenciones IRPF',c:['ok','ok','ai','pend','na']},
  {modelo:'115',desc:'Retenciones alquileres',c:['ok','ok','pend','pend','na']},
  {modelo:'202',desc:'Pago fraccionado IS',c:['ok','na','pend','pend','na']},
  {modelo:'200',desc:'Impuesto sobre Sociedades',c:['na','na','na','na','ok']},
  {modelo:'390',desc:'Resumen anual IVA',c:['na','na','na','na','ok']},
  {modelo:'347',desc:'Operaciones con terceros',c:['na','na','na','na','ok']}
];
```
**Propuesto**
```js
// La matriz la deja la capa de datos (pantallas/impuestos.js) con los trimestres reales de la
// empresa que se está analizando: la plataforma calcula por empresa y ejercicio, y no registra
// presentaciones.
const IMPUESTOS = [];
```
**Motivo** las siete filas y sus 35 casillas estaban escritas a mano. La plataforma sólo calcula
303, 111 y 202 (los 115 salen como retenciones a profesionales, pero sin obligación calculada; 200,
390 y 347 no existen como módulo) y no conoce el estado de presentación: se declara con
`ctx.sinDatos` y la matriz se rellena con lo calculado, trimestre a trimestre.

## P13 · Ficha de clientes: «Próximo vencimiento» — recomendado

**Actual**
```
<span style="font-size:12px;color:var(--muted);">Próximo vencimiento: 20/10/2026 · 303, 111, 115 y 202</span>
```
**Propuesto**
```html
<span style="font-size:12px;color:var(--muted);">Los modelos 303, 111 y 202 de esta empresa se detallan en la pantalla Impuestos</span>
```
**Motivo** la fecha y la lista de modelos están escritas a mano y la ficha de un cliente no tiene
datos fiscales propios: la plataforma calcula por empresa y ejercicio. La frase que se propone dice
lo que hay y dónde está.

## P14 · `datos.js`: los parámetros del informe — obligatorio

**Actual** (en `ctx.informe`, dentro de `frontend/hub/datos.js`)
```
parametros: parametros || undefined
```
**Propuesto**
```js
          params: parametros || undefined
```
**Motivo** `PeticionInforme` de la API prohíbe campos de más (`extra: forbid`): mandar `parametros`
devuelve **422 «Extra inputs are not permitted»** (comprobado contra la plataforma). El traductor de
Impuestos esquiva el problema llamando a `ctx.api.informe` con `params`, pero cualquier traductor que
use `ctx.informe('fiscal', {trimestre: 3})` fallará mientras esto no se cambie.
