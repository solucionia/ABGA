# Duplicados de facturas y conciliación de mayores · datos reales

Este documento acompaña a los dos traductores de datos que faltaban para estas pantallas:

    frontend/hub/pantallas/duplicados.js      módulo `duplicados`   (informe INTERNO de ABGA)
    frontend/hub/pantallas/conciliacion.js    módulo `conciliacion`

Los dos siguen el mismo contrato que `pantallas/inicio.js`: se registran con `ABGA.registrar`,
reciben el `ctx` de `datos.js`, dejan los datos del hub con la forma que él ya usaba (`ctx.poner`),
y lo que la plataforma no sabe se declara con `ctx.sinDatos`, nunca se rellena con cifras
inventadas. Ninguno de los dos toca la API por su cuenta salvo el informe del módulo.

Lo que dejan en el hub:

| Pantalla | `ctx.poner` | `ctx.parchear` |
|---|---|---|
| Duplicados | `DUPS` (una entrada por par de asientos) | `dups`, `dupTab`, `dupSelId`, `dupLeaving`, `modal`, `dupsResumen`, `dupsEscala` |
| Conciliación | `CUENTAS` (opción «Todas», una por cuenta y una por tercero) | `concCliente`, `concCuenta`, `concStatus`, `concRows`, `concFilter`, `concResumen` |

Además, conciliación deja las filas a mano del hub en `window.ABGA_CONC`, con la clave
`«empresa|cuenta»` (y `«empresa|»` para «Todas»): es lo que hace falta para que el selector de
cuenta pueda pedir sus filas en vez de generarlas (parche A.2).

Sin los parches de este documento la pantalla **pinta datos de ejemplo** en cuanto se toca el
selector de cuenta (el `genRows()` del hub los fabrica) y afirma cosas que la plataforma no hace
(extracto bancario, propuesta de casación de la IA, porcentaje de similitud, NIF, IVA). Los
traductores, por sí solos, ya dejan los datos reales en pantalla cuando se entra en la pantalla; los
parches son para que lo que se lee alrededor de esos datos sea verdad.

---

## A. Parches en `frontend/hub/index.html`

### A.1 · Cargar los dos ficheros nuevos

**Actual**

```html
<script src="pantallas/inicio.js"></script>
<script src="pantallas/envios.js"></script>
```

**Propuesto**

```html
<script src="pantallas/inicio.js"></script>
<script src="pantallas/envios.js"></script>
<script src="pantallas/duplicados.js"></script>
<script src="pantallas/conciliacion.js"></script>
```

**Motivo:** los traductores no se ejecutan si la página no los carga. Van después de `datos.js`,
como `inicio.js`.

### A.2 · `loadConc()`: las partidas las trae la plataforma, no `genRows()`

**Actual**

```js
  loadConc(cliente, cuenta, retry){
    this.setState({concCliente:cliente, concCuenta:cuenta, concStatus:'loading', concFilter:'todas'});
    clearTimeout(this._concT);
    this._concT = setTimeout(() => {
      const c = CUENTAS.find(x => x.cod === cuenta);
      if (c.tipo === 'vacia') return this.setState({concStatus:'empty', concRows:[]});
      if (c.tipo === 'error' && !retry) return this.setState({concStatus:'error', concRows:[]});
      this.setState({concStatus:'ready', concRows:genRows(cliente, c.tipo === 'error' ? '572.0001' : cuenta, this.state.ejercicio)});
    }, 750);
  }
```

**Propuesto**

```js
  loadConc(cliente, cuenta, retry){
    this.setState({concCliente:cliente, concCuenta:cuenta, concStatus:'loading', concFilter:'todas'});
    clearTimeout(this._concT);
    this._concT = setTimeout(() => {
      // Las filas las trae la capa de datos (window.ABGA_CONC, clave «empresa|cuenta»): el hub ya no
      // fabrica apuntes ni movimientos de extracto. Sin filas para esa cuenta, la pantalla lo dice.
      const filas = ((window.ABGA_CONC || {})[cliente + '|' + cuenta] || []);
      this.setState({concStatus: filas.length ? 'ready' : 'empty', concRows: filas.map(r => ({...r}))});
    }, 250);
  }
```

