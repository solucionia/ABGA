# Proyecciones · del modelo del frontal a los números de la plataforma

La pantalla «Proyecciones» del hub (`frontend/hub/index.html`, `rvProy`) calculaba sus propias
cifras: temporadas fijas (`SEAS_RAW`), ruido mensual inventado (`NOISE`), tres escenarios escritos a
mano con sus porcentajes (`ESC`), cinco supuestos editables con rangos (`PARAMS`) y las funciones
`projBase` / `realMonths` / `project` / `pyg`. Nada de eso sale de la contabilidad del cliente.

Ahora los números los pone el módulo `proyecciones` de la plataforma, que es determinista. El
traductor es `frontend/hub/pantallas/proyecciones.js` (registrado con `ABGA.registrar('proyecciones')`)
y deja todo en `state.proyDatos`; `rvProy` sólo dibuja.

## Cómo entra

```
hub componentDidMount → ABGA.cargar(componente)
  → traductor 'proyecciones' (pantallas/proyecciones.js)
      · si !ctx.hayCache(): pantalla vacía + ctx.sinDatos + ctx.pedirDelErp  (igual que inicio.js)
      · ctx.informe('proyecciones')            → la `data` del módulo, sin parámetros propios
      · ctx.parchear({proyDatos: {...}})       → state.proyDatos
  → se vuelve a pintar y rvProy lee state.proyDatos
```

El selector de cliente del hub ya usa su propia lista de empresas (`CLIENTES`, sembrada por
datos.js desde `/api/empresas`): cambiar de cliente cambia `proyCliente`, y datos.js lo traduce a
`estado.empresa` y recarga la pantalla (el módulo se vuelve a pedir para esa empresa).

## De dónde sale cada bloque

| En pantalla | Campo del módulo (`data`) |
|---|---|
| Gráfico · tramo continuo | `mesEnCurso` hasta `mesCorte` (meses con apuntes leídos) |
| Gráfico · tramo discontinuo dentro del ejercicio | `mesEnCurso` con `proyectado: true` (cierre estimado por el módulo con `factorEstacionalIngresos`) |
| Gráfico · 12 meses del ejercicio proyectado | `mesMensualProyectado` (reparto con la estacionalidad real), `yearProyectado` |
| Gráfico · banda | `escenarios.conservador.ingresos` y `escenarios.optimista.ingresos` repartidos con `pesoIngresos` |
| Indicadores (4) | `proyeccionBase` (ingresos, ebitda, resultado, margenEbitda, margenNeto) y `magnitudesActual`; las variaciones, tal cual las da el módulo (`varIngresos`, `varResultado`) |
| Tarjetas de escenario | `escenarios` (conservador/base/optimista) con `factorIngresos`, `factorGastos`, `variacionResultado`, `tesoreriaEstimada` |
| Panel izquierdo | `tendencias` (por magnitud: `proyeccion`, `tendencia`, `tasaCrecimiento`, `r2`, `n`, `fiabilidad`, `nota`) + `tipoImpuesto`, `mesCorte`, factores |
| Tabla de la PyG | `historico` (un ejercicio por columna) + `proyeccionBase` (última columna) |
| Avisos | `alertas` (`nivel` ALTA/MEDIA/INFO + `mensaje`) y `nivelGlobal` |
| CSV | las mismas filas y columnas que la tabla (valores sin formatear) |

Tres cosas que la pantalla compone y conviene tener dichas:

- **El EBITDA de cada mes** es `ingresos − gastos de explotación`, que es la definición que usa el
  propio módulo para el EBITDA anual. No es una estimación nueva.
- **La fila «Margen bruto»** de la tabla es `ingresos − aprovisionamientos` (diferencia de dos
  magnitudes del módulo, no una proyección aparte).
- **Los meses del escenario** (la banda) son la cifra anual que devuelve el módulo para ese
  escenario repartida con los pesos mensuales que también devuelve el módulo
  (`mesMensualProyectado[].pesoIngresos`). La proyección de la plataforma es **anual por
  ejercicio**; abrirla en meses es esto, no un modelo nuevo del frontal.

## Lo que la plataforma no proyecta (y por eso se declara con `ctx.sinDatos`)

1. `el horizonte a 36 meses` — proyecta un único ejercicio, el siguiente al cargado.
2. `los supuestos editables por partida (PARAMS)` — ajusta una regresión ponderada; no simula
   crecimientos por partida.
3. `el porcentaje de confianza de cada escenario` — publica los factores aplicados y la variación
   del resultado, no una probabilidad.
4. `guardar el escenario` — no guarda escenarios propios del despacho.
5. `las temporadas fijas y el ruido del frontal (SEAS_RAW, NOISE)` — sustituidos por los factores
   estacionales reales (`factorEstacionalIngresos`, `aniosCompletosEstacionalidad`).
6. `el saldo de tesorería proyectado` cuando el ERP no trae cuentas 570-577 (`hayTesoreria: false`):
   el módulo informa de la caja generada.
7. `las magnitudes del ejercicio cargado` cuando `magnitudesActual` es `null` (ese ejercicio no está
   entre los que tienen apuntes).

Además, cuando el módulo no está disponible (`disponible: false`) o el informe falla, la pantalla se
queda vacía y lo dice: `proyVacio` + `proyAviso`, más el aviso de la capa de datos.

## Parches para `frontend/hub/index.html`

Los `Actual` están copiados **verbatim** del fichero (verificado: cada uno aparece exactamente una
vez), así que se localizan por texto y no por número de línea. Aplicados los 18, el script del hub
sigue siendo JavaScript válido (`node --check`) y no queda ni una referencia a `ESC`, `PARAMS`,
`projBase`, `realMonths`, `project(`, `pyg(`, `proyTargets`, `tweenProj`, `setParam`, `proyP`,
`proyDisp`, `proyEdited`, `proySaved`, `proyParams`, `proySave`, `proyReset`, `proyConf`,
`proyNotEdited` ni `proyEscLabel`.


### Parche 1

**Actual**

```
<script src="pantallas/envios.js"></script>
```

**Propuesto**

