// ============================================================
// REQ-01 — CONCILIACIÓN DE MAYORES
// Detecta 5 tipos de anomalías desde los apuntes contables:
// 1. Saldos negativos en cuentas de clientes (43x)
// 2. Saldos negativos en cuentas de proveedores (40x)
// 3. Cobros en 43x sin factura asociada
// 4. Pagos en 40x sin factura asociada
// 5. Cuentas con movimientos anómalos (debe = haber exacto, posible duplicado)
// ============================================================

const tokens = $('Guardar Token').item.json;
const raw = $('GET Apuntes Clientes (43x)').item.json;
const datos = raw?.Datos || raw?.datos || (Array.isArray(raw) ? raw : []);

const fmt = (n) => typeof n==='number' ? n.toLocaleString('es-ES',{minimumFractionDigits:2,maximumFractionDigits:2})+' €' : '—';

// Expandir líneas de detalle con referencia al asiento padre
const lineas = [];
datos.forEach(asiento => {
  if (asiento.Detalles) {
    asiento.Detalles.forEach(d => lineas.push({
      ...d,
      _numAsiento: asiento.Documento || asiento.NumeroAsiento || '',
      _fecha: asiento.Fecha || '',
      _descripcionAsiento: asiento.Descripcion || '',
      _serie: asiento.Serie || ''
    }));
  }
});

// Agrupar por cuenta — calcular saldo neto
const saldosPorCuenta = {};
lineas.forEach(l => {
  const cuenta = String(l.Cuenta || '');
  if (!saldosPorCuenta[cuenta]) saldosPorCuenta[cuenta] = { debe: 0, haber: 0, lineas: [] };
  saldosPorCuenta[cuenta].debe += parseFloat(l.Debe || 0);
  saldosPorCuenta[cuenta].haber += parseFloat(l.Haber || 0);
  saldosPorCuenta[cuenta].lineas.push(l);
});

// ---- BLOQUE 1: Clientes con saldo negativo (43x) ----
// En cuentas 43x el saldo normal es deudor (Debe > Haber)
// Si Haber > Debe → saldo negativo → cobro sin factura o factura pendiente
const clientesAnomalos = [];
Object.entries(saldosPorCuenta).forEach(([cuenta, s]) => {
  if (!cuenta.startsWith('43') && !cuenta.startsWith('44')) return;
  const saldo = s.debe - s.haber;
  if (saldo < -0.01) {
    clientesAnomalos.push({
      tipo: 'CLIENTE_SALDO_NEGATIVO',
      nivel: Math.abs(saldo) > 5000 ? 'ALTA' : Math.abs(saldo) > 1000 ? 'MEDIA' : 'INFO',
      cuenta, saldo: fmt(saldo), saldoNum: saldo,
      descripcion: 'Saldo negativo en cuenta de cliente — posible cobro duplicado o factura pendiente'
    });
  }
});

// ---- BLOQUE 2: Proveedores con saldo negativo (40x) ----
// En cuentas 40x el saldo normal es acreedor (Haber > Debe)
// Si Debe > Haber → saldo negativo → pago sin factura o anticipo sin aplicar
const proveedoresAnomalos = [];
Object.entries(saldosPorCuenta).forEach(([cuenta, s]) => {
  if (!cuenta.startsWith('40') && !cuenta.startsWith('41')) return;
  const saldo = s.haber - s.debe;
  if (saldo < -0.01) {
    proveedoresAnomalos.push({
      tipo: 'PROVEEDOR_SALDO_NEGATIVO',
      nivel: Math.abs(saldo) > 5000 ? 'ALTA' : Math.abs(saldo) > 1000 ? 'MEDIA' : 'INFO',
      cuenta, saldo: fmt(saldo), saldoNum: saldo,
      descripcion: 'Saldo negativo en cuenta de proveedor — posible pago duplicado o anticipo sin aplicar'
    });
  }
});

// ---- BLOQUE 3: Apuntes en tesorería (57x) sin contrapartida en 43x/40x ----
// Un cobro de cliente debería tener contrapartida 43x en el mismo asiento
// Si hay un movimiento en 57x sin 43x/40x → posible cobro/pago no identificado
const cobrosSinContrapartida = [];
const pagosSinContrapartida = [];