**Motivo:** es el único camino por el que el selector de cuenta y el de cliente cambian lo que se
ve. Sin esto, elegir otra cuenta genera apuntes y extractos de ejemplo (`P_BANCO`, `P_CLI`,
`P_PROV` con `genRows()`), que es justo lo que no puede aparecer. Con el parche, la cuenta elegida
se busca en las filas reales que dejó el traductor.

### A.3 · Estado inicial: ni apuntes ni parejas de ejemplo

**Actual**

```js
concCliente:'C001', concCuenta:'572.0001', concStatus:'ready', concRows:genRows('C001','572.0001','2026'), concFilter:'todas', concRetry:0,
      dups:DUPS.map(d => ({...d, estado:'pendiente'})), dupTab:'pendiente', dupSelId:'D1', dupLeaving:null, modal:null,
```

**Propuesto**

```js
concCliente:'C001', concCuenta:'572.0001', concStatus:'loading', concRows:[], concFilter:'todas', concRetry:0,
      dups:[], dupTab:'pendiente', dupSelId:null, dupLeaving:null, modal:null,
```

**Motivo:** con el estado inicial de ejemplo, el hub pinta durante un instante cuentas, apuntes y
parejas que no existen (y el contador de duplicados del menú). Ojo con `concCuenta`: `rvConc()` se
calcula en **todos** los renders (`rvAll`), no sólo al abrir la pantalla, y hace
`CUENTAS.find(c => c.cod === s.concCuenta).nombre`. Por eso aquí se deja un código que existe en el
`CUENTAS` de ejemplo: si se dejara `''` antes de que el traductor sustituya `CUENTAS`, la pantalla
fallaría al montar. El traductor siempre deja un `CUENTAS` que contiene el `concCuenta` que pone.

### A.4 · El contador del menú

**Actual**

```js
    const badges = {conciliacion:12, duplicados:pendDup, memoria:s.caStep < 4 ? 1 : 0};
```

**Propuesto**

```js
    const badges = {conciliacion:(s.concResumen ? s.concResumen.cuentasPendientes : 0), duplicados:pendDup, memoria:s.caStep < 4 ? 1 : 0};
```

**Motivo:** el 12 era un número escrito a mano. El contador real está en `concResumen`
(`n_cuentas_pendientes` del informe: 406 en el ejercicio de 6091).

### A.5 · Texto del encabezado de duplicados

**Actual**

```html
Parejas sospechosas detectadas por la IA en facturas recibidas · criterios: NIF, importe, fecha, nº de factura y concepto
```

**Propuesto**

```html
Pares de asientos con coincidencias, detectados por el módulo de duplicados · criterios: importe, cuentas, fecha, tercero, documento y descripción
```

**Motivo:** el informe no es de la IA: es el módulo `duplicados` con sus índices y su puntuación (y
se calcula cuando se pide, no solo). Y los criterios reales son los suyos: importe, cuentas, fecha
(igual o próxima), proveedor, cliente, descripción (idéntica o similar) y documento. Ni NIF ni
número de factura ni IVA.

### A.6 · La puntuación del módulo no es un porcentaje

**Actual**

```js
score:d.score + ' %', scoreFg: d.score >= 90 ? 'var(--err)' : d.score >= 80 ? 'var(--warn)' : 'var(--muted)', scoreBg: d.score >= 90 ? 'var(--err-soft)' : d.score >= 80 ? 'var(--warn-soft)' : 'var(--surface2)',
```

**Propuesto**

