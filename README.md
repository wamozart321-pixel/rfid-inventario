# Sistema de Inventario RFID
### Chainway C72 + Zebra ZT411 + PC Windows — compatible con otros lectores

Dos piezas que se comunican por tu red WiFi/LAN:

```
┌─────────────┐   WiFi (HTTP)   ┌──────────────────┐   Red :9100 (ZPL)  ┌───────────┐
│ Chainway C72 │ ──────────────► │  PC Windows       │ ─────────────────► │ Zebra     │
│ (app Android)│                 │  servidor + web   │                    │ ZT411     │
└─────────────┘                 └──────────────────┘                    └───────────┘
        otros lectores (modo teclado) ──► página "Captura rápida"
```

---

## 1. Servidor en Windows (`servidor/`)

**Instalar (una sola vez):**
1. Instala Python 3.10+ desde https://www.python.org (marca ✔ "Add Python to PATH").
2. Abre CMD en la carpeta `servidor` y ejecuta:
   ```
   pip install flask
   ```

**Ejecutar:**
```
python app.py
```
Abre `http://localhost:5000` en el navegador. Desde la pistola u otros equipos usa
`http://IP-DEL-PC:5000` (averigua la IP con `ipconfig`; permite el puerto 5000 en el
Firewall de Windows la primera vez).

**Qué incluye:**
- **Productos**: alta de SKU, nombre, ubicación y cantidad esperada. Asociación de
  tags EPC a cada producto (varios tags por producto).
- **Conteos (sesiones)**: abre una sesión, dispara con la pistola, y ve en tiempo
  real completos / parciales / faltantes, más los EPC desconocidos. Exporta a CSV
  (abre en Excel).
- **Captura rápida**: un campo de texto que recibe lecturas de **cualquier lector
  en modo teclado** (C72 con emulación de teclado, lectores USB, otras marcas).
  Así el sistema no queda amarrado a una sola pistola.
- **Impresión Zebra ZT411**: botón "Imprimir" por producto → genera ZPL y lo manda
  a la impresora por red (puerto 9100). En **Configuración** pones la IP de la
  impresora, DPI (203/300/600 según tu ZT411) y el tamaño de etiqueta en mm.
  - Si tu impresora es **ZT411R (con módulo RFID)**, activa "Codificar RFID":
    al imprimir escribirá el EPC que indiques dentro del inlay de la etiqueta
    (comando `^RFW`). Con una ZT411 normal deja la casilla apagada.
  - También funciona con **cualquier otra impresora Zebra** (ZT2xx, ZT6xx, GK/GX,
    ZD…) porque todas hablan ZPL por el puerto 9100.

**API para integrar otras pistolas o sistemas:**
- `POST /api/lecturas` — `{"dispositivo":"C72-01","epcs":["E280...","E280..."]}`
- `POST /api/tags` — `{"epc":"E280...","sku":"A1"}` (asociar tag a producto)
- `GET /api/estado` — sesión activa

---

## 2. App Android para la C72 (`android-c72/`)

Proyecto de **Android Studio** en Kotlin. Antes de compilar necesitas el SDK
oficial de Chainway (gratuito):

1. Descárgalo de **chainway.net → Support → Download → C72** (o pídelo a tu
   distribuidor). El archivo es tipo `DeviceAPI_ver20240XXX_release.jar`.
2. Cópialo en `android-c72/app/libs/`. Si el SDK trae carpetas `arm64-v8a` /
   `armeabi-v7a` con archivos `.so`, cópialas en `app/src/main/jniLibs/`.
3. Abre la carpeta `android-c72` en Android Studio → Sync → **Build APK**.
4. Instala el APK en la C72 (por USB o copiándolo a la memoria).

**Uso en la pistola:**
- Botón **⚙**: escribe la URL del servidor (`http://IP-DEL-PC:5000`) y el nombre
  del equipo (ej. `C72-01`).
- **Gatillo físico** o botón **▶ LEER**: lectura continua; acumula EPC únicos.
- **Enviar**: manda todo al servidor (se guarda en la sesión de conteo activa).
- **Asociar**: escribes un SKU, acercas una etiqueta, y ese EPC queda vinculado
  al producto (para etiquetar mercancía nueva sin tocar el PC).

> Nota: si la firma exacta del callback del SDK cambió en tu versión del jar
> (Chainway lo actualiza), Android Studio te lo marcará en `MainActivity.kt`;
> son 2-3 líneas (`setInventoryCallback`, `startInventoryTag`,
> `inventorySingleTag`) fáciles de ajustar con el demo que trae el SDK.

**Alternativa sin compilar nada:** activa en la C72 el modo *emulación de
teclado* (app "KeyboardEmulator" que viene preinstalada por Chainway), abre el
navegador de la pistola en `http://IP-DEL-PC:5000/captura` y dispara: cada
lectura entra directo al sistema. Esto mismo sirve para lectores de otras marcas.

---

## 3. Flujo de trabajo recomendado

1. **Alta de productos** en la web (SKU, nombre, ubicación, cantidad esperada).
2. **Etiquetar**: imprime etiquetas en la ZT411
   (con ZT411R además se graba el EPC), o usa el botón **Asociar** de la pistola
   con etiquetas pre-codificadas.
3. **Contar**: abre una sesión en "Conteos", recorre la bodega disparando,
   pulsa **Enviar** en la pistola.
4. **Revisar**: la sesión muestra completos/parciales/faltantes y EPC
   desconocidos. Exporta el CSV para Excel.

## Archivos
```
servidor/app.py            ← backend: web + API + impresión ZPL
servidor/templates/        ← frontend (páginas HTML)
servidor/static/           ← frontend (estilos y JS; funciona sin internet)
servidor/config.json       ← se crea solo; IP de impresora, tamaño etiqueta, etc.
servidor/inventario.db     ← base de datos SQLite (se crea sola)
android-c72/               ← proyecto Android Studio para la pistola
```

**El frontend** es responsivo (sirve en el navegador de la pistola también) y
funciona 100% offline: sin CDNs ni librerías externas.
- **Panel**: KPIs y "antena" con las últimas lecturas en vivo (se refresca solo
  cada 3 s mientras disparas).
- **Conteos**: barras de progreso por producto que se actualizan solas mientras
  la sesión está abierta; lista en vivo de EPC desconocidos.
- **Productos**: buscador instantáneo, impresión y asociación de tags en línea.
- **Captura rápida**: mantiene el foco en el campo, pitido de confirmación
  (agudo = producto reconocido, grave = EPC sin asociar).
- **Configuración**: botón "Guardar y probar impresora" que manda una etiqueta
  de prueba a la ZT411.
