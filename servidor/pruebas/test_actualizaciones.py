# -*- coding: utf-8 -*-
"""El programa se pone al día solo cuando se publica una versión nueva."""
import io
import json
import os
import sys
import tempfile
from datetime import datetime, timedelta

from _comun import ruta  # noqa: E402  (deja el programa a mano)
import app as A

TMP = tempfile.mkdtemp(prefix="rfid_upd_")
A.DB = os.path.join(TMP, "t.db")
A.CFG = os.path.join(TMP, "c.json")
A.BASE = TMP
A.init_db()
ok = lambda m: print("[OK] " + m)
cl = A.app.test_client()

# ---------------------------------------------------------------- comparar
assert A._num_version("v2.10.1") == (2, 10, 1)
assert A.hay_version_nueva("2.1", "v2.2")
assert A.hay_version_nueva("2.9", "2.10"), "2.10 es MAYOR que 2.9"
assert not A.hay_version_nueva("2.1", "v2.1")
assert not A.hay_version_nueva("2.1", "v2.0")
assert not A.hay_version_nueva("2.1", "")
ok("compara versiones por números: la 2.10 es MAYOR que la 2.9 (no como texto)")

# ------------------------------------------------- respuesta falsa de GitHub
RESPUESTA = {"tag_name": "v9.9", "body": "Arregla la impresora",
             "assets": [{"name": "ServidorInventarioRFID.exe", "size": 33_000_000,
                         "browser_download_url":
                         "https://github.com/x/y/releases/download/v9.9/ServidorInventarioRFID.exe"}]}


class RespuestaFalsa:
    def __init__(self, datos): self._d = json.dumps(datos).encode()
    def read(self): return self._d
    def __enter__(self): return self
    def __exit__(self, *a): return False


import urllib.request
pedidas = []


def falso_urlopen(req, timeout=0, **k):
    url = req.full_url if hasattr(req, "full_url") else req
    pedidas.append(url)
    return RespuestaFalsa(RESPUESTA)


urllib.request.urlopen = falso_urlopen

info = A.buscar_actualizacion()
assert info["hay"] and info["nueva"] == "v9.9" and info["tamano"] == 33_000_000
assert "releases/latest" in pedidas[0] and "wamozart321-pixel/rfid-inventario" in pedidas[0]
assert info["notas"] == "Arregla la impresora"
ok("pregunta al repositorio y detecta que hay una versión nueva publicada")

# una versión más vieja o igual no cuenta
RESPUESTA["tag_name"] = "v1.0"
assert not A.buscar_actualizacion()["hay"]
RESPUESTA["tag_name"] = "v" + A.VERSION
assert not A.buscar_actualizacion()["hay"]
ok("una versión igual o más vieja NO se instala")

# publicada pero sin el programa adjunto: se avisa, no se rompe
RESPUESTA["tag_name"] = "v9.9"
RESPUESTA["assets"] = [{"name": "Instalar-InventarioRFID.exe", "size": 1, "browser_download_url": "x"}]
i2 = A.buscar_actualizacion()
assert not i2["hay"] and "no trae el programa" in i2["error"]
ok("si la publicación no trae el programa, avisa en vez de intentarlo")
RESPUESTA["assets"] = [{"name": "ServidorInventarioRFID.exe", "size": 33_000_000,
                        "browser_download_url":
                        "https://github.com/x/y/releases/download/v9.9/ServidorInventarioRFID.exe"}]

# el repositorio se puede cambiar desde la configuración
c = A.cfg(); c["actualizar_repo"] = "otro/repo"; A.guardar_cfg(c)
pedidas.clear(); A.buscar_actualizacion()
assert "otro/repo" in pedidas[0]
c["actualizar_repo"] = ""; A.guardar_cfg(c)
ok("se puede apuntar a otro repositorio desde la configuración")

# ---------------------------------------------------------------- descarga
EXE_FALSO = b"MZ" + b"\0" * (2 * 1024 * 1024)
# el tamaño anunciado en la publicación tiene que cuadrar con el archivo
RESPUESTA["assets"][0]["size"] = len(EXE_FALSO)


