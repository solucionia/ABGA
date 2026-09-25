// ============================================================
// REQ-06 — ALERTAS FISCALES
// Calcula IVA (472/477), retenciones (4751) y pago fraccionado IS
// desde los apuntes contables del ejercicio
// ============================================================

const tokens = $('Guardar Token').item.json;

// Extraer todas las líneas de detalle
const raw = $('GET Apuntes IVA y Retenciones').item.json;
const datos = raw?.Datos || raw?.datos || (Array.isArray(raw) ? raw : []);
const lineas = [];
datos.forEach(a => { if (a.Detalles) a.Detalles.forEach(d => lineas.push(d)); });

const fmt = (n) => typeof n === 'number' ? n.toLocaleString('es-ES',{minimumFractionDigits:2,maximumFractionDigits:2})+' €' : '—';
const fmtPct = (n) => typeof n === 'number' ? n.toFixed(1)+'%' : '—';

// Filtrar líneas por prefijo de cuenta
const porCuenta = (prefijos) => lineas.filter(l => prefijos.some(p => String(l.Cuenta||'').startsWith(p)));

// ---- IVA REPERCUTIDO (477) ----
// Haber - Debe = IVA devengado por ventas
const lineas477 = porCuenta(['477']);
const ivaRepercutido = lineas477.reduce((s,l) => s + (parseFloat(l.Haber||0) - parseFloat(l.Debe||0)), 0);

// ---- IVA SOPORTADO DEDUCIBLE (472) ----
// Debe - Haber = IVA deducible por compras
const lineas472 = porCuenta(['472']);
const ivaSoportado = lineas472.reduce((s,l) => s + (parseFloat(l.Debe||0) - parseFloat(l.Haber||0)), 0);

// Saldo IVA neto
const saldoIVA = ivaRepercutido - ivaSoportado;
const ivaAIngresar = saldoIVA > 0 ? saldoIVA : 0;
const ivaADevolver = saldoIVA < 0 ? Math.abs(saldoIVA) : 0;

// ---- IVA POR TRIMESTRE ----
const ivaTrimestreDetalle = [];
const trimestres = [
  { nombre: 'Q1', fechaIni: parseInt(tokens.year+'0101'), fechaFin: parseInt(tokens.year+'0331') },
  { nombre: 'Q2', fechaIni: parseInt(tokens.year+'0401'), fechaFin: parseInt(tokens.year+'0630') },
  { nombre: 'Q3', fechaIni: parseInt(tokens.year+'0701'), fechaFin: parseInt(tokens.year+'0930') },
  { nombre: 'Q4', fechaIni: parseInt(tokens.year+'1001'), fechaFin: parseInt(tokens.year+'1231') }
];

trimestres.forEach(t => {
  const lineasT = lineas.filter(l => {
    const f = parseInt(l.Fecha||0);
    return f >= t.fechaIni && f <= t.fechaFin;
  });
  const rep = lineasT.filter(l => String(l.Cuenta||'').startsWith('477'))
    .reduce((s,l) => s + (parseFloat(l.Haber||0) - parseFloat(l.Debe||0)), 0);
  const sop = lineasT.filter(l => String(l.Cuenta||'').startsWith('472'))
    .reduce((s,l) => s + (parseFloat(l.Debe||0) - parseFloat(l.Haber||0)), 0);
  const saldo = rep - sop;
  ivaTrimestreDetalle.push({
    trimestre: t.nombre,
    repercutido: fmt(rep),
    soportado: fmt(sop),
    saldo: fmt(saldo),
    resultado: saldo > 0 ? 'A ingresar' : saldo < 0 ? 'A devolver' : 'Cero',
    color: saldo > 0 ? '#c62828' : saldo < 0 ? '#2e7d32' : '#666'
  });
});

// ---- RETENCIONES IRPF (4751) ----
const lineas4751 = porCuenta(['4751']);
const retencionesIRPF = lineas4751.reduce((s,l) => s + (parseFloat(l.Haber||0) - parseFloat(l.Debe||0)), 0);

// ---- RETENCIONES POR TRIMESTRE ----
const retTrimestreDetalle = trimestres.map(t => {
  const lineasT = lineas4751.filter(l => {
    const f = parseInt(l.Fecha||0);
    return f >= t.fechaIni && f <= t.fechaFin;
  });
  const ret = lineasT.reduce((s,l) => s + (parseFloat(l.Haber||0) - parseFloat(l.Debe||0)), 0);
  return { trimestre: t.nombre, importe: fmt(ret) };
});

