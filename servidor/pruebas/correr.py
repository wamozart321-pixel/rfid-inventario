# -*- coding: utf-8 -*-
"""Corre TODAS las pruebas y dice cuáles pasan.

    python correr.py              todas
    python correr.py balizas      solo las que lleven «balizas» en el nombre

Cada prueba se lanza aparte, así una que reviente no tumba a las demás.
"""
import os
import subprocess
import sys

PRUEBAS = os.path.dirname(os.path.abspath(__file__))


def main():
    filtro = sys.argv[1].lower() if len(sys.argv) > 1 else ""
    archivos = sorted(n for n in os.listdir(PRUEBAS)
                      if n.startswith("test_") and n.endswith(".py")
                      and filtro in n.lower())
    if not archivos:
        print("No hay ninguna prueba que coincida con «%s»" % filtro)
        return 1

    entorno = dict(os.environ, PYTHONIOENCODING="utf-8")
    bien, mal = [], []
    for n in archivos:
        r = subprocess.run([sys.executable, os.path.join(PRUEBAS, n)],
                           capture_output=True, text=True, encoding="utf-8",
                           errors="replace", env=entorno)
        if r.returncode == 0:
            bien.append(n)
            print("  OK    %s" % n)
        else:
            salida = (r.stdout or "") + (r.stderr or "")
            ultima = [l for l in salida.splitlines() if l.strip()][-1:] or [""]
            mal.append((n, ultima[0].strip()[:110]))
            print("  FALLA %s" % n)

    print("\n%d de %d pruebas pasan" % (len(bien), len(archivos)))
    if mal:
        print("\nFallan:")
        for n, motivo in mal:
            print("  %-34s %s" % (n, motivo))
        print("\nPara ver el detalle de una:  python %s" % mal[0][0])
    return 1 if mal else 0


if __name__ == "__main__":
    sys.exit(main())
