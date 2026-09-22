/**
 * Le HUD : une vue sur le bus d'événements du daemon, rien de plus.
 *
 * Il n'a aucune logique métier et ne parle à aucun modèle — il se reconnecte
 * tout seul et se contente de refléter ce que le noyau émet. On peut le
 * fermer à tout moment sans perturber Jarvis.
 */
import { Reactor } from "./reactor";

const WS = `ws://127.0.0.1:8787`;

const $ = <T extends HTMLElement>(id: string) => document.getElementById(id) as T;
const stateEl = $("state");
const latencyEl = $("latency");
const transcript = $<HTMLDivElement>("transcript");
const events = $<HTMLDivElement>("events");
const stats = $<HTMLDListElement>("stats");
const input = $<HTMLInputElement>("input");

const reactor = new Reactor($<HTMLCanvasElement>("reactor"));
let socket: WebSocket | null = null;

/* ------------------------------------------------------------------ rendu */

function setState(name: string, code: number) {
  stateEl.textContent = name;
  stateEl.dataset.on = code === 1 ? "listening" : code === 2 ? "thinking" : code === 3 ? "speaking" : "";
  reactor.setState(code);
}

function addTurn(who: string, text: string, cls: string) {
  const last = transcript.lastElementChild;
  if (last?.classList.contains(cls) && cls === "jarvis") {
    last.querySelector(".body")!.textContent += " " + text;
  } else {
    const el = document.createElement("div");
    el.className = `turn ${cls}`;
    el.innerHTML = `<div class="who"></div><div class="body"></div>`;
    el.querySelector(".who")!.textContent = who;
    el.querySelector(".body")!.textContent = text;
    transcript.appendChild(el);
  }
  transcript.scrollTop = transcript.scrollHeight;
  while (transcript.childElementCount > 120) transcript.firstElementChild!.remove();
}

function log(text: string, cls = "") {
  const el = document.createElement("div");
  el.className = `ev ${cls}`;
  const t = new Date().toLocaleTimeString("fr-FR", { hour12: false });
  el.innerHTML = `<span class="t"></span><span class="m"></span>`;
  el.querySelector(".t")!.textContent = t;
  el.querySelector(".m")!.textContent = text;
  events.appendChild(el);
  events.scrollTop = events.scrollHeight;
  while (events.childElementCount > 200) events.firstElementChild!.remove();
}

const LABELS: Record<string, string> = {
  episodes: "épisodes",
  facts: "faits",
  entities: "entités",
  relations: "relations",
  pending: "à consolider",
  embed_backend: "embeddings",
};

function renderStats(data: Record<string, unknown>) {
  stats.innerHTML = "";
  for (const [key, label] of Object.entries(LABELS)) {
    if (!(key in data)) continue;
    const dt = document.createElement("dt");
    const dd = document.createElement("dd");
    dt.textContent = label;
    dd.textContent = String(data[key]);
    stats.append(dt, dd);
  }
}

/* --------------------------------------------------------------- réception */

function onEvent(ev: any) {
  switch (ev.topic) {
    case "hud.snapshot":
      renderStats(ev.memory ?? {});
      $("offline").textContent = ev.offline ? "local" : "réseau";
      setState(ev.busy ? "réflexion" : ev.listening ? "écoute" : "repos", ev.busy ? 2 : ev.listening ? 1 : 0);
      break;

    case "stt.text":
      if (ev.text) { addTurn("vous", ev.text, "user"); reactor.pulse(0.5); }
      break;

    case "turn.start":
      setState("réflexion", 2);
      break;

    case "turn.first_token":
      latencyEl.textContent = String(ev.ms);
      break;

    case "jarvis.says":
      addTurn("jarvis", ev.text, "jarvis");
      setState("parole", 3);
      reactor.pulse(0.35);
      break;

    case "turn.end":
      setState("écoute", 1);
      log(`tour terminé · ${ev.ms} ms · premier mot à ${ev.first_ms} ms`);
      break;

    case "brain.route":
      log(`route → ${ev.target} (${ev.reason})`);
      break;

    case "brain.loading":
      log(`chargement ${ev.role} : ${ev.model}`);
      break;

    case "brain.loaded":
      log(`modèle ${ev.role} prêt`);
      break;

    case "tool.call":
      log(`outil ${ev.name} ${JSON.stringify(ev.input)}`, "tool");
      reactor.pulse(0.6);
      break;

    case "tool.result":
      log(`↳ ${String(ev.output).slice(0, 90)}`, ev.error ? "err" : "tool");
      break;

    case "memory.consolidating":
      log(`consolidation de ${ev.episodes} épisodes…`);
      break;

    case "memory.consolidated":
      log(`consolidation : ${ev.facts} faits retenus`);
      if (ev.stats) renderStats(ev.stats);
      break;

    case "speech.ignored":
      log(`ignoré (pas d'appel par le nom) : ${ev.text}`, "");
      break;

    case "gate.opened":
      setState("écoute", 1);
      break;

    case "gate.closed":
      setState("repos", 0);
      break;

    case "tts.interrupted":
      log("interrompu");
      break;

    default:
      if (ev.topic?.endsWith("failed") || ev.error) log(`${ev.topic} : ${ev.error ?? ""}`, "err");
  }
}

/* ------------------------------------------------------------- connexion */

function connect() {
  socket = new WebSocket(WS);

  socket.onopen = () => {
    log("connecté au noyau");
    setState("repos", 0);
    send({ cmd: "snapshot" });
  };

  socket.onmessage = (m) => {
    try { onEvent(JSON.parse(m.data)); } catch { /* trame illisible : on ignore */ }
  };

  socket.onclose = () => {
    setState("hors ligne", 0);
    log("noyau injoignable — nouvelle tentative dans 2 s", "err");
    setTimeout(connect, 2000);   // le HUD survit au redémarrage du daemon
  };

  socket.onerror = () => socket?.close();
}

function send(msg: object) {
  if (socket?.readyState === WebSocket.OPEN) socket.send(JSON.stringify(msg));
}

/* ------------------------------------------------------------- commandes */

input.addEventListener("keydown", (e) => {
  if (e.key !== "Enter" || !input.value.trim()) return;
  addTurn("vous", input.value.trim(), "user");
  send({ cmd: "say", text: input.value.trim() });
  input.value = "";
});

$("listen").addEventListener("click", () => send({ cmd: "listen" }));
$("consolidate").addEventListener("click", () => send({ cmd: "consolidate" }));

document.addEventListener("keydown", (e) => {
  if (e.key === "Escape") send({ cmd: "interrupt" });
});

connect();
