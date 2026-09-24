// Traduce la pantalla del inventario (templates/escritorio.html) a una versión
// para navegadores VIEJOS: templates/escritorio_es5.html.
//
// ¿Para qué? La pistola Alien ALR-H450 trae Android 4.4, cuyo navegador es de
// 2013: no entiende «const», las funciones flecha, «async/await», «?.», ni las
// variables de CSS. Con la pantalla normal se quedaba en blanco. El servidor le
// da esta copia traducida solo a esos navegadores; los PCs y los celulares
// modernos siguen recibiendo la normal.
//
// Cada vez que se cambia escritorio.html hay que volver a correr esto:
//     cd servidor\es5
//     npm install          (solo la primera vez)
//     node construir.mjs
// La prueba test_es5.py avisa si alguien se olvida (compara una huella).
import fs from "node:fs";
import path from "node:path";
import crypto from "node:crypto";
import { fileURLToPath } from "node:url";
import { createRequire } from "node:module";
import * as babel from "@babel/core";
import postcss from "postcss";
import customProps from "postcss-custom-properties";
import * as acorn from "acorn";

const aqui = path.dirname(fileURLToPath(import.meta.url));
const require = createRequire(import.meta.url);
const T = path.join(aqui, "..", "templates");
const S = path.join(aqui, "..", "static", "es5");

const fuente = fs.readFileSync(path.join(T, "escritorio.html"), "utf8");
const huella = crypto.createHash("sha256").update(fuente).digest("hex").slice(0, 16);

// Los únicos datos que el servidor mete DENTRO del JavaScript. En la versión
// vieja van en un objeto aparte (__J) para que el traductor no los toque.
const DATOS = [
  ["'http://{{ ip }}:5000'", "'http://' + __J.ip + ':5000'"],
  ["'{{ modo }}'", "__J.modo"],
  ["{{ 'true' if afuera else 'false' }}", "__J.afuera"],
  ["'{{ usuario_afuera }}'", "__J.usuario"],
];
const J = "<script>var __J = {ip: '{{ ip }}', modo: '{{ modo }}', " +
          "afuera: {{ 'true' if afuera else 'false' }}, usuario: '{{ usuario_afuera }}'};</script>";

function fallar(m) { console.error("✖ " + m); process.exit(1); }