```js
score:d.score + ' ptos', scoreFg: d.gravedad === 'ALTA' ? 'var(--err)' : d.gravedad === 'MEDIA' ? 'var(--warn)' : 'var(--muted)', scoreBg: d.gravedad === 'ALTA' ? 'var(--err-soft)' : d.gravedad === 'MEDIA' ? 'var(--warn-soft)' : 'var(--surface2)',
```

**Motivo:** `score` son los puntos del módulo (11, 12...). Con los umbrales del diseño (90 / 80 %)
todos los pares salían en gris con un «11 %» que no significa nada. La gravedad real viene en el
informe: `ALTA` (≥ 8 puntos), `MEDIA`, `BAJA`.

### A.7 · La barra de similitud del detalle: `scoreW`

**Actual**

```js
scoreW:d.score + '%', scoreFg: d.score >= 90 ? 'var(--err)' : d.score >= 80 ? 'var(--warn)' : 'var(--muted)', coincidenTxt:d.coinciden.length + ' de 5 criterios coinciden',
```

**Propuesto**

```js
scoreW:Math.round(Math.min(1, d.score / (s.dupsEscala ? s.dupsEscala.max : 14)) * 100) + '%', scoreFg: d.gravedad === 'ALTA' ? 'var(--err)' : d.gravedad === 'MEDIA' ? 'var(--warn)' : 'var(--muted)', coincidenTxt:d.criterios.length + ' de los 8 criterios que compara el módulo',
```

**Motivo:** con los puntos a secas, `width:11%` deja la barra casi vacía. La escala real del módulo
está en el estado (`dupsEscala.max` = 14 puntos: importe 3 + cuentas 2 + misma fecha 3 + proveedor 2
+ cliente 2 + descripción idéntica 2). El «de 5 criterios» también era fijo: los criterios que
compara el módulo son 8 (`d.criterios`, los del informe tal cual), y los que se pueden marcar campo
a campo son los de `d.coinciden`.

### A.8 · Filas de comparación: sin NIF ni IVA, con el importe del asiento

**Actual**

```js
    const fields = [
      ['NIF proveedor', d.nif, d.nif, 'nif'], ['Nº de factura', d.a.num, d.b.num, 'num'], ['Fecha', d.a.fecha, d.b.fecha, 'fecha'],
      ['Base imponible', eur(d.a.base), eur(d.b.base), 'importe'], ['IVA', d.a.iva + ' % · ' + eur(d.a.base * d.a.iva / 100), d.b.iva + ' % · ' + eur(d.b.base * d.b.iva / 100), 'importe'],
      ['Total', eur(tot(d.a)), eur(tot(d.b)), 'importe'], ['Concepto', d.a.concepto, d.b.concepto, 'concepto'], ['Asiento', d.a.asiento, d.b.asiento, null]
```

**Propuesto**

```js
    const fields = [
      ['Documento', d.a.num, d.b.num, 'num'], ['Fecha', d.a.fecha, d.b.fecha, 'fecha'],
      ['Importe del asiento', eur(d.a.base), eur(d.b.base), 'importe'],
      ['Concepto', d.a.concepto, d.b.concepto, 'concepto'], ['Asiento', d.a.asiento, d.b.asiento, null]
```

**Motivo:** el informe no trae NIF ni desglose de base e IVA: da el importe del asiento. Las filas
«NIF proveedor» y «IVA» salían vacías («0 % · 0,00 €») y «Base imponible» y «Total» repetían la
misma cifra. Se dejan las cinco filas que sí tienen dato real. (`d.a.num` es el número de documento
del asiento, no el de la factura: por eso la fila se llama «Documento».)

### A.9 · El NIF del titular, en el detalle

**Actual**

```html
<span style="font-family:'IBM Plex Mono',monospace;">{{ dupSel.nif }}</span> · {{ dupSel.cliente }}
```

y, en el modelo:

```js
dupSel:{proveedor:d.proveedor, nif:d.nif, cliente:cli(d.cli).nombre,
```

**Propuesto**

```html
<span style="font-family:'IBM Plex Mono',monospace;">{{ dupSel.documentos }}</span> · {{ dupSel.cliente }}
```

