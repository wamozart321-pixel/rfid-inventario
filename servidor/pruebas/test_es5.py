# -*- coding: utf-8 -*-
"""La pantalla del inventario también funciona en navegadores VIEJOS.

La pistola Alien trae Android 4.4 (navegador de 2013): con la pantalla normal
se quedaba en blanco («SyntaxError: Use of const»). Para ella hay una copia
traducida (templates/escritorio_es5.html) que genera servidor/es5/construir.mjs.

Lo que se vigila aquí:
  * que la copia esté AL DÍA con escritorio.html (si no, la Alien vería una
    pantalla vieja): si falla, correr «node construir.mjs» en servidor/es5;
  * que el servidor dé cada versión a quien le toca;
  * que en la pantalla no se cuele CSS demasiado nuevo que deje las ventanas
    sin tamaño en la Alien (ya pasó con «inset» y «min()»).
"""
import hashlib
import os
import re
import tempfile

from _comun import ruta  # noqa: E402  (deja el programa a mano)
import app as A

TMP = tempfile.mkdtemp(prefix="rfid_es5_")
A.DB = os.path.join(TMP, "t.db")
A.CFG = os.path.join(TMP, "c.json")
A.BASE = TMP
A.init_db()
ok = lambda m: print("[OK] " + m)

fuente = open(ruta("templates", "escritorio.html"), "rb").read()
copia = open(ruta("templates", "escritorio_es5.html"), encoding="utf-8").read()

# ===================================================== la copia está al día
huella = hashlib.sha256(fuente).hexdigest()[:16]
m = re.search(r"huella ([0-9a-f]{16})", copia)
assert m, "escritorio_es5.html no dice de qué versión salió"
assert m.group(1) == huella, (
    "escritorio_es5.html está VIEJA: se cambió escritorio.html y no se volvió a "
    "traducir. Correr:  cd servidor\\es5  y  node construir.mjs")
ok("la copia para navegadores viejos está al día con la pantalla normal")

poly = ruta("static", "es5", "polyfills.js")
assert os.path.getsize(poly) > 100_000
texto_poly = open(poly, encoding="utf-8").read()
for pieza in ("regeneratorRuntime", "fetch", "String.prototype.normalize", "E.closest"):
    assert pieza in texto_poly, "a polyfills.js le falta " + pieza
ok("polyfills.js trae fetch, async/await, normalize (tildes) y closest")

# ===================================================== a cada uno lo suyo
ALIEN = ("Mozilla/5.0 (Linux; Android 4.4.2; ALR-H450 Build/KOT49H) AppleWebKit/537.36 "
         "(KHTML, like Gecko) Version/4.0 Chrome/30.0.0.0 Mobile Safari/537.36")
VIEJO_SIN_CHROME = "Mozilla/5.0 (Linux; U; Android 4.1.2; es-co) AppleWebKit/534.30 Version/4.0 Mobile Safari/534.30"
PC = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) "
      "Chrome/140.0.0.0 Safari/537.36")
CEL = ("Mozilla/5.0 (Linux; Android 14; SM-A546E) AppleWebKit/537.36 (KHTML, like Gecko) "
       "Chrome/140.0.0.0 Mobile Safari/537.36")
cl = A.app.test_client()


def pagina(ua, extra=""):
    r = cl.get("/escritorio" + extra, headers={"User-Agent": ua})
    assert r.status_code == 200, r.status_code
    return r.get_data(as_text=True)


es_vieja = lambda h: "/static/es5/polyfills.js" in h
assert es_vieja(pagina(ALIEN)), "la Alien debería recibir la copia traducida"
assert es_vieja(pagina(VIEJO_SIN_CHROME))
ok("la Alien (Android 4.4) y otros navegadores viejos reciben la copia traducida")
assert not es_vieja(pagina(PC)) and not es_vieja(pagina(CEL))
ok("el PC y los celulares modernos siguen recibiendo la pantalla normal")
assert es_vieja(pagina(PC, "?es5=1"))
ok("con ?es5=1 se puede ver la copia vieja desde cualquier navegador")

# la copia recibe los mismos datos del servidor que la normal
h = pagina(ALIEN, "?modo=vendedor")
assert "modo: 'vendedor'" in h and "afuera: false" in h, "faltan los datos del servidor en la copia"
assert "{{" not in h and "{%" not in h, "quedó código de plantilla sin procesar"
assert "#1F7A44" in h and "#E87722" not in h, "el modo vendedor debe salir verde también en la copia"
ok("la copia recibe modo, dirección y colores igual que la normal (vendedor = verde)")

# y su JavaScript es del estándar viejo (lo que entiende Android 4.4)
scripts = re.findall(r"<script>([\s\S]*?)</script>", h)
grande = max(scripts, key=len)
for nuevo in (r"\bconst\s", r"\blet\s", r"=>", r"\basync\s+function", r"\?\.", r"\?\?"):
    assert not re.search(nuevo, grande), "en la copia quedó JavaScript moderno: " + nuevo
ok("el JavaScript de la copia no usa nada moderno (const, flechas, async, ?., ??)")

# ===================================================== CSS que la Alien no entiende
estilo = fuente.decode("utf-8")
for prohibido, porque in ((r"\binset\s*:", "«inset» (usa top/right/bottom/left)"),
                          (r":\s*(min|max|clamp)\(", "min()/max()/clamp() en CSS")):
    hallado = re.search(prohibido, estilo)
    assert not hallado, ("en escritorio.html hay %s: en la Alien las ventanas quedan sin tamaño"
                         % porque)
ok("la pantalla no usa CSS que deje las ventanas sin tamaño en la Alien")

print("\nTODAS LAS PRUEBAS PASARON")
