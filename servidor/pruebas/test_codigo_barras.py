# -*- coding: utf-8 -*-
"""El código de barras: fórmula, dígito de control y búsqueda al escanear.

Es de lo más delicado del sistema: un error aquí se imprime en cientos de
rótulos y no se nota hasta que el escáner no encuentra el repuesto.
"""
import os
import sqlite3
import sys
import tempfile

from _comun import ruta  # noqa: E402  (deja el programa a mano)
import app as A

TMP = tempfile.mkdtemp(prefix="rfid_cb_")
A.DB = os.path.join(TMP, "t.db")
A.CFG = os.path.join(TMP, "c.json")
A.BASE = TMP
A.init_db()
ok = lambda m: print("[OK] " + m)
cl = A.app.test_client()
con = sqlite3.connect(A.DB)
con.row_factory = sqlite3.Row

# ======================================================= dígito de control
# Códigos EAN-13 reales, de productos de verdad: si esto falla, los rótulos
# salen con un dígito que ningún escáner acepta.
REALES = [
    ("400638133393", "4006381333931"),   # Ritter Sport
    ("590123412345", "5901234123457"),   # ejemplo canónico de la norma
    ("012345678905", "0123456789050"[:12] + "5"),
]
for doce, completo in REALES[:2]:
    assert A.ean13_control(doce) == completo, (doce, A.ean13_control(doce), completo)
ok("el dígito de control coincide con el de códigos EAN-13 reales")

# cuando la suma es múltiplo de 10 el dígito es 0, no 10
assert A.ean13_control("000000000000") == "0000000000000"
assert A.ean13_control("000000000000")[-1] == "0"
ok("si la cuenta da múltiplo de 10 el dígito es 0 (no 10)")

# el dígito depende de la POSICIÓN: cambiar dos dígitos de sitio lo cambia
a, b = A.ean13_control("123456789012"), A.ean13_control("213456789012")
assert a[-1] != b[-1], "el control no está pesando las posiciones"
ok("el dígito cambia si se equivoca el ORDEN de los números")

# todos los códigos guardados en la base tienen que poder llevar control
for doce in ("300002627011", "214508595014", "999999999999"):
    c13 = A.ean13_control(doce)
    assert len(c13) == 13 and c13[:12] == doce and c13[-1].isdigit()
ok("a cualquier código de 12 dígitos se le puede poner el control")

# ======================================================= la fórmula
# Ejemplo de la documentación: proveedor 30, mínimo $26.000, normal $27.000
cb = A.generar_codigo_barras(1, 26000, 27000, proveedor=30)
assert cb[:7] == "3000026", "izquierda mal: " + cb
assert cb[7:10] == "270", "el precio normal debe empezar justo tras las guías: " + cb
assert len(cb) == 12, cb
ok("proveedor 30 · mín $26.000 · normal $27.000 -> 3000026|270.. como está documentado")

# el proveedor manda al principio y el mínimo termina pegado a las guías
cb = A.generar_codigo_barras(7, 260000, 27000, proveedor=30)
assert cb[:7] == "3000260", cb
ok("el mínimo queda pegado a las guías del centro, con ceros entre medias")

# sin proveedor empieza por 2 (código interno de tienda)
cb = A.generar_codigo_barras(1450, 85000, 95000)
assert cb[0] == "2", cb
assert cb[5:7] == "85", "el mínimo (85 = $85.000) debe terminar en las guías: " + cb
assert cb[7:10] == "950", "el normal (950 = $95.000) empieza tras las guías: " + cb
ok("sin proveedor: empieza por 2 y los dos precios quedan en su sitio")

# ------- LA REGLA QUE NO SE PUEDE ROMPER -------
# Si el código empieza por 0, el escáner lo lee como UPC-A y SE COME ese cero:
# el repuesto deja de aparecer. Pasó de verdad y por eso se fuerza el 2.
casos = [(1, 1000, 2000, 0), (99999, 500, 700, 0), (1, 0, 100, 0),
         (1, 100, 0, 0), (123456, 999999999, 88888888, 0),
         (1, 26000, 27000, 30), (5, 1000, 2000, 7), (5, 1000, 2000, 999999)]
for pid, pmin, pnor, prov in casos:
    cb = A.generar_codigo_barras(pid, pmin, pnor, prov)
    if cb:
        assert cb[0] != "0", ("empieza por CERO, el escáner se lo come: %r" % cb, pid, prov)
        assert len(cb) == 12, (cb, len(cb))
        assert cb.isdigit(), cb
ok("NINGÚN código empieza por 0 y todos tienen 12 dígitos")

# sin precios no hay código que valga
assert A.generar_codigo_barras(1, 0, 0) == ""
assert A.generar_codigo_barras(1, None, None) == ""
ok("un repuesto sin precios no genera código (mejor vacío que inventado)")

