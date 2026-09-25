// ============================================================
// REQ-02 — PROYECCIONES FINANCIERAS
// Regresión lineal ponderada sobre histórico 4 años
// Horizonte: próximo ejercicio completo + desglose trimestral
// ============================================================

const tokens = $('Guardar Token').item.json;

const extraerLineas = (raw) => {
  const datos = raw?.Datos || raw?.datos || (Array.isArray(raw) ? raw : []);
  const lineas = [];
  datos.forEach(a => { if (a.Detalles) a.Detalles.forEach(d => lineas.push(d)); });
  return lineas;
};

const L = extraerLineas($('GET Apuntes Año Actual').item.json);
const L1 = extraerLineas($('GET Apuntes Año -1').item.json);
const L2 = extraerLineas($('GET Apuntes Año -2').item.json);
const L3 = extraerLineas($('GET Apuntes Año -3').item.json);

const fmt = (n) => typeof n==='number' ? n.toLocaleString('es-ES',{minimumFractionDigits:2,maximumFractionDigits:2})+' €' : '—';
const fmtPct = (n) => typeof n==='number' ? (n>=0?'+':'')+n.toFixed(1)+'%' : '—';

const sumaA = (lineas, pref) => lineas
  .filter(l => pref.some(p => String(l.Cuenta||'').startsWith(p)))
  .reduce((s,l) => s + parseFloat(l.Haber||0) - parseFloat(l.Debe||0), 0);

const sumaD = (lineas, pref) => lineas
  .filter(l => pref.some(p => String(l.Cuenta||'').startsWith(p)))
  .reduce((s,l) => s + parseFloat(l.Debe||0) - parseFloat(l.Haber||0), 0);

const magnitudes = (L) => ({
  ingresos: sumaA(L,['700','701','702','703','704','705','706','708','709']),
  aprov: sumaD(L,['600','601','602','606','607','608','609','610','611','612']),
  gastPers: sumaD(L,['640','641','642','643','644','649']),
  otrosGast: sumaD(L,['620','621','622','623','624','625','626','627','628','629','650','651']),
  amort: sumaD(L,['680','681','682']),
  gastFin: sumaD(L,['660','661','662','663','664','665','669']),
  tesoreria: sumaD(L,['570','571','572','573','574','575','576','577'])
});

const m = magnitudes(L);
const m1 = magnitudes(L1);
const m2 = magnitudes(L2);
const m3 = magnitudes(L3);

// ---- Regresión lineal ponderada ----
// Pesos: año más reciente tiene más peso [1,2,3,4]
const regresion = (valores) => {
  const validos = valores.filter(v => v !== 0 && !isNaN(v));
  if (validos.length < 2) return { proyeccion: valores[valores.length-1] || 0, tendencia: 'ESTABLE', tasaCrecimiento: 0 };
  const n = valores.length;
  const pesos = valores.map((_,i) => i+1);
  const mediaY = valores.reduce((s,v,i) => s + v*pesos[i], 0) / pesos.reduce((s,p)=>s+p,0);
  const xs = valores.map((_,i) => i);
  const mediaX = xs.reduce((s,x)=>s+x,0)/n;
  const num = xs.reduce((s,x,i) => s + (x-mediaX)*(valores[i]-mediaY), 0);
  const den = xs.reduce((s,x) => s + Math.pow(x-mediaX,2), 0);
  const pendiente = den !== 0 ? num/den : 0;
  const intercepto = mediaY - pendiente*mediaX;
  const proyeccion = Math.max(0, intercepto + pendiente*n);
  const primer = validos[0];
const ultimo = validos[validos.length-1];
  const tasaCrecimiento = primer > 0 ? (ultimo/primer - 1)*100/(validos.length-1) : 0;
  return {
    proyeccion,
    tendencia: pendiente > mediaY*0.05 ? 'CRECIENTE' : pendiente < -mediaY*0.05 ? 'DECRECIENTE' : 'ESTABLE',
    tasaCrecimiento
  };
};

// Series históricas [año-3, año-2, año-1, año actual]
const serieIngresos = [m3.ingresos, m2.ingresos, m1.ingresos, m.ingresos];
const serieAprov = [m3.aprov, m2.aprov, m1.aprov, m.aprov];
const serieGastPers = [m3.gastPers, m2.gastPers, m1.gastPers, m.gastPers];
const serieOtrosGast = [m3.otrosGast, m2.otrosGast, m1.otrosGast, m.otrosGast];
const serieGastFin = [m3.gastFin, m2.gastFin, m1.gastFin, m.gastFin];
const serieTesoreria = [m3.tesoreria, m2.tesoreria, m1.tesoreria, m.tesoreria];

const pIngresos = regresion(serieIngresos);
const pAprov = regresion(serieAprov);
const pGastPers = regresion(serieGastPers);
const pOtrosGast = regresion(serieOtrosGast);
const pGastFin = regresion(serieGastFin);
const pTesoreria = regresion(serieTesoreria);

// PyG proyectada
const ingProy = pIngresos.proyeccion;
const aprovProy = pAprov.proyeccion;
const gastPersProy = pGastPers.proyeccion;
const otrosGastProy = pOtrosGast.proyeccion;
const amortProy = m.amort;
const gastFinProy = pGastFin.proyeccion;
const ebitdaProy = ingProy - aprovProy - gastPersProy - otrosGastProy;
const ebitProy = ebitdaProy - amortProy;
const raiProy = ebitProy - gastFinProy;
const isProy = raiProy > 0 ? raiProy * 0.25 : 0;
const resultadoProy = raiProy - isProy;
const margenProy = ingProy > 0 ? resultadoProy/ingProy*100 : 0;

