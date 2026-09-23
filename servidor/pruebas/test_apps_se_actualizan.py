# -*- coding: utf-8 -*-
"""Las apps de Android (pistolas y celular) se ponen al día solas.

Cadena completa:
  1. las APK nuevas van DENTRO del programa del servidor (carpeta «apks»);
  2. al arrancar, el servidor las pasa a «subidos» si son más nuevas;
  3. las apps preguntan en /api/apps/versiones y, si hay una más nueva,
     la descargan y Android pide «Actualizar».
Si se rompe cualquier eslabón, las pistolas se quedan con la versión vieja
sin que nadie se entere. Por eso se prueba entera.
"""
import io
import os
import shutil
import subprocess
import tempfile

from _comun import ruta  # noqa: E402  (deja el programa a mano)
import app as A

ok = lambda m: print("[OK] " + m)
SERV = os.path.dirname(ruta("app.py"))
RAIZ = os.path.dirname(SERV)
TMP = tempfile.mkdtemp(prefix="rfid_apps_")
A.DB = os.path.join(TMP, "t.db")
A.CFG = os.path.join(TMP, "c.json")
A.BASE = TMP
A.init_db()

APPS = {"InventarioRFID-C72.apk": "com.inventario.rfid",
        "InventarioRFID-Alien.apk": "com.inventario.alien",
        "InventarioRFID-Movil.apk": "com.inventario.movil"}
INCLUIDAS = os.path.join(SERV, "apks")

# ===================================================== leer la versión de una APK
for n, paq in APPS.items():
    p, vc, vn = A.leer_version_apk(os.path.join(INCLUIDAS, n))
    assert p == paq and vc > 0 and vn, (n, p, vc, vn)
ok("se lee paquete y versión de las tres APK sin herramientas de Android")

# comparado con la herramienta oficial, si está en este PC
aapt = None
bt = r"C:\Android\Sdk\build-tools"
if os.path.isdir(bt):
    for v in sorted(os.listdir(bt), reverse=True):
        if os.path.exists(os.path.join(bt, v, "aapt.exe")):
            aapt = os.path.join(bt, v, "aapt.exe")
            break
if aapt:
    for n in APPS:
        f = os.path.join(INCLUIDAS, n)
        # aapt no abre rutas con «Ñ» (la carpeta es DISEÑO): se le da solo el nombre
        linea = subprocess.run([aapt, "dump", "badging", n], capture_output=True, cwd=INCLUIDAS,
                               text=True, errors="replace").stdout.splitlines()[0]
        p, vc, vn = A.leer_version_apk(f)
        assert "name='%s'" % p in linea and "versionCode='%d'" % vc in linea \
            and "versionName='%s'" % vn in linea, (linea, p, vc, vn)
    ok("coincide exactamente con aapt, la herramienta oficial de Android")
else:
    print("[--] aapt no está en este PC: comparación con la oficial saltada")

# ===================================================== lo que trae el programa
for n in APPS:
    inc = A.leer_version_apk(os.path.join(INCLUIDAS, n))[1]
    sub = A.leer_version_apk(os.path.join(SERV, "subidos", n))[1]
    raiz = A.leer_version_apk(os.path.join(RAIZ, n))[1]
    assert inc >= sub, "%s: la del programa (%d) es más vieja que la de subidos (%d)" % (n, inc, sub)
    assert inc == raiz, "%s: la del programa (%d) y la de la raíz (%d) no coinciden" % (n, inc, raiz)
ok("el programa lleva la última versión de cada app (igual que la de la raíz)")

bat = io.open(os.path.join(SERV, "compilar.bat"), encoding="utf-8").read()
assert '--add-data "apks;apks"' in bat, "compilar.bat debe meter las APK en el programa"
ok("compilar.bat mete las APK dentro del programa")

# ===================================================== el servidor las pone al día
A.SUBIDOS = os.path.join(TMP, "subidos")
os.makedirs(A.SUBIDOS)
puestas = A.sincronizar_apks()
assert sorted(puestas) == sorted(APPS), puestas
ok("al arrancar sin apps, las pone todas en «subidos»")
assert A.sincronizar_apks() == []
ok("si ya están al día, no copia nada")

