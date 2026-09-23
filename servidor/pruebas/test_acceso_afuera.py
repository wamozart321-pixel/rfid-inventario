# -*- coding: utf-8 -*-
"""Entrar al inventario desde AFUERA de la bodega, con usuario y contraseña.

Dentro de la red del negocio todo sigue como siempre, sin clave. Desde
internet se entra por el puerto 5001 (el túnel, p. ej. Tailscale Funnel, lo
conecta ahí), y TODO lo que llega por esa puerta pide usuario y contraseña.

Esta prueba es la que evita que el inventario quede abierto a cualquiera.
"""
import os
import socket
import sqlite3
import tempfile
import time
import urllib.error
import urllib.request

from _comun import ruta  # noqa: E402  (deja el programa a mano)
import app as A

TMP = tempfile.mkdtemp(prefix="rfid_afuera_")
A.DB = os.path.join(TMP, "t.db")
A.CFG = os.path.join(TMP, "c.json")
A.BASE = TMP
A.init_db()
ok = lambda m: print("[OK] " + m)

BODEGA = {"REMOTE_ADDR": "192.168.0.23"}
ESTE_PC = {"REMOTE_ADDR": "127.0.0.1"}
# lo que llega por la puerta de afuera: el túnel se conecta desde este mismo
# PC y apunta al FINAL de X-Forwarded-For la IP de verdad
TUNEL = {"REMOTE_ADDR": "127.0.0.1", "rfid.afuera": True}


def cliente(env):
    c = A.app.test_client()
    c.environ_base.update(env)
    return c


def por_tunel(ip="181.50.10.20"):
    c = cliente(TUNEL)
    c.environ_base["HTTP_X_FORWARDED_FOR"] = ip
    c.environ_base["HTTP_X_FORWARDED_PROTO"] = "https"
    return c


# ===================================================== en la bodega, nada cambia
b = cliente(BODEGA)
for ruta_ in ("/escritorio", "/api/dashboard", "/api/productos", "/api/quien", "/"):
    r = b.get(ruta_)
    assert r.status_code == 200, (ruta_, r.status_code)
assert b.post("/api/productos/guardar", json={"sku": "S1", "nombre": "UNO",
              "precio": "1", "precio_minimo": "1"}).status_code == 200
assert cliente(ESTE_PC).get("/api/dashboard").status_code == 200
ok("en la bodega y en el propio PC se entra como siempre, sin clave")

# la pistola y los otros PCs tampoco
assert cliente({"REMOTE_ADDR": "10.0.0.7"}).get("/api/quien").status_code == 200
assert cliente({"REMOTE_ADDR": "172.20.1.4"}).get("/api/quien").status_code == 200
ok("cualquier red privada (192.168, 10., 172.16-31) cuenta como bodega")

# ===================================================== desde afuera, cerrado
t = por_tunel()
r = t.get("/escritorio")
assert r.status_code == 302 and r.headers["Location"].startswith("/entrar"), r.status_code
r = t.get("/api/productos")
assert r.status_code == 401 and r.get_json()["entrar"], r.status_code
assert t.post("/api/productos/guardar", json={"sku": "X", "nombre": "X"}).status_code == 401
assert t.get("/").status_code == 302 and t.get("/subir").status_code == 302
ok("desde afuera, sin entrar, no se ve NI se cambia nada (ni la API)")

# sin usuarios creados, el acceso de afuera está apagado del todo
h = t.get("/entrar").get_data(as_text=True)
assert "apagado" in h and 'name="clave"' not in h
ok("sin usuarios creados, desde afuera no hay ni formulario: está apagado")

# una IP pública directa al 5000 (alguien abrió el router) también es de afuera
assert cliente({"REMOTE_ADDR": "8.8.8.8"}).get("/api/productos").status_code == 401
assert cliente({"REMOTE_ADDR": "100.101.1.2"}).get("/api/productos").status_code == 401
ok("una IP pública o de Tailscale directa al 5000 también pide clave")

# fingir por cabecera que se viene de la bodega no sirve
t2 = por_tunel("192.168.0.23")
assert t2.get("/api/productos").status_code == 401
ok("por la puerta de afuera no vale decir «soy de la bodega» en una cabecera")

