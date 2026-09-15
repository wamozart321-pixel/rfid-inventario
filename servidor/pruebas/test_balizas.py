# -*- coding: utf-8 -*-
"""Balizas: etiquetas fijas del estante que sitúan a la pistola."""
import os
import sqlite3
import sys
import tempfile
from datetime import datetime, timedelta

from _comun import ruta  # noqa: E402  (deja el programa a mano)
import app as A

TMP = tempfile.mkdtemp(prefix="rfid_bal_")
A.DB = os.path.join(TMP, "t.db")
A.CFG = os.path.join(TMP, "c.json")
A.BASE = TMP
A.init_db()
ok = lambda m: print("[OK] " + m)
cl = A.app.test_client()
con = sqlite3.connect(A.DB)
con.row_factory = sqlite3.Row

# --- repuestos con su etiqueta puesta ---
for sku in ("BOBINA-1", "PASTILLA-2", "FILTRO-3"):
    cl.post("/api/productos/guardar", json={"sku": sku, "nombre": "PROD " + sku,
                                            "precio_minimo": "0", "precio": "0"})
ids = {r["sku"]: r["id"] for r in con.execute("SELECT id, sku FROM productos")}
EPC = {"BOBINA-1": "E28011AA01", "PASTILLA-2": "E28011AA02", "FILTRO-3": "E28011AA03"}
for sku, epc in EPC.items():
    con.execute("INSERT INTO tags(epc,producto_id,creado) VALUES(?,?,?)",
                (epc, ids[sku], datetime.now().isoformat()))
con.commit()

# --- dar de alta dos balizas ---
r = cl.post("/api/balizas", json={"epc": "BAL-B12", "bodega": "bodega 8",
                                  "posicion": "b12", "nota": "estante del fondo"})
assert r.get_json()["ok"] and r.get_json()["sitio"] == "BODEGA 8 / B12", r.get_json()
cl.post("/api/balizas", json={"epc": "BAL-C04", "bodega": "BODEGA 8", "posicion": "C04"})
b = con.execute("SELECT * FROM balizas WHERE epc='BAL-B12'").fetchone()
assert b["bodega"] == "BODEGA 8" and b["posicion"] == "B12"
ok("se dan de alta balizas y se guardan en MAYÚSCULAS aunque se escriban en minúscula")

# --- validaciones ---
assert cl.post("/api/balizas", json={"epc": "", "bodega": "X", "posicion": "1"}).status_code == 400
assert cl.post("/api/balizas", json={"epc": "Z9", "bodega": "", "posicion": ""}).status_code == 400
r = cl.post("/api/balizas", json={"epc": "E28011AA01", "bodega": "BODEGA 8", "posicion": "A1"})
assert r.status_code == 409 and "repuesto" in r.get_json()["error"]
ok("no deja usar como baliza una etiqueta que ya está puesta en un repuesto")

# --- la pistola lee: primero la baliza, luego los repuestos ---
r = cl.post("/api/lecturas", json={"dispositivo": "C72-01",
                                   "epcs": ["BAL-B12", EPC["BOBINA-1"], EPC["PASTILLA-2"]]})
j = r.get_json()
sid = j["sesion_id"]
assert j["balizas"] == 1 and j["nuevos"] == 2, j
assert j["sitio"] == "BODEGA 8 / B12", j
ok("al leer la baliza la pistola queda situada y lo de después se apunta ahí")

# la baliza NO se cuenta como repuesto ni sale en «desconocidos»
assert con.execute("SELECT COUNT(*) c FROM lecturas WHERE epc='BAL-B12'").fetchone()["c"] == 0
assert not [x for x in cl.get("/api/desconocidos").get_json() if x["epc"] == "BAL-B12"]
ok("la baliza no se cuenta como repuesto ni aparece como etiqueta desconocida")