```
<script src="pantallas/envios.js"></script>
<script src="pantallas/proyecciones.js"></script>
```

**Motivo** El traductor de la pantalla tiene que estar cargado antes de que el hub pida los datos (datos.js lo llama en componentDidMount).


### Parche 2

**Actual**

```
[&quot;12&quot;,&quot;24&quot;,&quot;36&quot;]
```

**Propuesto**

```
[&quot;12&quot;,&quot;24&quot;]
```

**Motivo** La plataforma proyecta un único ejercicio (el siguiente al cargado): no hay proyección a 36 meses que ofrecer.


### Parche 3

**Actual**

```
proyCliente:'C001', proyH: [12,24,36].includes(Number(p.horizonteInicial)) ? Number(p.horizonteInicial) : 24, proyEsc:'base', proyP:{...ESC.base}, proyEdited:false, proyTip:null, proyDisp:null, proySaved:false,
```

**Propuesto**

```
proyCliente:'C001', proyH: Number(p.horizonteInicial) === 12 ? 12 : 24, proyEsc:'base', proyTip:null, proyDatos:null,
```

**Motivo** El estado guardaba los supuestos del frontal (proyP, proyEdited, proySaved, proyDisp) y un horizonte de 12/24/36. Ahora guarda el escenario y el horizonte elegidos, y `proyDatos`, que es lo que deja el traductor.


### Parche 4

**Actual**

```
const ESC = {
  conservador:{l:'Conservador', ventas:1.5, aprov:44, personal:4, otros:3.5, fin:5, conf:78, nota:'Demanda plana y subida de costes de vidrio y energía'},
  base:{l:'Base', ventas:5.5, aprov:42, personal:3, otros:2.5, fin:0, conf:84, nota:'Tendencia de los últimos 36 meses y cartera de pedidos actual'},
  optimista:{l:'Optimista', ventas:9, aprov:40.5, personal:2.5, otros:2, fin:-5, conf:71, nota:'Entrada en dos distribuidores de exportación y bajada de tipos'}
};
const PARAMS = [
  {k:'ventas', l:'Cifra de negocios', sub:'Crecimiento anual', min:-10, max:20, step:0.5},
  {k:'aprov', l:'Aprovisionamientos', sub:'% sobre ventas', min:30, max:55, step:0.5},
  {k:'personal', l:'Gastos de personal', sub:'Crecimiento anual', min:-5, max:10, step:0.5},
  {k:'otros', l:'Otros gastos de explotación', sub:'Crecimiento anual', min:-5, max:10, step:0.5},
  {k:'fin', l:'Gastos financieros', sub:'Variación anual', min:-20, max:20, step:1}
];

```

**Propuesto**

```
(se borra)
```

**Motivo** Se va el modelo de escenarios y supuestos del frontal: crecimientos por partida escritos a mano (ESC) y sus rangos editables (PARAMS). Los escenarios y las tendencias los calcula el módulo `proyecciones` (factores declarados y regresión ponderada por magnitud).


### Parche 5

**Actual**

```
function projBase(cid){ const f = cli(cid).factor; return {ventas:4350000 * f, personal:1120000 * f, otros:620000 * f, amort:210000 * f, fin:48000 * f}; }
function realMonths(cid){
  const b = projBase(cid), out = [];
  for (let i = 0; i < 12; i++) { const m = (8 + i) % 12, y = 2025 + Math.floor((8 + i) / 12); const v = b.ventas * SEAS[m] * NOISE[i] / 1.055; const ebitda = v - v * 0.423 - b.personal / 12 - b.otros / 12; out.push({m, y, label:MES_C[m] + ' ' + String(y).slice(2), v, ebitda, real:true}); }
  return out;
}
function project(cid, p, H){
  const b = projBase(cid), out = [];
  for (let t = 1; t <= H; t++) {
    const m = (7 + t) % 12, y = 2026 + Math.floor((7 + t) / 12), yrs = t / 12;
    const v = b.ventas * SEAS[m] * Math.pow(1 + p.ventas / 100, yrs);
    const ap = v * p.aprov / 100, pe = b.personal / 12 * Math.pow(1 + p.personal / 100, yrs), ot = b.otros / 12 * Math.pow(1 + p.otros / 100, yrs);
    const am = b.amort / 12, fi = b.fin / 12 * Math.pow(1 + p.fin / 100, yrs);
    out.push({m, y, label:MES_C[m] + ' ' + String(y).slice(2), v, ap, pe, ot, am, fi, ebitda:v - ap - pe - ot, real:false});
  }
  return out;
}
function pyg(rows, b, realFlag){
  const s = k => rows.reduce((a, r) => a + (r[k] || 0), 0);
  const v = s('v'), ap = realFlag ? v * 0.423 : s('ap'), pe = realFlag ? b.personal : s('pe'), ot = realFlag ? b.otros : s('ot'), am = realFlag ? b.amort : s('am'), fi = realFlag ? b.fin : s('fi');
  const mb = v - ap, ebitda = mb - pe - ot, bai = ebitda - am - fi, is = bai > 0 ? bai * 0.25 : 0, neto = bai - is;
  return {v, ap, mb, pe, ot, ebitda, am, fi, bai, is, neto, mn: v ? neto / v * 100 : 0};
}

```

**Propuesto**

```
(se borra)
```

**Motivo** Se van las funciones que inventaban las cifras (projBase, realMonths, project, pyg): proyección por temporadas fijas y ruido sobre una cifra base. `niceMax` se queda: es la escala del gráfico, no un cálculo financiero.


### Parche 6

**Actual**