class Descarga:
    def __init__(self, datos): self._b = io.BytesIO(datos)
    def read(self, n=-1): return self._b.read(n)
    def __enter__(self): return self
    def __exit__(self, *a): return False


def con_descarga(datos):
    def _f(req, timeout=0, **k):
        url = req.full_url if hasattr(req, "full_url") else req
        if "api.github.com" in url:
            return RespuestaFalsa(RESPUESTA)
        return Descarga(datos)
    urllib.request.urlopen = _f


con_descarga(EXE_FALSO)
dest = os.path.join(TMP, "bajado.exe")

# de un sitio que no es GitHub: ni se intenta
try:
    A._descargar_exe("https://malo.example.com/x.exe", dest)
    raise AssertionError("debía negarse")
except OSError as e:
    assert "no viene de GitHub" in str(e)
assert not os.path.exists(dest)
ok("no descarga de ningún sitio que no sea GitHub")

# por http (sin cifrar) tampoco
try:
    A._descargar_exe("http://github.com/x.exe", dest)
    raise AssertionError("debía negarse")
except OSError as e:
    assert "no viene de GitHub" in str(e)
ok("tampoco por conexión sin cifrar")

URL = "https://github.com/x/y/releases/download/v9.9/ServidorInventarioRFID.exe"
n = A._descargar_exe(URL, dest, len(EXE_FALSO))
assert n == len(EXE_FALSO) and os.path.exists(dest)
ok("descarga bien cuando viene de GitHub y el tamaño cuadra")

# tamaño distinto del anunciado = descarga cortada
try:
    A._descargar_exe(URL, dest, len(EXE_FALSO) + 5)
    raise AssertionError("debía negarse")
except OSError as e:
    assert "incompleta" in str(e)
assert not os.path.exists(dest), "y borra lo descargado"
ok("si la descarga llega incompleta se descarta (no se instala a medias)")

# lo descargado no es un programa de Windows
con_descarga(b"NO SOY UN EXE" + b"\0" * (2 * 1024 * 1024))
try:
    A._descargar_exe(URL, dest)
    raise AssertionError("debía negarse")
except OSError as e:
    assert "no es un programa de Windows" in str(e)
assert not os.path.exists(dest)
ok("si lo descargado no es un programa de Windows, se descarta")

# demasiado pequeño
con_descarga(b"MZ")
try:
    A._descargar_exe(URL, dest)
    raise AssertionError("debía negarse")
except OSError as e:
    assert "demasiado pequeño" in str(e)
ok("un archivo ridículamente pequeño también se descarta")

# ---------------------------------------------------------------- instalar
con_descarga(EXE_FALSO)

# desde el código (sin .exe) no se actualiza solo
try:
    A.instalar_actualizacion()
    raise AssertionError("debía negarse")
except OSError as e:
    assert "programa instalado" in str(e)
ok("corriendo desde el código no intenta actualizarse")

# ahora como si fuera el programa instalado
reinicios = []
A._reiniciar_programa = lambda: reinicios.append(1)


class TimerFalso:
    def __init__(self, *a, **k): pass
    def start(self): pass