y, en el modelo:

```js
dupSel:{proveedor:d.proveedor, documentos:d.documentos, cliente:cli(d.cli).nombre,
```

**Motivo:** la API no da el NIF. `d.documentos` («122 / 123») sí es real y sitúa la pareja.

### A.10 · La fila «Registro»

**Actual**

```html
<div style="padding:9px 16px;">Registro</div><div style="padding:9px 12px;">{{ dupSel.regA }}</div><div style="padding:9px 12px;border-left:1px solid var(--border);">{{ dupSel.regB }}</div>
```

**Propuesto**

```html
<div style="padding:9px 16px;">Registro</div><div style="padding:9px 12px;">La plataforma no guarda quién ni cuándo se registró el asiento</div><div style="padding:9px 12px;border-left:1px solid var(--border);">{{ dupSel.cliente }}</div>
```

**Motivo:** el «Registrada por IA · 05/09/2026» no existe: el ERP no trae el autor ni la fecha de
registro. Se dice en la propia fila en vez de dejarla en blanco.

### A.11 · «Ver original» y el modal del documento

**Actual**

```html
<button sc-camel-on-click="{{ verOriginalA }}" style="border:none;background:transparent;color:var(--accent-strong);font-size:12px;cursor:pointer;padding:0;" style-hover="text-decoration:underline;">Ver original</button>
```

**Propuesto**

```html
<span style="font-size:12px;color:var(--muted);">Sin documento en la plataforma</span>
```

**Motivo:** «Ver original» abre un modal de «documento original» que la plataforma no tiene: no hay
escaneo de facturas ni OCR en la API. El botón promete algo que no puede enseñar.

**Actual** (y el mismo cambio en `verOriginalB`)

```js
verOriginalA:() => this.setState({modal:doc(d.a, 'Factura A')}), verOriginalB:() => this.setState({modal:doc(d.b, 'Factura B')}),
```

**Propuesto** (si se prefiere dejar el modal para enseñar el asiento)

```js
verOriginalA:() => this.setState({modal:doc(d.a, 'Asiento A')}), verOriginalB:() => this.setState({modal:doc(d.b, 'Asiento B')}),
```

**Motivo:** al menos que el modal diga la verdad (enseña el asiento, no la factura escaneada).

### A.12 · Dentro del modal: NIF e IVA

**Actual**

```html
<div style="font-size:12px;color:#5b6b80;">NIF {{ modal.nif }}</div>
```

**Propuesto**

```html
<div style="font-size:12px;color:#5b6b80;">Asiento {{ modal.asiento }}</div>
```

**Actual**

```html
<span style="color:#5b6b80;">{{ modal.ivaTxt }}</span><span style="text-align:right;color:#5b6b80;">{{ modal.iva }}</span>
```

**Propuesto**

```html
<span style="color:#5b6b80;">Importe del asiento</span><span style="text-align:right;color:#5b6b80;">{{ modal.total }}</span>
```

**Motivo:** ni NIF ni IVA existen en el informe; el importe del asiento sí.

### A.13 · «Marcada como duplicada · asiento … anulado»

**Actual**

```js
estadoTxt: d.estado === 'duplicada' ? 'Marcada como duplicada · asiento ' + d.b.asiento + ' anulado' : 'Marcada como no duplicada'
```

**Propuesto**

```js
estadoTxt: d.estado === 'duplicada' ? 'Marcada como duplicada desde el hub (no se ha anulado ningún asiento en la contabilidad)' : 'Marcada como no duplicada'
```

**Motivo:** marcar en el hub es una anotación de la bandeja, en memoria. La plataforma no anula
asientos en el ERP: afirmarlo es falso.

### A.14 · «La IA seguirá analizando las facturas nuevas cada hora»

**Actual**

```js
dupEmptyTxt: s.dupTab === 'pendiente' ? 'No hay parejas pendientes de revisar. La IA seguirá analizando las facturas nuevas cada hora.' : 'Todavía no hay facturas en este estado.'
```

