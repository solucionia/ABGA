# Informe financiero · parches necesarios en `frontend/hub/index.html`

El traductor `pantallas/informe.js` deja los datos reales en `INF_PER`, `INF_PYG` e `INF_BAL`, pero
`rvInf()` (que sigue siendo el de siempre) tiene varios valores escritos a mano que estropean las
cifras o enseñan datos inventados. El **0** es imprescindible para que el traductor se cargue; el
**1** y el **2** lo son para que las cifras salgan bien. El resto son recomendados.

Los números de línea son de `frontend/hub/index.html` tal y como está hoy.

---

## 0. (Imprescindible) Cargar el traductor

El hub carga sus traductores con una etiqueta `<script>` por pantalla (al final del documento, tras
`</x-dc>`). Sin esta línea `pantallas/informe.js` no se ejecuta y la pantalla se queda con los datos
de ejemplo.

```html
<!-- actual -->
<script src="pantallas/envios.js"></script>
<!-- propuesto -->
<script src="pantallas/envios.js"></script>
<script src="pantallas/informe.js"></script>
```

---

## 1. (Imprescindible) El «factor» de cliente multiplica todas las cifras

Línea **2478**.

Hoy: `rvInf` escala toda la cuenta de resultados y el balance por el `factor` del cliente. Las
empresas que devuelve `/api/empresas` no traen ese campo y el puente del hub lo siembra a `0`
(`factor: e.factor || 0`), así que `f = 0` y **la pantalla entera sale a cero**. Las constantes ya
llevan importes reales, no una base que haya que escalar.

```js
// actual
//     const s = this.state, P = INF_PER[s.infPeriodo], c = cli(s.infCliente), f = c.factor * P.pf, fb = c.factor;
// propuesto
//     const s = this.state, P = INF_PER[s.infPeriodo], c = cli(s.infCliente), f = P.pf, fb = 1;
```

`P.pf` vale 1 en el periodo que deja el traductor. (Alternativa equivalente: sembrar las empresas con
`factor: e.factor || 1` en el puente `ABGA_SEMBRAR`, en vez de tocar `rvInf`.)

---

## 2. (Imprescindible) El impuesto de sociedades se recalcula al 25 % y pisa el resultado real

Línea **2482**.

El traductor pone en las filas `is` y `neto` el impuesto real (cuenta 630) y el resultado del
ejercicio. Pero `calc()` los vuelve a calcular siempre con un tipo fijo del 25 % y sobreescribe lo
que venía del informe. Con datos reales, el resultado del periodo y el patrimonio neto del balance
salen falseados (comprobado con la empresa 6172: 21.049,69 € en vez de 25.942,49 €).

```js
// actual
//     ... r.bai = r.ebit + r.fi; r.is = -(r.bai > 0 ? r.bai * 0.25 : 0); r.neto = r.bai + r.is; return r; };
// propuesto
//     ... r.bai = r.ebit + r.fi; if (r.is === undefined) r.is = -(r.bai > 0 ? r.bai * 0.25 : 0); if (r.neto === undefined) r.neto = r.bai + r.is; return r; };
```

El 25 % se queda sólo como último recurso, para cuando la constante no traiga el impuesto.

---

## 3. (Recomendado) El pasivo corriente se inventa para que el balance cuadre solo

Línea **2486**.

Hoy `pc` se deriva (`tot - pn - pnc`), de modo que el balance cuadra siempre por construcción y
oculta cualquier descuadre real. La plataforma da el pasivo corriente de verdad.

```js
// actual
//     ..., pc:tot - pn - sc('pnc')}; };
// propuesto
//     ..., pc:sc('pc'), pt:pn + sc('pnc') + sc('pc')}; };
```

## 4. (Recomendado) La fila del total del pasivo repite el total del activo

Línea **2488**.

```js
// actual
//     ...,['Total patrimonio neto y pasivo','tot',true]]
// propuesto
//     ...,['Total patrimonio neto y pasivo','pt',true]]
```

Con esto `pt` (patrimonio + pasivo no corriente + pasivo corriente) puede no coincidir con `tot`
(activo total): es el descuadre real del ejercicio, y el traductor lo declara con `ctx.sinDatos`.

---

## 5. (Recomendado) La gráfica de «Ventas mensuales» reparte el anual con una estacionalidad de ejemplo

Línea **2508**.

`SEAS` y `NOISE` son constantes de ejemplo: reparten la cifra anual en doce meses inventados. La
plataforma da los ingresos y gastos **reales** de cada mes del ejercicio en curso; el traductor los
deja en `P.mensual` (dentro del periodo de `INF_PER`). Como la plataforma no publica la serie
mensual del ejercicio anterior, la segunda barra pasa a ser los gastos del mismo ejercicio.

```js
// actual
//     const mv = ms.map((m, i) => ({m, a:cur.v * SEAS[m] / sw * NOISE[m], b:prv.v * SEAS[m] / sw * NOISE[(m + 5) % 12]}));
// propuesto
//     const mv = ms.map((m, i) => ({m, a:(P.mensual && P.mensual[i] ? P.mensual[i].ingresos : 0), b:(P.mensual && P.mensual[i] ? P.mensual[i].gastos : 0)}));
```

La línea de arriba (`const ms = P.meses, sw = ms.reduce(...)`) deja de hacer falta, pero se puede
dejar: no molesta.