```
  proyTargets(s){
    const b = projBase(s.proyCliente), pr = project(s.proyCliente, s.proyP, s.proyH), last = pr.slice(-12);
    const r = pyg(realMonths(s.proyCliente), b, true), f = pyg(last, b, false);
    return {v:f.v, ebitda:f.ebitda, neto:f.neto, mn:f.mn, rv:r.v, rebitda:r.ebitda, rneto:r.neto, rmn:r.mn};
  }
  tweenProj(next){
    const from = this.state.proyDisp || this.proyTargets(this.state), to = this.proyTargets({...this.state, ...next});
    this.setState(next);
    clearTimeout(this._pr);
    const t0 = Date.now();
    const step = () => { const t = Math.min(1, (Date.now() - t0) / 450), e = 1 - Math.pow(1 - t, 3), d = {}; Object.keys(to).forEach(k => d[k] = from[k] + (to[k] - from[k]) * e); this.setState({proyDisp:d}); if (t < 1) this._pr = setTimeout(step, 16); };
    this._pr = setTimeout(step, 16);
  }
  setParam(k, v){ this.tweenProj({proyP:{...this.state.proyP, [k]:Number(v)}, proyEdited:true, proySaved:false}); }
  setEsc(k){ this.tweenProj({proyEsc:k, proyP:{...ESC[k]}, proyEdited:false, proySaved:false}); }
```

**Propuesto**

```
  setEsc(k){ this.setState({proyEsc:k, proyTip:null}); }
```

**Motivo** proyTargets/tweenProj/setParam/setEsc animaban y recalculaban cifras propias. Queda sólo setEsc, que cambia el escenario que se enseña: los tres escenarios los da el módulo.


### Parche 7

**Actual**

```
const blob = new Blob(['\ufeff' + lines.join('\n')], {type:'text/csv;charset=utf-8'}); const a = document.createElement('a'); a.href = URL.createObjectURL(blob); a.download = 'proyeccion_' + this.state.proyEsc + '_' + this.state.proyH + 'm.csv'; document.body.appendChild(a); a.click(); a.remove();
```

**Propuesto**

```
const blob = new Blob(['\ufeff' + lines.join('\n')], {type:'text/csv;charset=utf-8'}); const a = document.createElement('a'); a.href = URL.createObjectURL(blob); a.download = 'proyeccion_' + ((this.state.proyDatos || {}).yearProyectado || '') + '_' + this.state.proyEsc + '.csv'; document.body.appendChild(a); a.click(); a.remove();
```

**Motivo** El nombre del fichero ya no puede llevar `state.proyH` (el horizonte de 12/24/36 meses del frontal no existe): lleva el ejercicio proyectado y el escenario que se está viendo.


### Parche 8

**Actual**

