# -*- coding: utf-8 -*-
"""La pantalla del inventario se puede usar en un celular.

Antes no llevaba etiqueta de móvil: el teléfono la dibujaba a lo ancho de un
PC y tocaba arrastrar y hacer zoom para todo. Ahora se dibuja al ancho real
del teléfono y, por debajo de cierto tamaño, se quita de la vista lo que
menos se consulta.

En PC y tabletas en horizontal NO debe cambiar nada.
"""
import os
import re
import sys
import tempfile

from _comun import ruta  # noqa: E402  (deja el programa a mano)
import app as A

TMP = tempfile.mkdtemp(prefix="rfid_movil_")
A.DB = os.path.join(TMP, "t.db")
A.CFG = os.path.join(TMP, "c.json")
A.BASE = TMP
A.init_db()
ok = lambda m: print("[OK] " + m)

# --- ANTES QUE NADA: la página tiene que cargar ---
# En la plantilla, «{#» abre un comentario. Si en el CSS aparece «{#algo»
# (una regla pegada a un selector de id), la página entera da error 500 y
# el inventario se cae en TODOS los equipos. Ya pasó una vez.
fuente = open(ruta("templates", "escritorio.html"), encoding="utf-8").read()
assert "{#" not in fuente, ("hay un «{#» en la plantilla: se lee como comentario "
                            "y la página se cae. Pon un espacio: «{ #»")
r = A.app.test_client().get("/escritorio")
assert r.status_code == 200, "la pantalla no carga: HTTP %d" % r.status_code
ok("la pantalla carga (200) y no hay ningún «{#» suelto que la tumbe")
h = r.get_data(as_text=True)

# --- el teléfono la dibuja a SU ancho ---
cab = h.split("</head>")[0]
assert 'name="viewport"' in cab and "width=device-width" in cab
ok("el teléfono la dibuja a su propio ancho, no al de un PC")

# --- las reglas de móvil existen y están acotadas ---
anchos = [int(x) for x in re.findall(r"@media \(max-width:(\d+)px\)", h)]
assert anchos, "no hay ninguna regla para pantallas estrechas"
assert max(anchos) <= 900, "una regla de móvil llega hasta %dpx: tocaría el PC" % max(anchos)
ok("las reglas solo entran por debajo de 900px: el PC y las tabletas quedan igual")

# --- en un celular caben las columnas que importan ---
movil = h.split("@media (max-width:620px)")[1].split("@media")[0]
for col in ("nth-child(4)", "nth-child(5)"):
    assert col in movil, "en el celular debería ocultarse la columna " + col
assert "#t-resumen th:nth-child(3)" in movil, "el conteo también debe compactarse"
ok("en el celular se ocultan bodega y precio mínimo; quedan código, nombre, precio y stock")

# nunca se ocultan las dos primeras: sin código ni nombre no sirve de nada
# (se busca en cada regla que OCULTA algo; darles ancho sí está permitido)
for selectores in re.findall(r"([^{}]+)\{[^{}]*display:none[^{}]*\}", h):
    for col in ("nth-child(1)", "nth-child(2)"):
        assert not ("t-productos" in selectores and col in selectores), \
            "jamás ocultar el código ni el nombre del repuesto: " + selectores.strip()[:90]
ok("el código y el nombre no se ocultan nunca")

# --- los formularios de dos columnas pasan a una ---
assert "grid-template-columns:1fr}" in movil
ok("los formularios de dos columnas pasan a una sola")

# --- que el teléfono no haga zoom solo al tocar un campo ---
assert "font-size:16px" in movil
ok("los campos van a 16px: el teléfono no hace zoom solo al escribir")

# --- los botones se pueden tocar con el dedo ---
assert ".btn{padding:9px 14px}" in movil
ok("los botones crecen para poder tocarlos con el dedo")

# --- y el modo oscuro sigue funcionando (no se pisó la paleta) ---
assert ':root{' in h and 'html[data-tema="oscuro"]' in h
assert h.index(":root{") < h.index("@media (max-width:900px)"), \
    "la paleta debe definirse ANTES de las reglas de móvil"
ok("el modo oscuro sigue en pie y la paleta se define antes que las reglas")

print("\nTODAS LAS PRUEBAS PASARON")
