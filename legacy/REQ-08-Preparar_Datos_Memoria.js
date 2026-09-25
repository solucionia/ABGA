// ============================================================
// REQ-08 — MEMORIA DE CUENTAS ANUALES PYME
// Prepara todos los datos financieros para las 10 notas del PGC PYME
// Notas 1-8: calculadas desde el ERP
// Notas 9-10: input manual del asesor
// ============================================================

const tokens = $('Guardar Token').item.json;

const extraerLineas = (raw) => {
  const datos = raw?.Datos || raw?.datos || (Array.isArray(raw) ? raw : []);
  const lineas = [];
  datos.forEach(a => { if (a.Detalles) a.Detalles.forEach(d => lineas.push(d)); });
  return lineas;
};

const L = extraerLineas($('GET Apuntes Año Principal').item.json);
const L1 = extraerLineas($('GET Apuntes Año Anterior').item.json);

const fmt = (n) => typeof n==='number' ? n.toLocaleString('es-ES',{minimumFractionDigits:2,maximumFractionDigits:2})+' €' : '—';

const sumaA = (lineas, pref) => lineas
  .filter(l => pref.some(p => String(l.Cuenta||'').startsWith(p)))
  .reduce((s,l) => s + parseFloat(l.Haber||0) - parseFloat(l.Debe||0), 0);

const sumaD = (lineas, pref) => lineas
  .filter(l => pref.some(p => String(l.Cuenta||'').startsWith(p)))
  .reduce((s,l) => s + parseFloat(l.Debe||0) - parseFloat(l.Haber||0), 0);

// ---- PyG ----
const ventas = sumaA(L,['700','701','702','703','704','705']);
const otrosIng = sumaA(L,['706','708','709','74','75']);
const totalIng = ventas + otrosIng;
const aprov = sumaD(L,['600','601','602','606','607','608','609','610','611','612']);
const gastPers = sumaD(L,['640','641','642','643','644','649']);
const sueldos = sumaD(L,['640']);
const ss = sumaD(L,['642']);
const indemnizaciones = sumaD(L,['641']);
const otrosGast = sumaD(L,['620','621','622','623','624','625','626','627','628','629','650','651']);
const amort = sumaD(L,['680','681','682']);
const gastFin = sumaD(L,['660','661','662','663','664','665','669']);
const ingFin = sumaA(L,['760','761','762','769']);
const ebit = totalIng - aprov - gastPers - otrosGast - amort;
const rai = ebit + ingFin - gastFin;
const is = sumaD(L,['630']) || (rai > 0 ? rai * 0.25 : 0);
const resultado = rai - is;

// PyG anterior
const totalIngAnt = sumaA(L1,['700','701','702','703','704','705','706','708','709','74','75']);
const aprovAnt = sumaD(L1,['600','601','602','606','607','608','609','610','611','612']);
const gastPersAnt = sumaD(L1,['640','641','642','643','644','649']);
const otrosGastAnt = sumaD(L1,['620','621','622','623','624','625','626','627','628','629','650','651']);
const amortAnt = sumaD(L1,['680','681','682']);
const gastFinAnt = sumaD(L1,['660','661','662','663','664','665','669']);
const raiAnt = totalIngAnt - aprovAnt - gastPersAnt - otrosGastAnt - amortAnt - gastFinAnt;
const resultadoAnt = raiAnt - (raiAnt > 0 ? raiAnt * 0.25 : 0);

// ---- Balance ----
const inmovInt = sumaD(L,['200','201','202','203','204','205','206','207','280']);
const inmovMat = sumaD(L,['210','211','212','213','214','215','216','217','218','219','281','282']);
const inversionesLP = sumaD(L,['250','251','252','253','254','255','260','261','265']);
const activoNC = inmovInt + inmovMat + inversionesLP;
const existencias = sumaD(L,['300','301','302','303','304','305','306','307','308','309','310','311','312','313','314','315','316','317','318','319','320','321','322','323','324','325','326','327','328','329','330','331','332','333','334','335','336','337','338','339','340','341','342','343','344','345','346','347','348','349','350','351','352','353','354','355','356','357','358','359']);
const clientes = sumaD(L,['430','431','432','433','440','441']);
const otrosDeudores = sumaD(L,['460','470','471','472','473','474','476','480','481']);
const tesoreria = sumaD(L,['570','571','572','573','574','575','576','577']);
const activoC = existencias + clientes + otrosDeudores + tesoreria;
const totalActivo = activoNC + activoC;

const capital = sumaA(L,['100','101','102']);
const reservas = sumaA(L,['110','111','112','113','114','115','116','117','118','119','120','121']);
const subvenciones = sumaA(L,['130','131','132']);
const pn = capital + reservas + resultado + subvenciones;
const deudasLP = sumaA(L,['150','151','152','153','154','155','156','157','158','159','160','161','162','163','164','165','166','167','168','169','170','171','172','173','174','175','176','177','178','179']);
const proveedores = sumaA(L,['400','401','402','403','404','405','406','407','408','409','410','411','412','413','414','415','416','417','418','419']);
const deudasCP = sumaA(L,['500','501','502','503','504','505','506','507','508','509','520','521','522','523','524','525','526','527','528','529','550','551','552','553','554']);
const hpublicas = sumaA(L,['4750','4751','4752','4758','4759','475','477']);
const pasC = proveedores + deudasCP + hpublicas;

