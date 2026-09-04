# -*- coding: utf-8 -*-
"""
Sistema de Inventario RFID — servidor web + API
Chainway C72 (y otros lectores) · Zebra ZT411/ZT411R (ZPL por red)

Requisitos:  pip install flask
Ejecutar:    python app.py
Abrir:       http://localhost:5000   (desde la pistola: http://IP-DEL-PC:5000)
"""
import json, os, re, socket, sqlite3, csv, io, sys, secrets, subprocess, time, shutil, threading
from datetime import datetime, timedelta
from flask import (Flask, g, request, redirect, url_for, render_template,
                   jsonify, Response)

if getattr(sys, "frozen", False):
    # Empaquetado como .exe (PyInstaller): templates/static van dentro del exe;
    # la base de datos y la configuración viven junto al .exe para no perderse.
    RECURSOS = sys._MEIPASS
    BASE = os.path.dirname(os.path.abspath(sys.executable))
else:
    RECURSOS = BASE = os.path.dirname(os.path.abspath(__file__))
DB = os.path.join(BASE, "inventario.db")
CFG = os.path.join(BASE, "config.json")

DEFAULT_CFG = {
    "impresora_ip": "192.168.1.100",
    "impresora_puerto": 9100,
    "dpi": 300,
    "etiqueta_ancho_mm": 100,
    "etiqueta_alto_mm": 50,
    "codificar_rfid": False,   # True solo si la ZT411 tiene módulo RFID (ZT411R)
    "oscuridad": 27,           # 0-30: qué tan marcado imprime (bajo = borroso)
    "velocidad": 3,            # 2-7 pulgadas/seg: lento = mejor calidad
    # tipo de papel: "" = como esté la impresora · gap = etiquetas troqueladas
    # con separación · marca = marca negra · continuo = papel continuo
    "papel_tipo": "",
    "zebra_impresora_win": "",   # nombre en Windows (para el botón Avanzado)
    # Cómo se le manda a la Zebra: "red" = directo a su IP (puerto 9100) ·
    # "windows" = a la impresora instalada en Windows (sirve por USB y por red,
    # y así no hay que perseguir la IP cuando el router se la cambia).
    "zebra_salida": "red",
    "nombre_empresa": "MI EMPRESA",
    # Integración BarTender: imprime con el diseño .btw original en vez del ZPL propio
    "bartender": False,
    "bartender_exe": r"C:\Program Files\Seagull\BarTender 2022\bartend.exe",
    "bartender_plantilla": "",   # ruta al .btw conectado a bt_datos.csv
    "bartender_impresora": "",   # impresora de Windows (vacío = la guardada en el diseño)
    "diseno": {},                # ajustes del editor de diseño de etiqueta
    # Impresora SAT (etiquetas blancas de DESCRIPCIÓN, sin chip): también por
    # red. Se le manda la etiqueta como imagen, en su lenguaje (TSPL) o en ZPL.
    "sat_ip": "",
    "sat_puerto": 9100,
    "sat_dpi": 203,              # casi todas las SAT/TSC son de 203 dpi
    "sat_ancho_mm": 50,
    "sat_alto_mm": 40,
    "sat_gap_mm": 3,             # separación entre etiquetas del rollo
    "sat_lenguaje": "tspl",      # tspl = SAT/TSC (lo normal) · zpl = modo Zebra
    "sat_oscuridad": 12,         # 0-15
    "sat_papel_tipo": "",        # "" / gap / marca / continuo
    "sat_impresora_win": "",     # nombre en Windows (para el botón Avanzado)
    "sat_salida": "red",         # "red" (IP) o "windows" (USB o driver instalado)
    # SEMÁFORO DE ROTACIÓN: unidades VENDIDAS en los últimos N días.
    #   verde  = alta rotación (se vende mucho)
    #   ámbar  = media
    #   rojo   = baja (poco o nada; revisar promociones o redistribución)
    "rotacion_dias": 180,
    "rotacion_alta": 10,         # desde estas unidades vendidas -> ALTA
    "rotacion_media": 3,         # desde estas -> MEDIA (por debajo, BAJA)
    "sat_doble": False,          # rollo de DOS etiquetas lado a lado (mismo ancho c/u)
    "sat_sep_mm": 4,             # separación horizontal entre las dos etiquetas
    "sat_lado": "izquierda",     # cuál de las dos usar: izquierda / derecha
    # Copia de seguridad automática de la base de datos cada día a una hora
    # Actualizaciones: el programa se pone al dia solo cuando se publica
    # una version nueva (nadie tiene que reinstalar nada a mano).
    "actualizar_revisar": True,   # mirar cada pocas horas si hay version nueva
    "actualizar_auto": True,      # ademas de mirar, instalarla sola
    "actualizar_repo": "",        # vacio = el repositorio de siempre
    "respaldo_activo": True,
    "respaldo_hora": "05:20",    # HH:MM (24h)
    "respaldo_carpeta": "",      # vacío = carpeta 'respaldos' junto al programa
    "respaldo_dias": 30,         # cuántas copias diarias conservar
    # % que se le resta al precio de venta para estimar el COSTO (valorización)
    "costo_descuento": 48,
    "diseno_desc": {},           # diseño de la etiqueta de descripción
    # carpeta (local o de red) con las fotos de los productos, nombradas por
    # la referencia (SKU) o por el nombre del producto
    "fotos_ruta": r"\\WIN-I56F313Q7LR\imagenes repuestos"
}

app = Flask(__name__,
            template_folder=os.path.join(RECURSOS, "templates"),
            static_folder=os.path.join(RECURSOS, "static"))

# ---------------------------------------------------------------- utilidades
def cfg():
    if not os.path.exists(CFG):
        with open(CFG, "w", encoding="utf-8") as f:
            json.dump(DEFAULT_CFG, f, indent=2, ensure_ascii=False)
    with open(CFG, encoding="utf-8") as f:
        c = DEFAULT_CFG.copy(); c.update(json.load(f)); return c

def db():
    if "db" not in g:
        g.db = sqlite3.connect(DB)
        g.db.row_factory = sqlite3.Row
    return g.db

@app.teardown_appcontext
def close_db(e=None):
    d = g.pop("db", None)
    if d: d.close()

def init_db():
    con = sqlite3.connect(DB)
    con.executescript("""
    CREATE TABLE IF NOT EXISTS productos(
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        sku TEXT UNIQUE NOT NULL,
        nombre TEXT NOT NULL,
        ubicacion TEXT DEFAULT '',
        cantidad_esperada INTEGER DEFAULT 0);
    CREATE TABLE IF NOT EXISTS tags(
        epc TEXT PRIMARY KEY,
        producto_id INTEGER REFERENCES productos(id) ON DELETE CASCADE,
        creado TEXT);
    CREATE TABLE IF NOT EXISTS sesiones(
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        nombre TEXT, estado TEXT DEFAULT 'abierta', creada TEXT);
    CREATE TABLE IF NOT EXISTS sesion_productos(
        sesion_id INTEGER, producto_id INTEGER,
        PRIMARY KEY(sesion_id, producto_id));
    CREATE TABLE IF NOT EXISTS salidas(
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        producto_id INTEGER,
        cantidad INTEGER,
        origen TEXT DEFAULT '',
        es_venta INTEGER DEFAULT 1,
        ts TEXT);
    CREATE INDEX IF NOT EXISTS idx_salidas_ts ON salidas(ts);
    CREATE TABLE IF NOT EXISTS lecturas(
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        sesion_id INTEGER REFERENCES sesiones(id),
        epc TEXT, dispositivo TEXT, ts TEXT,
        UNIQUE(sesion_id, epc));
    CREATE TABLE IF NOT EXISTS proveedores(
        codigo INTEGER PRIMARY KEY,
        nombre TEXT NOT NULL);
    CREATE TABLE IF NOT EXISTS stock_bodegas(
        producto_id INTEGER NOT NULL REFERENCES productos(id) ON DELETE CASCADE,
        bodega TEXT NOT NULL,
        cantidad INTEGER DEFAULT 0,
        posicion TEXT DEFAULT '',
        PRIMARY KEY(producto_id, bodega));
    -- BALIZAS: etiquetas fijas pegadas al estante que dicen DÓNDE está la
    -- pistola. Al leer una, todo lo que venga después se apunta en ese sitio.
    CREATE TABLE IF NOT EXISTS balizas(
        epc TEXT PRIMARY KEY,
        bodega TEXT NOT NULL DEFAULT '',
        posicion TEXT NOT NULL DEFAULT '',
        nota TEXT DEFAULT '',
        creada TEXT);
    -- Cuántas VECES se vio cada producto en cada sitio. Se cuenta repetido a
    -- propósito: el sitio con más lecturas gana, y así el eco del pasillo de
    -- al lado (que se lee pocas veces) no manda sobre el estante de verdad.
    CREATE TABLE IF NOT EXISTS detecciones_pos(
        sesion_id INTEGER,
        epc TEXT,
        bodega TEXT,
        posicion TEXT,
        veces INTEGER DEFAULT 0,
        ultima TEXT,
        PRIMARY KEY(sesion_id, epc, bodega, posicion));
    CREATE INDEX IF NOT EXISTS idx_detpos_ses ON detecciones_pos(sesion_id);
    -- Dónde está ahora mismo cada pistola (la última baliza que leyó).
    CREATE TABLE IF NOT EXISTS dispositivo_pos(
        dispositivo TEXT PRIMARY KEY,
        bodega TEXT DEFAULT '',
        posicion TEXT DEFAULT '',
        epc_baliza TEXT DEFAULT '',
        ts TEXT);
    """)
    try:
        # posición dentro de la bodega (estante/casilla: A1, F6, CJ4…)
        con.execute("ALTER TABLE stock_bodegas ADD COLUMN posicion TEXT DEFAULT ''")
    except sqlite3.OperationalError:
        pass
    try:
        con.execute("ALTER TABLE productos ADD COLUMN oem TEXT DEFAULT ''")
    except sqlite3.OperationalError:
        pass   # la columna ya existe
    try:
        con.execute("ALTER TABLE sesiones ADD COLUMN tipo TEXT DEFAULT 'verificacion'")
    except sqlite3.OperationalError:
        pass
    try:
        con.execute("ALTER TABLE sesiones ADD COLUMN bodega TEXT DEFAULT ''")
    except sqlite3.OperationalError:
        pass
    try:
        # bases de antes de la pregunta venta/ajuste: sus salidas eran ventas
        con.execute("ALTER TABLE salidas ADD COLUMN es_venta INTEGER DEFAULT 1")
    except sqlite3.OperationalError:
        pass
    for col in ("precio_minimo INTEGER DEFAULT 0", "precio INTEGER DEFAULT 0",
                "codigo_barras TEXT DEFAULT ''", "proveedor INTEGER DEFAULT 0",
                "foto TEXT DEFAULT ''", "referencias TEXT DEFAULT ''",
                # rotación puesta A MANO ('' = automática, según las ventas)
                "rotacion_manual TEXT DEFAULT ''"):
        try:
            con.execute(f"ALTER TABLE productos ADD COLUMN {col}")
        except sqlite3.OperationalError:
            pass
    con.commit(); con.close()

