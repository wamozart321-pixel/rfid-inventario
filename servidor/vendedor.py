# -*- coding: utf-8 -*-
"""Inventario RFID — app de CONSULTA para los VENDEDORES.

Es la misma app de los otros PCs (cliente.py) pero en modo vendedor:
ventana verde oscuro y SOLO consulta — el servidor le oculta las opciones
de modificar, eliminar, imprimir e inventarios. Sirve para buscar un
repuesto y ver su información (precios, bodegas, foto, referencias)."""
import cliente

cliente.MODO = "vendedor"

if __name__ == "__main__":
    cliente.main()
