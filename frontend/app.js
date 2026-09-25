'use strict';
/* Plataforma ABGA — panel de cliente (diseño de Claude Design + API real).
   Sin dependencias: las gráficas son SVG generados aquí. */

const API = '';
const estado = {
  token: localStorage.getItem('abga_token') || '',
  usuario: null, interno: false, empresas: [], modulos: [],
  empresa: localStorage.getItem('abga_empresa') || '',
  year: parseInt(localStorage.getItem('abga_year') || '0', 10),
  trabajo: null, poll: null, moduloAbierto: null,
};

const eur = new Intl.NumberFormat('es-ES', { minimumFractionDigits: 2, maximumFractionDigits: 2 });
const ent = new Intl.NumberFormat('es-ES', { maximumFractionDigits: 0 });
const $ = (id) => document.getElementById(id);
const esc = (t) => String(t == null ? '' : t).replace(/[&<>"]/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' }[c]));
const imp = (n) => (typeof n === 'number' ? eur.format(n) + ' €' : '—');
const cls = (n) => (typeof n !== 'number' ? '' : n > 0 ? 'pos' : n < 0 ? 'neg' : '');

function toast(texto, tipo = '') {
  const t = $('banner-usuario-texto');
  if (t) { $('banner-usuario').hidden = false; t.textContent = texto; $('banner-usuario').dataset.tipo = tipo; }
}

async function api(ruta, opciones = {}) {
  const cab = Object.assign({ 'Content-Type': 'application/json' }, opciones.headers || {});
  if (estado.token) cab.Authorization = 'Bearer ' + estado.token;
  const r = await fetch(API + ruta, Object.assign({ credentials: 'include' }, opciones, { headers: cab }));
  let d = {};
  try { d = await r.json(); } catch (e) { d = { error: 'respuesta no válida' }; }
  if (r.status === 401 && ruta !== '/api/login') { salir(true); throw new Error('sesión caducada'); }
  d._status = r.status;
  return d;
}

/* ============================ sesión ============================ */

async function entrar(email, password) {
  const r = await api('/api/login', { method: 'POST', body: JSON.stringify({ email, password }) });
  if (r.status !== 'ok') {
    const c = document.querySelector('.registro');
    if (c) { c.textContent = '⚠ ' + (r.error || 'No se pudo entrar'); c.classList.add('error'); }
    return;
  }
  estado.token = r.token;
  localStorage.setItem('abga_token', r.token);
  const reg = document.querySelector('.registro');
  if (reg) { reg.classList.remove('error'); reg.textContent = 'Acceso restringido · Cada usuario ve únicamente sus empresas'; }
  await arrancar();
}

function salir(automatico) {
  estado.token = '';
  localStorage.removeItem('abga_token');
  api('/api/logout', { method: 'POST' }).catch(() => {});
  $('vista-app').classList.remove('visible');
  $('vista-login').classList.add('visible');
  if (automatico) toast('La sesión ha caducado, vuelve a entrar', 'error');
}

async function arrancar() {
  const yo = await api('/api/yo');
  if (yo.status !== 'ok') { salir(); return; }
  estado.usuario = yo.usuario;
  estado.interno = yo.interno;
  $('cabecera-usuario').textContent = `${estado.usuario.nombre} · ${estado.interno ? 'ABGA' : 'Cliente'}`;
  $('tab-interno').style.display = estado.interno ? '' : 'none';
  $('vista-login').classList.remove('visible');
  $('vista-app').classList.add('visible');

  const emp = await api('/api/empresas');
  estado.empresas = emp.empresas || [];
  const mods = await api('/api/modulos');
  estado.modulos = mods.modulos || [];
  estado.menus = mods.menus || [];
  estado.pendientes = mods.pendientes || [];


  const selEmp = $('select-empresa');
  selEmp.innerHTML = estado.empresas.map((e) => `<option value="${esc(e.cod_empresa)}">${esc(e.nombre)}</option>`).join('');
  if (!estado.empresas.some((e) => e.cod_empresa === estado.empresa)) estado.empresa = await primeraEmpresaConDatos();
  selEmp.value = estado.empresa;
  // cada cliente va ligado a su número de empresa; si sólo tiene una, no hay que elegir
  $('select-empresa').closest('.campo').style.display = estado.empresas.length > 1 ? '' : 'none';

  await cargarEjercicios();

  pintarModulos();
  await cargarPanel();
}

/** Empresa por defecto: la primera que tenga algún ejercicio con datos cargados. */
async function primeraEmpresaConDatos() {
  if (!estado.empresas.length) return '';
  for (const e of estado.empresas) {
    try {
      const r = await api(`/api/ejercicios?cod_empresa=${encodeURIComponent(e.cod_empresa)}`);
      if ((r.ejercicios || []).some((y) => y.tiene_datos)) return e.cod_empresa;
    } catch (err) { /* sigue con la siguiente */ }
  }
  return estado.empresas[0].cod_empresa;
}

/** Rellena el selector de ejercicios y abre por el último ejercicio con datos. */
async function cargarEjercicios() {
  if (!estado.empresa) return;
  let lista = [];
  try { lista = (await api(`/api/ejercicios?cod_empresa=${encodeURIComponent(estado.empresa)}`)).ejercicios || []; }
  catch (e) { return; }
  const conDatos = lista.filter((e) => e.tiene_datos);
  const sel = $('select-ejercicio');
  sel.innerHTML = lista.map((e) => {
    const marca = e.tiene_datos === false ? ' · sin datos' : (e.tiene_datos === null ? ' · sin cargar' : '');
    return `<option value="${e.year}">${e.year}${marca}</option>`;
  }).join('');
  // año por defecto: el último ejercicio CERRADO con datos (no el año en curso, que está a medias)
  const anioActual = new Date().getFullYear();
  const objetivo = (conDatos.filter((e) => e.year !== anioActual)[0] || conDatos[0] || lista[0] || {}).year;
  if (!lista.some((e) => e.year === estado.year)) estado.year = objetivo;
  sel.value = estado.year;
  // si el ejercicio está en curso (año actual), se avisa en el panel
  $('ejercicio-en-curso').hidden = (estado.year !== anioActual);
}

/* ============================ panel ============================ */

async function cargarPanel() {
  if (!estado.empresa) return;
  let r;
  try { r = await api(`/api/dashboard?cod_empresa=${encodeURIComponent(estado.empresa)}&year=${estado.year}`); }
  catch (e) { return; }
  if (r.status !== 'ok') {
    $('avisos').hidden = false;
    $('avisos').innerHTML = `<div class="aviso"><span class="punto error"></span><span>${esc(r.error || 'No se pudieron cargar los datos')}</span></div>`;
    return;
  }
  pintarPanel(r.data, r.meta, r.avisos || []);
}

function pintarPanel(d, meta, avisos) {
  const k = d.kpis;
  const cache = meta && meta.desde_cache ? 'Datos sincronizados con el ERP el ' + fechaCorta(meta.generado) : 'Leyendo del ERP…';
  $('avisos').hidden = avisos.length === 0;
  $('avisos').innerHTML = avisos.map((a) => `<div class="aviso"><span class="punto aviso"></span><span>${esc(a)}</span></div>`).join('') +
    (avisos.length ? `<div class="aviso"><span class="punto info"></span><span>${esc(cache)}</span></div>` : '');

  const kpis = [
    ['Ingresos', imp(k.totalIngresos), varTxt(k.varIngresos), cls(k.varIngresos)],
    ['Resultado neto', imp(k.resultadoNeto), varTxt(k.varResultado), cls(k.varResultado)],
    ['EBITDA', imp(k.ebitda), `margen ${eur.format(k.margenEBITDA)} %`, ''],
    ['Fondo de maniobra', imp(k.fondoManiobra), k.fondoManiobra < 0 ? 'circulante tensionado' : 'holgado', cls(-k.fondoManiobra)],
    ['Tesorería', imp(k.tesoreria), 'saldo cuentas 57x', ''],
    ['Patrimonio neto', imp(k.patrimonioNeto), `endeudamiento ${eur.format(k.endeudamiento)} %`, k.endeudamiento > 70 ? 'neg' : ''],
    ['Liquidez', eur.format(k.liquidez), k.liquidez >= 1 ? 'correcta' : 'ajustada', k.liquidez >= 1 ? 'pos' : 'neg'],
    ['Rentabilidad (ROE)', eur.format(k.roe) + ' %', 'ROA ' + eur.format(k.roa) + ' %', cls(k.roe)],
  ];
  $('kpi-grid').innerHTML = kpis.map(([etq, val, sub, cl]) =>
    `<div class="kpi"><div class="etiqueta">${esc(etq)}</div><div class="valor ${cl}">${val}</div><div class="variacion ${cl}">${esc(sub)}</div></div>`).join('');

  const cats = d.mensual.map((m) => m.mes);
  barras($('svg-mensual'), cats, [
    { nombre: 'Ingresos', color: '#185FA5', valores: d.mensual.map((m) => m.ingresos) },
    { nombre: 'Gastos', color: '#c98a2b', valores: d.mensual.map((m) => m.gastos) },
  ], imp);
  lineas($('svg-linea'), cats, [
    { nombre: 'Resultado acumulado', color: '#185FA5', valores: d.mensual.map((m) => m.resultado_acumulado) },
    { nombre: 'Tesorería', color: '#2e7d32', valores: d.mensual.map((m) => m.tesoreria) },
  ], imp);
  barras($('svg-comparativa'), d.comparativa.map((c) => String(c.year)), [
    { nombre: 'Ingresos', color: '#185FA5', valores: d.comparativa.map((c) => c.ingresos) },
    { nombre: 'Resultado neto', color: '#2e7d32', valores: d.comparativa.map((c) => c.resultadoNeto) },
  ], imp);
  barrasH($('svg-gastos'), (d.top_gastos || []).map((f) => [f.cuenta, f.importe]));

  $('insight-mensual').textContent = `Ingresos ${imp(d.kpis.totalIngresos)} · Resultado neto ${imp(d.kpis.resultadoNeto)}.`;
  $('insight-linea').textContent = 'Evolución del resultado acumulado y del saldo de tesorería durante el ejercicio.';
  $('insight-comparativa').textContent = `Comparativa de ${d.comparativa.length} ejercicios: ${d.comparativa.map((c) => c.year).join(' · ')}.`;
  $('insight-gastos').textContent = 'Principales cuentas de gasto del ejercicio, ordenadas por importe.';

  const terceros = tablaTerceros(d);
  pintarTabla($('tabla-terceros'), ['Tercero', 'Cobro pendiente', 'Pago pendiente'], terceros, [1, 2]);
  $('filtro-terceros').oninput = (e) => pintarTabla($('tabla-terceros'), ['Tercero', 'Cobro pendiente', 'Pago pendiente'],
    terceros.filter((f) => f[0].toLowerCase().includes(e.target.value.toLowerCase())), [1, 2]);
  $('btn-export-terceros').onclick = () => descargarCSV('terceros', ['Tercero', 'Cobro', 'Pago'], terceros);

  pintarTabla($('tabla-cierre'),
    ['Ejercicio', 'Ingresos', 'EBITDA', 'Resultado neto', 'Tesorería', 'Margen', 'Asientos'],
    d.comparativa.map((c) => [
      String(c.year) + (c.tiene_datos ? '' : ' (sin datos)'), imp(c.ingresos), imp(c.ebitda),
      `<span class="${cls(c.resultadoNeto)}">${imp(c.resultadoNeto)}</span>`, imp(c.tesoreria),
      eur.format(c.margenNeto) + ' %', ent.format(c.n_asientos),
    ]), [1, 2, 3, 4, 5, 6]);
  $('btn-export-cierre').onclick = () => descargarCSV('cierre', ['Ejercicio', 'Ingresos', 'EBITDA', 'Resultado', 'Tesorería', 'Margen', 'Asientos'],
    d.comparativa.map((c) => [c.year, c.ingresos, c.ebitda, c.resultadoNeto, c.tesoreria, c.margenNeto, c.n_asientos]));
}

const varTxt = (v) => (typeof v === 'number' ? (v >= 0 ? '▲ ' : '▼ ') + eur.format(v) + ' % vs año anterior' : '—');

function tablaTerceros(d) {
  const prov = new Map((d.proveedores || []).map((p) => [p.tercero, p.saldo]));
  const mapa = new Map();
  (d.clientes || []).forEach((c) => mapa.set(c.tercero, { c: c.saldo, p: prov.get(c.tercero) || 0 }));
  (d.proveedores || []).forEach((p) => { if (!mapa.has(p.tercero)) mapa.set(p.tercero, { c: 0, p: p.saldo }); });
  return [...mapa.entries()].map(([n, v]) => [n, imp(v.c), imp(v.p)]);
}

/* ============================ gráficas ============================ */

function barras(svg, categorias, series, formato) {
  const W = 720, H = 260, mi = 8, md = 8, ms = 18, mf = 36, au = W - mi - md, hu = H - ms - mf;
  const max = Math.max(0.0001, ...series.flatMap((s) => s.valores.map((v) => Math.abs(v))));
  const ag = au / Math.max(1, categorias.length), ab = Math.max(4, (ag * 0.66) / series.length);
  let out = '';
  for (let i = 0; i <= 4; i++) out += `<line x1="${mi}" y1="${ms + hu * i / 4}" x2="${W - md}" y2="${ms + hu * i / 4}" stroke="#e7edf6"/>`;
  categorias.forEach((c, ci) => {
    const x0 = mi + ci * ag + (ag - ab * series.length) / 2;
    series.forEach((s, si) => {
      const v = s.valores[ci] || 0, h = (Math.abs(v) / max) * hu, x = x0 + si * ab, y = ms + hu - h;
      out += `<rect x="${x.toFixed(1)}" y="${y.toFixed(1)}" width="${(ab - 1.5).toFixed(1)}" height="${h.toFixed(1)}" fill="${s.color}" rx="1.5"><title>${esc(c)} · ${esc(s.nombre)}: ${formato(v)}</title></rect>`;
    });
    out += `<text x="${(mi + ci * ag + ag / 2).toFixed(1)}" y="${H - 12}" font-size="11" fill="#5b6b80" text-anchor="middle" font-family="system-ui,Arial">${esc(c)}</text>`;
  });
  svg.setAttribute('viewBox', `0 0 ${W} ${H}`);
  svg.innerHTML = out;
  const leg = $('legenda-' + (svg.id.replace('svg-', '') === 'mensual' ? 'mensual' : svg.id.replace('svg-', '')));
  if (leg) leg.innerHTML = series.map((s) => `<span class="leyenda-item"><i style="background:${s.color}"></i>${esc(s.nombre)}</span>`).join('');
}

function lineas(svg, categorias, series, formato) {
  const W = 720, H = 260, mi = 10, md = 10, ms = 18, mf = 36, au = W - mi - md, hu = H - ms - mf;
  const vals = series.flatMap((s) => s.valores), max = Math.max(0, ...vals), min = Math.min(0, ...vals), rango = (max - min) || 1;
  const y = (v) => ms + hu - ((v - min) / rango) * hu, n = Math.max(1, categorias.length - 1);
  let out = '';
  if (min < 0) out += `<line x1="${mi}" y1="${y(0).toFixed(1)}" x2="${W - md}" y2="${y(0).toFixed(1)}" stroke="#c9d4e4" stroke-dasharray="4,4"/>`;
  series.forEach((s) => {
    const pts = s.valores.map((v, i) => `${(mi + au * i / n).toFixed(1)},${y(v).toFixed(1)}`).join(' ');
    out += `<polyline points="${pts}" fill="none" stroke="${s.color}" stroke-width="2.4" stroke-linejoin="round"/>`;
    s.valores.forEach((v, i) => out += `<circle cx="${(mi + au * i / n).toFixed(1)}" cy="${y(v).toFixed(1)}" r="3" fill="#fff" stroke="${s.color}" stroke-width="2"><title>${esc(categorias[i])}: ${formato(v)}</title></circle>`);
  });
  categorias.forEach((c, i) => out += `<text x="${(mi + au * i / n).toFixed(1)}" y="${H - 12}" font-size="11" fill="#5b6b80" text-anchor="middle" font-family="system-ui,Arial">${esc(c)}</text>`);
  svg.setAttribute('viewBox', `0 0 ${W} ${H}`);
  svg.innerHTML = out;
  const leg = $('legenda-linea');
  if (leg) leg.innerHTML = series.map((s) => `<span class="leyenda-item"><i style="background:${s.color}"></i>${esc(s.nombre)}</span>`).join('');
}

function barrasH(svg, filas) {
  if (!filas.length) { svg.innerHTML = '<text x="8" y="20" font-size="12" fill="#5b6b80">Sin datos.</text>'; return; }
  const W = 720, H = Math.max(90, filas.length * 34 + 20);
  const max = Math.max(...filas.map((f) => Math.abs(f[1])), 1);
  let out = '';
  filas.forEach(([etq, val], i) => {
    const y = 12 + i * 34, w = (Math.abs(val) / max) * (W - 180);
    out += `<text x="4" y="${y + 12}" font-size="11" fill="#5b6b80" font-family="system-ui,Arial">${esc(String(etq).slice(0, 20))}</text>`;
    out += `<rect x="150" y="${y}" width="${Math.max(2, w).toFixed(1)}" height="14" fill="#185FA5" rx="2"/>`;
    out += `<text x="${150 + w + 6}" y="${y + 11}" font-size="11" fill="#112233" font-family="system-ui,Arial">${imp(val)}</text>`;
  });
  svg.setAttribute('viewBox', `0 0 ${W} ${H}`);
  svg.innerHTML = out;
}

/* ============================ tablas / utilidades ============================ */

function pintarTabla(tabla, cab, filas, num) {
  tabla.querySelector('thead').innerHTML = '<tr>' + cab.map((c, i) => `<th class="${num.includes(i) ? 'num' : ''}">${esc(c)}</th>`).join('') + '</tr>';
  tabla.querySelector('tbody').innerHTML = filas.length
    ? filas.map((f) => '<tr>' + f.map((c, i) => `<td class="${num.includes(i) ? 'num' : ''}">${typeof c === 'string' && c.startsWith('<') ? c : esc(c)}</td>`).join('') + '</tr>').join('')
    : '<tr><td colspan="' + cab.length + '" class="vacias">Sin datos.</td></tr>';
}

function descargarCSV(nombre, cab, filas) {
  const csv = [cab.join(';')].concat(filas.map((f) => f.map((c) => `"${String(c).replace(/"/g, '""')}"`).join(';'))).join('\n');
  const a = document.createElement('a');
  a.href = URL.createObjectURL(new Blob(['\ufeff' + csv], { type: 'text/csv;charset=utf-8' }));
  a.download = nombre + '.csv'; a.click();
}

function fechaCorta(iso) {
  if (!iso) return '';
  const d = new Date(iso);
  return d.toLocaleDateString('es-ES') + ' ' + d.toLocaleTimeString('es-ES', { hour: '2-digit', minute: '2-digit' });
}

/* ============================ informes ============================ */

function descripcionModulo(n) {
  const d = {
    dashboard: 'KPIs, evolución mensual y comparativa interanual.',
    analisis: 'Más de 30 comprobaciones automáticas con semáforo de riesgo.',
    pyg: 'Balance de situación y cuenta de pérdidas y ganancias.',
    sumas_saldos: 'Saldo inicial, debe y haber de cada cuenta, con subtotales por grupo.',
    libro_iva: 'IVA repercutido y soportado por mes y trimestre, con el detalle de cada factura.',
    libro_retenciones: 'Retenciones de trabajo y de profesionales por trimestre, con su modelo.',
    autodespro: 'Informe completo de 10 secciones con ratios a cinco años.',
    proyecciones: 'Escenarios y previsión del ejercicio en curso.',
    fiscal: 'IVA, retenciones y vencimientos de los modelos 303 y 202.',
    conciliacion: 'Partidas pendientes de puntear y anomalías del mayor.',
    duplicados: 'Pares de asientos sospechosos con importe en riesgo.',
    memoria: 'Memoria de cuentas anuales (PGC PYME), 10 notas.',
    tesoreria: 'Cobros y pagos pendientes por antigüedad.',
  };
  return d[n] || '';
}

function pintarModulos() {
  const cont = $('listado-modulos');
  cont.innerHTML = '';
  const menus = (estado.menus && estado.menus.length) ? estado.menus : [{ clave: '', titulo: '' }];
  menus.forEach((m) => {
    const delMenu = estado.modulos.filter((x) => (x.menu || '') === m.clave);
    const pend = (estado.pendientes || []).filter((p) => p.menu === m.clave);
    if (!delMenu.length && !pend.length) return;

    const caja = document.createElement('div');
    if (m.titulo) {
      const h = document.createElement('div');
      h.className = 'titulo-menu';
      h.innerHTML = `${esc(m.titulo)}<span class="cuenta">${delMenu.length} informe${delMenu.length === 1 ? '' : 's'}${pend.length ? ' · ' + pend.length + ' en camino' : ''}</span>`;
      caja.appendChild(h);
    }
    const rejilla = document.createElement('div');
    rejilla.className = 'modulos';
    delMenu.forEach((mod) => rejilla.appendChild(tarjetaModulo(mod)));
    pend.forEach((p) => rejilla.appendChild(tarjetaPendiente(p)));
    caja.appendChild(rejilla);
    cont.appendChild(caja);
  });
}

function tarjetaModulo(m) {
  const div = document.createElement('div');
  div.className = 'modulo';
  div.id = 'modulo-' + m.nombre;
  div.innerHTML = `<div class="chip-tipo ${m.interno ? 'interno' : 'cliente'}">${m.interno ? 'Uso interno ABGA' : 'Cliente'}</div>
    <div class="titulo">${esc(m.titulo)}</div>
    <div class="descripcion">${esc(descripcionModulo(m.nombre))}</div>
    <div class="chips-meta">
      <span class="chip-meta">${m.ejercicios.length > 1 ? m.ejercicios.length + ' ejercicios' : 'ejercicio actual'}</span>
      ${Object.keys(m.parametros || {}).length ? `<span class="chip-meta">${Object.keys(m.parametros).length} parámetros</span>` : ''}
    </div>`;
  div.addEventListener('click', () => abrirInforme(m));
  return div;
}

/* Informe acordado con ABGA que todavía no está construido: se muestra para que el cliente vea
   lo que viene, sin dejar abrirlo. */
function tarjetaPendiente(p) {
  const div = document.createElement('div');
  div.className = 'modulo pendiente';
  div.title = 'Acordado con ABGA; todavía no está construido.';
  div.innerHTML = `<div class="chip-tipo">En camino</div>
    <div class="titulo">${esc(p.titulo)}</div>
    <div class="descripcion">Acordado con ABGA, pendiente de construir.</div>`;
  return div;
}

async function abrirInforme(modulo, forzar) {
  estado.moduloAbierto = modulo.nombre;
  $('informe-visor').hidden = false;
  $('informe-chip-tipo').textContent = modulo.interno ? 'Uso interno ABGA' : 'Cliente';
  $('informe-chip-tipo').className = 'chip-tipo ' + (modulo.interno ? 'interno' : 'cliente');
  $('informe-titulo').textContent = modulo.titulo;
  pintarParametros(modulo);

  const faltan = await ejerciciosQueFaltan(modulo);
  if (faltan.length) {
    $('informe-resultado').innerHTML = `<div class="aviso"><span class="punto info"></span><span>Primera consulta de este ejercicio al ERP: hay que leer ${faltan.join(', ')}. Tarda unos minutos; después queda en caché y sale al instante.</span></div>`;
    const ok = await leerDelErp();
    if (!ok) return;
  }

  $('informe-loading').hidden = false;
  $('informe-resultado').innerHTML = '';
  const params = paramsDelVisor();
  let r;
  try {
    r = await api('/api/informe', { method: 'POST', body: JSON.stringify({ modulo: modulo.nombre, cod_empresa: estado.empresa, year: estado.year, params, forzar: !!forzar }) });
  } catch (e) { r = { status: 'error', error: e.message }; }
  $('informe-loading').hidden = true;
  if (r.status !== 'ok') { $('informe-resultado').innerHTML = `<div class="aviso"><span class="punto error"></span><span>${esc(r.error || 'No se pudo generar el informe')}</span></div>`; return; }
  const avisos = (r.avisos || []).map((a) => `<div class="aviso"><span class="punto info"></span><span>${esc(a)}</span></div>`).join('');
  $('informe-resultado').innerHTML = avisos + r.html;
  $('informe-visor').scrollIntoView({ behavior: 'smooth', block: 'start' });
}

function paramsDelVisor() {
  const params = {};
  document.querySelectorAll('#informe-parametros [data-param]').forEach((i) => {
    if (i.value !== '') params[i.dataset.param] = isNaN(i.value) ? i.value : Number(i.value);
  });
  return params;
}

/* Descarga del informe para trabajarlo en Excel: las tablas del propio informe, una hoja por
   sección. El PDF lo hace el botón Imprimir con la impresión del navegador. */
async function descargarExcel() {
  if (!estado.moduloAbierto) return;
  const btn = $('btn-informe-excel'), texto = btn.textContent;
  btn.disabled = true; btn.textContent = 'Preparando…';
  try {
    const r = await fetch('/api/informe/exportar', {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ modulo: estado.moduloAbierto, cod_empresa: estado.empresa,
                             year: estado.year, params: paramsDelVisor() }),
    });
    if (!r.ok) {
      const d = await r.json().catch(() => ({}));
      toast(d.error || 'No se pudo exportar el informe', 'error');
      return;
    }
    const blob = await r.blob();
    const cd = r.headers.get('Content-Disposition') || '';
    const m = cd.match(/filename="?([^";]+)"?/i);
    const nombre = m ? m[1] : 'informe.csv';
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url; a.download = nombre;
    document.body.appendChild(a); a.click(); a.remove();
    URL.revokeObjectURL(url);
    const n = r.headers.get('X-Tablas');
    toast(`Descargado ${nombre}${n ? ' · ' + n + ' secciones' : ''}`, 'ok');
  } catch (e) {
    toast('No se pudo exportar: ' + e.message, 'error');
  } finally {
    btn.disabled = false; btn.textContent = texto;
  }
}