# ===================================================== usuarios: solo desde la bodega
r = t.post("/api/afuera/guardar", json={"usuario": "intruso", "clave": "12345678"})
assert r.status_code in (401, 403), r.status_code
for mal, porque in ((("ab", "clave-larga-1")), "usuario corto"), \
                   ((("carlos", "corta")), "clave corta"), \
                   ((("carlos", "carlos")), "clave = usuario"), \
                   ((("car los", "clave-larga-1")), "espacio"):
    r = b.post("/api/afuera/guardar", json={"usuario": mal[0], "clave": mal[1]})
    assert r.status_code == 400, porque
r = b.post("/api/afuera/guardar", json={"usuario": "carlos", "clave": "Bodega-2026",
                                         "nombre": "Carlos vendedor"})
assert r.get_json()["ok"], r.get_json()
con = sqlite3.connect(A.DB)
guardada = con.execute("SELECT clave FROM usuarios_afuera").fetchone()[0]
assert "Bodega-2026" not in guardada and guardada.startswith(("scrypt:", "pbkdf2:"))
ok("los usuarios se crean SOLO desde la bodega, con reglas, y la clave va cifrada")

# ===================================================== entrar
t = por_tunel()
r = t.post("/entrar", data={"usuario": "carlos", "clave": "mala-clave", "sig": "/escritorio"})
assert r.status_code == 200 and "incorrectos" in r.get_data(as_text=True)
r = t.post("/entrar", data={"usuario": "nadie", "clave": "Bodega-2026"})
assert "incorrectos" in r.get_data(as_text=True)
ok("clave mala o usuario inexistente: mismo mensaje, no se dice cuál falló")

r = t.post("/entrar", data={"usuario": "CARLOS", "clave": "Bodega-2026",
                            "sig": "/escritorio?modo=vendedor"})
assert r.status_code == 302 and r.headers["Location"] == "/escritorio?modo=vendedor", r.headers
galleta = r.headers["Set-Cookie"]
assert "HttpOnly" in galleta and "SameSite=Lax" in galleta and "Secure" in galleta, galleta
assert t.get("/api/productos").status_code == 200
h = t.get("/escritorio").get_data(as_text=True)
assert "const AFUERA = true" in h and 'id="btn-salir"' in h
ok("con la clave buena entra, vuelve a donde iba y la galleta va protegida")

token = galleta.split("=", 1)[1].split(";", 1)[0]
assert con.execute("SELECT COUNT(*) FROM sesiones_afuera WHERE huella=?",
                   (token,)).fetchone()[0] == 0
ok("en la base no queda el token, solo su huella")

# tras entrar no se puede mandar a nadie a otra web
for raro in ("https://malo.com", "//malo.com", "/\\malo.com"):
    r = por_tunel().post("/entrar", data={"usuario": "carlos", "clave": "Bodega-2026", "sig": raro})
    assert r.headers["Location"] == "/escritorio", (raro, r.headers["Location"])
ok("después de entrar solo se va a páginas del inventario, nunca a otra web")

# con sesión tampoco se manejan usuarios desde afuera
r = t.post("/api/afuera/guardar", json={"usuario": "otro", "clave": "clave-larga-1"})
assert r.status_code == 403
assert t.get("/api/afuera").status_code == 403
ok("aun con sesión, desde afuera no se pueden crear usuarios")

# en la bodega la pantalla no trae el botón de salir
h = b.get("/escritorio").get_data(as_text=True)
assert "const AFUERA = false" in h and 'id="btn-salir"' not in h
ok("en la bodega la pantalla sale como siempre, sin botón de salir")

# ===================================================== echar, cambiar clave, borrar
assert b.post("/api/afuera/cerrar", json={"usuario": "carlos"}).get_json()["ok"]
assert t.get("/api/productos").status_code == 401
ok("«echar de sus equipos» funciona al momento (celular perdido)")

