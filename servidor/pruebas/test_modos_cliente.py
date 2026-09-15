# -*- coding: utf-8 -*-
"""Un solo programa para los tres tipos de PC: mostrador, principal y vendedor."""
import sys

from _comun import ruta  # noqa: E402  (deja el programa a mano)
import cliente

ok = lambda m: print("[OK] " + m)


def modo_con(args):
    """Lo que haría main() con esos argumentos, sin abrir ventana."""
    cliente.MODO = "cliente"
    viejo, sys.argv = sys.argv, ["InventarioRFID-Cliente.exe"] + args
    try:
        if "--vendedor" in sys.argv:
            cliente.MODO = "vendedor"
        elif "--principal" in sys.argv and cliente.MODO != "vendedor":
            cliente.MODO = "principal"
        return cliente.MODO, cliente.pagina()
    finally:
        sys.argv = viejo


# --- el modo sale del argumento del acceso directo ---
m, pag = modo_con([])
assert m == "cliente" and "/escritorio" in pag and "modo=" not in pag
assert "#E87722" in pag, "mostrador = naranja"
ok("sin argumentos: PC de MOSTRADOR (naranja), entra a /escritorio")

m, pag = modo_con(["--principal"])
assert m == "principal" and "/escritorio?modo=principal" in pag
assert "#C62828" in pag, "principal = rojo"
ok("con --principal: PC PRINCIPAL (rojo), entra con ⚙ Configuración")

m, pag = modo_con(["--vendedor"])
assert m == "vendedor" and "/escritorio?modo=vendedor" in pag
assert "#1F7A44" in pag, "vendedor = verde"
ok("con --vendedor: PC de VENDEDOR (verde), solo consulta")

# --- si vinieran los dos, manda vendedor (el más restringido) ---
m, _ = modo_con(["--principal", "--vendedor"])
assert m == "vendedor"
ok("si por error llegan los dos, gana el más restringido (vendedor)")

# --- comprobación real del codigo, no de mi imitación ---
fuente = open(ruta("cliente.py"),
              encoding="utf-8").read()
assert '"--vendedor" in sys.argv' in fuente
assert 'MODO = "vendedor"' in fuente.split("def main()")[1]
ok("main() reconoce de verdad --vendedor (no solo mi imitación)")

# --- el instalador nuevo pasa esos mismos argumentos ---
iss = open(ruta("instalador_inventario.iss"),
           encoding="utf-8").read()
assert "--principal" in iss and "--vendedor" in iss
assert "CreateInputOptionPage" in iss and iss.count("PaginaModo.Add") == 3
assert "LimpiarAtajosDeOtrosModos" in iss
assert "Instalar-InventarioRFID-PCs" in iss
ok("el instalador de los PCs ofrece los 3 tipos y pasa el argumento correcto")

# --- el del servidor limpia el arranque que sobra (la ventana de 0.5) ---
srv = open(ruta("instalador.iss"),
           encoding="utf-8").read()
assert "procedure LimpiarArranques" in srv
assert "ssPostInstall" in srv and "LimpiarArranques();" in srv
assert "Servidor Inventario RFID.lnk" in srv
assert "schtasks" in srv.split("procedure LimpiarArranques")[1][:900]
ok("el instalador del servidor borra el acceso de inicio que abría la ventana")

# --- ya no empaqueta los dos instaladores viejos ---
assert "Instalar-InventarioRFID-OtrosPCs.exe" not in srv
assert "Instalar-InventarioRFID-Vendedores.exe" not in srv
assert "Instalar-InventarioRFID-PCs.exe" in srv
ok("el del servidor lleva dentro el instalador nuevo, no los dos viejos")

print("\nTODAS LAS PRUEBAS PASARON")
