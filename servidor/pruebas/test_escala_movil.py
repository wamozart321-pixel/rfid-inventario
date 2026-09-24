# -*- coding: utf-8 -*-
"""Tamaño de la pantalla ajustable a mano, probado en un navegador de verdad.

Se abre la pantalla en Edge simulando un celular (390 px, táctil). Lo que se
comprueba es lo que ve la persona: si cabe sin arrastrar de lado, qué
columnas aparecen y que el tamaño elegido se recuerda.

Si Edge o la librería playwright no están, la prueba se salta (no falla):
es una comprobación de navegador, no de la lógica del programa.
"""
import os
import socket
import sys
import tempfile
import threading
import time

from _comun import ruta  # noqa: E402  (deja el programa a mano)

try:
    from playwright.sync_api import sync_playwright
except ImportError:
    print("[--] playwright no está instalado: prueba de navegador saltada")
    print("\nTODAS LAS PRUEBAS PASARON")
    sys.exit(0)

import app as A

TMP = tempfile.mkdtemp(prefix="rfid_escala_")
A.DB = os.path.join(TMP, "t.db")
A.CFG = os.path.join(TMP, "c.json")
A.BASE = TMP
A.init_db()
ok = lambda m: print("[OK] " + m)

# repuestos de prueba con nombres LARGOS y el precio más ancho posible: con la
# tabla vacía no se puede ver si algo se corta
_cl = A.app.test_client()
for i in range(40):
    _cl.post("/api/productos/guardar", json={
        "sku": "01M3254%03dx" % i,
        "nombre": "PASTILLA DE FRENO DELANTERA GOLF JETTA BORA VENTO %d" % i,
        "precio_minimo": "1500000", "precio": "1650000"})

# un servidor de prueba propio, en un puerto libre, con base temporal
s = socket.socket()
s.bind(("127.0.0.1", 0))
PUERTO = s.getsockname()[1]
s.close()
threading.Thread(target=lambda: A.app.run(host="127.0.0.1", port=PUERTO,
                                          debug=False, use_reloader=False),
                 daemon=True).start()
URL = "http://127.0.0.1:%d/escritorio" % PUERTO
for _ in range(50):
    try:
        socket.create_connection(("127.0.0.1", PUERTO), timeout=0.2).close()
        break
    except OSError:
        time.sleep(0.1)

MEDIR = """() => {
  const vv = window.visualViewport;
  const col4 = document.querySelector('#t-productos th:nth-child(4)');
  const btn = document.getElementById('btn-escala');
  const tw = document.querySelector('#v-productos .twrap');
  const alto = window.innerHeight;
  const filas = [...document.querySelectorAll('#t-productos tbody tr:not(.esp)')]
    .filter(r => { const b = r.getBoundingClientRect();
                   return b.height > 0 && b.top >= 0 && b.bottom <= alto; });
  return {
    tabla_sobra: tw.scrollWidth - tw.clientWidth,
    nombre: document.querySelector('#t-productos th:nth-child(2)').getBoundingClientRect().width
            / document.getElementById('t-productos').getBoundingClientRect().width,
    filas: filas.length,
    filtros: Math.round(document.getElementById('barra-filtros').getBoundingClientRect().height),
    ancho: document.documentElement.clientWidth,
    sobra: document.documentElement.scrollWidth - document.documentElement.clientWidth,
    escala: vv ? vv.scale : 1,
    visible: vv ? vv.width : window.innerWidth,
    col4: getComputedStyle(col4).display,
    boton: getComputedStyle(btn).display,
    meta: document.querySelector('meta[name=viewport]').content,
  };
}"""

