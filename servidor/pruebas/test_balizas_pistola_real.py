# -*- coding: utf-8 -*-
"""¿Funcionan las balizas con la APK que YA está instalada en la pistola?

Se imita exactamente lo que hace MainActivity.kt:
  - mientras lee, NO manda nada (todo se acumula en `tags`, un LinkedHashMap)
  - al soltar el gatillo, resolverNombres() reporta solo los DESCONOCIDOS
    (la baliza lo es para la pistola) con enviarDesconocidos()
  - al pulsar ENVIAR manda tags.keys.toList(): TODO, en el orden en que se
    leyó cada etiqueta por primera vez
"""
import os
import sqlite3
import sys
import tempfile
from datetime import datetime

from _comun import ruta  # noqa: E402  (deja el programa a mano)
import app as A

TMP = tempfile.mkdtemp(prefix="rfid_pistola_")
A.DB = os.path.join(TMP, "t.db")
A.CFG = os.path.join(TMP, "c.json")
A.BASE = TMP
A.init_db()
ok = lambda m: print("[OK] " + m)
cl = A.app.test_client()
con = sqlite3.connect(A.DB)
con.row_factory = sqlite3.Row
A.enviar_zpl = lambda zpl, c: None          # sin impresora de verdad

# --- almacén de mentira: 3 pasillos con 2 repuestos cada uno ---
pasillos = {"A1": ["BOBINA", "PASTILLA"],
            "B1": ["FILTRO", "BUJIA"],
            "C1": ["CORREA", "AMORTIGUADOR"]}
epc = {}
for skus in pasillos.values():
    for sku in skus:
        cl.post("/api/productos/guardar", json={"sku": sku, "nombre": "PROD " + sku,
                                                "precio_minimo": "0", "precio": "0"})
ids = {r["sku"]: r["id"] for r in con.execute("SELECT id, sku FROM productos")}
for skus in pasillos.values():
    for sku in skus:
        # 2 unidades de cada repuesto = 2 etiquetas, como en la vida real
        epc[sku] = [f"E280{ids[sku]:04X}{i:04X}0000000000"[:24].ljust(24, "0") for i in (1, 2)]
        for e in epc[sku]:
            con.execute("INSERT INTO tags(epc,producto_id,creado) VALUES(?,?,?)",
                        (e, ids[sku], datetime.now().isoformat()))
con.commit()

# --- se imprimen las balizas de los 3 pasillos ---
cl.post("/api/balizas/imprimir", json={"bodega": "BODEGA 8", "desde_letra": "A",
                                       "hasta_letra": "C", "desde_num": 1, "hasta_num": 1})
bal = {r["posicion"]: r["epc"] for r in con.execute("SELECT posicion, epc FROM balizas")}
assert set(bal) == {"A1", "B1", "C1"}
ok("las 3 balizas se imprimen y quedan dadas de alta")


def recorrido():
    """Lo que se lee, en orden, recorriendo los 3 pasillos de un tirón."""
    leidos = []
    for pos, skus in pasillos.items():
        leidos.append(bal[pos])                      # la baliza al entrar al pasillo
        for sku in skus:
            leidos.extend(epc[sku])                  # y luego los repuestos
    return leidos


leidos = recorrido()

# --- 1) al soltar el gatillo la pistola reporta SOLO los desconocidos ---
# (para la APK actual las balizas son etiquetas desconocidas)
desconocidos = [e for e in leidos if e in bal.values()]
cl.post("/api/lecturas", json={"dispositivo": "C72-01", "epcs": desconocidos})
ok("la pistola manda las balizas sola al soltar el gatillo (las ve como desconocidas)")

# --- 2) el usuario pulsa ENVIAR: va TODO en orden de lectura ---
j = cl.post("/api/lecturas", json={"dispositivo": "C72-01", "epcs": leidos}).get_json()
assert j["balizas"] == 3, j
assert j["nuevos"] == 12, j          # 6 repuestos x 2 etiquetas
ok("ENVIAR manda todo junto: 3 balizas + 12 etiquetas de repuesto")

# --- 3) cada repuesto quedó en SU pasillo, no todos en el último ---
prop = {p["sku"]: p for p in cl.get("/api/balizas/propuestas").get_json()["propuestas"]}
for pos, skus in pasillos.items():
    for sku in skus:
        assert prop[sku]["posicion"] == pos, (sku, prop[sku]["posicion"], "esperaba", pos)
        assert prop[sku]["confianza"] == 100, (sku, prop[sku]["confianza"])
        assert prop[sku]["bodega"] == "BODEGA 8"
ok("CADA repuesto quedó en su pasillo (A1/B1/C1), no todos en el último")
ok("las 2 etiquetas de cada repuesto suman: 100% de seguridad")

# --- 4) el conteo normal sigue igual: las balizas no inflan la cantidad ---
assert con.execute("SELECT COUNT(*) c FROM lecturas").fetchone()["c"] == 12
assert not con.execute("SELECT 1 FROM lecturas WHERE epc IN (?,?,?)",
                       tuple(bal.values())).fetchone()
ok("la sesión de conteo cuenta 12 etiquetas de repuesto: las balizas NO suman cantidad")

# --- 5) tampoco ensucian la lista de desconocidos del escritorio ---
assert not [x for x in cl.get("/api/desconocidos").get_json() if x["epc"] in bal.values()]
ok("las balizas no aparecen en «Etiquetas desconocidas» del escritorio")

# --- 6) segunda vuelta: se refuerza lo que ya se sabía ---
cl.post("/api/lecturas", json={"dispositivo": "C72-01", "epcs": recorrido()})
p = next(x for x in cl.get("/api/balizas/propuestas").get_json()["propuestas"]
         if x["sku"] == "BOBINA")
assert p["veces"] == 4 and p["posicion"] == "A1", p     # 2 etiquetas x 2 vueltas
ok("repetir el recorrido refuerza la posición en vez de duplicar el conteo")

# --- 7) un repuesto que se MOVIÓ de sitio: gana donde más se vio ---
# se lee 3 veces en B1 y solo 1 en A1 (eco del pasillo de al lado)
for _ in range(3):
    cl.post("/api/lecturas", json={"dispositivo": "C72-01",
                                   "epcs": [bal["B1"]] + epc["BOBINA"]})
p = next(x for x in cl.get("/api/balizas/propuestas").get_json()["propuestas"]
         if x["sku"] == "BOBINA")
assert p["posicion"] == "B1", p          # 6 lecturas en B1 contra 4 en A1
assert p["actual"] == "", "todavía no se ha aplicado nada"
ok("si un repuesto se mueve, gana el sitio donde más se le ve")

# --- 8) hasta que no se acepta, la base NO cambia ---
assert con.execute("SELECT COUNT(*) c FROM stock_bodegas").fetchone()["c"] == 0
ok("nada se guarda hasta pulsar «Aplicar marcadas» en el escritorio")
con.close()

print("\nTODAS LAS PRUEBAS PASARON")