## 6. (Recomendado) Etiquetas del globo de la gráfica mensual

Línea **2522**.

```js
// actual
//     ..., ya:P.y, yb:P.yp} : {...};
// propuesto
//     ..., ya:'Ingresos', yb:'Gastos'} : {...};
```

## 7. (Recomendado) Leyenda de la gráfica mensual

Línea **1219** (markup de la pantalla).

```html
<!-- actual -->
<span style="width:9px;height:9px;border-radius:2px;background:var(--border);"></span>{{ infP.yp }}</span><span style="display:inline-flex;align-items:center;gap:4px;"><span style="width:9px;height:9px;border-radius:2px;background:var(--accent);"></span>{{ infP.y }}
<!-- propuesto -->
<span style="width:9px;height:9px;border-radius:2px;background:var(--border);"></span>Gastos</span><span style="display:inline-flex;align-items:center;gap:4px;"><span style="width:9px;height:9px;border-radius:2px;background:var(--accent);"></span>Ingresos
```

---

## 8. (Recomendado) La curva de tesorería es una fórmula inventada

Línea **2524**.

Hoy la serie mensual de tesorería se fabrica con una tendencia y un seno sobre el saldo final
(`0.74`, `0.26`, `0.06`, `Math.sin(i * 1.7)`): son cifras que no existen. La plataforma da el saldo
real mes a mes; el traductor lo deja en `P.tesoreria`.

```js
// actual
//     const n = ms.length, tes = ms.map((m, i) => bc.te * (0.74 + 0.26 * (n > 1 ? i / (n - 1) : 1)) * (1 + 0.06 * Math.sin(i * 1.7)));
// propuesto
//     const n = ms.length, tes = ms.map((m, i) => (P.tesoreria && typeof P.tesoreria[i] === 'number') ? P.tesoreria[i] : 0);
```

---

## 9. (Recomendado · en el markup) Fecha y hora de la cabecera, inventadas

Línea **1104**.

```html
<!-- actual -->
Datos del ERP hasta 31/08/2026 · generado hoy a las 10:42
<!-- propuesto (sin inventar nada) -->
Datos leídos del ERP de ABGA
```

`31/08/2026` y `10:42` están escritos a mano y no salen de ningún sitio. La plataforma sí devuelve
la fecha de generación del informe (`meta.generado`), pero hoy no viaja hasta el hub: si se quiere
enseñar, habría que añadirla al periodo en el traductor y un val nuevo en `rvInf`.

## 10. (Recomendado · en el markup) La misma fecha inventada en el pie

Línea **1288**.

```html
<!-- actual -->
<span>ABGA Consultores · Informe elaborado a partir de la contabilidad a 31/08/2026</span>
<!-- propuesto -->
<span>ABGA Consultores · Informe elaborado a partir de la contabilidad del ejercicio</span>
```

## 11. (Recomendado · en el markup) El asesor que edita, escrito a mano

Línea **1271**.

```html
<!-- actual -->
<span style="font-size:11px;font-weight:600;color:var(--ok);">✓ Editado por Javier Roldán</span>
<!-- propuesto -->
<span style="font-size:11px;font-weight:600;color:var(--ok);">✓ Editado por el asesor</span>
```

## 12. (Recomendado) El asesor del correo de envío, escrito a mano

Línea **2549**.

```js
// actual
//     ... '\n\nUn saludo,\nJavier Roldán · ABGA Consultores'
// propuesto
//     ... '\n\nUn saludo,\nABGA Consultores'
```

*(Comprobado con la empresa 6091 · MB DOMMO, S.L. y 6172 · 17 DE AGOSTO 21 DESARROLLOS Y PROYE.)*

---

## Lo que NO hace falta tocar

* Las constantes `DOCS`, `CV_FACT` y `CV_MESES` **no las usa la pantalla «Informe financiero»**
  (`rvInf`/su markup no las referencian). `DOCS` alimenta la ficha de cliente y `CV_FACT`/`CV_MESES`
  no las usa ninguna pantalla: el traductor no las toca.
* El markup y los estilos: sólo lo indicado arriba (etiquetas y fechas escritas a mano).

## Matices conocidos (documentados, sin parche)

* La fila «Importe neto de la cifra de negocios» lleva `totalIng` (total de ingresos de explotación,
  que incluye otros ingresos), no sólo las ventas: es la base que usan los márgenes y el EBITDA del
  propio informe de la plataforma. La columna de la izquierda de la tabla dice «% s/ ventas».
* La fila «Gastos financieros» lleva el **resultado financiero** (ingresos − gastos financieros),
  porque la pantalla la suma al EBIT para llegar al RAI, igual que el informe de la plataforma. Si
  se quisiera separar, habría que añadir una fila al `INF_PYG` (cambio visible en la tabla).
* «Deudores comerciales» agrupa clientes y otros deudores, para que el activo corriente completo (y
  el total del activo) cuadre con el de la plataforma.
* Con la pantalla en blanco (ejercicio no leído del ERP) las cifras van a cero y algunos
  porcentajes salen `NaN`, porque los formateadores de `rvInf` dividen por cero. Un parche opcional
  (no incluido) sería devolver `'—'` en `pct`/`n1`/`n2` cuando el valor no sea finito.
* El envío del informe al cliente sigue sin endpoint en la plataforma: la pantalla lo declara con
  `ctx.sinDatos`.