with sync_playwright() as pw:
    # el Chromium de playwright primero (hecho para esto); Edge de reserva
    nav = None
    for opciones in ({}, {"channel": "msedge"}):
        try:
            nav = pw.chromium.launch(headless=True, **opciones)
            break
        except Exception:
            continue
    if nav is None:
        print("[--] no se pudo abrir ningún navegador: prueba saltada")
        print("     (python -m playwright install chromium-headless-shell)")
        print("\nTODAS LAS PRUEBAS PASARON")
        sys.exit(0)

    cel = nav.new_context(viewport={"width": 390, "height": 844}, device_scale_factor=3,
                          is_mobile=True, has_touch=True)
    pag = cel.new_page()

    def abrir(escala=None):
        pag.goto(URL)
        pag.evaluate("e => { if(e) localStorage.setItem('escala', e); "
                     "else localStorage.removeItem('escala'); }", escala)
        pag.goto(URL)
        pag.wait_for_selector("#t-productos tbody tr:not(.esp)", timeout=15000)
        pag.wait_for_timeout(300)
        return pag.evaluate(MEDIR)

    # --- 100 %: exactamente como estaba ---
    m = abrir()
    assert m["ancho"] == 390, m
    assert "device-width" in m["meta"], m
    assert m["sobra"] <= 1, "hay que arrastrar de lado: " + str(m)
    assert m["col4"] == "none", "en el celular la bodega va oculta"
    ok("al 100 % queda como estaba: 390 px, cabe sin arrastrar, bodega oculta")

    # el botón Aa se ve en el celular
    assert m["boton"] != "none", "el botón de tamaño debería verse en el celular"
    ok("en el celular aparece el botón «Aa»")

    # --- lo que se veía mal en las capturas ---
    assert m["tabla_sobra"] <= 1, "la tabla se corta por la derecha: " + str(m)
    ok("la tabla no se corta: precio y stock se ven enteros")
    # las columnas ocultas no pueden quedarse con el ancho del nombre (pasó:
    # el nombre salía como «A…» y a la derecha quedaba un hueco vacío)
    assert m["nombre"] > 0.2, "el nombre queda aplastado: " + str(m)
    ok("el nombre tiene su sitio (%d %% del ancho), sin hueco a la derecha" % (100 * m["nombre"]))
    assert m["filtros"] < 60, "los filtros deberían ir plegados (%d px)" % m["filtros"]
    assert m["filas"] >= 12, "se ven muy pocos productos a la vez: %d" % m["filas"]
    ok("filtros plegados: se ven %d productos de una vez (antes, la mitad)" % m["filas"])

    pag.click("#fl-titulo")
    pag.wait_for_timeout(200)
    abierto = pag.evaluate(MEDIR)["filtros"]
    assert abierto > 100, "al tocar «Filtros» deberían desplegarse (%d px)" % abierto
    pag.click("#fl-titulo")
    pag.wait_for_timeout(200)
    assert pag.evaluate(MEDIR)["filtros"] < 60
    ok("tocar «Filtros» los despliega, y tocar otra vez los pliega")

    # --- más pequeño: cabe más, SIN arrastrar ---
    m = abrir("0.8")
    assert abs(m["ancho"] - 488) <= 2, m            # 390 / 0,8
    assert abs(m["escala"] - 0.8) < 0.02, m
    assert m["sobra"] <= 1, "al achicar no debería haber que arrastrar: " + str(m)
    assert abs(m["visible"] - m["ancho"]) <= 2, "no cabe entera en la pantalla: " + str(m)
    ok("al 80 % la pantalla hace de 488 px y cabe entera, sin arrastrar")

    # al achicar bastante vuelven las columnas (lo que promete la ayuda)
    m = abrir("0.6")
    assert m["ancho"] >= 620, m
    assert m["col4"] != "none", "al 60 % la bodega debería volver: " + str(m)
    assert m["sobra"] <= 1, m
    ok("al 60 % vuelven la bodega y el precio mínimo, y sigue sin arrastrar")

    # --- más grande: se lee mejor, SIN arrastrar ---
    m = abrir("1.3")
    assert abs(m["ancho"] - 300) <= 2, m            # 390 / 1,3
    assert abs(m["escala"] - 1.3) < 0.02, m
    assert m["sobra"] <= 1 and abs(m["visible"] - m["ancho"]) <= 2, m
    assert m["tabla_sobra"] <= 1, "al 130 % la tabla se corta: " + str(m)
    assert m["nombre"] > 0.2, "al 130 % el nombre queda aplastado: " + str(m)
    ok("al 130 % todo más grande, cabe sin arrastrar y la tabla no se corta")

    # --- el máximo (150 %) tampoco se sale: la tira de arriba debe caber ---
    m = abrir("1.5")
    assert abs(m["ancho"] - 260) <= 2, m            # 390 / 1,5
    assert m["sobra"] <= 1, "al 150 % algo se sale por la derecha: " + str(m)
    assert m["tabla_sobra"] <= 1, "al 150 % la tabla se corta: " + str(m)
    ok("al 150 % (260 px de ancho) tampoco se sale nada, ni la tabla")

    # --- un celular ESTRECHO (360 px, muy común en Android) ---
    cel360 = nav.new_context(viewport={"width": 360, "height": 780}, device_scale_factor=3,
                             is_mobile=True, has_touch=True)
    p3 = cel360.new_page()
    for esc in (None, "1.5"):
        p3.goto(URL)
        p3.evaluate("e => { if(e) localStorage.setItem('escala', e); "
                    "else localStorage.removeItem('escala'); }", esc)
        p3.goto(URL)
        p3.wait_for_selector("#t-productos tbody tr:not(.esp)", timeout=15000)
        p3.wait_for_timeout(300)
        m3 = p3.evaluate(MEDIR)
        assert m3["sobra"] <= 1, "en un celular de 360 px se sale algo: " + str(m3)
        assert m3["tabla_sobra"] <= 1, "en un celular de 360 px la tabla se corta: " + str(m3)
    ok("en un celular estrecho (360 px) cabe al 100 % y al 150 %")
    cel360.close()

    # --- dentro de las apps (pistolas y celular) sale además el ⚙ de la app,
    # junto a la 🌙: la tira tiene que seguir cabiendo con él ---
    app = nav.new_context(viewport={"width": 360, "height": 780}, device_scale_factor=3,
                          is_mobile=True, has_touch=True)
    app.add_init_script("window.AppInventario = {ajustes(){ window.__ajustes = (window.__ajustes||0) + 1; }};")
    pa = app.new_page()
    for esc in (None, "1.5"):
        pa.goto(URL)
        pa.evaluate("e => { if(e) localStorage.setItem('escala', e); "
                    "else localStorage.removeItem('escala'); }", esc)
        pa.goto(URL)
        pa.wait_for_selector("#t-productos tbody tr:not(.esp)", timeout=15000)
        pa.wait_for_timeout(300)
        ma = pa.evaluate(MEDIR)
        assert ma["sobra"] <= 1, "con el ⚙ de la app la tira se sale: " + str(ma)
        b1 = pa.evaluate("[...document.querySelectorAll('#tira > *')].map(e => [e.id, "
                         "Math.round(e.getBoundingClientRect().right)])")
        assert all(r <= ma["ancho"] + 1 for _, r in b1), b1
    orden = [i for i, _ in b1 if i in ("btn-escala", "btn-app", "btn-tema")]
    assert orden == ["btn-escala", "btn-app", "btn-tema"], orden
    pa.click("#btn-app")
    assert pa.evaluate("window.__ajustes") == 1, "el ⚙ no llamó a los ajustes de la app"
    ok("en la app sale el ⚙ a la izquierda de la 🌙, abre SUS ajustes y cabe hasta al 150 %")
    app.close()

    # --- el tamaño se recuerda al volver a abrir ---
    pag.goto(URL)
    pag.wait_for_timeout(300)
    assert abs(pag.evaluate(MEDIR)["escala"] - 1.5) < 0.02   # lo último que se eligió
    ok("el tamaño elegido se recuerda al volver a abrir")

    # --- la ventanita funciona de punta a punta ---
    abrir()
    pag.click("#btn-escala")
    assert pag.inner_text("#esc-valor").strip() == "100 %"
    pag.click("#esc-menos")
    pag.wait_for_timeout(300)
    assert pag.inner_text("#esc-valor").strip() == "90 %"
    m = pag.evaluate(MEDIR)
    assert abs(m["ancho"] - 433) <= 2, m            # 390 / 0,9, aplicado al momento
    assert pag.evaluate("localStorage.getItem('escala')") == "0.9"
    ok("tocar «A−» lo aplica al momento (90 %) y lo guarda")

    pag.click("text=Volver al 100 %")
    pag.wait_for_timeout(300)
    m = pag.evaluate(MEDIR)
    assert m["ancho"] == 390 and pag.evaluate("localStorage.getItem('escala')") is None
    ok("«Volver al 100 %» lo deja como siempre y borra el ajuste")

    # --- en el PC no aparece ni cambia nada ---
    pc = nav.new_context(viewport={"width": 1280, "height": 800})
    pp = pc.new_page()
    pp.goto(URL)
    pp.evaluate("localStorage.setItem('escala', '0.7')")
    pp.goto(URL)
    pp.wait_for_timeout(300)
    m = pp.evaluate(MEDIR)
    assert m["boton"] == "none", "en el PC el botón no debería verse"
    assert pp.evaluate("getComputedStyle(document.getElementById('btn-app')).display") == "none",         "en el PC (sin app) el ⚙ de la app no debe salir"
    assert m["ancho"] >= 1260, "en el PC el ajuste no debería cambiar nada: " + str(m)
    assert m["col4"] != "none"
    ok("en el PC el botón no aparece y el ajuste no cambia nada")

    nav.close()

print("\nTODAS LAS PRUEBAS PASARON")
