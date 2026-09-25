// ============================================================
// REQ-03 — INFORME AUTODESPRO
// 10 secciones: Magnitudes, Evolución, PyG, Balance,
// Ventas, Proveedores, Tesorería, Partidas555, Personal, Ratios
// ============================================================

const tokens = $('Guardar Token').item.json;

const extraerLineas = (raw) => {
  const datos = raw?.Datos || raw?.datos || (Array.isArray(raw) ? raw : []);
  const lineas = [];
  datos.forEach(a => { if (a.Detalles) a.Detalles.forEach(d => lineas.push({...d, _fechaAsiento: a.Fecha})); });
  return lineas;
};

const L = extraerLineas($('GET Apuntes Año Principal').item.json);
const L1 = extraerLineas($('GET Apuntes Año Anterior').item.json);
const L2 = extraerLineas($('GET Apuntes Año -2').item.json);
const L3 = extraerLineas($('GET Apuntes Año -3').item.json);
const L4 = extraerLineas($('GET Apuntes Año -4').item.json);

const fmt = (n) => typeof n==='number' ? n.toLocaleString('es-ES',{minimumFractionDigits:2,maximumFractionDigits:2})+' €' : '—';
const fmtPct = (n) => typeof n==='number' ? (n>=0?'+':'')+n.toFixed(2)+'%' : '—';
const fmtVar = (a,b) => b!==0 ? fmtPct((a-b)/Math.abs(b)*100) : '—';

// Saldo deudor (activo/gasto): Debe - Haber
const sumaD = (lineas, pref) => lineas
  .filter(l => pref.some(p => String(l.Cuenta||'').startsWith(p)))
  .reduce((s,l) => s + parseFloat(l.Debe||0) - parseFloat(l.Haber||0), 0);

// Saldo acreedor (pasivo/ingreso): Haber - Debe
const sumaA = (lineas, pref) => lineas
  .filter(l => pref.some(p => String(l.Cuenta||'').startsWith(p)))
  .reduce((s,l) => s + parseFloat(l.Haber||0) - parseFloat(l.Debe||0), 0);

// Magnitudes de un set de líneas
const mag = (L) => {
  const ventas = sumaA(L,['700','701','702','703','704','705']);
  const otrosIng = sumaA(L,['706','708','709','74','75','76']);
  const totalIng = ventas + otrosIng;
  const aprov = sumaD(L,['600','601','602','606','607','608','609','610','611','612']);
  const gastPers = sumaD(L,['640','641','642','643','644','649']);
  const otrosGast = sumaD(L,['620','621','622','623','624','625','626','627','628','629','650','651']);
  const amort = sumaD(L,['680','681','682']);
  const gastFin = sumaD(L,['660','661','662','663','664','665','669']);
  const ingFin = sumaA(L,['760','761','762','769']);
  const ebitda = totalIng - aprov - gastPers - otrosGast;
  const ebit = ebitda - amort;
  const rai = ebit + ingFin - gastFin;
  const is = sumaD(L,['630']);
  const resultado = rai - is;
  const cashFlow = resultado + amort;
  // Balance
  const activoNC = sumaD(L,['200','201','202','203','204','205','206','207','208','209','210','211','212','213','214','215','216','217','218','219','280','281','282']);
  const existencias = sumaD(L,['300','301','302','303','304','305','306','307','308','309','310','311','312','313','314','315','316','317','318','319','320','321','322','323','324','325','326','327','328','329','330','331','332','333','334','335','336','337','338','339','340','341','342','343','344','345','346','347','348','349','350','351','352','353','354','355','356','357','358','359']);
  const clientes = sumaD(L,['430','431','432','433','434','435','436','437','438','439','440','441']);
  const tesoreria = sumaD(L,['570','571','572','573','574','575','576','577']);
  const otrosDeudores = sumaD(L,['460','470','471','472','473','474','476','480','481']);
  const activoC = existencias + clientes + otrosDeudores + tesoreria;
  const totalActivo = activoNC + activoC;
  const pn = sumaA(L,['100','101','102','103','104','108','109','110','111','112','113','114','115','116','117','118','119','120','121','130','131','132']) + resultado;
  const pasNC = sumaA(L,['150','151','152','153','154','155','156','157','158','159','160','161','162','163','164','165','166','167','168','169','170','171','172','173','174','175','176','177','178','179']);
  const proveedores = sumaA(L,['400','401','402','403','404','405','406','407','408','409','410','411','412','413','414','415','416','417','418','419']);
  const deudasCP = sumaA(L,['500','501','502','503','504','505','506','507','508','509','520','521','522','523','524','525','526','527','528','529','550','551','552','553','554','556','557','558','559','4750','4751','4752','4758','4759','475','477']);
  const pasC = proveedores + deudasCP;
  const fm = activoC - pasC;
  return { ventas,otrosIng,totalIng,aprov,gastPers,otrosGast,amort,gastFin,ingFin,ebitda,ebit,rai,is,resultado,cashFlow,activoNC,existencias,clientes,tesoreria,otrosDeudores,activoC,totalActivo,pn,pasNC,proveedores,deudasCP,pasC,fm };
};

