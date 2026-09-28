# Cuentas anuales · de dónde salen los datos y qué parchear en `index.html`

Traductor: `frontend/hub/pantallas/cuentas-anuales.js`, registrado como
`ABGA.registrar('memoria', ...)` (la pantalla del hub se llama `memoria`: `sCA: s.screen === 'memoria'`).
Las líneas que se citan son de `index.html` en el momento de escribir esto: pueden moverse si se
editan otras partes del fichero, así que el fragmento manda sobre el número.

## Qué alimenta la pantalla

Todo sale del módulo **`memoria`** de la plataforma (`POST /api/informe` con `modulo: 'memoria'`). No
hay ningún otro endpoint para esta pantalla. La respuesta trae `data` (cifras y comprobaciones),
`html` (la memoria completa ya redactada, unos 66.000 caracteres) y `meta` (`desde_cache`,
`segundos`, `ejercicios`, `faltantes`).

| Dato del hub | De dónde sale |
|---|---|
| `CA_DATOS` | lo que el módulo declara haber leído: `nLineas`, `integridad.cuadre`, `resultadoNeto`, `totalInmovilizado`, `amortizacionAcumulada`, `exigible`, `nLineasAnterior`. Lo que no consta en el ERP va marcado `ok:false` (plantilla media, reparto de vencimientos, amortización acumulada) |
| `CA_BAL` | `activoNoCorriente`, `activoCorriente`, `totalActivo`, `patrimonioNeto`, `deudasLP`, `pasivoCorriente`, `ventas`, `ebit`, `resultadoNeto`; la columna del año anterior sólo con `totalActivoAnt`, `patrimonioNetoAnt`, `pasivoCorrienteAnt`, `ventasAnt`, `ebitAnt`, `resultadoNetoAnt`, y **sólo si hay apuntes del año anterior** (si no, `null`) |
| `CA_NOTAS` | las **10 notas del PGC de PYMES** que el módulo redacta dentro del `html`. Se recortan por sus encabezados `Nota N · Título`; el texto de cada nota es esa nota aplanada a texto plano, sin las tablas de cifras (esas se leen en el informe). **No hay `conf`**: el módulo no puntúa las notas |
| `CA_CAMBIOS` | **vacío**: la plataforma no compara con la memoria del ejercicio anterior ni propone cambios de texto |
| `caChecksDatos` (estado) | las comprobaciones reales: `integridad.cuadre`, activo = patrimonio neto + pasivo exigible, número de notas, `integridad.saldosContrarios`, `integridad.gruposSinMovimiento`, apuntes de los dos ejercicios |
| `caAvisos` (estado) | `data.avisos` (13 avisos en las empresas de prueba): lo que el ERP no puede dar y el módulo deja declarado |

Parámetros que se mandan al módulo: **sólo `localidad`**, con la ciudad del catálogo de empresas del
hub (`ctx.MOCK.CLIENTES`). Sin ella el módulo usaría «Madrid» por defecto, que no es un dato del ERP.
`administrador`, `fechaFormulacion`, `nota9`, `nota10` y `nota10MedioAmbiente` no viajan: son texto del
asesor y la plataforma no los tiene (el documento deja el aviso correspondiente).

## Por qué hacen falta parches

`rvCA` y los métodos del asistente calculan **dentro** de `index.html` todo lo derivado: la tabla del
balance, el índice de notas, las comprobaciones, el historial, la animación de generación y la
descarga. El traductor sólo puede rellenar `CA_DATOS`, `CA_BAL`, `CA_NOTAS`, `CA_CAMBIOS` y el estado,
así que lo que `index.html` daba por hecho —un año fijo, dos columnas siempre llenas, un porcentaje de
confianza por nota, una aprobación firmada y unas versiones— hay que ajustarlo.

### 1. Cargar el traductor

Actual:

```
<script src="pantallas/inicio.js"></script>
```

Propuesto:

```
<script src="pantallas/inicio.js"></script>
<script src="pantallas/cuentas-anuales.js"></script>
```

Motivo: sin esa línea el traductor no se registra y la pantalla sigue con los datos de ejemplo.

### 2. Cabecera: año, empresa y NIF

Actual:

```
    <div><h1 style="margin:0;font-size:20px;font-weight:600;">Cuentas anuales · ejercicio 2025</h1><div style="color:var(--muted);margin-top:3px;">Bodegas Vega Alta, S.L. · B26451873 · formato abreviado · {{ caStepTxt }}</div></div>
```