**Propuesto**

```js
dupEmptyTxt: s.dupTab === 'pendiente' ? (s.dupsResumen && s.dupsResumen.avisos && s.dupsResumen.avisos.length ? s.dupsResumen.avisos[0] : 'No hay parejas que revisar en este ejercicio.') : 'Todavía no hay facturas en este estado.'
```

**Motivo:** no hay análisis continuo: el informe se calcula cuando se pide. Este texto es justo el
que se lee cuando la pantalla está vacía por falta de datos (usuario de cliente o ejercicio sin
leer), así que la frase hacía pensar que la plataforma seguía trabajando en ello.

### A.15 · «Importe en riesgo» del encabezado

**Actual**

```js
      dupPend:pend.length, dupRiesgo:eur(pend.reduce((a, x) => a + x.b.base * (1 + x.b.iva / 100), 0)), dupHasSel:!!d, dupNoSel:!d,
```

**Propuesto**

```js
      dupPend:pend.length, dupRiesgo:eur(s.dupsResumen ? s.dupsResumen.importeRiesgoTotal : 0), dupHasSel:!!d, dupNoSel:!d,
```

**Motivo:** sumar la cara B de cada pareja no es el importe en riesgo del informe. En 6091/2025 la
suma del hub daba 114.689,67 € y el informe dice 114.689,65 € (`importeRiesgoTotal`, el menor de
los dos importes de cada par). Con `dupsResumen` la cifra es la del informe.

### A.16 · Contador de pendientes: «N de M»

**Actual**

```html
<div style="font-size:11px;color:var(--muted);text-transform:uppercase;letter-spacing:.05em;font-weight:600;">Pendientes</div><div style="font-size:18px;font-weight:600;">{{ dupPend }}</div>
```

**Propuesto**

```html
<div style="font-size:11px;color:var(--muted);text-transform:uppercase;letter-spacing:.05em;font-weight:600;">Pendientes</div><div style="font-size:18px;font-weight:600;">{{ dupPend }} de {{ dupTotal }}</div>
```

**Motivo:** opcional, sólo si se quiere dejar claro el recorte del informe. El traductor pide
`max_filas: 200` para que vengan todos (104 en 6091/2025), así que hoy `dupPend` ya es el total;
pero si algún día el informe devuelve menos, el estado trae `dupsResumen.total`. Si se aplica, hay
que añadir `dupTotal:(s.dupsResumen ? s.dupsResumen.total : 0),` al objeto que devuelve `rvDup`.

### A.17 · Texto del encabezado de conciliación

**Actual**

```html
Mayor contable frente a extracto o contrapartida · la IA propone el casado, una persona lo valida</div>
```

**Propuesto**

```html
Punteo del ejercicio: cuentas y terceros con partidas sin puntear · la plataforma no tiene extracto bancario ni propone casaciones</div>
```

**Motivo:** no hay extracto, no hay propuesta automática y no hay validación. Lo que sí hay es el
punteo contable del módulo `conciliacion`.

### A.18 · «Extracto leído del ERP a las 10:42 · Norma 43»

**Actual**

```js
      concUltima:'Extracto leído del ERP a las 10:42 · ' + (cuenta.tipo === 'cli' || cuenta.tipo === 'prov' ? 'contrapartidas de tesorería' : 'Norma 43')
```

**Propuesto**

```js
      concUltima:(s.concResumen
        ? ('Corte ' + s.concResumen.corte + ' · ' + s.concResumen.pendientes + ' de ' + s.concResumen.partidas + ' partidas sin puntear · ' + (s.concResumen.marcaBancaria ? 'con punteo bancario' : 'el ERP no trae punteo bancario'))
        : 'Sin datos del ejercicio')
```

