# -*- coding: utf-8 -*-
"""Impresión por lotes de balizas: se eligen bodega, letras y números."""
import os
import sqlite3
import sys
import tempfile
from datetime import datetime

from _comun import ruta  # noqa: E402  (deja el programa a mano)
import app as A

TMP = tempfile.mkdtemp(prefix="rfid_balimp_")
A.DB = os.path.join(TMP, "t.db")
A.CFG = os.path.join(TMP, "c.json")
A.BASE = TMP
A.init_db()
ok = lambda m: print("[OK] " + m)
cl = A.app.test_client()
con = sqlite3.connect(A.DB)
con.row_factory = sqlite3.Row

# la impresora no existe: se sustituye el envío y se guarda lo que se mandaría
enviados = []
A.enviar_zpl = lambda zpl, c: enviados.append(zpl)

c = A.cfg()
c["codificar_rfid"] = True          # ZT411R: graba el chip
c["etiqueta_ancho_mm"], c["etiqueta_alto_mm"], c["dpi"] = 100, 50, 300
A.guardar_cfg(c)

# --- vista previa: no imprime ni da de alta ---
j = cl.post("/api/balizas/imprimir", json={"bodega": "bodega 8", "desde_letra": "a",
                                           "hasta_letra": "c", "desde_num": 1,
                                           "hasta_num": 4, "solo_ver": True}).get_json()
assert j["total"] == 12 and j["nuevas"] == 12 and j["reimpresas"] == 0, j
assert j["bodega"] == "BODEGA 8"
assert [x["posicion"] for x in j["etiquetas"][:5]] == ["A1", "A2", "A3", "A4", "B1"], j["etiquetas"][:5]
assert not enviados and not con.execute("SELECT COUNT(*) c FROM balizas").fetchone()["c"]
ok("la vista previa dice cuántas salen (3 letras x 4 números = 12) sin imprimir nada")

# --- impresión de verdad ---
j = cl.post("/api/balizas/imprimir", json={"bodega": "BODEGA 8", "desde_letra": "A",
                                           "hasta_letra": "C", "desde_num": 1,
                                           "hasta_num": 4}).get_json()
assert j["ok"] and j["impresas"] == 12, j
assert len(enviados) == 12
filas = con.execute("SELECT * FROM balizas ORDER BY posicion").fetchall()
assert len(filas) == 12
assert {f["posicion"] for f in filas} == {l + str(n) for l in "ABC" for n in range(1, 5)}
assert all(f["bodega"] == "BODEGA 8" for f in filas)
ok("se imprimen las 12 y quedan dadas de alta solas, sin leer nada con la pistola")

# --- el EPC lleva la posición dentro ---
b12 = con.execute("SELECT * FROM balizas WHERE posicion='B2'").fetchone()
assert len(b12["epc"]) == 24 and b12["epc"].startswith("AF02"), b12["epc"]
assert A.decodificar_baliza(b12["epc"]) == "B2", A.decodificar_baliza(b12["epc"])
assert len({f["epc"] for f in filas}) == 12, "cada baliza necesita su propio EPC"
ok("el EPC es AF02 + la posición dentro: se reconoce aunque se pierda la base")

# --- el ZPL graba el chip y lleva la posición en grande ---
z = enviados[0]
assert "^RFW,H,,,A^FD" + filas[0]["epc"] in z, z[:400]
assert "^FDA1^FS" in z and "^FDBODEGA 8^FS" in z
assert "BALIZA DE POSICION - NO QUITAR" in z
assert "^PW1181" in z and "^LL590" in z          # 100x50 mm a 300 ppp
ok("el ZPL graba el chip, pone la posición en grande y avisa de no quitarla")

# --- reimprimir conserva el EPC (etiqueta rota) ---
antes = {f["posicion"]: f["epc"] for f in filas}
enviados.clear()
j = cl.post("/api/balizas/imprimir", json={"bodega": "BODEGA 8", "desde_letra": "A",
                                           "hasta_letra": "A", "desde_num": 1,
                                           "hasta_num": 2, "solo_ver": True}).get_json()
assert j["nuevas"] == 0 and j["reimpresas"] == 2, j
cl.post("/api/balizas/imprimir", json={"bodega": "BODEGA 8", "desde_letra": "A",
                                       "hasta_letra": "A", "desde_num": 1, "hasta_num": 2})
