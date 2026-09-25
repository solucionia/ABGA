// ============================================================
// REQ-05 — BALANCE Y PyG
// Fuente: /api/apuntes/ expandiendo Detalles
// Saldo por cuenta = suma(Haber) - suma(Debe) o inverso según grupo
// ============================================================

const tokens = $('Guardar Token').item.json;

// Extraer líneas de detalle de los apuntes
const extraerLineas = (raw) => {
  const datos = raw?.Datos || raw?.datos || (Array.isArray(raw) ? raw : []);
  const lineas = [];
  datos.forEach(asiento => {
    if (asiento.Detalles) {
      asiento.Detalles.forEach(d => lineas.push(d));
    }
  });
  return lineas;
};

const lineas = extraerLineas($('GET Apuntes Año Actual').item.json);
const lineasAnt = extraerLineas($('GET Apuntes Año Anterior').item.json);

const fmt = (n) => typeof n === 'number' ? n.toLocaleString('es-ES',{minimumFractionDigits:2,maximumFractionDigits:2})+' €' : '—';
const fmtPct = (n) => typeof n === 'number' ? n.toFixed(1)+'%' : '—';

// Calcular saldo neto por cuenta (Debe - Haber para cuentas de activo/gasto, Haber - Debe para pasivo/ingreso)
const saldosPorCuenta = (lineasArr) => {
  const mapa = {};
  lineasArr.forEach(l => {
    const cuenta = String(l.Cuenta || '');
    if (!mapa[cuenta]) mapa[cuenta] = { debe: 0, haber: 0 };
    mapa[cuenta].debe += parseFloat(l.Debe || 0);
    mapa[cuenta].haber += parseFloat(l.Haber || 0);
  });
  return mapa;
};

// Suma de saldos por prefijos de cuenta
// Para cuentas de ACTIVO y GASTOS: saldo = Debe - Haber (positivo = saldo deudor)
// Para cuentas de PASIVO e INGRESOS: saldo = Haber - Debe (positivo = saldo acreedor)
const sumaDeudor = (saldos, prefijos) => {
  let total = 0;
  Object.entries(saldos).forEach(([cuenta, s]) => {
    if (prefijos.some(p => cuenta.startsWith(p))) {
      total += s.debe - s.haber;
    }
  });
  return Math.max(0, total);
};

const sumaAcreedor = (saldos, prefijos) => {
  let total = 0;
  Object.entries(saldos).forEach(([cuenta, s]) => {
    if (prefijos.some(p => cuenta.startsWith(p))) {
      total += s.haber - s.debe;
    }
  });
  return Math.max(0, total);
};

const s = saldosPorCuenta(lineas);
const sAnt = saldosPorCuenta(lineasAnt);

// ---- PyG AÑO ACTUAL ----
const ventas = sumaAcreedor(s, ['700','701','702','703','704','705']);
const otrosIngresos = sumaAcreedor(s, ['706','708','709','740','741','746','747','748','749','75','76','778']);
const totalIngresos = ventas + otrosIngresos;
const aprovisionamientos = sumaDeudor(s, ['600','601','602','606','607','608','609','610','611','612']);
const gastosPersonal = sumaDeudor(s, ['640','641','642','643','644','649']);
const otrosGastosExplot = sumaDeudor(s, ['620','621','622','623','624','625','626','627','628','629','630','631','632','633','634','636','639','650','651','659']);
const amortizaciones = sumaDeudor(s, ['680','681','682','690','691','692']);
const ebitda = totalIngresos - aprovisionamientos - gastosPersonal - otrosGastosExplot;
const ebit = ebitda - amortizaciones;
const ingresosFinancieros = sumaAcreedor(s, ['760','761','762','763','769']);
const gastosFinancieros = sumaDeudor(s, ['660','661','662','663','664','665','669']);
const rai = ebit + ingresosFinancieros - gastosFinancieros;
const impuesto = sumaDeudor(s, ['630']);
const resultadoNeto = rai - impuesto;
const cashFlow = resultadoNeto + amortizaciones;
const margenBruto = totalIngresos > 0 ? (totalIngresos - aprovisionamientos) / totalIngresos * 100 : 0;
const margenNeto = totalIngresos > 0 ? resultadoNeto / totalIngresos * 100 : 0;
const margenEBITDA = totalIngresos > 0 ? ebitda / totalIngresos * 100 : 0;

