# -*- coding: utf-8 -*-
"""Modo oscuro: paleta por variables, sin romper los colores de cada modo."""
import os
import re
import sys
import tempfile

from _comun import ruta  # noqa: E402  (deja el programa a mano)
import app as A

TMP = tempfile.mkdtemp(prefix="rfid_osc_")
A.DB = os.path.join(TMP, "t.db")
A.CFG = os.path.join(TMP, "c.json")
A.BASE = TMP
A.init_db()
ok = lambda m: print("[OK] " + m)
cl = A.app.test_client()

h = cl.get("/escritorio").get_data(as_text=True)

# --- toda variable usada tiene que estar definida ---
usadas = set(re.findall(r"var\((--[a-z0-9-]+)\)", h))
raiz = h.split(":root{")[1].split("}")[0]
oscuro = h.split('html[data-tema="oscuro"]{')[1].split("}")[0]
definidas = set(re.findall(r"(--[a-z0-9-]+)\s*:", raiz))
faltan = usadas - definidas
assert not faltan, "variables usadas sin definir: %s" % sorted(faltan)
assert len(usadas) >= 12, len(usadas)
ok("las %d variables de color que se usan están todas definidas" % len(usadas))

# --- el tema oscuro redefine TODAS, si no queda algo a medias ---
en_oscuro = set(re.findall(r"(--[a-z0-9-]+)\s*:", oscuro))
sin_oscuro = definidas - en_oscuro
assert not sin_oscuro, "sin versión oscura: %s" % sorted(sin_oscuro)
ok("el tema oscuro redefine las %d, no deja ninguna a medias" % len(definidas))

# --- el oscuro tiene que ser de verdad oscuro y con contraste ---
def luz(c):
    r, g, b = int(c[1:3], 16), int(c[3:5], 16), int(c[5:7], 16)
    return (0.299 * r + 0.587 * g + 0.114 * b) / 255


def val(bloque, nombre):
    return re.search(nombre + r":\s*(#[0-9A-Fa-f]{6})", bloque).group(1)


assert luz(val(oscuro, "--fondo")) < 0.2, val(oscuro, "--fondo")
assert luz(val(oscuro, "--texto")) > 0.8, val(oscuro, "--texto")
assert luz(val(raiz, "--fondo")) > 0.9 and luz(val(raiz, "--texto")) < 0.2
ok("en oscuro el fondo es oscuro y la letra clara; en claro, al revés")

# contraste texto/fondo suficiente en los dos temas
for nombre, bloque in (("claro", raiz), ("oscuro", oscuro)):
    c = abs(luz(val(bloque, "--fondo")) - luz(val(bloque, "--texto")))
    assert c > 0.6, (nombre, c)
ok("el contraste entre letra y fondo es amplio en los dos temas")

# --- los recuadros de color (avisos, semáforo) también se oscurecen ---
# Si no, quedaría letra clara sobre fondo claro: ilegible.
for v in ("--aviso", "--rot-alta", "--rot-baja"):
    assert luz(val(raiz, v)) > 0.85, ("en claro debe ser pastel", v)
    assert luz(val(oscuro, v)) < 0.28, ("en oscuro debe ser oscuro", v, val(oscuro, v))
ok("los recuadros de aviso y del semáforo tienen versión oscura")

# y los textos de color se aclaran para que se lean sobre el fondo oscuro
for v in ("--verde", "--ambar", "--rojo", "--exito"):
    assert luz(val(oscuro, v)) > luz(val(raiz, v)), ("no se aclaró", v, val(oscuro, v))
    # lo que de verdad importa: que se despegue del fondo oscuro
    assert abs(luz(val(oscuro, v)) - luz(val(oscuro, "--fondo"))) > 0.4, \
        (v, val(oscuro, v), "poco contraste con el fondo")
ok("los textos verdes, ámbar y rojos se aclaran para leerse en oscuro")