# --- la pistola sigue situada en lotes siguientes ---
cl.post("/api/lecturas", json={"dispositivo": "C72-01", "epcs": [EPC["FILTRO-3"]]})
d = con.execute("""SELECT * FROM detecciones_pos WHERE epc=? AND posicion='B12'""",
                (EPC["FILTRO-3"],)).fetchone()
assert d and d["veces"] == 1
ok("la pistola sigue situada en el siguiente envío, sin volver a leer la baliza")

# --- votación: gana el sitio donde más veces se vio ---
for _ in range(9):
    cl.post("/api/lecturas", json={"dispositivo": "C72-01", "epcs": [EPC["BOBINA-1"]]})
cl.post("/api/lecturas", json={"dispositivo": "C72-01", "epcs": ["BAL-C04", EPC["BOBINA-1"]]})
v = {r["posicion"]: r["veces"] for r in con.execute(
    "SELECT posicion, veces FROM detecciones_pos WHERE epc=?", (EPC["BOBINA-1"],))}
assert v == {"B12": 10, "C04": 1}, v
ok("se cuentan las lecturas repetidas: 10 veces en B12 y 1 (eco) en C04")

j = cl.get("/api/balizas/propuestas").get_json()
p = next(x for x in j["propuestas"] if x["sku"] == "BOBINA-1")
assert p["posicion"] == "B12", p
assert p["confianza"] == 91, p["confianza"]
assert p["otras"] == [{"posicion": "C04", "veces": 1}], p["otras"]
ok("gana B12 con 91% de seguridad: el eco del pasillo de al lado no manda")

# --- un repuesto con VARIAS etiquetas (una por unidad) cuenta como uno solo ---
# (esto se escapó en la primera versión: cada etiqueta parecía un sitio distinto
#  y la seguridad salía absurdamente baja)
for extra in ("E28011BB01", "E28011BB02"):
    con.execute("INSERT INTO tags(epc,producto_id,creado) VALUES(?,?,?)",
                (extra, ids["PASTILLA-2"], datetime.now().isoformat()))
con.commit()
cl.post("/api/lecturas", json={"dispositivo": "C72-01", "epcs": ["BAL-B12"]})
for _ in range(4):
    cl.post("/api/lecturas", json={"dispositivo": "C72-01",
                                   "epcs": ["E28011BB01", "E28011BB02"]})
j = cl.get("/api/balizas/propuestas").get_json()
p = next(x for x in j["propuestas"] if x["sku"] == "PASTILLA-2")
assert p["posicion"] == "B12", p
assert p["veces"] == 9, p["veces"]          # 1 de la etiqueta original + 4 + 4
assert [o["posicion"] for o in p["otras"]] == [], p["otras"]
assert p["confianza"] == 100, p["confianza"]
ok("las 3 etiquetas del mismo repuesto suman como un solo sitio (no como 3 sitios)")

# --- proponer NO es guardar ---
assert con.execute("SELECT COUNT(*) c FROM stock_bodegas").fetchone()["c"] == 0
ok("pedir las propuestas no toca la base: solo propone")

# --- aplicar solo lo aceptado ---
r = cl.post("/api/balizas/aplicar", json={"cambios": [
    {"producto_id": ids["BOBINA-1"], "bodega": "BODEGA 8", "posicion": "B12"}]})
assert r.get_json()["aplicados"] == 1
sb = con.execute("SELECT * FROM stock_bodegas WHERE producto_id=?",
                 (ids["BOBINA-1"],)).fetchone()
assert sb["bodega"] == "BODEGA 8" and sb["posicion"] == "B12"
assert con.execute("SELECT COUNT(*) c FROM stock_bodegas").fetchone()["c"] == 1
ok("solo se guarda lo que se aceptó; los demás repuestos quedan intactos")

# aplicar sobre una posición que ya existía la reemplaza, sin borrar el stock
con.execute("UPDATE stock_bodegas SET cantidad=7 WHERE producto_id=?", (ids["BOBINA-1"],))
con.commit()
cl.post("/api/balizas/aplicar", json={"cambios": [
    {"producto_id": ids["BOBINA-1"], "bodega": "BODEGA 8", "posicion": "Z99"}]})