assert con.execute("SELECT COUNT(*) c FROM balizas").fetchone()["c"] == 12, "no debe duplicar"
assert con.execute("SELECT epc FROM balizas WHERE posicion='A1'").fetchone()["epc"] == antes["A1"]
assert antes["A1"] in enviados[0]
ok("reimprimir una casilla reusa SU MISMO chip: la etiqueta vieja sigue valiendo")

# --- otra bodega puede repetir las mismas posiciones ---
cl.post("/api/balizas/imprimir", json={"bodega": "ALMACEN", "desde_letra": "A",
                                       "hasta_letra": "A", "desde_num": 1, "hasta_num": 2})
assert con.execute("SELECT COUNT(*) c FROM balizas").fetchone()["c"] == 14
a1 = con.execute("SELECT epc, bodega FROM balizas WHERE posicion='A1' ORDER BY bodega").fetchall()
assert len(a1) == 2 and a1[0]["epc"] != a1[1]["epc"]
ok("la A1 de ALMACEN y la A1 de BODEGA 8 son balizas distintas")

# --- validaciones ---
assert cl.post("/api/balizas/imprimir", json={"bodega": ""}).status_code == 400
r = cl.post("/api/balizas/imprimir", json={"bodega": "X", "desde_letra": "1",
                                           "hasta_letra": "9"})
assert r.status_code == 400 and "A a la Z" in r.get_json()["error"]
r = cl.post("/api/balizas/imprimir", json={"bodega": "X", "desde_letra": "A", "hasta_letra": "A",
                                           "desde_num": 0, "hasta_num": 5})
assert r.status_code == 400 and "1 al 99" in r.get_json()["error"]
r = cl.post("/api/balizas/imprimir", json={"bodega": "X", "desde_letra": "A", "hasta_letra": "Z",
                                           "desde_num": 1, "hasta_num": 99})
assert r.status_code == 400 and "tope" in r.get_json()["error"], r.get_json()
ok("no deja letras raras, número 0, ni un lote de 2.574 etiquetas de un clic")

# al revés también vale: de la F a la A
enviados.clear()
j = cl.post("/api/balizas/imprimir", json={"bodega": "ALMACEN", "desde_letra": "C",
                                           "hasta_letra": "A", "desde_num": 3,
                                           "hasta_num": 1, "solo_ver": True}).get_json()
assert j["total"] == 9 and j["etiquetas"][0]["posicion"] == "A1"
ok("si se ponen los rangos al revés se ordenan solos")

# --- si la impresora falla no se dan de alta etiquetas que no salieron ---
def revienta(zpl, c):
    raise OSError("impresora apagada")
A.enviar_zpl = revienta
antes_n = con.execute("SELECT COUNT(*) c FROM balizas").fetchone()["c"]
r = cl.post("/api/balizas/imprimir", json={"bodega": "BODEGA 9", "desde_letra": "A",
                                           "hasta_letra": "A", "desde_num": 1, "hasta_num": 3})
assert r.status_code == 502 and "impresora" in r.get_json()["error"]
assert con.execute("SELECT COUNT(*) c FROM balizas").fetchone()["c"] == antes_n
ok("si la impresora no responde NO se dan de alta balizas que nunca salieron")

# --- una baliza impresa pero borrada no ensucia el conteo ---
A.enviar_zpl = lambda zpl, c: enviados.append(zpl)
epc_huerfano = con.execute("SELECT epc FROM balizas WHERE posicion='C4'").fetchone()["epc"]
cl.post("/api/balizas/borrar", json={"epc": epc_huerfano})
cl.post("/api/lecturas", json={"dispositivo": "C72", "epcs": [epc_huerfano]})
assert con.execute("SELECT COUNT(*) c FROM lecturas WHERE epc=?",
                   (epc_huerfano,)).fetchone()["c"] == 0
ok("una baliza que se dio de baja se ignora, no se cuenta como repuesto perdido")

# --- la pantalla ---
h = cl.get("/escritorio").get_data(as_text=True)
for marca in ("🖨️ Imprimir balizas", "function imprimirBalizas", "function resumenBI",
              'id="f-bi-l1"', 'id="f-bi-n2"', "se reimprimen con su mismo chip"):
    assert marca in h, marca
ok("la pantalla trae el botón de imprimir, los rangos y el resumen antes de dar a imprimir")
con.close()

print("\nTODAS LAS PRUEBAS PASARON")