**Motivo:** la hora y el «Norma 43» eran inventados. Con `concResumen` se dice la fecha de corte
real y el punteo real: en 6091/2025, 4.790 de 4.790 partidas sin puntear y 0 marcas bancarias. Ese
es el motivo por el que la pantalla aparece entera en rojo, y hoy no se explica en ninguna parte.

### A.19 · Las cuatro tarjetas del resumen

Son cuatro etiquetas del mismo bloque. Cada una, por separado:

**Actual / Propuesto**

| Actual | Propuesto |
|---|---|
| `>Saldo mayor<` | `>Pendiente de las cuentas mostradas<` |
| `>Saldo extracto / contrapartida<` | `>Sin extracto bancario (la plataforma no lo tiene)<` |
| `>Diferencia</div>` | `>No calculable sin extracto</div>` |
| `>Partidas cuadradas<` | `>Cuentas sin partidas pendientes<` |

**Motivo:** las tres primeras son la comparación con un extracto que no existe. Con los datos
reales: «Saldo mayor» es la suma del pendiente de las cuentas que se muestran (640.455,71 € en
6091), «Saldo extracto» es siempre 0,00 € y «Diferencia» repite la primera cifra, lo que hace pensar
en un descuadre que no es tal. La cuarta cuenta cuentas, no partidas. (`Diferencia` lleva su
contexto porque el mismo texto está también en la cabecera de la tabla, que no se toca.)

### A.20 · Filtros de la tabla: dos estados no existen

**Actual**

```js
    const filters = [['todas','Todas'],['cuadrada','Cuadradas'],['diferencia','Diferencias'],['sin_casar','Sin casar']].map((
```

**Propuesto**

```js
    const filters = [['todas','Todas'],['sin_casar','Con partidas pendientes'],['cuadrada','Sin partidas pendientes']].map((
```

**Motivo:** «Diferencia» necesita un extracto con el que comparar, y no lo hay: ese filtro sale
siempre a 0. «Cuadradas» en el sentido del diseño (partida casada) tampoco: lo que hay es cuentas
sin partidas pendientes, y con el punteo que exporta hoy el ERP no hay ninguna.

### A.21 · Cabecera de columna «Extracto / contrapartida»

**Actual**

```html
<span>Extracto / contrapartida</span>
```

**Propuesto**

```html
<span>Extracto / contrapartida (no disponible)</span>
```

**Motivo:** la columna se queda vacía en todas las filas porque la plataforma no tiene extractos.

### A.22 · «Sin movimiento casado»

**Actual**

```html
<span style="font-size:12px;color:var(--muted);font-style:italic;">Sin movimiento casado</span>
```

**Propuesto**

```html
<span style="font-size:12px;color:var(--muted);font-style:italic;">Sin extracto con el que casar</span>
```

**Motivo:** «sin movimiento casado» suena a que el casado se ha intentado y no ha salido; lo cierto
es que la plataforma no tiene los movimientos del banco.

### A.23 · «As. » delante del número

**Actual**

```js
mAsiento:r.mayor ? 'As. ' + r.mayor.asiento : '',
```

**Propuesto**

```js
mAsiento:r.mayor ? r.mayor.asiento : '',
```

**Motivo:** en la fila del mayor, `asiento` no es un asiento: es la cuenta (o las cuentas del
tercero). «As. 700000000003» confunde. Con el prefijo fuera, se lee «700000000003 · Ingresos · 66 de
66 partidas sin puntear».

### A.24 · Texto de carga

**Actual**

```html
Leyendo apuntes y extracto desde el ERP…</div>
```

**Propuesto**

```html
Leyendo el punteo del ejercicio desde la plataforma…</div>
```

**Motivo:** no se lee ningún extracto. (Con el parche A.2 este estado apenas se ve: las filas ya
están cargadas.)

### A.25 · Bloque de error: el 503 de CaixaBank es de ejemplo

**Actual**

```html
>No se ha podido leer el extracto</div>
        <div style="color:var(--muted);margin:6px auto 16px;max-width:460px;">La API del ERP ha respondido con un error 503 al solicitar los movimientos de CaixaBank. Los datos del mayor no se han modificado.</div>
```