function pintarParametros(modulo) {
  const cont = $('informe-parametros'), params = modulo.parametros || {}, claves = Object.keys(params);
  if (!claves.length) { cont.innerHTML = ''; return; }
  cont.innerHTML = claves.map((k) => {
    if (k === 'trimestre') return `<label>Trimestre <select data-param="trimestre"><option value="">automático</option>${[1, 2, 3, 4].map((t) => `<option value="${t}">T${t}</option>`).join('')}</select></label>`;
    return `<label>${esc(k)} <input class="input sm" data-param="${esc(k)}" type="number" step="any" placeholder="${esc(params[k])}"></label>`;
  }).join('');
}

async function ejerciciosQueFaltan(modulo) {
  try {
    const r = await api('/api/cache?cod_empresa=' + encodeURIComponent(estado.empresa));
    const tengo = new Set((r.cache || []).map((c) => Number(c.ejercicio)));
    return (modulo.ejercicios || [0]).map((dd) => estado.year + dd).filter((y) => !tengo.has(y)).sort((a, b) => b - a);
  } catch (e) { return []; }
}

function leerDelErp() {
  return new Promise(async (resolve) => {
    const r = await api('/api/refrescar', { method: 'POST', body: JSON.stringify({ cod_empresa: estado.empresa, year: estado.year, forzar: false }) });
    if (r.status !== 'ok') { toast(r.error || 'No se pudo leer del ERP', 'error'); resolve(false); return; }
    const id = r.trabajo.id;
    clearInterval(estado.poll);
    estado.poll = setInterval(async () => {
      const t = (await api('/api/trabajos/' + id)).trabajo;
      if (!t) { clearInterval(estado.poll); resolve(false); return; }
      $('informe-loading').hidden = false;
      $('informe-loading').textContent = 'Leyendo del ERP ' + t.cod_empresa + '/' + t.year + ': ' + t.mensaje;
      if (t.estado !== 'en_curso') {
        clearInterval(estado.poll);
        $('informe-loading').hidden = true;
        $('informe-loading').textContent = 'Generando informe…';
        if (t.estado !== 'hecho') toast('La lectura del ERP falló: ' + t.mensaje, 'error');
        resolve(t.estado === 'hecho');
      }
    }, 1500);
  });
}