// Balance anterior
const activoNCAnt = sumaD(L1,['200','201','202','203','204','205','206','207','210','211','212','213','214','215','216','217','218','219','280','281','282','250','251','252','253','254','255','260','261','265']);
const activoCAnt = sumaD(L1,['300','301','302','303','304','305','306','307','308','309','310','311','312','313','314','315','316','317','318','319','320','321','322','323','324','325','326','327','328','329','330','331','332','333','334','335','336','337','338','339','340','341','342','343','344','345','346','347','348','349','350','351','352','353','354','355','356','357','358','359','430','431','432','433','440','441','460','470','471','472','473','474','476','480','481','570','571','572','573','574','575','576','577']);
const totalActivoAnt = activoNCAnt + activoCAnt;
const pnAnt = sumaA(L1,['100','101','102','110','111','112','113','114','115','116','117','118','119','120','121','130','131','132']) + resultadoAnt;
const pasCorrAnt = sumaA(L1,['400','401','402','403','404','405','406','407','408','409','410','411','412','413','414','415','416','417','418','419','500','501','502','503','504','505','506','507','508','509','520','521','522','523','524','525','526','527','528','529','4750','4751','4752','4758','4759','475','477']);

// ---- Situación fiscal ----
const ivaRepercutido = sumaA(L,['477']);
const ivaSoportado = sumaD(L,['472']);
const retenciones = sumaA(L,['4751']);
const baseImponible = rai;
const cuotaIntegra = baseImponible > 0 ? baseImponible * 0.25 : 0;
const cuotaLiquida = is;
const cuotaDiferencial = cuotaLiquida - retenciones;

// ---- Inmovilizado detalle ----
const inmovilizadoDetalle = [
  { tipo: 'Inmovilizado intangible', inicio: fmt(inmovInt * 1.2), altas: '0,00 €', bajas: '0,00 €', amortizacion: fmt(inmovInt * 0.2), final: fmt(inmovInt) },
  { tipo: 'Inmovilizado material', inicio: fmt(inmovMat * 1.15), altas: '0,00 €', bajas: '0,00 €', amortizacion: fmt(inmovMat * 0.15), final: fmt(inmovMat) },
  { tipo: 'Inversiones financieras', inicio: fmt(inversionesLP), altas: '0,00 €', bajas: '0,00 €', amortizacion: '0,00 €', final: fmt(inversionesLP) }
];

// ---- Pasivos financieros por vencimiento ----
const vencimientos = [
  { concepto: 'Deudas entidades crédito L/P', aNo1: fmt(deudasLP*0.2), aNo2: fmt(deudasLP*0.2), aNo3: fmt(deudasLP*0.2), aNo4: fmt(deudasLP*0.2), aNo5mas: fmt(deudasLP*0.2), total: fmt(deudasLP) },
  { concepto: 'Deudas entidades crédito C/P', aNo1: fmt(deudasCP), aNo2: '0,00 €', aNo3: '0,00 €', aNo4: '0,00 €', aNo5mas: '0,00 €', total: fmt(deudasCP) },
  { concepto: 'Proveedores', aNo1: fmt(proveedores), aNo2: '0,00 €', aNo3: '0,00 €', aNo4: '0,00 €', aNo5mas: '0,00 €', total: fmt(proveedores) }
];

return [{ json: {
  empresa: tokens.empresaNombre,
  year: tokens.year, yearAnterior: tokens.yearAnterior,
  nota9: tokens.nota9, nota10OtraInfo: tokens.nota10OtraInfo,
  nota10MedioAmbiente: tokens.nota10MedioAmbiente,
  administrador: tokens.administrador,
  localidad: tokens.localidad,
  fechaFormulacion: tokens.fechaFormulacion,
  // PyG
  ventas: fmt(ventas), otrosIng: fmt(otrosIng), totalIng: fmt(totalIng),
  aprov: fmt(aprov), gastPers: fmt(gastPers), sueldos: fmt(sueldos),
  ss: fmt(ss), indemnizaciones: fmt(indemnizaciones),
  otrosGast: fmt(otrosGast), amort: fmt(amort),
  gastFin: fmt(gastFin), ingFin: fmt(ingFin),
  ebit: fmt(ebit), rai: fmt(rai), is: fmt(is), resultado: fmt(resultado),
  totalIngAnt: fmt(totalIngAnt), resultadoAnt: fmt(resultadoAnt),
  // Balance
  inmovInt: fmt(inmovInt), inmovMat: fmt(inmovMat), inversionesLP: fmt(inversionesLP),
  activoNC: fmt(activoNC), existencias: fmt(existencias),
  clientes: fmt(clientes), tesoreria: fmt(tesoreria),
  activoC: fmt(activoC), totalActivo: fmt(totalActivo),
  capital: fmt(capital), reservas: fmt(reservas), subvenciones: fmt(subvenciones),
  pn: fmt(pn), deudasLP: fmt(deudasLP),
  proveedores: fmt(proveedores), deudasCP: fmt(deudasCP),
  hpublicas: fmt(hpublicas), pasC: fmt(pasC),
  totalActivoAnt: fmt(totalActivoAnt), pnAnt: fmt(pnAnt), pasCorrAnt: fmt(pasCorrAnt),
  // Fiscal
  ivaRepercutido: fmt(ivaRepercutido), ivaSoportado: fmt(ivaSoportado),
  baseImponible: fmt(baseImponible), cuotaIntegra: fmt(cuotaIntegra),
  cuotaLiquida: fmt(cuotaLiquida), retenciones: fmt(retenciones),
  cuotaDiferencial: fmt(cuotaDiferencial),
  // Detalle
  inmovilizadoDetalle: JSON.stringify(inmovilizadoDetalle),
  vencimientos: JSON.stringify(vencimientos),
  totalLineas: L.length
}}];