# -*- coding: utf-8 -*-
"""Las apps de Android traen la pantalla del inventario (la misma del PC)."""
import os
import zipfile

from _comun import ruta  # noqa: E402  (deja el programa a mano)

ok = lambda m: print("[OK] " + m)
RAIZ = os.path.dirname(os.path.dirname(ruta("app.py")))


def dex(nombre):
    z = zipfile.ZipFile(os.path.join(RAIZ, nombre))
    return b"".join(z.read(n) for n in z.namelist() if n.endswith(".dex"))


# --- las tres apps existen y pesan lo razonable ---
for nombre, minimo in (("InventarioRFID-C72.apk", 3), ("InventarioRFID-Alien.apk", 3),
                       ("InventarioRFID-Movil.apk", 1)):
    p = os.path.join(RAIZ, nombre)
    assert os.path.exists(p), "falta " + nombre
    mb = os.path.getsize(p) / 1024 / 1024
    assert mb > minimo, (nombre, mb)
ok("están las tres apps: las dos pistolas y la del celular")

# --- las dos pistolas abren la pantalla del PC ---
for nombre in ("InventarioRFID-C72.apk", "InventarioRFID-Alien.apk"):
    d = dex(nombre)
    assert b"/escritorio" in d, nombre + " no abre la pantalla del inventario"
    assert b"mostrarInventario" in d and b"prepararWeb" in d, nombre
ok("las dos pistolas traen dentro la pantalla del inventario")

# --- la del celular NO lleva SDK de pistola (por eso funciona en cualquiera) ---
d = dex("InventarioRFID-Movil.apk")
assert b"/escritorio" in d
for sdk in (b"RFIDWithUHFUART", b"com.rscja", b"com.alien.rfid"):
    assert sdk not in d, "la app del celular no debería llevar %s" % sdk.decode()
ok("la del celular no lleva SDK de pistola: sirve en cualquier Android")

# --- y sabe buscar el servidor sola ---
assert b"/api/quien" in d, "debe poder buscar el servidor en la red"
assert b"escritorio?modo=vendedor" in d or b"?modo=vendedor" in d
ok("busca el servidor sola y puede abrirse en modo vendedor")

# --- fuera de la bodega: una segunda dirección (https) de reserva ---
assert b"Direcci\xc3\xb3n para fuera de la bodega" in d, "falta la dirección de afuera"
fuente = open(os.path.join(RAIZ, "android-movil", "app", "src", "main", "java", "com",
                           "inventario", "movil", "MainActivity.kt"), encoding="utf-8").read()
abrir = fuente.split("private fun abrir()")[1].split("private fun noConecta")[0]
assert "quienEs(base(direccion))" in abrir and "usandoAfuera = !enBodega" in abrir, \
    "al abrir debe probar PRIMERO la bodega y solo si no contesta ir por internet"
assert "CookieManager.getInstance().flush()" in fuente, "la sesión de afuera debe guardarse"
ok("la del celular prueba primero la bodega y, si no contesta, entra por internet")

# --- pesa bastante menos que las de pistola ---
gs = {n: os.path.getsize(os.path.join(RAIZ, n)) for n in
      ("InventarioRFID-C72.apk", "InventarioRFID-Movil.apk")}
assert gs["InventarioRFID-Movil.apk"] < gs["InventarioRFID-C72.apk"]
ok("la del celular pesa menos: %.1f MB contra %.1f MB"
   % (gs["InventarioRFID-Movil.apk"] / 1048576, gs["InventarioRFID-C72.apk"] / 1048576))

# --- publicadas donde se instalan desde la pistola ---
for nombre in ("InventarioRFID-C72.apk", "InventarioRFID-Alien.apk",
               "InventarioRFID-Movil.apk"):
    assert os.path.exists(ruta("subidos", nombre)), \
        "%s no está en subidos: no se podrá instalar desde /apps" % nombre
ok("las tres están publicadas en el servidor, listas para instalar desde /apps")

print("\nTODAS LAS PRUEBAS PASARON")