```
  rvProy(){
    const s = this.state, b = projBase(s.proyCliente), real = realMonths(s.proyCliente), pr = project(s.proyCliente, s.proyP, s.proyH);
    const lo = project(s.proyCliente, ESC.conservador, s.proyH), hi = project(s.proyCliente, ESC.optimista, s.proyH);
    const all = [...real, ...pr], N = all.length;
    const fmtC = v => Math.abs(v) >= 1e6 ? (v / 1e6).toLocaleString('es-ES', {maximumFractionDigits:1}) + ' M€' : Math.round(v / 1000).toLocaleString('es-ES') + ' k€';
    const pct = v => (v >= 0 ? '+' : '−') + Math.abs(v).toLocaleString('es-ES', {minimumFractionDigits:1, maximumFractionDigits:1}) + ' %';
    const W = 760, H = 290, pl = 54, prr = 14, pt = 16, pb = 30, pw = W - pl - prr, ph = H - pt - pb;
    const maxV = niceMax(Math.max(...all.map(r => r.v), ...hi.map(r => r.v)) * 1.08);
    const minE = Math.min(0, ...all.map(r => r.ebitda), ...lo.map(r => r.ebitda)), minV = minE < 0 ? -niceMax(-minE * 1.3) : 0;
    const X = i => pl + i * pw / (N - 1), Y = v => pt + ph - (v - minV) / (maxV - minV) * ph;
    const pts = (arr, off, key) => arr.map((r, i) => X(i + off).toFixed(1) + ' ' + Y(r[key]).toFixed(1));
    const lr = real[11];
    const path = (arr, off, key, start) => (start ? 'M' + X(11).toFixed(1) + ' ' + Y(lr[key]).toFixed(1) + ' L' : 'M') + pts(arr, off, key).join(' L');
    const band = 'M' + X(11).toFixed(1) + ' ' + Y(lr.v).toFixed(1) + ' L' + pts(hi, 12, 'v').join(' L') + ' L' + pts(lo, 12, 'v').reverse().join(' L') + ' Z';
    const grid = [0, 1, 2, 3, 4].map(g => { const v = minV + (maxV - minV) * g / 4; return {y:Y(v).toFixed(1), label:fmtC(v), x1:pl, x2:W - prr}; });
    const every = s.proyH === 36 ? 6 : 3;
    const xl = all.map((r, i) => ({x:X(i).toFixed(1), y:H - 9, t:r.label, show:i % every === 0})).filter(x => x.show);
    const colW = pw / (N - 1);
    const cols = all.map((r, i) => ({x:(X(i) - colW / 2).toFixed(1), w:colW.toFixed(1), enter:() => this.setState({proyTip:i})}));
    const ti = s.proyTip, tr = ti !== null && ti !== undefined ? all[ti] : null;
    const zero = minV < 0 ? Y(0).toFixed(1) : null;
    const chart = {W, H, pl, pt, ph, grid, xl, cols, band, pReal:path(real, 0, 'v'), pProj:path(pr, 12, 'v', true), eReal:path(real, 0, 'ebitda'), eProj:path(pr, 12, 'ebitda', true),
      divX:X(11.5).toFixed(1), futW:(W - prr - X(11.5)).toFixed(1), divLabelX:(X(11.5) + 6).toFixed(1), realLabelX:(X(11.5) - 6).toFixed(1), hasZero:zero !== null, zeroY:zero || 0, bottom:pt + ph};
    const tip = tr ? {left:(X(ti) / W * 100) + '%', top:(Math.min(Y(tr.v), Y(tr.ebitda)) / H * 100) + '%', cx:X(ti).toFixed(1), cyV:Y(tr.v).toFixed(1), cyE:Y(tr.ebitda).toFixed(1), label:tr.label, v:eur(tr.v), e:eur(tr.ebitda), tipo: tr.real ? 'Real contabilizado' : 'Proyección · ' + (s.proyEdited ? 'personalizada' : ESC[s.proyEsc].l.toLowerCase()), tipoFg: tr.real ? '#9fc2e8' : '#7fd6e3'} : {left:'0', top:'0', cx:0, cyV:0, cyE:0, label:'', v:'', e:'', tipo:'', tipoFg:'#fff'};
    const d = s.proyDisp || this.proyTargets(s);
    const yrs = s.proyH / 12, lastLbl = pr[pr.length - 1].label;
    const kpis = [
      {label:'Ventas · año ' + yrs, value:eur(d.v), sub:pct((d.v / d.rv - 1) * 100) + ' vs. últimos 12 meses', fg: d.v >= d.rv ? 'var(--ok)' : 'var(--err)'},
      {label:'EBITDA · año ' + yrs, value:eur(d.ebitda), sub:'Margen ' + (d.ebitda / d.v * 100).toLocaleString('es-ES', {maximumFractionDigits:1}) + ' % · real ' + (d.rebitda / d.rv * 100).toLocaleString('es-ES', {maximumFractionDigits:1}) + ' %', fg: d.ebitda >= d.rebitda ? 'var(--ok)' : 'var(--err)'},
      {label:'Resultado neto · año ' + yrs, value:eur(d.neto), sub:pct((d.neto / d.rneto - 1) * 100) + ' vs. últimos 12 meses', fg: d.neto >= d.rneto ? 'var(--ok)' : 'var(--err)'},
      {label:'Margen neto · año ' + yrs, value:d.mn.toLocaleString('es-ES', {minimumFractionDigits:1, maximumFractionDigits:1}) + ' %', sub:'Real últimos 12 meses: ' + d.rmn.toLocaleString('es-ES', {maximumFractionDigits:1}) + ' %', fg: d.mn >= d.rmn ? 'var(--ok)' : 'var(--err)'}
    ];
    const periods = [pyg(real, b, true)], colsT = ['Últimos 12 meses (real)'];
    for (let y = 0; y < yrs; y++) { periods.push(pyg(pr.slice(y * 12, y * 12 + 12), b, false)); colsT.push('Año ' + (y + 1) + ' · hasta ' + pr[y * 12 + 11].label); }
    const RW = [['Cifra de negocios','v',false,1],['Aprovisionamientos','ap',false,-1],['Margen bruto','mb',true,1],['Gastos de personal','pe',false,-1],['Otros gastos de explotación','ot',false,-1],['EBITDA','ebitda',true,1],['Amortización del inmovilizado','am',false,-1],['Gastos financieros','fi',false,-1],['Resultado antes de impuestos','bai',true,1],['Impuesto sobre Sociedades (25 %)','is',false,-1],['Resultado del ejercicio','neto',true,1]];
    const tRows = RW.map(([l, k2, bold, sg], i) => {
      const raw = periods.map(p => p[k2] * sg), last = raw[raw.length - 1], first = raw[0];
      const dv = first ? (last / first - 1) * 100 : 0;
      return {l, raw, cells:raw.map((v, j) => ({v:eur(v), fg: v < 0 ? 'var(--err)' : 'var(--text)', w: bold ? 600 : 400, bg: j === 0 ? 'var(--surface2)' : 'transparent'})), fw: bold ? 600 : 400, rowBg: bold ? 'var(--accent-soft)' : 'transparent', delta:pct(dv), deltaFg: (sg > 0 ? dv >= 0 : dv <= 0) ? 'var(--ok)' : 'var(--err)', delay:(i * 25) + 'ms'};
    });
    const escCards = Object.keys(ESC).map(k2 => {
      const e = ESC[k2], p2 = pyg(project(s.proyCliente, e, s.proyH).slice(-12), b, false), act = s.proyEsc === k2;
      return {l:e.l, nota:e.nota, conf:e.conf + ' %', v:fmtC(p2.v), neto:fmtC(p2.neto), mn:p2.mn.toLocaleString('es-ES', {maximumFractionDigits:1}) + ' %', onClick:() => this.setEsc(k2), bd: act ? 'var(--accent)' : 'var(--border)', bg: act ? 'var(--accent-soft)' : 'var(--surface)', sh: act ? '0 0 0 3px var(--accent-soft)' : 'none', act, supuestos:'Ventas ' + pct(e.ventas) + ' · Aprov. ' + e.aprov.toLocaleString('es-ES') + ' %'};
    });
    const params = PARAMS.map(pm => {
      const v = s.proyP[pm.k], def = ESC[s.proyEsc][pm.k], fill = (v - pm.min) / (pm.max - pm.min) * 100;
      return {...pm, v, val: pm.k === 'aprov' ? v.toLocaleString('es-ES', {minimumFractionDigits:1}) + ' %' : pct(v), onChange:e => this.setParam(pm.k, e.target.value), changed: v !== def, defTxt:'Propuesta IA: ' + (pm.k === 'aprov' ? def.toLocaleString('es-ES') + ' %' : pct(def)), track:'linear-gradient(90deg,var(--accent) ' + fill + '%,var(--border) ' + fill + '%)', id:'pp-' + pm.k};
    });
    return {
      proyClientes:CLIENTES.map(c => ({value:c.id, label:c.nombre})), proyCliente:s.proyCliente, setProyCliente:e => this.tweenProj({proyCliente:e.target.value, proyTip:null}),
      proyHs:[12,24,36].map(h2 => ({label:h2 + ' meses', onClick:() => this.tweenProj({proyH:h2, proyTip:null}), bg: s.proyH === h2 ? 'var(--surface)' : 'transparent', fg: s.proyH === h2 ? 'var(--text)' : 'var(--muted)', sh: s.proyH === h2 ? 'var(--shadow)' : 'none'})),
      proyKpis:kpis, proyChart:chart, proyHasTip:!!tr, proyTipD:tip, proyLeave:() => this.setState({proyTip:null}),
      proyCols:colsT, proyRows:tRows, proyEsc:escCards, proyParams:params, proyEdited:s.proyEdited, proyNotEdited:!s.proyEdited,
      proyEscLabel: s.proyEdited ? 'Personalizado · a partir del escenario ' + ESC[s.proyEsc].l.toLowerCase() : 'Escenario ' + ESC[s.proyEsc].l.toLowerCase(), proyConf:ESC[s.proyEsc].conf + ' %', proyHasta:lastLbl,
      proyReset:() => this.setEsc(s.proyEsc), proySave:() => this.setState({proySaved:true}), proySaved:s.proySaved, proySaveLabel: s.proySaved ? 'Escenario guardado' : 'Guardar escenario',
      proyCsv:() => this.exportProyCsv(tRows, colsT)
    };
  }
```

