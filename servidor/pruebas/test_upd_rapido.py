# -*- coding: utf-8 -*-
"""Al ABRIR la pantalla se mira si hay versión nueva (no cada 6 horas)."""
import json
import os
import sys
import tempfile
import time
from datetime import datetime, timedelta

from _comun import ruta  # noqa: E402  (deja el programa a mano)
import app as A

TMP = tempfile.mkdtemp(prefix="rfid_updrap_")
A.DB = os.path.join(TMP, "t.db")
A.CFG = os.path.join(TMP, "c.json")
A.BASE = TMP
A.init_db()
ok = lambda m: print("[OK] " + m)
cl = A.app.test_client()

RESPUESTA = {"tag_name": "v9.9", "body": "nueva",
             "assets": [{"name": "ServidorInventarioRFID.exe", "size": 33_000_000,
                         "browser_download_url": "https://github.com/a/b/x.exe"}]}
consultas = []


class R:
    def __init__(self, d): self._d = json.dumps(d).encode()
    def read(self): return self._d
    def __enter__(self): return self
    def __exit__(self, *a): return False


import urllib.request


def falso(req, timeout=0, **k):
    consultas.append(getattr(req, "full_url", req))
    return R(RESPUESTA)


urllib.request.urlopen = falso


def esperar(cond, seg=5):
    t0 = time.time()
    while time.time() - t0 < seg:
        if cond():
            return True
        time.sleep(0.05)
    return False


assert A.MINUTOS_ENTRE_REVISIONES == 60 and A.PRIMERA_REVISION_SEG == 15
assert not hasattr(A, "HORAS_ENTRE_REVISIONES")
ok("ya no espera 6 horas: revisa al arrancar y luego cada hora")

# --- abrir la pantalla dispara la revisión ---
A.ESTADO_ACTUALIZACION.update(revisado=None, hay=False, nueva="", error="")
consultas.clear()
cl.get("/api/dashboard")
assert esperar(lambda: consultas), "abrir la pantalla debe disparar la consulta"
assert esperar(lambda: A.ESTADO_ACTUALIZACION.get("hay"))
assert A.ESTADO_ACTUALIZACION["nueva"] == "v9.9"
ok("al abrir la pantalla se consulta sola y queda anotado que hay versión nueva")

# --- y el aviso viaja en la siguiente vuelta del latido ---
d = cl.get("/api/dashboard").get_json()
assert d["actualizacion"]["hay"] and d["actualizacion"]["nueva"] == "v9.9"
ok("el aviso llega a la pantalla en la vuelta siguiente (10 s después)")

# --- pero no se machaca a GitHub en cada refresco ---
consultas.clear()
for _ in range(12):
    cl.get("/api/dashboard")
    cl.get("/api/actualizacion")
time.sleep(0.4)
assert consultas == [], "recién revisado: no debe volver a consultar"
ok("aunque se refresque muchas veces, no consulta más de una vez cada 10 minutos")

# --- pasados los 10 minutos, vuelve a mirar ---
A.ESTADO_ACTUALIZACION["revisado"] = (datetime.now() - timedelta(minutes=11)).isoformat(timespec="seconds")
consultas.clear()
cl.get("/api/actualizacion")
assert esperar(lambda: consultas), "pasado el rato sí debe volver a consultar"
ok("pasados 10 minutos vuelve a mirar sola")

# --- si se apaga el aviso, no molesta a GitHub ---
c = A.cfg(); c["actualizar_revisar"] = False; A.guardar_cfg(c)
A.ESTADO_ACTUALIZACION["revisado"] = (datetime.now() - timedelta(hours=2)).isoformat(timespec="seconds")
consultas.clear()
cl.get("/api/dashboard")
time.sleep(0.4)
assert consultas == [], "con el aviso desactivado no debe consultar"
c["actualizar_revisar"] = True; A.guardar_cfg(c)
ok("si se desactiva el aviso, deja de consultar del todo")

# --- una consulta que falla no bloquea las siguientes ---
def revienta(req, timeout=0, **k):
    raise OSError("sin internet")


urllib.request.urlopen = revienta
A.ESTADO_ACTUALIZACION["revisado"] = None
cl.get("/api/dashboard")
assert esperar(lambda: A.ESTADO_ACTUALIZACION.get("error"))
assert A._revisando is False, "el candado se suelta aunque falle"
ok("si falla la consulta se anota el motivo y no deja el sistema bloqueado")

# --- la versión subió ---
assert A.VERSION == "3.4"
assert cl.get("/api/actualizacion").get_json()["version"] == "3.4"
ok("la versión del programa es la 3.4")

print("\nTODAS LAS PRUEBAS PASARON")
