# -*- coding: utf-8 -*-
"""Inventario RFID — app para los OTROS PCs del local.

No corre ningún servidor: abre una ventana nativa conectada al PC PRINCIPAL
(el que tiene instalado el programa del inventario). Arranca con una página
local que prueba la conexión y salta sola al inventario; si el principal no
contesta, muestra un formulario para corregir la dirección (queda guardada
en el propio navegador de la ventana).

Sin js_api a propósito: el puente JS-Python de pywebview congela la ventana
("no responde") cuando la página cargada es remota.
"""
import html
import json
import os
import re
import socket
import sys
import threading
import time

# "cliente" = otros PCs que SÍ modifican (naranja) · "vendedor" = solo
# consulta (verde oscuro; el servidor le oculta modificar/imprimir) ·
# "principal" = el PC del encargado (rojo, con ⚙ Configuración) — se activa
# con el argumento --principal (el instalador tiene la casilla).
# vendedor.py importa este módulo y cambia este valor antes de arrancar.
MODO = "cliente"

BASE = os.path.dirname(sys.executable if getattr(sys, "frozen", False)
                       else os.path.abspath(__file__))
CFG = os.path.join(BASE, "cliente.json")
# Si la carpeta del programa no deja escribir (permisos), la dirección se
# guarda aquí: así igual se recuerda el servidor elegido.
CFG_ALT = os.path.join(os.environ.get("LOCALAPPDATA") or BASE,
                       "InventarioRFID", "cliente.json")


def _archivo_config():
    """El cliente.json que manda: el de la carpeta del programa, salvo que la
    copia de respaldo sea más reciente (porque no se pudo escribir allí)."""
    try:
        if os.path.exists(CFG_ALT) and (not os.path.exists(CFG)
                                        or os.path.getmtime(CFG_ALT) > os.path.getmtime(CFG)):
            return CFG_ALT
    except OSError:
        pass
    return CFG


def direccion_predeterminada():
    try:
        with open(_archivo_config(), encoding="utf-8") as f:
            return str(json.load(f).get("servidor") or "192.168.0.2:5000").strip()
    except Exception:
        return "192.168.0.2:5000"


def guardar_direccion(direccion):
    """Deja escrita en cliente.json la dirección del servidor al que este PC
    se conectó de verdad. Así, si el PC principal cambia de IP y se elige el
    nuevo (o lo encuentra el buscador), la próxima vez abre directo con él."""
    datos = {}
    try:
        with open(_archivo_config(), encoding="utf-8") as f:
            datos = json.load(f) or {}
    except Exception:
        datos = {}
    if str(datos.get("servidor") or "").strip() == direccion:
        return False
    datos["servidor"] = direccion
    for ruta in (CFG, CFG_ALT):
        try:
            os.makedirs(os.path.dirname(ruta), exist_ok=True)
            with open(ruta, "w", encoding="utf-8") as f:
                json.dump(datos, f, indent=2, ensure_ascii=False)
            return True
        except OSError:
            continue   # sin permisos aquí: se intenta en la copia de respaldo
    return False


def red_local():
    """Prefijo de la red de ESTE PC (ej. '192.168.0.') para que el buscador
    de servidores sepa dónde buscar."""
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))
        ip = s.getsockname()[0]
        s.close()
        return ip.rsplit(".", 1)[0] + "."
    except OSError:
        return "192.168.0."