Propuesto: usar props nuevas en lugar del año y de la empresa del ejemplo.

```
    <div><h1 style="margin:0;font-size:20px;font-weight:600;">Cuentas anuales · ejercicio {{ caAnio }}</h1><div style="color:var(--muted);margin-top:3px;">{{ caEmpresaNombre }} · {{ caNif }} · formato abreviado · {{ caStepTxt }}</div></div>
```

Y en `rvCA`, añadir a las props devueltas:

```
      caAnio: String(s.ejercicio || ''),
      caEmpresaNombre: (CLIENTES.find(c => c.id === (window.ABGA && ABGA.estado.empresa)) || CLIENTES[0] || {}).nombre || '',
      caNif: (CLIENTES.find(c => c.id === (window.ABGA && ABGA.estado.empresa)) || CLIENTES[0] || {}).nif || '',
```

Motivo: «2025», «Bodegas Vega Alta, S.L.» y «B26451873» estaban fijos, de la empresa del ejemplo.

### 3. Cabeceras de las columnas del balance

Actual (líneas 1385-1386):

```
          <sc-raw-th style="text-align:right;padding:8px 12px;font-size:11px;font-weight:600;color:var(--muted);background:var(--surface2);border-bottom:1px solid var(--border);">31/12/2025</sc-raw-th>
          <sc-raw-th style="text-align:right;padding:8px 12px;font-size:11px;font-weight:600;color:var(--muted);background:var(--surface2);border-bottom:1px solid var(--border);">31/12/2024</sc-raw-th>
```

Propuesto: cambiar sólo el texto de cada celda por `{{ caBalAnio1 }}` y `{{ caBalAnio2 }}`.

```
          <sc-raw-th style="text-align:right;padding:8px 12px;font-size:11px;font-weight:600;color:var(--muted);background:var(--surface2);border-bottom:1px solid var(--border);">{{ caBalAnio1 }}</sc-raw-th>
          <sc-raw-th style="text-align:right;padding:8px 12px;font-size:11px;font-weight:600;color:var(--muted);background:var(--surface2);border-bottom:1px solid var(--border);">{{ caBalAnio2 }}</sc-raw-th>
```

Y en `rvCA`:

```
      caBalAnio1: '31/12/' + s.ejercicio,
      caBalAnio2: '31/12/' + (Number(s.ejercicio) - 1),
```

Motivo: las dos fechas eran fijas.

### 4. Datos de partida: respetar lo que falta y quitar la fecha inventada

Actual:

```
    const datos = [...CA_DATOS.map(d => ({...d, ok:true, pend:false})), {t:'Hechos posteriores al cierre', det: s.caHechos ? 'Confirmado con el cliente el 23/09/2026' : 'Pendiente de confirmar con el cliente', ok:s.caHechos, pend:!s.caHechos}];
```

Propuesto:

```
    const datos = [...CA_DATOS.map(d => ({...d, ok: d.ok !== false, pend: d.ok === false})), {t:'Hechos posteriores al cierre', det: s.caHechos ? 'Confirmado a mano en esta sesión' : 'Sin confirmar: la plataforma no guarda esta confirmación (el texto lo aporta el asesor en la Nota 10)', ok:s.caHechos, pend:!s.caHechos}];
```

Motivo: `ok:true` para todo tapaba los datos que el módulo no puede dar (plantilla media, reparto de
vencimientos, amortización acumulada) y el `det` se inventaba una confirmación con fecha concreta
(«23/09/2026»).

### 5. Columna del año anterior y variación cuando no hay apuntes del año anterior

Actual:

```
    const bal = CA_BAL.map(([l, a, b2, bold], i) => ({l, a:eur(a), b:eur(b2), d:((a / b2 - 1) * 100 >= 0 ? '+' : '−') + Math.abs((a / b2 - 1) * 100).toLocaleString('es-ES', {minimumFractionDigits:1, maximumFractionDigits:1}) + ' %', dFg: a >= b2 ? 'var(--ok)' : 'var(--err)', fw: bold ? 600 : 400, sep: i === 2 || i === 5, bt: i === 3 || i === 6 ? '2px solid var(--border)' : '1px solid var(--border)'}));
```

Propuesto:

