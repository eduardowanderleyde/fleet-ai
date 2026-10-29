// Fleet AI — Control Center (SPEC-003, ticket 01).
//
// Fala só com a origem do Fleet AI. Todo texto vindo da API entra na página por
// textContent; nada é interpretado como HTML. As posições já chegam em pixels do
// mapa (geometria calculada e testada no servidor, fleet_ai/geometry.py).

const FLEET_EVERY_MS = 1000;
const MISSION_EVERY_MS = 1000;
const HISTORY_EVERY_MS = 2000;
const HEALTH_EVERY_MS = 5000;
const MAX_BACKOFF_MS = 10000;

const STATUS_TEXT = {
  running: "em andamento",
  completed: "concluída",
  not_understood: "não entendida",
  incomplete: "incompleta",
  failed: "falhou",
  rejected: "recusada",
};
const NAV_TEXT = { idle: "parado", navigating: "navegando", failed: "falhou" };
const NAV_COLOR = { idle: "#1f7a68", navigating: "#1d5bd6", failed: "#c4321c" };
const ADAPTER_TEXT = { sim: "SimFleet", fleet_ui: "Fleet UI" };
const PLANNER_TEXT = { deterministic: "por regras", llm: "LLM" };
const INK = "#1d262b";
const PAPER = "#ffffff";
const PLACE_COLOR = "#b88a00";
// Tamanhos em pixels de tela: os símbolos não mudam com a escala do mapa.
const ROBOT_RADIUS_PX = 9;
const PLACE_SIZE_PX = 6;
const LABEL_PX = 12;

const state = {
  map: null, // resposta de /v1/map
  image: null, // HTMLImageElement do PNG, quando há mapa
  robots: [],
  stale: true,
  missionId: null,
  robotIds: null, // ids da última lista, para não recriar o seletor à toa
  missionDone: false, // a missão acompanhada já terminou: não precisa mais consultar
};

const $ = (id) => document.getElementById(id);

function el(tag, text, className) {
  const node = document.createElement(tag);
  if (text !== undefined) node.textContent = String(text);
  if (className) node.className = className;
  return node;
}

class HttpError extends Error {
  constructor(status, body, retryAfter) {
    super(`HTTP ${status}`);
    this.status = status;
    this.body = body;
    this.retryAfter = retryAfter;
  }
}

async function api(path, options = {}) {
  const response = await fetch(path, { cache: "no-store", ...options });
  let body = null;
  try {
    body = await response.json();
  } catch {
    body = null;
  }
  if (!response.ok) {
    throw new HttpError(response.status, body, response.headers.get("Retry-After"));
  }
  return body;
}

function showConnection(problem) {
  const banner = $("connection");
  banner.textContent = problem || "";
  banner.classList.toggle("hidden", !problem);
}

// Repete `task` a cada `every` ms; depois de uma falha, recua 1, 2, 4… até 10 s.
function poll(task, every) {
  let delay = every;
  const run = async () => {
    try {
      await task();
      delay = every;
    } catch (error) {
      delay = Math.min(Math.max(delay * 2, 1000), MAX_BACKOFF_MS);
      console.warn("poll failed", error);
    }
    setTimeout(run, delay);
  };
  run();
}

// ---- Mapa -----------------------------------------------------------------

async function loadMap() {
  const map = await api("/v1/map");
  state.map = map;
  const meters = (pixels) => Math.round(pixels * map.resolution);
  $("map-note").textContent = map.available
    ? `${meters(map.width)} m × ${meters(map.height)} m`
    : "Sem planta do backend: grade de 1 m";
  const canvas = $("map");
  canvas.width = map.width;
  canvas.height = map.height;
  if (map.available && map.image) {
    const image = new Image();
    image.onload = () => {
      state.image = image;
      draw();
    };
    image.src = map.image;
  }
  draw();
}

function drawGrid(ctx, map) {
  const step = 1 / map.resolution; // 1 m em pixels
  ctx.strokeStyle = "#d5dad8";
  ctx.lineWidth = 1;
  for (let x = 0; x <= map.width; x += step) {
    ctx.beginPath();
    ctx.moveTo(x, 0);
    ctx.lineTo(x, map.height);
    ctx.stroke();
  }
  for (let y = map.height; y >= 0; y -= step) {
    ctx.beginPath();
    ctx.moveTo(0, y);
    ctx.lineTo(map.width, y);
    ctx.stroke();
  }
}

