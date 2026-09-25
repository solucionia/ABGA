// ============================================================
// REQ-04 — DETECCIÓN DE FACTURAS DUPLICADAS
// Trabaja directamente sobre los apuntes contables
// Detecta asientos con mismo importe + misma contrapartida + fecha próxima
// Algoritmo multivariable con puntuación de confianza
// ============================================================

const tokens = $('Guardar Token').item.json;
const raw = $('GET Apuntes del Ejercicio').item.json;
const datos = raw?.Datos || raw?.datos || (Array.isArray(raw) ? raw : []);

const fmt = (n) => typeof n==='number' ? n.toLocaleString('es-ES',{minimumFractionDigits:2,maximumFractionDigits:2})+' €' : '—';

// ---- Levenshtein para comparar conceptos ----
const lev = (a, b) => {
  if (!a || !b) return 99;
  if (a === b) return 0;
  const m = a.length, n = b.length;
  const dp = Array.from({length:m+1}, (_,i) => Array.from({length:n+1}, (_,j) => i===0?j:j===0?i:0));
  for (let i=1;i<=m;i++) for (let j=1;j<=n;j++)
    dp[i][j] = a[i-1]===b[j-1] ? dp[i-1][j-1] : 1+Math.min(dp[i-1][j],dp[i][j-1],dp[i-1][j-1]);
  return dp[m][n];
};

// Normalizar cada asiento para comparación
const asientos = datos.map(a => {
  const totalDebe = (a.Detalles||[]).reduce((s,d)=>s+parseFloat(d.Debe||0),0);
  const totalHaber = (a.Detalles||[]).reduce((s,d)=>s+parseFloat(d.Haber||0),0);
  const cuentas = [...new Set((a.Detalles||[]).map(d=>String(d.Cuenta||'').substring(0,4)).sort())].join(',');
  const contrapartidas40 = (a.Detalles||[]).filter(d=>String(d.Cuenta||'').startsWith('40')||String(d.Cuenta||'').startsWith('41')).map(d=>String(d.Cuenta||'').substring(0,10)).join(',');
  const contrapartidas43 = (a.Detalles||[]).filter(d=>String(d.Cuenta||'').startsWith('43')||String(d.Cuenta||'').startsWith('44')).map(d=>String(d.Cuenta||'').substring(0,10)).join(',');
  return {
    id: a.Documento||a.NumeroAsiento||Math.random().toString(),
    fecha: parseInt(String(a.Fecha||'0')),
    fechaStr: String(a.Fecha||''),
    descripcion: String(a.Descripcion||'').toLowerCase().trim(),
    totalDebe: Math.round(totalDebe*100)/100,
    totalHaber: Math.round(totalHaber*100)/100,
    importe: Math.round(Math.max(totalDebe,totalHaber)*100)/100,
    cuentas,
    contrapartidas40,
    contrapartidas43,
    serie: String(a.Serie||''),
    tipoAsiento: String(a.TipoAsiento||'')
  };
}).filter(a => a.importe > 50);

// ---- Algoritmo de detección ----
const duplicados = [];
const yaComparados = new Set();

for (let i=0; i<asientos.length; i++) {
  for (let j=i+1; j<asientos.length; j++) {
    const a = asientos[i];
    const b = asientos[j];
    const clave = [a.id, b.id].sort().join('|');
    if (yaComparados.has(clave)) continue;
    yaComparados.add(clave);

    let puntos = 0;
    const coincidencias = [];

    // 1. Importe idéntico (peso 3 — criterio más importante)
    if (Math.abs(a.importe - b.importe) < 0.02 && a.importe > 0) {
      puntos += 3;
      coincidencias.push(`Importe idéntico: ${fmt(a.importe)}`);
    }

    // 2. Mismas cuentas involucradas (peso 2)
    if (a.cuentas && b.cuentas && a.cuentas === b.cuentas) {
      puntos += 2;
      coincidencias.push(`Mismas cuentas: ${a.cuentas}`);
    }

    // 3. Fecha próxima — mismo día (peso 3) o ±3 días (peso 1)
    const diasDif = Math.abs(a.fecha - b.fecha);
    if (diasDif === 0) {
      puntos += 3;
      coincidencias.push(`Misma fecha: ${a.fechaStr}`);
    } else if (diasDif <= 3) {
      puntos += 1;
      coincidencias.push(`Fechas próximas: ${a.fechaStr} / ${b.fechaStr}`);
    }

    // 4. Descripción similar (Levenshtein ≤ 5, peso 2)
    if (a.descripcion && b.descripcion && a.descripcion.length > 3) {
      const dist = lev(a.descripcion.substring(0,30), b.descripcion.substring(0,30));
      if (dist === 0) {
        puntos += 2;
        coincidencias.push(`Descripción idéntica: "${a.descripcion.substring(0,40)}"`);
      } else if (dist <= 5) {
        puntos += 1;
        coincidencias.push(`Descripción similar (dist.${dist})`);
      }
    }

    // 5. Misma contrapartida de proveedor (peso 2)
    if (a.contrapartidas40 && b.contrapartidas40 && a.contrapartidas40 === b.contrapartidas40) {
      puntos += 2;
      coincidencias.push(`Mismo proveedor: ${a.contrapartidas40}`);
    }

    // 6. Misma contrapartida de cliente (peso 2)
    if (a.contrapartidas43 && b.contrapartidas43 && a.contrapartidas43 === b.contrapartidas43) {
      puntos += 2;
      coincidencias.push(`Mismo cliente: ${a.contrapartidas43}`);
    }

    // Umbral mínimo 4 puntos para reportar
    if (puntos < 4) continue;

    const nivel = puntos >= 8 ? 'PROBABLE' : puntos >= 6 ? 'POSIBLE' : 'REVISAR';

    duplicados.push({
      nivel,
      puntuacion: puntos,
      coincidencias,
      asientoA: { id:a.id, fecha:a.fechaStr, descripcion:a.descripcion, importe:fmt(a.importe) },
      asientoB: { id:b.id, fecha:b.fechaStr, descripcion:b.descripcion, importe:fmt(b.importe) },
      importeRiesgo: a.importe,
      importeRiesgoFmt: fmt(a.importe)
    });
  }
}

// Ordenar por nivel y puntuación
duplicados.sort((a,b) => {
  const o = {PROBABLE:0,POSIBLE:1,REVISAR:2};
  return o[a.nivel]-o[b.nivel] || b.puntuacion-a.puntuacion;
});

const probableCount = duplicados.filter(d=>d.nivel==='PROBABLE').length;
const posibleCount = duplicados.filter(d=>d.nivel==='POSIBLE').length;
const revisarCount = duplicados.filter(d=>d.nivel==='REVISAR').length;
const importeTotalRiesgo = duplicados
  .filter(d=>d.nivel==='PROBABLE'||d.nivel==='POSIBLE')
  .reduce((s,d)=>s+d.importeRiesgo,0);

return [{ json: {
  empresa: tokens.empresaNombre,
  year: tokens.year,
  nivelGlobal: probableCount>0?'PROBABLE':posibleCount>0?'POSIBLE':revisarCount>0?'REVISAR':'OK',
  totalDuplicados: duplicados.length,
  probableCount, posibleCount, revisarCount,
  importeTotalRiesgo: fmt(importeTotalRiesgo),
  duplicados: JSON.stringify(duplicados.slice(0,20)),
  stats: { totalAsientos: asientos.length, totalComparaciones: yaComparados.size }
}}];