datos.forEach(asiento => {
  if (!asiento.Detalles || asiento.Detalles.length < 2) return;
  const tieneTesoreria = asiento.Detalles.some(d => String(d.Cuenta||'').startsWith('57'));
  if (!tieneTesoreria) return;
  const tieneCliente = asiento.Detalles.some(d => String(d.Cuenta||'').match(/^(43|44)/) );
  const tieneProveedor = asiento.Detalles.some(d => String(d.Cuenta||'').match(/^(40|41)/) );
  const lineasTes = asiento.Detalles.filter(d => String(d.Cuenta||'').startsWith('57'));
  lineasTes.forEach(l => {
    const haber = parseFloat(l.Haber || 0);
    const debe = parseFloat(l.Debe || 0);
    if (haber > 100 && !tieneCliente) {
      cobrosSinContrapartida.push({
        tipo: 'COBRO_SIN_CONTRAPARTIDA',
        nivel: haber > 5000 ? 'ALTA' : 'MEDIA',
        fecha: String(asiento.Fecha||''),
        cuenta: l.Cuenta,
        concepto: asiento.Descripcion || '',
        importe: fmt(haber), importeNum: haber,
        descripcion: `Cobro de ${fmt(haber)} en tesorería sin contrapartida en cuenta de cliente`
      });
    }
    if (debe > 100 && !tieneProveedor) {
      pagosSinContrapartida.push({
        tipo: 'PAGO_SIN_CONTRAPARTIDA',
        nivel: debe > 5000 ? 'ALTA' : 'MEDIA',
        fecha: String(asiento.Fecha||''),
        cuenta: l.Cuenta,
        concepto: asiento.Descripcion || '',
        importe: fmt(debe), importeNum: debe,
        descripcion: `Pago de ${fmt(debe)} en tesorería sin contrapartida en cuenta de proveedor`
      });
    }
  });
});

// ---- BLOQUE 4: Partidas en cuenta 555 (pendientes de aplicar) ----
const partidas555 = [];
Object.entries(saldosPorCuenta).forEach(([cuenta, s]) => {
  if (!cuenta.startsWith('555')) return;
  const saldo = Math.abs(s.debe - s.haber);
  if (saldo > 0.01) {
    partidas555.push({
      tipo: 'PARTIDA_PENDIENTE_555',
      nivel: saldo > 1000 ? 'ALTA' : 'MEDIA',
      cuenta, saldo: fmt(saldo), saldoNum: saldo,
      descripcion: 'Partida pendiente de aplicación — requiere identificación y contabilización'
    });
  }
});

// ---- BLOQUE 5: Cuentas con movimientos espejo (posible duplicado de asiento) ----
const posiblesDuplicados = [];
const asientosPorImporte = {};
datos.forEach(asiento => {
  if (!asiento.Detalles) return;
  const totalDebe = asiento.Detalles.reduce((s,d) => s + parseFloat(d.Debe||0), 0);
  const key = `${String(asiento.Fecha||'').substring(0,8)}_${Math.round(totalDebe)}`;
  if (!asientosPorImporte[key]) asientosPorImporte[key] = [];
  asientosPorImporte[key].push({ doc: asiento.Documento||asiento.NumeroAsiento||'', fecha: asiento.Fecha, desc: asiento.Descripcion||'', importe: fmt(totalDebe), importeNum: totalDebe });
});
Object.values(asientosPorImporte).forEach(grupo => {
  if (grupo.length >= 2 && grupo[0].importeNum > 100) {
    posiblesDuplicados.push({
      tipo: 'ASIENTO_DUPLICADO',
      nivel: grupo[0].importeNum > 5000 ? 'ALTA' : 'MEDIA',
      fecha: String(grupo[0].fecha||''),
      importe: grupo[0].importe, importeNum: grupo[0].importeNum,
      asientos: grupo.map(g => g.doc).join(' / '),
      descripcion: `${grupo.length} asientos con mismo importe (${grupo[0].importe}) en la misma fecha — revisar posible duplicado`
    });
  }
});

// Consolidar todos los hallazgos
const todos = [
  ...clientesAnomalos,
  ...proveedoresAnomalos,
  ...cobrosSinContrapartida.slice(0,10),
  ...pagosSinContrapartida.slice(0,10),
  ...partidas555,
  ...posiblesDuplicados.slice(0,10)
].sort((a,b) => {
  const orden = { ALTA:0, MEDIA:1, INFO:2 };
  return orden[a.nivel] - orden[b.nivel];
});

const altaCount = todos.filter(h=>h.nivel==='ALTA').length;
const mediaCount = todos.filter(h=>h.nivel==='MEDIA').length;
const importeRiesgo = todos
  .filter(h=>h.nivel==='ALTA'||h.nivel==='MEDIA')
  .reduce((s,h) => s + Math.abs(h.importeNum||h.saldoNum||0), 0);

return [{ json: {
  empresa: tokens.empresaNombre,
  year: tokens.year,
  nivelGlobal: altaCount>0?'ALTA':mediaCount>0?'MEDIA':todos.length>0?'INFO':'OK',
  totalHallazgos: todos.length,
  altaCount, mediaCount,
  importeRiesgo: fmt(importeRiesgo),
  resumen: {
    clientesAnomalos: clientesAnomalos.length,
    proveedoresAnomalos: proveedoresAnomalos.length,
    cobrosSinContrapartida: cobrosSinContrapartida.length,
    pagosSinContrapartida: pagosSinContrapartida.length,
    partidas555: partidas555.length,
    posiblesDuplicados: posiblesDuplicados.length
  },
  hallazgos: JSON.stringify(todos),
  totalLineas: lineas.length,
  totalAsientos: datos.length
}}];