def generar_codigo_barras(pid, precio_minimo, precio, proveedor=0):
    """Código EAN-13 al estilo FactuSOL: [proveedor][ceros][precio mín] ‖ [precio normal][relleno].
      · el código EMPIEZA con el código del PROVEEDOR (ej. la bobina
        300026027001: 30 = Innovateq); sin proveedor se usa "2" (código
        interno de tienda) porque un cero inicial el escáner "se lo come"
      · el precio MÍNIMO (÷1.000) termina JUSTO en las guías del centro,
        con ceros entre el proveedor y él (como el 3000·26 del usuario)
      · el precio NORMAL (÷100) empieza INMEDIATAMENTE después de las guías;
        lo que sobre a la derecha se rellena con el número del producto
    Ej. proveedor 30, $26.000 mín, $27.000 normal -> 3000026 | 270xx
        se lee:  ...26 || 270...  (26 = $26.000 · 270 = $27.000)."""
    if not (precio_minimo or precio):
        return ""
    m = str(int(precio_minimo) // 1000) if precio_minimo else "0"
    n = str(int(precio) // 100) if precio else "0"
    m, n = m[-6:], n[:5]
    try:
        prov = str(int(proveedor)) if int(proveedor or 0) > 0 else ""
    except (TypeError, ValueError):
        prov = ""
    if prov:
        # proveedor + ceros + mínimo = 7 dígitos (el 1º + grupo izquierdo);
        # si no caben, el mínimo pierde dígitos de la izquierda (caso extremo)
        m = m[-(7 - len(prov)):] if len(prov) < 7 else ""
        izq = prov + "0" * (7 - len(prov) - len(m)) + m
    else:
        izq_rell = str(pid).zfill(6)
        izq = "2" + (izq_rell[-(6 - len(m)):] if len(m) < 6 else "") + m
    # a la derecha el sobrante se rellena con el nº de producto (no con ceros,
    # para que no parezca parte del precio; como el "950126" del usuario)
    der = (n + str(pid) * 5)[:5]
    return (izq + der)[-12:]   # 12 dígitos; la impresora agrega el control

def producto_por_codigo(d, codigo):
    """Busca un producto por referencia (SKU) o por el código de barras
    generado. El escáner entrega el EAN-13 completo (13 dígitos con el de
    control); en la base se guardan 12, así que también se prueba sin él."""
    cod = str(codigo or "").strip()
    if not cod:
        return None
    p = d.execute("SELECT * FROM productos WHERE sku=? COLLATE NOCASE", (cod,)).fetchone()
    if p:
        return p
    candidatos = [cod]
    if cod.isdigit():
        if len(cod) == 13:
            candidatos.append(cod[:12])          # EAN completo: quita el control
        if len(cod) == 12:
            # el escáner se comió el 0 inicial (lo leyó como UPC-A):
            # se repone el 0 y se quita el dígito de control
            candidatos.append("0" + cod[:11])
        if len(cod) == 11:
            candidatos.append("0" + cod)         # sin 0 inicial y sin control
    for cand in candidatos:
        p = d.execute("SELECT * FROM productos WHERE codigo_barras=?", (cand,)).fetchone()
        if p:
            return p
    return None

def sesion_activa(d):
    return d.execute("SELECT * FROM sesiones WHERE estado='abierta' ORDER BY id DESC LIMIT 1").fetchone()

def crear_sesion(d, nombre=None, tipo="verificacion", bodega="", productos=None):
    """productos = lista de ids para contar SOLO esos; vacía/None = todos."""
    bodega = str(bodega or "").strip().upper()
    auto = datetime.now().strftime(f"Conteo {bodega + ' ' if bodega else ''}%Y-%m-%d %H:%M")
    cur = d.execute("INSERT INTO sesiones(nombre,creada,tipo,bodega) VALUES(?,?,?,?)",
                    (nombre or auto, datetime.now().isoformat(), tipo, bodega))
    sid = cur.lastrowid
    for pid in productos or []:
        try:
            d.execute("INSERT OR IGNORE INTO sesion_productos(sesion_id,producto_id) "
                      "VALUES(?,?)", (sid, int(pid)))
        except (TypeError, ValueError):
            pass
    d.commit()
    return sesion_activa(d)

def seleccion_sesion(d, sid):
    """Ids de los productos elegidos para la sesión ([] = se cuentan todos)."""
    return [r["producto_id"] for r in d.execute(
        "SELECT producto_id FROM sesion_productos WHERE sesion_id=?", (sid,))]

def resumen_sesion(d, sid):
    s = d.execute("SELECT * FROM sesiones WHERE id=?", (sid,)).fetchone()
    bod = (s["bodega"] if s and "bodega" in s.keys() else "") or ""
    # sesión de SOLO ciertos productos: el resumen se limita a esos
    sel = seleccion_sesion(d, sid)
    filtro = f" WHERE p.id IN ({','.join('?' * len(sel))})" if sel else ""
    if bod:
        # sesión de UNA bodega: lo esperado es el stock de ESA bodega
        filas = d.execute(f"""
            SELECT p.sku, p.nombre, p.ubicacion, IFNULL(p.codigo_barras,'') codigo_barras,
                   IFNULL(sb.cantidad, 0) cantidad_esperada,
                   COUNT(DISTINCT l.epc) leidos
            FROM productos p
            LEFT JOIN stock_bodegas sb ON sb.producto_id = p.id AND sb.bodega = ?
            LEFT JOIN tags t ON t.producto_id = p.id
            LEFT JOIN lecturas l ON l.epc = t.epc AND l.sesion_id = ?
            {filtro}
            GROUP BY p.id ORDER BY p.nombre""", (bod, sid, *sel)).fetchall()
    else:
        filas = d.execute(f"""
            SELECT p.sku, p.nombre, p.ubicacion, IFNULL(p.codigo_barras,'') codigo_barras,
                   p.cantidad_esperada,
                   COUNT(DISTINCT l.epc) leidos
            FROM productos p
            LEFT JOIN tags t ON t.producto_id = p.id
            LEFT JOIN lecturas l ON l.epc = t.epc AND l.sesion_id = ?
            {filtro}
            GROUP BY p.id ORDER BY p.nombre""", (sid, *sel)).fetchall()
    desconocidos = d.execute("""SELECT l.epc, l.dispositivo, l.ts FROM lecturas l
        WHERE l.sesion_id=? AND l.epc NOT IN (SELECT epc FROM tags)
        ORDER BY l.ts DESC""", (sid,)).fetchall()
    filas = [dict(r) for r in filas]
    for r in filas:
        cb = r["codigo_barras"]
        # buscar también por el EAN-13 COMPLETO (con el dígito de control que
        # trae la etiqueta impresa; en la base solo se guardan los 12 sin él)
        r["codigo_barras_ean"] = ean13_control(cb) if len(cb) == 12 and cb.isdigit() else ""
    return filas, desconocidos

# ---------------------------------------------------------------- impresión ZPL
def mm_a_dots(mm, dpi): return int(mm / 25.4 * dpi)

# Diseño editable de la etiqueta: cada elemento con visible (on), posición en
# porcentaje del ancho/alto (x, y) y tamaño (s = fuente en el diseño base
# 100x50 mm; se escala solo). Estos valores por defecto replican el diseño
# BarTender original del usuario; lo que se cambie en el editor del escritorio
# se guarda en config.json bajo "diseno" y aquí solo se pisa lo modificado.
DISENO_DEFAULT = {
    # borde apagado: la etiqueta física ya viene troquelada con esquinas
    # redondeadas, no hace falta imprimirle un marco
    "borde":     {"on": False},
    # lineas 0 = automático: el nombre usa las líneas que necesite (hasta 4)
    "oem":       {"on": True, "x": 0.0,  "y": 2.7,  "ancho": 100.0, "s": 34, "alin": "C"},
    "raya1":     {"on": True, "x": 2.5,  "y": 10.5, "ancho": 95.0},
    "nombre":    {"on": True, "x": 0.0,  "y": 14.2, "ancho": 100.0, "s": 74, "lineas": 0, "alin": "C"},
    "raya2":     {"on": True, "x": 2.5,  "y": 36.0, "ancho": 95.0},
    # x deja sitio a la izquierda para el primer dígito del EAN-13
    "codigo":    {"on": True, "x": 6.0,  "y": 40.5, "alto": 36},
    # referencia pequeña justo ENCIMA de la foto (franja derecha)
    "sku":       {"on": True, "x": 60.0, "y": 36.6, "ancho": 37.0, "s": 20, "alin": "C"},
    # foto del producto en la franja derecha (solo si existe en la carpeta)
    "foto":      {"on": True, "x": 60.0, "y": 40.0, "ancho": 37.0, "alto": 44.0},
    "precio":    {"on": False, "x": 62.0, "y": 46.0, "s": 46},
    "ubicacion": {"on": True, "x": 87.0, "y": 80.0, "s": 22},
    "web":       {"on": True, "x": 0.0,  "y": 91.0, "ancho": 100.0, "s": 58, "alin": "C"},
    "epc":       {"on": True, "x": 0.8,  "y": 1.2,  "s": 18},
    "texto1":    {"on": False, "x": 5.0, "y": 55.0, "s": 30, "texto": "TEXTO LIBRE 1"},
    "texto2":    {"on": False, "x": 5.0, "y": 64.0, "s": 30, "texto": "TEXTO LIBRE 2"},
    "recuadro":  {"on": False, "x": 55.0, "y": 42.0, "ancho": 40.0, "alto": 28.0, "grosor": 2},
}

# Etiqueta de DESCRIPCIÓN (impresora SAT, sin chip): replica la etiqueta blanca
# de las cajas — referencia pequeña arriba, descripción grande en negrita y la
# franja negra con la página web abajo (inv = letras blancas sobre negro).
DISENO_DESC_DEFAULT = {
    "borde":     {"on": False},
    "sku":       {"on": True,  "x": 0.0,  "y": 2.5,  "ancho": 100.0, "s": 42, "alin": "C"},
    "nombre":    {"on": True,  "x": 3.0,  "y": 15.0, "ancho": 94.0,  "s": 110, "lineas": 0,
                  "alin": "L", "fuente": "arial", "negrita": True},
    "oem":       {"on": False, "x": 3.0,  "y": 72.0, "ancho": 94.0,  "s": 40, "alin": "L"},
    "precio":    {"on": False, "x": 66.0, "y": 2.5,  "s": 46},
    "ubicacion": {"on": False, "x": 3.0,  "y": 80.0, "s": 36},
    "web":       {"on": True,  "x": 0.0,  "y": 88.0, "ancho": 100.0, "s": 54, "alin": "C",
                  "fuente": "arial", "negrita": True, "inv": True},
    # código de barras (apagado por defecto): la SAT también puede imprimirlo
    "codigo":    {"on": False, "x": 6.0,  "y": 52.0, "alto": 26},
    "texto1":    {"on": False, "x": 5.0,  "y": 55.0, "s": 40, "texto": "TEXTO LIBRE 1"},
    "texto2":    {"on": False, "x": 5.0,  "y": 64.0, "s": 40, "texto": "TEXTO LIBRE 2"},
    "recuadro":  {"on": False, "x": 55.0, "y": 42.0, "ancho": 40.0, "alto": 28.0, "grosor": 2},
}

def ean13_control(d12):
    """Agrega el dígito 13 de control a los 12 dígitos del EAN."""
    s = sum(int(ch) * (3 if i % 2 else 1) for i, ch in enumerate(d12))
    return d12 + str((10 - s % 10) % 10)

# ---- código de barras como imagen 1-bit (para imprimir en la SAT) ----
_EAN_L = {"0": "0001101", "1": "0011001", "2": "0010011", "3": "0111101",
          "4": "0100011", "5": "0110001", "6": "0101111", "7": "0111011",
          "8": "0110111", "9": "0001011"}
_EAN_PAR = {"0": "LLLLLL", "1": "LLGLGG", "2": "LLGGLG", "3": "LLGGGL",
            "4": "LGLLGG", "5": "LGGLLG", "6": "LGGGLL", "7": "LGLGLG",
            "8": "LGLGGL", "9": "LGGLGL"}
_EAN_G = {k: "".join("1" if b == "0" else "0" for b in v[::-1]) for k, v in _EAN_L.items()}
# patrones Code128 (valores 0-106) como anchos de barra/espacio
_C128_W = ("212222 222122 222221 121223 121322 131222 122213 122312 132212 221213 "
           "221312 231212 112232 122132 122231 113222 123122 123221 223211 221132 "
           "221231 213212 223112 312131 311222 321122 321221 312212 322112 322211 "
           "212123 212321 232121 111323 131123 131321 112313 132113 132311 211313 "
           "231113 231311 112133 112331 132131 113123 113321 133121 313121 211331 "
           "231131 213113 213311 213131 311123 311321 331121 312113 312311 332111 "
           "314111 221411 431111 111224 111422 121124 121421 141122 141221 112214 "
           "112412 122114 122411 142112 142211 241211 221114 413111 241112 134111 "
           "111242 121142 121241 114212 124112 124211 411212 421112 421211 212141 "
           "214121 412121 111143 111341 131141 114113 114311 411113 411311 113141 "
           "114131 311141 411131 211412 211214 211232 2331112").split()

def _anchos_a_bits(w6):
    bits, uno = "", True
    for ch in w6:
        bits += ("1" if uno else "0") * int(ch)
        uno = not uno
    return bits

def _ean13_bits(dato):
    # el dígito de control SIEMPRE se recalcula: así la imagen y lo que manda
    # la Zebra (^BE con 12 dígitos) codifican exactamente lo mismo, aunque el
    # código venga con un 13º dígito equivocado
    d = ean13_control(dato[:12])
    par = _EAN_PAR[d[0]]
    bits = "101"
    for i in range(6):
        bits += (_EAN_L if par[i] == "L" else _EAN_G)[d[i + 1]]
    bits += "01010"
    for i in range(6):
        bits += "".join("1" if x == "0" else "0" for x in _EAN_L[d[7 + i]])
    return bits + "101", d

def _c128b_bits(texto):
    texto = "".join(ch for ch in texto if 32 <= ord(ch) < 127) or "0"
    vals = [104] + [ord(ch) - 32 for ch in texto]      # Start B + datos
    chk = (vals[0] + sum(i * v for i, v in enumerate(vals[1:], 1))) % 103
    vals += [chk, 106]                                 # control + Stop
    return "".join(_anchos_a_bits(_C128_W[v]) for v in vals)

def _fuente_num_pil(px, clave="arial"):
    try:
        from PIL import ImageFont
        base = os.path.join(os.environ.get("WINDIR", r"C:\Windows"), "Fonts")
        ruta = os.path.join(base, FUENTES_WIN.get(clave, "arial.ttf"))
        if not os.path.exists(ruta):
            ruta = os.path.join(base, "arial.ttf")
        return ImageFont.truetype(ruta, max(8, int(px)))
    except Exception:
        return None

def dibujar_codigo_img(img, dib, e, dato, w, h, ft):
    """Dibuja el código de barras del elemento 'codigo' sobre la etiqueta SAT,
    igual que en la Zebra: EAN-13 (números 6+6, primer dígito afuera) o, si el
    dato no es EAN, Code128 con el texto debajo. dato numérico de 12/13 = EAN."""
    dato = str(dato)
    es_ean = dato.isdigit() and len(dato) in (12, 13)
    x0 = int(w * float(e.get("x", 6)) / 100)
    y0 = int(h * float(e.get("y", 40)) / 100)
    alto_bc = max(20, int(h * float(e.get("alto", 30)) / 100))
    con_num = e.get("numeros") is not False
    ajuste = {"fino": -1, "grueso": 1}.get(e.get("barras", ""), 0)
    num_s = float(e.get("num_s") or 0)
    dig = max(10, int(num_s * ft)) if num_s > 0 else \
        max(10, int(float(e.get("alto", 30)) * 1.4 * ft))
    fn = str(e.get("fuente_num", "arial"))
    fnt = _fuente_num_pil(dig, fn if fn in FUENTES_WIN else "arial")

    def num(txt, cx0, cy, ancho_max):
        if not fnt:
            return
        try:
            bb = dib.textbbox((0, 0), txt, font=fnt)
            tw = bb[2] - bb[0]
        except Exception:
            tw, bb = len(txt) * dig // 2, (0, 0, 0, 0)
        dib.text((max(0, cx0 + (ancho_max - tw) // 2 - bb[0]), cy), txt, fill=1, font=fnt)

    if es_ean:
        mod = max(2, min(7, int(w * 0.5 / 95) + ajuste))
        bits, d13 = _ean13_bits(dato)
        for i, b in enumerate(bits):
            if b == "1":
                guia = i < 3 or 45 <= i < 50 or i >= 92
                extra = int(dig * 0.55) if (guia and con_num) else 0
                dib.rectangle([x0 + i * mod, y0, x0 + i * mod + mod - 1,
                               y0 + alto_bc - 1 + extra], fill=1)
        if con_num:
            yb = y0 + alto_bc + 2
            num(d13[1:7], x0 + 3 * mod, yb, 43 * mod)
            num(d13[7:13], x0 + 49 * mod, yb, 43 * mod)
            num(d13[0], max(0, x0 - dig - mod), yb, dig)
    else:
        mod = max(2, min(6, (2 if w < 700 else 3) + ajuste))
        bits = _c128b_bits(dato)
        for i, b in enumerate(bits):
            if b == "1":
                dib.rectangle([x0 + i * mod, y0, x0 + i * mod + mod - 1,
                               y0 + alto_bc - 1], fill=1)
        if con_num:
            num(dato, x0, y0 + alto_bc + 2, len(bits) * mod)

FUENTES_WIN = {
    "arial": "arial.ttf", "arialbd": "arialbd.ttf", "arialn": "ARIALN.TTF",
    "consolas": "consola.ttf", "ocr": "OCRAEXT.TTF", "segoe": "segoeui.ttf",
}

# Fuentes para los TEXTOS de la etiqueta: (normal, negrita, cursiva, negrita+cursiva)
FUENTES_TXT = {
    "arial":    ("arial.ttf", "arialbd.ttf", "ariali.ttf", "arialbi.ttf"),
    "arialn":   ("ARIALN.TTF", "ARIALNB.TTF", "ARIALNI.TTF", "ARIALNBI.TTF"),
    "times":    ("times.ttf", "timesbd.ttf", "timesi.ttf", "timesbi.ttf"),
    "verdana":  ("verdana.ttf", "verdanab.ttf", "verdanai.ttf", "verdanaz.ttf"),
    "georgia":  ("georgia.ttf", "georgiab.ttf", "georgiai.ttf", "georgiaz.ttf"),
    "segoe":    ("segoeui.ttf", "segoeuib.ttf", "segoeuii.ttf", "segoeuiz.ttf"),
    "consolas": ("consola.ttf", "consolab.ttf", "consolai.ttf", "consolaz.ttf"),
    "courier":  ("cour.ttf", "courbd.ttf", "couri.ttf", "courbi.ttf"),
    "impact":   ("impact.ttf",) * 4,
    "ocr":      ("OCRAEXT.TTF",) * 4,
}

def _gfa(img):
    """Imagen Pillow modo '1' -> comando ^GFA. Devuelve (comando, ancho, alto)."""
    wpx, hpx = img.size
    bpr = (wpx + 7) // 8
    hexd = img.tobytes().hex().upper()
    total = bpr * hpx
    return (f"^GFA,{total},{total},{bpr},{hexd}", wpx, hpx)

def img_bloque(texto, alto, clave, negrita=False, cursiva=False, fac=1.0,
               ancho_max=None, max_lineas=1, alin="C", gap=4):
    """Texto con fuente REAL de Windows como imagen 1-bit (1 = tinta): admite
    negrita/cursiva, factor de ancho (letra estrecha/ancha) y, con ancho_max,
    parte en líneas y alinea como ^FB. Devuelve (imagen, dx, dy) recortada al
    contenido, o None. Es la base de gf_bloque (Zebra) y de la etiqueta SAT."""
    try:
        from PIL import Image, ImageDraw, ImageFont
    except ImportError:
        return None
    arch = FUENTES_TXT.get(clave)
    texto = str(texto or "").strip()
    if not arch or not texto:
        return None
    base = os.path.join(os.environ.get("WINDIR", r"C:\Windows"), "Fonts")
    ruta = os.path.join(base, arch[(1 if negrita else 0) + (2 if cursiva else 0)])
    if not os.path.exists(ruta):
        ruta = os.path.join(base, arch[0])
        if not os.path.exists(ruta):
            return None
    try:
        fnt = ImageFont.truetype(ruta, max(8, int(alto)))
    except OSError:
        return None
    fac = max(0.3, min(3.0, float(fac or 1.0)))
    med = ImageDraw.Draw(Image.new("1", (1, 1)))
    ancho_de = lambda t: med.textlength(t, font=fnt) * fac
    if ancho_max:
        # partir por palabras al estilo ^FB (lo que no cabe se corta)
        lineas, actual = [], ""
        for pal in texto.split():
            prueba = (actual + " " + pal).strip()
            if actual and ancho_de(prueba) > ancho_max:
                lineas.append(actual)
                actual = pal
                if len(lineas) >= max_lineas:
                    actual = ""
                    break
            else:
                actual = prueba
        if actual and len(lineas) < max_lineas:
            lineas.append(actual)
        W = int(ancho_max)
    else:
        lineas = [texto]
        # margen extra a la derecha: la cursiva sobresale de lo medido
        W = max(1, int(ancho_de(texto) + (alto * 0.25 if cursiva else 0)))
    if not lineas:
        return None
    alto_lin = max(8, int(alto))
    H = alto_lin * len(lineas) + gap * (len(lineas) - 1)
    W0 = max(1, int(W / fac))
    img = Image.new("1", (W0, H), 0)
    dib = ImageDraw.Draw(img)
    for i, lin in enumerate(lineas):
        wl = med.textlength(lin, font=fnt)
        x = 0 if alin == "L" else (W0 - wl if alin == "R" else (W0 - wl) / 2)
        dib.text((max(0, int(x)), i * (alto_lin + gap)), lin, fill=1, font=fnt)
    if fac != 1.0:
        img = img.resize((max(1, W), H))
    bb = img.getbbox()
    if not bb:
        return None
    return (img.crop(bb), bb[0], bb[1])   # recorte: solo la tinta

def gf_bloque(texto, alto, clave, negrita=False, cursiva=False, fac=1.0,
              ancho_max=None, max_lineas=1, alin="C", gap=4):
    """img_bloque convertido a gráfico ZPL para la Zebra.
    Devuelve (^GFA, ancho, alto, dx, dy) o None."""
    r = img_bloque(texto, alto, clave, negrita, cursiva, fac,
                   ancho_max, max_lineas, alin, gap)
    if not r:
        return None
    cmd, wpx, hpx = _gfa(r[0])
    return (cmd, wpx, hpx, r[1], r[2])

def gf_texto(texto, alto, fuente="arial"):
    """Convierte un texto en un gráfico ZPL (^GFA) usando fuentes reales de
    Windows: la vista previa y la impresión salen IDÉNTICAS píxel a píxel.
    Devuelve (comando, ancho_px, alto_px) o None si no hay Pillow/fuente."""
    try:
        from PIL import Image, ImageDraw, ImageFont
    except ImportError:
        return None
    base = os.path.join(os.environ.get("WINDIR", r"C:\Windows"), "Fonts")
    ruta = os.path.join(base, FUENTES_WIN.get(fuente, "arial.ttf"))
    if not os.path.exists(ruta):
        ruta = os.path.join(base, "arial.ttf")
    try:
        fnt = ImageFont.truetype(ruta, max(8, int(alto)))
    except OSError:
        return None
    l, t, r, b = fnt.getbbox(texto)
    wpx, hpx = max(1, r - l), max(1, b - t)
    img = Image.new("1", (wpx, hpx), 0)
    ImageDraw.Draw(img).text((-l, -t), texto, fill=1, font=fnt)
    bpr = (wpx + 7) // 8
    hexd = img.tobytes().hex().upper()
    total = bpr * hpx
    return (f"^GFA,{total},{total},{bpr},{hexd}", wpx, hpx)

EXT_FOTO = (".jpg", ".jpeg", ".png", ".bmp", ".gif", ".webp", ".jfif")
_FOTOS_CACHE = {"t": 0.0, "ruta": "", "map": {}}

def buscar_foto(c, sku, nombre=""):
    """Busca la foto del producto en la carpeta configurada (por referencia o
    por nombre, sin importar mayúsculas). Devuelve la ruta o None."""
    global _FOTOS_CACHE
    ruta = (c.get("fotos_ruta") or "").strip()
    if not ruta or not sku:
        return None
    for ext in EXT_FOTO:                      # intento directo (rápido)
        pf = os.path.join(ruta, sku + ext)
        if os.path.exists(pf):
            return pf
    import time
    if _FOTOS_CACHE["ruta"] != ruta or time.time() - _FOTOS_CACHE["t"] > 300:
        m = {}
        try:
            for f in os.listdir(ruta):        # índice, se refresca cada 5 min
                raiz, ext = os.path.splitext(f)
                if ext.lower() in EXT_FOTO:
                    m.setdefault(raiz.strip().lower(), f)
        except OSError:
            return None
        _FOTOS_CACHE = {"t": time.time(), "ruta": ruta, "map": m}
    m = _FOTOS_CACHE["map"]
    for clave in (str(sku).strip().lower(), str(nombre or "").strip().lower()):
        if clave and clave in m:
            return os.path.join(ruta, m[clave])
    return None

def gf_imagen(ruta, ancho, alto):
    """Convierte una foto a gráfico ZPL 1-bit con difuminado (lo único que la
    impresora térmica puede pintar). Devuelve (comando, w, h) o None."""
    try:
        from PIL import Image, ImageOps
    except ImportError:
        return None
    try:
        img = Image.open(ruta)
        if img.mode in ("RGBA", "LA", "P"):   # transparencias sobre blanco
            img = img.convert("RGBA")
            fondo = Image.new("RGBA", img.size, (255, 255, 255, 255))
            img = Image.alpha_composite(fondo, img)
        img = img.convert("L")
        img.thumbnail((max(8, int(ancho)), max(8, int(alto))), Image.LANCZOS)
        img = ImageOps.invert(img)            # en ZPL el bit 1 = negro
        img = img.convert("1")                # difuminado Floyd-Steinberg
        wpx, hpx = img.size
        bpr = (wpx + 7) // 8
        hexd = img.tobytes().hex().upper()
        total = bpr * hpx
        return (f"^GFA,{total},{total},{bpr},{hexd}", wpx, hpx)
    except Exception:
        return None                           # una foto dañada no daña la etiqueta

def diseno_cfg(c):
    """Diseño por defecto + lo que el usuario haya ajustado en el editor,
    incluyendo los elementos que él agregó (texto3+, raya3+, caja1+...)."""
    user = c.get("diseno") or {}
    dz = {k: {**v, **(user.get(k) or {})} for k, v in DISENO_DEFAULT.items()}
    for k, v in user.items():
        if k not in dz and isinstance(v, dict):
            dz[k] = v
    return dz

def diseno_desc_cfg(c):
    """Igual que diseno_cfg pero para la etiqueta de descripción (SAT)."""
    user = c.get("diseno_desc") or {}
    dz = {k: {**v, **(user.get(k) or {})} for k, v in DISENO_DESC_DEFAULT.items()}
    for k, v in user.items():
        if k not in dz and isinstance(v, dict):
            dz[k] = v
    return dz

def registrar_salida(d, pid, antes, despues, origen, es_venta=True):
    """Si el stock BAJÓ, se anota la salida con fecha. es_venta=False cuando
    el usuario dijo que era SOLO un ajuste (no cuenta en «más vendidos»)."""
    try:
        baja = int(antes or 0) - int(despues or 0)
    except (TypeError, ValueError):
        return
    if baja > 0:
        d.execute("INSERT INTO salidas(producto_id,cantidad,origen,es_venta,ts) "
                  "VALUES(?,?,?,?,?)",
                  (pid, baja, origen, 1 if es_venta else 0, datetime.now().isoformat()))

def fijar_bodegas(d, pid, filas, origen="fijar", es_venta=True):
    """Reemplaza las existencias por bodega del producto y sincroniza el
    TOTAL (cantidad_esperada) y la UBICACIÓN (lista de bodegas con unidades).
    filas = [{"bodega": nombre, "cantidad": n, "posicion": "A1"}].
    Devuelve True si algo cambió."""
    limpio, pos = {}, {}
    for f in filas or []:
        b = str(f.get("bodega") or "").strip().upper()[:40]
        if not b:
            continue
        try:
            cant = max(0, int(float(f.get("cantidad") or 0)))
        except (TypeError, ValueError):
            cant = 0
        limpio[b] = limpio.get(b, 0) + cant
        p = str(f.get("posicion") or "").strip().upper()[:20]
        if p:
            pos[b] = p
    prev = {r["bodega"]: (r["cantidad"], r["posicion"] or "") for r in d.execute(
        "SELECT bodega, cantidad, IFNULL(posicion,'') posicion FROM stock_bodegas "
        "WHERE producto_id=?", (pid,))}
    total = sum(limpio.values())
    ubi = ", ".join(b for b, cant in limpio.items() if cant > 0) \
        or ", ".join(limpio)
    d.execute("DELETE FROM stock_bodegas WHERE producto_id=?", (pid,))
    for b, cant in limpio.items():
        d.execute("INSERT INTO stock_bodegas(producto_id,bodega,cantidad,posicion) "
                  "VALUES(?,?,?,?)", (pid, b, cant, pos.get(b, "")))
    fila_p = d.execute("SELECT cantidad_esperada, ubicacion FROM productos WHERE id=?",
                       (pid,)).fetchone()
    if fila_p:
        registrar_salida(d, pid, fila_p["cantidad_esperada"], total, origen, es_venta)
    d.execute("UPDATE productos SET cantidad_esperada=?, ubicacion=? WHERE id=?",
              (total, ubi[:120], pid))
    ahora = {b: (cant, pos.get(b, "")) for b, cant in limpio.items()}
    return ahora != prev or (fila_p and
                             (fila_p["cantidad_esperada"] != total
                              or (fila_p["ubicacion"] or "") != ubi[:120]))

def oem_etiqueta(oem):
    """En la etiqueta solo caben DOS referencias OEM. Se separan SOLO por
    espacios: una referencia puede traer / . - adentro (ej. 06A198151C/F,
    1.2-1.5-2.0, 190/h/u//r) y esas compuestas tienen PRIORIDAD para salir.
    Ej. "1k0456834 1k02584h 19034567/t/y/u" -> "1k0456834 19034567/t/y/u"."""
    refs = [t.strip(",;") for t in str(oem).split() if t.strip(",;")]
    if len(refs) <= 2:
        return " ".join(refs)
    idx = [i for i, r in enumerate(refs) if re.search(r"[^0-9A-Za-z]", r)][:2]
    for i in range(len(refs)):
        if len(idx) >= 2:
            break
        if i not in idx:
            idx.append(i)
    return " ".join(refs[i] for i in sorted(idx))

def zpl_etiqueta(p, epc, c):
    """Diseño tipo BarTender del usuario: OEM arriba, rayas, nombre grande
    centrado, código de barras grande con número legible (a la izquierda; la
    franja derecha queda libre para la futura foto), sitio web al pie.
    Cada elemento sale de diseno_cfg() (editor de diseño del escritorio) y se
    escala automáticamente al tamaño de etiqueta y DPI configurados."""
    w = mm_a_dots(c["etiqueta_ancho_mm"], c["dpi"])
    h = mm_a_dots(c["etiqueta_alto_mm"], c["dpi"])
    fx, fy = w / 1181, h / 590
    ft = min(fx, fy)
    dz = diseno_cfg(c)
    def F(v): return max(14, int(float(v) * ft))      # tamaños de fuente
    def X(pct): return int(w * float(pct) / 100)      # % del ancho -> puntos
    def Yp(pct): return int(h * float(pct) / 100)     # % del alto  -> puntos
    def A(e, s):
        # estilo de letra del elemento: normal, estrecha o ancha
        fac = {"estrecha": 0.72, "ancha": 1.35}.get(e.get("letra", ""), 1.0)
        return f"^A0N,{s},{max(10, int(s * fac))}"
    def poner_texto(e, s, texto, x, y, ancho=None, lineas=1):
        """Un texto: con fuente de Windows elegida sale como gráfico (admite
        negrita/cursiva, idéntico en vista previa e impresión); sin fuente
        elegida usa la de la impresora (^A0, como siempre)."""
        fte = str(e.get("fuente") or "")
        if fte in FUENTES_TXT:
            fac = {"estrecha": 0.72, "ancha": 1.35}.get(e.get("letra", ""), 1.0)
            gf = gf_bloque(texto, s, fte, bool(e.get("negrita")),
                           bool(e.get("cursiva")), fac, ancho, lineas,
                           e.get("alin", "C"))
            if gf:
                z.append(f"^FO{x + gf[3]},{y + gf[4]}{gf[0]}")
                return
        if ancho is not None:
            z.append(f"^FO{x},{y}^FB{ancho},{lineas},4,{e.get('alin', 'C')}"
                     f"{A(e, s)}^FD{texto}^FS")
        else:
            z.append(f"^FO{x},{y}{A(e, s)}^FD{texto}^FS")
    # cada etiqueta lleva su oscuridad y velocidad: calidad estable aunque
    # alguien cambie la configuración de la impresora
    osc = max(0, min(30, int(c.get("oscuridad", 27))))
    vel = max(2, min(7, int(c.get("velocidad", 3))))
    z = [f"~SD{osc:02d}", "^XA", f"^PW{w}", f"^LL{h}", f"^PR{vel},{vel}", "^CI28"]
    # tipo de papel elegido en Configuración ("" = respetar el de la impresora)
    mn = {"gap": "^MNY", "marca": "^MNM", "continuo": "^MNN"}.get(
        str(c.get("papel_tipo") or ""))
    if mn:
        z.append(mn)
    if c.get("codificar_rfid") and epc:
        z += ["^RS8", f"^RFW,H,,,A^FD{epc}^FS"]      # graba el EPC (solo ZT411R)
    if dz["borde"]["on"]:
        z.append(f"^FO3,3^GB{w-6},{h-6},2,B,3^FS")    # marco impreso (opcional)
    e = dz["recuadro"]
    if e["on"]:
        g = max(1, int(float(e.get("grosor", 2))))
        z.append(f"^FO{X(e['x'])},{Yp(e['y'])}^GB{X(e['ancho'])},{Yp(e['alto'])},{g}^FS")
    oem = (p["oem"] if "oem" in p.keys() else "") or ""
    e = dz["oem"]
    if e["on"] and oem:
        poner_texto(e, F(e["s"]), f"OEM {oem_etiqueta(oem)}",
                    X(e.get("x", 0)), Yp(e["y"]), X(e.get("ancho", 100)))
    e = dz["raya1"]
    if e["on"]:
        z.append(f"^FO{X(e.get('x', 2.5))},{Yp(e['y'])}^GB{X(e.get('ancho', 95))},2,2^FS")
    e = dz["nombre"]
    if e["on"]:
        # lineas 0 = automático: se reservan hasta 4 líneas y el texto usa las
        # que necesite; un nombre largo ya no se corta
        n = int(e.get("lineas") or 0) or 4
        poner_texto(e, F(e["s"]), p["nombre"][:64].upper(),
                    X(e.get("x", 0)), Yp(e["y"]), X(e.get("ancho", 100)), n)
    e = dz["raya2"]
    if e["on"]:
        z.append(f"^FO{X(e.get('x', 2.5))},{Yp(e['y'])}^GB{X(e.get('ancho', 95))},2,2^FS")
    # El dato del código de barras: el EAN-13 con precio (codigo_barras) si el
    # producto lo tiene; si no, la referencia (SKU) en Code 128.
    e = dz["codigo"]
    if e["on"]:
        cb = ((p["codigo_barras"] if "codigo_barras" in p.keys() else "") or "").strip()
        dato = cb if (cb.isdigit() and len(cb) in (12, 13)) else str(p["sku"])
        x0, y0 = X(e["x"]), Yp(e["y"])
        alto_bc = max(30, Yp(e["alto"]))
        ajuste = {"fino": -1, "grueso": 1}.get(e.get("barras", ""), 0)
        con_nums = e.get("numeros") is not False
        # Fuente de los números: una fuente REAL de Windows convertida a
        # gráfico (idéntica en vista previa e impresión); "0" = fuente Zebra.
        fnum = str(e.get("fuente_num", "arial"))
        if fnum not in FUENTES_WIN and fnum != "0":
            fnum = "arial"
        # Tamaño de los números: num_s en unidades de "letra" (como los demás
        # textos); 0 o vacío = automático según el alto de las barras.
        num_s = float(e.get("num_s") or 0)
        dig = max(12, int(num_s * ft)) if num_s > 0 else \
            max(12, int(float(e["alto"]) * 1.5 * ft))

        def poner_numeros(x, y, texto, ancho_max):
            """Números centrados en ancho_max; se encogen si no caben.
            Regresa el alto real usado (para las guías)."""
            gf = None if fnum == "0" else gf_texto(texto, dig, fnum)
            if gf and gf[1] > ancho_max:
                gf = gf_texto(texto, max(8, int(dig * ancho_max / gf[1])), fnum)
            if gf:
                z.append(f"^FO{max(0, x + (ancho_max - gf[1]) // 2)},{y}{gf[0]}")
                return gf[2]
            cw = min(int(dig * 0.75), max(6, (ancho_max - 2) // max(1, len(texto))))
            xg = max(0, x + (ancho_max - len(texto) * cw) // 2)
            z.append(f"^FO{xg},{y}^A0N,{dig},{cw}^FD{texto}^FS")
            return dig

        if dato.isdigit() and len(dato) in (12, 13):
            mod = max(2, min(7, int(w * 0.5 / 95) + ajuste))   # EAN-13: ~95 módulos
            z.append(f"^FO{x0},{y0}^BY{mod}^BEN,{alto_bc},N,N^FD{dato[:12]}^FS")
            if con_nums:
                y_num = y0 + alto_bc + 2
                d13 = dato if len(dato) == 13 else ean13_control(dato[:12])
                # grupos de 6 centrados bajo cada mitad + primer dígito afuera
                alto_g = poner_numeros(x0 + 3 * mod, y_num, d13[1:7], 43 * mod)
                poner_numeros(x0 + 49 * mod, y_num, d13[7:13], 43 * mod)
                poner_numeros(max(0, x0 - dig - mod), y_num, d13[0], dig)
                # guías clásicas (inicio, centro, fin) bajando entre los números
                for mmod in (0, 2, 46, 48, 92, 94):
                    z.append(f"^FO{x0 + mmod * mod},{y0 + alto_bc}^GB{mod},{alto_g},{mod}^FS")
        else:
            mod = max(2, min(6, (2 if w < 700 else 3) + ajuste))
            ancho_bc = (11 * len(dato) + 35) * mod
            z.append(f"^FO{x0},{y0}^BY{mod}^BCN,{alto_bc},N,N^FD{dato}^FS")
            if con_nums:
                poner_numeros(x0, y0 + alto_bc + 2, dato, ancho_bc)
    e = dz.get("sku") or {}
    if e.get("on") and str(p["sku"] or "").strip():
        # la referencia, pequeña, encima de la foto
        poner_texto(e, F(e.get("s", 20)), str(p["sku"]).strip(),
                    X(e.get("x", 60)), Yp(e.get("y", 36.6)), X(e.get("ancho", 37)))
    e = dz["foto"]
    if e["on"]:
        # foto elegida a mano para el producto; si no hay (o ya no existe),
        # se busca sola por referencia/nombre en la carpeta de fotos
        ruta_f = ((p["foto"] if "foto" in p.keys() else "") or "").strip()
        if not (ruta_f and os.path.exists(ruta_f)):
            ruta_f = buscar_foto(c, str(p["sku"]),
                                 p["nombre"] if "nombre" in p.keys() else "")
        if ruta_f:
            aw, ah = X(e.get("ancho", 35)), Yp(e.get("alto", 40))
            gf = gf_imagen(ruta_f, aw, ah)
            if gf:
                xf = max(0, X(e["x"]) + (aw - gf[1]) // 2)
                yf = max(0, Yp(e["y"]) + (ah - gf[2]) // 2)
                z.append(f"^FO{xf},{yf}{gf[0]}")
    e = dz["web"]
    if e["on"] and c.get("nombre_empresa"):
        poner_texto(e, F(e["s"]), c["nombre_empresa"],
                    X(e.get("x", 0)), Yp(e["y"]), X(e.get("ancho", 100)))
    e = dz["precio"]
    precio_val = (p["precio"] if "precio" in p.keys() else 0) or 0
    if e["on"] and precio_val:
        txt = "${:,.0f}".format(precio_val).replace(",", ".")
        poner_texto(e, F(e["s"]), txt, X(e["x"]), Yp(e["y"]))
    for kk in ("texto1", "texto2"):
        e = dz[kk]
        if e["on"] and (e.get("texto") or "").strip():
            poner_texto(e, F(e["s"]), e["texto"][:60], X(e["x"]), Yp(e["y"]))
    e = dz["ubicacion"]
    ubi = (p["ubicacion"] if "ubicacion" in p.keys() else "") or ""
    if e["on"] and ubi:
        poner_texto(e, F(e["s"]), f"U: {ubi}", X(e["x"]), Yp(e["y"]))
    e = dz["epc"]
    if e["on"] and epc:
        s = max(10, int(float(e["s"]) * ft))
        z.append(f"^FO{X(e['x'])},{Yp(e['y'])}^A0N,{s},{s}^FD{epc}^FS")   # EPC pequeño
    # elementos agregados por el usuario en el editor (texto3+, raya3+, caja1+)
    for k, e in dz.items():
        if k in DISENO_DEFAULT or not isinstance(e, dict) or not e.get("on"):
            continue
        try:
            if k.startswith("texto") and (e.get("texto") or "").strip():
                poner_texto(e, F(e.get("s", 30)), str(e["texto"])[:60],
                            X(e["x"]), Yp(e["y"]))
            elif k.startswith("raya"):
                z.append(f"^FO{X(e['x'])},{Yp(e['y'])}^GB{X(e.get('ancho', 40))},2,2^FS")
            elif k.startswith("caja"):
                g = max(1, int(float(e.get("grosor", 2))))
                z.append(f"^FO{X(e['x'])},{Yp(e['y'])}^GB{X(e.get('ancho', 30))},"
                         f"{Yp(e.get('alto', 20))},{g}^FS")
        except (KeyError, TypeError, ValueError):
            pass   # un elemento a medio configurar no daña la etiqueta
    z.append("^XZ")
    return "\n".join(z)

def guardar_cfg(c):
    with open(CFG, "w", encoding="utf-8") as fp:
        json.dump(c, fp, indent=2, ensure_ascii=False)

def _mandar_zpl(zpl, ip, puerto, timeout=6):
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    s.settimeout(timeout)
    s.connect((ip, int(puerto)))
    s.sendall(zpl.encode("utf-8") if isinstance(zpl, str) else zpl)
    s.close()

def buscar_impresoras():
    """Escanea la red local (puerto 9100) y pregunta el modelo por SGD.
    Las Zebra contestan (ej. ZT411R); otros equipos con 9100 quedan sin modelo.
    Devuelve [{"ip", "modelo"}] con las Zebra primero."""
    base = ip_local()
    if base.count(".") != 3 or not base.replace(".", "").isdigit():
        return []
    red = base.rsplit(".", 1)[0]

    def probar(ip):
        try:
            s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            s.settimeout(0.4)
            s.connect((ip, 9100))
        except OSError:
            return None
        modelo = ""
        try:
            s.settimeout(1.5)
            s.sendall(b'! U1 getvar "device.product_name"\r\n')
            modelo = s.recv(128).decode("ascii", "ignore").strip().strip('"').strip()
        except OSError:
            pass
        try:
            s.close()
        except OSError:
            pass
        return {"ip": ip, "modelo": modelo}

    import concurrent.futures
    ips = [f"{red}.{n}" for n in range(1, 255) if f"{red}.{n}" != base]
    with concurrent.futures.ThreadPoolExecutor(max_workers=64) as ex:
        res = [r for r in ex.map(probar, ips) if r]
    return sorted(res, key=lambda r: (not r["modelo"], r["ip"]))

def _es_zebra(modelo):
    m = (modelo or "").upper()
    return bool(m) and ("ZEBRA" in m or m.startswith(("ZT", "ZD", "ZQ", "GK", "GX")))

def impresoras_windows():
    """Nombres de las impresoras instaladas en Windows (para el botón
    Avanzado, que abre las preferencias del driver)."""
    try:
        r = subprocess.run(
            ["powershell", "-NoProfile", "-Command", "(Get-Printer).Name"],
            capture_output=True, text=True, timeout=25,
            creationflags=0x08000000)          # sin ventana de consola
        return [l.strip() for l in (r.stdout or "").splitlines() if l.strip()]
    except Exception:
        return []

def abrir_preferencias_impresora(nombre):
    """Abre la ventana de 'Preferencias de impresión' de Windows del driver
    (la misma de Panel de control), sin bloquear el servidor."""
    subprocess.Popen(["rundll32", "printui.dll,PrintUIEntry", "/e", "/n", nombre])


def mandar_windows(nombre, datos):
    """Manda los datos EN CRUDO (ZPL o TSPL) a una impresora instalada en
    Windows. Da igual si está por USB o por red: de la conexión se encarga
    Windows, así no hay que perseguir la IP cuando el router se la cambia.

    Se usa la API del spooler con ctypes a propósito: así no hace falta
    instalar pywin32 ni añadir nada al .exe."""
    if os.name != "nt":
        raise OSError("imprimir por Windows solo funciona en Windows")
    nombre = str(nombre or "").strip()
    if not nombre:
        raise OSError("no se ha elegido la impresora de Windows")
    if not isinstance(datos, (bytes, bytearray)):
        datos = str(datos).encode("utf-8")
    datos = bytes(datos)

    import ctypes
    from ctypes import wintypes

    ws = ctypes.WinDLL("winspool.drv", use_last_error=True)

    class DOC_INFO_1(ctypes.Structure):
        _fields_ = [("pDocName", wintypes.LPWSTR),
                    ("pOutputFile", wintypes.LPWSTR),
                    ("pDatatype", wintypes.LPWSTR)]

    ws.OpenPrinterW.argtypes = [wintypes.LPWSTR, ctypes.POINTER(wintypes.HANDLE),
                                ctypes.c_void_p]
    ws.StartDocPrinterW.argtypes = [wintypes.HANDLE, wintypes.DWORD,
                                    ctypes.POINTER(DOC_INFO_1)]
    ws.StartPagePrinter.argtypes = [wintypes.HANDLE]
    ws.WritePrinter.argtypes = [wintypes.HANDLE, ctypes.c_void_p, wintypes.DWORD,
                                ctypes.POINTER(wintypes.DWORD)]
    ws.EndPagePrinter.argtypes = [wintypes.HANDLE]
    ws.EndDocPrinter.argtypes = [wintypes.HANDLE]
    ws.ClosePrinter.argtypes = [wintypes.HANDLE]

    h = wintypes.HANDLE()
    if not ws.OpenPrinterW(nombre, ctypes.byref(h), None):
        raise OSError("Windows no encuentra la impresora «%s» (error %d). "
                      "Revisa que el nombre sea exacto en ⚙ Configuración."
                      % (nombre, ctypes.get_last_error()))
    try:
        doc = DOC_INFO_1("Inventario RFID", None, "RAW")
        if not ws.StartDocPrinterW(h, 1, ctypes.byref(doc)):
            raise OSError("Windows no aceptó el trabajo para «%s» (error %d)"
                          % (nombre, ctypes.get_last_error()))
        try:
            ws.StartPagePrinter(h)
            escritos = wintypes.DWORD(0)
            if not ws.WritePrinter(h, datos, len(datos), ctypes.byref(escritos)):
                raise OSError("no se pudieron enviar los datos a «%s» (error %d)"
                              % (nombre, ctypes.get_last_error()))
            if escritos.value != len(datos):
                raise OSError("la impresora «%s» solo aceptó %d de %d bytes"
                              % (nombre, escritos.value, len(datos)))
            ws.EndPagePrinter(h)
        finally:
            ws.EndDocPrinter(h)
    finally:
        ws.ClosePrinter(h)


def salida_windows(c, cual):
    """Devuelve el nombre de la impresora de Windows si esa impresora está
    configurada para imprimir POR WINDOWS; si no, cadena vacía (= por red)."""
    pre = "sat" if cual == "sat" else "zebra"
    if str(c.get(pre + "_salida") or "red").lower() != "windows":
        return ""
    return str(c.get(pre + "_impresora_win") or "").strip()


def enviar_zpl(zpl, c):
    win = salida_windows(c, "zebra")
    if win:
        mandar_windows(win, zpl)
        return
    try:
        _mandar_zpl(zpl, c["impresora_ip"], c["impresora_puerto"])
        return
    except OSError:
        pass
    # No contestó: quizá el router le cambió la IP (DHCP). Se busca la
    # impresora en la red y, si hay UNA Zebra clara, se reintenta y la
    # configuración queda corregida sola.
    zebras = [z for z in buscar_impresoras() if _es_zebra(z["modelo"])]
    if len(zebras) == 1 and zebras[0]["ip"] != c["impresora_ip"]:
        _mandar_zpl(zpl, zebras[0]["ip"], c["impresora_puerto"])
        c["impresora_ip"] = zebras[0]["ip"]
        guardar_cfg(c)
        return
    # sin arreglo automático: que el error original llegue al usuario
    _mandar_zpl(zpl, c["impresora_ip"], c["impresora_puerto"])

# ------- etiqueta de DESCRIPCIÓN (impresora SAT, sin chip) -------
def _img_foto_pil(ruta, ancho, alto):
    """Foto del producto como imagen '1' (1 = tinta) para pegar en la etiqueta."""
    try:
        from PIL import Image, ImageOps
        im = Image.open(ruta)
        if im.mode in ("RGBA", "LA", "P"):
            im = im.convert("RGBA")
            fondo = Image.new("RGBA", im.size, (255, 255, 255, 255))
            im = Image.alpha_composite(fondo, im)
        im = im.convert("L")
        im.thumbnail((max(8, int(ancho)), max(8, int(alto))), Image.LANCZOS)
        return ImageOps.invert(im).convert("1")
    except Exception:
        return None

def img_descripcion(p, c, dpi=None, diseno=None, ancho=None, alto=None):
    """Dibuja una etiqueta completa (por defecto la de DESCRIPCIÓN, o el diseño
    que se pase) como imagen 1-bit (1 = tinta) con Pillow, a tamaño de la SAT.
    Sirve para imprimir en la SAT tanto la etiqueta de descripción como la de
    CÓDIGO DE BARRAS (pasándole diseno=diseno_cfg(c)); con ancho/alto en puntos
    sale al tamaño de OTRA impresora (la Zebra, que además graba el chip)."""
    from PIL import Image, ImageDraw
    dpi = int(dpi or c.get("sat_dpi") or 203)
    w = int(ancho or mm_a_dots(float(c.get("sat_ancho_mm") or 50), dpi))
    h = int(alto or mm_a_dots(float(c.get("sat_alto_mm") or 40), dpi))
    ft = min(w / 1181, h / 590)      # misma escala relativa que la etiqueta Zebra
    dz = diseno if diseno is not None else diseno_desc_cfg(c)
    img = Image.new("1", (w, h), 0)
    dib = ImageDraw.Draw(img)
    def F(v): return max(10, int(float(v) * ft))
    def X(pct): return int(w * float(pct) / 100)
    def Yp(pct): return int(h * float(pct) / 100)
    def val(k): return (p[k] if k in p.keys() else "") or ""
    precio_val = val("precio") or 0
    textos = {
        "sku":       str(val("sku")),
        "nombre":    str(val("nombre"))[:120].upper(),
        "oem":       ("OEM " + oem_etiqueta(val("oem"))) if val("oem") else "",
        "precio":    "${:,.0f}".format(precio_val).replace(",", ".") if precio_val else "",
        "ubicacion": ("U: " + str(val("ubicacion"))) if val("ubicacion") else "",
        "web":       str(c.get("nombre_empresa") or ""),
    }
    def poner(k, e):
        txt = textos.get(k, str(e.get("texto") or "")).strip()
        if not txt:
            return
        s = F(e.get("s", 30))
        fte = str(e.get("fuente") or "")
        neg, cur = bool(e.get("negrita")), bool(e.get("cursiva"))
        if fte not in FUENTES_TXT:
            fte, neg = "arialn", True   # aproximación de la "fuente de impresora"
        fac = {"estrecha": 0.72, "ancha": 1.35}.get(e.get("letra", ""), 1.0)
        ancho = X(e["ancho"]) if e.get("ancho") is not None else None
        lin = (int(e.get("lineas") or 0) or 4) if k == "nombre" else 1
        r = img_bloque(txt, s, fte, neg, cur, fac, ancho, lin, e.get("alin", "C"))
        if not r:
            return
        ti, dx, dy = r
        x, y = X(e.get("x", 0)), Yp(e.get("y", 0))
        if e.get("inv"):
            # franja negra con letras blancas (como el pie de la etiqueta real)
            pad = max(2, int(s * 0.3))
            bw = ancho if ancho else ti.width + 2 * pad
            dib.rectangle([x, max(0, y + dy - pad),
                           min(w, x + bw) - 1, min(h - 1, y + dy + ti.height + pad)],
                          fill=1)
            img.paste(0, (x + (dx if ancho else pad + dx), y + dy), ti)
        else:
            img.paste(1, (x + dx, y + dy), ti)
    if dz.get("borde", {}).get("on"):
        dib.rectangle([2, 2, w - 3, h - 3], outline=1, width=2)
    for k, e in dz.items():
        if k == "borde" or not isinstance(e, dict) or not e.get("on"):
            continue
        try:
            if k == "codigo":
                cb = str(val("codigo_barras")).strip()
                dato = cb if (cb.isdigit() and len(cb) in (12, 13)) else str(val("sku"))
                if dato:
                    dibujar_codigo_img(img, dib, e, dato, w, h, ft)
            elif k == "foto":
                ruta_f = str(val("foto")).strip()
                if not (ruta_f and os.path.exists(ruta_f)):
                    ruta_f = buscar_foto(c, str(val("sku")), str(val("nombre")))
                if ruta_f:
                    aw, ah = X(e.get("ancho", 35)), Yp(e.get("alto", 40))
                    fi = _img_foto_pil(ruta_f, aw, ah)
                    if fi:
                        xf = max(0, X(e["x"]) + (aw - fi.width) // 2)
                        yf = max(0, Yp(e["y"]) + (ah - fi.height) // 2)
                        img.paste(1, (xf, yf), fi)
            elif k in textos or k.startswith("texto"):
                poner(k, e)
            elif k.startswith("raya"):
                x, y = X(e.get("x", 0)), Yp(e["y"])
                dib.rectangle([x, y, x + X(e.get("ancho", 40)) - 1, y + 2], fill=1)
            elif k.startswith("caja") or k == "recuadro":
                g = max(1, int(float(e.get("grosor", 2))))
                dib.rectangle([X(e["x"]), Yp(e["y"]),
                               X(e["x"]) + X(e.get("ancho", 30)),
                               Yp(e["y"]) + Yp(e.get("alto", 20))], outline=1, width=g)
        except (KeyError, TypeError, ValueError):
            pass   # un elemento a medio configurar no daña la etiqueta
    return img

def datos_sat_img(img, c, copias=1):
    """Empaqueta una imagen 1-bit para la impresora SAT en su lenguaje:
    TSPL (SAT/TSC, lo normal) o ZPL. Lo usan la etiqueta de descripción y la
    de código de barras cuando salen por la SAT.
    Rollo de DOBLE etiqueta (sat_doble): la impresora ve un rollo con DOS
    etiquetas lado a lado; si se le declara el ancho de una sola, el firmware
    la centra en medio de las dos (queda a caballo entre ambas). Se le declara
    el ANCHO TOTAL real (las dos + separación) y la imagen (de una sola
    etiqueta) se ubica en el/los carril(es) elegido(s):
      izquierda / derecha -> solo esa mitad, la otra queda en blanco
      ambas               -> se repite EN LAS DOS a la vez (mismo contenido),
                              así no se desperdicia la otra mitad del rollo."""
    copias = max(1, int(copias or 1))
    osc = max(0, min(15, int(c.get("sat_oscuridad", 12))))
    papel = str(c.get("sat_papel_tipo") or "")
    ancho_mm = float(c.get("sat_ancho_mm") or 50)
    alto_mm = float(c.get("sat_alto_mm") or 40)
    dpi = int(c.get("sat_dpi") or 203)
    doble = bool(c.get("sat_doble"))
    sep_mm = float(c.get("sat_sep_mm") or 4)
    lado = str(c.get("sat_lado") or "izquierda")
    ancho_total_mm = ancho_mm * 2 + sep_mm if doble else ancho_mm
    if doble and lado == "ambas":
        xs_mm = [0, ancho_mm + sep_mm]
    elif doble and lado == "derecha":
        xs_mm = [ancho_mm + sep_mm]
    else:
        xs_mm = [0]
    xs_dots = [mm_a_dots(x, dpi) for x in xs_mm]
    if str(c.get("sat_lenguaje") or "tspl").lower() == "zpl":
        cmd = _gfa(img)[0]
        mn = {"gap": "^MNY", "marca": "^MNM", "continuo": "^MNN"}.get(papel, "")
        pw = mm_a_dots(ancho_total_mm, dpi)
        bloques = "".join(f"^FO{x},0{cmd}" for x in xs_dots)
        return (f"~SD{min(30, osc * 2):02d}\n^XA^PW{pw}^LL{img.height}{mn}"
                f"{bloques}^PQ{copias}^XZ").encode("utf-8")
    # TSPL: en BITMAP el bit 0 pinta negro (al revés del ZPL) -> se invierte
    bpr = (img.width + 7) // 8
    datos = bytes(b ^ 0xFF for b in img.tobytes())
    gap = float(c.get("sat_gap_mm") or 3)
    # tipo de papel: separación normal (GAP), marca negra (BLINE) o continuo
    linea_papel = (f"BLINE {gap:g} mm,0" if papel == "marca"
                   else "GAP 0,0" if papel == "continuo" else f"GAP {gap:g} mm,0")
    # BITMAP en X solo admite múltiplos de 8 puntos (byte-alineado) en la
    # mayoría de firmwares TSPL
    xs_dots = [(x // 8) * 8 for x in xs_dots]
    cab = (f"SIZE {ancho_total_mm:g} mm,{alto_mm:g} mm\r\n"
           f"{linea_papel}\r\n"
           f"DIRECTION 1\r\nREFERENCE 0,0\r\nDENSITY {osc}\r\nCLS\r\n").encode("ascii")
    bitmaps = b"".join(f"BITMAP {x},0,{bpr},{img.height},0,".encode("ascii") + datos
                        for x in xs_dots)
    return cab + bitmaps + f"\r\nPRINT {copias},1\r\n".encode("ascii")

def datos_prueba(c, tipo, ruta):
    """Etiqueta de PRUEBA corta, en el lenguaje de cada impresora. Lleva escrito
    por dónde salió, para que se vea de un vistazo si la ruta es la buena."""
    if tipo == "zebra":
        dpi = int(c.get("dpi") or 203)
        w = mm_a_dots(float(c.get("etiqueta_ancho_mm") or 50), dpi)
        h = mm_a_dots(float(c.get("etiqueta_alto_mm") or 39), dpi)
        g, p = int(h * 0.20), int(h * 0.10)
        return "\n".join([
            "^XA", f"^PW{w}", f"^LL{h}",
            f"^FO0,{int(h*0.16)}^A0N,{g},{g}^FB{w},1,0,C^FDPRUEBA ZEBRA^FS",
            f"^FO0,{int(h*0.48)}^A0N,{p},{p}^FB{w},2,3,C^FD{texto_zebra(ruta)}^FS",
            "^PQ1", "^XZ"])
    # SAT: se declara el ancho TOTAL (rollo doble incluido), como al imprimir
    dpi = int(c.get("sat_dpi") or 203)
    ancho = float(c.get("sat_ancho_mm") or 50)
    alto = float(c.get("sat_alto_mm") or 40)
    total = ancho * 2 + float(c.get("sat_sep_mm") or 4) if c.get("sat_doble") else ancho
    osc = max(0, min(15, int(c.get("sat_oscuridad", 12))))
    papel = str(c.get("sat_papel_tipo") or "")
    if str(c.get("sat_lenguaje") or "tspl").lower() == "zpl":
        w, h = mm_a_dots(total, dpi), mm_a_dots(alto, dpi)
        mn = {"gap": "^MNY", "marca": "^MNM", "continuo": "^MNN"}.get(papel, "")
        g, p = int(h * 0.20), int(h * 0.10)
        return "\n".join([
            "^XA", f"^PW{w}", f"^LL{h}", mn,
            f"^FO0,{int(h*0.16)}^A0N,{g},{g}^FB{w},1,0,C^FDPRUEBA SAT (ZPL)^FS",
            f"^FO0,{int(h*0.48)}^A0N,{p},{p}^FB{w},2,3,C^FD{texto_zebra(ruta)}^FS",
            "^PQ1", "^XZ"])
    gap = float(c.get("sat_gap_mm") or 3)
    linea_papel = (f"BLINE {gap:g} mm,0" if papel == "marca"
                   else "GAP 0,0" if papel == "continuo" else f"GAP {gap:g} mm,0")
    return "\r\n".join([
        f"SIZE {total:g} mm,{alto:g} mm", linea_papel,
        "DIRECTION 1", "REFERENCE 0,0", f"DENSITY {osc}", "CLS",
        'TEXT 24,30,"4",0,1,1,"PRUEBA SAT (TSPL)"',
        'TEXT 24,95,"2",0,1,1,"%s"' % texto_zebra(ruta),
        'TEXT 24,135,"2",0,1,1,"si lees esto, la impresora quedo bien"',
        "PRINT 1,1", ""])


def datos_descripcion(p, c, copias=1):
    """Etiqueta de DESCRIPCIÓN para la SAT (imagen)."""
    return datos_sat_img(img_descripcion(p, c), c, copias)

def datos_codigo_sat(p, c, copias=1):
    """La etiqueta de CÓDIGO DE BARRAS (el diseño de la pestaña 🏷️, el mismo de
    la Zebra) impresa en la SAT: se dibuja a tamaño de la SAT y va como imagen."""
    return datos_sat_img(img_descripcion(p, c, diseno=diseno_cfg(c)), c, copias)

def enviar_descripcion(datos, c):
    win = salida_windows(c, "sat")
    if win:
        mandar_windows(win, datos)
        return
    ip = str(c.get("sat_ip") or "").strip()
    if not ip:
        raise OSError("primero pon la IP de la impresora SAT en ⚙ Configuración "
                      "(o cámbiala a «por Windows»)")
    _mandar_zpl(datos, ip, int(c.get("sat_puerto") or 9100))

def zpl_descripcion(p, epc, c):
    """La etiqueta de DESCRIPCIÓN impresa en la ZEBRA, que además GRABA EL CHIP.
    La SAT no sabe grabar chips: la única que puede es la ZT411R. Se dibuja el
    mismo diseño de descripción como imagen y se le añade el EPC."""
    dpi = int(c.get("dpi") or 203)
    w = mm_a_dots(float(c.get("etiqueta_ancho_mm") or 50), dpi)
    h = mm_a_dots(float(c.get("etiqueta_alto_mm") or 39), dpi)
    img = img_descripcion(p, c, dpi=dpi, ancho=w, alto=h)
    cmd = _gfa(img)[0]
    z = [f"~SD{max(0, min(30, int(c.get('oscuridad', 27)))):02d}",
         "^XA", f"^PW{w}", f"^LL{h}",
         f"^PR{max(2, min(7, int(c.get('velocidad', 3))))}"]
    mn = {"gap": "^MNY", "marca": "^MNM", "continuo": "^MNN"}.get(
        str(c.get("papel_tipo") or ""), "")
    if mn:
        z.append(mn)
    if c.get("codificar_rfid") and epc:
        z += ["^RS8", f"^RFW,H,,,A^FD{epc}^FS"]      # graba el EPC (solo ZT411R)
    z.append(f"^FO0,0{cmd}")
    z.append("^PQ1")
    z.append("^XZ")
    return "\n".join(z)

EPC_MARCA = "AF01"   # prefijo propio: identifica los EPC grabados por este sistema

def nuevo_epc(d, producto_id):
    """EPC de 24 hex autodescriptivo: AF01 + id de producto (6 hex) +
    consecutivo (6 hex) + aleatorio (8 hex). La referencia va dentro del
    número, así una etiqueta se reconoce aunque falte la asociación."""
    serie = d.execute("SELECT COUNT(*) FROM tags WHERE producto_id=?",
                      (producto_id,)).fetchone()[0]
    while True:
        epc = "%s%06X%06X%s" % (EPC_MARCA, producto_id % 0xFFFFFF,
                                serie % 0xFFFFFF, secrets.token_hex(4).upper())
        if not d.execute("SELECT 1 FROM tags WHERE epc=?", (epc,)).fetchone():
            return epc
        serie += 1

def decodificar_epc(d, epc):
    """Si el EPC es de los nuestros (AF01...), regresa el id de producto."""
    if len(epc) == 24 and epc.startswith(EPC_MARCA):
        try:
            pid = int(epc[4:10], 16)
            if d.execute("SELECT 1 FROM productos WHERE id=?", (pid,)).fetchone():
                return pid
        except ValueError:
            pass
    return None


EPC_BALIZA = "AF02"   # prefijo de las BALIZAS de posición (no son repuestos)


def partir_posicion(posicion):
    """«B12» -> ("B", 12).  Devuelve (None, None) si no tiene esa forma."""
    m = re.match(r"^([A-Z])\s*(\d{1,2})$", str(posicion or "").strip().upper())
    return (m.group(1), int(m.group(2))) if m else (None, None)


def nuevo_epc_baliza(d, posicion):
    """EPC de 24 hex para una baliza: AF02 + letra (2 hex) + número (2 hex) +
    16 al azar. La posición va DENTRO del número, así una baliza se reconoce
    aunque se pierda la base de datos."""
    letra, num = partir_posicion(posicion)
    cab = EPC_BALIZA + ("%02X" % (ord(letra) - 64) if letra else "00") \
                     + ("%02X" % min(num or 0, 255))
    while True:
        epc = cab + secrets.token_hex(8).upper()
        if not d.execute("SELECT 1 FROM balizas WHERE epc=?", (epc,)).fetchone() \
           and not d.execute("SELECT 1 FROM tags WHERE epc=?", (epc,)).fetchone():
            return epc


def decodificar_baliza(epc):
    """Si el EPC es de una baliza (AF02...), regresa «B12». Red de seguridad
    para reconocerla aunque no esté dada de alta."""
    if len(epc) == 24 and epc.startswith(EPC_BALIZA):
        try:
            l, n = int(epc[4:6], 16), int(epc[6:8], 16)
            if 1 <= l <= 26 and n:
                return "%s%d" % (chr(64 + l), n)
        except ValueError:
            pass
    return None


def texto_zebra(s):
    """Quita acentos SIN cambiar mayúsculas: la Zebra no los dibuja bien con la
    tabla de caracteres por defecto. (Ojo: no confundir con _sin_tildes, que es
    la del buscador y sí pasa todo a minúsculas.)"""
    tabla = str.maketrans("ÁÉÍÓÚÜÑáéíóúüñ", "AEIOUUNaeiouun")
    return str(s or "").translate(tabla)


def zpl_baliza(bodega, posicion, epc, c):
    """Etiqueta de BALIZA: la posición enorme para pegarla sin equivocarse, y
    el EPC grabado en el chip (solo la ZT411R sabe grabar)."""
    w = mm_a_dots(float(c.get("etiqueta_ancho_mm") or 100), c["dpi"])
    h = mm_a_dots(float(c.get("etiqueta_alto_mm") or 50), c["dpi"])
    z = [f"~SD{max(0, min(30, int(c.get('oscuridad', 27)))):02d}",
         "^XA", f"^PW{w}", f"^LL{h}",
         f"^PR{max(2, min(7, int(c.get('velocidad', 3))))}"]
    mn = {"gap": "^MNY", "marca": "^MNM", "continuo": "^MNN"}.get(
        str(c.get("papel_tipo") or ""), "")
    if mn:
        z.append(mn)
    if c.get("codificar_rfid") and epc:
        z += ["^RS8", f"^RFW,H,,,A^FD{epc}^FS"]      # graba el EPC (solo ZT411R)
    s_bod, s_pos, s_pie = int(h * 0.15), int(h * 0.46), int(h * 0.085)
    z += [
        f"^FO6,6^GB{w-12},{h-12},3^FS",
        f"^FO0,{int(h*0.10)}^A0N,{s_bod},{s_bod}^FB{w},1,0,C^FD{texto_zebra(bodega)}^FS",
        f"^FO0,{int(h*0.30)}^A0N,{s_pos},{s_pos}^FB{w},1,0,C^FD{texto_zebra(posicion)}^FS",
        f"^FO0,{int(h*0.83)}^A0N,{s_pie},{s_pie}^FB{w},1,0,C^FDBALIZA DE POSICION - NO QUITAR^FS",
        "^PQ1", "^XZ"]
    return "\n".join(z)

# ------------------------------------------------------------------- BALIZAS
# Una baliza es una etiqueta RFID fija pegada al estante que no es un repuesto:
# sirve para saber DÓNDE está la pistola. Cuando lee la baliza de «BODEGA 8 /
# B-12», todo lo que lea a continuación se apunta como visto en ese sitio.
BALIZA_MINUTOS = 10          # si la última baliza es más vieja, ya no vale


def balizas_mapa(d):
    """EPC -> (bodega, posición) de todas las balizas."""
    return {r["epc"]: (r["bodega"], r["posicion"])
            for r in d.execute("SELECT epc, bodega, posicion FROM balizas")}


def pos_dispositivo(d, dispositivo, minutos=BALIZA_MINUTOS):
    """Dónde está esa pistola ahora. Si hace rato que no lee una baliza se
    devuelve vacío: es preferible no saber dónde está a inventárselo."""
    r = d.execute("SELECT bodega, posicion, ts FROM dispositivo_pos WHERE dispositivo=?",
                  (dispositivo,)).fetchone()
    if not r or not r["posicion"]:
        return ("", "")
    try:
        if datetime.now() - datetime.fromisoformat(r["ts"]) > timedelta(minutes=minutos):
            return ("", "")
    except (TypeError, ValueError):
        return ("", "")
    return (r["bodega"], r["posicion"])


def marcar_baliza(d, dispositivo, epc, bodega, posicion):
    d.execute("""INSERT INTO dispositivo_pos(dispositivo,bodega,posicion,epc_baliza,ts)
                 VALUES(?,?,?,?,?)
                 ON CONFLICT(dispositivo) DO UPDATE SET
                   bodega=excluded.bodega, posicion=excluded.posicion,
                   epc_baliza=excluded.epc_baliza, ts=excluded.ts""",
              (dispositivo, bodega, posicion, epc, datetime.now().isoformat()))


def anotar_deteccion(d, sesion_id, epc, bodega, posicion):
    """Suma UNA lectura de ese EPC en ese sitio. Se cuenta repetido a propósito:
    manda el sitio donde más veces se vio."""
    d.execute("""INSERT INTO detecciones_pos(sesion_id,epc,bodega,posicion,veces,ultima)
                 VALUES(?,?,?,?,1,?)
                 ON CONFLICT(sesion_id,epc,bodega,posicion) DO UPDATE SET
                   veces = veces + 1, ultima = excluded.ultima""",
              (sesion_id, epc, bodega, posicion, datetime.now().isoformat()))


# ---------------------------------------------------------------- API (pistolas)
@app.post("/api/lecturas")
def api_lecturas():
    """JSON: {"dispositivo":"C72-01", "epcs":["E28011...", ...], "sesion_id": opcional}

    Los EPCs se procesan EN ORDEN: si uno es una baliza, cambia el sitio en el
    que se apunta todo lo que venga detrás."""
    global ULTIMA_LECTURA
    d = db(); data = request.get_json(force=True)
    epcs = [e.strip().upper() for e in data.get("epcs", []) if e.strip()]
    disp = data.get("dispositivo", "?")
    ULTIMA_LECTURA = datetime.now()   # no se actualiza a mitad de un conteo
    ses = None
    if data.get("sesion_id"):
        ses = d.execute("SELECT * FROM sesiones WHERE id=?", (data["sesion_id"],)).fetchone()
    if not ses:
        ses = sesion_activa(d) or crear_sesion(d, "Auto " + datetime.now().strftime("%Y-%m-%d %H:%M"))
    balizas = balizas_mapa(d)
    bodega, posicion = pos_dispositivo(d, disp)
    nuevos = balizas_vistas = 0
    for e in epcs:
        # ¿es una baliza? entonces no es un repuesto: solo mueve el «dónde»
        if e in balizas:
            bodega, posicion = balizas[e]
            marcar_baliza(d, disp, e, bodega, posicion)
            balizas_vistas += 1
            continue
        if decodificar_baliza(e):
            # baliza impresa por nosotros que ya no está dada de alta: no es un
            # repuesto, así que se ignora en vez de ensuciar el conteo
            continue
        try:
            d.execute("INSERT INTO lecturas(sesion_id,epc,dispositivo,ts) VALUES(?,?,?,?)",
                      (ses["id"], e, disp, datetime.now().isoformat()))
            nuevos += 1
        except sqlite3.IntegrityError:
            pass
        if posicion:
            anotar_deteccion(d, ses["id"], e, bodega, posicion)
        # Red de seguridad: EPC con nuestra marca (AF01) sin asociar -> se
        # asocia solo al producto codificado dentro del número.
        if not d.execute("SELECT 1 FROM tags WHERE epc=?", (e,)).fetchone():
            pid = decodificar_epc(d, e)
            if pid:
                d.execute("INSERT OR REPLACE INTO tags(epc,producto_id,creado) VALUES(?,?,?)",
                          (e, pid, datetime.now().isoformat()))
    d.commit()
    return jsonify(ok=True, sesion_id=ses["id"], recibidos=len(epcs), nuevos=nuevos,
                   balizas=balizas_vistas, bodega=bodega, posicion=posicion,
                   sitio=(f"{bodega} / {posicion}" if posicion else ""))

@app.post("/api/tags")
def api_tags():
    """JSON: {"epc":"...", "sku":"..."} — sku acepta la referencia O el
    código de barras impreso (lo que la pistola haya escaneado)."""
    d = db(); data = request.get_json(force=True)
    p = producto_por_codigo(d, data.get("sku", ""))
    if not p: return jsonify(ok=False, error="SKU no existe"), 404
    d.execute("INSERT OR REPLACE INTO tags(epc,producto_id,creado) VALUES(?,?,?)",
              (data["epc"].strip().upper(), p["id"], datetime.now().isoformat()))
    d.commit()
    return jsonify(ok=True, sku=p["sku"], nombre=p["nombre"])

@app.get("/api/buscar_producto")
def api_buscar_producto():
    """?codigo=... -> producto por SKU o código de barras (para la pistola)."""
    p = producto_por_codigo(db(), request.args.get("codigo", ""))
    if not p:
        return jsonify(ok=False), 404
    return jsonify(ok=True, sku=p["sku"], nombre=p["nombre"])

@app.post("/api/resolver")
def api_resolver():
    """JSON: {"epcs":[...]} -> {"EPC": {"sku":..., "nombre":...}} (solo los conocidos).
    Lo usa la pistola para mostrar nombres de producto en vez de números EPC."""
    d = db(); data = request.get_json(force=True)
    out = {}
    for e in [str(x).strip().upper() for x in data.get("epcs", [])][:500]:
        p = d.execute("""SELECT p.sku, p.nombre FROM productos p
                         JOIN tags t ON t.producto_id=p.id WHERE t.epc=?""", (e,)).fetchone()
        if not p:
            pid = decodificar_epc(d, e)
            if pid:
                p = d.execute("SELECT sku, nombre FROM productos WHERE id=?", (pid,)).fetchone()
        if p:
            out[e] = {"sku": p["sku"], "nombre": p["nombre"]}
    return jsonify(out)

@app.get("/api/tags/todos")
def api_tags_todos():
    """Catálogo completo EPC->producto para las pistolas. Lo descargan UNA vez
    al abrir la app y así reconocen las etiquetas AL INSTANTE sin usar la red
    mientras leen (igual de rápido que la demo de Alien)."""
    d = db()
    tags = {r["epc"]: [r["sku"], r["nombre"]] for r in d.execute(
        """SELECT t.epc, p.sku, p.nombre FROM tags t
           JOIN productos p ON p.id=t.producto_id""").fetchall()}
    prods = {str(r["id"]): [r["sku"], r["nombre"]] for r in d.execute(
        "SELECT id, sku, nombre FROM productos").fetchall()}
    ign = [r["epc"] for r in d.execute(
        "SELECT epc FROM tags WHERE producto_id IS NULL").fetchall()]
    # las balizas van aparte para que la pistola pueda enseñar «📍 BODEGA 8 /
    # B-12» en vez de tratarlas como una etiqueta desconocida
    bal = {r["epc"]: [r["bodega"], r["posicion"]] for r in d.execute(
        "SELECT epc, bodega, posicion FROM balizas").fetchall()}
    return jsonify(marca=EPC_MARCA, tags=tags, productos=prods, ignorados=ign,
                   balizas=bal)

@app.get("/api/desconocidos")
def api_desconocidos():
    """Lista de EPCs leídos sin producto, para la pistola.
    Las balizas se excluyen: son etiquetas nuestras, no repuestos perdidos."""
    d = db()
    rows = d.execute("""SELECT epc, COUNT(*) veces, MAX(ts) ultima FROM lecturas
        WHERE epc NOT IN (SELECT epc FROM tags)
          AND epc NOT IN (SELECT epc FROM balizas)
        GROUP BY epc ORDER BY ultima DESC LIMIT 200""").fetchall()
    return jsonify([dict(r) for r in rows])

def _norm_baliza(data):
    """Limpia y valida lo que viene del formulario de balizas."""
    epc = str(data.get("epc", "")).strip().upper()
    bodega = str(data.get("bodega", "")).strip().upper()
    posicion = str(data.get("posicion", "")).strip().upper()
    nota = str(data.get("nota", "")).strip()
    return epc, bodega, posicion, nota


@app.get("/api/balizas")
def api_balizas():
    """Balizas dadas de alta, con cuántas lecturas ha situado cada una."""
    d = db()
    rows = d.execute("""
        SELECT b.epc, b.bodega, b.posicion, b.nota, b.creada,
               (SELECT IFNULL(SUM(veces),0) FROM detecciones_pos dp
                 WHERE dp.bodega=b.bodega AND dp.posicion=b.posicion) situadas
        FROM balizas b ORDER BY b.bodega, b.posicion""").fetchall()
    return jsonify([dict(r) for r in rows])


@app.get("/api/balizas/pistolas")
def api_balizas_pistolas():
    """Dónde está cada pistola según la última baliza que leyó. Sirve para
    comprobar de un vistazo si la pistola está viendo las balizas o no."""
    d = db()
    out = []
    for r in d.execute("SELECT * FROM dispositivo_pos ORDER BY ts DESC"):
        try:
            mins = int((datetime.now() - datetime.fromisoformat(r["ts"])).total_seconds() // 60)
        except (TypeError, ValueError):
            mins = 9999
        out.append({"dispositivo": r["dispositivo"], "bodega": r["bodega"],
                    "posicion": r["posicion"], "minutos": mins,
                    "vigente": mins < BALIZA_MINUTOS})
    return jsonify(out)


@app.post("/api/balizas")
def api_balizas_guardar():
    """JSON: {epc, bodega, posicion, nota}. Da de alta o corrige una baliza."""
    d = db()
    epc, bodega, posicion, nota = _norm_baliza(request.get_json(force=True))
    if not epc:
        return jsonify(ok=False, error="Falta el número de la etiqueta (EPC)"), 400
    if not bodega or not posicion:
        return jsonify(ok=False, error="Hay que decir la bodega y la posición"), 400
    if d.execute("SELECT 1 FROM tags WHERE epc=? AND producto_id IS NOT NULL",
                 (epc,)).fetchone():
        return jsonify(ok=False, error="Esa etiqueta ya está puesta en un repuesto. "
                                       "Usa una etiqueta nueva para la baliza."), 409
    d.execute("""INSERT INTO balizas(epc,bodega,posicion,nota,creada) VALUES(?,?,?,?,?)
                 ON CONFLICT(epc) DO UPDATE SET
                   bodega=excluded.bodega, posicion=excluded.posicion, nota=excluded.nota""",
              (epc, bodega, posicion, nota, datetime.now().isoformat()))
    d.commit()
    return jsonify(ok=True, epc=epc, sitio=f"{bodega} / {posicion}")


@app.post("/api/balizas/borrar")
def api_balizas_borrar():
    """JSON: {epc}. Quita la baliza (las detecciones ya hechas se conservan)."""
    d = db()
    epc = str(request.get_json(force=True).get("epc", "")).strip().upper()
    if not d.execute("SELECT 1 FROM balizas WHERE epc=?", (epc,)).fetchone():
        return jsonify(ok=False, error="Esa baliza no existe"), 404
    d.execute("DELETE FROM balizas WHERE epc=?", (epc,))
    d.execute("DELETE FROM dispositivo_pos WHERE epc_baliza=?", (epc,))
    d.commit()
    return jsonify(ok=True)


@app.get("/api/balizas/propuestas")
def api_balizas_propuestas():
    """?sesion_id= (o la sesión abierta) -> cambios de posición SUGERIDOS.

    Para cada producto gana el sitio donde más veces se leyó. Nunca se toca la
    base aquí: esto solo propone, y hay que confirmar en pantalla."""
    d = db()
    sid = request.args.get("sesion_id", type=int)
    if not sid:
        s = sesion_activa(d)
        sid = s["id"] if s else 0
    # Un mismo repuesto puede llevar VARIAS etiquetas (una por unidad), así que
    # se suman todas las suyas: si no, cada etiqueta parecería un sitio distinto
    # y la seguridad saldría ridículamente baja.
    filas = d.execute("""
        SELECT p.id producto_id, p.sku, p.nombre, dp.bodega, dp.posicion,
               SUM(dp.veces) veces, IFNULL(sb.posicion,'') actual,
               (sb.producto_id IS NOT NULL) en_bodega
        FROM detecciones_pos dp
        JOIN tags t ON t.epc = dp.epc
        JOIN productos p ON p.id = t.producto_id
        LEFT JOIN stock_bodegas sb ON sb.producto_id = p.id AND sb.bodega = dp.bodega
        WHERE dp.sesion_id = ?
        GROUP BY p.id, dp.bodega, dp.posicion
        ORDER BY p.id, SUM(dp.veces) DESC""", (sid,)).fetchall()
    # el sitio con más lecturas gana; se guarda el segundo para poder avisar
    mejor = {}
    for f in filas:
        k = (f["producto_id"], f["bodega"])
        if k not in mejor:
            mejor[k] = {"producto_id": f["producto_id"], "sku": f["sku"],
                        "nombre": f["nombre"], "bodega": f["bodega"],
                        "posicion": f["posicion"], "veces": f["veces"],
                        "actual": f["actual"], "en_bodega": bool(f["en_bodega"]),
                        "otras": []}
        else:
            mejor[k]["otras"].append({"posicion": f["posicion"], "veces": f["veces"]})
    out = []
    for m in mejor.values():
        total = m["veces"] + sum(o["veces"] for o in m["otras"])
        m["confianza"] = round(100.0 * m["veces"] / total) if total else 0
        m["cambia"] = (m["posicion"] != m["actual"])
        out.append(m)
    out.sort(key=lambda m: (not m["cambia"], -m["veces"]))
    return jsonify(sesion_id=sid, propuestas=out)


@app.post("/api/balizas/aplicar")
def api_balizas_aplicar():
    """JSON: {cambios:[{producto_id, bodega, posicion}, ...]}
    Escribe las posiciones aceptadas. Solo llega aquí lo que se confirmó."""
    d = db()
    cambios = request.get_json(force=True).get("cambios", [])
    hechos = 0
    for c in cambios:
        try:
            pid = int(c["producto_id"])
        except (KeyError, TypeError, ValueError):
            continue
        bodega = str(c.get("bodega", "")).strip().upper()
        posicion = str(c.get("posicion", "")).strip().upper()
        if not bodega or not posicion:
            continue
        if not d.execute("SELECT 1 FROM productos WHERE id=?", (pid,)).fetchone():
            continue
        d.execute("""INSERT INTO stock_bodegas(producto_id,bodega,cantidad,posicion)
                     VALUES(?,?,0,?)
                     ON CONFLICT(producto_id,bodega) DO UPDATE SET posicion=excluded.posicion""",
                  (pid, bodega, posicion))
        hechos += 1
    d.commit()
    return jsonify(ok=True, aplicados=hechos)


MAX_BALIZAS_LOTE = 300     # tope de seguridad: evita gastar un rollo por un clic


def _rango_letras(desde, hasta):
    a, b = (str(desde or "A").strip().upper() or "A")[0], (str(hasta or "A").strip().upper() or "A")[0]
    if not ("A" <= a <= "Z" and "A" <= b <= "Z"):
        return []
    if a > b:
        a, b = b, a
    return [chr(x) for x in range(ord(a), ord(b) + 1)]


@app.post("/api/balizas/imprimir")
def api_balizas_imprimir():
    """JSON: {bodega, desde_letra:"A", hasta_letra:"F", desde_num:1, hasta_num:10,
              solo_ver: true|false}

    Genera una baliza por cada casilla (A1, A2… F10), le inventa el EPC, la da
    de alta y la manda a la Zebra grabando el chip. Si una casilla YA tiene
    baliza se reimprime con SU MISMO EPC (así se reemplaza una etiqueta rota
    sin que la vieja deje de valer)."""
    d = db(); data = request.get_json(force=True)
    bodega = str(data.get("bodega", "")).strip().upper()
    if not bodega:
        return jsonify(ok=False, error="Falta la bodega"), 400
    letras = _rango_letras(data.get("desde_letra"), data.get("hasta_letra"))
    if not letras:
        return jsonify(ok=False, error="Las letras deben ir de la A a la Z"), 400
    try:
        n1, n2 = int(data.get("desde_num", 1)), int(data.get("hasta_num", 1))
    except (TypeError, ValueError):
        return jsonify(ok=False, error="Los números no son válidos"), 400
    if n1 > n2:
        n1, n2 = n2, n1
    if n1 < 1 or n2 > 99:
        return jsonify(ok=False, error="Los números van del 1 al 99"), 400
    total = len(letras) * (n2 - n1 + 1)
    if total > MAX_BALIZAS_LOTE:
        return jsonify(ok=False, error=f"Son {total} etiquetas y el tope es "
                                       f"{MAX_BALIZAS_LOTE}. Hazlo por partes."), 400

    existentes = {r["posicion"]: r["epc"] for r in d.execute(
        "SELECT posicion, epc FROM balizas WHERE bodega=?", (bodega,))}
    lote = []
    for letra in letras:
        for n in range(n1, n2 + 1):
            pos = f"{letra}{n}"
            lote.append({"posicion": pos, "epc": existentes.get(pos, ""),
                         "reimpresa": pos in existentes})

    if data.get("solo_ver"):
        return jsonify(ok=True, bodega=bodega, total=total, etiquetas=lote,
                       nuevas=sum(1 for x in lote if not x["reimpresa"]),
                       reimpresas=sum(1 for x in lote if x["reimpresa"]))

    c = cfg()
    hechas, fallo = [], None
    for x in lote:
        if not x["epc"]:
            x["epc"] = nuevo_epc_baliza(d, x["posicion"])
        try:
            enviar_zpl(zpl_baliza(bodega, x["posicion"], x["epc"], c), c)
        except OSError as e:
            fallo = str(e)
            break
        # solo se da de alta lo que la impresora aceptó de verdad
        d.execute("""INSERT INTO balizas(epc,bodega,posicion,nota,creada) VALUES(?,?,?,'',?)
                     ON CONFLICT(epc) DO UPDATE SET bodega=excluded.bodega,
                       posicion=excluded.posicion""",
                  (x["epc"], bodega, x["posicion"], datetime.now().isoformat()))
        hechas.append(x)
    d.commit()
    if fallo and not hechas:
        return jsonify(ok=False, error="No respondió la impresora: " + fallo), 502
    return jsonify(ok=True, bodega=bodega, impresas=len(hechas), etiquetas=hechas,
                   error=(f"Se cortó tras {len(hechas)} etiquetas: {fallo}" if fallo else ""))


@app.post("/api/ignorar")
def api_ignorar():
    """JSON: {"epc":"..."} — marca un EPC como ajeno (deja de aparecer)."""
    d = db(); data = request.get_json(force=True)
    epc = str(data.get("epc", "")).strip().upper()
    if not epc:
        return jsonify(ok=False, error="EPC vacío"), 400
    d.execute("INSERT OR REPLACE INTO tags(epc,producto_id,creado) VALUES(?,NULL,?)",
              (epc, datetime.now().isoformat()))
    d.commit()
    return jsonify(ok=True)

@app.get("/api/quien")
def api_quien():
    """Identificación para el buscador de servidores de las apps de PC:
    contesta el NOMBRE de este equipo y su IP. Lleva CORS abierto para que
    la pantallita local de conexión de la app cliente pueda leer la respuesta."""
    r = jsonify(inventario=True, nombre=socket.gethostname(), ip=ip_local())
    r.headers["Access-Control-Allow-Origin"] = "*"
    return r

SUBIDOS = os.path.join(BASE, "subidos")

@app.route("/subir", methods=["GET", "POST"])
def subir_archivo():
    """Página SIMPLE (funciona hasta en el navegador de Android 4.4) para pasar
    archivos a este PC sin cable: por ejemplo la APK de demo de la pistola Alien,
    para poder armar su app. Los archivos quedan en la carpeta 'subidos'."""
    try:
        os.makedirs(SUBIDOS, exist_ok=True)
    except OSError:
        pass
    msg = ""
    if request.method == "POST":
        f = request.files.get("archivo")
        if f and f.filename:
            nombre = re.sub(r"[^0-9A-Za-z._-]+", "_",
                            os.path.basename(f.filename))[:100] or "archivo"
            try:
                f.save(os.path.join(SUBIDOS, nombre))
                msg = "✔ Subido: " + nombre
            except Exception as e:
                msg = "✖ No se pudo guardar: %s" % e
        else:
            msg = "✖ No elegiste ningún archivo"
    try:
        files = sorted(os.listdir(SUBIDOS))
    except OSError:
        files = []
    lista = "".join("<li>%s</li>" % x for x in files) or "<li>(nada todavía)</li>"
    return """<!doctype html><html lang="es"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1"><title>Subir archivo</title></head>
<body style="font-family:sans-serif;max-width:540px;margin:0 auto;padding:18px;color:#222">
<h2>Subir archivo al PC del inventario</h2>
<p style="color:#0a0;font-weight:bold;min-height:20px">%s</p>
<form method="post" enctype="multipart/form-data">
  <input type="file" name="archivo" style="font-size:16px"><br><br>
  <button type="submit" style="padding:12px 22px;font-size:17px;background:#E87722;color:#fff;border:0;border-radius:6px">Subir</button>
</form>
<p style="color:#555;font-size:14px;margin-top:18px">Sirve para pasar archivos desde la
pistola u otro equipo a este PC <b>sin cable</b> (por ejemplo la APK de demostración de la
pistola Alien, para poder crear su app de inventario).</p>
<h3 style="font-size:16px">Archivos ya subidos</h3><ul style="font-size:14px">%s</ul>
</body></html>""" % (msg, lista)

@app.route("/apps")
def pagina_apps():
    """Página SIMPLE (Android 4.4 OK) para DESCARGAR e instalar apps desde la
    pistola sin cable: lista los .apk de la carpeta 'subidos'."""
    try:
        apks = sorted(f for f in os.listdir(SUBIDOS) if f.lower().endswith(".apk"))
    except OSError:
        apks = []
    filas = "".join(
        '<li style="margin:10px 0"><a href="/descargar/%s" '
        'style="display:inline-block;padding:12px 18px;background:#1F7A44;color:#fff;'
        'text-decoration:none;border-radius:6px;font-size:17px">⬇ %s</a></li>'
        % (x, x) for x in apks) or "<li>(no hay apps todavía)</li>"
    return """<!doctype html><html lang="es"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1"><title>Apps</title></head>
<body style="font-family:sans-serif;max-width:540px;margin:0 auto;padding:18px;color:#222">
<h2>Instalar apps del inventario</h2>
<p style="color:#555;font-size:14px">Toca la app para descargarla; cuando termine, ábrela para
instalar. Si Android lo pide, activa <b>«Orígenes desconocidos»</b> en Ajustes → Seguridad.</p>
<ul style="list-style:none;padding:0">%s</ul>
<p style="color:#888;font-size:13px">Para pasar archivos AL PC, usa <a href="/subir">/subir</a>.</p>
</body></html>""" % filas

@app.get("/descargar/<path:nombre>")
def descargar_archivo(nombre):
    """Sirve un archivo de la carpeta 'subidos' (para instalar apps en la
    pistola). Los .apk salen con el tipo correcto para que Android los instale."""
    nombre = os.path.basename(nombre)
    ruta = os.path.join(SUBIDOS, nombre)
    if not os.path.exists(ruta):
        return "No existe", 404
    from flask import send_file
    tipo = ("application/vnd.android.package-archive"
            if nombre.lower().endswith(".apk") else None)
    return send_file(ruta, mimetype=tipo, as_attachment=True, download_name=nombre)

@app.get("/api/estado")
def api_estado():
    d = db(); s = sesion_activa(d)
    return jsonify(ok=True, sesion_activa=(dict(s) if s else None))

# ------- JSON para refresco en vivo del frontend
@app.get("/api/dashboard")
def api_dashboard():
    d = db(); s = sesion_activa(d)
    tot = d.execute("SELECT COUNT(*) c FROM productos").fetchone()["c"]
    tags = d.execute("SELECT COUNT(*) c FROM tags").fetchone()["c"]
    leidos, ultimas = 0, []
    if s:
        leidos = d.execute("SELECT COUNT(*) c FROM lecturas WHERE sesion_id=?", (s["id"],)).fetchone()["c"]
        ultimas = [dict(r) for r in d.execute("""
            SELECT l.epc, l.dispositivo, l.ts, IFNULL(p.sku,'') sku, IFNULL(p.nombre,'') nombre
            FROM lecturas l LEFT JOIN tags t ON t.epc=l.epc
            LEFT JOIN productos p ON p.id=t.producto_id
            WHERE l.sesion_id=? ORDER BY l.id DESC LIMIT 12""", (s["id"],)).fetchall()]
    revisar_si_toca()   # abrir la pantalla dispara la revisión
    return jsonify(productos=tot, tags=tags, leidos=leidos,
                   sesion=(dict(s) if s else None), ultimas=ultimas,
                   respaldo=ULTIMO_RESPALDO,   # para avisar de la copia diaria
                   actualizacion=dict(ESTADO_ACTUALIZACION, version=VERSION))

@app.get("/api/sesiones/<int:sid>/resumen")
def api_resumen(sid):
    d = db()
    s = d.execute("SELECT * FROM sesiones WHERE id=?", (sid,)).fetchone()
    filas, desconocidos = resumen_sesion(d, sid)
    return jsonify(sesion=(dict(s) if s else None),
                   resumen=[dict(r) for r in filas],
                   seleccion=len(seleccion_sesion(d, sid)),
                   desconocidos=[dict(x) for x in desconocidos])

# ------- importar Excel / CSV (productos, precios y conteos de inventario)
IMPORT_CACHE = {}   # token -> {"filas": [...], "t": epoch}; caduca a los 15 min

# campos reconocibles y palabras que los delatan en los títulos de columna
# (el orden importa: lo más específico primero)
# (campo, palabras que lo delatan, palabras que lo DESCARTAN)
CAMPOS_IMPORT = [
    ("codigo_barras", ("barras", "ean"), ()),
    # antes de "nombre": "imagen"/"foto" no debe confundirse con descripción
    ("foto", ("foto", "imagen", "ruta imagen", "archivo imagen"), ()),
    ("posicion", ("posicion", "ubicacion exacta", "estante", "casilla",
                  "marca"), ()),
    ("oem", ("oem", "fabrica"), ()),
    # antes de sku: "referencias aplicables" también contiene "referencia"
    ("referencias", ("aplicable", "compatible", "equivalencia"), ()),
    ("sku", ("sku", "codigo", "referencia", "ref"), ("barras", "ean")),
    ("nombre", ("nombre", "descripcion", "producto", "articulo", "detalle"), ()),
    ("ubicacion", ("ubicacion", "bodega", "almacen", "sitio"), ()),
    # "stock mínimo" es una CANTIDAD, no un precio: por eso va antes que
    # precio_minimo y este lo descarta con sus palabras negativas
    ("cantidad", ("cantidad", "saldo", "stock", "existencia", "conteo",
                  "unidades", "cant", "total"), ("minimo",)),
    ("precio_minimo", ("minimo", "p. min", "p.min", "venta 2", "precio 2",
                       "mayorista", "mayor"),
     ("stock", "existencia", "cantidad", "saldo", "unidades")),
    ("proveedor", ("proveedor", "prov"), ()),
    ("precio", ("precio", "venta", "pvp", "valor"), ("minimo", "costo")),
]

def _sin_tildes(s):
    import unicodedata
    return "".join(ch for ch in unicodedata.normalize("NFD", str(s).lower())
                   if unicodedata.category(ch) != "Mn")

def _texto(v):
    """Celda a texto limpio; los números enteros de Excel pierden el '.0'."""
    if v is None:
        return ""
    if isinstance(v, float) and v.is_integer():
        return str(int(v))
    return str(v).strip()

def _num_ent(v):
    if v is None or v == "":
        return None
    try:
        return max(0, int(round(float(str(v).replace(",", ".")))))
    except (TypeError, ValueError):
        return None

def _num_precio(v):
    """Precio en pesos: entiende $ y separadores de miles/decimales
    ('$26.000', '26,000.50', '26000.0' -> 26000)."""
    if v is None or v == "":
        return None
    if isinstance(v, (int, float)):
        return max(0, int(round(float(v))))
    s = re.sub(r"[^\d.,-]", "", str(v))
    if not s.strip("-.,"):
        return None
    if "." in s and "," in s:
        dec = max(s.rfind("."), s.rfind(","))     # el último separador = decimal
        s = re.sub(r"[.,]", "", s[:dec])
    elif "." in s or "," in s:
        sep = "." if "." in s else ","
        partes = s.split(sep)
        # 2 partes y 1-2 dígitos al final = decimal; si no, separador de miles
        s = partes[0] if (len(partes) == 2 and len(partes[1]) in (1, 2)) \
            else "".join(partes)
    try:
        return max(0, int(s or 0))
    except ValueError:
        return None

def _leer_tabla(datos, nombre, hoja=None):
    """Archivo subido -> (hojas, hoja_usada, filas). Soporta .xlsx y .csv."""
    ext = os.path.splitext(nombre or "")[1].lower()
    if ext in (".csv", ".txt"):
        texto = None
        for enc in ("utf-8-sig", "latin-1"):
            try:
                texto = datos.decode(enc)
                break
            except UnicodeDecodeError:
                pass
        muestra = "\n".join((texto or "").splitlines()[:10])
        sep = ";" if muestra.count(";") > muestra.count(",") else ","
        return ([], "", [f for f in csv.reader(io.StringIO(texto or ""), delimiter=sep)])
    if ext in (".xlsx", ".xlsm"):
        import openpyxl
        wb = openpyxl.load_workbook(io.BytesIO(datos), data_only=True, read_only=True)
        hojas = wb.sheetnames
        usada = hoja if hoja in hojas else hojas[0]
        filas = [list(f) for f in wb[usada].iter_rows(values_only=True)]
        wb.close()
        return (hojas, usada, filas)
    raise ValueError("Formato no soportado: usa .xlsx o .csv "
                     "(si es un .xls viejo, ábrelo en Excel y guárdalo como .xlsx)")

def _detectar_encabezado(filas):
    """La fila de títulos = la que más palabras conocidas tenga (puede no ser
    la primera: el Excel del usuario los tiene en la fila 5)."""
    mejor, mejor_n = 0, 0
    for i, fila in enumerate(filas[:15]):
        n = sum(1 for c in fila
                if c and any(any(kw in _sin_tildes(c) for kw in kws)
                             for _, kws, _neg in CAMPOS_IMPORT))
        if n > mejor_n:
            mejor, mejor_n = i, n
    return mejor

def _mapear_columnas(encabezados):
    mapeo, usadas = {}, set()
    for campo, kws, negativas in CAMPOS_IMPORT:
        for i, enc in enumerate(encabezados):
            e = _sin_tildes(enc or "")
            if i in usadas or not e or not any(kw in e for kw in kws):
                continue
            if any(nk in e for nk in negativas):
                continue      # p.ej. "Stock mínimo" NO es el precio mínimo
            # las columnas de unidades por bodega (ALMACEN, BODEGA 1…) no son
            # la "ubicación" del producto: esas van con sus casillas propias
            if campo == "ubicacion" and re.match(r"^(almacen|bodega)\b", e):
                continue
            mapeo[campo] = i
            usadas.add(i)
            break
    return mapeo

@app.post("/api/importar/analizar")
def api_importar_analizar():
    f = request.files.get("archivo")
    if not f:
        return jsonify(ok=False, error="No llegó ningún archivo"), 400
    try:
        hojas, hoja, filas = _leer_tabla(f.read(), f.filename,
                                         request.form.get("hoja") or None)
    except ValueError as ex:
        return jsonify(ok=False, error=str(ex)), 400
    except Exception:
        return jsonify(ok=False, error="No se pudo leer el archivo. ¿Está dañado o abierto en Excel?"), 400
    filas = [list(fi) for fi in filas if any(str(c or "").strip() for c in fi)]
    if not filas:
        return jsonify(ok=False, error="El archivo está vacío"), 400
    ie = _detectar_encabezado(filas)
    encabezados = [str(c or "").strip() for c in filas[ie]]
    datos = filas[ie + 1:]
    ncol = max(len(encabezados), max((len(x) for x in datos[:80]), default=0))
    encabezados += [""] * (ncol - len(encabezados))
    ahora = time.time()
    for t in [k for k, v in IMPORT_CACHE.items() if ahora - v["t"] > 900]:
        IMPORT_CACHE.pop(t, None)
    token = secrets.token_hex(8)
    IMPORT_CACHE[token] = {"filas": datos, "enc": encabezados, "t": ahora}
    # columnas que parecen bodegas (ALMACEN, BODEGA 1..8) para unidades por bodega
    bodegas_sug = [i for i, enc in enumerate(encabezados)
                   if re.match(r"^(almacen|bodega)\b", _sin_tildes(enc or "").strip())
                   and "total" not in _sin_tildes(enc)]
    return jsonify(ok=True, token=token, hojas=hojas, hoja=hoja, total=len(datos),
                   columnas=[{"i": i, "titulo": encabezados[i] or f"Columna {i + 1}"}
                             for i in range(ncol)],
                   mapeo=_mapear_columnas(encabezados),
                   bodegas_sugeridas=bodegas_sug,
                   muestra=[[_texto(c) for c in (fi + [None] * ncol)[:ncol]]
                            for fi in datos[:5]])

@app.post("/api/importar/ejecutar")
def api_importar_ejecutar():
    fj = request.get_json(force=True)
    ent = IMPORT_CACHE.get(str(fj.get("token") or ""))
    if not ent:
        return jsonify(ok=False, error="La importación caducó: vuelve a elegir el archivo"), 400
    tipo = str(fj.get("tipo") or "productos")
    try:
        mapeo = {k: int(v) for k, v in (fj.get("mapeo") or {}).items()
                 if v is not None and str(v) != ""}
    except (TypeError, ValueError):
        return jsonify(ok=False, error="Mapeo de columnas inválido"), 400
    try:
        bods = [int(i) for i in (fj.get("bodegas") or [])] \
            if tipo in ("productos", "inventario") else []
    except (TypeError, ValueError):
        bods = []
    if "sku" not in mapeo:
        return jsonify(ok=False, error="Indica cuál columna trae la referencia (SKU)"), 400
    if tipo == "inventario" and "cantidad" not in mapeo and not bods:
        return jsonify(ok=False, error="Indica la columna de cantidad o marca las bodegas"), 400
    if tipo == "precios" and "precio" not in mapeo and "precio_minimo" not in mapeo:
        return jsonify(ok=False, error="Indica al menos una columna de precio"), 400
    if tipo == "fotos" and "foto" not in mapeo:
        return jsonify(ok=False, error="Indica cuál columna trae la foto (ruta o nombre del archivo)"), 400
    # la POSICIÓN (A1, F6…) va DENTRO de una bodega: hay que decir cuál
    bod_pos = str(fj.get("bodega_posicion") or "").strip().upper()[:40]
    if "posicion" in mapeo and not bod_pos:
        return jsonify(ok=False, error="Elige a qué bodega pertenecen esas posiciones"), 400
    if tipo == "posiciones" and "posicion" not in mapeo:
        return jsonify(ok=False, error="Indica cuál columna trae la posición (A1, F6…)"), 400
    if tipo == "referencias" and "referencias" not in mapeo:
        return jsonify(ok=False, error="Indica cuál columna trae las referencias aplicables"), 400
    permitidos = {
        "productos": ("sku", "nombre", "oem", "referencias", "ubicacion", "cantidad",
                      "precio_minimo", "precio", "proveedor", "codigo_barras",
                      "foto", "posicion"),
        "precios": ("sku", "precio_minimo", "precio", "proveedor"),
        "inventario": ("sku", "cantidad"),
        "fotos": ("sku", "foto"),
        "posiciones": ("sku", "posicion"),
        "referencias": ("sku", "referencias"),
    }.get(tipo)
    if not permitidos:
        return jsonify(ok=False, error="Tipo de importación desconocido"), 400
    mapeo = {k: v for k, v in mapeo.items() if k in permitidos}
    enc = ent.get("enc") or []
    d = db()
    provs = {_sin_tildes(r["nombre"]): r["codigo"]
             for r in d.execute("SELECT codigo, nombre FROM proveedores")}
    creados = actualizados = sin_cambios = 0
    no_encontrados, errores = [], []
    TXT = ("nombre", "oem", "ubicacion", "codigo_barras", "referencias", "foto")

    def val(fila, campo):
        i = mapeo.get(campo)
        return fila[i] if i is not None and i < len(fila) else None

    for nf, fila in enumerate(ent["filas"], start=1):
        sku = _texto(val(fila, "sku"))
        if not sku:
            continue
        try:
            p = d.execute("SELECT * FROM productos WHERE sku=? COLLATE NOCASE",
                          (sku,)).fetchone()
            vals = {}
            if "nombre" in mapeo and _texto(val(fila, "nombre")):
                vals["nombre"] = _texto(val(fila, "nombre"))[:120]
            if "oem" in mapeo:
                vals["oem"] = _texto(val(fila, "oem"))[:120]
            if "referencias" in mapeo:
                vals["referencias"] = _texto(val(fila, "referencias"))[:20000]
            if "ubicacion" in mapeo:
                vals["ubicacion"] = _texto(val(fila, "ubicacion"))[:60]
            if "cantidad" in mapeo and _num_ent(val(fila, "cantidad")) is not None:
                vals["cantidad_esperada"] = _num_ent(val(fila, "cantidad"))
            for cp in ("precio_minimo", "precio"):
                if cp in mapeo and _num_precio(val(fila, cp)) is not None:
                    vals[cp] = _num_precio(val(fila, cp))
            if "proveedor" in mapeo:
                t = _texto(val(fila, "proveedor"))
                cod = None
                if t.isdigit():
                    cod = int(t)
                elif t:
                    tn = _sin_tildes(t)
                    cod = provs.get(tn) or next(
                        (c for nb, c in provs.items() if tn in nb or nb in tn), None)
                if cod is not None:
                    vals["proveedor"] = cod
            if "foto" in mapeo:
                fo = _texto(val(fila, "foto"))
                # puede venir la ruta completa o SOLO el nombre del archivo
                # (típico al exportar de otro programa): si es solo el nombre,
                # se completa con la carpeta de fotos configurada
                if fo and not os.path.isabs(fo) and "\\" not in fo and "/" not in fo:
                    base_fotos = (cfg().get("fotos_ruta") or "").strip()
                    if base_fotos:
                        fo = os.path.join(base_fotos, fo)
                if fo:
                    vals["foto"] = fo[:400]
            if "codigo_barras" in mapeo:
                cb = re.sub(r"\D", "", _texto(val(fila, "codigo_barras")))
                # el sistema guarda los EAN-13 SIN su dígito de control (12):
                # ese dígito se calcula solo al imprimir y al buscar. Si el
                # archivo lo trae completo y el control cuadra, se quita para
                # que quede en el mismo formato que los códigos propios.
                if len(cb) == 13 and ean13_control(cb[:12]) == cb:
                    cb = cb[:12]
                if cb:
                    vals["codigo_barras"] = cb
            # unidades POR BODEGA: cada columna marcada es una bodega y su
            # celda las unidades; None en todas = la fila no trae ese dato
            filas_b = None
            if bods:
                celdas = [((_texto(enc[i]) if i < len(enc) and _texto(enc[i])
                            else f"BODEGA {i + 1}"),
                           _num_ent(fila[i]) if i < len(fila) else None)
                          for i in bods]
                if any(q is not None for _, q in celdas):
                    filas_b = [{"bodega": n, "cantidad": q} for n, q in celdas if q]
            if p is None:
                if tipo != "productos":
                    no_encontrados.append(sku)
                    continue
                if not vals.get("nombre"):
                    errores.append(f"fila {nf}: '{sku}' es nuevo y la fila no trae nombre")
                    continue
                cur = d.execute(
                    """INSERT INTO productos(sku,nombre,oem,ubicacion,cantidad_esperada,
                       precio_minimo,precio,proveedor,codigo_barras,referencias,foto)
                       VALUES(?,?,?,?,?,?,?,?,?,?,?)""",
                    (sku, vals["nombre"], vals.get("oem", ""), vals.get("ubicacion", ""),
                     vals.get("cantidad_esperada", 0), vals.get("precio_minimo", 0),
                     vals.get("precio", 0), vals.get("proveedor", 0),
                     vals.get("codigo_barras", ""), vals.get("referencias", ""),
                     vals.get("foto", "")))
                pid, creados = cur.lastrowid, creados + 1
                if filas_b is not None:
                    fijar_bodegas(d, pid, filas_b, origen="importacion", es_venta=False)
                existia = False
                cambio_precio = True
                fin = {"precio_minimo": vals.get("precio_minimo", 0),
                       "precio": vals.get("precio", 0),
                       "proveedor": vals.get("proveedor", 0),
                       "codigo_barras": vals.get("codigo_barras", "")}
            else:
                pid = p["id"]
                difs = {k: v for k, v in vals.items()
                        if v != (p[k] if p[k] is not None else ("" if k in TXT else 0))}
                if difs:
                    if "cantidad_esperada" in difs:
                        # es_venta=False: cargar un archivo NO es vender — si no,
                        # cada importación ensuciaría el informe de más vendidos
                        registrar_salida(d, pid, p["cantidad_esperada"],
                                         difs["cantidad_esperada"], "importacion",
                                         es_venta=False)
                    d.execute("UPDATE productos SET " + ", ".join(f"{k}=?" for k in difs)
                              + " WHERE id=?", (*difs.values(), pid))
                cambio = bool(difs)
                if filas_b is not None and fijar_bodegas(d, pid, filas_b, origen="importacion",
                                                        es_venta=False):
                    cambio = True
                existia = True     # el contador se decide tras fijar la posición
                cambio_precio = any(k in difs for k in ("precio_minimo", "precio", "proveedor"))
                fin = {k: vals.get(k, p[k] or 0)
                       for k in ("precio_minimo", "precio", "proveedor")}
                fin["codigo_barras"] = vals.get("codigo_barras", p["codigo_barras"] or "")
            # POSICIÓN dentro de la bodega elegida (A1, F6…). Se guarda sin
            # tocar las cantidades: si el producto todavía no tenía detalle por
            # bodega, la fila nueva se crea con TODO su stock actual para que
            # el total siga cuadrando (si no, quedaría en cero).
            cambio_pos = False
            if "posicion" in mapeo and bod_pos:
                po = _texto(val(fila, "posicion")).strip().upper()[:20]
                if po:
                    ya = d.execute("""SELECT IFNULL(posicion,'') posicion
                                      FROM stock_bodegas
                                      WHERE producto_id=? AND bodega=?""",
                                   (pid, bod_pos)).fetchone()
                    if ya:
                        if ya["posicion"] != po:
                            d.execute("""UPDATE stock_bodegas SET posicion=?
                                         WHERE producto_id=? AND bodega=?""",
                                      (po, pid, bod_pos))
                            cambio_pos = True
                    else:
                        cambio_pos = True
                        hay = d.execute("SELECT COUNT(*) c FROM stock_bodegas "
                                        "WHERE producto_id=?", (pid,)).fetchone()["c"]
                        cant0 = 0
                        if not hay:
                            pr = d.execute("SELECT cantidad_esperada FROM productos "
                                           "WHERE id=?", (pid,)).fetchone()
                            cant0 = (pr["cantidad_esperada"] or 0) if pr else 0
                        d.execute("""INSERT INTO stock_bodegas(producto_id,bodega,
                                     cantidad,posicion) VALUES(?,?,?,?)""",
                                  (pid, bod_pos, cant0, po))
                        if not hay:
                            d.execute("UPDATE productos SET ubicacion=? WHERE id=?",
                                      (bod_pos, pid))
            if existia:
                if cambio or cambio_pos:
                    actualizados += 1
                else:
                    sin_cambios += 1
            # regenerar el código de barras si cambió precio/proveedor o no había
            if "codigo_barras" not in vals and (fin["precio_minimo"] or fin["precio"]) \
                    and (cambio_precio or not fin["codigo_barras"]):
                nuevo = generar_codigo_barras(pid, fin["precio_minimo"],
                                              fin["precio"], fin["proveedor"])
                if nuevo and nuevo != fin["codigo_barras"]:
                    d.execute("UPDATE productos SET codigo_barras=? WHERE id=?", (nuevo, pid))
        except Exception as ex:
            if len(errores) < 30:
                errores.append(f"fila {nf} ({sku}): {ex}")
    d.commit()
    return jsonify(ok=True, creados=creados, actualizados=actualizados,
                   sin_cambios=sin_cambios,
                   no_encontrados=len(no_encontrados),
                   no_encontrados_lista=no_encontrados[:15],
                   errores=errores[:15])

# ------- API JSON del modo escritorio (ventana de PC estilo FactuSOL)
def rotacion_vendidos(d, c=None):
    """Unidades VENDIDAS por producto en los últimos «rotacion_dias» días.
    Solo cuentan las salidas marcadas como venta (los ajustes y las
    importaciones no son ventas, así que no ensucian el semáforo)."""
    c = c or cfg()
    try:
        dias = max(1, int(c.get("rotacion_dias", 180)))
    except (TypeError, ValueError):
        dias = 180
    desde = (datetime.now() - timedelta(days=dias)).isoformat()
    return {r["producto_id"]: r["u"] for r in d.execute(
        """SELECT producto_id, SUM(cantidad) u FROM salidas
           WHERE es_venta=1 AND ts >= ? GROUP BY producto_id""", (desde,))}

NIVELES_ROT = ("alta", "media", "baja")

def nivel_rotacion(vendidos, c=None):
    """alta / media / baja según lo vendido en el periodo."""
    c = c or cfg()
    try:
        alta = max(1, int(c.get("rotacion_alta", 10)))
        media = max(1, int(c.get("rotacion_media", 3)))
    except (TypeError, ValueError):
        alta, media = 10, 3
    if vendidos >= alta:
        return "alta"
    if vendidos >= media:
        return "media"
    return "baja"

@app.get("/api/productos")
def api_productos():
    d = db()
    rows = d.execute("""SELECT p.id, p.sku, p.nombre, IFNULL(p.oem,'') oem,
                               IFNULL(p.ubicacion,'') ubicacion,
                               p.cantidad_esperada, COUNT(t.epc) n_tags,
                               IFNULL(p.precio_minimo,0) precio_minimo,
                               IFNULL(p.precio,0) precio,
                               IFNULL(p.codigo_barras,'') codigo_barras,
                               IFNULL(p.proveedor,0) proveedor,
                               IFNULL(p.foto,'') foto,
                               IFNULL(p.rotacion_manual,'') rotacion_manual
                        FROM productos p LEFT JOIN tags t ON t.producto_id=p.id
                        GROUP BY p.id ORDER BY p.nombre""").fetchall()
    c = cfg()
    vendidos = rotacion_vendidos(d, c)
    out = []
    for r in rows:
        r = dict(r)
        cb = r["codigo_barras"]
        # el buscador también debe encontrar por el EAN-13 COMPLETO (13
        # dígitos, con el de control) que es lo que trae la etiqueta impresa;
        # en la base solo se guardan los 12 sin control
        r["codigo_barras_ean"] = ean13_control(cb) if len(cb) == 12 and cb.isdigit() else ""
        # semáforo de rotación (verde/ámbar/rojo). Si alguien lo puso A MANO,
        # ese manda sobre lo que digan las ventas.
        r["vendidos"] = vendidos.get(r["id"], 0)
        r["rotacion_auto"] = nivel_rotacion(r["vendidos"], c)
        manual = r["rotacion_manual"] if r["rotacion_manual"] in NIVELES_ROT else ""
        r["rotacion_manual"] = manual
        r["rotacion"] = manual or r["rotacion_auto"]
        out.append(r)
    return jsonify(out)

@app.get("/api/estadisticas/ventas")
def api_estadisticas_ventas():
    """Productos que MÁS SE VENDEN en el periodo (?periodo=dia|mes|ano).
    Se calcula con las BAJADAS de stock registradas en la tabla salidas
    (ajustes, fijar stock, conteos, importaciones): menos stock = venta."""
    periodo = request.args.get("periodo", "mes")
    hoy = datetime.now()
    if periodo == "dia":
        desde = hoy.strftime("%Y-%m-%dT00:00:00")
    elif periodo == "ano":
        desde = hoy.strftime("%Y-01-01T00:00:00")
    else:
        periodo = "mes"
        desde = hoy.strftime("%Y-%m-01T00:00:00")
    d = db()
    rows = d.execute("""
        SELECT p.id, p.sku, p.nombre, p.cantidad_esperada stock,
               SUM(s.cantidad) unidades, COUNT(s.id) veces
        FROM salidas s JOIN productos p ON p.id = s.producto_id
        WHERE s.ts >= ? AND s.es_venta = 1
        GROUP BY p.id ORDER BY unidades DESC, veces DESC LIMIT 50""",
        (desde,)).fetchall()
    total = d.execute("SELECT IFNULL(SUM(cantidad),0) t FROM salidas "
                      "WHERE ts >= ? AND es_venta = 1",
                      (desde,)).fetchone()["t"]
    # serie de tiempo para la gráfica de línea: por hora (día), por día (mes)
    # o por mes (año) — ts es ISO "2026-07-16T10:39:00"
    pos, ln = {"dia": (12, 2), "mes": (9, 2), "ano": (6, 2)}[periodo]
    mapa = {r["k"]: r["u"] for r in d.execute(
        f"SELECT substr(ts,{pos},{ln}) k, SUM(cantidad) u FROM salidas "
        "WHERE ts >= ? AND es_venta = 1 GROUP BY k", (desde,))}
    MESES = ["Ene", "Feb", "Mar", "Abr", "May", "Jun",
             "Jul", "Ago", "Sep", "Oct", "Nov", "Dic"]
    if periodo == "dia":
        serie = [{"etiqueta": f"{h}h", "unidades": mapa.get(f"{h:02d}", 0)}
                 for h in range(0, hoy.hour + 1)]
    elif periodo == "ano":
        serie = [{"etiqueta": MESES[m - 1], "unidades": mapa.get(f"{m:02d}", 0)}
                 for m in range(1, hoy.month + 1)]
    else:
        serie = [{"etiqueta": str(dd), "unidades": mapa.get(f"{dd:02d}", 0)}
                 for dd in range(1, hoy.day + 1)]
    return jsonify(ok=True, periodo=periodo, desde=desde, total_unidades=total,
                   serie=serie, productos=[dict(r) for r in rows])

def _autofit(ws, cap=55, min_w=9):
    """Ajusta el ancho de cada columna al contenido (para no estirar a mano)."""
    for col in ws.columns:
        letra = None
        largo = min_w
        for cel in col:
            if letra is None and cel.column_letter:
                letra = cel.column_letter
            if cel.value is not None:
                largo = max(largo, len(str(cel.value)) + 2)
        if letra:
            ws.column_dimensions[letra].width = min(largo, cap)

@app.get("/api/exportar/productos")

def api_exportar_productos():
    """Exporta TODOS los productos a Excel. Hoja 'productos' = plantilla que se
    puede re-importar; hoja 'valorizacion' = valor del inventario por bodega y
    total, al precio de venta y al COSTO (precio menos el % configurado)."""
    from openpyxl import Workbook
    from openpyxl.styles import Font, Alignment, PatternFill
    c = cfg()
    factor = max(0.0, (100 - float(c.get("costo_descuento", 48))) / 100.0)
    pct = int(c.get("costo_descuento", 48))
    d = db()
    prods = d.execute("SELECT * FROM productos ORDER BY nombre").fetchall()
    bods = [r["bodega"] for r in d.execute(
        "SELECT DISTINCT bodega FROM stock_bodegas ORDER BY bodega")]
    stock = {}
    for r in d.execute("SELECT producto_id, bodega, cantidad FROM stock_bodegas"):
        stock.setdefault(r["producto_id"], {})[r["bodega"]] = r["cantidad"]

    wb = Workbook()
    neg = Font(bold=True)
    encab = Font(bold=True, color="FFFFFF")
    relleno = PatternFill("solid", fgColor="1F7A44")
    pesos = '"$"#,##0'

    # ---- hoja 1: productos (plantilla re-importable) ----
    ws = wb.active; ws.title = "productos"
    cols = ["Codigo (SKU)", "Nombre", "Referencia fabrica (OEM)",
            "Referencias aplicables", "Proveedor", "Precio minimo",
            "Precio normal", "Codigo de barras", "Stock total"] + bods
    ws.append(cols)
    for cel in ws[1]:
        cel.font = encab; cel.fill = relleno
    for p in prods:
        sb = stock.get(p["id"], {})
        ws.append([p["sku"], p["nombre"], p["oem"] or "",
                   (p["referencias"] if "referencias" in p.keys() else "") or "",
                   p["proveedor"] or "", p["precio_minimo"] or 0, p["precio"] or 0,
                   p["codigo_barras"] or "", p["cantidad_esperada"] or 0]
                  + [sb.get(b, "") for b in bods])
    # formato de números: precios en pesos
    for fila in ws.iter_rows(min_row=2, min_col=6, max_col=7):
        for cel in fila:
            cel.number_format = pesos
    ws.freeze_panes = "A2"
    _autofit(ws)
    ws.column_dimensions["D"].width = 32   # referencias aplicables: tope

    # ---- hoja 2: valorización por bodega ----
    val = {}   # bodega -> [unidades, valor_venta]
    for p in prods:
        precio = p["precio"] or 0
        sb = stock.get(p["id"], {})
        asignado = 0
        for b, cant in sb.items():
            asignado += cant
            v = val.setdefault(b, [0, 0.0]); v[0] += cant; v[1] += precio * cant
        resto = (p["cantidad_esperada"] or 0) - asignado
        if resto > 0:
            v = val.setdefault("(sin bodega asignada)", [0, 0.0])
            v[0] += resto; v[1] += precio * resto
    wv = wb.create_sheet("valorizacion")
    wv.append([f"Valorización del inventario  ·  costo = precio − {pct}%"])
    wv["A1"].font = Font(bold=True, size=13)
    wv.append([])
    wv.append(["Bodega", "Unidades", "Valor de venta", f"Costo (−{pct}%)"])
    for cel in wv[3]:
        cel.font = encab; cel.fill = relleno
    tot_u = tot_v = 0
    for b in sorted(val):
        u, vv = val[b]
        wv.append([b, u, round(vv), round(vv * factor)])
        tot_u += u; tot_v += vv
    fila_tot = wv.max_row + 1
    wv.append(["TOTAL", tot_u, round(tot_v), round(tot_v * factor)])
    for cel in wv[fila_tot]:
        cel.font = neg
    for fila in wv.iter_rows(min_row=4, min_col=3, max_col=4):
        for cel in fila:
            cel.number_format = pesos
    _autofit(wv)

    buf = io.BytesIO(); wb.save(buf); buf.seek(0)
    from flask import send_file
    return send_file(
        buf, as_attachment=True,
        download_name=f"productos_{datetime.now():%Y-%m-%d}.xlsx",
        mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")

@app.get("/api/proveedores")
def api_proveedores():
    d = db()
    rows = d.execute("SELECT codigo, nombre FROM proveedores ORDER BY codigo").fetchall()
    return jsonify([dict(r) for r in rows])

@app.post("/api/proveedores")
def api_proveedor_nuevo():
    """Agrega un proveedor. El código es el número con el que EMPIEZAN los
    códigos de barras de sus productos, así que debe ser único y cortico."""
    d = db(); f = request.get_json(force=True) or {}
    nombre = str(f.get("nombre") or "").strip().upper()[:60]
    try:
        codigo = int(f.get("codigo"))
    except (TypeError, ValueError):
        return jsonify(ok=False, error="El código debe ser un número"), 400
    if not (1 <= codigo <= 9999):
        return jsonify(ok=False, error="El código debe estar entre 1 y 9999"), 400
    if not nombre:
        return jsonify(ok=False, error="Escribe el nombre del proveedor"), 400
    ya = d.execute("SELECT nombre FROM proveedores WHERE codigo=?", (codigo,)).fetchone()
    if ya:
        return jsonify(ok=False,
                       error=f"El código {codigo} ya es de {ya['nombre']}"), 400
    d.execute("INSERT INTO proveedores(codigo,nombre) VALUES(?,?)", (codigo, nombre))
    d.commit()
    return jsonify(ok=True, codigo=codigo, nombre=nombre)

@app.post("/api/productos/guardar")
def api_producto_guardar():
    d = db(); f = request.get_json(force=True)
    sku = str(f.get("sku", "")).strip()
    nombre = str(f.get("nombre", "")).strip()
    if not sku or not nombre:
        return jsonify(ok=False, error="El código y el nombre son obligatorios"), 400
    def entero(k):
        try:
            return max(0, int(f.get(k) or 0))
        except (TypeError, ValueError):
            return 0
    # stock y ubicación SOLO se tocan si vienen en el formulario (el escritorio
    # ya no los manda: allá se manejan con «Fijar stock» / bodegas)
    cant = entero("cantidad") if "cantidad" in f else None
    ubi = str(f.get("ubicacion", "")).strip() if "ubicacion" in f else None
    pmin = entero("precio_minimo")
    pnor = entero("precio")
    prov = entero("proveedor")
    oem = str(f.get("oem", "")).strip()
    cb = str(f.get("codigo_barras", "")).strip()
    # En pantalla el código se muestra COMPLETO (13 dígitos, igual que en el
    # rótulo impreso), pero se guarda sin el dígito de control: ese se calcula
    # solo al imprimir y al buscar. Si vuelve el de 13 y el control cuadra, se
    # quita — así el código guardado no cambia por el simple hecho de abrir la
    # ficha y darle Guardar.
    if len(cb) == 13 and cb.isdigit() and ean13_control(cb[:12]) == cb:
        cb = cb[:12]
    foto = str(f.get("foto", "")).strip()
    # Si solo escribieron el NOMBRE del archivo (032905106B.jpg), se completa
    # con la carpeta de fotos configurada: así no hay que pegar la ruta larga
    # en cada producto.
    if foto and not os.path.isabs(foto) and "\\" not in foto and "/" not in foto:
        base_fotos = (cfg().get("fotos_ruta") or "").strip()
        if base_fotos:
            foto = os.path.join(base_fotos, foto)
    # referencias aplicables (pueden ser miles de caracteres): solo se tocan
    # si el formulario las manda — así una ficha que no alcanzó a cargarlas
    # no las borra al guardar
    refs = str(f.get("referencias") or "").strip() if "referencias" in f else None
    try:
        auto_regenerar = False
        if f.get("id"):
            pid = f["id"]
            # El código de barras lleva DENTRO el proveedor y los precios: si
            # alguno de esos cambia, el código guardado queda desfasado (deja
            # de coincidir con el que se imprime en la etiqueta). Se regenera
            # solo, salvo que el usuario haya escrito uno a mano.
            ant = d.execute("""SELECT precio_minimo, precio, proveedor, codigo_barras
                               FROM productos WHERE id=?""", (pid,)).fetchone()
            if ant:
                cambio = ((ant["precio_minimo"] or 0) != pmin
                          or (ant["precio"] or 0) != pnor
                          or (ant["proveedor"] or 0) != prov)
                # "a mano" = lo que llegó es distinto de lo que ya estaba guardado
                escrito_a_mano = cb and cb != (ant["codigo_barras"] or "")
                auto_regenerar = bool(cambio and not escrito_a_mano)
            sets = {"sku": sku, "nombre": nombre, "oem": oem, "precio_minimo": pmin,
                    "precio": pnor, "codigo_barras": cb, "proveedor": prov, "foto": foto}
            if cant is not None:
                sets["cantidad_esperada"] = cant
                antes = d.execute("SELECT cantidad_esperada FROM productos WHERE id=?",
                                  (pid,)).fetchone()
                if antes:
                    registrar_salida(d, pid, antes["cantidad_esperada"], cant, "ficha")
            if ubi is not None:
                sets["ubicacion"] = ubi
            if refs is not None:
                sets["referencias"] = refs
            d.execute("UPDATE productos SET " + ", ".join(f"{k}=?" for k in sets)
                      + " WHERE id=?", (*sets.values(), pid))
        else:
            cur = d.execute("""INSERT INTO productos(sku,nombre,oem,ubicacion,
                               cantidad_esperada,precio_minimo,precio,codigo_barras,proveedor,foto,
                               referencias)
                               VALUES(?,?,?,?,?,?,?,?,?,?,?)""",
                            (sku, nombre, oem, ubi or "", cant or 0,
                             pmin, pnor, cb, prov, foto, refs or ""))
            pid = cur.lastrowid
        # Sin código escrito a mano -> se genera solo con proveedor + precios
        # (estilo FactuSOL). Dejar el campo vacío regenera el código, y también
        # se regenera si cambiaron los precios o el proveedor (van dentro).
        if not cb or auto_regenerar:
            d.execute("UPDATE productos SET codigo_barras=? WHERE id=?",
                      (generar_codigo_barras(pid, pmin, pnor, prov), pid))
        # existencias por bodega: si el formulario las manda, ellas mandan
        # (recalculan el total y la ubicación)
        if isinstance(f.get("bodegas"), list):
            fijar_bodegas(d, pid, f["bodegas"])
        d.commit()
    except sqlite3.IntegrityError:
        return jsonify(ok=False, error=f"Ya existe otro producto con el código {sku}"), 400
    n = d.execute("SELECT codigo_barras FROM productos WHERE id=?", (pid,)).fetchone()
    return jsonify(ok=True, codigo_barras=(n["codigo_barras"] if n else ""))

@app.post("/api/productos/revisar_codigos")
def api_revisar_codigos():
    """Busca productos cuyo código de barras GUARDADO ya no corresponde a sus
    precios/proveedor de hoy (pasa si se les asignó el proveedor después de
    generar el código). Con {"aplicar": true} los corrige.
    Nunca toca códigos de productos sin precio (esos no llevan código)."""
    d = db()
    aplicar = bool((request.get_json(silent=True) or {}).get("aplicar"))
    rows = d.execute("""SELECT id, sku, nombre, codigo_barras, precio_minimo,
                               precio, proveedor
                        FROM productos WHERE IFNULL(codigo_barras,'')!=''""").fetchall()
    desfasados = []
    for r in rows:
        nuevo = generar_codigo_barras(r["id"], r["precio_minimo"] or 0,
                                      r["precio"] or 0, r["proveedor"] or 0)
        # SOLO se corrigen los códigos que generó este sistema ANTES de que el
        # producto tuviera proveedor. Un código traído de otro programa (o
        # escrito a mano) NO se toca aunque no coincida con nuestra fórmula.
        sin_prov = generar_codigo_barras(r["id"], r["precio_minimo"] or 0,
                                         r["precio"] or 0, 0)
        if r["codigo_barras"] != sin_prov:
            continue
        if nuevo and nuevo != r["codigo_barras"]:
            desfasados.append({"id": r["id"], "sku": r["sku"], "nombre": r["nombre"],
                               "antes": r["codigo_barras"], "ahora": nuevo})
            if aplicar:
                d.execute("UPDATE productos SET codigo_barras=? WHERE id=?",
                          (nuevo, r["id"]))
    if aplicar:
        d.commit()
    return jsonify(ok=True, aplicado=aplicar, total=len(desfasados),
                   productos=desfasados[:200])

@app.get("/api/bodegas")
def api_bodegas():
    """Bodegas conocidas para elegir (las estándar + las que ya están en uso),
    así un error de escritura no crea una bodega que no existe."""
    d = db()
    base = ["ALMACEN"] + [f"BODEGA {i}" for i in range(1, 9)]
    usadas = [r["bodega"] for r in d.execute(
        "SELECT DISTINCT bodega FROM stock_bodegas ORDER BY bodega")]
    vistas, out = set(), []
    for b in base + usadas:
        bn = str(b or "").strip().upper()
        if bn and bn not in vistas:
            vistas.add(bn)
            out.append(bn)
    return jsonify(out)

def _raiz_busqueda(p):
    """«pastillas» -> «pastilla», «motores» -> «motor»: buscando la raíz, da
    igual escribir en singular o en plural."""
    if len(p) > 4 and p.lower().endswith("es"):
        return p[:-2]
    if len(p) > 3 and p.lower().endswith("s"):
        return p[:-1]
    return p

@app.get("/api/productos/buscar_refs")
def api_buscar_refs():
    """Ids de productos cuyas REFERENCIAS APLICABLES contienen el texto.
    El buscador del escritorio pregunta aquí aparte, porque esas listas son
    enormes y no viajan con la tabla de productos."""
    q = (request.args.get("q") or "").strip()
    if len(q) < 2:
        return jsonify([])
    # se busca por PALABRAS sueltas y en cualquier orden: "pastillas t5"
    # encuentra las que tengan las dos, estén como estén escritas. Se usa la
    # RAÍZ de cada palabra (pastillas -> pastilla) para que singular y plural
    # den lo mismo.
    palabras = [_raiz_busqueda(p) for p in q.split() if p][:8]
    cond = " AND ".join(["referencias LIKE ?"] * len(palabras))
    d = db()
    rows = d.execute(f"SELECT id FROM productos WHERE {cond} LIMIT 500",
                     tuple("%" + p + "%" for p in palabras)).fetchall()
    return jsonify([r["id"] for r in rows])

@app.get("/api/productos/<int:pid>/referencias")
def api_producto_referencias(pid):
    """Las referencias aplicables se cargan aparte: pueden ser miles de
    caracteres y no conviene mandarlas con toda la tabla de productos."""
    d = db()
    n = d.execute("SELECT IFNULL(referencias,'') r FROM productos WHERE id=?",
                  (pid,)).fetchone()
    if not n:
        return jsonify(ok=False, error="El producto no existe"), 404
    return jsonify(ok=True, referencias=n["r"])

@app.post("/api/productos/<int:pid>/referencias")
def api_producto_referencias_guardar(pid):
    """Guarda SOLO las referencias aplicables. Es lo único que pueden cambiar
    los VENDEDORES (su ventana no toca precios, stock ni nada más)."""
    d = db(); f = request.get_json(force=True)
    if not d.execute("SELECT 1 FROM productos WHERE id=?", (pid,)).fetchone():
        return jsonify(ok=False, error="El producto no existe"), 404
    refs = str(f.get("referencias") or "").strip()[:20000]
    d.execute("UPDATE productos SET referencias=? WHERE id=?", (refs, pid))
    d.commit()
    return jsonify(ok=True, referencias=refs)

@app.get("/api/productos/<int:pid>/bodegas")
def api_producto_bodegas(pid):
    d = db()
    rows = d.execute("""SELECT bodega, cantidad, IFNULL(posicion,'') posicion
                        FROM stock_bodegas
                        WHERE producto_id=? ORDER BY bodega""", (pid,)).fetchall()
    return jsonify([dict(r) for r in rows])

@app.post("/api/productos/<int:pid>/rotacion")
def api_producto_rotacion(pid):
    """Fija A MANO el semáforo de rotación de un producto, o lo devuelve a
    automático mandando nivel vacío. No toca nada más del producto."""
    d = db(); f = request.get_json(force=True)
    p = d.execute("SELECT sku FROM productos WHERE id=?", (pid,)).fetchone()
    if not p:
        return jsonify(ok=False, error="El producto no existe"), 404
    nivel = str(f.get("nivel") or "").strip().lower()
    if nivel and nivel not in NIVELES_ROT:
        return jsonify(ok=False, error="Nivel inválido (alta, media o baja)"), 400
    d.execute("UPDATE productos SET rotacion_manual=? WHERE id=?", (nivel, pid))
    d.commit()
    return jsonify(ok=True, nivel=nivel, sku=p["sku"],
                   msg=(f"✔ Rotación de {p['sku']} puesta a mano en {nivel.upper()}"
                        if nivel else
                        f"✔ Rotación de {p['sku']} vuelve a calcularse sola con las ventas"))

@app.post("/api/productos/<int:pid>/posiciones")
def api_producto_posiciones(pid):
    """Guarda SOLO la posición (A1, F6…) de cada bodega del producto. No toca
    las cantidades: eso es «Fijar stock». Lo usa la ficha de Modificar."""
    d = db(); f = request.get_json(force=True)
    filas = f.get("posiciones")
    if not isinstance(filas, list):
        return jsonify(ok=False, error="Faltan las posiciones"), 400
    cambios = 0
    for it in filas:
        b = str((it or {}).get("bodega") or "").strip().upper()[:40]
        po = str((it or {}).get("posicion") or "").strip().upper()[:20]
        if not b:
            continue
        cur = d.execute("""UPDATE stock_bodegas SET posicion=?
                           WHERE producto_id=? AND bodega=?
                             AND IFNULL(posicion,'')!=?""", (po, pid, b, po))
        cambios += cur.rowcount
    d.commit()
    return jsonify(ok=True, cambios=cambios)

@app.post("/api/productos/<int:pid>/bodegas")
def api_producto_bodegas_fijar(pid):
    """Fija las existencias por bodega (botón Fijar stock del escritorio).
    motivo="ajuste" = la bajada NO fue venta (no cuenta en más vendidos)."""
    d = db(); f = request.get_json(force=True)
    if not isinstance(f.get("bodegas"), list):
        return jsonify(ok=False, error="Faltan las bodegas"), 400
    fijar_bodegas(d, pid, f["bodegas"],
                  es_venta=str(f.get("motivo") or "venta") != "ajuste")
    d.commit()
    n = d.execute("SELECT cantidad_esperada, IFNULL(ubicacion,'') u "
                  "FROM productos WHERE id=?", (pid,)).fetchone()
    return jsonify(ok=True, cantidad=(n["cantidad_esperada"] if n else 0),
                   ubicacion=(n["u"] if n else ""))

@app.get("/api/productos/<int:pid>/foto_img")
def api_producto_foto_img(pid):
    """Sirve la IMAGEN del producto (la asignada a mano o la que se encuentra
    sola en la carpeta de fotos) para mostrarla en la ventana de información."""
    d = db(); c = cfg()
    p = d.execute("SELECT sku, nombre, IFNULL(foto,'') foto FROM productos WHERE id=?",
                  (pid,)).fetchone()
    if not p:
        return jsonify(ok=False), 404
    ruta = (p["foto"] or "").strip()
    if not (ruta and os.path.exists(ruta)):
        ruta = buscar_foto(c, str(p["sku"]), p["nombre"])
    if not ruta:
        return jsonify(ok=False), 404
    try:
        from flask import send_file
        return send_file(ruta)
    except Exception:
        return jsonify(ok=False), 404

@app.post("/api/productos/<int:pid>/foto")
def api_producto_foto(pid):
    """Asigna (o quita, con ruta vacía) el archivo exacto de la foto."""
    d = db(); f = request.get_json(force=True)
    d.execute("UPDATE productos SET foto=? WHERE id=?",
              (str(f.get("ruta") or "").strip(), pid))
    d.commit()
    return jsonify(ok=True)

@app.post("/api/dialogo_archivo")
def api_dialogo_archivo():
    """Abre el explorador de archivos DE WINDOWS (en el PC donde corre el
    programa) para elegir una imagen; devuelve la ruta elegida."""
    c = cfg()
    inicio = (c.get("fotos_ruta") or "").strip()
    try:
        import webview
        if webview.windows:
            r = webview.windows[0].create_file_dialog(
                webview.OPEN_DIALOG, directory=inicio,
                file_types=("Imágenes (*.jpg;*.jpeg;*.png;*.bmp;*.gif;*.webp;*.jfif)",
                            "Todos los archivos (*.*)"))
            return jsonify(ok=True, ruta=(r[0] if r else ""))
    except Exception:
        pass
    return jsonify(ok=False, error="El explorador solo se abre en el PC principal "
                   "(donde corre el programa). Desde otro PC escribe la ruta a mano, "
                   "por ejemplo \\\\WIN-I56F313Q7LR\\imagenes repuestos\\archivo.jpg"), 400

@app.post("/api/productos/<int:pid>/eliminar")
def api_producto_eliminar(pid):
    d = db()
    d.execute("DELETE FROM stock_bodegas WHERE producto_id=?", (pid,))
    d.execute("DELETE FROM productos WHERE id=?", (pid,))
    d.commit()
    return jsonify(ok=True)

@app.post("/api/productos/<int:pid>/cantidad")
def api_producto_cantidad(pid):
    d = db(); f = request.get_json(force=True)
    filas_b = d.execute("SELECT bodega FROM stock_bodegas WHERE producto_id=?",
                        (pid,)).fetchall()
    if len(filas_b) > 1:
        return jsonify(ok=False, error="Este producto tiene existencias en varias "
                       "bodegas: usa «Fijar stock» para ajustar cada una"), 400
    antes = d.execute("SELECT cantidad_esperada FROM productos WHERE id=?",
                      (pid,)).fetchone()
    if str(f.get("delta", "")) in ("-1", "1", "+1"):
        d.execute("UPDATE productos SET cantidad_esperada=MAX(0,cantidad_esperada+?) WHERE id=?",
                  (int(f["delta"]), pid))
    else:
        try:
            v = max(0, int(f.get("valor") or 0))
        except (TypeError, ValueError):
            v = 0
        d.execute("UPDATE productos SET cantidad_esperada=? WHERE id=?", (v, pid))
    n = d.execute("SELECT cantidad_esperada FROM productos WHERE id=?", (pid,)).fetchone()
    if antes and n:
        # motivo "ajuste" = el usuario dijo que NO fue venta
        registrar_salida(d, pid, antes["cantidad_esperada"], n["cantidad_esperada"],
                         "ajuste", es_venta=str(f.get("motivo") or "venta") != "ajuste")
    if filas_b and n:
        # una sola bodega: su detalle se mantiene sincronizado con el total
        d.execute("UPDATE stock_bodegas SET cantidad=? WHERE producto_id=?",
                  (n["cantidad_esperada"], pid))
    d.commit()
    return jsonify(ok=True, cantidad=(n["cantidad_esperada"] if n else 0))

@app.post("/api/productos/<int:pid>/imprimir")
def api_producto_imprimir(pid):
    d = db(); c = cfg()
    p = d.execute("SELECT * FROM productos WHERE id=?", (pid,)).fetchone()
    if not p:
        return jsonify(ok=False, msg="✖ El producto no existe"), 404
    f = request.get_json(force=True) or {}
    copias = max(1, int(f.get("copias") or 1))
    ok, msg = ejecutar_impresion(d, c, p, copias, "")
    return jsonify(ok=ok, msg=msg)

@app.post("/api/productos/<int:pid>/imprimir_desc")
def api_producto_imprimir_desc(pid):
    """Etiqueta de DESCRIPCIÓN del producto por la impresora SAT (sin chip)."""
    d = db(); c = cfg()
    p = d.execute("SELECT * FROM productos WHERE id=?", (pid,)).fetchone()
    if not p:
        return jsonify(ok=False, msg="✖ El producto no existe"), 404
    f = request.get_json(silent=True) or {}
    copias = max(1, int(f.get("copias") or 1))
    try:
        enviar_descripcion(datos_descripcion(p, c, copias), c)
    except Exception as e:
        return jsonify(ok=False, msg=f"✖ No se pudo imprimir en la SAT: {e}"), 502
    return jsonify(ok=True,
                   msg=f"✔ {copias} etiqueta(s) de descripción de {p['sku']} enviada(s) a la SAT")

@app.post("/api/productos/<int:pid>/imprimir_desc_zebra")
def api_producto_imprimir_desc_zebra(pid):
    """La etiqueta de DESCRIPCIÓN por la ZEBRA, GRABANDO EL CHIP de cada una.
    La SAT no puede grabar chips; esta es la forma de que la etiqueta de
    descripción también quede con RFID."""
    d = db(); c = cfg()
    p = d.execute("SELECT * FROM productos WHERE id=?", (pid,)).fetchone()
    if not p:
        return jsonify(ok=False, msg="✖ El producto no existe"), 404
    f = request.get_json(silent=True) or {}
    copias = max(1, int(f.get("copias") or 1))
    grabados = []
    try:
        for _ in range(copias):
            epc = nuevo_epc(d, p["id"]) if c.get("codificar_rfid") else ""
            enviar_zpl(zpl_descripcion(p, epc, c), c)
            if epc:
                d.execute("INSERT OR REPLACE INTO tags(epc,producto_id,creado) VALUES(?,?,?)",
                          (epc, p["id"], datetime.now().isoformat()))
                d.commit()
                grabados.append(epc)
    except Exception as e:
        return jsonify(ok=False, msg=f"✖ No se pudo imprimir en la Zebra: {e}"), 502
    if grabados:
        lista = ", ".join(grabados[:3]) + ("…" if len(grabados) > 3 else "")
        return jsonify(ok=True, msg=f"✔ {copias} etiqueta(s) de descripción de "
                                    f"{p['sku']}: EPC grabados y asociados ({lista})")
    return jsonify(ok=True, msg=f"✔ {copias} etiqueta(s) de descripción de {p['sku']} "
                                "enviada(s) a la Zebra (sin grabar chip: está apagado "
                                "en ⚙ Configuración)")

@app.post("/api/productos/<int:pid>/imprimir_codigo_sat")
def api_producto_imprimir_codigo_sat(pid):
    """La etiqueta de CÓDIGO DE BARRAS (diseño de la pestaña 🏷️) por la SAT."""
    d = db(); c = cfg()
    p = d.execute("SELECT * FROM productos WHERE id=?", (pid,)).fetchone()
    if not p:
        return jsonify(ok=False, msg="✖ El producto no existe"), 404
    f = request.get_json(silent=True) or {}
    copias = max(1, int(f.get("copias") or 1))
    try:
        enviar_descripcion(datos_codigo_sat(p, c, copias), c)
    except Exception as e:
        return jsonify(ok=False, msg=f"✖ No se pudo imprimir en la SAT: {e}"), 502
    return jsonify(ok=True,
                   msg=f"✔ {copias} etiqueta(s) de código de barras de {p['sku']} enviada(s) a la SAT")

@app.get("/api/sesiones")
def api_sesiones():
    d = db()
    rows = d.execute("""SELECT s.*, COUNT(l.id) n,
                          (SELECT COUNT(*) FROM sesion_productos sp
                           WHERE sp.sesion_id = s.id) np
                        FROM sesiones s
                        LEFT JOIN lecturas l ON l.sesion_id=s.id
                        GROUP BY s.id ORDER BY s.id DESC""").fetchall()
    return jsonify([dict(r) for r in rows])

@app.post("/api/sesiones/nueva")
def api_sesion_nueva():
    d = db(); f = request.get_json(force=True)
    d.execute("UPDATE sesiones SET estado='cerrada' WHERE estado='abierta'")
    prods = f.get("productos") if isinstance(f.get("productos"), list) else None
    s = crear_sesion(d, (f.get("nombre") or "").strip() or None,
                     f.get("tipo") or "verificacion",
                     f.get("bodega") or "", prods)
    return jsonify(ok=True, id=s["id"])

@app.post("/api/sesiones/<int:sid>/cerrar")
def api_sesion_cerrar(sid):
    msg = cerrar_sesion_db(db(), sid)
    return jsonify(ok=True, msg=msg or "✔ Sesión cerrada")

@app.post("/api/sesiones/<int:sid>/eliminar")
def api_sesion_eliminar(sid):
    """Borra la sesión con sus lecturas. NO toca el stock de los productos."""
    d = db()
    if not d.execute("SELECT 1 FROM sesiones WHERE id=?", (sid,)).fetchone():
        return jsonify(ok=False, msg="✖ La sesión no existe"), 404
    d.execute("DELETE FROM lecturas WHERE sesion_id=?", (sid,))
    d.execute("DELETE FROM sesion_productos WHERE sesion_id=?", (sid,))
    d.execute("DELETE FROM sesiones WHERE id=?", (sid,))
    d.commit()
    return jsonify(ok=True, msg=f"✔ Sesión #{sid} eliminada (el stock no cambió)")

@app.post("/api/impresora/buscar")
def api_impresora_buscar():
    """Busca la impresora en la red local (el router puede cambiarle la IP).
    Con {"aplicar": true} guarda la Zebra encontrada si hay exactamente una."""
    c = cfg()
    lista = buscar_impresoras()
    zebras = [z for z in lista if _es_zebra(z["modelo"])]
    f = request.get_json(silent=True) or {}
    aplicada = ""
    if f.get("aplicar") and len(zebras) == 1:
        c["impresora_ip"] = zebras[0]["ip"]
        guardar_cfg(c)
        aplicada = zebras[0]["ip"]
    return jsonify(ok=True, impresoras=lista, zebras=zebras,
                   actual=c["impresora_ip"], aplicada=aplicada)

@app.get("/api/impresoras_windows")
def api_impresoras_windows():
    """Impresoras instaladas en Windows, para elegirlas en ⚙ Configuración."""
    c = cfg()
    return jsonify(lista=impresoras_windows(),
                   zebra=str(c.get("zebra_impresora_win") or ""),
                   sat=str(c.get("sat_impresora_win") or ""),
                   zebra_salida=str(c.get("zebra_salida") or "red"),
                   sat_salida=str(c.get("sat_salida") or "red"))


@app.post("/api/impresora/probar")
def api_impresora_probar():
    """JSON: {tipo:"zebra"|"sat"} — saca UNA etiqueta de prueba por la ruta que
    esté configurada (red o Windows), diciendo en la propia etiqueta por dónde
    salió. Es la forma rápida de saber si quedó bien sin adivinar."""
    f = request.get_json(silent=True) or {}
    tipo = "sat" if f.get("tipo") == "sat" else "zebra"
    c = cfg()
    win = salida_windows(c, tipo)
    if win:
        ruta = "por Windows: " + win
    elif tipo == "sat":
        ruta = "por red: %s:%s" % (c.get("sat_ip") or "(sin IP)", c.get("sat_puerto") or 9100)
    else:
        ruta = "por red: %s:%s" % (c.get("impresora_ip") or "(sin IP)",
                                   c.get("impresora_puerto") or 9100)
    datos = datos_prueba(c, tipo, ruta)
    try:
        if tipo == "sat":
            enviar_descripcion(datos.encode("latin-1", "replace"), c)
        else:
            enviar_zpl(datos, c)
    except OSError as e:
        return jsonify(ok=False, ruta=ruta, error=str(e)), 502
    return jsonify(ok=True, ruta=ruta,
                   msg="Etiqueta de prueba enviada %s" % ruta)


@app.post("/api/impresora/avanzado")
def api_impresora_avanzado():
    """Abre las Preferencias de impresión de Windows (driver) de la Zebra o la
    SAT en el PC principal. Si no reconoce cuál es, devuelve la lista para que
    el usuario elija (y la elección queda recordada en config.json)."""
    f = request.get_json(silent=True) or {}
    tipo = "sat" if f.get("tipo") == "sat" else "zebra"
    clave = "sat_impresora_win" if tipo == "sat" else "zebra_impresora_win"
    c = cfg()
    lista = impresoras_windows()
    nombre = str(f.get("nombre") or "").strip()
    if nombre:
        c[clave] = nombre                     # elegida a mano: queda recordada
        guardar_cfg(c)
    else:
        nombre = str(c.get(clave) or "").strip()
        if nombre and lista and nombre not in lista:
            nombre = ""                       # la recordada ya no existe
        if not nombre:
            pistas = ("sat", "tt4", "tsc") if tipo == "sat" \
                else ("zebra", "zt4", "zd4", "zd6")
            cand = [n for n in lista if any(p in n.lower() for p in pistas)]
            if len(cand) == 1:
                nombre = cand[0]
                c[clave] = nombre
                guardar_cfg(c)
            else:
                if not lista:
                    return jsonify(ok=False, lista=[],
                                   error="No pude ver las impresoras de Windows")
                return jsonify(ok=False, lista=(cand or lista),
                               error="Elige cuál es en Windows")
    try:
        abrir_preferencias_impresora(nombre)
    except Exception as e:
        return jsonify(ok=False, lista=lista, error=f"No se pudo abrir: {e}")
    return jsonify(ok=True, nombre=nombre)

@app.get("/api/carpetas")
def api_carpetas():
    """Lista las carpetas del PC SERVIDOR para poder elegir una (la de fotos,
    la de copias) DESDE CUALQUIER PC. Se navegan las del servidor a propósito:
    es él quien abre esos archivos, así que una carpeta del PC de al lado no
    le serviría. Solo devuelve NOMBRES de carpetas, nunca el contenido.
    Con ?archivos=1 lista también las IMÁGENES, para elegir la foto de un
    producto desde cualquier equipo (antes solo se podía en el principal)."""
    ruta = (request.args.get("ruta") or "").strip()
    con_archivos = request.args.get("archivos") in ("1", "true", "si")
    # el filtro se aplica AQUÍ (no en la pantalla): en carpetas con miles de
    # fotos solo se mandan las que coinciden, así ninguna queda fuera de la lista
    q = (request.args.get("q") or "").strip().lower()
    TOPE = 1500
    if ruta in ("..", "raiz"):
        ruta = ""
    # sin ruta: las unidades del servidor (C:\, D:\, …)
    if not ruta:
        unidades = []
        for letra in "CDEFGHIJKLMNOPQRSTUVWXYZ":
            u = f"{letra}:\\"
            if os.path.isdir(u):
                unidades.append({"nombre": f"💽 {u}", "ruta": u})
        return jsonify(ok=True, ruta="", padre=None, raiz=True,
                       equipo=socket.gethostname(), imagenes=0,
                       carpetas=unidades, archivos=[])
    if not os.path.isdir(ruta):
        return jsonify(ok=False, error=f"No existe la carpeta {ruta}"), 404
    carpetas, archivos, imagenes = [], [], 0
    try:
        with os.scandir(ruta) as it:
            for e in it:
                try:
                    if e.is_dir():
                        carpetas.append({"nombre": "📁 " + e.name, "ruta": e.path})
                    elif os.path.splitext(e.name)[1].lower() in EXT_FOTO:
                        imagenes += 1
                        if (con_archivos and len(archivos) < TOPE
                                and (not q or q in e.name.lower())):
                            archivos.append({"nombre": e.name, "ruta": e.path})
                except OSError:
                    pass
    except PermissionError:
        return jsonify(ok=False, error="Windows no deja ver esa carpeta"), 403
    except OSError as e:
        return jsonify(ok=False, error=str(e)), 400
    carpetas.sort(key=lambda x: x["nombre"].lower())
    archivos.sort(key=lambda x: x["nombre"].lower())
    base = ruta.rstrip("\\/")
    padre = os.path.dirname(base)
    # arriba del todo (una unidad como C:\ o un \\SERVIDOR) -> lista de unidades
    if (not padre
            or os.path.normcase(padre.rstrip("\\/")) == os.path.normcase(base)
            or not os.path.isdir(padre)):
        padre = ""
    return jsonify(ok=True, ruta=ruta, padre=padre, raiz=False,
                   equipo=socket.gethostname(), imagenes=imagenes,
                   carpetas=carpetas[:500], archivos=archivos,
                   truncado=(len(archivos) >= TOPE))

@app.get("/api/vista_archivo")
def api_vista_archivo():
    """Muestra una imagen del PC servidor para verla antes de elegirla como
    foto del producto. SOLO imágenes (por extensión): así este atajo no sirve
    para sacar la base de datos ni ningún otro archivo del servidor."""
    ruta = (request.args.get("ruta") or "").strip()
    if (not ruta or os.path.splitext(ruta)[1].lower() not in EXT_FOTO
            or not os.path.isfile(ruta)):
        return jsonify(ok=False), 404
    try:
        from flask import send_file
        return send_file(ruta)
    except Exception:
        return jsonify(ok=False), 404

@app.post("/api/respaldo/ahora")
def api_respaldo_ahora():
    """Hace una copia de seguridad de la base de datos ya mismo (botón manual)."""
    try:
        dest = hacer_respaldo()
        return jsonify(ok=True, ruta=dest,
                       msg=f"✔ Copia guardada en {dest}")
    except Exception as e:
        return jsonify(ok=False, msg=f"✖ No se pudo copiar: {e}"), 500

@app.get("/api/respaldos")
def api_respaldos():
    """Lista las copias existentes (nombre, tamaño, fecha) y la carpeta."""
    carp = carpeta_respaldos()
    out = []
    try:
        for f in sorted(os.listdir(carp), reverse=True):
            if f.startswith("inventario_") and f.endswith(".db"):
                p = os.path.join(carp, f)
                out.append({"nombre": f, "kb": round(os.path.getsize(p) / 1024)})
    except OSError:
        pass
    return jsonify(carpeta=carp, copias=out)

@app.get("/api/config")
def api_config():
    return jsonify(cfg())

@app.post("/api/config")
def api_config_guardar():
    c = cfg(); f = request.get_json(force=True)
    for k in DEFAULT_CFG:
        if k in f:
            c[k] = f[k]
    try:
        c["impresora_puerto"] = int(c["impresora_puerto"])
        c["dpi"] = int(c["dpi"])
        c["etiqueta_ancho_mm"] = float(c["etiqueta_ancho_mm"])
        c["etiqueta_alto_mm"] = float(c["etiqueta_alto_mm"])
        c["codificar_rfid"] = bool(c["codificar_rfid"])
        c["bartender"] = bool(c["bartender"])
        c["oscuridad"] = max(0, min(30, int(c.get("oscuridad", 27))))
        c["velocidad"] = max(2, min(7, int(c.get("velocidad", 3))))
        c["sat_puerto"] = int(c.get("sat_puerto") or 9100)
        c["sat_dpi"] = int(c.get("sat_dpi") or 203)
        c["sat_ancho_mm"] = float(c.get("sat_ancho_mm") or 50)
        c["sat_alto_mm"] = float(c.get("sat_alto_mm") or 40)
        c["sat_gap_mm"] = float(c.get("sat_gap_mm") or 3)
        c["sat_oscuridad"] = max(0, min(15, int(c.get("sat_oscuridad", 12))))
        if str(c.get("sat_lenguaje") or "").lower() not in ("tspl", "zpl"):
            c["sat_lenguaje"] = "tspl"
        c["sat_doble"] = bool(c.get("sat_doble"))
        c["sat_sep_mm"] = float(c.get("sat_sep_mm") or 4)
        if str(c.get("sat_lado") or "") not in ("izquierda", "derecha", "ambas"):
            c["sat_lado"] = "izquierda"
        # por dónde sale cada impresora: red (IP) o la instalada en Windows
        for pre in ("zebra", "sat"):
            k = pre + "_salida"
            if str(c.get(k) or "").lower() not in ("red", "windows"):
                c[k] = "red"
            # elegir "por Windows" sin decir cuál no tiene sentido: se vuelve a red
            if c[k] == "windows" and not str(c.get(pre + "_impresora_win") or "").strip():
                c[k] = "red"
        for kp in ("papel_tipo", "sat_papel_tipo"):
            if str(c.get(kp) or "") not in ("", "gap", "marca", "continuo"):
                c[kp] = ""
        c["actualizar_revisar"] = bool(c.get("actualizar_revisar", True))
        c["actualizar_auto"] = bool(c.get("actualizar_auto", True))
        c["actualizar_repo"] = str(c.get("actualizar_repo") or "").strip()
        c["respaldo_activo"] = bool(c.get("respaldo_activo", True))
        c["respaldo_dias"] = max(1, min(365, int(c.get("respaldo_dias", 30))))
        c["costo_descuento"] = max(0, min(100, int(c.get("costo_descuento", 48))))
        c["rotacion_dias"] = max(1, min(3650, int(c.get("rotacion_dias", 180))))
        c["rotacion_alta"] = max(1, int(c.get("rotacion_alta", 10)))
        c["rotacion_media"] = max(1, int(c.get("rotacion_media", 3)))
        if c["rotacion_media"] > c["rotacion_alta"]:      # no se pueden cruzar
            c["rotacion_media"] = c["rotacion_alta"]
        h = str(c.get("respaldo_hora") or "05:20").strip()
        m = re.match(r"^(\d{1,2}):(\d{2})$", h)
        c["respaldo_hora"] = (f"{int(m.group(1)) % 24:02d}:{int(m.group(2)) % 60:02d}"
                              if m else "05:20")
    except (TypeError, ValueError):
        return jsonify(ok=False, error="Hay valores numéricos inválidos"), 400
    with open(CFG, "w", encoding="utf-8") as fp:
        json.dump(c, fp, indent=2, ensure_ascii=False)
    return jsonify(ok=True)

# ------- editor de diseño de etiqueta (con vista previa)
def producto_muestra(d, sku=""):
    """Producto para la vista previa: el pedido, o uno con código de precio,
    o el primero; si no hay productos, uno de ejemplo."""
    p = None
    if sku:
        p = d.execute("SELECT * FROM productos WHERE sku=?", (sku.strip(),)).fetchone()
    if not p:
        p = d.execute("""SELECT * FROM productos WHERE IFNULL(codigo_barras,'')!=''
                         ORDER BY id LIMIT 1""").fetchone()
    if not p:
        p = d.execute("SELECT * FROM productos ORDER BY id LIMIT 1").fetchone()
    return p or {"sku": "EJEMPLO-01", "nombre": "PRODUCTO DE EJEMPLO",
                 "oem": "032905106B F000ZS0210", "ubicacion": "BODEGA 1",
                 "codigo_barras": "300026000270", "precio": 27000,
                 "precio_minimo": 26000}

def producto_preview(f):
    """Producto armado con lo ESCRITO en la ficha (aunque no esté guardado):
    la previsualización de la ficha muestra las etiquetas tal como saldrían."""
    fp = f.get("producto") or {}
    def ent(k):
        try:
            return max(0, int(float(str(fp.get(k) or 0).replace(",", ".") or 0)))
        except (TypeError, ValueError):
            return 0
    pid = ent("id")
    pmin, pnor, prov = ent("precio_minimo"), ent("precio"), ent("proveedor")
    cb = str(fp.get("codigo_barras") or "").strip()
    if not cb:
        # mismo código que se generaría al guardar (con proveedor + precios)
        cb = generar_codigo_barras(pid, pmin, pnor, prov)
    return {"sku": str(fp.get("sku") or "").strip() or "EJEMPLO-01",
            "nombre": str(fp.get("nombre") or "").strip() or "PRODUCTO DE EJEMPLO",
            "oem": str(fp.get("oem") or "").strip(),
            "ubicacion": str(fp.get("ubicacion") or "").strip(),
            "codigo_barras": cb,
            "foto": str(fp.get("foto") or "").strip(),
            "precio": pnor, "precio_minimo": pmin}

@app.get("/api/etiqueta/diseno")
def api_diseno():
    c = cfg()
    return jsonify(actual=diseno_cfg(c), original=DISENO_DEFAULT,
                   desc_actual=diseno_desc_cfg(c), desc_original=DISENO_DESC_DEFAULT)

@app.post("/api/etiqueta/preview")
def api_diseno_preview():
    """Genera la imagen de la etiqueta (vía Labelary, requiere internet) con
    el diseño que se está editando, sin guardarlo."""
    import urllib.request
    d = db(); f = request.get_json(force=True) or {}
    c = dict(cfg())
    if f.get("diseno"):
        c["diseno"] = f["diseno"]
    p = producto_preview(f) if isinstance(f.get("producto"), dict) \
        else producto_muestra(d, f.get("sku", ""))
    # se renderiza en alta resolución (24 puntos/mm) para que el editor se vea
    # nítido; el diseño escala idéntico porque todo se calcula desde milímetros
    c["dpi"] = 609
    zpl = zpl_etiqueta(p, "AF010001230000015AB4C2D9", c)
    url = (f"http://api.labelary.com/v1/printers/24dpmm/labels/"
           f"{c['etiqueta_ancho_mm']/25.4:.2f}x{c['etiqueta_alto_mm']/25.4:.2f}/0/")
    try:
        req = urllib.request.Request(url, data=zpl.encode("utf-8"),
                                     headers={"Accept": "image/png"})
        png = urllib.request.urlopen(req, timeout=15).read()
    except Exception as e:
        return jsonify(ok=False,
                       error=f"No se pudo generar la vista previa (¿sin internet?): {e}"), 502
    return Response(png, mimetype="image/png")

@app.post("/api/etiqueta/guardar")
def api_diseno_guardar():
    f = request.get_json(force=True) or {}
    c = cfg()
    if "diseno" in f:
        c["diseno"] = f.get("diseno") or {}
    if "diseno_desc" in f:
        c["diseno_desc"] = f.get("diseno_desc") or {}
    with open(CFG, "w", encoding="utf-8") as fp:
        json.dump(c, fp, indent=2, ensure_ascii=False)
    return jsonify(ok=True)

@app.post("/api/etiqueta/prueba")
def api_diseno_prueba():
    """Imprime UNA etiqueta física con el diseño en edición, sin grabar chip
    ni asociar nada (solo para ver cómo queda en papel)."""
    d = db(); f = request.get_json(force=True) or {}
    c = dict(cfg())
    if f.get("diseno"):
        c["diseno"] = f["diseno"]
    c["codificar_rfid"] = False        # prueba visual: no gastar el chip
    p = producto_muestra(d, f.get("sku", ""))
    try:
        enviar_zpl(zpl_etiqueta(p, "", c), c)
    except Exception as e:
        return jsonify(ok=False, msg=f"✖ No se pudo imprimir: {e}"), 502
    return jsonify(ok=True, msg=f"✔ Etiqueta de prueba de {p['sku']} enviada a la impresora (sin grabar chip)")

@app.post("/api/etiqueta/preview_desc")
def api_diseno_preview_desc():
    """Vista previa de la etiqueta de descripción (SAT): se dibuja aquí mismo
    con Pillow, así que NO necesita internet y es idéntica a la impresión."""
    d = db(); f = request.get_json(force=True) or {}
    c = dict(cfg())
    if f.get("diseno"):
        c["diseno_desc"] = f["diseno"]
    p = producto_preview(f) if isinstance(f.get("producto"), dict) \
        else producto_muestra(d, f.get("sku", ""))
    try:
        from PIL import ImageOps
        img = img_descripcion(p, c, dpi=609)   # alta resolución para el editor
        vis = ImageOps.invert(img.convert("L"))
        buf = io.BytesIO()
        vis.save(buf, "PNG")
    except Exception as e:
        return jsonify(ok=False, error=f"No se pudo generar la vista previa: {e}"), 500
    return Response(buf.getvalue(), mimetype="image/png")

@app.post("/api/etiqueta/prueba_desc")
def api_diseno_prueba_desc():
    """Imprime UNA etiqueta de descripción en la SAT con el diseño en edición."""
    d = db(); f = request.get_json(force=True) or {}
    c = dict(cfg())
    if f.get("diseno"):
        c["diseno_desc"] = f["diseno"]
    p = producto_muestra(d, f.get("sku", ""))
    try:
        enviar_descripcion(datos_descripcion(p, c, 1), c)
    except Exception as e:
        return jsonify(ok=False, msg=f"✖ No se pudo imprimir en la SAT: {e}"), 502
    return jsonify(ok=True, msg=f"✔ Etiqueta de descripción de {p['sku']} enviada a la impresora SAT")

@app.post("/api/etiqueta/prueba_codigo_sat")
def api_diseno_prueba_codigo_sat():
    """Imprime en la SAT UNA etiqueta de CÓDIGO DE BARRAS con el diseño en edición."""
    d = db(); f = request.get_json(force=True) or {}
    c = dict(cfg())
    if f.get("diseno"):
        c["diseno"] = f["diseno"]
    p = producto_muestra(d, f.get("sku", ""))
    try:
        enviar_descripcion(datos_codigo_sat(p, c, 1), c)
    except Exception as e:
        return jsonify(ok=False, msg=f"✖ No se pudo imprimir en la SAT: {e}"), 502
    return jsonify(ok=True, msg=f"✔ Código de barras de {p['sku']} enviado a la impresora SAT")

# ---------------------------------------------------------------- vistas web
def page(name, **kw):
    nd = db().execute("""SELECT COUNT(DISTINCT epc) FROM lecturas
                         WHERE epc NOT IN (SELECT epc FROM tags)""").fetchone()[0]
    return render_template(name + ".html", pg=name, c=cfg(), nd=nd, **kw)

# Cada versión del escritorio tiene su color (semáforo de qué PC es):
#   principal = ROJO · cliente (otros PCs que sí modifican) = NARANJA (original)
#   vendedor = VERDE OSCURO y SOLO consulta (sin modificar ni imprimir).
# El color se aplica cambiando la paleta naranja del HTML ya renderizado, así
# TODA la interfaz (botones, pestañas, barra, selecciones) cambia pareja.
PALETAS = {
    "principal": {   # rojos
        "#E87722": "#C62828", "#D0641B": "#A82222", "#C25705": "#9E1B1B",
        "#FDEBD9": "#FBE3E1", "#F5C9A4": "#F0B9B4", "#FBDCBE": "#F7CFCB",
        "#FCE0C6": "#F8D6D2", "#FDEEE2": "#FBE7E5", "#FDE7D2": "#FADFDC",
        "#B34A00": "#8E1410",
    },
    "vendedor": {    # verdes oscuros
        "#E87722": "#1F7A44", "#D0641B": "#186238", "#C25705": "#135C31",
        "#FDEBD9": "#E2F1E6", "#F5C9A4": "#B9DCC4", "#FBDCBE": "#D3E9DA",
        "#FCE0C6": "#D9EBDF", "#FDEEE2": "#E7F2EA", "#FDE7D2": "#E0EFE4",
        "#B34A00": "#0F5129",
    },
}

@app.get("/escritorio")
def escritorio():
    """Interfaz de la ventana de PC, estilo FactuSOL (Productos e Inventario).
    ?modo=principal (rojo) · sin modo = cliente (naranja) · ?modo=vendedor
    (verde, solo consulta). El celular y la pistola siguen con las páginas web."""
    modo = request.args.get("modo", "")
    if modo not in ("principal", "vendedor"):
        modo = ""
    html = render_template("escritorio.html", ip=ip_local(), c=cfg(), modo=modo)
    for viejo, nuevo in PALETAS.get(modo, {}).items():
        html = html.replace(viejo, nuevo).replace(viejo.lower(), nuevo)
    return html

@app.route("/")
def home():
    d = db(); s = sesion_activa(d)
    tot = d.execute("SELECT COUNT(*) c FROM productos").fetchone()["c"]
    tags = d.execute("SELECT COUNT(*) c FROM tags").fetchone()["c"]
    leidos = d.execute("SELECT COUNT(*) c FROM lecturas WHERE sesion_id=?", (s["id"],)).fetchone()["c"] if s else 0
    return page("home", productos=tot, tags=tags, sesion=s, leidos=leidos)

@app.route("/productos", methods=["GET", "POST"])
def productos():
    d = db()
    if request.method == "POST":
        f = request.form
        try:
            d.execute("INSERT INTO productos(sku,nombre,ubicacion,cantidad_esperada,oem) VALUES(?,?,?,?,?)",
                      (f["sku"].strip(), f["nombre"].strip(), f.get("ubicacion", ""),
                       f.get("cantidad") or 0, f.get("oem", "").strip()))
            d.commit()
        except sqlite3.IntegrityError:
            pass
        return redirect(url_for("productos"))
    rows = d.execute("""SELECT p.*, COUNT(t.epc) n_tags FROM productos p
                        LEFT JOIN tags t ON t.producto_id=p.id
                        GROUP BY p.id ORDER BY p.nombre""").fetchall()
    return page("productos", rows=rows, msg=request.args.get("msg"))

@app.get("/imprimir")
def imprimir_lista():
    """Subpágina de Productos dedicada solo a imprimir etiquetas."""
    d = db()
    rows = d.execute("""SELECT p.*, COUNT(t.epc) n_tags FROM productos p
                        LEFT JOIN tags t ON t.producto_id=p.id
                        GROUP BY p.id ORDER BY p.nombre""").fetchall()
    return page("imprimir", rows=rows, msg=request.args.get("msg"))

@app.post("/productos/<int:pid>/cantidad")
def ajustar_cantidad(pid):
    """Ajuste manual de unidades sin recontar: +1, −1 o fijar un valor."""
    d = db(); delta = request.form.get("delta", "")
    antes = d.execute("SELECT cantidad_esperada FROM productos WHERE id=?",
                      (pid,)).fetchone()
    if delta in ("-1", "+1", "1"):
        d.execute("UPDATE productos SET cantidad_esperada = MAX(0, cantidad_esperada + ?) WHERE id=?",
                  (int(delta), pid))
    else:
        try:
            valor = max(0, int(request.form.get("valor") or 0))
        except ValueError:
            valor = 0
        d.execute("UPDATE productos SET cantidad_esperada=? WHERE id=?", (valor, pid))
    p = d.execute("SELECT sku, cantidad_esperada FROM productos WHERE id=?", (pid,)).fetchone()
    if antes and p:
        registrar_salida(d, pid, antes["cantidad_esperada"], p["cantidad_esperada"], "ajuste")
    d.commit()
    return redirect(url_for("productos", msg=f"✔ {p['sku']}: cantidad ajustada a {p['cantidad_esperada']}"))

@app.post("/productos/<int:pid>/borrar")
def borrar_producto(pid):
    d = db()
    d.execute("DELETE FROM stock_bodegas WHERE producto_id=?", (pid,))
    d.execute("DELETE FROM productos WHERE id=?", (pid,))
    d.commit()
    return redirect(url_for("productos"))

@app.post("/productos/<int:pid>/tag")
def agregar_tag(pid):
    d = db(); epc = request.form["epc"].strip().upper()
    if epc:
        d.execute("INSERT OR REPLACE INTO tags(epc,producto_id,creado) VALUES(?,?,?)",
                  (epc, pid, datetime.now().isoformat())); d.commit()
    return redirect(url_for("productos"))

def imprimir_bartender(d, p, copias, c):
    """Imprime con BarTender usando la plantilla .btw del usuario: los datos
    (y el EPC a grabar) van en bt_datos.csv, una fila por etiqueta. Los EPC se
    asocian solo si BarTender termina bien."""
    grabados = []
    filas = []
    for _ in range(copias):
        epc = nuevo_epc(d, p["id"])
        filas.append({"sku": p["sku"], "nombre": p["nombre"],
                      "oem": (p["oem"] if "oem" in p.keys() else "") or "",
                      "codigo": ((p["codigo_barras"] if "codigo_barras" in p.keys() else "") or p["sku"]),
                      "epc": epc, "web": c.get("nombre_empresa", "")})
        grabados.append(epc)
    ruta_csv = os.path.join(BASE, "bt_datos.csv")
    with open(ruta_csv, "w", newline="", encoding="utf-8-sig") as fh:
        wcsv = csv.DictWriter(fh, fieldnames=["sku", "nombre", "oem", "codigo", "epc", "web"])
        wcsv.writeheader()
        wcsv.writerows(filas)
    cmd = [c["bartender_exe"], f"/F={c['bartender_plantilla']}", "/P", "/X"]
    if c.get("bartender_impresora"):
        cmd.insert(1, f"/PRN={c['bartender_impresora']}")
    r = subprocess.run(cmd, timeout=180)
    if r.returncode != 0:
        raise RuntimeError(f"BarTender terminó con código {r.returncode}")
    for epc in grabados:
        d.execute("INSERT OR REPLACE INTO tags(epc,producto_id,creado) VALUES(?,?,?)",
                  (epc, p["id"], datetime.now().isoformat()))
    d.commit()
    return grabados

def ejecutar_impresion(d, c, p, copias, epc_manual=""):
    """Imprime `copias` etiquetas de un producto (BarTender o ZPL propio).
    Regresa (ok, mensaje)."""
    if c.get("bartender") and c.get("bartender_plantilla"):
        try:
            grabados = imprimir_bartender(d, p, copias, c)
            lista = ", ".join(grabados[:3]) + ("…" if len(grabados) > 3 else "")
            return True, f"✔ {copias} etiqueta(s) de {p['sku']} impresas con BarTender ({lista})"
        except Exception as e:
            return False, f"✖ Error BarTender: {e}"
    try:
        grabados = []
        for i in range(copias):
            epc = ""
            if c.get("codificar_rfid"):
                # Cada etiqueta lleva un EPC único: el escrito a mano (solo si es
                # una copia) o uno generado con la referencia del producto adentro.
                epc = epc_manual if (epc_manual and copias == 1) else nuevo_epc(d, p["id"])
            enviar_zpl(zpl_etiqueta(p, epc, c), c)
            if epc:
                d.execute("INSERT OR REPLACE INTO tags(epc,producto_id,creado) VALUES(?,?,?)",
                          (epc, p["id"], datetime.now().isoformat()))
                d.commit()
                grabados.append(epc)
        if grabados:
            lista = ", ".join(grabados[:3]) + ("…" if len(grabados) > 3 else "")
            return True, f"✔ {copias} etiqueta(s) de {p['sku']}: EPC grabados y asociados ({lista})"
        return True, f"✔ {copias} etiqueta(s) de {p['sku']} enviada(s) a {c['impresora_ip']}"
    except Exception as e:
        return False, f"✖ Error de impresión: {e}"

@app.post("/productos/<int:pid>/imprimir")
def imprimir(pid):
    d = db(); c = cfg()
    p = d.execute("SELECT * FROM productos WHERE id=?", (pid,)).fetchone()
    epc_manual = request.form.get("epc", "").strip().upper()
    copias = max(1, int(request.form.get("copias", 1) or 1))
    ok, msg = ejecutar_impresion(d, c, p, copias, epc_manual)
    destino = "imprimir_lista" if request.form.get("volver") == "imprimir" else "productos"
    return redirect(url_for(destino, msg=msg))

@app.route("/sesiones", methods=["GET", "POST"])
def sesiones():
    d = db()
    if request.method == "POST":
        d.execute("UPDATE sesiones SET estado='cerrada' WHERE estado='abierta'")
        crear_sesion(d, request.form.get("nombre") or None,
                     request.form.get("tipo") or "verificacion")
        return redirect(url_for("sesiones"))
    rows = d.execute("""SELECT s.*, COUNT(l.id) n FROM sesiones s
                        LEFT JOIN lecturas l ON l.sesion_id=s.id
                        GROUP BY s.id ORDER BY s.id DESC""").fetchall()
    return page("sesiones", rows=rows)

def cerrar_sesion_db(d, sid):
    """Cierra una sesión; si es de conteo total aplica lo contado como cantidad
    oficial. Regresa el mensaje para el usuario (o None)."""
    s = d.execute("SELECT * FROM sesiones WHERE id=?", (sid,)).fetchone()
    d.execute("UPDATE sesiones SET estado='cerrada' WHERE id=?", (sid,))
    msg = None
    if s and ("tipo" in s.keys()) and s["tipo"] == "total":
        # Conteo total: lo contado se vuelve la cantidad oficial. Solo aplica a
        # productos que tienen etiquetas (los no etiquetados no se pueden contar
        # por RFID y conservan su cantidad).
        bod = (s["bodega"] if "bodega" in s.keys() else "") or ""
        # sesión de SOLO ciertos productos: los demás NO se tocan al cerrar
        sel = seleccion_sesion(d, sid)
        filtro = f" WHERE p.id IN ({','.join('?' * len(sel))})" if sel else ""
        filas = d.execute(f"""
            SELECT p.id, p.cantidad_esperada antes, COUNT(DISTINCT l.epc) c
            FROM productos p JOIN tags t ON t.producto_id = p.id
            LEFT JOIN lecturas l ON l.epc = t.epc AND l.sesion_id = ?
            {filtro}
            GROUP BY p.id""", (sid, *sel)).fetchall()
        aplicados = 0
        for f in filas:
            if bod:
                # conteo de UNA bodega: lo contado queda en esa bodega; las
                # demás no se tocan y el total/ubicación se recalculan solos
                # se conserva la POSICIÓN de cada bodega: el conteo cambia
                # cantidades, no dónde está guardado el repuesto
                posic = {}
                mapa = {}
                for r in d.execute("""SELECT bodega, cantidad, IFNULL(posicion,'') posicion
                                      FROM stock_bodegas WHERE producto_id=?""", (f["id"],)):
                    mapa[r["bodega"]] = r["cantidad"]
                    posic[r["bodega"]] = r["posicion"]
                if f["c"] == 0 and bod not in mapa:
                    # no se leyó y no estaba registrado en esa bodega:
                    # este producto no pertenece al conteo — no se toca
                    continue
                if not mapa:
                    # producto sin detalle por bodega todavía: el resto de su
                    # stock se conserva donde decía su ubicación de siempre
                    pv = d.execute("SELECT cantidad_esperada, IFNULL(ubicacion,'') u "
                                   "FROM productos WHERE id=?", (f["id"],)).fetchone()
                    resto = max(0, (pv["cantidad_esperada"] or 0) - f["c"])
                    otra = pv["u"].strip().upper()[:40]
                    if resto and otra and otra != bod:
                        mapa[otra] = resto
                mapa[bod] = f["c"]
                fijar_bodegas(d, f["id"],
                              [{"bodega": b, "cantidad": cq,
                                "posicion": posic.get(b, "")} for b, cq in mapa.items()],
                              origen="conteo")
                aplicados += 1
            else:
                registrar_salida(d, f["id"], f["antes"], f["c"], "conteo")
                d.execute("UPDATE productos SET cantidad_esperada=? WHERE id=?",
                          (f["c"], f["id"]))
                aplicados += 1
        donde = f" en {bod}" if bod else ""
        msg = (f"✔ Conteo total aplicado: la cantidad{donde} de {aplicados} productos "
               "etiquetados quedó como lo contado en esta sesión")
    d.commit()
    return msg

@app.post("/sesiones/<int:sid>/cerrar")
def cerrar_sesion(sid):
    msg = cerrar_sesion_db(db(), sid)
    return redirect(url_for("ver_sesion", sid=sid, msg=msg))

@app.get("/sesiones/<int:sid>")
def ver_sesion(sid):
    d = db()
    s = d.execute("SELECT * FROM sesiones WHERE id=?", (sid,)).fetchone()
    filas, desconocidos = resumen_sesion(d, sid)
    return page("sesion", s=s, resumen=filas, desconocidos=desconocidos,
                msg=request.args.get("msg"))

@app.get("/sesiones/<int:sid>/excel")
def sesion_excel(sid):
    """El conteo de la sesión en Excel, como se ve en pantalla: SOLO productos
    (nada de EPC desconocidos). 'Contado (unidades)' se llama así a propósito:
    el archivo se puede reimportar como conteo de inventario."""
    from openpyxl import Workbook
    from openpyxl.styles import Font, PatternFill
    d = db()
    s = d.execute("SELECT * FROM sesiones WHERE id=?", (sid,)).fetchone()
    filas, _ = resumen_sesion(d, sid)
    wb = Workbook(); ws = wb.active; ws.title = "conteo"
    ws.append(["Codigo (SKU)", "Nombre", "Bodega", "Esperado",
               "Contado (unidades)", "Diferencia"])
    for cel in ws[1]:
        cel.font = Font(bold=True, color="FFFFFF"); cel.fill = PatternFill("solid", fgColor="1F7A44")
    for r in filas:
        ws.append([r["sku"], r["nombre"], r["ubicacion"] or "",
                   r["cantidad_esperada"] or 0, r["leidos"] or 0,
                   (r["leidos"] or 0) - (r["cantidad_esperada"] or 0)])
    ws.freeze_panes = "A2"
    _autofit(ws)
    buf = io.BytesIO(); wb.save(buf); buf.seek(0)
    from flask import send_file
    nom = re.sub(r"[^0-9A-Za-z_-]+", "_", (s["nombre"] if s else "") or "")[:40]
    return send_file(
        buf, as_attachment=True,
        download_name=f"conteo_{sid}{('_' + nom) if nom else ''}.xlsx",
        mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")

@app.get("/sesiones/<int:sid>/csv")
def sesion_csv(sid):
    d = db()
    rows = d.execute("""SELECT l.epc, IFNULL(p.sku,''), IFNULL(p.nombre,''), l.dispositivo, l.ts
        FROM lecturas l LEFT JOIN tags t ON t.epc=l.epc
        LEFT JOIN productos p ON p.id=t.producto_id
        WHERE l.sesion_id=? ORDER BY l.ts""", (sid,)).fetchall()
    out = io.StringIO(); w = csv.writer(out)
    w.writerow(["EPC", "SKU", "Producto", "Dispositivo", "Fecha"])
    w.writerows(rows)
    return Response(out.getvalue(), mimetype="text/csv",
                    headers={"Content-Disposition": f"attachment; filename=sesion_{sid}.csv"})

@app.route("/desconocidos", methods=["GET", "POST"])
def desconocidos_view():
    """EPC leídos que ningún producto reclama: revisarlos y asignarlos a mano."""
    d = db(); msg = None
    if request.method == "POST":
        epc = request.form["epc"].strip().upper()
        if request.form.get("accion") == "ignorar":
            # tag ajeno: se guarda sin producto para que deje de aparecer
            d.execute("INSERT OR REPLACE INTO tags(epc,producto_id,creado) VALUES(?,NULL,?)",
                      (epc, datetime.now().isoformat()))
            d.commit()
            msg = f"EPC {epc} marcado como ignorado"
        else:
            sku = request.form.get("sku", "").strip()
            p = producto_por_codigo(d, sku)
            if p:
                d.execute("INSERT OR REPLACE INTO tags(epc,producto_id,creado) VALUES(?,?,?)",
                          (epc, p["id"], datetime.now().isoformat()))
                d.commit()
                msg = f"✔ {epc} → {p['sku']}"
            else:
                msg = f"✖ SKU '{sku}' no existe"
    rows = d.execute("""
        SELECT epc, COUNT(*) veces, MAX(ts) ultima, MAX(dispositivo) dispositivo
        FROM lecturas WHERE epc NOT IN (SELECT epc FROM tags)
        GROUP BY epc ORDER BY ultima DESC""").fetchall()
    return page("desconocidos", rows=rows, msg=msg)

@app.route("/captura", methods=["GET", "POST"])
def captura():
    """Para cualquier lector en modo teclado (HID/wedge): C72, USB, otras marcas."""
    d = db(); resultado = None
    if request.method == "POST":
        epc = request.form["epc"].strip().upper()
        if epc:
            s = sesion_activa(d) or crear_sesion(d, "Auto " + datetime.now().strftime("%Y-%m-%d %H:%M"))
            try:
                d.execute("INSERT INTO lecturas(sesion_id,epc,dispositivo,ts) VALUES(?,?,?,?)",
                          (s["id"], epc, "web", datetime.now().isoformat()))
                d.commit()
            except sqlite3.IntegrityError:
                pass
            p = d.execute("""SELECT p.* FROM productos p JOIN tags t ON t.producto_id=p.id
                             WHERE t.epc=?""", (epc,)).fetchone()
            resultado = {"epc": epc, "producto": (dict(p) if p else None)}
    return page("captura", resultado=resultado)

@app.route("/config", methods=["GET", "POST"])
def config_view():
    c = cfg(); msg = None
    if request.method == "POST":
        f = request.form
        c.update({
            "impresora_ip": f["impresora_ip"].strip(),
            "impresora_puerto": int(f["impresora_puerto"]),
            "dpi": int(f["dpi"]),
            "etiqueta_ancho_mm": float(f["ancho"]),
            "etiqueta_alto_mm": float(f["alto"]),
            "codificar_rfid": ("codificar_rfid" in f),
            "nombre_empresa": f["empresa"].strip(),
            "bartender": ("bartender" in f),
            "bartender_exe": f.get("bartender_exe", "").strip(),
            "bartender_plantilla": f.get("bartender_plantilla", "").strip(),
            "bartender_impresora": f.get("bartender_impresora", "").strip(),
        })
        with open(CFG, "w", encoding="utf-8") as fp:
            json.dump(c, fp, indent=2, ensure_ascii=False)
        if f.get("accion") == "probar":
            try:
                enviar_zpl(zpl_etiqueta({"nombre": "ETIQUETA DE PRUEBA", "sku": "TEST-001",
                                         "ubicacion": "—"}, "", c), c)
                msg = f"✔ Etiqueta de prueba enviada a {c['impresora_ip']}:{c['impresora_puerto']}"
            except Exception as e:
                msg = f"✖ No se pudo conectar con la impresora: {e}"
        else:
            msg = "✔ Configuración guardada"
    return page("config", msg=msg)

def ip_local():
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))
        ip = s.getsockname()[0]
        s.close()
        return ip
    except Exception:
        return "<IP-de-este-PC>"

# ---------------------------------------------------------------- copia de seguridad
# última copia hecha en esta sesión del programa: sirve para avisar en pantalla
ULTIMO_RESPALDO = None

def carpeta_respaldos(c=None):
    c = c or cfg()
    return (c.get("respaldo_carpeta") or "").strip() or os.path.join(BASE, "respaldos")

def hacer_respaldo(c=None):
    """Copia la base de datos a la carpeta de respaldos con la fecha de hoy.
    Conserva solo las últimas 'respaldo_dias' copias. Devuelve la ruta."""
    global ULTIMO_RESPALDO
    c = c or cfg()
    carp = carpeta_respaldos(c)
    os.makedirs(carp, exist_ok=True)
    dest = os.path.join(carp, f"inventario_{datetime.now():%Y-%m-%d}.db")
    if os.path.exists(DB):
        shutil.copy2(DB, dest)
    # queda anotado para avisar en pantalla (lo lee /api/dashboard)
    try:
        ULTIMO_RESPALDO = {"ruta": dest, "cuando": datetime.now().isoformat(timespec="seconds"),
                           "kb": round(os.path.getsize(dest) / 1024) if os.path.exists(dest) else 0}
    except OSError:
        ULTIMO_RESPALDO = {"ruta": dest,
                           "cuando": datetime.now().isoformat(timespec="seconds"), "kb": 0}
    # limpiar viejas: dejar solo las N más recientes
    try:
        dias = max(1, int(c.get("respaldo_dias", 30)))
        copias = sorted(f for f in os.listdir(carp)
                        if f.startswith("inventario_") and f.endswith(".db"))
        for viejo in copias[:-dias]:
            os.remove(os.path.join(carp, viejo))
    except (OSError, TypeError, ValueError):
        pass
    return dest

def bucle_respaldo():
    """Cada minuto revisa si toca la copia diaria. Si el PC estaba apagado a
    la hora fijada, la hace igual cuando se prende (al pasar de esa hora, si
    aún no hay copia de hoy). Corre en segundo plano."""
    while True:
        try:
            c = cfg()
            if c.get("respaldo_activo", True):
                hora = str(c.get("respaldo_hora") or "05:20")
                hh, mm = (hora.split(":") + ["0"])[:2]
                ahora = datetime.now()
                prog = ahora.replace(hour=int(hh) % 24, minute=int(mm) % 60,
                                     second=0, microsecond=0)
                dest = os.path.join(carpeta_respaldos(c),
                                    f"inventario_{ahora:%Y-%m-%d}.db")
                if ahora >= prog and not os.path.exists(dest) and os.path.exists(DB):
                    hacer_respaldo(c)
        except Exception:
            pass
        time.sleep(60)

_respaldo_iniciado = False
def iniciar_respaldos():
    """Arranca el hilo de respaldo una sola vez (solo en la instancia que
    realmente sirve el inventario)."""
    global _respaldo_iniciado
    if not _respaldo_iniciado:
        _respaldo_iniciado = True
        threading.Thread(target=bucle_respaldo, daemon=True).start()

# ---------------------------------------------------------------- actualizaciones
# El programa mira solo si hay una versión nueva publicada en el repositorio y,
# si está activado, se actualiza y se reinicia sin que nadie haga nada.
VERSION = "2.3"
REPO_ACTUALIZACIONES = "wamozart321-pixel/rfid-inventario"
NOMBRE_EXE = "ServidorInventarioRFID.exe"
PRIMERA_REVISION_SEG = 15     # al abrir el programa se mira casi enseguida
MINUTOS_ENTRE_REVISIONES = 60
MINUTOS_MINIMOS = 10          # no se molesta a GitHub más seguido que esto
# lo último que se sabe de las actualizaciones (lo lee la pantalla para avisar)
ESTADO_ACTUALIZACION = {"version": VERSION, "hay": False, "nueva": "", "notas": "",
                        "estado": "", "error": "", "revisado": None}
# cuándo llegó la última lectura de una pistola: no se actualiza a mitad de un
# conteo, se espera a que nadie esté leyendo
ULTIMA_LECTURA = None


def _num_version(v):
    """«v2.10.1» -> (2, 10, 1). Comparar por números y no como texto es lo que
    hace que la 2.10 se entienda MAYOR que la 2.9."""
    nums = re.findall(r"\d+", str(v or ""))
    return tuple(int(n) for n in nums[:4]) if nums else (0,)


def hay_version_nueva(actual, publicada):
    return _num_version(publicada) > _num_version(actual)


def buscar_actualizacion(c=None):
    """Le pregunta al repositorio cuál es la última versión publicada.
    Devuelve un diccionario; 'hay' dice si toca actualizar."""
    import urllib.request
    c = c or cfg()
    repo = str(c.get("actualizar_repo") or REPO_ACTUALIZACIONES).strip()
    req = urllib.request.Request(
        "https://api.github.com/repos/%s/releases/latest" % repo,
        headers={"Accept": "application/vnd.github+json",
                 "User-Agent": "InventarioRFID/" + VERSION})
    with urllib.request.urlopen(req, timeout=20) as r:
        j = json.loads(r.read().decode("utf-8"))
    nueva = str(j.get("tag_name") or "")
    exe = None
    for a in j.get("assets") or []:
        if str(a.get("name") or "").lower() == NOMBRE_EXE.lower():
            exe = a
            break
    info = {"version": VERSION, "nueva": nueva,
            "notas": str(j.get("body") or "")[:4000],
            "url": str((exe or {}).get("browser_download_url") or ""),
            "tamano": int((exe or {}).get("size") or 0),
            "hay": bool(exe) and hay_version_nueva(VERSION, nueva),
            "revisado": datetime.now().isoformat(timespec="seconds"), "error": ""}
    # solo molesta con esto si la publicada es MÁS NUEVA pero no se puede
    # instalar sola; si ya tenemos una igual o mejor, no hay nada que decir
    if nueva and not exe and hay_version_nueva(VERSION, nueva):
        info["error"] = ("la versión %s no trae el programa (%s) para instalar sola"
                         % (nueva, NOMBRE_EXE))
    return info


def _descargar_exe(url, destino, tamano=0):
    """Baja el programa nuevo comprobando que venga de donde debe y que llegue
    entero. Si algo no cuadra se borra y no se instala nada."""
    import urllib.request
    from urllib.parse import urlparse
    u = urlparse(url)
    host = (u.hostname or "").lower()
    if u.scheme != "https" or not (host == "github.com"
                                   or host.endswith(".githubusercontent.com")):
        raise OSError("la descarga no viene de GitHub: se cancela por seguridad")
    req = urllib.request.Request(url, headers={"User-Agent": "InventarioRFID/" + VERSION})
    with urllib.request.urlopen(req, timeout=180) as r, open(destino, "wb") as f:
        shutil.copyfileobj(r, f, 256 * 1024)
    n = os.path.getsize(destino)
    if tamano and n != tamano:
        os.remove(destino)
        raise OSError("la descarga llegó incompleta (%d de %d bytes)" % (n, tamano))
    if n < 1024 * 1024:
        os.remove(destino)
        raise OSError("el archivo descargado es demasiado pequeño (%d bytes)" % n)
    # OJO: hay que CERRAR el archivo antes de borrarlo; Windows no deja
    # borrar lo que sigue abierto.
    with open(destino, "rb") as f:
        cabecera = f.read(2)
    if cabecera != b"MZ":
        os.remove(destino)
        raise OSError("lo descargado no es un programa de Windows")
    return n


def _reiniciar_programa():
    """Se vuelve a abrir solo. En Windows esto hay que hacerlo desde FUERA del
    proceso que se está cerrando, así que se deja una orden esperando."""
    exe = os.path.join(BASE, NOMBRE_EXE)
    if "--sinventana" in sys.argv:
        orden = 'schtasks /run /tn "Inventario RFID Servidor"'
    else:
        orden = 'start "" "%s"' % exe
    subprocess.Popen("cmd /c ping 127.0.0.1 -n 5 >nul & " + orden,
                     shell=True, creationflags=0x00000008 | 0x00000200)


def instalar_actualizacion(info=None):
    """Deja instalada la versión nueva y reinicia el programa.

    En Windows no se puede sobreescribir un .exe en marcha, pero SÍ renombrarlo:
    por eso el que está corriendo se aparta con su número de versión (queda por
    si hay que volver atrás) y el nuevo ocupa su sitio."""
    if not getattr(sys, "frozen", False):
        raise OSError("solo se actualiza solo el programa instalado (.exe)")
    info = info or buscar_actualizacion()
    if not info.get("hay"):
        raise OSError("no hay ninguna versión nueva que instalar")
    ESTADO_ACTUALIZACION.update(estado="descargando", error="")
    actual = os.path.join(BASE, NOMBRE_EXE)
    nuevo = actual + ".nuevo"
    _descargar_exe(info["url"], nuevo, info.get("tamano") or 0)
    try:
        hacer_respaldo()          # copia de la base ANTES de tocar nada
    except Exception:
        pass
    ESTADO_ACTUALIZACION.update(estado="instalando")
    viejo = os.path.join(BASE, "ServidorInventarioRFID_v%s.exe" % VERSION)
    try:
        if os.path.exists(viejo):
            os.remove(viejo)
        os.rename(actual, viejo)          # apartar el que está corriendo
    except OSError as e:
        os.remove(nuevo)
        raise OSError("no se pudo apartar la versión actual: %s" % e)
    try:
        os.rename(nuevo, actual)          # poner el nuevo en su sitio
    except OSError as e:
        os.rename(viejo, actual)          # dejarlo todo como estaba
        raise OSError("no se pudo poner la versión nueva: %s" % e)
    ESTADO_ACTUALIZACION.update(estado="reiniciando", nueva=info.get("nueva", ""))
    _reiniciar_programa()
    threading.Timer(2.0, lambda: os._exit(0)).start()
    return {"instalada": info.get("nueva", ""), "anterior": VERSION, "copia": viejo}


def _nadie_leyendo(minutos=10):
    """True si hace rato que ninguna pistola manda lecturas: es el momento
    seguro para reiniciar sin cortarle el conteo a nadie."""
    if not ULTIMA_LECTURA:
        return True
    return (datetime.now() - ULTIMA_LECTURA) > timedelta(minutes=minutos)


_revisando = False


def _revisado_hace_poco(minutos=MINUTOS_MINIMOS):
    r = ESTADO_ACTUALIZACION.get("revisado")
    if not r:
        return False
    try:
        return (datetime.now() - datetime.fromisoformat(r)) < timedelta(minutes=minutos)
    except (TypeError, ValueError):
        return False


def revisar_si_toca():
    """Lanza una revisión EN SEGUNDO PLANO si hace rato que no se mira. La usa
    la pantalla al abrirse: así el aviso sale a los pocos segundos de entrar,
    sin que nadie tenga que esperar ni pulsar nada."""
    global _revisando
    if _revisando or _revisado_hace_poco():
        return False
    if not cfg().get("actualizar_revisar", True):
        return False
    _revisando = True

    def tarea():
        global _revisando
        try:
            ESTADO_ACTUALIZACION.update(buscar_actualizacion())
        except Exception as e:
            ESTADO_ACTUALIZACION.update(
                error=str(e)[:300],
                revisado=datetime.now().isoformat(timespec="seconds"))
        finally:
            _revisando = False

    threading.Thread(target=tarea, daemon=True).start()
    return True


def bucle_actualizaciones():
    """Cada pocas horas mira si hay versión nueva. Si «actualizar_auto» está
    puesto, la instala sola cuando nadie está leyendo con la pistola."""
    time.sleep(PRIMERA_REVISION_SEG)   # al arrancar se mira casi enseguida
    while True:
        try:
            c = cfg()
            if c.get("actualizar_revisar", True):
                info = buscar_actualizacion(c)
                ESTADO_ACTUALIZACION.update(info)
                if info.get("hay") and c.get("actualizar_auto", True) \
                        and getattr(sys, "frozen", False) and _nadie_leyendo():
                    instalar_actualizacion(info)
        except Exception as e:
            ESTADO_ACTUALIZACION.update(
                error=str(e)[:300],
                revisado=datetime.now().isoformat(timespec="seconds"))
        time.sleep(max(1, int(MINUTOS_ENTRE_REVISIONES)) * 60)


_actualizaciones_iniciado = False


def iniciar_actualizaciones():
    """Arranca el vigilante una sola vez (solo en la instancia que sirve)."""
    global _actualizaciones_iniciado
    if not _actualizaciones_iniciado:
        _actualizaciones_iniciado = True
        threading.Thread(target=bucle_actualizaciones, daemon=True).start()


@app.get("/api/actualizacion")
def api_actualizacion():
    """Lo último que se sabe. De paso lanza una revisión en segundo plano si
    hace rato que no se mira, así el aviso aparece a los pocos segundos."""
    revisar_si_toca()
    return jsonify(dict(ESTADO_ACTUALIZACION, version=VERSION,
                        instalable=bool(getattr(sys, "frozen", False))))


@app.post("/api/actualizacion/buscar")
def api_actualizacion_buscar():
    """Mira AHORA si hay versión nueva (botón de ⚙ Configuración)."""
    try:
        info = buscar_actualizacion()
    except Exception as e:
        ESTADO_ACTUALIZACION.update(error=str(e)[:300])
        return jsonify(ok=False, error="No se pudo consultar: %s" % e), 502
    ESTADO_ACTUALIZACION.update(info)
    return jsonify(ok=True, **dict(info, instalable=bool(getattr(sys, "frozen", False))))


@app.post("/api/actualizacion/instalar")
def api_actualizacion_instalar():
    """Instala la versión nueva y reinicia el programa."""
    try:
        r = instalar_actualizacion()
    except OSError as e:
        ESTADO_ACTUALIZACION.update(estado="", error=str(e)[:300])
        return jsonify(ok=False, error=str(e)), 502
    except Exception as e:
        ESTADO_ACTUALIZACION.update(estado="", error=str(e)[:300])
        return jsonify(ok=False, error="Falló la actualización: %s" % e), 502
    return jsonify(ok=True, msg="Actualizado a la versión %s. El programa se "
                                "reinicia solo en unos segundos." % r["instalada"], **r)


def esperar_servidor(timeout=10):
    """Espera a que el puerto 5000 responda antes de abrir la ventana."""
    import time
    for _ in range(int(timeout * 10)):
        try:
            s = socket.create_connection(("127.0.0.1", 5000), timeout=0.3)
            s.close()
            return True
        except OSError:
            time.sleep(0.1)
    return False

if __name__ == "__main__":
    init_db()
    ip = ip_local()
    print("\n  Sistema de Inventario RFID")
    print("  Local:   http://localhost:5000")
    print(f"  Red:     http://{ip}:5000  (usar esta URL en la pistola)\n")
    def correr():
        iniciar_respaldos()        # copia de seguridad diaria (solo quien sirve)
        iniciar_actualizaciones()  # se pone al dia solo cuando hay version nueva
        app.run(host="0.0.0.0", port=5000, debug=False)
    if "--sinventana" in sys.argv:
        # Modo PC SERVIDOR (siempre prendido): corre sin ventana y no se apaga
        # por accidente. Los demás PCs y la pistola entran por la red.
        # El instalador lo pone como TAREA de Windows: arranca al prender el
        # PC aunque nadie inicie sesión.
        print("  Modo servidor sin ventana (--sinventana)\n")
        correr()
        sys.exit(0)
    if esperar_servidor(1.5):
        # Ya hay un servidor corriendo en este PC (la tarea del modo servidor):
        # solo se muestra una ventanita informativa NEGRA. Cerrarla no apaga
        # nada — el servidor de verdad sigue corriendo como tarea.
        try:
            import webview
            pag = f"""<!doctype html><html lang="es"><head><meta charset="utf-8"></head>
<body style="background:#111;color:#EAEAEA;font-family:'Segoe UI',Arial,sans-serif;
             display:flex;align-items:center;justify-content:center;height:96vh;margin:0">
  <div style="text-align:center;max-width:540px;padding:20px">
    <div style="font-size:54px">🟢</div>
    <h2 style="color:#7CE38B;margin:10px 0 4px">El servidor del inventario está corriendo</h2>
    <p style="font-size:15px;line-height:1.8;color:#C8C8C8">
      Este PC es el <b>SERVIDOR</b>. Los demás PCs y la pistola entran a:<br>
      <span style="font-family:Consolas,monospace;font-size:19px;color:#fff">http://{ip}:5000</span></p>
    <p style="color:#8A8A8A;font-size:13px;line-height:1.7">Puedes cerrar esta ventanita
      tranquilamente: el servidor <b>sigue corriendo</b> como tarea de Windows,
      incluso sin iniciar sesión en este PC.</p>
  </div></body></html>"""
            webview.create_window("Servidor Inventario RFID · corriendo",
                                  html=pag, width=660, height=430)
            webview.start()
        except ImportError:
            print("  El servidor ya está corriendo en este PC.")
        sys.exit(0)
    try:
        # Ventana propia de la aplicación: al cerrarla se apaga el servidor.
        import webview
        import threading
        threading.Thread(target=correr, daemon=True).start()
        esperar_servidor()
        webview.create_window(f"Inventario RFID · SERVIDOR · en la pistola usa http://{ip}:5000",
                              "http://127.0.0.1:5000/escritorio?modo=principal",
                              width=1280, height=820)
        webview.start()
    except ImportError:
        # Sin pywebview: modo clásico con navegador.
        import threading, webbrowser
        threading.Timer(1.2, lambda: webbrowser.open("http://localhost:5000")).start()
        correr()