/* ============================ interno ============================ */

async function cargarInterno() {
  const r = await api('/api/interno/resumen' + (estado.empresa ? `?cod_empresa=${encodeURIComponent(estado.empresa)}` : ''));
  if (r.status !== 'ok') { toast(r.error || 'No se pudo cargar el panel interno', 'error'); return; }
  pintarTabla($('tabla-ejecuciones'), ['Fecha', 'Empresa', 'Módulo', 'Estado', 'Seg.', 'Caché'],
    (r.ejecuciones || []).map((e) => [new Date(e.instante).toLocaleString('es-ES'), esc(e.cod_empresa || '—'), esc(e.modulos), nivel(e.estado), e.segundos == null ? '—' : eur.format(e.segundos), e.desde_cache ? 'sí' : 'no']), [4]);
  pintarTabla($('tabla-cache'), ['Ejercicio', 'Asientos', 'Líneas', 'Cobertura', 'Actualizado', 'Seg.'],
    (r.cache || []).map((c) => [String(c.ejercicio), ent.format(c.n_asientos), ent.format(c.n_lineas), esc(c.cobertura || ''), esc((c.actualizado || '').replace('T', ' ').slice(0, 16)), c.segundos == null ? '—' : eur.format(c.segundos)]), [1, 2, 5]);
  $('trabajos-lista').innerHTML = (r.trabajos || []).map((t) => `<div class="progreso-item"><div class="progreso-cabecera"><span class="progreso-titulo">${esc(t.tipo)} ${esc(t.cod_empresa)}/${t.year} · ${nivel(t.estado)}</span><span class="progreso-valor">${Math.round(t.progreso * 100)} %</span></div><div class="progreso-pista"><div class="progreso-relleno" style="width:${(t.progreso * 100).toFixed(0)}%"></div></div><div class="progreso-titulo">${esc(t.mensaje)}</div></div>`).join('') || '<div class="aviso"><span class="punto info"></span><span>Sin trabajos en curso.</span></div>';
  pintarTabla($('tabla-estado-modulos'), ['Módulo', 'Título', 'Tipo', 'Estado'],
    (r.modulos || []).map((m) => [esc(m.nombre), esc(m.titulo), m.interno ? 'interno' : 'cliente', m.disponible ? '<span class="chip-estado ok">disponible</span>' : `<span class="chip-estado error">${esc(m.error || 'no disponible')}</span>`]));
  pintarTabla($('tabla-empresas'), ['Código', 'Nombre'], (r.empresas || []).map((e) => [esc(e.cod_empresa), esc(e.nombre)]));
  pintarTabla($('tabla-usuarios'), ['Email', 'Nombre', 'Rol', 'Empresas'],
    (r.usuarios || []).map((u) => [esc(u.email), esc(u.nombre), esc(u.rol), esc((u.empresas || []).join(', '))]));
}

