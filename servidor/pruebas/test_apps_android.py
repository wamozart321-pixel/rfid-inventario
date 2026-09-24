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

# --- el ⚙ de los ajustes de la app va en la pantalla, junto a la 🌙 ---
for carpeta, paq in (("android-c72", "rfid"), ("android-alien", "alien"), ("android-movil", "movil")):
    kt = open(os.path.join(RAIZ, carpeta, "app", "src", "main", "java", "com", "inventario", paq,
                           "MainActivity.kt"), encoding="utf-8").read()
    assert 'addJavascriptInterface(Puente(), "AppInventario")' in kt, carpeta
    puente = kt.split("inner class Puente")[1][:300]
    assert "@android.webkit.JavascriptInterface" in puente and "dialogoConfig()" in puente, carpeta
lay = open(os.path.join(RAIZ, "android-movil", "app", "src", "main", "res", "layout",
                        "activity_main.xml"), encoding="utf-8").read()
assert "btnConfig" not in lay, "la app del celular ya no lleva la barra con el ⚙ arriba"
ok("las tres apps abren sus ajustes desde el ⚙ de la pantalla; el celular sin barra arriba")

# --- en las pistolas, esos ajustes son los de siempre MÁS lo del celular ---
for carpeta, paq in (("android-c72", "rfid"), ("android-alien", "alien")):
    kt = open(os.path.join(RAIZ, carpeta, "app", "src", "main", "java", "com", "inventario", paq,
                           "MainActivity.kt"), encoding="utf-8").read()
    cfg = kt.split("private fun dialogoConfig()")[1].split("\n    private fun ")[0]
    for de_siempre in ("URL servidor", "Buscar el servidor en la red", "Nombre equipo",
                       "barPot", "Pitido al leer"):
        assert de_siempre in cfg, "%s: se perdió «%s» de la Configuración" % (carpeta, de_siempre)
    assert "AjustesPantalla(cont)" in cfg and "ajPant.guardar()" in cfg, carpeta
    assert "ScrollView" in cfg, carpeta + ": la Configuración debe poder desplazarse (pantalla chica)"
    nuevo = kt.split("inner class AjustesPantalla")[1][:2600]
    for t in ("Para qué se usa este equipo", "fuera de la bodega", "Recargar la pantalla del inventario",
              "Buscar actualización de la app"):
        assert t in nuevo, "%s: falta «%s»" % (carpeta, t)
    assert "abrirInventario()" in kt.split("private fun mostrarInventario")[1][:1600], carpeta
ok("pistolas: la Configuración conserva servidor, alcance y pitido, y suma modo, "
   "dirección de afuera, recargar y buscar actualización")

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
