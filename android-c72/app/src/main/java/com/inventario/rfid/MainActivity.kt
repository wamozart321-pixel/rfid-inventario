package com.inventario.rfid

import android.app.AlertDialog
import android.os.Bundle
import android.os.Handler
import android.os.Looper
import android.view.KeyEvent
import android.view.View
import android.view.ViewGroup
import android.widget.*
import androidx.appcompat.app.AppCompatActivity
import com.rscja.barcode.BarcodeDecoder
import com.rscja.barcode.BarcodeFactory
import com.rscja.deviceapi.RFIDWithUHFUART
import com.rscja.deviceapi.entity.UHFTAGInfo
import org.json.JSONArray
import org.json.JSONObject
import java.io.OutputStreamWriter
import java.net.HttpURLConnection
import java.net.Inet4Address
import java.net.NetworkInterface
import java.net.URL
import java.util.Collections
import java.util.concurrent.Executors
import kotlin.concurrent.thread

/**
 * Lector de inventario para Chainway C72 (SDK Chainway / DeviceAPI).
 * - Gatillo físico o botón para leer RFID en modo continuo.
 * - Acumula EPC únicos con contador.
 * - Envía las lecturas al servidor (POST /api/lecturas).
 * - Modo "asociar": el próximo EPC leído se vincula a un SKU (POST /api/tags).
 * - Escáner 2D/código de barras integrado: el código escaneado sirve de SKU
 *   para asociar tags sin teclear.
 */
class MainActivity : AppCompatActivity() {

    private var uhf: RFIDWithUHFUART? = null
    private var barcode: BarcodeDecoder? = null
    private var inputSkuActivo: EditText? = null              // campo SKU abierto en el diálogo Asociar
    private var loteSku: String? = null                       // modo lote: SKU al que se asocia todo lo leído
    private val loteAsociadas = HashSet<String>()
    private val nombres = HashMap<String, String>()           // EPC -> "NOMBRE (sku)"
    private val epcSku = HashMap<String, String>()            // EPC -> sku (para el filtro)
    private val consultados = HashSet<String>()               // EPC ya preguntados al servidor
    private var resolviendo = false
    private var wifiLock: android.net.wifi.WifiManager.WifiLock? = null

    // Catálogo local EPC->producto (se descarga UNA vez del servidor): las
    // etiquetas se reconocen AL INSTANTE y sin tocar la red mientras se lee.
    // Sin red durante la lectura = contador inmediato y sin trabas.
    private var catalogo = HashMap<String, Pair<String, String>>()   // epc -> (sku, nombre)
    private var productosId = HashMap<Int, Pair<String, String>>()   // id -> (sku, nombre)
    private var ignorados = HashSet<String>()                        // EPC ajenos
    private var marcaEpc = "AF01"
    private var filtroSku: String? = null                     // modo "solo un producto"
    private lateinit var btnFiltro: Button
    private var leyendo = false
    private val tags = LinkedHashMap<String, Int>()          // EPC -> nº de lecturas
    private lateinit var adaptador: AdaptadorRepuestos
    private val ui = Handler(Looper.getMainLooper())

    /** Una fila de la lista = un REPUESTO (no una etiqueta suelta). */
    private class FilaRepuesto(val sku: String, val etiqueta: String,
                               val unidades: Int, val veces: Int)

    /** Pinta cada repuesto con la cantidad en NARANJA y las veces leído en BLANCO. */
    private inner class AdaptadorRepuestos :
        ArrayAdapter<FilaRepuesto>(this, R.layout.fila_repuesto) {
        override fun getView(pos: Int, reuso: View?, padre: ViewGroup): View {
            val v = reuso ?: layoutInflater.inflate(R.layout.fila_repuesto, padre, false)
            val f = getItem(pos)
            if (f != null) {
                v.findViewById<TextView>(R.id.fNombre).text = f.etiqueta
                v.findViewById<TextView>(R.id.fCant).text = "${f.unidades}"
                v.findViewById<TextView>(R.id.fVeces).text = "×${f.veces}"
            }
            return v
        }
    }
    private var tono: android.media.ToneGenerator? = null

    // pitido corto al detectar una etiqueta nueva (se puede apagar en ⚙)
    private fun pitar() {
        if (!prefs.getBoolean("beep", true)) return
        try { tono?.startTone(android.media.ToneGenerator.TONE_PROP_BEEP, 70) } catch (_: Throwable) {}
    }

    // Las lecturas RFID llegan a cientos por segundo: se acumulan aquí (fuera
    // del hilo de pantalla) y un temporizador las vuelca 4 veces por segundo.
    // Actualizar la pantalla en cada lectura congelaba la app ("no responde").
    private val pendientes = HashMap<String, Int>()
    private val candado = Any()
    private var tasaSeg = 0          // lecturas por segundo (se muestra en pantalla)
    private var cuentaSeg = 0
    private var tUltTasa = 0L
    private val tictac = object : Runnable {
        override fun run() {
            volcarPendientes()
            if (leyendo) ui.postDelayed(this, 250)
        }
    }

