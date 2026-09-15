# -*- coding: utf-8 -*-
"""Imprimir por la impresora INSTALADA EN WINDOWS (USB o red) en vez de por IP."""
import os
import sys
import tempfile

from _comun import ruta  # noqa: E402  (deja el programa a mano)
import app as A

TMP = tempfile.mkdtemp(prefix="rfid_impwin_")
A.DB = os.path.join(TMP, "t.db")
A.CFG = os.path.join(TMP, "c.json")
A.BASE = TMP
A.init_db()
ok = lambda m: print("[OK] " + m)
cl = A.app.test_client()

# se cambian los dos caminos de salida por espías
por_red, por_win = [], []
A._mandar_zpl = lambda datos, ip, puerto, timeout=6: por_red.append((ip, puerto, datos))
A.mandar_windows = lambda nombre, datos: por_win.append((nombre, datos))

c = A.cfg()
assert c["zebra_salida"] == "red" and c["sat_salida"] == "red"
ok("de entrada las dos siguen saliendo POR RED (no cambia nada de lo que ya funcionaba)")

# --- por red: como siempre ---
c["impresora_ip"] = "192.168.0.29"
c["sat_ip"] = "192.168.0.32"
A.guardar_cfg(c)
A.enviar_zpl("^XA^XZ", A.cfg())
A.enviar_descripcion(b"SIZE 50 mm", A.cfg())
assert por_red[0][0] == "192.168.0.29" and por_red[1][0] == "192.168.0.32"
assert not por_win
ok("por red, cada una va a SU IP")

# --- por Windows ---
por_red.clear()
c = A.cfg()
c["zebra_salida"] = "windows"; c["zebra_impresora_win"] = "Zebra ZT411 (203 dpi)"
c["sat_salida"] = "windows"; c["sat_impresora_win"] = "SAT TT448-2 USE"
A.guardar_cfg(c)
A.enviar_zpl("^XA^XZ", A.cfg())
A.enviar_descripcion(b"SIZE 50 mm", A.cfg())
assert not por_red, "ya no debe tocar la red"
assert por_win[0][0] == "Zebra ZT411 (203 dpi)"
assert por_win[1][0] == "SAT TT448-2 USE"
ok("por Windows, cada una va a SU impresora instalada y NO se toca la red")

# --- cada impresora es independiente ---
por_red.clear(); por_win.clear()
c = A.cfg(); c["sat_salida"] = "red"; A.guardar_cfg(c)
A.enviar_zpl("^XA^XZ", A.cfg())
A.enviar_descripcion(b"SIZE 50 mm", A.cfg())
assert len(por_win) == 1 and por_win[0][0] == "Zebra ZT411 (203 dpi)"
assert len(por_red) == 1 and por_red[0][0] == "192.168.0.32"
ok("se pueden mezclar: la Zebra por Windows y la SAT por red")

# --- elegir «por Windows» sin decir cuál se corrige solo ---
r = cl.post("/api/config", json={"zebra_salida": "windows", "zebra_impresora_win": "",
                                 "sat_salida": "windows", "sat_impresora_win": ""})
assert r.get_json()["ok"]
c = A.cfg()
assert c["zebra_salida"] == "red" and c["sat_salida"] == "red"
ok("marcar «por Windows» sin elegir impresora vuelve a red (en vez de dejar de imprimir)")

# --- valores inventados ---
cl.post("/api/config", json={"zebra_salida": "bluetooth", "sat_salida": "🖨"})
c = A.cfg()
assert c["zebra_salida"] == "red" and c["sat_salida"] == "red"
ok("un valor inventado no rompe nada: se queda en red")

# --- etiqueta de prueba ---
c = A.cfg()
c["zebra_salida"] = "windows"; c["zebra_impresora_win"] = "MI ZEBRA"
c["sat_lenguaje"] = "tspl"; c["sat_ip"] = "192.168.0.32"
A.guardar_cfg(c)
por_win.clear(); por_red.clear()
j = cl.post("/api/impresora/probar", json={"tipo": "zebra"}).get_json()
assert j["ok"] and j["ruta"] == "por Windows: MI ZEBRA", j
assert por_win and "PRUEBA ZEBRA" in por_win[0][1]
assert "por Windows: MI ZEBRA" in por_win[0][1], "la etiqueta dice por dónde salió"
ok("la etiqueta de prueba de la Zebra sale por Windows y lo dice impreso")

j = cl.post("/api/impresora/probar", json={"tipo": "sat"}).get_json()
assert j["ok"] and "192.168.0.32" in j["ruta"], j
txt = por_red[0][2].decode("latin-1")
assert txt.startswith("SIZE ") and "PRUEBA SAT (TSPL)" in txt and "PRINT 1,1" in txt
ok("la de la SAT sale en TSPL por su IP, con SIZE y PRINT como toca")

# en modo ZPL la SAT manda ZPL
c = A.cfg(); c["sat_lenguaje"] = "zpl"; A.guardar_cfg(c)
por_red.clear()
cl.post("/api/impresora/probar", json={"tipo": "sat"})
txt = por_red[0][2].decode("latin-1")
assert txt.startswith("^XA") and "PRUEBA SAT (ZPL)" in txt
ok("si se pone en ZPL, la prueba sale en ZPL: sirve para ver cuál entiende")

# --- si la impresora falla, error claro y 502 ---
def revienta(nombre, datos):
    raise OSError("Windows no encuentra la impresora «MI ZEBRA»")
A.mandar_windows = revienta
r = cl.post("/api/impresora/probar", json={"tipo": "zebra"})
assert r.status_code == 502 and "no encuentra" in r.get_json()["error"]
ok("si falla, se ve el motivo en pantalla en vez de un silencio")

# --- la lista de impresoras de Windows ---
A.impresoras_windows = lambda: ["Zebra ZT411 (203 dpi)", "SAT TT448-2 USE", "Fax"]
j = cl.get("/api/impresoras_windows").get_json()
assert j["lista"] == ["Zebra ZT411 (203 dpi)", "SAT TT448-2 USE", "Fax"]
assert j["zebra"] == "MI ZEBRA"
ok("la pantalla puede ofrecer la lista de impresoras instaladas")

# --- la pantalla ---
h = cl.get("/escritorio").get_data(as_text=True)
for marca in ("function bloqueConexion", "function probarImpresora", "function pintarConexion",
              "Por Windows (USB o la instalada)", "🖨️ Etiqueta de prueba",
              "zebra_salida:q('#c-zeb-salida').value", "sat_salida:q('#c-sat-salida').value"):
    assert marca in h, marca
ok("⚙ Configuración trae el selector de conexión y el botón de prueba en las DOS")

print("\nTODAS LAS PRUEBAS PASARON")