// Escenarios
const optimista = { ing: ingProy*1.15, gast: (aprovProy+gastPersProy+otrosGastProy)*0.95 };
const pesimista = { ing: ingProy*0.85, gast: (aprovProy+gastPersProy+otrosGastProy)*1.05 };
const calcRes = (ing, gast) => { const ebitda=ing-gast; const rai=ebitda-amortProy-gastFinProy; return Math.max(-ing, rai*(rai>0?0.75:1)); };

// Distribución trimestral estacional (basada en el año actual)
const mesesNombre = ['Ene','Feb','Mar','Abr','May','Jun','Jul','Ago','Sep','Oct','Nov','Dic'];
const ingMensuales = mesesNombre.map((_,i) => {
  const mesStr = String(i+1).padStart(2,'0');
  const fechaIni = parseInt(tokens.year + mesStr + '01');
  const fechaFin = parseInt(tokens.year + mesStr + '31');
  const lMes = L.filter(l => { const f = parseInt(l.Fecha||0); return f >= fechaIni && f <= fechaFin; });
  return sumaA(lMes,['700','701','702','703','704','705','706','708','709']);
});
const totalMensual = ingMensuales.reduce((s,v)=>s+v,0);
const pesos = ingMensuales.map(v => totalMensual > 0 ? v/totalMensual : 1/12);
const trimQ = [0,1,2,3].map(q => ({
  trimestre: `Q${q+1}`,
  ingProy: fmt(ingProy * pesos.slice(q*3,(q+1)*3).reduce((s,p)=>s+p,0)),
  resultProy: fmt(resultadoProy * pesos.slice(q*3,(q+1)*3).reduce((s,p)=>s+p,0))
}));

// Alertas
const alertas = [];
if (pIngresos.tendencia === 'DECRECIENTE') alertas.push({ nivel:'ALTA', msg:`Tendencia de ingresos decreciente (${fmtPct(pIngresos.tasaCrecimiento)}/año). Se proyecta reducción en ${tokens.yearProyectado}.` });
if (pGastPers.tendencia === 'CRECIENTE' && pGastPers.tasaCrecimiento > 10) alertas.push({ nivel:'MEDIA', msg:`Gastos de personal en crecimiento acelerado (${fmtPct(pGastPers.tasaCrecimiento)}/año).` });
if (margenProy < 5) alertas.push({ nivel:'MEDIA', msg:`Margen neto proyectado bajo (${fmtPct(margenProy)}). Margen de seguridad reducido.` });
if (pTesoreria.tendencia === 'DECRECIENTE') alertas.push({ nivel:'ALTA', msg:`Tesorería con tendencia decreciente. Posible tensión de liquidez.` });
if (alertas.length === 0) alertas.push({ nivel:'INFO', msg:'Proyecciones estables. Sin alertas relevantes para el próximo ejercicio.' });

const nivelGlobal = alertas.some(a=>a.nivel==='ALTA') ? 'ALTA' : alertas.some(a=>a.nivel==='MEDIA') ? 'MEDIA' : 'INFO';

return [{ json: {
  empresa: tokens.empresaNombre,
  year: tokens.year, yearAnterior: tokens.yearAnterior,
  year2: tokens.year2, year3: tokens.year3,
  yearProyectado: tokens.yearProyectado,
  nivelGlobal,
  alertas: JSON.stringify(alertas),
  // Histórico
  historico: JSON.stringify([
    { year: tokens.year3, ingresos: fmt(m3.ingresos), resultado: fmt(m3.ingresos-m3.aprov-m3.gastPers-m3.otrosGast-m3.amort-m3.gastFin), tesoreria: fmt(m3.tesoreria) },
    { year: tokens.year2, ingresos: fmt(m2.ingresos), resultado: fmt(m2.ingresos-m2.aprov-m2.gastPers-m2.otrosGast-m2.amort-m2.gastFin), tesoreria: fmt(m2.tesoreria) },
    { year: tokens.yearAnterior, ingresos: fmt(m1.ingresos), resultado: fmt(m1.ingresos-m1.aprov-m1.gastPers-m1.otrosGast-m1.amort-m1.gastFin), tesoreria: fmt(m1.tesoreria) },
    { year: tokens.year, ingresos: fmt(m.ingresos), resultado: fmt(m.ingresos-m.aprov-m.gastPers-m.otrosGast-m.amort-m.gastFin), tesoreria: fmt(m.tesoreria) }
  ]),
  // PyG proyectada
  ingProy: fmt(ingProy), aprovProy: fmt(aprovProy),
  gastPersProy: fmt(gastPersProy), otrosGastProy: fmt(otrosGastProy),
  ebitdaProy: fmt(ebitdaProy), ebitProy: fmt(ebitProy),
  gastFinProy: fmt(gastFinProy), raiProy: fmt(raiProy),
  isProy: fmt(isProy), resultadoProy: fmt(resultadoProy),
  margenProy: fmtPct(margenProy),
  // Tendencias
  tendenciaIngresos: pIngresos.tendencia,
  tasaIngresos: fmtPct(pIngresos.tasaCrecimiento),
  tendenciaGastPers: pGastPers.tendencia,
  tendenciaTesoreria: pTesoreria.tendencia,
  // Escenarios
  escOptIng: fmt(optimista.ing), escOptRes: fmt(calcRes(optimista.ing, optimista.gast)),
  escBaseIng: fmt(ingProy), escBaseRes: fmt(resultadoProy),
  escPesIng: fmt(pesimista.ing), escPesRes: fmt(calcRes(pesimista.ing, pesimista.gast)),
  // Trimestral
  trimQ: JSON.stringify(trimQ),
  totalLineas: L.length
}}];