PAGINA = """<!doctype html><html lang="es"><head><meta charset="utf-8">
<title>Inventario RFID</title></head>
<body style="font-family:'Segoe UI',Arial,sans-serif;background:#F3F1EF;display:flex;
             align-items:center;justify-content:center;height:96vh;margin:0">
<div id="caja" style="background:#fff;border:1px solid #E7E5E3;border-radius:8px;
            padding:28px 32px;max-width:440px;box-shadow:0 8px 30px rgba(0,0,0,.12)">
  <h2 id="tit" style="margin:0 0 6px;color:#5A5856">Conectando…</h2>
  <p id="txt" style="color:#5A5856;font-size:14px;line-height:1.5">
    Buscando el PC principal del inventario…</p>
  <div id="form" style="display:none">
    <label style="font-size:13px;color:#5A5856;font-weight:600">Dirección del PC principal
      <input id="ip" style="width:100%;padding:8px;margin-top:4px;border:1px solid #C8C6C4;
                     border-radius:4px;font-size:15px;box-sizing:border-box">
    </label>
    <button onclick="reintentar()"
            style="margin-top:14px;width:100%;padding:10px;background:__ACC__;border:none;
                   border-radius:4px;color:#fff;font-size:15px;font-weight:600;cursor:pointer">
      Guardar y reintentar</button>
    <button id="btn-buscar" onclick="buscarServidores()"
            style="margin-top:8px;width:100%;padding:9px;background:#fff;border:1px solid #C8C6C4;
                   border-radius:4px;color:#5A5856;font-size:14px;cursor:pointer">
      🔍 Buscar el servidor en la red (elige el PC por su nombre)</button>
    <div id="res-buscar"></div>
  </div>
  <div id="msg" style="color:#B3261E;font-size:13px;margin-top:10px;min-height:18px"></div>
</div>
<script>
var PREDET = "__DIR__";
function direccion(){
  var d = "";
  try{ d = localStorage.getItem("servidor") || ""; }catch(e){}
  return (d || PREDET).trim();
}
function probar(dir, cuandoBien, cuandoMal){
  var ctl = new AbortController();
  var t = setTimeout(function(){ ctl.abort(); }, 3000);
  fetch("http://" + dir + "__RUTA__", {mode: "no-cors", cache: "no-store",
                                       signal: ctl.signal})
    .then(function(){ clearTimeout(t); cuandoBien(); })
    .catch(function(){ clearTimeout(t); cuandoMal(); });
}
function entrar(dir){ location.href = "http://" + dir + "__RUTA__"; }
function fallo(){
  document.getElementById("tit").textContent = "Buscando el PC principal…";
  document.getElementById("tit").style.color = "#C25705";
  document.getElementById("txt").innerHTML =
    "No contestó en <b>" + direccion() + "</b>. Puede que ese PC haya cambiado " +
    "de dirección: se está buscando solo en la red…";
  document.getElementById("form").style.display = "";
  document.getElementById("ip").value = direccion();
  buscarServidores(true);   // automático: si aparece uno solo, entra directo
}
function nadie(){
  document.getElementById("tit").textContent = "No se pudo conectar";
  document.getElementById("txt").innerHTML =
    "Este PC trabaja conectado al <b>PC principal</b> (donde está instalado el " +
    "programa del inventario). Revisa que ese PC esté <b>prendido</b> y con el " +
    "programa <b>abierto</b>, y que este PC tenga red.";
}
function reintentar(){
  var dir = (document.getElementById("ip").value || "").trim();
  if(!dir) return;
  if(dir.indexOf(":") < 0) dir += ":5000";
  document.getElementById("msg").textContent = "⏳ Probando…";
  probar(dir, function(){
    try{ localStorage.setItem("servidor", dir); }catch(e){}
    entrar(dir);
  }, function(){
    document.getElementById("msg").textContent =
      "✖ No contesta en " + dir + ". ¿El programa está abierto en el PC principal?";
  });
}
document.addEventListener("keydown", function(e){
  if(e.key === "Enter" && document.getElementById("form").style.display !== "none")
    reintentar();
});
/* --- buscador de servidores: escanea la red y muestra NOMBRE DE PC + IP --- */
var RED = "__RED__";
function elegirServidor(ip){
  var dir = ip + ":5000";
  try{ localStorage.setItem("servidor", dir); }catch(e){}
  entrar(dir);
}
function quienEs(ip){
  return new Promise(function(listo){
    var ctl = new AbortController();
    var t = setTimeout(function(){ ctl.abort(); listo(null); }, 1200);
    fetch("http://" + ip + ":5000/api/quien", {signal: ctl.signal, cache: "no-store"})
      .then(function(r){ return r.ok ? r.json() : null; })
      .then(function(j){
        clearTimeout(t);
        listo(j && j.inventario ? {ip: ip, nombre: j.nombre || ip} : null);
      })
      .catch(function(){ clearTimeout(t); listo(null); });
  });
}
function buscarServidores(automatico){
  var b = document.getElementById("btn-buscar");
  var res = document.getElementById("res-buscar");
  b.disabled = true;
  var hallados = [], vistos = 0, pend = [];
  for(var n = 1; n <= 254; n++) pend.push(RED + n);
  res.innerHTML = "<div id='res-est' style='color:#5A5856;font-size:12.5px;margin-top:8px'>" +
                  "🔎 Buscando en " + RED + "1-254…</div><div id='res-lista'></div>";
  function pinta(){
    document.getElementById("res-lista").innerHTML = hallados.map(function(h){
      return "<button onclick=\\"elegirServidor('" + h.ip + "')\\" " +
        "style='margin-top:6px;width:100%;padding:9px;background:#F0F8F1;border:1px solid #B7DFB9;" +
        "border-radius:4px;font-size:14px;cursor:pointer;text-align:left'>" +
        "🖥 <b>" + h.nombre + "</b> — " + h.ip + "</button>";
    }).join("");
  }
  function lote(){
    if(!pend.length){
      b.disabled = false;
      // encontrado uno solo en una búsqueda automática: entra sin preguntar
      // (la dirección queda guardada para la próxima vez)
      if(automatico && hallados.length === 1){
        document.getElementById("res-est").textContent =
          "✔ Encontrado: " + hallados[0].nombre + " — " + hallados[0].ip + ". Entrando…";
        elegirServidor(hallados[0].ip);
        return;
      }
      if(!hallados.length && automatico) nadie();
      document.getElementById("res-est").textContent = hallados.length
        ? "✔ " + hallados.length + " servidor(es) — toca el tuyo:"
        : "✖ No se encontró el servidor. ¿Está prendido ese PC y con el programa corriendo?";
      pinta();
      return;
    }
    Promise.all(pend.splice(0, 40).map(quienEs)).then(function(rs){
      rs.forEach(function(r){ if(r) hallados.push(r); });
      vistos += 40;
      var est = document.getElementById("res-est");
      if(est && pend.length) est.textContent = "🔎 Buscando… " +
        Math.min(100, Math.round(vistos / 254 * 100)) + "%";
      pinta();
      lote();
    });
  }
  lote();
}
probar(direccion(), function(){ entrar(direccion()); }, fallo);
</script>
</body></html>"""


