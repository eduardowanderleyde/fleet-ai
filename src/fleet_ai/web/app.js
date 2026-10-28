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
const NAV_COLOR = { idle: "#3fb950", navigating: "#58a6ff", failed: "#f85149" };

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
  $("map-note").textContent = map.available
    ? `${map.width} × ${map.height} px · ${map.resolution} m/px`
    : "backend sem mapa: grade simples";
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
  ctx.strokeStyle = "#1c2630";
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
  const unit = Math.max(map.width, map.height) / 120; // tamanho dos símbolos
  ctx.font = `${Math.round(unit * 1.6)}px system-ui, sans-serif`;
  for (const place of map.places) {
    const { x, y } = place.pixel;
    ctx.fillStyle = "#d29922";
    ctx.fillRect(x - unit / 2, y - unit / 2, unit, unit);
    ctx.fillText(place.name, x + unit, y - unit / 2);
  }
  for (const robot of state.robots) {
    drawRobot(ctx, robot, unit);
  }
  canvas.classList.toggle("stale", state.stale);
}

function drawRobot(ctx, robot, unit) {
  const { x, y, inside } = robot.pixel;
  if (!inside) return; // fora do mapa: aparece só na lista de robôs
  const radius = unit * 1.4;
  ctx.save();
  ctx.translate(x, y);
  ctx.rotate(robot.heading); // já em ângulo de canvas (y para baixo)
  ctx.fillStyle = NAV_COLOR[robot.nav_state] || "#8b98a5";
  ctx.beginPath();
  ctx.arc(0, 0, radius, 0, 2 * Math.PI);
  ctx.fill();
  ctx.strokeStyle = "#0b0f14";
  ctx.lineWidth = unit / 3;
  ctx.beginPath();
  ctx.moveTo(0, 0);
  ctx.lineTo(radius * 1.6, 0);
  ctx.stroke();
  ctx.restore();
  ctx.fillStyle = "#e6edf3";
  ctx.fillText(robot.robot_id, x + radius * 1.3, y + radius * 1.8);
}

// ---- Frota ----------------------------------------------------------------

function renderRobots() {
  const list = $("robots");
  list.replaceChildren(
    ...state.robots.map((robot) => {
      const pose = robot.pose;
      const where = robot.pixel.inside ? "" : " · fora do mapa";
      const error = robot.last_error ? ` · ${robot.last_error}` : "";
      const text =
        `${robot.robot_id} (${robot.role}) · ${NAV_TEXT[robot.nav_state] || robot.nav_state}` +
        ` · x ${pose.x.toFixed(2)} y ${pose.y.toFixed(2)}${where}${error}`;
      return el("li", state.stale ? `${text} · desatualizado` : text);
    }),
  );
  // Só recria o seletor quando a lista de robôs muda (não fecha o menu aberto).
  const ids = state.robots.map((robot) => robot.robot_id).join(",");
  if (ids === state.robotIds) return;
  state.robotIds = ids;
  const select = $("robot");
  const chosen = select.value;
  select.replaceChildren(
    el("option", "nenhum"),
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

function healthRow(list, label, value, tone) {
  list.append(el("dt", label), el("dd", value, tone));
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
    healthRow(list, "Backend", ok ? "ok" : "indisponível", ok ? "ok" : "bad");
    healthRow(list, "Adaptador", ready.fleet_adapter);
    healthRow(list, "Planejador", ready.planner);
    healthRow(list, "LLM", ready.llm_enabled ? "ligado" : "desligado");
  } else {
    healthRow(list, "Backend", "desconhecido", "warn");
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
    const item = el("li", step.tool, step.is_error ? "is-error" : "");
    item.append(
      el("code", `entrada: ${JSON.stringify(step.input)}`),
      el("code", `resultado: ${JSON.stringify(step.result)}`),
    );
    steps.append(item);
  }
  const header = el("p");
  header.append(statusBadge(mission.status), el("span", ` · ${mission.planner}`, "muted"));
  if (mission.robot_id) header.append(el("span", ` · escopo ${mission.robot_id}`, "muted"));
  box.replaceChildren(
    header,
    el("p", mission.instruction, "instruction"),
    mission.steps.length ? steps : el("p", "Nenhum passo ainda.", "muted"),
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
      const item = el("li");
      item.append(statusBadge(mission.status), el("span", ` ${mission.instruction}`));
      item.addEventListener("click", () => {
        follow(mission.mission_id).catch(() => {});
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
poll(refreshFleet, FLEET_EVERY_MS);
poll(refreshMission, MISSION_EVERY_MS);
poll(refreshHistory, HISTORY_EVERY_MS);
poll(refreshHealth, HEALTH_EVERY_MS);
