# -*- coding: utf-8 -*-
"""Importar un Excel: qué columna es cada cosa y qué NO puede confundirse.

Aquí hubo dos sustos de verdad, y los dos habrían tocado los 8.000 productos
de golpe:

  · «Stock mínimo» se estaba tomando como PRECIO mínimo -> habría puesto a
    cero el precio mínimo de todo el catálogo.
  · Cargar un archivo se anotaba como VENTA -> habría metido cientos de
    ventas falsas y desbaratado el semáforo de rotación.

Por eso estas pruebas son tan tozudas con los nombres de las columnas.
"""
import os
import sqlite3
import sys
import tempfile
from datetime import datetime

from _comun import ruta  # noqa: E402  (deja el programa a mano)
import app as A

TMP = tempfile.mkdtemp(prefix="rfid_imp_")
A.DB = os.path.join(TMP, "t.db")
A.CFG = os.path.join(TMP, "c.json")
A.BASE = TMP
A.init_db()
ok = lambda m: print("[OK] " + m)
con = sqlite3.connect(A.DB)
con.row_factory = sqlite3.Row

mapa = lambda encs: A._mapear_columnas(encs)

# ===================================================== el susto nº 1
# «Stock mínimo» es una CANTIDAD. Si se toma como precio mínimo, el catálogo
# entero se queda con precios de 3 o 5 pesos.
m = mapa(["Referencia", "Descripción", "Stock mínimo", "Precio venta"])
assert m.get("precio_minimo") is None, "¡«Stock mínimo» se coló como PRECIO! " + str(m)
# tampoco vale tomarla como la cantidad que hay: el «stock mínimo» es el
# nivel al que hay que reponer, no lo que hay en el estante. Se ignora.
assert m.get("cantidad") is None, "¡«Stock mínimo» se tomó como las existencias! " + str(m)
assert m == {"sku": 0, "nombre": 1, "precio": 3}, m
ok("«Stock mínimo» se ignora: ni es un precio ni son las existencias")

# una columna «Stock» a secas SÍ son las existencias
assert mapa(["Referencia", "Stock"]).get("cantidad") == 1
assert mapa(["Referencia", "Existencias"]).get("cantidad") == 1
ok("«Stock» o «Existencias» a secas sí son las unidades que hay")

for enc in ("Existencia mínima", "Cantidad mínima", "Saldo mínimo", "Unidades mínimas"):
    m = mapa(["Referencia", enc, "Precio"])
    assert m.get("precio_minimo") is None, "%r se coló como precio: %s" % (enc, m)
ok("ninguna columna de unidades con la palabra «mínimo» se toma por un precio")

# y el precio mínimo de verdad SÍ se reconoce, se llame como se llame
for enc in ("Precio mínimo", "P. min", "Venta 2", "Precio 2", "Precio mayorista",
            "Valor mayor"):
    m = mapa(["Referencia", enc, "Precio venta"])
    assert m.get("precio_minimo") == 1, "no reconoció %r: %s" % (enc, m)
ok("el precio mínimo se reconoce con sus seis nombres habituales")

# ===================================================== precio normal
m = mapa(["Referencia", "Precio mínimo", "Precio de venta"])
assert m.get("precio") == 2 and m.get("precio_minimo") == 1, m
for enc in ("Precio", "Venta", "PVP", "Valor unitario"):
    assert mapa(["Ref", enc]).get("precio") == 1, enc
ok("el precio normal se reconoce y no se pisa con el mínimo")

# el COSTO no es el precio de venta: si se confunde, se vende a precio de costo
m = mapa(["Referencia", "Costo", "Precio venta"])
assert m.get("precio") == 2, "¡tomó el COSTO como precio de venta! " + str(m)
ok("el «costo» no se confunde con el precio de venta")

# ===================================================== las demás columnas
m = mapa(["Código de barras", "Referencia", "Descripción", "Ubicación",
          "Referencias aplicables", "Ruta imagen", "Estante", "Proveedor"])
assert m["codigo_barras"] == 0, m
assert m["sku"] == 1, "«Referencia» a secas es la referencia del repuesto"
assert m["nombre"] == 2
assert m["ubicacion"] == 3
assert m["referencias"] == 4, "«Referencias aplicables» NO es la referencia"
assert m["foto"] == 5
assert m["posicion"] == 6
assert m["proveedor"] == 7
ok("cada columna va a su sitio, incluso las que se parecen entre sí")