    private fun volcarPendientes() {
        val lote: Map<String, Int>
        synchronized(candado) {
            if (pendientes.isEmpty()) return
            lote = HashMap(pendientes)
            pendientes.clear()
        }
        // medidor de lecturas por segundo (se muestra en la línea de estado)
        cuentaSeg += lote.values.sum()
        val ahora = System.currentTimeMillis()
        if (tUltTasa == 0L) tUltTasa = ahora
        else if (ahora - tUltTasa >= 1000) {
            tasaSeg = (cuentaSeg * 1000L / (ahora - tUltTasa)).toInt()
            cuentaSeg = 0; tUltTasa = ahora
        }
        if (leyendo && loteSku == null && tasaSeg > 0)
            estado.text = "Leyendo…   ⚡ $tasaSeg/s   ·   📡 ${tags.size} etiquetas"
        val f = filtroSku
        var cambio = false
        var nuevo = false
        for ((epc, n) in lote) {
            if (epc in ignorados) continue                 // ajeno: ni contarlo
            val conocido = reconocer(epc)                  // catálogo local: SIN red
            if (f != null) {
                // Modo "solo un producto": lo que no sea de ese SKU se ignora
                if (conocido && epcSku[epc] != f) continue
                if (!conocido && epc in consultados) continue
            }
            if (epc !in tags) nuevo = true                 // etiqueta nunca vista
            tags[epc] = (tags[epc] ?: 0) + n
            cambio = true
            val sku = loteSku
            if (sku != null && loteAsociadas.add(epc)) asociarEnLote(epc, sku)
        }
        if (nuevo) pitar()
        if (cambio) pintar()                               // nada de red mientras se lee
    }

    private lateinit var estado: TextView
    private lateinit var contador: TextView
    private lateinit var btnLeer: Button
    private lateinit var bannerDesc: Button
    private val autoEnviados = HashSet<String>()              // desconocidos ya reportados solos

    private val prefs by lazy { getSharedPreferences("cfg", MODE_PRIVATE) }
    private val urlServidor get() = prefs.getString("url", "http://192.168.1.10:5000")!!
    private val nombreEquipo get() = prefs.getString("nombre", "C72-01")!!

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        setContentView(R.layout.activity_main)

        estado = findViewById(R.id.estado)
        contador = findViewById(R.id.contador)
        btnLeer = findViewById(R.id.btnLeer)
        val lista = findViewById<ListView>(R.id.lista)
        adaptador = AdaptadorRepuestos()
        lista.adapter = adaptador

        btnLeer.setOnClickListener { if (leyendo) detener() else iniciar() }
        lista.setOnItemClickListener { _, _, pos, _ ->
            val sku = skusMostrados.getOrNull(pos) ?: return@setOnItemClickListener
            detalleRepuesto(sku)
        }
        findViewById<Button>(R.id.btnLimpiar).setOnClickListener {
            tags.clear(); refrescar()
        }
        findViewById<Button>(R.id.btnDesc).setOnClickListener { mostrarDesconocidos() }
        bannerDesc = findViewById(R.id.bannerDesc)
        bannerDesc.setOnClickListener { mostrarDesconocidos() }
        btnFiltro = findViewById(R.id.btnFiltro)
        btnFiltro.setOnClickListener { dialogoFiltro() }
        findViewById<Button>(R.id.btnEnviar).setOnClickListener { enviar() }
        findViewById<Button>(R.id.btnAsociar).setOnClickListener { dialogoAsociar() }
        findViewById<Button>(R.id.btnConfig).setOnClickListener { dialogoConfig() }
        findViewById<Button>(R.id.btnCodigo).setOnClickListener {
            barcode?.startScan() ?: toast("Escáner 2D no disponible en este equipo")
        }