const nivel = (e) => {
  const k = { ok: 'ok', error: 'error', error_erp: 'error', error_calculo: 'error', en_curso: 'aviso' }[e] || 'aviso';
  return `<span class="chip-estado ${k}">${esc(e)}</span>`;
};

/* ============================ eventos ============================ */

document.addEventListener('DOMContentLoaded', () => {
  $('form-login').addEventListener('submit', (e) => { e.preventDefault(); entrar($('login-email').value.trim(), $('login-password').value); });
  $('btn-rol-cliente').addEventListener('click', () => { $('login-email').value = 'cliente@mbdommo.com'; $('login-password').value = 'demo2025'; });
  $('btn-rol-interno').addEventListener('click', () => { $('login-email').value = 'admin@abgaconsultores.com'; $('login-password').focus(); });
  $('btn-salir').addEventListener('click', () => salir());
  $('btn-cerrar-banner').addEventListener('click', () => $('banner-usuario').hidden = true);

  $('select-empresa').addEventListener('change', async (e) => { estado.empresa = e.target.value; localStorage.setItem('abga_empresa', estado.empresa); await cargarEjercicios(); await cargarPanel(); if ($('vista-interno').classList.contains('visible')) await cargarInterno(); });
  $('select-ejercicio').addEventListener('change', async (e) => { estado.year = parseInt(e.target.value, 10); localStorage.setItem('abga_year', estado.year); $('ejercicio-en-curso').hidden = (estado.year !== new Date().getFullYear()); await cargarPanel(); if ($('vista-interno').classList.contains('visible')) await cargarInterno(); });

  document.querySelectorAll('.pestana').forEach((b) => {
    b.addEventListener('click', async () => {
      document.querySelectorAll('.pestana').forEach((x) => { x.classList.remove('activa'); x.setAttribute('aria-selected', 'false'); });
      b.classList.add('activa'); b.setAttribute('aria-selected', 'true');
      // OJO: sólo las vistas DE DENTRO del contenedor. El envoltorio de la aplicación
      // (#vista-app) también lleva la clase .vista; si se limpia su 'visible', al pulsar una
      // pestaña desaparece la aplicación entera y la pantalla se queda en blanco.
      document.querySelectorAll('.contenedor .vista').forEach((v) => v.classList.remove('visible'));
      const v = $('vista-' + b.dataset.tab);
      if (v) v.classList.add('visible');
      if (b.dataset.tab === 'interno') await cargarInterno();
    });
  });

  $('btn-informe-cerrar').addEventListener('click', () => $('informe-visor').hidden = true);
  $('btn-informe-actualizar').addEventListener('click', () => { const m = estado.modulos.find((x) => x.nombre === estado.moduloAbierto); if (m) abrirInforme(m, true); });
  $('btn-informe-imprimir').addEventListener('click', () => { const w = window.open('', '_blank'); w.document.write(`<html><head><title>ABGA · ${esc($('informe-titulo').textContent)}</title></head><body>${$('informe-resultado').innerHTML}</body></html>`); w.document.close(); w.focus(); w.print(); });
  $('btn-informe-excel').addEventListener('click', () => void descargarExcel());

  $('btn-refrescar-cache').addEventListener('click', async () => {
    const r = await api('/api/refrescar', { method: 'POST', body: JSON.stringify({ cod_empresa: estado.empresa, year: estado.year, forzar: true }) });
    toast(r.status === 'ok' ? 'Actualizando desde el ERP…' : (r.error || 'Error'), r.status === 'ok' ? 'ok' : 'error');
    if (r.status === 'ok') vigilarTrabajo(r.trabajo.id);
  });
  $('btn-borrar-cache').addEventListener('click', async () => {
    if (!confirm('¿Borrar los apuntes cacheados de esta empresa? La próxima consulta volverá a leer del ERP.')) return;
    const r = await api('/api/interno/cache', { method: 'POST', body: JSON.stringify({ cod_empresa: estado.empresa }) });
    toast(r.status === 'ok' ? `Caché borrada (${r.borrados} ejercicios)` : (r.error || 'Error'), r.status === 'ok' ? 'ok' : 'error');
    await cargarInterno();
  });

  $('form-alta-empresa').addEventListener('submit', async (e) => {
    e.preventDefault();
    const r = await api('/api/interno/empresas', { method: 'POST', body: JSON.stringify({ cod_empresa: $('alta-emp-codigo').value, nombre: $('alta-emp-nombre').value }) });
    toast(r.status === 'ok' ? 'Empresa creada' : (r.error || 'Error'), r.status === 'ok' ? 'ok' : 'error');
    if (r.status === 'ok') { e.target.reset(); await cargarInterno(); }
  });
  $('form-alta-usuario').addEventListener('submit', async (e) => {
    e.preventDefault();
    const rol = $('alta-us-rol').value === 'Interno ABGA' ? 'interno' : 'cliente';
    const r = await api('/api/interno/usuarios', { method: 'POST', body: JSON.stringify({ email: $('alta-us-email').value, nombre: $('alta-us-nombre').value, rol, empresas: [] }) });
    if (r.status === 'ok') {
      $('banner-usuario').hidden = false;
      $('banner-usuario-texto').innerHTML = `Usuario ${esc(r.email)} creado (${esc(r.rol)}). Contraseña temporal: <strong>${esc(r.password)}</strong> — cámbiala en el primer acceso.`;
      e.target.reset(); await cargarInterno();
    } else toast(r.error || 'Error', 'error');
  });

  // Soporta sesión por token (localStorage) y por cookie httpOnly: se intenta entrar siempre;
  // si el backend no reconoce la sesión, se vuelve al login.
  arrancar().catch(() => salir());
});