const m = mag(L);
const m1 = mag(L1);
const m2 = mag(L2);
const m3 = mag(L3);
const m4 = mag(L4);

// ---- Evolución mensual de ventas ----
const mesesNombre = ['Ene','Feb','Mar','Abr','May','Jun','Jul','Ago','Sep','Oct','Nov','Dic'];
const evMensual = mesesNombre.map((nombre, i) => {
  const mesStr = String(i+1).padStart(2,'0');
  const fechaIni = parseInt(tokens.year + mesStr + '01');
  const fechaFin = parseInt(tokens.year + mesStr + '31');
  const lMes = L.filter(l => { const f = parseInt(l.Fecha||0); return f >= fechaIni && f <= fechaFin; });
  return { mes: nombre, ventas: sumaA(lMes,['700','701','702','703','704','705','706','708','709']), gastos: sumaD(lMes,['600','601','602','640','641','642','620','621','622','623','624','625','626','627','628','629']) };
});

// ---- Partidas pendientes cuenta 555 ----
const partidas555 = L.filter(l => String(l.Cuenta||'').startsWith('555')).slice(0,10).map(l => ({
  fecha: String(l.Fecha||''), concepto: l.Descripcion||l.Concepto||'',
  debe: fmt(parseFloat(l.Debe||0)), haber: fmt(parseFloat(l.Haber||0))
}));

// ---- Ratios 5 años ----
const ratio = (m) => ({
  pruebaAcida: m.pasC > 0 ? ((m.clientes + m.tesoreria) / m.pasC) : 0,
  solvencia: m.pasC > 0 ? m.activoC / m.pasC : 0,
  endeudamiento: m.totalActivo > 0 ? (m.pasNC + m.pasC) / m.totalActivo * 100 : 0,
  garantia: (m.pasNC + m.pasC) > 0 ? m.totalActivo / (m.pasNC + m.pasC) : 0,
  roe: m.pn > 0 ? m.resultado / m.pn * 100 : 0,
  roa: m.totalActivo > 0 ? m.ebit / m.totalActivo * 100 : 0
});

const r = ratio(m);
const r1 = ratio(m1);
const r2 = ratio(m2);
const r3 = ratio(m3);
const r4 = ratio(m4);