        try { tono = android.media.ToneGenerator(android.media.AudioManager.STREAM_MUSIC, 90) } catch (_: Throwable) {}
        sujetarWifi()
        cargarCatalogoLocal()
        refrescarCatalogo()
        conectarLector()
    }

    // Mantiene el WiFi despierto mientras la app está abierta (el RFID a plena
    // potencia tiende a interferirlo).
    private fun sujetarWifi() {
        try {
            val wm = applicationContext.getSystemService(WIFI_SERVICE) as android.net.wifi.WifiManager
            wifiLock = wm.createWifiLock(
                android.net.wifi.WifiManager.WIFI_MODE_FULL_HIGH_PERF, "inventario-c72"
            ).apply { setReferenceCounted(false); acquire() }
        } catch (_: Throwable) {}
    }

    // --------------------------------------------- catálogo local (sin red al leer)
    private fun archivoCatalogo() = java.io.File(filesDir, "catalogo.json")

    private fun aplicarCatalogo(o: JSONObject) {
        val cat = HashMap<String, Pair<String, String>>()
        val pro = HashMap<Int, Pair<String, String>>()
        val ign = HashSet<String>()
        o.optJSONObject("tags")?.let { t ->
            val it2 = t.keys()
            while (it2.hasNext()) {
                val epc = it2.next()
                val a = t.optJSONArray(epc) ?: continue
                cat[epc] = Pair(a.optString(0), a.optString(1))
            }
        }
        o.optJSONObject("productos")?.let { p ->
            val it2 = p.keys()
            while (it2.hasNext()) {
                val id = it2.next()
                val a = p.optJSONArray(id) ?: continue
                id.toIntOrNull()?.let { pro[it] = Pair(a.optString(0), a.optString(1)) }
            }
        }
        o.optJSONArray("ignorados")?.let { for (i in 0 until it.length()) ign.add(it.optString(i)) }
        marcaEpc = o.optString("marca", "AF01")
        catalogo = cat; productosId = pro; ignorados = ign
    }

    private fun cargarCatalogoLocal() {
        try {
            val f = archivoCatalogo()
            if (f.exists()) aplicarCatalogo(JSONObject(f.readText()))
        } catch (_: Throwable) {}
    }

    /** Baja el catálogo del servidor en segundo plano (al abrir la app y tras asociar). */
    private fun refrescarCatalogo() {
        thread {
            try {
                val c = URL("$urlServidor/api/tags/todos").openConnection() as HttpURLConnection
                c.connectTimeout = 6000; c.readTimeout = 30000
                val txt = c.inputStream.bufferedReader().readText()
                val o = JSONObject(txt)
                try { archivoCatalogo().writeText(txt) } catch (_: Throwable) {}
                ui.post {
                    aplicarCatalogo(o)
                    if (!leyendo) pintar()
                }
            } catch (_: Exception) {}
        }
    }

    /** Reconoce un EPC con el catálogo local (o el formato AF01+id). true = producto conocido. */
    private fun reconocer(epc: String): Boolean {
        if (nombres[epc] != null) return true
        var p = catalogo[epc]
        if (p == null && epc.length == 24 && epc.startsWith(marcaEpc)) {
            val id = epc.substring(4, 10).toIntOrNull(16)
            if (id != null) p = productosId[id]
        }
        if (p == null) return false
        epcSku[epc] = p.first
        nombres[epc] = "${p.second} (${p.first})"
        return true
    }

    private fun agregarAlCatalogo(epc: String, sku: String, nombre: String) {
        catalogo[epc] = Pair(sku, nombre)
        epcSku[epc] = sku
        nombres[epc] = "$nombre ($sku)"
    }

    // ------------------------------------------------ lector UHF + escáner 2D
    private fun conectarLector() {
        thread {
            val okUhf = try {
                uhf = RFIDWithUHFUART.getInstance()
                uhf!!.init(applicationContext)
            } catch (e: Throwable) { false }
            if (okUhf) {
                // potencia MÁXIMA por defecto (30 dBm) — se puede bajar en ⚙
                try { uhf?.setPower(prefs.getInt("potencia", 30)) } catch (_: Throwable) {}
                // solo EPC (sin TID/USER): más lecturas por segundo
                try { uhf?.setEPCMode() } catch (_: Throwable) {}
                // sesión Gen2 S0 + target A: las etiquetas responden SIN PARAR
                // (en S1/S2 se callan un rato tras contestar y se ven 2-3
                // lecturas por segundo). Esto multiplica las lecturas/s.
                try {
                    val g = uhf?.getGen2()
                    if (g != null) {
                        g.querySession = 0   // S0
                        g.queryTarget = 0    // A
                        uhf?.setGen2(g)
                    }
                } catch (_: Throwable) {}
            }
            val okBar = try {
                val b = BarcodeFactory.getInstance().getBarcodeDecoder()
                if (b.open(applicationContext)) {
                    b.setDecodeCallback { ent ->
                        if (ent.resultCode == BarcodeDecoder.DECODE_SUCCESS) {
                            val dato = ent.barcodeData?.trim()
                            if (!dato.isNullOrEmpty()) ui.post { pitar(); onBarcode(dato) }
                        }
                    }
                    barcode = b
                    true
                } else false
            } catch (e: Throwable) { false }
            ui.post {
                estado.text = "RFID ${if (okUhf) "✔" else "✖"} · Código 2D ${if (okBar) "✔" else "✖"} · $nombreEquipo"
            }
        }
    }

    // Código de barras leído: se le pregunta al servidor qué producto es (sirve
    // la referencia o el código impreso con precios) y el campo se cambia solo
    // al SKU, mostrando el nombre para confirmar que lo reconoció.
    private fun onBarcode(dato: String) {
        val campo = inputSkuActivo
        if (campo != null) {
            campo.setText(dato)
            thread {
                try {
                    val r = getJsonObj("$urlServidor/api/buscar_producto?codigo=" +
                            java.net.URLEncoder.encode(dato, "UTF-8"))
                    ui.post {
                        if (r.optBoolean("ok")) {
                            val sku = r.optString("sku")
                            inputSkuActivo?.setText(sku)          // código -> SKU
                            estado.text = "✔ ${r.optString("nombre")}"
                            toast("✔ ${r.optString("nombre")} ($sku)")
                        } else {
                            toast("✖ Código $dato: no corresponde a ningún producto")
                        }
                    }
                } catch (_: Exception) {
                    ui.post { toast("Código: $dato (sin conexión para identificarlo)") }
                }
            }
        } else {
            thread {
                var titulo = "Código leído"; var mensaje = dato; var sku = dato
                try {
                    val r = getJsonObj("$urlServidor/api/buscar_producto?codigo=" +
                            java.net.URLEncoder.encode(dato, "UTF-8"))
                    if (r.optBoolean("ok")) {
                        sku = r.optString("sku")
                        titulo = "Producto reconocido"
                        mensaje = "${r.optString("nombre")}\n\nReferencia: $sku"
                    }
                } catch (_: Exception) {}
                ui.post {
                    AlertDialog.Builder(this)
                        .setTitle(titulo)
                        .setMessage(mensaje)
                        .setPositiveButton("Asociar tags a este producto") { _, _ -> dialogoAsociar(sku) }
                        .setNegativeButton("Cerrar", null).show()
                }
            }
        }
    }

    private fun iniciar() {
        val u = uhf ?: return toast("Lector no inicializado")
        // Callback de inventario continuo (SDK Chainway): SOLO acumula — nada
        // de pantalla aquí; el temporizador tictac hace el resto sin congelar.
        u.setInventoryCallback { info: UHFTAGInfo ->
            val epc = info.epc?.uppercase() ?: return@setInventoryCallback
            synchronized(candado) {
                pendientes[epc] = (pendientes[epc] ?: 0) + 1
            }
        }
        tasaSeg = 0; cuentaSeg = 0; tUltTasa = 0L
        if (u.startInventoryTag()) {
            leyendo = true
            btnLeer.text = "■ DETENER"
            estado.text = "Leyendo…"
            ui.removeCallbacks(tictac)
            ui.postDelayed(tictac, 250)
        } else toast("No se pudo iniciar la lectura")
    }

    private fun detener() {
        uhf?.stopInventory()
        leyendo = false
        ui.removeCallbacks(tictac)
        volcarPendientes()                     // lo último leído no se pierde
        resolverNombres()      // ya sin leer: consulta al servidor lo no reconocido
        btnLeer.text = "▶ LEER"
        val sku = loteSku
        if (sku != null) {
            loteSku = null
            estado.text = "✔ Lote terminado: ${loteAsociadas.size} etiquetas → $sku"
            toast("✔ ${loteAsociadas.size} etiquetas asociadas a $sku")
            refrescarCatalogo()
        } else estado.text = "Detenido · ${tags.size} EPC únicos"
    }

    // Modo lote: cada EPC nuevo leído se asocia de inmediato al SKU elegido
    private fun asociarEnLote(epc: String, sku: String) {
        estado.text = "LOTE $sku · asociadas: ${loteAsociadas.size} · gatillo para terminar"
        thread {
            try {
                val r = post("$urlServidor/api/tags", JSONObject().put("epc", epc).put("sku", sku))
                if (!r.optBoolean("ok")) ui.post {
                    loteAsociadas.remove(epc)
                    toast("✖ ${r.optString("error")}")
                } else ui.post {
                    consultados.remove(epc)
                    agregarAlCatalogo(epc, r.optString("sku", sku), r.optString("nombre", sku))
                    pintar()
                }
            } catch (e: Exception) {
                ui.post { loteAsociadas.remove(epc); toast("Error de red: ${e.message}") }
            }
        }
    }

    private fun refrescar() {
        pintar()
        if (!leyendo) resolverNombres()
    }

    private val skusMostrados = ArrayList<String>()           // fila de la lista -> SKU

    // La lista principal solo muestra productos reconocidos; los desconocidos
    // van al banner (y se reportan solos al servidor).
    private fun pintar() {
        val f = filtroSku
        // El contador naranja solo suma etiquetas registradas (y del producto
        // elegido, si hay filtro). Los desconocidos nunca cuentan.
        val visibles = tags.entries.filter {
            nombres[it.key] != null && (f == null || epcSku[it.key] == f)
        }
        contador.text = "${visibles.size}"
        val descon = if (f == null) tags.keys.count { nombres[it] == null } else 0
        bannerDesc.visibility = if (descon == 0) View.GONE else View.VISIBLE
        if (descon > 0) bannerDesc.text = "¿? Desconocidos: $descon — tocar para revisar"

        // Una fila POR REPUESTO: se juntan todas sus etiquetas.
        //   naranja = cuántas unidades (etiquetas distintas) se han leído
        //   blanco  = cuántas veces las ha visto el lector en total
        val porSku = LinkedHashMap<String, IntArray>()
        val rotulo = HashMap<String, String>()
        for (e in visibles) {
            val sku = epcSku[e.key] ?: continue
            val a = porSku.getOrPut(sku) { IntArray(2) }
            a[0]++; a[1] += e.value
            if (sku !in rotulo) rotulo[sku] = nombres[e.key] ?: sku
        }
        adaptador.clear()
        skusMostrados.clear()
        for ((sku, a) in porSku) {
            skusMostrados.add(sku)
            adaptador.add(FilaRepuesto(sku, rotulo[sku] ?: sku, a[0], a[1]))
        }
    }

    /** Tocar un repuesto: detalle con sus etiquetas una por una. */
    private fun detalleRepuesto(sku: String) {
        val epcs = tags.keys.filter { epcSku[it] == sku }
        if (epcs.isEmpty()) return
        val veces = epcs.map { tags[it] ?: 0 }.sum()
        val txt = StringBuilder("Cantidad leída: ${epcs.size}\nVeces leído: $veces\n\nEtiquetas:\n")
        for (e in epcs.take(40)) txt.append("• $e   ×${tags[e]}\n")
        if (epcs.size > 40) txt.append("… y ${epcs.size - 40} más")
        AlertDialog.Builder(this).setTitle(nombres[epcs[0]] ?: sku)
            .setMessage(txt.toString()).setPositiveButton("Cerrar", null).show()
    }

    // Pregunta al servidor los nombres de los EPC que aún no conoce (en lote)
    private fun resolverNombres() {
        if (leyendo) return          // JAMÁS usar la red mientras se está leyendo
        val faltan = tags.keys.filter { it !in nombres && it !in consultados }
        if (faltan.isEmpty() || resolviendo) return
        resolviendo = true
        thread {
            try {
                val r = post("$urlServidor/api/resolver",
                    JSONObject().put("epcs", JSONArray(faltan)))
                ui.post {
                    val f = filtroSku
                    val nuevosDesc = ArrayList<String>()
                    for (epc in faltan) {
                        consultados.add(epc)
                        val o = r.optJSONObject(epc)
                        if (o != null) {
                            agregarAlCatalogo(epc, o.optString("sku"), o.optString("nombre"))
                            if (f != null && epcSku[epc] != f) tags.remove(epc)   // otro producto
                        } else {
                            if (f != null) tags.remove(epc)   // desconocido en modo producto: fuera
                            else if (autoEnviados.add(epc)) nuevosDesc.add(epc)
                        }
                    }
                    resolviendo = false
                    pintar()
                    if (nuevosDesc.isNotEmpty()) enviarDesconocidos(nuevosDesc)
                }
            } catch (e: Exception) {
                ui.post { resolviendo = false }   // sin red: se quedan los EPC crudos
            }
        }
    }

    // Teclas físicas medidas en esta C72:
    //  - laterales: derecho = 139 (F9), izquierdo = 142 (F12) -> escanear código
    //  - gatillo empuñadura -> RFID (códigos de gatillo del demo Chainway)
    private val teclasEscaner = setOf(139, 142, 249, 250, 251, 252)
    private val teclasGatillo = setOf(280, 291, 293, 294, 311, 312, 313, 315, 591, 593, 594, 595, 596)

    override fun onKeyDown(keyCode: Int, event: KeyEvent?): Boolean {
        if (keyCode in teclasEscaner) {
            if (event?.repeatCount == 0) {
                barcode?.startScan() ?: toast("Escáner 2D no disponible")
            }
            return true
        }
        // Gatillo IGUAL que las demos: se lee MIENTRAS está apretado y al
        // soltarlo se detiene. (El botón ▶ de pantalla sigue siendo prender/apagar.)
        if (keyCode in teclasGatillo) {
            if (event?.repeatCount == 0 && !leyendo) iniciar()
            return true
        }
        // Tecla desconocida: mostrar el código para poder mapearla después
        if (keyCode != KeyEvent.KEYCODE_BACK && keyCode != KeyEvent.KEYCODE_VOLUME_UP &&
            keyCode != KeyEvent.KEYCODE_VOLUME_DOWN) {
            estado.text = "tecla física: $keyCode (avísame este número si un botón no hace nada)"
        }
        return super.onKeyDown(keyCode, event)
    }

    override fun onKeyUp(keyCode: Int, event: KeyEvent?): Boolean {
        if (keyCode in teclasGatillo) { if (leyendo) detener(); return true }
        return super.onKeyUp(keyCode, event)
    }

    // ------------------------------------------------ red
    private fun enviar() {
        val f = filtroSku
        val lista = if (f == null) tags.keys.toList()
                    else tags.keys.filter { epcSku[it] == f }
        if (lista.isEmpty()) return toast("No hay lecturas")
        estado.text = "Enviando ${lista.size} EPC…"
        thread {
            try {
                val body = JSONObject().apply {
                    put("dispositivo", nombreEquipo)
                    put("epcs", JSONArray(lista))
                }
                val resp = post("$urlServidor/api/lecturas", body)
                ui.post {
                    estado.text = "Servidor: ${resp.optInt("nuevos")} nuevos de ${resp.optInt("recibidos")} (sesión ${resp.optInt("sesion_id")})"
                    toast("Enviado ✔")
                }
            } catch (e: Exception) {
                ui.post { estado.text = "Error de red: ${e.message}" }
            }
        }
    }

    private fun dialogoAsociar(skuInicial: String? = null) {
        val input = EditText(this).apply { hint = "SKU del producto"; setText(skuInicial ?: "") }
        val cont = LinearLayout(this).apply {
            orientation = LinearLayout.VERTICAL; setPadding(40, 20, 40, 0)
            addView(input)
            if (barcode != null) addView(Button(context).apply {
                text = "▦ Escanear código de barras"
                setOnClickListener { barcode?.startScan() }
            })
        }
        inputSkuActivo = input
        AlertDialog.Builder(this)
            .setTitle("Asociar tags a un producto")
            .setMessage("Escribe o escanea el SKU. \"Leer y asociar\" = 1 etiqueta. \"EN LOTE\" = todas las que leas hasta soltar el gatillo.")
            .setView(cont)
            .setOnDismissListener { inputSkuActivo = null }
            .setNeutralButton("EN LOTE (varias)") { _, _ ->
                val sku = input.text.toString().trim()
                if (sku.isEmpty()) { toast("Escribe o escanea el SKU primero"); return@setNeutralButton }
                loteAsociadas.clear()
                loteSku = sku
                tags.clear(); refrescar()
                iniciar()
                estado.text = "LOTE $sku · pasa el lector por las etiquetas; gatillo para terminar"
            }
            .setPositiveButton("Leer y asociar") { _, _ ->
                val sku = input.text.toString().trim()
                if (sku.isEmpty()) { toast("Escribe o escanea el SKU primero"); return@setPositiveButton }
                ui.post { estado.text = "Acerca la etiqueta RFID al lector…" }
                thread {
                    try {
                        // Reintenta la lectura hasta ~6 s para dar tiempo a acercar el tag
                        var epc: String? = null
                        val limite = System.currentTimeMillis() + 6000
                        while (epc == null && System.currentTimeMillis() < limite) {
                            epc = uhf?.inventorySingleTag()?.epc?.uppercase()
                        }
                        if (epc == null) {
                            ui.post { estado.text = "No se leyó ningún tag"; toast("No se leyó ningún tag. Acércalo más e intenta de nuevo.") }
                            return@thread
                        }
                        val r = post("$urlServidor/api/tags",
                            JSONObject().put("epc", epc).put("sku", sku))
                        ui.post {
                            if (r.optBoolean("ok")) {
                                estado.text = "✔ Tag asociado a $sku"
                                toast("✔ $epc → $sku")
                                consultados.remove(epc)
                                agregarAlCatalogo(epc, r.optString("sku", sku), r.optString("nombre", sku))
                            } else {
                                val err = r.optString("error")
                                estado.text = "✖ $err"
                                toast(if (err == "SKU no existe")
                                          "El SKU $sku no está dado de alta. Créalo primero en la web (Productos)."
                                      else "Error: $err")
                            }
                        }
                    } catch (e: Exception) { ui.post { estado.text = "Error: ${e.message}"; toast("Error: ${e.message}") } }
                }
            }
            .setNegativeButton("Cancelar", null).show()
    }

    // ------------------------------------------------ modo "solo un producto"
    private fun dialogoFiltro() {
        if (filtroSku != null) {
            filtroSku = null
            btnFiltro.text = "◎ LEER SOLO UN PRODUCTO"
            estado.text = "Modo libre: cuenta todo lo registrado"
            pintar()
            return
        }
        val input = EditText(this).apply { hint = "SKU del producto" }
        val cont = LinearLayout(this).apply {
            orientation = LinearLayout.VERTICAL; setPadding(40, 20, 40, 0)
            addView(input)
            if (barcode != null) addView(Button(context).apply {
                text = "▦ Escanear código de barras"
                setOnClickListener { barcode?.startScan() }
            })
        }
        inputSkuActivo = input
        AlertDialog.Builder(this)
            .setTitle("Leer solo un producto")
            .setMessage("El contador solo sumará etiquetas de ese producto; lo demás (incluidos los desconocidos) se ignora por completo.")
            .setView(cont)
            .setOnDismissListener { inputSkuActivo = null }
            .setPositiveButton("Activar") { _, _ ->
                val cod = input.text.toString().trim()
                if (cod.isEmpty()) { toast("Escribe o escanea el SKU primero"); return@setPositiveButton }
                estado.text = "Buscando $cod…"
                // El código escaneado puede ser la referencia O el código de
                // barras impreso (con precios): el servidor lo traduce.
                thread {
                    var sku = cod
                    var nombre = ""
                    try {
                        val r = getJsonObj("$urlServidor/api/buscar_producto?codigo=" +
                                java.net.URLEncoder.encode(cod, "UTF-8"))
                        if (r.optBoolean("ok")) {
                            sku = r.optString("sku", cod)
                            nombre = r.optString("nombre", "")
                        }
                    } catch (_: Exception) { /* sin red: se usa tal cual */ }
                    ui.post {
                        filtroSku = sku
                        tags.clear()
                        btnFiltro.text = "◎ SOLO: $sku — tocar para quitar"
                        estado.text = if (nombre.isNotEmpty()) "Contando solo: $nombre" else "Contando solo $sku"
                        pintar()
                    }
                }
            }
            .setNegativeButton("Cancelar", null).show()
    }

    // ------------------------------------------------ desconocidos
    // Trae del servidor los EPC sin producto y permite resolverlos aquí mismo
    private fun mostrarDesconocidos() {
        estado.text = "Consultando desconocidos…"
        thread {
            try {
                val arr = getJson("$urlServidor/api/desconocidos")
                ui.post {
                    if (arr.length() == 0) {
                        estado.text = "Sin desconocidos pendientes ✔"
                        toast("Nada pendiente: todo identificado")
                        return@post
                    }
                    estado.text = "${arr.length()} desconocidos pendientes"
                    val items = (0 until arr.length()).map {
                        val o = arr.getJSONObject(it)
                        "${o.getString("epc")}   ×${o.optInt("veces")}"
                    }.toTypedArray()
                    AlertDialog.Builder(this)
                        .setTitle("EPC desconocidos (${arr.length()})")
                        .setItems(items) { _, i ->
                            dialogoResolverEpc(arr.getJSONObject(i).getString("epc"))
                        }
                        .setNegativeButton("Cerrar", null).show()
                }
            } catch (e: Exception) {
                ui.post { estado.text = "Error de red: ${e.message}" }
            }
        }
    }

    // Asociar o ignorar un EPC concreto (escribiendo o escaneando el SKU)
    private fun dialogoResolverEpc(epc: String) {
        val input = EditText(this).apply { hint = "SKU del producto" }
        val cont = LinearLayout(this).apply {
            orientation = LinearLayout.VERTICAL; setPadding(40, 20, 40, 0)
            addView(input)
            if (barcode != null) addView(Button(context).apply {
                text = "▦ Escanear código de barras"
                setOnClickListener { barcode?.startScan() }
            })
        }
        inputSkuActivo = input
        AlertDialog.Builder(this)
            .setTitle("EPC sin producto")
            .setMessage(epc)
            .setView(cont)
            .setOnDismissListener { inputSkuActivo = null }
            .setPositiveButton("Asociar") { _, _ ->
                val sku = input.text.toString().trim()
                if (sku.isEmpty()) { toast("Escribe o escanea el SKU primero"); return@setPositiveButton }
                thread {
                    try {
                        val r = post("$urlServidor/api/tags",
                            JSONObject().put("epc", epc).put("sku", sku))
                        ui.post {
                            if (r.optBoolean("ok")) {
                                consultados.remove(epc)
                                agregarAlCatalogo(epc, r.optString("sku", sku), r.optString("nombre", sku))
                                refrescar()
                                estado.text = "✔ $epc → $sku"; toast("✔ Asociado")
                            } else toast("✖ ${r.optString("error")}")
                        }
                    } catch (e: Exception) { ui.post { toast("Error: ${e.message}") } }
                }
            }
            .setNeutralButton("Ignorar (ajeno)") { _, _ ->
                thread {
                    try {
                        val r = post("$urlServidor/api/ignorar", JSONObject().put("epc", epc))
                        ui.post {
                            if (r.optBoolean("ok")) { estado.text = "EPC ignorado"; toast("Ignorado: no volverá a aparecer") }
                            else toast("✖ ${r.optString("error")}")
                        }
                    } catch (e: Exception) { ui.post { toast("Error: ${e.message}") } }
                }
            }
            .setNegativeButton("Cancelar", null).show()
    }

    private fun dialogoConfig() {
        val cont = LinearLayout(this).apply { orientation = LinearLayout.VERTICAL; setPadding(40, 20, 40, 0) }
        val inUrl = EditText(this).apply { hint = "URL servidor"; setText(urlServidor) }
        val inNom = EditText(this).apply { hint = "Nombre equipo"; setText(nombreEquipo) }
        val lblPot = TextView(this)
        val barPot = SeekBar(this).apply {
            max = 25                                   // 0..25 -> 5..30 dBm
            progress = prefs.getInt("potencia", 30) - 5
            setOnSeekBarChangeListener(object : SeekBar.OnSeekBarChangeListener {
                override fun onProgressChanged(sb: SeekBar?, p: Int, deUsuario: Boolean) {
                    lblPot.text = textoPotencia(p + 5)
                }
                override fun onStartTrackingTouch(sb: SeekBar?) {}
                override fun onStopTrackingTouch(sb: SeekBar?) {}
            })
        }
        lblPot.text = textoPotencia(barPot.progress + 5)
        val btnBuscar = Button(this).apply { text = "🔍 Buscar el servidor en la red"; setOnClickListener { buscarServidores(inUrl) } }
        val chkBeep = CheckBox(this).apply { text = "🔊 Pitido al leer"; isChecked = prefs.getBoolean("beep", true) }
        cont.addView(inUrl); cont.addView(btnBuscar); cont.addView(inNom); cont.addView(lblPot); cont.addView(barPot); cont.addView(chkBeep)
        AlertDialog.Builder(this).setTitle("Configuración").setView(cont)
            .setPositiveButton("Guardar") { _, _ ->
                var u = inUrl.text.toString().trim().trimEnd('/')
                if (u.isNotEmpty() && !u.startsWith("http")) u = "http://$u"
                val pot = barPot.progress + 5
                prefs.edit().putString("url", u)
                    .putString("nombre", inNom.text.toString().trim())
                    .putInt("potencia", pot).putBoolean("beep", chkBeep.isChecked).apply()
                thread { try { uhf?.setPower(pot) } catch (_: Throwable) {} }
                estado.text = "Config guardada · alcance $pot dBm"
                refrescarCatalogo()
            }.setNegativeButton("Cancelar", null).show()
    }

    // ------------------------------------------------ autodetección del servidor
    private fun buscarServidores(inUrl: EditText) {
        val base = prefijoRed() ?: return toast("Sin red WiFi")
        val dlg = AlertDialog.Builder(this).setTitle("Buscando servidor…")
            .setMessage("Revisando ${base}1-254").setNegativeButton("Cerrar", null).show()
        val hallados = Collections.synchronizedList(ArrayList<Pair<String, String>>())
        val pool = Executors.newFixedThreadPool(16)
        val restantes = java.util.concurrent.atomic.AtomicInteger(254)
        for (n in 1..254) {
            val ip = "$base$n"
            pool.execute {
                val nombre = quienEs(ip)
                if (nombre != null) hallados.add(Pair(ip, nombre))
                if (restantes.decrementAndGet() == 0) ui.post {
                    dlg.dismiss(); pool.shutdown()
                    if (hallados.isEmpty()) { toast("No se encontró el servidor. ¿Está prendido y con el programa?"); return@post }
                    val items = hallados.map { "🖥 ${it.second}  —  ${it.first}" }.toTypedArray()
                    AlertDialog.Builder(this).setTitle("Elige el servidor")
                        .setItems(items) { _, i -> inUrl.setText("http://${hallados[i].first}:5000") }
                        .setNegativeButton("Cancelar", null).show()
                }
            }
        }
    }

    private fun prefijoRed(): String? {
        try {
            for (ni in Collections.list(NetworkInterface.getNetworkInterfaces())) {
                if (!ni.isUp || ni.isLoopback) continue
                for (a in Collections.list(ni.inetAddresses)) {
                    if (a is Inet4Address && !a.isLoopbackAddress) {
                        val ip = a.hostAddress ?: continue
                        if (ip.startsWith("192.") || ip.startsWith("10.") || ip.startsWith("172."))
                            return ip.substring(0, ip.lastIndexOf('.') + 1)
                    }
                }
            }
        } catch (_: Throwable) {}
        return null
    }

    private fun quienEs(ip: String): String? {
        try {
            val c = URL("http://$ip:5000/api/quien").openConnection() as HttpURLConnection
            c.connectTimeout = 900; c.readTimeout = 900
            if (c.responseCode == 200) {
                val txt = c.inputStream.bufferedReader().readText(); c.disconnect()
                val o = JSONObject(txt)
                if (o.optBoolean("inventario")) return o.optString("nombre", ip)
            }
            c.disconnect()
        } catch (_: Throwable) {}
        return null
    }

    private fun textoPotencia(p: Int) = "Alcance RFID: $p dBm — " + when {
        p <= 10 -> "muy corto (etiqueta pegada al lector)"
        p <= 17 -> "corto (solo lo que apuntas de cerca)"
        p <= 24 -> "medio (hasta ~1-2 m)"
        else    -> "máximo (lee toda la zona)"
    }

    // Los desconocidos se reportan solos al servidor: caen en su sección
    // "Desconocidos" sin esperar a que el usuario pulse Enviar.
    private fun enviarDesconocidos(epcs: List<String>) {
        thread {
            try {
                post("$urlServidor/api/lecturas", JSONObject().apply {
                    put("dispositivo", nombreEquipo)
                    put("epcs", JSONArray(epcs))
                })
            } catch (_: Exception) { /* sin red: los cubre el botón Enviar */ }
        }
    }

    private fun getJson(url: String): JSONArray {
        val c = URL(url).openConnection() as HttpURLConnection
        c.connectTimeout = 6000; c.readTimeout = 8000
        return JSONArray(c.inputStream.bufferedReader().readText())
    }

    private fun getJsonObj(url: String): JSONObject {
        val c = URL(url).openConnection() as HttpURLConnection
        c.connectTimeout = 6000; c.readTimeout = 8000
        val txt = (if (c.responseCode < 400) c.inputStream else c.errorStream)
            .bufferedReader().readText()
        return JSONObject(txt)
    }

    private fun post(url: String, body: JSONObject): JSONObject {
        val c = URL(url).openConnection() as HttpURLConnection
        c.requestMethod = "POST"
        c.connectTimeout = 6000; c.readTimeout = 8000
        c.doOutput = true
        c.setRequestProperty("Content-Type", "application/json")
        OutputStreamWriter(c.outputStream).use { it.write(body.toString()) }
        val txt = (if (c.responseCode < 400) c.inputStream else c.errorStream)
            .bufferedReader().readText()
        return JSONObject(txt)
    }

    private fun toast(m: String) = Toast.makeText(this, m, Toast.LENGTH_SHORT).show()

    override fun onDestroy() {
        detener()
        uhf?.free()
        try { barcode?.close() } catch (_: Throwable) {}
        try { wifiLock?.release() } catch (_: Throwable) {}
        try { tono?.release() } catch (_: Throwable) {}
        super.onDestroy()
    }
}