```
    const bal = CA_BAL.map(([l, a, b2, bold], i) => ({l, a:eur(a),
      b: b2 === null || b2 === undefined ? '—' : eur(b2),
      d: b2 ? ((a / b2 - 1) * 100 >= 0 ? '+' : '−') + Math.abs((a / b2 - 1) * 100).toLocaleString('es-ES', {minimumFractionDigits:1, maximumFractionDigits:1}) + ' %' : '—',
      dFg: b2 ? (a >= b2 ? 'var(--ok)' : 'var(--err)') : 'var(--muted)',
      fw: bold ? 600 : 400, sep: i === 2 || i === 5, bt: i === 3 || i === 6 ? '2px solid var(--border)' : '1px solid var(--border)'}));
```

Motivo: el traductor pone `null` en el año anterior cuando no hay apuntes de ese ejercicio (o cuando
el módulo no devuelve esa magnitud). Sin el guardo saldría `NaN €` y una variación `NaN %`; el módulo,
a propósito, deja la comparativa en blanco en vez de estimarla.

### 6. Índice de notas: sin confianza y con el número real

Actual:

```
      <div style="padding:12px 16px;border-bottom:1px solid var(--border);"><strong>Índice de la memoria</strong><div style="font-size:12px;color:var(--muted);margin-top:2px;">12 notas · confianza de la IA por nota</div></div>
```

Propuesto: `12 notas · confianza de la IA por nota` pasa a `{{ caNotasTitulo }}` (y la chapa de la
cabecera de la nota, ver más abajo).

Y en `rvCA`:

```
      caNotasTitulo: CA_NOTAS.length + ' notas del PGC de PYMES · redactadas desde los apuntes',
```

Motivo: eran «12 notas» y un porcentaje de confianza inventados; la memoria del PGC de PYMES tiene 10
notas y la plataforma no las puntúa.

### 7. `conf` de cada nota y nota seleccionada

Actual:

```
    const notas = CA_NOTAS.map((n, i) => ({...n, conf:n.conf + ' %', confFg: n.conf >= 90 ? 'var(--ai)' : 'var(--warn)', onClick:() => this.setState({caNota:i}), bg: s.caNota === i ? 'var(--accent-soft)' : 'transparent', fg: s.caNota === i ? 'var(--accent-strong)' : 'var(--text)'}));
```

Propuesto: dejar `conf` vacío cuando no sea un número.

```
    const notas = CA_NOTAS.map((n, i) => ({...n, conf: typeof n.conf === 'number' ? n.conf + ' %' : '', confFg: n.conf >= 90 ? 'var(--ai)' : 'var(--warn)', onClick:() => this.setState({caNota:i}), bg: s.caNota === i ? 'var(--accent-soft)' : 'transparent', fg: s.caNota === i ? 'var(--accent-strong)' : 'var(--text)'}));
```

Actual (con `CA_NOTAS` vacío, `nota` sería `undefined` y `nota.conf` reventaría):

```
    const nota = CA_NOTAS[s.caNota];
```

Propuesto:

```
    const nota = CA_NOTAS[s.caNota] || {n:'', t:'', txt:''};
```

Actual:

```
      caNotas:notas, caNotaSel:{...nota, conf:nota.conf + ' %'}, caToRev:() => this.setState({caStep:2}),
```

Propuesto:

```
      caNotas:notas, caNotaSel:{...nota, conf: typeof nota.conf === 'number' ? nota.conf + ' %' : ''}, caToRev:() => this.setState({caStep:2}),
```

Actual (cabecera de la nota: marca «IA» y confianza):

```
        <div style="display:flex;align-items:center;gap:8px;"><span style="font-family:'IBM Plex Mono',monospace;font-size:10px;font-weight:600;color:#fff;background:var(--ai);border-radius:3px;padding:2px 6px;">IA</span><strong>Borrador generado · confianza {{ caNotaSel.conf }}</strong></div>
```

Propuesto:

```
        <div style="display:flex;align-items:center;gap:8px;"><strong>Borrador generado desde los apuntes</strong></div>
```

Actual (título del documento):

```
        <div style="font-size:11px;color:var(--muted);text-transform:uppercase;letter-spacing:.08em;">Memoria abreviada del ejercicio 2025</div>
```

Propuesto: `Memoria abreviada del ejercicio {{ caAnio }}` en lugar de `2025`.

Motivo: las notas reales no traen `conf` y la memoria no la redacta un modelo de lenguaje.