// ---- PyG AÑO ANTERIOR ----
const ventasAnt = sumaAcreedor(sAnt, ['700','701','702','703','704','705']);
const totalIngresosAnt = ventasAnt + sumaAcreedor(sAnt, ['706','708','709','740','741','746','747','748','749','75','76','778']);
const aprovisionamientosAnt = sumaDeudor(sAnt, ['600','601','602','606','607','608','609','610','611','612']);
const gastosPersonalAnt = sumaDeudor(sAnt, ['640','641','642','643','644','649']);
const otrosGastosAnt = sumaDeudor(sAnt, ['620','621','622','623','624','625','626','627','628','629','630','631','632','633','634','636','639','650','651','659']);
const amortAnt = sumaDeudor(sAnt, ['680','681','682','690','691','692']);
const ebitAnt = totalIngresosAnt - aprovisionamientosAnt - gastosPersonalAnt - otrosGastosAnt - amortAnt;
const gastosFinAnt = sumaDeudor(sAnt, ['660','661','662','663','664','665','669']);
const raiAnt = ebitAnt + sumaAcreedor(sAnt, ['760','761','762','763','769']) - gastosFinAnt;
const resultadoNetoAnt = raiAnt - sumaDeudor(sAnt, ['630']);

// ---- BALANCE AÑO ACTUAL ----
const inmovIntangible = sumaDeudor(s, ['200','201','202','203','204','205','206','207','280']);
const inmovMaterial = sumaDeudor(s, ['210','211','212','213','214','215','216','217','218','219','281','282']);
const inversionesLP = sumaDeudor(s, ['250','251','252','253','254','255','256','257','258','259','260','261','262','263','264','265','266','267','268','269']);
const activoNoCorriente = inmovIntangible + inmovMaterial + inversionesLP;
const existencias = sumaDeudor(s, ['300','301','302','303','304','305','306','307','308','309','310','311','312','313','314','315','316','317','318','319','320','321','322','323','324','325','326','327','328','329','330','331','332','333','334','335','336','337','338','339','340','341','342','343','344','345','346','347','348','349','350','351','352','353','354','355','356','357','358','359']);
const clientesSaldo = sumaDeudor(s, ['430','431','432','433','434','435','436','437','438','439','440','441','460','470','471','472','473','474','476','480','481','567','568']);
const tesoreria = sumaDeudor(s, ['570','571','572','573','574','575','576','577']);
const activoCorriente = existencias + clientesSaldo + tesoreria;
const totalActivo = activoNoCorriente + activoCorriente;

const capitalSocial = sumaAcreedor(s, ['100','101','102','103','104','108','109']);
const reservas = sumaAcreedor(s, ['110','111','112','113','114','115','116','117','118','119','120','121']);
const subvenciones = sumaAcreedor(s, ['130','131','132']);
const patrimonioNeto = capitalSocial + reservas + resultadoNeto + subvenciones;
const deudasLP = sumaAcreedor(s, ['150','151','152','153','154','155','156','157','158','159','160','161','162','163','164','165','166','167','168','169','170','171','172','173','174','175','176','177','178','179']);
const proveedoresSaldo = sumaAcreedor(s, ['400','401','402','403','404','405','406','407','408','409','410','411','412','413','414','415','416','417','418','419']);
const deudasCP = sumaAcreedor(s, ['500','501','502','503','504','505','506','507','508','509','510','511','512','513','514','515','516','517','518','519','520','521','522','523','524','525','526','527','528','529','550','551','552','553','554','555','556','557','558','559','475','477','476','4750','4751','4752','4758','4759']);
const pasivoCorriente = proveedoresSaldo + deudasCP;
const totalPasivo = deudasLP + pasivoCorriente + patrimonioNeto;
const fondoManiobra = activoCorriente - pasivoCorriente;

// ---- RATIOS ----
const liquidez = pasivoCorriente > 0 ? activoCorriente / pasivoCorriente : 0;
const endeudamiento = totalActivo > 0 ? (deudasLP + pasivoCorriente) / totalActivo * 100 : 0;
const roe = patrimonioNeto > 0 ? resultadoNeto / patrimonioNeto * 100 : 0;
const roa = totalActivo > 0 ? ebit / totalActivo * 100 : 0;