function draw() {
  const map = state.map;
  const canvas = $("map");
  const ctx = canvas.getContext("2d");
  ctx.clearRect(0, 0, canvas.width, canvas.height);
  if (!map) return;
  if (state.image) {
    ctx.drawImage(state.image, 0, 0, map.width, map.height);
  } else {
    drawGrid(ctx, map);
  }
  // Pixels do mapa por pixel de tela: o canvas é reduzido pelo CSS para caber.
  const scale = canvas.width / (canvas.clientWidth || canvas.width);
  ctx.font = `600 ${Math.round(LABEL_PX * scale)}px "Avenir Next", "Segoe UI", sans-serif`;
  ctx.textBaseline = "middle";
  for (const place of map.places) {
    drawPlace(ctx, place, scale);
  }
  for (const robot of state.robots) {
    drawRobot(ctx, robot, scale);
  }
  canvas.classList.toggle("stale", state.stale);
}

// Texto com contorno branco: continua legível sobre paredes e prateleiras.
function label(ctx, text, x, y, color, scale) {
  ctx.lineJoin = "round";
  ctx.lineWidth = 4 * scale;
  ctx.strokeStyle = PAPER;
  ctx.strokeText(text, x, y);
  ctx.fillStyle = color;
  ctx.fillText(text, x, y);
}

// Lugar: um losango, como marcação de piso.
function drawPlace(ctx, place, scale) {
  const { x, y, inside } = place.pixel;
  if (!inside) return;
  const size = PLACE_SIZE_PX * scale;
  ctx.beginPath();
  ctx.moveTo(x, y - size);
  ctx.lineTo(x + size, y);
  ctx.lineTo(x, y + size);
  ctx.lineTo(x - size, y);
  ctx.closePath();
  ctx.fillStyle = PLACE_COLOR;
  ctx.fill();
  ctx.lineWidth = 1.5 * scale;
  ctx.strokeStyle = INK;
  ctx.stroke();
  label(ctx, place.name, x + size * 1.8, y, INK, scale);
}

// Robô: disco na cor do estado, anel branco e uma seta para onde ele aponta.
function drawRobot(ctx, robot, scale) {
  const { x, y, inside } = robot.pixel;
  if (!inside) return; // fora do mapa: aparece só na lista de robôs
  const radius = ROBOT_RADIUS_PX * scale;
  const color = NAV_COLOR[robot.nav_state] || "#56636b";
  ctx.save();
  ctx.translate(x, y);
  ctx.rotate(robot.heading); // já em ângulo de canvas (y para baixo)
  ctx.beginPath();
  ctx.arc(0, 0, radius, 0, 2 * Math.PI);
  ctx.fillStyle = color;
  ctx.fill();
  ctx.lineWidth = 2.5 * scale;
  ctx.strokeStyle = PAPER;
  ctx.stroke();
  ctx.beginPath();
  ctx.moveTo(radius * 0.62, 0);
  ctx.lineTo(-radius * 0.32, -radius * 0.46);
  ctx.lineTo(-radius * 0.12, 0);
  ctx.lineTo(-radius * 0.32, radius * 0.46);
  ctx.closePath();
  ctx.fillStyle = PAPER;
  ctx.fill();
  ctx.restore();
  label(ctx, robot.robot_id, x + radius * 1.5, y - radius * 1.1, color, scale);
}

// ---- Frota ----------------------------------------------------------------

function renderRobots() {
  const list = $("robots");
  list.replaceChildren(
    ...state.robots.map((robot) => {
      const pose = robot.pose;
      const notes = [
        NAV_TEXT[robot.nav_state] || robot.nav_state,
        `x ${pose.x.toFixed(1)} · y ${pose.y.toFixed(1)}`,
      ];
      if (!robot.pixel.inside) notes.push("fora do mapa");
      if (robot.last_error) notes.push(robot.last_error);
      if (state.stale) notes.push("desatualizado");
      const known = Object.hasOwn(NAV_TEXT, robot.nav_state) ? robot.nav_state : "";
      const item = el("li", undefined, known);
      item.append(el("strong", robot.robot_id), el("span", notes.join(" · "), "quiet"));
      return item;
    }),
  );
  // Só recria o seletor quando a lista de robôs muda (não fecha o menu aberto).
  const ids = state.robots.map((robot) => robot.robot_id).join(",");
  if (ids === state.robotIds) return;
  state.robotIds = ids;
  const select = $("robot");
  const chosen = select.value;
  select.replaceChildren(
    el("option", "qualquer robô"),
    ...state.robots.map((robot) => el("option", robot.robot_id)),
  );
  select.options[0].value = "";
  select.value = state.robots.some((r) => r.robot_id === chosen) ? chosen : "";
}

async function refreshFleet() {
  try {
    if (!state.map) await loadMap();
    const fleet = await api("/v1/fleet");
    state.robots = fleet.robots;
    state.stale = false;
    showConnection(null);
  } catch (error) {
    state.stale = true;
    showConnection(
      error instanceof HttpError
        ? "Backend de frota indisponível: posições desatualizadas."
        : "Sem conexão com o Fleet AI.",
    );
    throw error;
  } finally {
    renderRobots();
    draw();
  }
}

// ---- Saúde ----------------------------------------------------------------

