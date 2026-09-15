# -*- coding: utf-8 -*-
"""Certificados: que la comprobación funcione en todos los PCs, sin apagarla."""
import os
import ssl
import sys
import tempfile

from _comun import ruta  # noqa: E402  (deja el programa a mano)
import app as A

TMP = tempfile.mkdtemp(prefix="rfid_ssl_")
A.DB = os.path.join(TMP, "t.db")
A.CFG = os.path.join(TMP, "c.json")
A.BASE = TMP
A.init_db()
ok = lambda m: print("[OK] " + m)
cl = A.app.test_client()

# --- LO MÁS IMPORTANTE: nunca se apaga la comprobación ---
ctx = A.contexto_ssl()
assert ctx.verify_mode == ssl.CERT_REQUIRED, ctx.verify_mode
assert ctx.check_hostname is True
ok("el certificado SIEMPRE se comprueba (por aquí entra un programa que se ejecuta)")

fuente = open(ruta("app.py"),
              encoding="utf-8").read()
for prohibido in ("CERT_NONE", "check_hostname = False", "check_hostname=False",
                  "_create_unverified_context"):
    assert prohibido not in fuente, prohibido
ok("en el código no hay ninguna forma de saltarse la comprobación")

# --- se confía en la tienda de Windows Y en la lista propia ---
n = len(ctx.get_ca_certs())
assert n > 100, "pocas autoridades cargadas: %d" % n
import certifi
propias = ssl.create_default_context()
propias.load_verify_locations(certifi.where())
hay_certifi = {c["serialNumber"] for c in propias.get_ca_certs()}
tiene = {c["serialNumber"] for c in ctx.get_ca_certs()}
assert hay_certifi & tiene, "no cargó la lista que trae el programa"
ok("confía en las %d autoridades del sistema MÁS la lista propia (certifi)" % n)

# el contexto se reutiliza (no se rehace en cada consulta)
assert A.contexto_ssl() is ctx
ok("el contexto se prepara una sola vez y se reutiliza")

# --- se usa de verdad al consultar y al descargar ---
consulta = fuente.split("def buscar_actualizacion")[1].split("def ")[0]
assert "context=contexto_ssl()" in consulta
descarga = fuente.split("def _descargar_exe")[1].split("def ")[0]
assert "context=contexto_ssl()" in descarga
ok("se usa tanto al preguntar por la versión como al descargarla")

# --- los errores se explican en cristiano ---
casos = [
    ("[SSL: CERTIFICATE_VERIFY_FAILED] unable to get local issuer certificate",
     ["certificado de GitHub", "a mano"]),
    ("<urlopen error [Errno 11001] getaddrinfo failed>", ["salida a internet"]),
    ("The read operation timed out", ["no contestó a tiempo"]),
]
for tecnico, esperados in casos:
    claro = A.motivo_red(Exception(tecnico))
    for e in esperados:
        assert e in claro, (tecnico[:40], e, claro)
    assert "_ssl.c" not in claro and "Errno" not in claro
ok("los errores se traducen: nada de «_ssl.c:1032» en pantalla")

# uno desconocido se deja tal cual en vez de tragárselo
assert A.motivo_red(Exception("algo muy raro")) == "algo muy raro"
ok("un error que no se reconoce se muestra tal cual, no se oculta")

# --- llega a la pantalla ---
import urllib.request
urllib.request.urlopen = lambda *a, **k: (_ for _ in ()).throw(
    Exception("[SSL: CERTIFICATE_VERIFY_FAILED] unable to get local issuer certificate"))
r = cl.post("/api/actualizacion/buscar", json={})
assert r.status_code == 502
msg = r.get_json()["error"]
assert "certificado de GitHub" in msg and "_ssl.c" not in msg, msg
assert "certificado de GitHub" in A.ESTADO_ACTUALIZACION["error"]
ok("si falla, en pantalla sale el motivo entendible y qué hacer")

print("\nTODAS LAS PRUEBAS PASARON")