// ---- Construir datos para el agente ----
return [{ json: {
  empresa: tokens.empresaNombre,
  year: tokens.year, yearAnterior: tokens.yearAnterior,
  year2: tokens.year2, year3: tokens.year3, year4: tokens.year4,
  // Sección 1: Principales magnitudes (5 años)
  magnitudes: JSON.stringify([
    { desc:'Importe neto cifra de negocios', v:[fmt(m4.totalIng),fmt(m3.totalIng),fmt(m2.totalIng),fmt(m1.totalIng),fmt(m.totalIng)] },
    { desc:'Resultado del ejercicio', v:[fmt(m4.resultado),fmt(m3.resultado),fmt(m2.resultado),fmt(m1.resultado),fmt(m.resultado)] },
    { desc:'EBITDA', v:[fmt(m4.ebitda),fmt(m3.ebitda),fmt(m2.ebitda),fmt(m1.ebitda),fmt(m.ebitda)] },
    { desc:'Activo total', v:[fmt(m4.totalActivo),fmt(m3.totalActivo),fmt(m2.totalActivo),fmt(m1.totalActivo),fmt(m.totalActivo)] },
    { desc:'Patrimonio neto', v:[fmt(m4.pn),fmt(m3.pn),fmt(m2.pn),fmt(m1.pn),fmt(m.pn)] },
    { desc:'Pasivo corriente', v:[fmt(m4.pasC),fmt(m3.pasC),fmt(m2.pasC),fmt(m1.pasC),fmt(m.pasC)] },
    { desc:'Fondo de maniobra', v:[fmt(m4.fm),fmt(m3.fm),fmt(m2.fm),fmt(m1.fm),fmt(m.fm)] },
    { desc:'Tesorería', v:[fmt(m4.tesoreria),fmt(m3.tesoreria),fmt(m2.tesoreria),fmt(m1.tesoreria),fmt(m.tesoreria)] }
  ]),
  // Sección 3: PyG comparativa
  pyg: JSON.stringify([
    { desc:'Ventas', actual:fmt(m.ventas), pctA:m.totalIng>0?(m.ventas/m.totalIng*100).toFixed(1)+'%':'—', ant:fmt(m1.ventas), pctAnt:m1.totalIng>0?(m1.ventas/m1.totalIng*100).toFixed(1)+'%':'—', var:fmtVar(m.ventas,m1.ventas) },
    { desc:'Otros ingresos', actual:fmt(m.otrosIng), pctA:m.totalIng>0?(m.otrosIng/m.totalIng*100).toFixed(1)+'%':'—', ant:fmt(m1.otrosIng), pctAnt:'—', var:fmtVar(m.otrosIng,m1.otrosIng) },
    { desc:'TOTAL INGRESOS', actual:fmt(m.totalIng), pctA:'100%', ant:fmt(m1.totalIng), pctAnt:'100%', var:fmtVar(m.totalIng,m1.totalIng), bold:true },
    { desc:'Aprovisionamientos', actual:fmt(-m.aprov), pctA:m.totalIng>0?(m.aprov/m.totalIng*100).toFixed(1)+'%':'—', ant:fmt(-m1.aprov), pctAnt:'—', var:fmtVar(m.aprov,m1.aprov) },
    { desc:'MARGEN BRUTO', actual:fmt(m.totalIng-m.aprov), pctA:m.totalIng>0?((m.totalIng-m.aprov)/m.totalIng*100).toFixed(1)+'%':'—', ant:fmt(m1.totalIng-m1.aprov), pctAnt:'—', var:fmtVar(m.totalIng-m.aprov,m1.totalIng-m1.aprov), bold:true },
    { desc:'Gastos de personal', actual:fmt(-m.gastPers), pctA:m.totalIng>0?(m.gastPers/m.totalIng*100).toFixed(1)+'%':'—', ant:fmt(-m1.gastPers), pctAnt:'—', var:fmtVar(m.gastPers,m1.gastPers) },
    { desc:'Otros gastos explotación', actual:fmt(-m.otrosGast), pctA:m.totalIng>0?(m.otrosGast/m.totalIng*100).toFixed(1)+'%':'—', ant:fmt(-m1.otrosGast), pctAnt:'—', var:fmtVar(m.otrosGast,m1.otrosGast) },
    { desc:'EBITDA', actual:fmt(m.ebitda), pctA:m.totalIng>0?(m.ebitda/m.totalIng*100).toFixed(1)+'%':'—', ant:fmt(m1.ebitda), pctAnt:'—', var:fmtVar(m.ebitda,m1.ebitda), bold:true },
    { desc:'Amortizaciones', actual:fmt(-m.amort), pctA:m.totalIng>0?(m.amort/m.totalIng*100).toFixed(1)+'%':'—', ant:fmt(-m1.amort), pctAnt:'—', var:fmtVar(m.amort,m1.amort) },
    { desc:'RESULTADO EXPLOTACIÓN', actual:fmt(m.ebit), pctA:m.totalIng>0?(m.ebit/m.totalIng*100).toFixed(1)+'%':'—', ant:fmt(m1.ebit), pctAnt:'—', var:fmtVar(m.ebit,m1.ebit), bold:true },
    { desc:'Resultado financiero', actual:fmt(m.ingFin-m.gastFin), pctA:'—', ant:fmt(m1.ingFin-m1.gastFin), pctAnt:'—', var:fmtVar(m.ingFin-m.gastFin,m1.ingFin-m1.gastFin) },
    { desc:'RESULTADO ANTES IMPUESTOS', actual:fmt(m.rai), pctA:m.totalIng>0?(m.rai/m.totalIng*100).toFixed(1)+'%':'—', ant:fmt(m1.rai), pctAnt:'—', var:fmtVar(m.rai,m1.rai), bold:true },
    { desc:'Impuesto Sociedades', actual:fmt(-m.is), pctA:'—', ant:fmt(-m1.is), pctAnt:'—', var:'—' },
    { desc:'RESULTADO DEL EJERCICIO', actual:fmt(m.resultado), pctA:m.totalIng>0?(m.resultado/m.totalIng*100).toFixed(1)+'%':'—', ant:fmt(m1.resultado), pctAnt:'—', var:fmtVar(m.resultado,m1.resultado), bold:true, total:true },
    { desc:'Cash-Flow', actual:fmt(m.cashFlow), pctA:'—', ant:fmt(m1.cashFlow), pctAnt:'—', var:fmtVar(m.cashFlow,m1.cashFlow) }
  ]),
  // Sección 4: Balance
  balanceActivo: JSON.stringify([
    { desc:'Activo no corriente', v:fmt(m.activoNC), vAnt:fmt(m1.activoNC) },
    { desc:'Existencias', v:fmt(m.existencias), vAnt:fmt(m1.existencias) },
    { desc:'Clientes y deudores', v:fmt(m.clientes+m.otrosDeudores), vAnt:fmt(m1.clientes+m1.otrosDeudores) },
    { desc:'Tesorería', v:fmt(m.tesoreria), vAnt:fmt(m1.tesoreria) },
    { desc:'Activo corriente', v:fmt(m.activoC), vAnt:fmt(m1.activoC), bold:true },
    { desc:'TOTAL ACTIVO', v:fmt(m.totalActivo), vAnt:fmt(m1.totalActivo), bold:true, total:true }
  ]),
  balancePasivo: JSON.stringify([
    { desc:'Patrimonio neto', v:fmt(m.pn), vAnt:fmt(m1.pn) },
    { desc:'Pasivo no corriente', v:fmt(m.pasNC), vAnt:fmt(m1.pasNC) },
    { desc:'Proveedores', v:fmt(m.proveedores), vAnt:fmt(m1.proveedores) },
    { desc:'Otras deudas C/P', v:fmt(m.deudasCP), vAnt:fmt(m1.deudasCP) },
    { desc:'Pasivo corriente', v:fmt(m.pasC), vAnt:fmt(m1.pasC), bold:true },
    { desc:'TOTAL PASIVO+PN', v:fmt(m.totalActivo), vAnt:fmt(m1.totalActivo), bold:true, total:true }
  ]),
  // Sección 5: Ventas mensuales
  evMensual: JSON.stringify(evMensual.map(e => ({ mes:e.mes, ventas:fmt(e.ventas), gastos:fmt(e.gastos), resultado:fmt(e.ventas-e.gastos) }))),
  // Sección 8: Partidas 555
  partidas555: JSON.stringify(partidas555),
  // Sección 10: Ratios 5 años
  ratios: JSON.stringify([
    { nombre:'Prueba ácida', optimo:'0,8–1,0', v:[r4.pruebaAcida.toFixed(2),r3.pruebaAcida.toFixed(2),r2.pruebaAcida.toFixed(2),r1.pruebaAcida.toFixed(2),r.pruebaAcida.toFixed(2)] },
    { nombre:'Ratio solvencia', optimo:'1,50', v:[r4.solvencia.toFixed(2),r3.solvencia.toFixed(2),r2.solvencia.toFixed(2),r1.solvencia.toFixed(2),r.solvencia.toFixed(2)] },
    { nombre:'Endeudamiento s/activo', optimo:'50%', v:[r4.endeudamiento.toFixed(1)+'%',r3.endeudamiento.toFixed(1)+'%',r2.endeudamiento.toFixed(1)+'%',r1.endeudamiento.toFixed(1)+'%',r.endeudamiento.toFixed(1)+'%'] },
    { nombre:'Ratio de garantía', optimo:'>1,20', v:[r4.garantia.toFixed(2),r3.garantia.toFixed(2),r2.garantia.toFixed(2),r1.garantia.toFixed(2),r.garantia.toFixed(2)] },
    { nombre:'ROE', optimo:'>10%', v:[r4.roe.toFixed(2)+'%',r3.roe.toFixed(2)+'%',r2.roe.toFixed(2)+'%',r1.roe.toFixed(2)+'%',r.roe.toFixed(2)+'%'] },
    { nombre:'ROA', optimo:'>5%', v:[r4.roa.toFixed(2)+'%',r3.roa.toFixed(2)+'%',r2.roa.toFixed(2)+'%',r1.roa.toFixed(2)+'%',r.roa.toFixed(2)+'%'] }
  ]),
  // Resumen ejecutivo
  totalIngresos: fmt(m.totalIng), resultadoNeto: fmt(m.resultado),
  ebitda: fmt(m.ebitda), tesoreria: fmt(m.tesoreria), fondoManiobra: fmt(m.fm),
  totalLineas: L.length
}}];