### 8. Comprobaciones antes de aprobar (las de verdad)

Actual (líneas 2446-2452):

```
    const checks = [
      {t:'Balance cuadrado: activo = patrimonio neto + pasivo', det:'4.096.778,89 €', ok:true},
      {t:'El resultado de la memoria coincide con la cuenta de pérdidas y ganancias', det:'394.212,55 €', ok:true},
      {t:'Notas obligatorias del formato abreviado completas', det:'12 de 12', ok:true},
      {t:'Cambios propuestos por la IA revisados', det:nAcc + ' aceptados · ' + (nRes - nAcc) + ' rechazados', ok:nRes === cambios.length},
      {t:'Aprobación del responsable del despacho', det: s.caApproved ? 'María Dolores Ibáñez · 23/09/2026 11:24' : s.caApproving ? 'Esperando firma…' : 'Pendiente', ok:s.caApproved}
    ].map((c, i) => ({...c, fg: c.ok ? 'var(--ok)' : 'var(--warn)', bg: c.ok ? 'var(--ok-soft)' : 'var(--warn-soft)', mark: c.ok ? '✓' : '·', delay:(i * 90) + 'ms'}));
```

Propuesto: las comprobaciones las deja el traductor en `s.caChecksDatos`; aquí sólo queda la
aprobación, sin persona ni fecha inventadas.

```
    const checks = (s.caChecksDatos || []).concat([{t:'Aprobación del responsable del despacho', det: s.caApproved ? 'marcada a mano en esta sesión' : s.caApproving ? 'Esperando confirmación…' : 'Pendiente: la plataforma no tiene circuito de aprobación', ok:s.caApproved}])
      .map((c, i) => ({...c, fg: c.ok ? 'var(--ok)' : 'var(--warn)', bg: c.ok ? 'var(--ok-soft)' : 'var(--warn-soft)', mark: c.ok ? '✓' : '·', delay:(i * 90) + 'ms'}));
```

Motivo: las cinco comprobaciones eran cifras y afirmaciones fijas («4.096.778,89 €», «12 de 12», una
firma con nombre y fecha). El módulo sí calcula comprobaciones de integridad y el traductor ya las
deja en `caChecksDatos`.

### 9. Avisos y limitaciones del cálculo en el paso de aprobación

Actual (`</sc-for>` que cierra el bucle de `caChecks`, línea 1471):

```
    </sc-for>
```

Propuesto: añadir un bloque después, con los avisos que deja el traductor en `s.caAvisos`.

```
    </sc-for>
    <div style="padding:12px 18px;border-top:1px solid var(--border);">
      <div style="font-weight:600;margin-bottom:6px;">Avisos y limitaciones del cálculo</div>
      <sc-for list="{{ caAvisos }}" as="av" hint-placeholder-count="3">
        <div style="font-size:12px;color:var(--muted);padding:3px 0;">· {{ av }}</div>
      </sc-for>
    </div>
```

Motivo: el módulo devuelve 13 avisos (Nota 9 y Nota 10 sin texto, impuesto sin asiento, cuadros de
inmovilizado y de vencimientos pendientes, grupos del balance sin movimiento…) y la pantalla no los
enseñaba en ningún sitio.

### 10. Aprobación: no fingir el circuito ni la firma

Actual:

```
        <span style="flex:1;font-size:12px;color:var(--muted);">Se enviará a María Dolores Ibáñez, responsable del despacho.</span>
```

Propuesto:

```
        <span style="flex:1;font-size:12px;color:var(--muted);">La plataforma no tiene circuito de aprobación ni firma: la aprobación se marca aquí a mano y se formaliza fuera.</span>
```

Actual:

```
        <button sc-camel-on-click="{{ caApprove }}" style="height:38px;padding:0 16px;border:none;border-radius:6px;background:var(--btn);color:#fff;font-size:13px;font-weight:600;cursor:pointer;" style-hover="background:var(--btn-hover);">Solicitar aprobación</button>
```

Propuesto: el texto del botón pasa a `Marcar como aprobada (a mano)`.

Actual:

```
        <span style="display:inline-flex;align-items:center;gap:8px;font-size:13px;color:var(--muted);"><span style="width:14px;height:14px;border-radius:50%;border:2px solid var(--border);border-top-color:var(--accent);animation:spin .7s linear infinite;"></span>Esperando la aprobación de María Dolores Ibáñez…</span>
```