def pagina():
    ruta = {"vendedor": "/escritorio?modo=vendedor",
            "principal": "/escritorio?modo=principal"}.get(MODO, "/escritorio")
    acc = {"vendedor": "#1F7A44",      # verde vendedores
           "principal": "#C62828"}.get(MODO, "#E87722")   # rojo principal
    return (PAGINA.replace("__DIR__", html.escape(direccion_predeterminada()))
                  .replace("__RUTA__", ruta).replace("__ACC__", acc)
                  .replace("__RED__", red_local()))


def vigilar_servidor(ventana):
    """Mira a qué dirección quedó conectada la ventana y la guarda en
    cliente.json. Es la forma segura de recordarla: el puente JS-Python de
    pywebview congela la ventana con páginas remotas, así que en vez de que
    la página avise, se lee la dirección que el propio navegador ya cargó."""
    while True:
        time.sleep(2)
        try:
            url = ventana.get_current_url() or ""
        except Exception:
            continue
        m = re.match(r"https?://([^/?#]+)", url)
        if not m:
            continue                      # la pantalla local de conexión
        direccion = m.group(1)
        if direccion.startswith(("127.0.0.1", "localhost", "0.0.0.0")):
            continue
        if ":" not in direccion:
            direccion += ":5000"
        guardar_direccion(direccion)


def main():
    global MODO
    # El modo se elige al INSTALAR y viaja en el acceso directo, así que este
    # mismo programa sirve para los tres tipos de PC.
    if "--vendedor" in sys.argv:
        MODO = "vendedor"
    elif "--principal" in sys.argv and MODO != "vendedor":
        MODO = "principal"
    import webview
    titulo = {"vendedor": f"Inventario RFID · {socket.gethostname()} (consulta vendedores)",
              "principal": f"Inventario RFID · {socket.gethostname()} · PC PRINCIPAL"} \
        .get(MODO, f"Inventario RFID · {socket.gethostname()} (conectado al servidor)")
    ventana = webview.create_window(titulo, html=pagina(), width=1280, height=820)
    threading.Thread(target=vigilar_servidor, args=(ventana,), daemon=True).start()
    webview.start(private_mode=False)   # persistente: recuerda la dirección


if __name__ == "__main__":
    main()
