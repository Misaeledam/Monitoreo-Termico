"use strict";

const fmt = (v, u = "°C", d = 1) => (v === null || v === undefined ? "–" : `${v.toFixed(d)} ${u}`);
const $ = (id) => document.getElementById(id);
const local = (iso) => new Date(iso).toLocaleString();

async function json(url) {
  const r = await fetch(url, { cache: "no-store" });
  if (!r.ok) throw new Error(`${url}: HTTP ${r.status}`);
  return r.json();
}

async function actualizarEstado() {
  const e = await json("api/estado");
  if (!e.disponible) { $("nivel").textContent = "Sin lecturas todavía"; return; }
  $("nivel").textContent = e.nivel_texto;
  $("nivel").className = `nivel n${e.nivel}`;
  const viejo = e.antiguedad_s > 180 ? " · ⚠ datos desactualizados" : "";
  $("actualizado").textContent = `Última lectura: ${local(e.marca_temporal)}${viejo}`;
  const ent = e.entrada || {}, sal = e.salida || {}, base = e.base || {};
  $("t_in").textContent = fmt(ent.temperatura);
  $("hr_in").textContent = ent.valida ? `HR ${fmt(ent.humedad_relativa, "%", 0)}` : `Sin lectura: ${ent.error || ""}`;
  $("t_out").textContent = fmt(sal.temperatura);
  $("hr_out").textContent = sal.valida ? `HR ${fmt(sal.humedad_relativa, "%", 0)}` : `Sin lectura: ${sal.error || ""}`;
  $("dt").textContent = fmt(e.delta_t);
  $("flujo").textContent = `Flujo: ${(e.condicion_flujo || "").toLowerCase().replace("_", " ")}`;
  const rocios = [e.punto_rocio_entrada, e.punto_rocio_salida].filter((v) => v !== null && v !== undefined);
  $("rocio").textContent = fmt(rocios.length ? Math.max(...rocios) : null);
  $("margen").textContent = `Margen de condensación: ${fmt(e.margen_condensacion)}`;
  $("tasa15").textContent = fmt(e.tasa_variacion_t_15min);
  $("tasa1h").textContent = `En 1 h: ${fmt(e.tasa_variacion_t_1h)}`;
  $("agua").textContent = base.agua_detectada ? "¡Detectada!" : (base.valida ? "Seca" : "Sin lectura");
  $("agua").className = `dato ${base.agua_detectada ? "n3" : ""}`;
}

function dibujar(puntos, umbrales) {
  const c = $("grafico");
  const ratio = window.devicePixelRatio || 1;
  const ancho = c.clientWidth, alto = 260;
  c.width = ancho * ratio; c.height = alto * ratio;
  const g = c.getContext("2d");
  g.scale(ratio, ratio);
  g.clearRect(0, 0, ancho, alto);
  const estilo = getComputedStyle(document.documentElement);
  const colorSub = estilo.getPropertyValue("--sub").trim();
  if (puntos.length < 2) {
    g.fillStyle = colorSub; g.fillText("Todavía no hay datos suficientes", 12, 24); return;
  }
  const t = puntos.map((p) => new Date(p.marca_temporal).getTime());
  const valores = puntos.flatMap((p) => [p.t_entrada, p.t_salida]).filter((v) => v !== null);
  umbrales.forEach((u) => valores.push(u.valor));
  let min = Math.min(...valores), max = Math.max(...valores);
  const margen = (max - min) * 0.08 || 1; min -= margen; max += margen;
  const izq = 40, der = 8, arr = 8, aba = 22;
  const x = (v) => izq + ((v - t[0]) / (t[t.length - 1] - t[0] || 1)) * (ancho - izq - der);
  const y = (v) => arr + (1 - (v - min) / (max - min)) * (alto - arr - aba);
  g.font = "11px system-ui"; g.fillStyle = colorSub; g.strokeStyle = colorSub; g.lineWidth = 0.5;
  for (let i = 0; i <= 4; i++) {
    const v = min + ((max - min) * i) / 4;
    g.fillText(v.toFixed(0), 4, y(v) + 4);
  }
  g.fillText(new Date(t[0]).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" }), izq, alto - 6);
  g.fillText(new Date(t[t.length - 1]).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" }), ancho - 50, alto - 6);
  const colores = { Aviso: "--aviso", Advertencia: "--advertencia", "Crítico": "--critico" };
  umbrales.forEach((u) => {
    g.setLineDash([4, 4]); g.strokeStyle = estilo.getPropertyValue(colores[u.nivel] || "--sub").trim();
    g.beginPath(); g.moveTo(izq, y(u.valor)); g.lineTo(ancho - der, y(u.valor)); g.stroke();
  });
  g.setLineDash([]); g.lineWidth = 2;
  [["t_entrada", "#2f7fd8"], ["t_salida", "#d8572f"]].forEach(([campo, color]) => {
    g.strokeStyle = color; g.beginPath();
    let empezado = false;
    puntos.forEach((p, i) => {
      if (p[campo] === null) { empezado = false; return; }
      if (!empezado) { g.moveTo(x(t[i]), y(p[campo])); empezado = true; } else g.lineTo(x(t[i]), y(p[campo]));
    });
    g.stroke();
  });
  g.fillStyle = "#2f7fd8"; g.fillText("Entrada", izq + 6, arr + 12);
  g.fillStyle = "#d8572f"; g.fillText("Salida", izq + 60, arr + 12);
}

async function actualizarSerie() {
  const s = await json(`api/serie?horas=${$("horas").value}`);
  dibujar(s.puntos, s.umbrales_temperatura);
}

async function actualizarEventos() {
  const e = await json("api/eventos");
  const filas = e.eventos.slice(0, 20).map((ev) => {
    const tr = document.createElement("tr");
    [local(ev.marca_temporal), `${ev.nivel_anterior} → ${ev.nivel_nuevo}`, ev.criterio || "–",
      `${ev.descripcion} (${ev.motivo})`].forEach((txt) => {
      const td = document.createElement("td"); td.textContent = txt; tr.appendChild(td);
    });
    return tr;
  });
  $("eventos").replaceChildren(...filas);
}

async function refrescar() {
  try { await Promise.all([actualizarEstado(), actualizarSerie(), actualizarEventos()]); }
  catch (err) { $("actualizado").textContent = `Error al actualizar: ${err.message}`; }
}

$("horas").addEventListener("change", actualizarSerie);
window.addEventListener("resize", actualizarSerie);
refrescar();
setInterval(refrescar, 30000);