Propuesto: quitar el nombre y dejar `Esperando la confirmación manual…`.

Actual:

```
        <span style="flex:1;font-size:13px;color:var(--ok);font-weight:600;animation:fadeIn .3s ease both;">✓ Cuentas anuales aprobadas</span>
```

Propuesto: `Aprobación marcada a mano en esta sesión` en lugar de `✓ Cuentas anuales aprobadas`.

Actual:

```
  caApprove(){ this.setState({caApproving:true}); setTimeout(() => this.setState({caApproving:false, caApproved:true}), 1800); }
```

Propuesto:

```
  caApprove(){ this.setState({caApproved:true}); }
```

Motivo: «María Dolores Ibáñez, responsable del despacho» era del ejemplo y el `setTimeout` de 1,8 s
simulaba una firma remota que no existe.

### 11. Generar el borrador: pedir el informe, no animar

Actual:

```
  caGenerate(){
    this.setState({caGen:{pct:0, i:0}});
    const t0 = Date.now(), dur = 3800;
    const tick = () => { const t = Math.min(1, (Date.now() - t0) / dur); this.setState({caGen:{pct:t * 100, i:Math.min(CA_GEN.length - 1, Math.floor(t * CA_GEN.length))}}); if (t < 1) this._cg = setTimeout(tick, 30); else setTimeout(() => this.setState({caGen:null, caStep:1, caNota:0}), 300); };
    this._cg = setTimeout(tick, 30);
  }
```

Propuesto:

```
  async caGenerate(){
    this.setState({caGen:{pct:0, i:0}});
    try { await ABGA.cargarPantalla('memoria', true); }
    catch (fallo) { ABGA.aviso('No se ha podido generar la memoria: ' + (fallo.message || fallo), 'error'); }
    this.setState({caGen:null, caStep:1, caNota:0});
  }
```

Motivo: la barra de 3,8 s era decorativa y el paso 2 se abría con las notas de ejemplo. Con esto el
botón vuelve a pedir el informe a la plataforma (mientras corre la petición la barra se queda en el
primer mensaje de `CA_GEN`, que describe lo que hace el módulo y se mantiene).

### 12. «IA» donde la plataforma sólo calcula

Actual:

```
const CA_STEPS = ['Datos','Borrador IA','Revisión','Aprobación','Exportar'];
```

Propuesto: `const CA_STEPS = ['Datos','Borrador','Revisión','Aprobación','Exportar'];`

Motivo: el borrador lo redacta el módulo con los apuntes, no un modelo de lenguaje.

Actual (botón de generar, con la chapa «IA»):

```
          <button sc-camel-on-click="{{ caGenerate }}" style="width:100%;height:40px;border:none;border-radius:6px;background:var(--btn);color:#fff;font-size:13px;font-weight:600;cursor:pointer;display:flex;align-items:center;justify-content:center;gap:8px;" style-hover="background:var(--btn-hover);"><span style="font-family:'IBM Plex Mono',monospace;font-size:10px;background:rgba(255,255,255,.2);border-radius:3px;padding:2px 5px;">IA</span>Generar borrador de la memoria</button>
```

Propuesto: quitar la chapa y dejar el texto `Generar la memoria con los apuntes`.

Actual (subtítulo del panel de datos):

```
      <div style="padding:12px 16px;border-bottom:1px solid var(--border);"><strong>Datos de partida</strong><div style="font-size:12px;color:var(--muted);margin-top:2px;">Leídos del ERP · la IA necesita todos para redactar la memoria</div></div>
```

Propuesto: `Lo que el módulo ha leído del ERP · lo que no consta se declara` en lugar de
`Leídos del ERP · la IA necesita todos para redactar la memoria`.

Actual (casilla de hechos posteriores):

```
        <span style="font-size:13px;">Confirmado con el cliente: no hay hechos posteriores relevantes</span>
```

Propuesto: `Hechos posteriores al cierre confirmados a mano (la plataforma no guarda esta confirmación)`.

Motivo: describe lo que la pantalla enseña de verdad y no da por hecho que la confirmación se guarde
(no se guarda).

### 13. Revisión pendiente: no dividir por cero con la lista vacía

Actual:

```
      caCambios:cambios, caRes:nRes, caTotal:cambios.length, caResW:(nRes / cambios.length * 100) + '%', caAllRes:nRes === cambios.length, caNotAll:nRes < cambios.length, caAprOp: nRes < cambios.length ? .45 : 1,
```