**Propuesto**

```
  rvProy(){
    // Todas las cifras llegan ya calculadas por la plataforma en `state.proyDatos`, que es lo que
    // deja pantallas/proyecciones.js. Aquí sólo se dibuja: escala, trazos y textos. Esta pantalla
    // ya no calcula ninguna proyección.
    const s = this.state, d = s.proyDatos || {}, banda = d.banda || [], todos = d.meses || [];
    // El módulo da 24 columnas: los 12 meses del ejercicio en curso (contabilizados hasta el mes de
    // corte) y los 12 del ejercicio proyectado. Con 12 se enseña sólo el ejercicio en curso.
    const all = s.proyH === 12 ? todos.slice(0, 12) : todos;
    const N = all.length, nReal = Math.min(d.nReal || 0, N), corte = Math.max(0, nReal);
    const num = v => (v === null || v === undefined || isNaN(v)) ? 0 : v;
    const fmtC = v => Math.abs(v) >= 1e6 ? (v / 1e6).toLocaleString('es-ES', {maximumFractionDigits:1}) + ' M€' : Math.round(v / 1000).toLocaleString('es-ES') + ' k€';
    const W = 760, H = 290, pl = 54, prr = 14, pt = 16, pb = 30, pw = W - pl - prr, ph = H - pt - pb;
    const maxV = niceMax(Math.max(1, ...all.map(r => num(r.v)), ...banda.slice(0, N).map(b => num(b.hi))) * 1.08);
    const minE = Math.min(0, ...all.map(r => num(r.ebitda)), ...banda.slice(0, N).map(b => num(b.lo)));
    const minV = minE < 0 ? -niceMax(-minE * 1.3) : 0;
    const X = i => N > 1 ? pl + i * pw / (N - 1) : pl + pw / 2, Y = v => pt + ph - (v - minV) / (maxV - minV) * ph;
    const pts = (arr, off, key) => arr.map((r, i) => X(i + off).toFixed(1) + ' ' + Y(num(r[key])).toFixed(1));
    // «sale» dibuja un tramo; si se le pasa `enlaza` arranca en ese punto (así lo proyectado sale
    // del último mes contabilizado y las dos líneas se tocan).
    const sale = (arr, off, key, enlaza) => arr.length ? (enlaza ? 'M' + X(off - 1).toFixed(1) + ' ' + Y(num(enlaza[key])).toFixed(1) + ' L' : 'M') + pts(arr, off, key).join(' L') : '';
    const real = all.slice(0, corte), proy = all.slice(corte), anterior = corte > 0 ? all[corte - 1] : null;
    const pReal = real.length > 1 ? sale(real, 0, 'v') : '', eReal = real.length > 1 ? sale(real, 0, 'ebitda') : '';
    const pProj = sale(proy, corte, 'v', anterior), eProj = sale(proy, corte, 'ebitda', anterior);
    // Banda del rango conservador-optimista: los importes mensuales que ya trae la plataforma.
    const hi = proy.map((r, i) => ({v: num((banda[corte + i] || {}).hi)})), lo = proy.map((r, i) => ({v: num((banda[corte + i] || {}).lo)}));
    const band = proy.length && anterior ? 'M' + X(corte - 1).toFixed(1) + ' ' + Y(num(anterior.v)).toFixed(1) + ' L' + pts(hi, corte, 'v').join(' L') + ' L' + pts(lo, corte, 'v').reverse().join(' L') + ' Z' : '';
    const grid = [0, 1, 2, 3, 4].map(g => { const v = minV + (maxV - minV) * g / 4; return {y:Y(v).toFixed(1), label:fmtC(v), x1:pl, x2:W - prr}; });
    const every = N > 25 ? 6 : 3;
    const xl = all.map((r, i) => ({x:X(i).toFixed(1), y:H - 9, t:r.label, show:i % every === 0})).filter(x => x.show);
    const colW = N > 1 ? pw / (N - 1) : pw;
    const cols = all.map((r, i) => ({x:(X(i) - colW / 2).toFixed(1), w:colW.toFixed(1), enter:() => this.setState({proyTip:i})}));
    const ti = s.proyTip, tr = ti !== null && ti !== undefined ? all[ti] : null;
    // La raya de «hasta aquí lo contabilizado» cae donde termina el dato real del ejercicio en curso.
    const divX = Math.min(W - prr, Math.max(pl, X(corte - 0.5)));
    const chart = {W, H, pl, pt, ph, grid, xl, cols, band, pReal, pProj, eReal, eProj,
      divX:divX.toFixed(1), futW:Math.max(0, W - prr - divX).toFixed(1), divLabelX:(divX + 6).toFixed(1), realLabelX:(divX - 6).toFixed(1), bottom:pt + ph};
    const escLbl = (d.escenarios || []).filter(e => e.clave === s.proyEsc).map(e => e.l)[0] || 'base';
    const tip = tr ? {left:(X(ti) / W * 100) + '%', top:(Math.min(Y(num(tr.v)), Y(num(tr.ebitda))) / H * 100) + '%', cx:X(ti).toFixed(1), cyV:Y(num(tr.v)).toFixed(1), cyE:Y(num(tr.ebitda)).toFixed(1), label:tr.label, v:eur(num(tr.v)), e:eur(num(tr.ebitda)), tipo: tr.tipo === 'real' ? 'Real contabilizado' : (tr.tipo === 'cierre' ? 'Cierre del ejercicio estimado por la plataforma' : 'Proyección de ' + tr.anio + ' · escenario ' + escLbl), tipoFg: tr.tipo === 'real' ? '#9fc2e8' : '#7fd6e3'} : {left:'0', top:'0', cx:0, cyV:0, cyE:0, label:'', v:'', e:'', tipo:'', tipoFg:'#fff'};
    return {
      proyClientes:CLIENTES.map(c => ({value:c.id, label:c.nombre})), proyCliente:s.proyCliente,
      setProyCliente:e => this.setState({proyCliente:e.target.value, proyTip:null}),
      proyHs:(d.horizontes || []).map(hz => ({label:hz.label, onClick:() => this.setState({proyH:hz.meses, proyTip:null}), bg: s.proyH === hz.meses ? 'var(--surface)' : 'transparent', fg: s.proyH === hz.meses ? 'var(--text)' : 'var(--muted)', sh: s.proyH === hz.meses ? 'var(--shadow)' : 'none'})),
      proyKpis:d.kpis || [], proyChart:chart, proyHasTip:!!tr, proyTipD:tip, proyLeave:() => this.setState({proyTip:null}),
      proyCols:d.cols || [], proyRows:d.rows || [],
      proyEsc:(d.escenarios || []).map(e => { const act = s.proyEsc === e.clave; return Object.assign({}, e, {onClick:() => this.setState({proyEsc:e.clave, proyTip:null}), bd: act ? 'var(--accent)' : 'var(--border)', bg: act ? 'var(--accent-soft)' : 'var(--surface)', sh: act ? '0 0 0 3px var(--accent-soft)' : 'none', act}); }),
      proyAlertas:d.alertas || [], proyHayAlertas:!!(d.alertas && d.alertas.length), proyNivel:d.nivelGlobal ? 'Nivel ' + d.nivelGlobal : '',
      proySupuestos:d.supuestos || [], proyFuente:d.fuente || '', proyParametros:d.parametros || '',
      proyResumen:d.resumen || '', proyTablaNota:d.tablaNota || '', proyHasta:d.hasta || '',
      // Con el horizonte de 12 meses de un ejercicio ya cerrado no hay nada que proyectar: la zona
      // sombreada y la etiqueta «PROYECCIÓN» se ocultan en vez de quedar pegadas al borde.
      proyHayProyeccion: proy.length > 0 && corte > 0,
      proyVacio:!d.listo,
      proyAviso:'La plataforma no ha devuelto la proyección de este ejercicio: o no está leído del ERP o no tiene apuntes cargados.',
      proyCsv:() => this.exportProyCsv(d.rows || [], d.cols || [])
    };
  }

```