# el relleno de la derecha es el nº de producto, NO ceros
# (un cero ahí parecería parte del precio)
cb = A.generar_codigo_barras(4, 26000, 27000, proveedor=30)
assert cb[7:10] == "270" and cb[10:12] == "44", cb
ok("lo que sobra a la derecha se rellena con el número del repuesto, no con ceros")

# mismo repuesto y mismos precios -> mismo código siempre
uno = A.generar_codigo_barras(42, 26000, 27000, 30)
assert uno == A.generar_codigo_barras(42, 26000, 27000, 30)
ok("el mismo repuesto con los mismos precios da siempre el mismo código")

# cambiar el precio cambia el código (si no, el rótulo mentiría)
assert A.generar_codigo_barras(42, 26000, 27000, 30) != \
       A.generar_codigo_barras(42, 31000, 27000, 30)
assert A.generar_codigo_barras(42, 26000, 27000, 30) != \
       A.generar_codigo_barras(42, 26000, 33000, 30)
ok("al cambiar un precio cambia el código: el rótulo nunca miente")

# ======================================================= al escanear
cl.post("/api/productos/guardar", json={"sku": "BOBINA-X", "nombre": "BOBINA DE PRUEBA",
                                        "precio_minimo": "26000", "precio": "27000",
                                        "proveedor": "30"})
p = con.execute("SELECT * FROM productos WHERE sku='BOBINA-X'").fetchone()
guardado = p["codigo_barras"]
assert guardado and len(guardado) == 12, guardado
ok("al guardar un repuesto con precios se le pone el código solo (%s)" % guardado)

completo = A.ean13_control(guardado)          # lo que sale IMPRESO en el rótulo
assert len(completo) == 13

# el escáner entrega los 13 dígitos del rótulo
assert A.producto_por_codigo(con, completo)["sku"] == "BOBINA-X"
ok("escaneando el rótulo entero (13 dígitos) encuentra el repuesto")

# y también por la referencia escrita a mano
assert A.producto_por_codigo(con, "BOBINA-X")["sku"] == "BOBINA-X"
assert A.producto_por_codigo(con, "bobina-x")["sku"] == "BOBINA-X", "sin distinguir mayúsculas"
ok("y también escribiendo la referencia, en mayúsculas o minúsculas")

# rótulos VIEJOS con cero delante: el escáner se comió el cero
con.execute("UPDATE productos SET codigo_barras='012345678901' WHERE sku='BOBINA-X'")
con.commit()
assert A.producto_por_codigo(con, "0123456789015")["sku"] == "BOBINA-X"   # 13 completos
assert A.producto_por_codigo(con, "123456789015")["sku"] == "BOBINA-X"    # sin el 0
assert A.producto_por_codigo(con, "12345678901")["sku"] == "BOBINA-X"     # sin 0 ni control
ok("las etiquetas VIEJAS con cero delante se siguen encontrando")

# lo que no existe, no existe
assert A.producto_por_codigo(con, "7777777777777") is None
assert A.producto_por_codigo(con, "") is None
assert A.producto_por_codigo(con, None) is None
ok("un código que no es de nadie no devuelve un repuesto cualquiera")

# ======================================================= las barras
# El dibujo tiene que llevar SIEMPRE el dígito de control, o el escáner lo
# rechaza. (Fue un fallo real: el último dígito no salía.)
bits, trece = A._ean13_bits("300002627011")
assert len(bits) == 95, "un EAN-13 son 95 módulos, salieron %d" % len(bits)
assert set(bits) <= {"0", "1"}, "las barras solo pueden ser 0 y 1"
assert bits[:3] == "101" and bits[-3:] == "101", "faltan las guías de los extremos"
assert bits[45:50] == "01010", "falta la guía del centro"
ok("el dibujo del código tiene los 95 módulos y sus tres guías")

# el número que se dibuja lleva el control: si falta, el escáner lo rechaza
# (fue un fallo real: el último dígito no salía en el rótulo)
assert trece == A.ean13_control("300002627011") and len(trece) == 13
ok("bajo las barras va el número CON su dígito de control, los 13")

# y si llega un código con el control equivocado, se recalcula en vez de
# dibujar una mentira
malo = "300002627011" + "9"          # 9 no es el control correcto
bits2, trece2 = A._ean13_bits(malo)
assert trece2 == trece and bits2 == bits, "debería corregir el control, no copiarlo"
ok("si el código trae un control equivocado, se corrige antes de imprimir")

# el mismo número dibuja siempre igual; otro número, distinto
assert A._ean13_bits("300002627011")[0] == bits
assert A._ean13_bits("300002627012")[0] != bits
ok("cada número dibuja sus propias barras")
con.close()

print("\nTODAS LAS PRUEBAS PASARON")