Propuesto: cambiar `caResW:(nRes / cambios.length * 100) + '%'` por
`caResW:(cambios.length ? nRes / cambios.length * 100 : 0) + '%'`.

Motivo: `CA_CAMBIOS` llega vacío (la plataforma no propone cambios), así que la división daba `NaN %`
en la barra «0 de 0 revisados». Con la lista vacía queda en 0 de 0, que es la verdad.

### 14. Exportar: lo que la plataforma sí sabe hacer

Actual (tarjeta de Word):

```
        <span style="font-size:11px;font-weight:700;color:var(--accent-strong);">WORD · .doc</span><strong>Memoria editable</strong><span style="font-size:12px;color:var(--muted);flex:1;">Para ajustes finales del despacho.</span>
```

Propuesto:

```
        <span style="font-size:11px;font-weight:700;color:var(--accent-strong);">CSV · ZIP</span><strong>Tablas del informe</strong><span style="font-size:12px;color:var(--muted);flex:1;">Lo que se descarga son las tablas del informe (la plataforma no genera .doc).</span>
```

Actual (tarjeta de PDF):

```
        <span style="font-size:11px;font-weight:700;color:var(--err);">PDF</span><strong>Cuentas anuales completas</strong><span style="font-size:12px;color:var(--muted);flex:1;">Balance, PyG, ECPN y memoria.</span>
```

Propuesto:

```
        <span style="font-size:11px;font-weight:700;color:var(--err);">IMPRESIÓN</span><strong>Guardar como PDF</strong><span style="font-size:12px;color:var(--muted);flex:1;">El PDF lo hace el navegador al imprimir el informe; la plataforma no genera PDF.</span>
```

Actual (tarjeta del Registro):

```
        <span style="font-size:11px;font-weight:700;color:var(--ai);">ZIP · D2</span><strong>Depósito en el Registro</strong><span style="font-size:12px;color:var(--muted);flex:1;">Paquete con huella digital para el Registro Mercantil.</span>
```

Propuesto:

```
        <span style="font-size:11px;font-weight:700;color:var(--ai);">REGISTRO</span><strong>Depósito en el Registro</strong><span style="font-size:12px;color:var(--muted);flex:1;">No disponible: la plataforma no genera el paquete de depósito ni su huella digital.</span>
```

Actual:

```
  caDownload(fmt){
    this.setState(s => ({caExport:{...s.caExport, [fmt]:1}}));
    const t0 = Date.now();
    const tick = () => { const t = Math.min(1, (Date.now() - t0) / 1400); this.setState(s => ({caExport:{...s.caExport, [fmt]:Math.max(1, t * 100)}})); if (t < 1) setTimeout(tick, 30); else if (fmt === 'word') this.caWordFile(); };
    setTimeout(tick, 30);
  }
```

Propuesto:

```
  caDownload(fmt){
    if (fmt === 'reg') { ABGA.aviso('El depósito en el Registro no está en la plataforma.', 'error'); return; }
    if (fmt === 'pdf') { window.print(); return; }
    const t0 = Date.now();
    const tick = () => { const t = Math.min(1, (Date.now() - t0) / 1400); this.setState(s => ({caExport:{...s.caExport, word:Math.max(1, t * 100)}})); if (t < 1) setTimeout(tick, 30); else ABGA_CA.exportar().catch(e => ABGA.aviso('No se ha podido descargar: ' + (e.message || e), 'error')); };
    setTimeout(tick, 30);
  }
```

Actual (método que fabricaba un `.doc` en el navegador):

```
  caWordFile(){
    const c = cli('C001'), body = CA_NOTAS.map(n => '<h2>Nota ' + n.n + '. ' + n.t + '</h2><p>' + n.txt + '</p>').join('');
    const html = '<html><head><meta charset="utf-8"><title>Memoria 2025</title></head><body style="font-family:Calibri,sans-serif"><h1>' + c.nombre + '</h1><p>NIF ' + c.nif + ' · Memoria abreviada del ejercicio 2025</p>' + body + '</body></html>';
    const a = document.createElement('a'); a.href = URL.createObjectURL(new Blob([html], {type:'application/msword'})); a.download = 'Memoria_2025_BodegasVegaAlta.doc'; document.body.appendChild(a); a.click(); a.remove();
  }
```

