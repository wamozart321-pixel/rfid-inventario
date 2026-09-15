# -*- coding: utf-8 -*-
"""Lo que comparten todas las pruebas.

Dos cosas importantes:

1. Encuentra el programa SOLA, a partir de dónde está este archivo. Así las
   pruebas funcionan en cualquier PC y en cualquier carpeta, sin rutas
   escritas a mano.

2. Las pruebas NUNCA tocan el inventario de verdad. Cada una trabaja sobre
   una base de datos nueva en una carpeta temporal:

       import app as A
       A.DB  = os.path.join(TMP, "t.db")
       A.CFG = os.path.join(TMP, "c.json")
       A.BASE = TMP
       A.init_db()

   Si alguna vez ves una prueba que no hace eso, párala: estaría escribiendo
   en el inventario real. Ya pasó una vez y dejó productos de prueba dentro.
"""
import os
import sys

PRUEBAS = os.path.dirname(os.path.abspath(__file__))
SERVIDOR = os.path.dirname(PRUEBAS)
RAIZ = os.path.dirname(SERVIDOR)

if SERVIDOR not in sys.path:
    sys.path.insert(0, SERVIDOR)


def ruta(*partes):
    """Un archivo del programa: ruta("app.py"), ruta("templates", "x.html")."""
    return os.path.join(SERVIDOR, *partes)


def ok(mensaje):
    print("[OK] " + mensaje)