**Motivo** rvProy calculaba la proyección dentro del frontal (project/pyg/ESC) y maquetaba supuestos editables, un porcentaje de confianza y un aviso de «ajustado por» una persona. Ahora lee los números que ha dejado el traductor (`state.proyDatos`) y sólo dibuja: escala, trazos, tarjetas, tabla y textos.


### Parche 9

**Actual**

```
Cuenta de pérdidas y ganancias proyectada a partir del histórico contable · real hasta ago 26
```

**Propuesto**

```
{{ proyResumen }}
```

**Motivo** La pantalla decía «real hasta ago 26» con una fecha fija. El texto lo compone el traductor con el mes de corte y el ejercicio que devuelve el módulo.


### Parche 10

**Actual**

```
<button sc-camel-on-click="{{ proySave }}" style="height:36px;padding:0 14px;border:none;border-radius:6px;background:var(--btn);color:#fff;font-size:13px;font-weight:600;cursor:pointer;transition:background .2s ease;" style-hover="background:var(--btn-hover);">{{ proySaveLabel }}</button>
```

**Propuesto**

```
(se borra)
```

**Motivo** La plataforma no guarda escenarios propios del despacho: el botón desaparece (el traductor lo declara con ctx.sinDatos). Queda el selector de escenario y la exportación a CSV.


### Parche 11

**Actual**

```
<span style="font-family:'IBM Plex Mono',monospace;font-size:10px;">IA</span>{{ e.conf }}</span>
```

**Propuesto**

```
<span style="font-weight:600;">{{ e.factores }}</span>
```

**Motivo** El porcentaje de confianza (78/84/71 %) era inventado y la etiqueta «IA» no describe lo que hace la plataforma: se enseña el factor que aplica cada escenario (ingresos ×0,85 · gastos ×1,05).


### Parche 12

**Actual**

```
        <div style="font-weight:600;">Supuestos por partida</div>
        <div style="font-size:12px;color:var(--muted);margin-top:2px;">{{ proyEscLabel }}</div>
        <sc-if value="{{ proyNotEdited }}" hint-placeholder-val="{{ true }}"><div style="display:inline-flex;align-items:center;gap:5px;margin-top:6px;font-size:11px;font-weight:600;color:var(--ai);background:var(--ai-soft);border-radius:4px;padding:2px 7px;"><span style="font-family:'IBM Plex Mono',monospace;font-size:10px;">IA</span>Propuestos con el histórico de 36 meses · {{ proyConf }}</div></sc-if>
        <sc-if value="{{ proyEdited }}" hint-placeholder-val="{{ false }}"><div style="display:flex;align-items:center;gap:8px;margin-top:6px;"><span style="font-size:11px;font-weight:600;color:var(--ok);">✓ Ajustado por Javier Roldán</span><button sc-camel-on-click="{{ proyReset }}" style="border:none;background:transparent;color:var(--accent-strong);font-size:11px;cursor:pointer;padding:0;" style-hover="text-decoration:underline;">Restablecer</button></div></sc-if>
```

**Propuesto**

```
        <div style="font-weight:600;">Cómo proyecta la plataforma</div>
        <div style="font-size:12px;color:var(--muted);margin-top:2px;">{{ proyFuente }}</div>
        <div style="font-size:11px;color:var(--muted);margin-top:6px;">{{ proyParametros }}</div>
```

**Motivo** El panel anunciaba supuestos propuestos por «IA» con 36 meses de histórico y un ajuste firmado por una persona. Ahora dice de dónde salen las tendencias (ejercicios con apuntes) y con qué parámetros corre el informe.


### Parche 13

**Actual**

