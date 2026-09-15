# -*- coding: utf-8 -*-
"""El indicador «¿la pistola está viendo las balizas?»."""
import os
import sqlite3
import sys
import tempfile
from datetime import datetime, timedelta

from _comun import ruta  # noqa: E402  (deja el programa a mano)
import app as A

TMP = tempfile.mkdtemp(prefix="rfid_balpis_")
A.DB = os.path.join(TMP, "t.db")
A.CFG = os.path.join(TMP, "c.json")
A.BASE = TMP
A.init_db()
ok = lambda m: print("[OK] " + m)
cl = A.app.test_client()
con = sqlite3.connect(A.DB)
con.row_factory = sqlite3.Row

# de entrada no hay ninguna pistola situada
assert cl.get("/api/balizas/pistolas").get_json() == []
ok("si ninguna pistola ha leído una baliza, la lista sale vacía (y la pantalla avisa)")

cl.post("/api/balizas", json={"epc": "BAL-A1", "bodega": "BODEGA 8", "posicion": "A1"})
cl.post("/api/lecturas", json={"dispositivo": "C72-01", "epcs": ["BAL-A1"]})
p = cl.get("/api/balizas/pistolas").get_json()
assert len(p) == 1 and p[0]["dispositivo"] == "C72-01"
assert p[0]["bodega"] == "BODEGA 8" and p[0]["posicion"] == "A1"
assert p[0]["minutos"] == 0 and p[0]["vigente"] is True
ok("tras leer la baliza, la pantalla dice dónde está esa pistola")

# caducidad
con.execute("UPDATE dispositivo_pos SET ts=?",
            ((datetime.now() - timedelta(minutes=A.BALIZA_MINUTOS + 3)).isoformat(),))
con.commit()
p = cl.get("/api/balizas/pistolas").get_json()
assert p[0]["vigente"] is False and p[0]["minutos"] >= A.BALIZA_MINUTOS
ok("cuando pasa el tiempo se marca como caducada en vez de mentir")

# varias pistolas
cl.post("/api/balizas", json={"epc": "BAL-C4", "bodega": "ALMACEN", "posicion": "C4"})
cl.post("/api/lecturas", json={"dispositivo": "ALIEN-01", "epcs": ["BAL-C4"]})
p = cl.get("/api/balizas/pistolas").get_json()
assert len(p) == 2 and p[0]["dispositivo"] == "ALIEN-01"      # la más reciente primero
ok("con dos pistolas salen las dos, la más reciente primero")

h = cl.get("/escritorio").get_data(as_text=True)
for marca in ('id="bal-pistolas"', "function cargarPistolas",
              "Ninguna pistola ha leído una baliza todavía"):
    assert marca in h, marca
ok("la pantalla trae el aviso de «ninguna pistola ha leído una baliza»")
con.close()

print("\nTODAS LAS PRUEBAS PASARON")