// ---- EVOLUCIÓN MENSUAL ----
const evolucionMensual = [];
const mesesNombre = ['Ene','Feb','Mar','Abr','May','Jun','Jul','Ago','Sep','Oct','Nov','Dic'];
for (let m = 1; m <= 12; m++) {
  const mesStr = String(m).padStart(2,'0');
  const fechaIni = parseInt(tokens.year + mesStr + '01');
  const fechaFin = parseInt(tokens.year + mesStr + '31');
  const lineasMes = lineas.filter(l => {
    const f = parseInt(l.Fecha || 0);
    return f >= fechaIni && f <= fechaFin;
  });
  const sMes = saldosPorCuenta(lineasMes);
  const ingMes = sumaAcreedor(sMes, ['700','701','702','703','704','705','706','708','709']);
  const gastMes = sumaDeudor(sMes, ['600','601','602','640','641','642','620','621','622','623','624','625','626','627','628','629']);
  if (ingMes > 0 || gastMes > 0) {
    evolucionMensual.push({
      mes: mesesNombre[m-1],
      ingresos: fmt(ingMes),
      gastos: fmt(gastMes),
      resultado: fmt(ingMes - gastMes)
    });
  }
}

return [{ json: {
  empresa: tokens.empresaNombre,
  cod_empresa: tokens.cod_empresa,
  year: tokens.year,
  yearAnterior: tokens.yearAnterior,
  nombreMes: tokens.nombreMes,
  trimestre: tokens.trimestre,
  email: tokens.emailDestino,
  // PyG actual
  ventas: fmt(ventas), otrosIngresos: fmt(otrosIngresos), totalIngresos: fmt(totalIngresos),
  aprovisionamientos: fmt(aprovisionamientos), gastosPersonal: fmt(gastosPersonal),
  otrosGastosExplot: fmt(otrosGastosExplot), amortizaciones: fmt(amortizaciones),
  ebitda: fmt(ebitda), ebit: fmt(ebit),
  ingresosFinancieros: fmt(ingresosFinancieros), gastosFinancieros: fmt(gastosFinancieros),
  rai: fmt(rai), impuesto: fmt(impuesto), resultadoNeto: fmt(resultadoNeto), cashFlow: fmt(cashFlow),
  margenBruto: fmtPct(margenBruto), margenNeto: fmtPct(margenNeto), margenEBITDA: fmtPct(margenEBITDA),
  // PyG anterior
  totalIngresosAnt: fmt(totalIngresosAnt), resultadoNetoAnt: fmt(resultadoNetoAnt),
  varIngresos: totalIngresosAnt > 0 ? fmtPct((totalIngresos - totalIngresosAnt) / totalIngresosAnt * 100) : '—',
  varResultado: resultadoNetoAnt !== 0 ? fmtPct((resultadoNeto - resultadoNetoAnt) / Math.abs(resultadoNetoAnt) * 100) : '—',
  // Balance
  inmovIntangible: fmt(inmovIntangible), inmovMaterial: fmt(inmovMaterial),
  activoNoCorriente: fmt(activoNoCorriente),
  existencias: fmt(existencias), clientesSaldo: fmt(clientesSaldo), tesoreria: fmt(tesoreria),
  activoCorriente: fmt(activoCorriente), totalActivo: fmt(totalActivo),
  capitalSocial: fmt(capitalSocial), reservas: fmt(reservas),
  patrimonioNeto: fmt(patrimonioNeto), deudasLP: fmt(deudasLP),
  proveedoresSaldo: fmt(proveedoresSaldo), pasivoCorriente: fmt(pasivoCorriente),
  totalPasivo: fmt(totalPasivo), fondoManiobra: fmt(fondoManiobra),
  // Ratios
  liquidez: liquidez.toFixed(2), endeudamiento: fmtPct(endeudamiento),
  roe: fmtPct(roe), roa: fmtPct(roa),
  // Evolución
  evolucionMensual: JSON.stringify(evolucionMensual),
  totalLineas: lineas.length,
  totalLineasAnt: lineasAnt.length
}}];