let usados = 0;
function traducirJs(js, cual) {
  for (const [a, b] of DATOS) {
    const n = js.split(a).length - 1;
    usados += n;
    js = js.split(a).join(b);
  }
  if (/\{\{|\{%/.test(js)) fallar(`el script ${cual} tiene datos del servidor que no sé traducir: añádelos a DATOS`);
  const r = babel.transformSync(js, {
    babelrc: false, configFile: false, sourceType: "script", compact: false, comments: false,
    presets: [["@babel/preset-env", { targets: { chrome: "30" }, modules: false }]],
  });
  // comprobación de verdad: tiene que ser JavaScript de 2009 (ES5)
  try { acorn.parse(r.code, { ecmaVersion: 5, sourceType: "script" }); }
  catch (e) { fallar(`el script ${cual} no quedó en ES5: ${e.message}`); }
  if (/\{#|\{%\s*endraw/.test(r.code)) fallar(`el script ${cual} traducido tiene «{#» o endraw`);
  return r.code;
}

async function traducirCss(css) {
  // Los colores salen de variables (--fondo, --texto…). Los navegadores viejos
  // no las entienden: se escribe el color de verdad al lado (modo claro).
  const r = await postcss([customProps({ preserve: true })]).process(css, { from: undefined });
  if (/\{#/.test(r.css)) fallar("el CSS traducido tiene «{#»");
  return r.css;
}

// --- recorre la página y cambia cada <style> y cada <script> ---
let salida = "", pos = 0, nScripts = 0;
const trozos = /<(style|script)>([\s\S]*?)<\/\1>/g;
let m;
while ((m = trozos.exec(fuente))) {
  salida += fuente.slice(pos, m.index);
  if (m[1] === "style") {
    salida += "<style>{% raw %}" + (await traducirCss(m[2])) + "{% endraw %}</style>";
  } else {
    nScripts++;
    if (nScripts === 1) salida += '<script src="/static/es5/polyfills.js"></script>\n';
    if (m[2].includes("__J") === false && DATOS.some(([a]) => m[2].includes(a))) salida += J + "\n";
    salida += "<script>{% raw %}" + traducirJs(m[2], nScripts) + "{% endraw %}</script>";
  }
  pos = m.index + m[0].length;
}
salida += fuente.slice(pos);
if (usados < DATOS.length) fallar("no encontré todos los datos del servidor en los scripts (¿cambió escritorio.html?)");

const cab = `{# GENERADO por servidor/es5/construir.mjs a partir de escritorio.html (huella ${huella}).
   NO editar a mano: cambia escritorio.html y vuelve a correr «node construir.mjs». #}\n`;
fs.writeFileSync(path.join(T, "escritorio_es5.html"), cab + salida);

// --- lo que les falta a los navegadores viejos (fetch, Promise, forEach…) ---
const extra = `
/* «normalize» (Chrome 34+): la pantalla lo usa para quitar tildes al buscar
   (normalize('NFD') y luego borrar las marcas). Aquí se separa la letra de su
   tilde igual que el de verdad, para las letras que se usan en español. */
if (!String.prototype.normalize) (function(){
  var TILDES = {"\\u0301": "áéíóúÁÉÍÓÚýÝ", "\\u0300": "àèìòùÀÈÌÒÙ", "\\u0302": "âêîôûÂÊÎÔÛ",
                "\\u0308": "äëïöüÄËÏÖÜÿ", "\\u0303": "ãõñÃÕÑ", "\\u0327": "çÇ"};
  var BASE = {"á":"a","é":"e","í":"i","ó":"o","ú":"u","Á":"A","É":"E","Í":"I","Ó":"O","Ú":"U","ý":"y","Ý":"Y",
              "à":"a","è":"e","ì":"i","ò":"o","ù":"u","À":"A","È":"E","Ì":"I","Ò":"O","Ù":"U",
              "â":"a","ê":"e","î":"i","ô":"o","û":"u","Â":"A","Ê":"E","Î":"I","Ô":"O","Û":"U",
              "ä":"a","ë":"e","ï":"i","ö":"o","ü":"u","Ä":"A","Ë":"E","Ï":"I","Ö":"O","Ü":"U","ÿ":"y",
              "ã":"a","õ":"o","ñ":"n","Ã":"A","Õ":"O","Ñ":"N","ç":"c","Ç":"C"};
  var MARCA = {};
  for (var m in TILDES) for (var i = 0; i < TILDES[m].length; i++) MARCA[TILDES[m].charAt(i)] = m;
  String.prototype.normalize = function(forma){
    var s = String(this);
    if (forma !== "NFD" && forma !== "NFKD") return s;
    return s.replace(/[^\\u0000-\\u007f]/g, function(c){ return BASE[c] ? BASE[c] + MARCA[c] : c; });
  };
})();

/* Pequeños arreglos del DOM que Android 4.4 no trae */
(function(){
  var E = Element.prototype;
  if (!E.matches) E.matches = E.webkitMatchesSelector || E.msMatchesSelector;
  if (!E.closest) E.closest = function(s){ var el = this;
    while (el && el.nodeType === 1) { if (el.matches(s)) return el; el = el.parentNode; } return null; };
  function nodos(args){ var f = document.createDocumentFragment();
    for (var i = 0; i < args.length; i++) f.appendChild(args[i] instanceof Node ? args[i] : document.createTextNode(String(args[i])));
    return f; }
  [E, Document.prototype, DocumentFragment.prototype].forEach(function(p){
    if (!p.append) p.append = function(){ this.appendChild(nodos(arguments)); };
    if (!p.prepend) p.prepend = function(){ this.insertBefore(nodos(arguments), this.firstChild); };
  });
  [E, CharacterData.prototype].forEach(function(p){
    if (!p.remove) p.remove = function(){ if (this.parentNode) this.parentNode.removeChild(this); };
    if (!p.before) p.before = function(){ this.parentNode.insertBefore(nodos(arguments), this); };
    if (!p.after) p.after = function(){ this.parentNode.insertBefore(nodos(arguments), this.nextSibling); };
    if (!p.replaceWith) p.replaceWith = function(){ this.parentNode.replaceChild(nodos(arguments), this); };
  });
})();
`;
const partes = [
  "/* Polyfills para la pantalla del inventario en navegadores viejos (Alien, Android 4.4).",
  "   GENERADO por servidor/es5/construir.mjs. Incluye core-js, regenerator-runtime y whatwg-fetch. */",
  fs.readFileSync(require.resolve("core-js-bundle/minified.js"), "utf8"),
  fs.readFileSync(require.resolve("regenerator-runtime/runtime.js"), "utf8"),
  fs.readFileSync(require.resolve("whatwg-fetch/dist/fetch.umd.js"), "utf8"),
  extra,
];
fs.mkdirSync(S, { recursive: true });
fs.writeFileSync(path.join(S, "polyfills.js"), partes.join("\n;\n"));

console.log(`✔ escritorio_es5.html (huella ${huella}, ${nScripts} scripts) y static/es5/polyfills.js ` +
            `(${Math.round(fs.statSync(path.join(S, "polyfills.js")).size / 1024)} KB)`);