// ---- INGRESOS PARA PAGO FRACCIONADO IS (Mod. 202) ----
// Base: resultado contable estimado * 18%
const lineasIngresos = porCuenta(['700','701','702','703','704','705','706','708','709']);
const baseIngresos = lineasIngresos.reduce((s,l) => s + (parseFloat(l.Haber||0) - parseFloat(l.Debe||0)), 0);
const lineasGastos = porCuenta(['600','601','602','620','621','622','623','624','625','626','627','628','629','640','641','642','660','661','662','680','681','682']);
const baseGastos = lineasGastos.reduce((s,l) => s + (parseFloat(l.Debe||0) - parseFloat(l.Haber||0)), 0);
const baseIS = Math.max(0, baseIngresos - baseGastos);
const pagoFraccionadoIS = baseIS * 0.18;
const aplicaModelo202 = tokens.trimestre === 'Q1' || tokens.trimestre === 'Q3';

// ---- OBLIGACIONES TOTALES DEL TRIMESTRE ----
const trimIdx = ['Q1','Q2','Q3','Q4'].indexOf(tokens.trimestre);
const ivaTrimestreActual = ivaTrimestreDetalle[trimIdx];
const retTrimestreActual = retTrimestreDetalle[trimIdx];

const ivaTrimestreNum = ivaTrimestreDetalle[trimIdx] ?
  parseFloat(ivaTrimestreDetalle[trimIdx].saldo.replace(/\./g,'').replace(',','.').replace(' €','')) : 0;
const retTrimestreNum = parseFloat(retTrimestreDetalle[trimIdx]?.importe?.replace(/\./g,'').replace(',','.').replace(' €','') || '0');
const totalObligaciones = Math.max(0, ivaTrimestreNum) + Math.max(0, retTrimestreNum) + (aplicaModelo202 ? pagoFraccionadoIS : 0);

// ---- ALERTAS ----
const alertas = [];
if (ivaTrimestreNum > 10000) alertas.push({ nivel:'ALTA', msg:`IVA a ingresar este trimestre: ${fmt(ivaTrimestreNum)} — vence el ${tokens.fechaLimite}` });
else if (ivaTrimestreNum > 3000) alertas.push({ nivel:'MEDIA', msg:`IVA a ingresar: ${fmt(ivaTrimestreNum)} — presentar antes del ${tokens.fechaLimite}` });
else if (ivaTrimestreNum > 0) alertas.push({ nivel:'INFO', msg:`IVA a ingresar: ${fmt(ivaTrimestreNum)}` });
else if (ivaADevolver > 0) alertas.push({ nivel:'INFO', msg:`IVA acumulado a devolver: ${fmt(ivaADevolver)} — valorar solicitud` });
if (retTrimestreNum > 0) alertas.push({ nivel:'INFO', msg:`Retenciones IRPF ${tokens.trimestre}: ${fmt(retTrimestreNum)} — Modelo 111` });
if (aplicaModelo202 && pagoFraccionadoIS > 1000) alertas.push({ nivel:'INFO', msg:`Pago fraccionado IS estimado: ${fmt(pagoFraccionadoIS)} — Modelo 202` });

const nivelGlobal = alertas.some(a=>a.nivel==='ALTA') ? 'ALTA' : alertas.some(a=>a.nivel==='MEDIA') ? 'MEDIA' : 'INFO';

return [{ json: {
  empresa: tokens.empresaNombre,
  cod_empresa: tokens.cod_empresa,
  year: tokens.year,
  trimestre: tokens.trimestre,
  fechaLimite: tokens.fechaLimite,
  modelos: tokens.modelos,
  nivelGlobal,
  alertas: JSON.stringify(alertas),
  // IVA
  ivaRepercutido: fmt(ivaRepercutido),
  ivaSoportado: fmt(ivaSoportado),
  saldoIVA: fmt(saldoIVA),
  ivaAIngresar: fmt(ivaAIngresar),
  ivaADevolver: fmt(ivaADevolver),
  ivaTrimestreDetalle: JSON.stringify(ivaTrimestreDetalle),
  ivaTrimestreActual: JSON.stringify(ivaTrimestreActual),
  // Retenciones
  retencionesIRPF: fmt(retencionesIRPF),
  retTrimestreDetalle: JSON.stringify(retTrimestreDetalle),
  retTrimestreActual: JSON.stringify(retTrimestreActual),
  // IS
  baseIS: fmt(baseIS),
  pagoFraccionadoIS: fmt(pagoFraccionadoIS),
  aplicaModelo202,
  // Total
  totalObligaciones: fmt(totalObligaciones),
  totalLineas: lineas.length
}}];