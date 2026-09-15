# -*- coding: utf-8 -*-
"""Los ASESORES (vendedores) también pueden cambiar la rotación a mano."""
import os
import re
import sqlite3
import sys
import tempfile
from datetime import datetime

from _comun import ruta  # noqa: E402  (deja el programa a mano)
import app as A

TMP = tempfile.mkdtemp(prefix="rfid_rotase_")
A.DB = os.path.join(TMP, "t.db")
A.CFG = os.path.join(TMP, "c.json")
A.BASE = TMP
A.init_db()
ok = lambda m: print("[OK] " + m)
cl = A.app.test_client()
con = sqlite3.connect(A.DB)
con.row_factory = sqlite3.Row

cl.post("/api/productos/guardar", json={"sku": "BOBINA-9", "nombre": "BOBINA DE PRUEBA",
                                        "precio_minimo": "0", "precio": "0"})
pid = con.execute("SELECT id FROM productos WHERE sku='BOBINA-9'").fetchone()["id"]

vend = cl.get("/escritorio?modo=vendedor").get_data(as_text=True)
cli = cl.get("/escritorio").get_data(as_text=True)

# --- los botones existen y están en UN SOLO SITIO ---
assert "function botonesRotacion" in vend
assert vend.count("function botonesRotacion") == 1
assert vend.count("onclick=\"cambiarRotacion(${p.id}, '${n}')\"") == 1, \
    "los botones deben salir de un solo ayudante, no copiados dos veces"
ok("los botones de rotación viven en un solo ayudante compartido")

# --- los usan los DOS semáforos ---
grande = vend.split("function semaforoGrande")[1].split("function semaforoChico")[0]
chico = vend.split("function semaforoChico")[1].split("function cambiarRotacion")[0]
assert "botonesRotacion(p)" in grande, "el semáforo grande (Información) debe traerlos"
assert "botonesRotacion(p)" in chico, "y el chico (Modificar) también"
ok("los trae tanto Información (grande) como Modificar producto (chico)")

# --- Información es la pantalla del asesor y ahí está el semáforo ---
assert 'id="i-rot"' in vend and "${semaforoGrande(p)}" in vend
assert "if(MODO === 'vendedor') infoProducto();" in vend
ok("el asesor entra por Información, que es justo donde está el semáforo")

# --- al cambiarla se repintan las dos fichas, no solo una ---
cambiar = vend.split("function cambiarRotacion")[1][:1400]
assert "getElementById('f-rot')" in cambiar and "getElementById('i-rot')" in cambiar
assert "semaforoGrande(p)" in cambiar and "semaforoChico(p)" in cambiar
ok("al cambiarla se actualiza a la vista sin cerrar la ficha, en las dos pantallas")

# --- sigue avisando de lo que implica ponerla a mano ---
assert "dejará de actualizarse solo" in vend
assert "↺ Automática" in vend
ok("el aviso de «deja de actualizarse solo» sigue estando para el asesor")

# --- y el servidor le deja guardarla de verdad ---
r = cl.post("/api/productos/%d/rotacion" % pid, json={"nivel": "alta"})
assert r.get_json()["ok"]
assert con.execute("SELECT rotacion_manual FROM productos WHERE id=?",
                   (pid,)).fetchone()["rotacion_manual"] == "alta"
p = next(x for x in cl.get("/api/productos").get_json() if x["sku"] == "BOBINA-9")
assert p["rotacion"] == "alta"
ok("el asesor la cambia y queda guardada de verdad")

r = cl.post("/api/productos/%d/rotacion" % pid, json={"nivel": ""})
assert r.get_json()["ok"]
assert con.execute("SELECT rotacion_manual FROM productos WHERE id=?",
                   (pid,)).fetchone()["rotacion_manual"] == ""
ok("y también puede devolverla a automática")

# --- lo demás sigue vedado para el asesor ---
assert "onclick=\"nuevoProducto()\"" not in vend and "onclick=\"nuevoProducto()\"" in cli
assert "onclick=\"modificarProducto()\"" not in vend
assert 'data-tab="inventario"' not in vend
assert "onclick=\"eliminarProducto()\"" not in vend
assert "onclick=\"importarExcel()\"" not in vend
ok("el asesor sigue SIN poder crear, modificar, borrar ni importar")

# los botones de su ficha son solo esos dos (la rama de Imprimir es de los otros modos)
rama = vend.split("MODO === 'vendedor'\n      ? [")[1].split("]")[0]
assert "Guardar referencias" in rama and "Cerrar" in rama
assert "Imprimir" not in rama and "Modificar" not in rama
ok("en su ficha solo tiene «Guardar referencias» y «Cerrar»: nada de imprimir")

# los botones de la ficha del asesor siguen siendo los suyos
assert "💾 Guardar referencias" in vend
ok("su botón sigue siendo «Guardar referencias»")
con.close()

print("\nTODAS LAS PRUEBAS PASARON")
