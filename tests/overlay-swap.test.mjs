// Arnés mínimo de DOM para comprobar la secuencia de cambio de canción.
import { readFileSync } from "node:fs";

const PROJECT = new URL("..", import.meta.url).pathname.replace(/^\//, "");
const srcAssignments = [];

class ClassList {
  constructor(owner) { this.owner = owner; this.set = new Set(); }
  add(...names) { names.forEach((n) => this.set.add(n)); }
  remove(...names) { names.forEach((n) => this.set.delete(n)); }
  contains(name) { return this.set.has(name); }
  toggle(name, force) {
    const on = force === undefined ? !this.set.has(name) : Boolean(force);
    if (on) this.set.add(name); else this.set.delete(name);
    return on;
  }
  [Symbol.iterator]() { return this.set.values(); }
  toString() { return [...this.set].join(" "); }
}

class El {
  constructor(id = "") {
    this.id = id;
    this.classList = new ClassList(this);
    this.style = { setProperty(k, v) { this[k] = v; } };
    this.dataset = {};
    this.attributes = {};
    this.textContent = "";
    this.hidden = false;
    this.children = [];
    this.offsetLeft = 10; this.offsetTop = 20;
    this.offsetWidth = 780; this.offsetHeight = 200;
    this.currentSrc = "";
    this._src = undefined;
  }
  get src() { return this._src; }
  set src(value) {
    this._src = value;
    this.currentSrc = value;
    if (this.id === "artwork") srcAssignments.push(value);
  }
  get className() { return this.classList.toString(); }
  set className(value) { this.classList.set = new Set(String(value).split(/\s+/).filter(Boolean)); }
  setAttribute(k, v) { if (k === "src") { this.src = v; return; } this.attributes[k] = v; }
  getAttribute(k) { return k === "src" ? this._src ?? null : this.attributes[k] ?? null; }
  removeAttribute(k) {
    if (k === "src") { this._src = undefined; this.currentSrc = ""; srcAssignments.push("<REMOVED>"); return; }
    delete this.attributes[k];
  }
  cloneNode() { const c = new El(); c.className = this.className; return c; }
  querySelectorAll() { return []; }
  append(child) { this.children.push(child); }
  remove() {}
}

const nodes = {};
for (const id of ["overlay-card", "artwork", "track-title", "artist", "album",
                  "current-lyric", "next-lyric", "current-translation",
                  "next-translation", "stage"]) {
  nodes[id] = new El(id);
}

const pendingImages = [];
class FakeImage {
  constructor() { this.decoding = "sync"; this.onload = null; this.onerror = null; this._src = ""; }
  get src() { return this._src; }
  set src(value) { this._src = value; pendingImages.push(this); }
  decode() { return Promise.resolve(); }
}

let socketListener = null;
class FakeWebSocket {
  constructor() { this.readyState = 1; }
  addEventListener(type, handler) { if (type === "message") socketListener = handler; }
  send() {}
}
FakeWebSocket.OPEN = 1;

const config = JSON.parse(readFileSync(`${PROJECT}/config.json`, "utf8"));
const trackState = (key, title, artwork) => ({
  type: "state", revision: 1, visible: true, status: "ready",
  track: { key, title, artist: "Artista", album: "Album", duration_ms: 200000, artwork_url: artwork },
  playback: { position_ms: 1000, duration_ms: 200000, is_playing: true, is_active: true, observed_at_ms: Date.now() },
  lyrics: [{ time_ms: 0, text: `letra de ${title}` }, { time_ms: 5000, text: "segunda" }],
  lyrics_provider: "Test", lyrics_timing: "synced", translation_provider: null,
});

globalThis.window = {
  innerWidth: 1280, innerHeight: 720,
  addEventListener() {},
  setTimeout: (fn, ms) => setTimeout(fn, ms),
  clearTimeout: (id) => clearTimeout(id),
  setInterval: () => 0,
  getComputedStyle: () => ({ transform: "matrix(1, 0, 0, 1, 0, 0)" }),
  location: { search: "", protocol: "https:", host: "x", origin: "https://x" },
  WebSocket: FakeWebSocket,
};
globalThis.location = window.location;
globalThis.WebSocket = FakeWebSocket;
globalThis.Image = FakeImage;
globalThis.document = {
  documentElement: { style: { setProperty() {} } },
  body: new El("body"),
  querySelector: (sel) => nodes[sel.replace("#", "")] ?? null,
  addEventListener() {},
};
globalThis.fetch = async (url) => ({
  ok: true,
  json: async () => (url.startsWith("/api/config") ? config : trackState("A", "Cancion A", "/artwork/a.jpg")),
});

const tick = () => new Promise((r) => setTimeout(r, 0));
const resolveImage = async (expectedUrl) => {
  const image = pendingImages.find((i) => i.src === expectedUrl && i.onload);
  if (!image) throw new Error(`no hay precarga pendiente para ${expectedUrl}`);
  image.onload();
  await tick(); await tick();
};

eval(readFileSync(`${PROJECT}/static/overlay.js`, "utf8"));

const card = nodes["overlay-card"];
const art = nodes["artwork"];
const title = nodes["track-title"];
const fails = [];
const check = (label, ok, extra = "") => {
  console.log(`${ok ? "  OK  " : " FALLA"}  ${label}${extra ? "  -> " + extra : ""}`);
  if (!ok) fails.push(label);
};

await tick(); await tick();

console.log("\n[1] Carga inicial: la tarjeta espera a la portada");
check("no se pinta antes de tener la portada", title.textContent === "", `titulo="${title.textContent}"`);
await resolveImage("/artwork/a.jpg");
check("tras decodificar se pinta la cancion A", title.textContent === "Cancion A");
check("la portada A queda puesta", art.src === "/artwork/a.jpg", `src=${art.src} precargas=${pendingImages.map((i) => i.src).join(",")}`);
check("se aplica la animacion de entrada", card.classList.contains(`song-enter-${config.animations.song}`), `clases="${card.className}" song=${config.animations.song}`);
check("el overlay queda visible", document.body.classList.contains("overlay-visible"));

console.log("\n[2] Cambio de cancion: se congela hasta tener la portada nueva");
card.classList.remove(`song-enter-${config.animations.song}`);
socketListener({ data: JSON.stringify(trackState("B", "Cancion B", "/artwork/b.jpg")) });
await tick();
check("sigue mostrando la cancion anterior", title.textContent === "Cancion A", `titulo=${title.textContent}`);
check("sigue mostrando la portada anterior", art.src === "/artwork/a.jpg", `src=${art.src}`);
check("no re-anima todavia", !card.classList.contains(`song-enter-${config.animations.song}`));

console.log("\n[3] Portada lista: cambia con la transicion");
await resolveImage("/artwork/b.jpg");
check("ahora muestra la cancion B", title.textContent === "Cancion B", `titulo=${title.textContent}`);
check("la portada B esta puesta", art.src === "/artwork/b.jpg");
check("se aplica la animacion de entrada", card.classList.contains(`song-enter-${config.animations.song}`), `clases="${card.className}" song=${config.animations.song}`);
check("se clono la tarjeta saliente", nodes["stage"].children.length === 1);

console.log("\n[4] El hueco de la portada nunca queda vacio");
check("src nunca fue eliminado ni vacio",
      !srcAssignments.includes("<REMOVED>") && !srcAssignments.includes(""),
      `asignaciones=${JSON.stringify(srcAssignments)}`);


console.log("\n[5] Cancion SIN portada: no debe congelar el overlay");
socketListener({ data: JSON.stringify(trackState("C", "Cancion C", null)) });
await tick();
check("congelado mientras espera", title.textContent === "Cancion B");
await new Promise((r) => setTimeout(r, 1700));
check("tras el limite de espera se pinta igualmente", title.textContent === "Cancion C", `titulo=${title.textContent}`);
check("la portada queda como pixel transparente", String(art.src).startsWith("data:image/gif"), `src=${String(art.src).slice(0, 22)}`);
check("sigue sin icono de imagen rota", !srcAssignments.includes("<REMOVED>") && !srcAssignments.includes(""));
check("la animacion de entrada tambien se aplica", card.classList.contains(`song-enter-${config.animations.song}`));

console.log("\n[6] La portada llega tarde para la misma cancion");
socketListener({ data: JSON.stringify(trackState("C", "Cancion C", "/artwork/c.jpg")) });
await tick();
await resolveImage("/artwork/c.jpg");
check("la portada tardia se coloca", art.src === "/artwork/c.jpg", `src=${art.src}`);
check("sin re-animar ni cambiar el titulo", title.textContent === "Cancion C");


console.log("\n[7] Interruptor de traduccion");
const conTraduccion = trackState("D", "Cancion D", "/artwork/d.jpg");
conTraduccion.lyrics = [
  { time_ms: 0, text: "Sola, ilusionada me quede", translation: "TRADUCCION UNO" },
  { time_ms: 5000, text: "Creyendo que tu me amabas", translation: "TRADUCCION DOS" },
];
socketListener({ data: JSON.stringify(conTraduccion) });
await tick();
await resolveImage("/artwork/d.jpg");
const curT = nodes["current-translation"];
check("con traduccion activada se muestra", curT.textContent === "TRADUCCION UNO" && curT.hidden === false,
      `texto="${curT.textContent}" hidden=${curT.hidden}`);

const apagada = JSON.parse(JSON.stringify(config));
apagada.translation.enabled = false;
socketListener({ data: JSON.stringify({ type: "config", config: apagada }) });
await tick();
check("al desactivar se oculta", curT.hidden === true, `hidden=${curT.hidden}`);
check("al desactivar se vacia el texto", curT.textContent === "", `texto="${curT.textContent}"`);
check("la letra original sigue intacta", nodes["current-lyric"].textContent === "Sola, ilusionada me quede",
      `letra="${nodes["current-lyric"].textContent}"`);

console.log(`\n${fails.length ? "FALLOS: " + fails.join(" | ") : "TODAS LAS COMPROBACIONES PASAN"}`);
process.exit(fails.length ? 1 : 0);
