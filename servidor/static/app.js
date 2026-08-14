/* Inventario RFID — lógica del frontend (sin dependencias, funciona offline) */

function $(s, c) { return (c || document).querySelector(s); }
function $$(s, c) { return Array.from((c || document).querySelectorAll(s)); }
function esc(t) { const d = document.createElement("div"); d.textContent = t ?? ""; return d.innerHTML; }
function hora(iso) { return (iso || "").slice(11, 19); }

/* ---------- reloj de la barra superior ---------- */
(function reloj() {
  const el = $("#reloj");
  if (!el) return;
  const f = () => el.textContent = new Date().toLocaleTimeString("es", { hour12: false });
  f(); setInterval(f, 1000);
})();

/* ---------- panel (home): KPIs + feed en vivo ---------- */
(function panelVivo() {
  const feed = $("#feed");
  if (!feed) return;
  let ultimo = 0;

  async function tick() {
    try {
      const r = await fetch("/api/dashboard");
      const d = await r.json();
      $("#k-prod").textContent = d.productos;
      $("#k-tags").textContent = d.tags;
      $("#k-leidos").textContent = d.leidos;

      const radar = $("#radar");
      const leyendo = d.leidos !== ultimo && ultimo !== 0;
      if (radar) radar.classList.toggle("quieto", !d.sesion);
      ultimo = d.leidos;

      if (!d.ultimas.length) {
        feed.innerHTML = '<div class="vacio">Sin lecturas todavía. Dispara con la pistola o usa Captura rápida.</div>';
      } else {
        feed.innerHTML = d.ultimas.map(u => `
          <div class="fila">
            <time>${hora(u.ts)}</time>
            <span class="epc">${esc(u.epc)}</span>
            <span class="${u.sku ? "okp" : "desc"}">${u.sku ? esc(u.sku) : "sin asociar"}</span>
            <span class="quien">${esc(u.dispositivo)}</span>
          </div>`).join("");
      }
      const dot = $("#dot-sesion"), txt = $("#txt-sesion");
      if (dot) dot.classList.toggle("vivo", !!d.sesion);
      if (txt) txt.textContent = d.sesion ? d.sesion.nombre : "sin sesión";
    } catch (e) { /* servidor dormido: reintenta */ }
  }
  tick(); setInterval(tick, 3000);
})();

/* ---------- vista de sesión: refresco de avance ---------- */
(function sesionViva() {
  const tabla = $("#tabla-avance");
  if (!tabla || tabla.dataset.estado !== "abierta") return;
  const sid = tabla.dataset.sid;

  async function tick() {
    try {
      const r = await fetch(`/api/sesiones/${sid}/resumen`);
      const d = await r.json();
      const tb = $("tbody", tabla);
      tb.innerHTML = d.resumen.map(x => {
        const esp = x.cantidad_esperada, lei = x.leidos;
        const pct = esp > 0 ? Math.min(100, Math.round(lei / esp * 100)) : (lei > 0 ? 100 : 0);
        const est = (esp > 0 && lei >= esp) ? ["ok", "completo"]
                  : lei > 0 ? ["warn", "parcial"] : ["bad", "faltante"];
        return `<tr data-q="${esc((x.sku + " " + x.nombre + " " + x.ubicacion).toLowerCase())}">
          <td class="mono">${esc(x.sku)}</td><td>${esc(x.nombre)}</td>
          <td>${esc(x.ubicacion)}</td>
          <td><div class="medidor">
            <div class="pista"><div class="nivel ${pct >= 100 ? "lleno" : ""}" style="width:${pct}%"></div></div>
            <span class="cifra">${lei}/${esp}</span></div></td>
          <td><span class="tag ${est[0]}">${est[1]}</span></td></tr>`;
      }).join("");
      aplicarFiltro();   // conserva la búsqueda activa tras el refresco
      const nd = $("#n-desc");
      if (nd) nd.textContent = d.desconocidos.length;
      const ld = $("#lista-desc");
      if (ld) ld.innerHTML = d.desconocidos.map(x => `
        <div class="fila"><time>${hora(x.ts)}</time>
        <span class="epc">${esc(x.epc)}</span>
        <span class="quien">${esc(x.dispositivo)}</span></div>`).join("")
        || '<div class="vacio">Ninguno. Todo lo leído está asociado a un producto.</div>';
    } catch (e) { }
  }
  tick(); setInterval(tick, 3000);
})();

/* ---------- filtro instantáneo (productos, desconocidos, conteos) ---------- */
function aplicarFiltro() {
  const inp = $("#buscar");
  if (!inp) return;
  const q = inp.value.trim().toLowerCase();
  $$("tr[data-q]").forEach(tr => {
    tr.style.display = tr.dataset.q.includes(q) ? "" : "none";
  });
}
(function filtro() {
  const inp = $("#buscar");
  if (!inp) return;
  inp.addEventListener("input", aplicarFiltro);
})();

/* ---------- captura: mantener foco y sonido de confirmación ---------- */
(function captura() {
  const inp = $("#campo-scan");
  if (!inp) return;
  inp.focus();
  document.addEventListener("click", e => {
    if (!e.target.closest("a,button,input")) inp.focus();
  });
  if ($("#hubo-lectura")) {
    try {
      const a = new AudioContext(), o = a.createOscillator(), g = a.createGain();
      o.connect(g); g.connect(a.destination);
      o.frequency.value = $("#hubo-lectura").dataset.ok === "1" ? 1150 : 420;
      g.gain.setValueAtTime(.08, a.currentTime);
      o.start(); o.stop(a.currentTime + .12);
    } catch (e) { }
  }
})();