# el texto tenue tiene que verse sobre el recuadro de aviso, en los dos temas
for nombre, bloque in (("claro", raiz), ("oscuro", oscuro)):
    d = abs(luz(val(bloque, "--tenue")) - luz(val(bloque, "--aviso")))
    assert d > 0.25, ("texto tenue poco legible sobre el aviso", nombre, d)
ok("la letra tenue se lee sobre el recuadro de aviso en los dos temas")

# --- se aplica ANTES de pintar, para que no dé un fogonazo blanco ---
cabeza = h.split("</head>")[0]
assert "data-tema" in cabeza and "localStorage.getItem('tema')" in cabeza
assert cabeza.index("setAttribute('data-tema'") < h.index("<body")
assert "prefers-color-scheme: dark" in cabeza
ok("el tema se aplica en la cabecera (sin parpadeo) y hace caso a Windows")

# --- el botón y la función ---
assert 'id="btn-tema"' in h and 'onclick="cambiarTema()"' in h
assert "function cambiarTema" in h and "localStorage.setItem('tema'" in h
assert "function pintarBotonTema" in h
ok("hay botón en la tira de pestañas y la elección se recuerda en ese PC")

# --- los COLORES DE MODO siguen funcionando (se sustituyen como texto) ---
hp = cl.get("/escritorio?modo=principal").get_data(as_text=True)
hv = cl.get("/escritorio?modo=vendedor").get_data(as_text=True)
assert "#C62828" in hp and "#E87722" not in hp, "el PC principal debe quedar rojo"
assert "#1F7A44" in hv and "#E87722" not in hv, "vendedores debe quedar verde"
assert "#E87722" in h, "sin modo sigue naranja"
ok("los colores de cada PC (rojo/naranja/verde) siguen pintándose bien")

# --- y el modo oscuro sigue estando en los tres ---
for nombre, pag in (("mostrador", h), ("principal", hp), ("vendedor", hv)):
    assert 'html[data-tema="oscuro"]' in pag, nombre
    assert 'id="btn-tema"' in pag, nombre
ok("los tres tipos de PC tienen modo oscuro")

# --- el papel de la etiqueta NO se oscurece: es lo que se imprime ---
assert "#dis-etq" in h.split('html[data-tema="oscuro"] img')[1][:400]
ok("la vista de la etiqueta se deja intacta (es papel blanco que se va a imprimir)")

# --- los grises solo pueden estar DENTRO de la paleta, en ningún otro sitio ---
fuera = h.replace(":root{" + raiz + "}", "")
for gris in ("#F3F2F1", "#E1DFDD", "#5A5856", "#8A8886", "#C8C6C4", "#252423",
             "#FBFAF9", "#FAF9F8", "#E7E5E3"):
    assert gris in raiz, "%s debería estar en la paleta" % gris
    assert gris not in fuera and gris.lower() not in fuera, \
        "%s quedó suelto fuera de la paleta" % gris
ok("los grises están SOLO en la paleta: cambiar el tema los cambia todos")

# --- NINGÚN recuadro puede llevar el fondo blanco fijo ---
# Si lo lleva, en oscuro queda letra clara sobre blanco: ilegible. Le pasó al
# cuadro de «referencias aplicables» de los vendedores. Los únicos blancos que
# valen son los del PAPEL de la etiqueta, marcados con /*papel*/.
sueltos = []
for linea in fuera.splitlines():
    if "/*papel*/" in linea:
        continue
    for blanco in ("background:#fff", "background:#FFFFFF", "background: #fff"):
        if blanco in linea:
            sueltos.append(linea.strip()[:90])
assert not sueltos, "fondo blanco fijo (ilegible en oscuro):\n  " + "\n  ".join(sueltos)
ok("ningún recuadro lleva fondo blanco fijo, salvo el papel de la etiqueta")

# el cuadro de referencias del VENDEDOR sigue el tema
ficha = h.split('<textarea id="i-refs-edit"')[1][:400]
assert "var(--campo)" in ficha and "#FFFFFF" not in ficha, ficha[:200]
ok("las referencias del vendedor usan el color del tema, no blanco fijo")

print("\nTODAS LAS PRUEBAS PASARON")