Propuesto: borrarlo entero (ya no lo llama nadie).

Motivo: `/api/informe/exportar` devuelve CSV o ZIP con las tablas del informe; no hay Word ni PDF en
el servidor (el endpoint lo dice: el PDF lo hace el navegador al imprimir) ni paquete del Registro.
`caDownload('word')` llamaba a `caWordFile`, que montaba un documento falso en el cliente, con el
nombre de la empresa del ejemplo en el fichero `Memoria_2025_BodegasVegaAlta.doc`. La descarga real la
hace `ABGA_CA.exportar()`, definida en el traductor.

### 15. Historial de versiones

Actual:

```
      caVersiones:[{v:'v1', t:'Borrador generado por la IA', q:'23/09/2026 10:14', ia:true}, {v:'v2', t:'Revisado por Javier Roldán · ' + nAcc + ' cambios aceptados', q:'23/09/2026 11:02', ia:false}, {v:'v3', t:'Aprobado por María Dolores Ibáñez', q:'23/09/2026 11:24', ia:false}],
```

Propuesto: `caVersiones:[]`.

Actual:

```
      <div style="padding:12px 16px;border-bottom:1px solid var(--border);"><strong>Historial de versiones</strong></div>
```

Propuesto: añadir el motivo a la cabecera del bloque.

```
      <div style="padding:12px 16px;border-bottom:1px solid var(--border);"><strong>Historial de versiones</strong><div style="font-size:12px;color:var(--muted);margin-top:2px;">La plataforma no versiona la memoria: no hay historial que mostrar.</div></div>
```

Motivo: las tres versiones, con sus horas y sus personas, eran inventadas; con la lista vacía el
bloque quedaría en blanco sin explicar por qué.

## Lo que la plataforma no hace (y por eso la pantalla lo declara)

1. **Comparar con la memoria del ejercicio anterior y proponer cambios de texto** (paso «Revisión»,
   `CA_CAMBIOS`): no se guardan memorias anteriores ni se comparan.
2. **Puntuar la confianza de cada nota**: el módulo redacta las notas con los apuntes, no hay
   porcentaje de fiabilidad, y los del diseño (97, 95, 93…) no existían.
3. **Circuito de aprobación y firma**: no hay usuarios firmantes, ni envío a aprobación, ni sellado.
   La aprobación es una marca manual de la sesión.
4. **Versionado de la memoria**: no hay historial de versiones.
5. **Exportar a Word (.doc) o a PDF desde el servidor**: la API sólo exporta las tablas del informe en
   CSV/ZIP y el PDF lo hace el navegador al imprimir. No hay ECPN ni estado de cambios en el
   patrimonio neto.
6. **El paquete de depósito en el Registro Mercantil** (ZIP «D2») y su huella digital.
7. **La plantilla media por categoría y sexo** y los **hechos posteriores al cierre**: no constan en
   los apuntes del ERP (los aporta el asesor en la Nota 10).
8. **El reparto de las deudas por año de vencimiento**: los apuntes no traen cuadros de amortización
   ni fechas de vencimiento por línea, y el módulo no reparte el saldo en tramos estimados.
9. **El cuadro de inmovilizado del PGC** (saldo inicial y saldo final): falta el asiento de apertura y
   las cuentas 28x; en su lugar se muestran los movimientos reales del ejercicio.
10. **La propuesta de aplicación del resultado**: la aprueba la Junta General; el módulo sólo publica
    la base de reparto y una propuesta por defecto.
11. **El texto de la Nota 9, de la Nota 10 y la información medioambiental**: es del asesor; si no
    llega, el documento deja el aviso.
12. **La fecha de formulación, el administrador y el domicilio social**: no están en la plataforma. El
    domicilio se pasa desde el catálogo de empresas del hub cuando lo trae; el resto queda con los
    valores por defecto del módulo (31 de marzo, «pendiente de indicar») y con su aviso.

## Cómo comprobarlo

    cd /home/pedro/.hermes/profiles/abga/workspace/abga/nuevo
    node --check frontend/hub/pantallas/cuentas-anuales.js
    ./.venv/bin/python backend/scripts/probe_dos_modulos.py    # memoria y duplicados con fixtures locales

Empresas con el ejercicio en caché local: **6091/2025** y **6172/2025**. Cualquier otro ejercicio
dispara cientos de consultas al ERP de ABGA: no se pide.