sb = con.execute("SELECT * FROM stock_bodegas WHERE producto_id=?",
                 (ids["BOBINA-1"],)).fetchone()
assert sb["posicion"] == "Z99" and sb["cantidad"] == 7, dict(sb)
ok("al corregir la posición no se pierde la cantidad que había en esa bodega")

# basura: se ignora en vez de reventar
r = cl.post("/api/balizas/aplicar", json={"cambios": [
    {"producto_id": 999999, "bodega": "X", "posicion": "1"},
    {"producto_id": "no soy un número", "bodega": "X", "posicion": "1"},
    {"producto_id": ids["FILTRO-3"], "bodega": "BODEGA 8", "posicion": ""}]})
assert r.get_json()["aplicados"] == 0, r.get_json()
ok("datos inválidos se descartan sin romper nada")

# --- si hace mucho que no lee una baliza, deja de estar situada ---
con.execute("UPDATE dispositivo_pos SET ts=? WHERE dispositivo='C72-01'",
            ((datetime.now() - timedelta(minutes=A.BALIZA_MINUTOS + 5)).isoformat(),))
con.commit()
antes = con.execute("SELECT IFNULL(SUM(veces),0) v FROM detecciones_pos").fetchone()["v"]
j = cl.post("/api/lecturas", json={"dispositivo": "C72-01",
                                   "epcs": [EPC["PASTILLA-2"]]}).get_json()
despues = con.execute("SELECT IFNULL(SUM(veces),0) v FROM detecciones_pos").fetchone()["v"]
assert j["sitio"] == "" and despues == antes, (j, antes, despues)
ok("si la última baliza es vieja, no se inventa la posición: se deja en blanco")

# --- cada pistola va por su lado ---
cl.post("/api/lecturas", json={"dispositivo": "ALIEN-02", "epcs": ["BAL-C04"]})
cl.post("/api/lecturas", json={"dispositivo": "ALIEN-02", "epcs": [EPC["FILTRO-3"]]})
v = {r["posicion"]: r["veces"] for r in con.execute(
    "SELECT posicion, veces FROM detecciones_pos WHERE epc=?", (EPC["FILTRO-3"],))}
assert v == {"B12": 1, "C04": 1}, v
ok("dos pistolas a la vez no se pisan: cada una recuerda su propio sitio")

# --- catálogo que descargan las pistolas ---
tt = cl.get("/api/tags/todos").get_json()
assert tt["balizas"]["BAL-B12"] == ["BODEGA 8", "B12"], tt["balizas"]
ok("el catálogo que descarga la pistola incluye las balizas")

# --- borrar ---
assert cl.post("/api/balizas/borrar", json={"epc": "NO-EXISTE"}).status_code == 404
assert cl.post("/api/balizas/borrar", json={"epc": "BAL-C04"}).get_json()["ok"]
assert not con.execute("SELECT 1 FROM balizas WHERE epc='BAL-C04'").fetchone()
assert con.execute("SELECT COUNT(*) c FROM detecciones_pos WHERE posicion='C04'").fetchone()["c"] > 0
ok("al quitar una baliza no se borra lo que ya se había situado con ella")

# --- listado con contador ---
lst = cl.get("/api/balizas").get_json()
assert len(lst) == 1 and lst[0]["epc"] == "BAL-B12" and lst[0]["situadas"] > 0
ok("el listado dice cuántas lecturas ha situado cada baliza")

# --- la pantalla ---
h = cl.get("/escritorio").get_data(as_text=True)
for marca in ("🧭 Balizas", 'id="v-balizas"', "function verBalizas", "function nuevaBaliza",
              "function aplicarPropuestas", 'id="t-propuestas"', "Seguridad",
              "reemplaza</b> la posición"):
    assert marca in h, marca
ok("la pantalla trae las balizas, las propuestas y el aviso antes de reemplazar")
con.close()

print("\nTODAS LAS PRUEBAS PASARON")