A.threading.Timer = TimerFalso
sys.frozen = True
try:
    exe = os.path.join(TMP, "ServidorInventarioRFID.exe")
    io.open(exe, "wb").write(b"MZ" + b"VIEJO" * 10)
    r = A.instalar_actualizacion()
    assert r["instalada"] == "v9.9" and r["anterior"] == A.VERSION
    assert io.open(exe, "rb").read() == EXE_FALSO, "el nuevo ocupa el sitio del viejo"
    guardado = os.path.join(TMP, "ServidorInventarioRFID_v%s.exe" % A.VERSION)
    assert os.path.exists(guardado), "la versión anterior queda guardada"
    assert b"VIEJO" in io.open(guardado, "rb").read()
    assert not os.path.exists(exe + ".nuevo"), "no deja basura"
    assert reinicios, "y se reinicia"
    ok("instala: aparta la versión vieja, pone la nueva en su sitio y reinicia")

    # antes de tocar nada hace copia del inventario
    carp = A.carpeta_respaldos()
    assert os.path.isdir(carp) and os.listdir(carp), "debía guardar copia de la base"
    ok("antes de actualizar guarda una copia del inventario")

    # si la descarga falla, NO se toca el programa que está corriendo
    io.open(exe, "wb").write(b"MZ" + b"BUENO" * 10)
    con_descarga(b"basura")
    try:
        A.instalar_actualizacion()
        raise AssertionError("debía fallar")
    except OSError:
        pass
    assert b"BUENO" in io.open(exe, "rb").read(), "el programa en uso quedó intacto"
    ok("si la descarga falla, el programa que está corriendo NO se toca")
    con_descarga(EXE_FALSO)

    # ---------------------------------------------------- momento seguro
    A.ULTIMA_LECTURA = None
    assert A._nadie_leyendo()
    A.ULTIMA_LECTURA = datetime.now()
    assert not A._nadie_leyendo(), "no se reinicia con una pistola leyendo"
    A.ULTIMA_LECTURA = datetime.now() - timedelta(minutes=30)
    assert A._nadie_leyendo()
    ok("no se actualiza a mitad de un conteo: espera a que nadie esté leyendo")

    # una lectura de la pistola deja la marca puesta
    A.ULTIMA_LECTURA = None
    cl.post("/api/lecturas", json={"dispositivo": "C72-01", "epcs": ["E2801100AA"]})
    assert A.ULTIMA_LECTURA is not None and not A._nadie_leyendo()
    ok("cada envío de la pistola deja anotado que se está trabajando")

    # ---------------------------------------------------- endpoints
    A.ULTIMA_LECTURA = None
    j = cl.post("/api/actualizacion/buscar", json={}).get_json()
    assert j["ok"] and j["hay"] and j["nueva"] == "v9.9" and j["instalable"] is True
    ok("el botón «Buscar ahora» consulta y responde")

    j = cl.get("/api/actualizacion").get_json()
    assert j["version"] == A.VERSION and j["hay"] and j["nueva"] == "v9.9"
    ok("la pantalla puede preguntar el estado sin salir a internet")

    io.open(exe, "wb").write(b"MZ" + b"OTRA" * 10)
    j = cl.post("/api/actualizacion/instalar", json={}).get_json()
    assert j["ok"] and "v9.9" in j["msg"] and "reinicia" in j["msg"]
    ok("el botón «Instalar ahora» actualiza y avisa de que se reinicia")

    # el aviso viaja por el latido que ya existía
    d = cl.get("/api/dashboard").get_json()
    assert d["actualizacion"]["nueva"] == "v9.9"
    assert d["actualizacion"]["version"] == A.VERSION
    ok("el aviso llega a la pantalla por /api/dashboard, sin pedir nada nuevo")

    # sin red: no revienta, deja el motivo escrito
    def sin_red(req, timeout=0, **k):
        raise OSError("no hay internet")
    urllib.request.urlopen = sin_red
    r = cl.post("/api/actualizacion/buscar", json={})
    assert r.status_code == 502 and "No se pudo consultar" in r.get_json()["error"]
    assert A.ESTADO_ACTUALIZACION["error"]
    ok("sin internet avisa con claridad en vez de romperse")
finally:
    del sys.frozen

# ---------------------------------------------------------------- ajustes
c = A.cfg()
assert c["actualizar_revisar"] is True and c["actualizar_auto"] is True
assert cl.post("/api/config", json={"actualizar_auto": False,
                                    "actualizar_revisar": False}).get_json()["ok"]
c = A.cfg()
assert c["actualizar_auto"] is False and c["actualizar_revisar"] is False
ok("se puede desactivar (avisar sí / instalar sola no) desde ⚙ Configuración")

# ---------------------------------------------------------------- pantalla
h = cl.get("/escritorio").get_data(as_text=True)
for marca in ("ACTUALIZACIONES DEL PROGRAMA", "function avisarActualizacion",
              "function instalarActualizacion", "function esperandoReinicio",
              'id="c-upd-auto"', "Instalarla sola", "🆕 Hay una versión nueva",
              "actualizar_auto:q('#c-upd-auto').checked"):
    assert marca in h, marca
ok("⚙ Configuración trae los interruptores y la pantalla avisa sola")

print("\nTODAS LAS PRUEBAS PASARON")