```
        <sc-for list="{{ proyParams }}" as="pm" hint-placeholder-count="5">
          <div style="padding:10px 0;border-bottom:1px dashed var(--border);">
            <div style="display:flex;justify-content:space-between;align-items:baseline;gap:8px;">
              <label for="{{ pm.id }}" style="font-weight:500;">{{ pm.l }}</label>
              <span style="font-weight:600;color:var(--accent-strong);min-width:64px;text-align:right;">{{ pm.val }}</span>
            </div>
            <div style="font-size:11px;color:var(--muted);margin-bottom:6px;">{{ pm.sub }}</div>
            <input id="{{ pm.id }}" type="range" min="{{ pm.min }}" max="{{ pm.max }}" step="{{ pm.step }}" value="{{ pm.v }}" sc-camel-on-change="{{ pm.onChange }}" style="width:100%;height:6px;border-radius:3px;appearance:none;-webkit-appearance:none;background:{{ pm.track }};accent-color:var(--accent);cursor:pointer;outline:none;" style-focus="box-shadow:0 0 0 3px var(--accent-soft);">
            <sc-if value="{{ pm.changed }}" hint-placeholder-val="{{ false }}"><div style="font-size:11px;color:var(--muted);margin-top:4px;animation:fadeIn .2s ease both;">{{ pm.defTxt }}</div></sc-if>
          </div>
        </sc-for>
```

**Propuesto**

```
        <sc-for list="{{ proySupuestos }}" as="sp" hint-placeholder-count="12">
          <div style="padding:10px 0;border-bottom:1px dashed var(--border);">
            <div style="display:flex;justify-content:space-between;align-items:baseline;gap:8px;">
              <span style="font-weight:500;">{{ sp.l }}</span>
              <span style="font-weight:600;color:var(--accent-strong);min-width:64px;text-align:right;">{{ sp.val }}</span>
            </div>
            <div style="font-size:11px;color:var(--muted);margin-top:2px;">{{ sp.sub }}</div>
            <div style="font-size:11px;font-weight:600;margin-top:3px;color:{{ sp.tendFg }};">{{ sp.tendTxt }}</div>
          </div>
        </sc-for>
```

**Motivo** Los cinco deslizadores (crecimiento de ventas, % de aprovisionamientos, personal, otros gastos y gastos financieros) eran una simulación del frontal: la plataforma no simula partida a partida, ajusta una regresión. Se sustituyen por el ajuste real (proyección, tasa, R², nº de ejercicios, fiabilidad) de cada magnitud.


### Parche 14

**Actual**

```
Banda: rango entre escenario conservador y optimista · hasta {{ proyHasta }}
```

**Propuesto**

```
Banda: escenarios conservador y optimista de la plataforma · proyectado hasta {{ proyHasta }}
```

**Motivo** La banda sigue existiendo, pero ahora son los escenarios de la plataforma, no el rango de un modelo del frontal.


### Parche 15

**Actual**

```
            <rect x="{{ proyChart.divX }}" y="{{ proyChart.pt }}" width="{{ proyChart.futW }}" height="{{ proyChart.ph }}" style="fill:var(--surface2);opacity:.6;"></rect>
            <path d="{{ proyChart.band }}" style="d:path('{{ proyChart.band }}');fill:var(--accent);opacity:.1;transition:d .5s cubic-bezier(.2,.8,.2,1);"></path>
            <line x1="{{ proyChart.divX }}" x2="{{ proyChart.divX }}" y1="{{ proyChart.pt }}" y2="{{ proyChart.bottom }}" style="stroke:var(--muted);" stroke-dasharray="3 3"></line>
            <text x="{{ proyChart.realLabelX }}" y="{{ proyChart.pt }}" dy="10" font-size="10" text-anchor="end" style="fill:var(--muted);font-weight:600;">REAL</text>
            <text x="{{ proyChart.divLabelX }}" y="{{ proyChart.pt }}" dy="10" font-size="10" style="fill:var(--ai);font-weight:600;">PROYECCIÓN</text>
```

**Propuesto**

```
            <sc-if value="{{ proyHayProyeccion }}" hint-placeholder-val="{{ false }}">
              <g>
                <rect x="{{ proyChart.divX }}" y="{{ proyChart.pt }}" width="{{ proyChart.futW }}" height="{{ proyChart.ph }}" style="fill:var(--surface2);opacity:.6;"></rect>
                <path d="{{ proyChart.band }}" style="d:path('{{ proyChart.band }}');fill:var(--accent);opacity:.1;transition:d .5s cubic-bezier(.2,.8,.2,1);"></path>
                <line x1="{{ proyChart.divX }}" x2="{{ proyChart.divX }}" y1="{{ proyChart.pt }}" y2="{{ proyChart.bottom }}" style="stroke:var(--muted);" stroke-dasharray="3 3"></line>
                <text x="{{ proyChart.realLabelX }}" y="{{ proyChart.pt }}" dy="10" font-size="10" text-anchor="end" style="fill:var(--muted);font-weight:600;">REAL</text>
                <text x="{{ proyChart.divLabelX }}" y="{{ proyChart.pt }}" dy="10" font-size="10" style="fill:var(--ai);font-weight:600;">PROYECCIÓN</text>
              </g>
            </sc-if>
```

**Motivo** Con el horizonte de 12 meses y el ejercicio ya cerrado no hay nada que proyectar: la zona sombreada, la raya y la etiqueta «PROYECCIÓN» quedarían pegadas al borde derecho sin enseñar nada. Se ocultan cuando no hay tramo proyectado.


### Parche 16

**Actual**

```
<div data-screen-label="Proyecciones" style="display:flex;flex-direction:column;gap:14px;animation:fadeInUp .35s ease both;">
```

**Propuesto**

```
<div data-screen-label="Proyecciones" style="display:flex;flex-direction:column;gap:14px;animation:fadeInUp .35s ease both;">
  <sc-if value="{{ proyVacio }}" hint-placeholder-val="{{ false }}"><div style="background:var(--surface2);border:1px dashed var(--border);border-radius:8px;padding:12px 14px;font-size:13px;color:var(--muted);">{{ proyAviso }}</div></sc-if>
```

