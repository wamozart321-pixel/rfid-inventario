# -*- coding: utf-8 -*-
"""Aviso de que las cantidades NO están verificadas todavía.

Las etiquetas RFID aún no han llegado, así que casi ningún repuesto se ha
contado con la pistola: lo que muestra el programa viene de lo que se importó.
Quien vaya a prometerle una cantidad a un cliente tiene que verlo avisado y
mirar Siigo primero.

Ojo con la columna «Sin Asignar» de Siigo: NO es stock y el importador hace
bien en ignorarla. Esa parte no se toca.
"""
import os
import sqlite3
import sys
import tempfile
from datetime import datetime

from _comun import ruta  # noqa: E402  (deja el programa a mano)
import app as A

TMP = tempfile.mkdtemp(prefix="rfid_aviso_")
A.DB = os.path.join(TMP, "t.db")
A.CFG = os.path.join(TMP, "c.json")
A.BASE = TMP
A.init_db()
ok = lambda m: print("[OK] " + m)
cl = A.app.test_client()
con = sqlite3.connect(A.DB)
con.row_factory = sqlite3.Row

for sku in ("CON-ETIQUETA", "SIN-ETIQUETA-1", "SIN-ETIQUETA-2"):
    cl.post("/api/productos/guardar", json={"sku": sku, "nombre": "PROD " + sku,
                                            "precio_minimo": "0", "precio": "0"})
ids = {r["sku"]: r["id"] for r in con.execute("SELECT id, sku FROM productos")}

# ===================================================== el recuento
d = cl.get("/api/dashboard").get_json()
assert d["productos"] == 3
assert d["etiquetados"] == 0, "sin etiquetas pegadas, ninguno está verificado"
ok("de entrada: 3 repuestos, 0 con etiqueta RFID")

con.execute("INSERT INTO tags(epc,producto_id,creado) VALUES(?,?,?)",
            ("E2801100AA", ids["CON-ETIQUETA"], datetime.now().isoformat()))
con.commit()
d = cl.get("/api/dashboard").get_json()
assert d["etiquetados"] == 1, d
ok("al pegar una etiqueta, ese repuesto pasa a contar como verificado")

# dos etiquetas en el MISMO repuesto siguen siendo UN repuesto verificado
con.execute("INSERT INTO tags(epc,producto_id,creado) VALUES(?,?,?)",
            ("E2801100BB", ids["CON-ETIQUETA"], datetime.now().isoformat()))
con.commit()
d = cl.get("/api/dashboard").get_json()
assert d["tags"] == 2 and d["etiquetados"] == 1, d
ok("dos etiquetas del mismo repuesto no lo cuentan dos veces")

# una etiqueta IGNORADA (sin producto) no verifica nada
con.execute("INSERT INTO tags(epc,producto_id,creado) VALUES(?,NULL,?)",
            ("E2801100CC", datetime.now().isoformat()))
con.commit()
assert cl.get("/api/dashboard").get_json()["etiquetados"] == 1
ok("una etiqueta ignorada no hace que ningún repuesto cuente como verificado")

# ===================================================== la pantalla
h = cl.get("/escritorio").get_data(as_text=True)
for marca in ("function sinVerificar", "function avisoCantidad",
              "function pintarAvisoInventario", 'id="aviso-inventario"'):
    assert marca in h, marca
ok("la pantalla trae el aviso y sus funciones")

# el texto tiene que decir QUÉ hacer, no solo que algo va mal
assert "Revisa Siigo" in h, "el aviso debe mandar a revisar Siigo"
assert "no tiene etiqueta RFID" in h
assert "Cantidad sin verificar" in h
assert "Inventario sin terminar" in h
ok("el aviso dice qué pasa y qué hacer: revisar Siigo antes de fiarse")

# aparece donde se consultan las cantidades: en la ficha y en Modificar
ficha = h.split("ℹ️ Información —")[1][:3000]
assert "${avisoCantidad(p)}" in ficha, "falta el aviso en la ficha de Información"
modificar = h.split("${bod.map(filaBodegaHtml)")[0][-400:]
assert "${avisoCantidad(p)}" in modificar, "falta el aviso junto a las bodegas"
ok("el aviso sale en Información y en Modificar, pegado a las cantidades")

# y el de arriba de la lista está dentro de la vista de productos
assert h.index('id="aviso-inventario"') < h.index('id="t-productos"')
ok("el aviso general va arriba de la lista de productos")

# ===================================================== cuándo se calla
# Solo cuando esté TODO etiquetado: si no, seguiría engañando.
fn = h.split("function pintarAvisoInventario")[1][:900]
# el porcentaje se redondea hacia ABAJO: con 26 etiquetados de 8.374 debe
# decir 99 %, no «100 %» (pasó: parecía que no había ninguno)
assert "Math.floor(100 * faltan" in fn, "el porcentaje debe redondear hacia abajo"
ok("el porcentaje redondea hacia abajo: nunca dice 100 % si hay alguno etiquetado")
assert "j.productos - (j.etiquetados || 0)" in fn
assert "faltan <= 0" in fn and "display = 'none'" in fn
ok("el aviso solo desaparece cuando ya no falta ningún repuesto por etiquetar")

# el aviso por repuesto se calla en cuanto ESE tiene etiqueta
fn2 = h.split("function sinVerificar")[1][:120]
assert "n_tags > 0" in fn2
ok("en la ficha, el aviso se quita en cuanto ese repuesto tiene su etiqueta")

# ===================================================== «Sin Asignar»
# No es stock: el importador debe seguir sin verla como bodega.
fuente = open(ruta("app.py"), encoding="utf-8").read()
det = fuente.split("bodegas_sug = ")[1][:220]
assert "almacen|bodega" in det, det
assert "sin asignar" not in det.lower() and "asignar" not in det.lower(), \
    "«Sin Asignar» NO es una bodega: no debe proponerse como tal"
ok("«Sin Asignar» sigue sin contar como bodega: no es stock")
con.close()

print("\nTODAS LAS PRUEBAS PASARON")