function healthRow(list, name, value, tone) {
  const row = el("div");
  row.append(el("dt", name), el("dd", value, tone));
  list.append(row);
}

async function refreshHealth() {
  const list = $("health");
  let live = false;
  try {
    live = (await api("/health/live")).status === "alive";
  } catch {
    live = false;
  }
  let ready = null;
  try {
    ready = await api("/health");
  } catch (error) {
    ready = error instanceof HttpError && error.body ? error.body : null;
  }
  list.replaceChildren();
  healthRow(list, "API", live ? "no ar" : "sem resposta", live ? "ok" : "bad");
  if (ready && typeof ready === "object" && "fleet_backend_reachable" in ready) {
    const ok = ready.status === "ok";
    healthRow(list, "Frota", ok ? "conectada" : "indisponível", ok ? "ok" : "bad");
    healthRow(list, "Backend", ADAPTER_TEXT[ready.fleet_adapter] || ready.fleet_adapter);
    healthRow(list, "Planejador", PLANNER_TEXT[ready.planner] || ready.planner);
  } else {
    healthRow(list, "Frota", "desconhecida", "warn");
  }
}

// ---- Missões --------------------------------------------------------------

function statusBadge(status) {
  return el("span", STATUS_TEXT[status] || status, `status ${status}`);
}

function renderMission(mission) {
  const box = $("mission");
  const steps = el("ol", undefined, "steps");
  for (const step of mission.steps) {
    const item = el("li", undefined, step.is_error ? "is-error" : "");
    item.append(
      el("span", step.tool, "tool"),
      el("code", `entrada: ${JSON.stringify(step.input)}`),
      el("code", `resultado: ${JSON.stringify(step.result)}`),
    );
    steps.append(item);
  }
  const header = el("p", undefined, "meta");
  header.append(
    statusBadge(mission.status),
    el("span", `planejador ${PLANNER_TEXT[mission.planner] || mission.planner}`, "quiet"),
  );
  if (mission.robot_id) header.append(el("span", `só ${mission.robot_id}`, "quiet"));
  box.replaceChildren(
    header,
    el("p", mission.instruction, "instruction"),
    mission.steps.length ? steps : el("p", "Nenhum passo ainda.", "quiet"),
    el("p", mission.final_text || (mission.status === "running" ? "Executando…" : ""), "final"),
  );
}

async function refreshMission(force = false) {
  if (!state.missionId || (state.missionDone && !force)) return;
  const mission = await api(`/v1/missions/${encodeURIComponent(state.missionId)}`);
  state.missionDone = mission.status !== "running";
  renderMission(mission);
}

function follow(missionId) {
  state.missionId = missionId;
  state.missionDone = false;
  return refreshMission(true);
}

async function refreshHistory() {
  const { missions } = await api("/v1/missions?limit=20");
  $("history").replaceChildren(
    ...missions.map((mission) => {
      const item = el("li", undefined, mission.mission_id === state.missionId ? "current" : "");
      item.tabIndex = 0;
      item.append(statusBadge(mission.status), el("span", mission.instruction));
      const open = () => {
        follow(mission.mission_id).catch(() => {});
      };
      item.addEventListener("click", open);
      item.addEventListener("keydown", (event) => {
        if (event.key === "Enter" || event.key === " ") {
          event.preventDefault();
          open();
        }
      });
      return item;
    }),
  );
}

function refusalText(error) {
  if (!(error instanceof HttpError)) return "Sem conexão com o Fleet AI. Tente de novo.";
  const message = error.body && typeof error.body.message === "string" ? error.body.message : "";
  if (error.status === 429) {
    return `Muitas missões agora; tente de novo em ${error.retryAfter || "alguns"} s. ${message}`;
  }
  if (error.status === 503) return `Sem capacidade no momento. ${message}`;
  return message || `Recusado (HTTP ${error.status}).`;
}

async function submitCommand(event) {
  event.preventDefault();
  const button = event.target.querySelector("button");
  const instruction = $("instruction").value.trim();
  const robot = $("robot").value;
  const errorBox = $("command-error");
  errorBox.textContent = "";
  if (!instruction) return;
  button.disabled = true;
  try {
    const body = robot ? { instruction, robot_id: robot } : { instruction };
    const created = await api("/v1/missions", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    });
    $("instruction").value = "";
    await follow(created.mission_id);
    await refreshHistory();
  } catch (error) {
    errorBox.textContent = refusalText(error);
  } finally {
    button.disabled = false;
  }
}

// ---- Início ---------------------------------------------------------------

$("command").addEventListener("submit", submitCommand);
window.addEventListener("resize", draw);
poll(refreshFleet, FLEET_EVERY_MS);
poll(refreshMission, MISSION_EVERY_MS);
poll(refreshHistory, HISTORY_EVERY_MS);
poll(refreshHealth, HEALTH_EVERY_MS);