t = por_tunel()
t.post("/entrar", data={"usuario": "carlos", "clave": "Bodega-2026"})
assert t.get("/api/productos").status_code == 200
b.post("/api/afuera/guardar", json={"usuario": "carlos", "clave": "Otra-Clave-9"})
assert t.get("/api/productos").status_code == 401
ok("al cambiar la clave, los equipos que entraron con la vieja salen")

t = por_tunel()
t.post("/entrar", data={"usuario": "carlos", "clave": "Otra-Clave-9"})
assert t.get("/api/productos").status_code == 200
t.get("/salir")
assert t.get("/api/productos").status_code == 401
ok("🚪 salir cierra la sesión de ese equipo")

t = por_tunel()
t.post("/entrar", data={"usuario": "carlos", "clave": "Otra-Clave-9"})
b.post("/api/afuera/borrar", json={"usuario": "carlos"})
assert t.get("/api/productos").status_code == 401
ok("al borrar el usuario ya no entra, aunque tuviera sesión")

# la sesión vence a los 30 días
b.post("/api/afuera/guardar", json={"usuario": "ana", "clave": "Clave-de-Ana1"})
t = por_tunel()
t.post("/entrar", data={"usuario": "ana", "clave": "Clave-de-Ana1"})
con.execute("UPDATE sesiones_afuera SET creada='2020-01-01T00:00:00'")
con.commit()
assert t.get("/api/productos").status_code == 401
ok("la sesión vence sola a los 30 días")

# ===================================================== probar claves sin parar
A._fallos.clear()
t = por_tunel("200.1.1.1")
for _ in range(A.FALLOS_POR_EQUIPO):
    t.post("/entrar", data={"usuario": "ana", "clave": "no-es"})
r = t.post("/entrar", data={"usuario": "ana", "clave": "Clave-de-Ana1"})
assert r.status_code == 429 and "Demasiados" in r.get_data(as_text=True)
ok("tras %d intentos malos se bloquea, aunque luego acierte" % A.FALLOS_POR_EQUIPO)

# otro equipo sí puede entrar: el bloqueo es por quien falla
r = por_tunel("201.2.2.2").post("/entrar", data={"usuario": "ana", "clave": "Clave-de-Ana1"})
assert r.status_code == 302
ok("el bloqueo es para el equipo que falla, no para los demás")

# y cambiando de IP a cada intento, frena el tope general
A._fallos.clear()
for i in range(A.FALLOS_EN_TOTAL):
    por_tunel("203.0.%d.1" % i).post("/entrar", data={"usuario": "ana", "clave": "x" * 9})
r = por_tunel("198.51.100.9").post("/entrar", data={"usuario": "ana", "clave": "Clave-de-Ana1"})
assert r.status_code == 429
ok("probando desde muchas IP distintas también se frena (tope general)")
A._fallos.clear()

# ===================================================== la puerta 5001 de verdad
# Se abre un servidor de prueba con la puerta de afuera en un puerto libre:
# solo debe escuchar en 127.0.0.1, y todo lo que entra por ahí pide clave.
s = socket.socket()
s.bind(("127.0.0.1", 0))
libre = s.getsockname()[1]
s.close()
A.PUERTO_AFUERA = libre
A.iniciar_puerta_afuera()
for _ in range(50):
    try:
        socket.create_connection(("127.0.0.1", libre), timeout=0.2).close()
        break
    except OSError:
        time.sleep(0.1)


class SinSeguir(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *a, **k):
        return None


abre = urllib.request.build_opener(SinSeguir)
try:
    abre.open("http://127.0.0.1:%d/api/productos" % libre, timeout=5)
    raise AssertionError("la puerta de afuera dejó ver los productos sin clave")
except urllib.error.HTTPError as e:
    assert e.code == 401, e.code
ok("la puerta de afuera de verdad (puerto aparte) pide clave aunque venga del propio PC")

fuente = open(ruta("app.py"), encoding="utf-8").read()
assert 'make_server("127.0.0.1", PUERTO_AFUERA' in fuente
assert "iniciar_puerta_afuera()" in fuente.split('if __name__ == "__main__":')[1]
ok("la puerta de afuera escucha SOLO en este PC y arranca con el servidor")
con.close()

print("\nTODAS LAS PRUEBAS PASARON")