# «Referencia» y «Referencias aplicables» son cosas MUY distintas
m = mapa(["Referencias aplicables", "Referencia"])
assert m["referencias"] == 0 and m["sku"] == 1, m
ok("«Referencias aplicables» y «Referencia» no se cruzan, estén en el orden que estén")

# el código de barras no se toma por la referencia
m = mapa(["EAN", "Código"])
assert m["codigo_barras"] == 0 and m["sku"] == 1, m
ok("una columna «EAN» es el código de barras, no la referencia")

# las columnas de unidades por bodega no son la «ubicación»
m = mapa(["Referencia", "ALMACEN", "BODEGA 1", "BODEGA 8"])
assert m.get("ubicacion") is None, "confundió una columna de bodega con la ubicación: " + str(m)
ok("las columnas ALMACEN / BODEGA n son cantidades, no la ubicación")

# OJO, decisión deliberada: una columna llamada solo «Bodega» TAMBIÉN se
# ignora, por la misma regla. En los archivos de Siigo esas columnas son
# cantidades por bodega, así que es lo prudente; pero si algún día llega un
# Excel donde «Bodega» sea de verdad el sitio del repuesto, se perdería sin
# avisar. Queda aquí escrito para que el día que se cambie, se cambie a
# sabiendas.
assert mapa(["Referencia", "Bodega"]).get("ubicacion") is None
assert mapa(["Referencia", "Ubicación"]).get("ubicacion") == 1
ok("una columna «Bodega» a secas se ignora a propósito; «Ubicación» sí se toma")

# sin tildes y en mayúsculas da igual
assert mapa(["DESCRIPCION"]).get("nombre") == 0
assert mapa(["Descripción"]).get("nombre") == 0
assert mapa(["UBICACIÓN"]).get("ubicacion") == 0
ok("da igual cómo estén escritas: tildes y mayúsculas no importan")

# una columna solo puede usarse para UNA cosa
m = mapa(["Precio", "Precio"])
assert list(m.values()).count(0) <= 1, m
ok("una misma columna no se reparte entre dos campos")

# ===================================================== la fila de títulos
# El Excel del usuario trae los títulos en la fila 5, no en la primera.
filas = [
    ["REPUESTOSVOLKSWAGENCOM SAS", "", "", ""],
    ["Listado de productos", "", "", ""],
    ["", "", "", ""],
    ["Generado el 28/07/2026", "", "", ""],
    ["Referencia", "Descripción", "Precio mínimo", "Precio venta"],
    ["LM21604", "BOBINA", "26000", "27000"],
]
assert A._detectar_encabezado(filas) == 4, A._detectar_encabezado(filas)
ok("encuentra la fila de títulos aunque esté en la quinta línea")

# si los títulos están arriba del todo, también
assert A._detectar_encabezado([["Referencia", "Precio"], ["X", "1"]]) == 0
ok("y si están en la primera línea, igual")

# ===================================================== el susto nº 2
# Cargar un archivo NO es vender. Si se anota como venta, el semáforo de
# rotación se vuelve loco y aparecen ventas que nunca ocurrieron.
fuente = open(ruta("app.py"), encoding="utf-8").read()
importar = fuente[fuente.index("def _importar_filas") if "def _importar_filas" in fuente
                  else fuente.index("origen=\"importacion\"") - 3000:]
assert "es_venta=False" in importar, "la importación debe anotarse con es_venta=False"
assert "es_venta=True" not in importar.split("origen=\"importacion\"")[0][-600:], \
    "hay una importación anotándose como venta"
ok("la importación se anota con es_venta=False: cargar un archivo no es vender")

# y el semáforo no cuenta lo que no es venta
cl = A.app.test_client()
cl.post("/api/productos/guardar", json={"sku": "PRUEBA-ROT", "nombre": "X",
                                        "precio_minimo": "0", "precio": "0"})
pid = con.execute("SELECT id FROM productos WHERE sku='PRUEBA-ROT'").fetchone()["id"]
con.execute("INSERT INTO salidas(producto_id,cantidad,origen,es_venta,ts) VALUES(?,?,?,?,?)",
            (pid, 500, "importacion", 0, datetime.now().isoformat()))
con.commit()
p = next(x for x in cl.get("/api/productos").get_json() if x["sku"] == "PRUEBA-ROT")
assert p["vendidos"] == 0, "¡500 unidades de una importación cuentan como vendidas!"
assert p["rotacion"] == "baja"
ok("500 unidades metidas por importación NO cuentan como vendidas")
con.close()

print("\nTODAS LAS PRUEBAS PASARON")