**Propuesto**

```html
>No se ha podido calcular la conciliación</div>
        <div style="color:var(--muted);margin:6px auto 16px;max-width:460px;">El informe de conciliación ha fallado. Los datos que ya había en pantalla no se han modificado.</div>
```

**Motivo:** el 503 y CaixaBank eran del ejemplo. Este bloque sale cuando el informe falla de verdad
(estado `error`), y ahí el usuario necesita el motivo, no una historia.

### A.26 · Bloque vacío: «Sin movimientos en esta cuenta»

**Actual**

```html
>Sin movimientos en esta cuenta</div>
        <div style="color:var(--muted);margin-top:6px;">No hay apuntes ni movimientos bancarios en el ejercicio {{ ejercicio }} para la cuenta seleccionada.</div>
```

**Propuesto**

```html
>Sin datos en esta cuenta</div>
        <div style="color:var(--muted);margin-top:6px;">No hay datos de la cuenta seleccionada en el ejercicio {{ ejercicio }}: o no está leída de la plataforma, o no tiene partidas pendientes.</div>
```

**Motivo:** este bloque es el que se ve cuando el ejercicio no está leído y cuando la cuenta
seleccionada no tiene filas. Decir «no hay apuntes ni movimientos bancarios» cuando en realidad no
se ha leído el ejercicio es lo único que faltaba para que la pantalla mintiera. (Si se aplica A.2,
la lista de cuentas sólo ofrece las que tienen datos, así que el bloque aparece sobre todo por lo
primero.)

### A.27 · Botón «Aceptar N sugerencias con confianza ≥ 90 %»

**Actual**

```html
>Aceptar {{ altaCount }} sugerencias con confianza ≥ 90 %</button>
```

**Propuesto**

```html
>Ver las {{ altaCount }} cuentas de mayor riesgo</button>
```

**Motivo:** no hay sugerencias que aceptar ni confianza que medir. `altaCount` se calcula como las
filas con propuesta de confianza ≥ 90: con los datos reales siempre es 0, así que el botón no se
pinta (`hasAlta` falso) y el parche sólo importa si algún día se enseña otra cosa ahí. Si se deja
tal cual, no molesta: no aparece.

### A.28 · «Sin propuesta de la IA · casar manualmente»

**Actual**

```js
        noSugOpen: r.estado === 'sin_casar' && !r.sug, noSugTxt: r.rechazada ? 'Sugerencia rechazada · casar manualmente' : 'Sin propuesta de la IA · casar manualmente',
```

**Propuesto**

```js
        noSugOpen: r.estado === 'sin_casar' && !r.sug, noSugTxt: 'Partidas sin puntear · la plataforma no propone casaciones',
```

**Motivo:** con los datos reales esta línea sale en **todas** las filas, así que es la frase que más
se lee de la pantalla, y afirma que hay una IA que propone casaciones cuando no la hay.

### A.29 · (Opcional) Ver los hallazgos del informe

El módulo devuelve 25 hallazgos (59 en 6091/2025 con `hallazgos_recuento`: 47 asientos duplicados y
12 clientes con saldo contrario) y la pantalla no tiene dónde pintarlos. Están en
`concResumen.listaHallazgos`. Si se quieren enseñar, el sitio natural es una sección detrás de la
tabla, con los campos reales de cada hallazgo: `tipo`, `nivel`, `cuenta`, `fecha` (formato
`AAAAMMDD`), `documento`, `importe` y `descripcion`.

---

## B. Parche en `frontend/hub/datos.js`

### B.1 · Los parámetros del informe viajan en `params`, no en `parametros`

**Actual**

```js
        parametros: parametros || undefined
```

**Propuesto**

```js
        params: parametros || undefined
```

