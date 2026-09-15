# Pruebas

Comprueban que el programa sigue haciendo lo que debe. **No tocan el
inventario de verdad**: cada prueba se crea su propia base de datos en una
carpeta temporal.

## Cómo correrlas

Doble clic en **`Correr pruebas.bat`**, o desde una consola:

```
python correr.py              todas
python correr.py balizas      solo las de balizas
python test_balizas.py        una sola, con todo el detalle
```

Sale una línea por prueba y un resumen al final. Si algo falla, dice cuál y
con qué mensaje.

## Qué cubre cada una

| Prueba | Qué vigila |
|---|---|
| `test_balizas.py` | Las balizas sitúan a la pistola; gana el sitio donde más se vio el repuesto; nada se guarda sin confirmar |
| `test_balizas_imprimir.py` | Impresión por lotes, el EPC lleva la posición dentro, reimprimir conserva el chip |
| `test_balizas_pistola_real.py` | El recorrido tal como lo hace la pistola: cada repuesto cae en SU pasillo |
| `test_balizas_pistolas.py` | El aviso de si la pistola está viendo las balizas |
| `test_rotacion_asesores.py` | Los asesores pueden cambiar la rotación; lo demás les sigue vedado |
| `test_impresora_windows.py` | Imprimir por red o por la cola de Windows (USB) |
| `test_actualizaciones.py` | Se actualiza solo: descarga, comprueba, guarda copia y reinicia |
| `test_upd_rapido.py` | Avisa al abrir el programa, sin machacar a GitHub |
| `test_certificados.py` | El certificado de GitHub SIEMPRE se comprueba; los errores se explican |
| `test_modo_oscuro.py` | Contraste del modo oscuro y ningún fondo blanco fijo suelto |
| `test_modos_cliente.py` | Un solo programa para PC principal, mostrador y vendedor |

## Si escribes una prueba nueva

Empieza igual que las demás:

```python
from _comun import ruta          # deja el programa a mano
import app as A

TMP = tempfile.mkdtemp(prefix="rfid_loquesea_")
A.DB = os.path.join(TMP, "t.db")
A.CFG = os.path.join(TMP, "c.json")
A.BASE = TMP
A.init_db()
```

**Esas cuatro líneas no son opcionales.** Sin ellas la prueba escribe en el
inventario real: ya pasó una vez y dejó productos inventados dentro de la
base buena.

## Por qué están aquí

Antes vivían en una carpeta temporal de Windows y se borraron solas: de 70
pruebas quedaron 11. Dentro del repositorio van con el código y no se pierden.
Faltan por rehacer las que cubrían códigos de barras, precios, etiquetas e
importaciones.