# una más VIEJA en subidos se reemplaza; una más NUEVA no se toca
vieja = subprocess.run(["git", "-C", RAIZ, "show", "94b471a:InventarioRFID-Movil.apk"],
                       capture_output=True).stdout
if vieja[:2] == b"PK":
    destino = os.path.join(A.SUBIDOS, "InventarioRFID-Movil.apk")
    io.open(destino, "wb").write(vieja)
    assert A.leer_version_apk(destino)[1] < A.leer_version_apk(
        os.path.join(INCLUIDAS, "InventarioRFID-Movil.apk"))[1]
    assert A.sincronizar_apks() == ["InventarioRFID-Movil.apk"]
    ok("una app vieja en «subidos» se reemplaza por la nueva")
    # al revés: el programa trae la vieja y en subidos hay una nueva
    otra = os.path.join(TMP, "incluidas_viejas")
    os.makedirs(otra)
    io.open(os.path.join(otra, "InventarioRFID-Movil.apk"), "wb").write(vieja)
    guardado, A.APKS_INCLUIDAS = A.APKS_INCLUIDAS, otra
    antes = A.leer_version_apk(destino)[1]
    assert A.sincronizar_apks() == [] and A.leer_version_apk(destino)[1] == antes
    A.APKS_INCLUIDAS = guardado
    ok("nunca pisa una app más nueva con una más vieja")
else:
    print("[--] sin la APK vieja en el historial: prueba de versiones saltada")

# ===================================================== lo que preguntan las apps
cl = A.app.test_client()
j = cl.get("/api/apps/versiones").get_json()
por_paquete = {a["paquete"]: a for a in j["apps"]}
for n, paq in APPS.items():
    a = por_paquete[paq]
    assert a["version_code"] == A.leer_version_apk(os.path.join(INCLUIDAS, n))[1]
    assert a["url"] == "/descargar/" + n and a["bytes"] > 1_000_000
    r = cl.get(a["url"])
    assert r.status_code == 200 and len(r.data) == a["bytes"]
    assert r.mimetype == "application/vnd.android.package-archive"
ok("/api/apps/versiones dice versión, tamaño y dónde bajarla, y la descarga cuadra")

# desde afuera también, pero con sesión (como todo lo demás)
t = A.app.test_client()
t.environ_base.update({"REMOTE_ADDR": "127.0.0.1", "rfid.afuera": True})
assert t.get("/api/apps/versiones").status_code == 401
ok("desde afuera, sin sesión, no se ve ni se baja nada")

# ===================================================== las tres apps
comun = io.open(os.path.join(RAIZ, "android-comun", "Actualizador.kt"), encoding="utf-8").read()
for carpeta, paq in (("android-c72", "com.inventario.rfid"), ("android-alien", "com.inventario.alien"),
                     ("android-movil", "com.inventario.movil")):
    src = os.path.join(RAIZ, carpeta, "app", "src", "main")
    kt = os.path.join(src, "java", *paq.split("."))
    act = io.open(os.path.join(kt, "Actualizador.kt"), encoding="utf-8").read()
    assert act == comun.replace("package PAQUETE", "package " + paq, 1), \
        carpeta + ": su Actualizador.kt no es copia del de android-comun"
    man = io.open(os.path.join(src, "AndroidManifest.xml"), encoding="utf-8").read()
    assert "android.permission.REQUEST_INSTALL_PACKAGES" in man, carpeta
    assert 'android:name="%s.ApkProvider"' % paq in man, carpeta
    assert 'android:authorities="%s.apk"' % paq in man, carpeta
    assert 'android:exported="false"' in man.split("ApkProvider")[1][:200], \
        carpeta + ": el proveedor no puede quedar abierto a otras apps"
    main = io.open(os.path.join(kt, "MainActivity.kt"), encoding="utf-8").read()
    assert "Actualizador.revisar(" in main and "Actualizador.alVolver(this)" in main, carpeta
    assert "override fun onResume()" in main, carpeta
ok("las tres apps llevan el mismo actualizador, su permiso y su proveedor privado")

# la dirección que usa el actualizador es la del proveedor declarado
assert 'Uri.parse("content://${act.packageName}.apk/$ARCHIVO")' in comun
ok("el actualizador le pasa la APK al instalador por el proveedor declarado")

shutil.rmtree(TMP, ignore_errors=True)
print("\nTODAS LAS PRUEBAS PASARON")