**Motivo:** la API (`PeticionInforme`) espera `params` y rechaza lo que no conoce
(`extra='forbid'`): con `parametros` responde **422** («Extra inputs are not permitted: parametros»)
y el informe no se calcula. En los dos traductores se ha evitado el problema llamando al cliente
HTTP directamente con `params` (función `informeConParametros`), porque hace falta pedir
`max_filas: 200` en duplicados y `top_cuentas: 25, top_terceros: 15` en conciliación. Cuando este
parche esté hecho, esas llamadas se pueden sustituir por `ctx.informe(modulo, parametros)` y quitar
el apoyo de los dos ficheros.

Comprobado contra la plataforma levantada en el puerto 8011:

    POST /api/informe {"modulo":"conciliacion","cod_empresa":"6091","year":2025,"parametros":{...}} → 422
    POST /api/informe {"modulo":"conciliacion","cod_empresa":"6091","year":2025,"params":{"top_cuentas":20}} → 200, 20 cuentas

---

## C. Lo que el diseño afirma y la plataforma no hace

Resumen de lo que se declara con `ctx.sinDatos` en cada pantalla (y que los parches de arriba
quitan de la vista):

| Lo que dice el diseño | Lo que hay |
|---|---|
| Detección por IA, análisis continuo, «la IA seguirá analizando» | módulo `duplicados` con índices y puntuación; se calcula cuando se pide |
| «Similitud 98 %» con umbrales 90 / 80 % | puntuación del módulo en puntos (umbral 11, ALTA desde 8, máximo 14) |
| NIF del proveedor y del cliente | no viene en el informe |
| Nº de factura, base imponible, IVA, «total factura» | el informe identifica asientos y documentos contables y da el importe del asiento |
| «Registrada por IA · 05/09/2026», «Ver original», documento original | la plataforma no guarda el registro del asiento ni tiene el escaneo de la factura |
| «Marcada como duplicada · asiento X anulado» | marcar es una anotación del hub; no se anula nada en la contabilidad |
| Extracto bancario, Norma 43, contrapartidas de tesorería | la plataforma no tiene extractos: sólo punteo contable |
| Propuesta de casación con «confianza 96 %», aceptar / rechazar | no existe ninguna propuesta automática |
| «Validado · [nombre]», «IA 97 %» | no hay validaciones guardadas |
| «Diferencia» mayor − extracto, estado «Diferencia» | sin extracto no hay diferencia que calcular |
| «Partidas cuadradas 62 %» | con el punteo que exporta el ERP no hay ni una partida punteada; el 0 % es real y hay que explicarlo |

---

## D. Cómo comprobarlo

    cd /home/pedro/.hermes/profiles/abga/workspace/abga/nuevo
    node --check frontend/hub/pantallas/duplicados.js
    node --check frontend/hub/pantallas/conciliacion.js
    ./.venv/bin/python backend/scripts/probe_api_hub.py 8011 6091 2025     # la forma real de cada informe

Los dos traductores se han ejecutado contra las respuestas reales de la plataforma (6091/2025 y
6172/2025, los dos únicos ejercicios en caché) y, con el resultado ya en el `state`, se han pintado
con las propias funciones `rvDup()` y `rvConc()` del hub: no fallan y las filas llevan los datos del
informe (104 pares y 114.689,65 € de riesgo en 6091; 40 filas de cuentas y terceros con partidas sin
puntear y 0 % de cuentas sin pendiente). Ninguna de las dos pantallas pide un ejercicio que no esté
en caché: si no lo está, se ofrece traerlo con `ctx.pedirDelErp`.

### Aviso sobre el resto de pantallas

`pantallas/inicio.js` traduce las mismas parejas de duplicados para su lista de tareas y el
indicador del resumen, con su propio mapeo (`criterios` sin traducir a las claves de la pantalla, el
`coinciden` sin marcar). Si se quiere una sola traducción, el traductor nuevo se puede usar como
referencia para dejar `inicio.js` con el mismo `coinciden` (los criterios traducidos) y el mismo
`score` en puntos.