**Motivo** Cuando el ejercicio no está leído del ERP (o el módulo no puede calcular la proyección) la pantalla se queda sin cifras: en vez de enseñar tarjetas y tablas vacías, se dice por qué.


### Parche 17

**Actual**

```
      <section style="background:var(--surface);border:1px solid var(--border);border-radius:8px;box-shadow:var(--shadow);overflow:hidden;">
        <div style="padding:12px 16px;border-bottom:1px solid var(--border);display:flex;justify-content:space-between;gap:8px;flex-wrap:wrap;"><strong>Cuenta de pérdidas y ganancias proyectada</strong><span style="font-size:12px;color:var(--muted);">Periodos de 12 meses desde sep 26 · importes en euros</span></div>
```

**Propuesto**

```
      <sc-if value="{{ proyHayAlertas }}" hint-placeholder-val="{{ false }}">
        <section style="background:var(--surface);border:1px solid var(--border);border-radius:8px;box-shadow:var(--shadow);padding:12px 16px;">
          <div style="display:flex;justify-content:space-between;align-items:baseline;gap:8px;margin-bottom:8px;">
            <strong style="font-size:14px;">Lo que la plataforma advierte de esta proyección</strong><span style="font-size:12px;color:var(--muted);">{{ proyNivel }}</span>
          </div>
          <sc-for list="{{ proyAlertas }}" as="al" hint-placeholder-count="3">
            <div style="display:flex;gap:8px;align-items:flex-start;background:{{ al.bg }};border:1px solid {{ al.bd }};border-radius:7px;padding:7px 11px;font-size:12px;margin-top:6px;">
              <span style="font-weight:600;color:{{ al.fg }};white-space:nowrap;">{{ al.n }}</span><span>{{ al.m }}</span>
            </div>
          </sc-for>
        </section>
      </sc-if>
      <section style="background:var(--surface);border:1px solid var(--border);border-radius:8px;box-shadow:var(--shadow);overflow:hidden;">
        <div style="padding:12px 16px;border-bottom:1px solid var(--border);display:flex;justify-content:space-between;gap:8px;flex-wrap:wrap;"><strong>Cuenta de pérdidas y ganancias proyectada</strong><span style="font-size:12px;color:var(--muted);">{{ proyTablaNota }}</span></div>
```

**Motivo** El módulo devuelve sus propias alertas (tendencia decreciente, escenario conservador en pérdidas, tesorería en tensión, ejercicio incompleto). Se enseñan en la pantalla, y la nota de la tabla deja de hablar de «periodos de 12 meses desde sep 26» (que era del modelo del frontal) para describir lo que es: un ejercicio por columna.


### Parche 18

**Actual**

```
DOCS: DOCS, ESC: ESC, PARAMS: PARAMS, DIAS14: DIAS14
```

**Propuesto**

```
DOCS: DOCS, DIAS14: DIAS14
```

**Motivo** El puente con datos.js entregaba ESC y PARAMS como datos del hub; al desaparecer esas constantes, la referencia deja de existir. (SEAS_RAW, SEAS y NOISE se quedan: la pantalla de Informe todavía los usa.)



## Parche condicionado (no incluido arriba)

`MES_C`, `SEAS_RAW`, `SEAS` y `NOISE` **no** se pueden borrar desde aquí: la pantalla de Informe
(`rvInf`, gráfico «real frente a presupuesto») todavía usa `SEAS` y `NOISE` para inventarse el
reparto mensual. Cuando esa pantalla se traduzca (su traductor debe usar `factorEstacionalIngresos` o
las series del módulo que le toque), estos cuatro se pueden ir con ella:

- `SEAS_RAW` / `SEAS` / `NOISE`: borrar las tres constantes y su entrada en el puente
  `window.ABGA_HUB` (`NOISE: NOISE, SEAS_RAW: SEAS_RAW,`).
- `MES_C`: usado por `rvInf` y por el informe; se queda hasta que esa pantalla cambie.

## Verificación hecha

- `node --check frontend/hub/pantallas/proyecciones.js` → OK.
- Traductor ejecutado en node con la salida real del módulo por API para `6091/2025` (ejercicio
  cerrado: `mesCorte 12`), `6091/2026` (en curso: `mesCorte 9`, `esParcial true`, 3 meses
  proyectados) y `6172/2025`: 24 columnas de gráfico, 4 indicadores, 3 escenarios, 12 filas de tabla
  y 12 tendencias en los tres casos, y las formas cuadran (`cols` = celdas de cada fila, `raw` =
  columnas).
- Casos límite: sin caché, informe que falla, `disponible: false` y respuesta vacía → `proyDatos:
  null`, un solo `ctx.sinDatos` y `ctx.pedirDelErp` sólo cuando falta el ejercicio en caché.
- `rvProy` propuesto ejecutado contra esos datos: los trazos (`pReal`, `pProj`, `eReal`, `eProj`,
  `banda`) salen bien formados, sin `NaN`, con la raya de «hasta aquí lo contabilizado» en el mes de
  corte y la banda arrancando en el último mes real.
- Los 18 parches aplicados sobre una copia: `node --check` del script del hub OK y cero referencias
  al modelo viejo.
- Todo lo anterior sin tocar el ERP: el informe `proyecciones` de `6091` y `6172` sale de caché
  (entre 0,3 y 0,8 s, `desde_cache: true`).

## Dos cosas a tener en cuenta al mantenerlo

- El módulo trabaja con **cuatro ejercicios** (`DESPLAZAMIENTOS [0,-1,-2,-3]`): el informe usa los
  que estén en caché y, si falta alguno, el servicio puede ir al ERP a leerlo. Por eso la pantalla
  sólo pide el informe cuando `ctx.hayCache()` es cierto, igual que Inicio.
- `mesEnCurso` trae también `tesoreria`, `deudores` y `proveedores` mes a mes, y el módulo publica
  `trimestralProyectado`, `cierreEstimadoAnioEnCurso` y `tesoreriaProyectada`. Esta pantalla no los
  pinta (el gráfico del hub es de ingresos y EBITDA); están ahí si se quieren aprovechar sin pedir
  nada nuevo.
