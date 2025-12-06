// Focus & Finish ToC Game - Browser version (with interactive P balancing)

// Canvas setup
const canvas = document.getElementById("gameCanvas");
const ctx = canvas.getContext("2d");

// UI
const infoSpan = document.getElementById("info");
const startBtn = document.getElementById("startBtn");
const stopBtn = document.getElementById("stopBtn");

// Layout constants
const CELL_WIDTH = 40;
const NODE_HEIGHT = 30;
const TOP_ROW_Y = 120;
const PATH_Y = 170;

const START_FINISH_WIDTH = CELL_WIDTH * 2;

const BASE_CHIP_SPEED = 40;      // px/s
const P_SPEED_MULT = 1.1;
const STATION_TIME = 0.25;       // sec per box
const SPAWN_INTERVAL = 0.5;
const S_WAIT_TIME = 0.4;

// P capacities (stations/boxes)
const P_BOXES = {
  P1: 2,
  P2: 4,
  P3: 7,
  P4: 2,
  P5: 4,
  P6: 1,
};

// Spawning control: series of ten
let spawnBlocked = false;
let p1PassesSinceBlock = 0;
let finishedCount = 0;

// Node data structures
let nodes = [];        // {name, kind, x, y, w, h, busyUntil, incoming}
let labels = [];       // {name, x, y, w, h}
let cells = [];        // rects used for drawing the path
let chips = [];

let simulationRunning = false;
let spawnTimer = 0;
let totalTime = 0;

let lastTimestamp = performance.now();

// For interactive P balancing
let selectedP = null;  // name of first P clicked, e.g. "P2"

// --------- Layout creation (similar to Python version) ---------

function createLayout() {
  nodes = [];
  labels = [];
  cells = [];

  let x = 40;

  function makeCell(width) {
    const r = { x, y: PATH_Y - NODE_HEIGHT / 2, w: width, h: NODE_HEIGHT };
    cells.push(r);
    x += width;
    return r;
  }

  // Start
  const startCell = makeCell(START_FINISH_WIDTH);
  const startIndex = 0;

  // P1..P5 + S1..S5
  const groupInfo = [];
  for (let k = 1; k <= 5; k++) {
    const pName = `P${k}`;
    const pCount = P_BOXES[pName];

    const pStartIndex = cells.length;
    for (let i = 0; i < pCount; i++) makeCell(CELL_WIDTH);

    const sName = `S${k}`;
    const sCellIndex = cells.length;
    makeCell(CELL_WIDTH);

    groupInfo.push({ pName, pStartIndex, pCount, sName, sCellIndex });
  }

  // P6 (no S6)
  const p6StartIndex = cells.length;
  const p6Count = P_BOXES["P6"];
  for (let i = 0; i < p6Count; i++) makeCell(CELL_WIDTH);

  // Finish
  const finishCellIndex = cells.length;
  const finishCell = makeCell(START_FINISH_WIDTH);

  // Map names -> node indices/kinds
  const nameToIndex = {};
  const nameToKind = {};

  nameToIndex["Start"] = startIndex;
  nameToKind["Start"] = "start";

  groupInfo.forEach(info => {
    const { pName, pStartIndex, sName, sCellIndex } = info;
    nameToIndex[pName] = pStartIndex;
    nameToKind[pName] = "p";

    nameToIndex[sName] = sCellIndex;
    nameToKind[sName] = "s";
  });

  nameToIndex["P6"] = p6StartIndex;
  nameToKind["P6"] = "p";

  nameToIndex["Finish"] = finishCellIndex;
  nameToKind["Finish"] = "finish";

  const nodeOrder = [
    "Start", "P1", "S1", "P2", "S2", "P3", "S3",
    "P4", "S4", "P5", "S5", "P6", "Finish",
  ];

  nodeOrder.forEach(name => {
    const ci = nameToIndex[name];
    const c = cells[ci];
    nodes.push({
      name,
      kind: nameToKind[name],
      x: c.x,
      y: c.y,
      w: c.w,
      h: c.h,
      busyUntil: 0,
      incoming: false,
    });
  });

  // Labels
  labels.push({
    name: "Start",
    x: startCell.x,
    y: TOP_ROW_Y,
    w: startCell.w,
    h: NODE_HEIGHT,
  });

  groupInfo.forEach(info => {
    const { pName, pStartIndex, pCount, sName, sCellIndex } = info;

    const pCell = cells[pStartIndex];
    labels.push({
      name: pName,
      x: pCell.x,
      y: TOP_ROW_Y,
      w: pCount * CELL_WIDTH,
      h: NODE_HEIGHT,
    });

    const sCell = cells[sCellIndex];
    labels.push({
      name: sName,
      x: sCell.x,
      y: TOP_ROW_Y,
      w: sCell.w,
      h: NODE_HEIGHT,
    });
  });

  const p6Cell = cells[p6StartIndex];
  labels.push({
    name: "P6",
    x: p6Cell.x,
    y: TOP_ROW_Y,
    w: p6Count * CELL_WIDTH,
    h: NODE_HEIGHT,
  });

  labels.push({
    name: "Finish",
    x: finishCell.x,
    y: TOP_ROW_Y,
    w: finishCell.w,
    h: NODE_HEIGHT,
  });
}

// --------- Chip class ---------

class Chip {
  constructor() {
    this.nodeIndex = 0;
    const n0 = nodes[0];
    this.x = n0.x + n0.w / 2;
    this.y = n0.y + n0.h / 2;
    this.state = "waiting"; // waiting, moving, processing, finished
    this.targetIndex = null;
    this.processEnd = 0;
    this.waitUntil = 0;
  }

  update(dt, time) {
    if (this.state === "finished") return;

    // Processing at P node
    if (this.state === "processing") {
      const node = nodes[this.nodeIndex];
      this.x = node.x + node.w / 2;
      this.y = node.y + node.h / 2;
      if (time >= this.processEnd) {
        node.busyUntil = 0;

        // leaving P1 while spawn is blocked?
        if (node.name === "P1" && spawnBlocked) {
          p1PassesSinceBlock += 1;
          if (p1PassesSinceBlock >= 1) {
            spawnBlocked = false;
            p1PassesSinceBlock = 0;
          }
        }

        if (this.nodeIndex + 1 < nodes.length) {
          this.state = "moving";
          this.targetIndex = this.nodeIndex + 1;
        } else {
          this.state = "finished";
        }
      }
      return;
    }

    // Waiting at Start / S / Finish
    if (this.state === "waiting") {
      const node = nodes[this.nodeIndex];
      this.x = node.x + node.w / 2;
      this.y = node.y + node.h / 2;

      if (node.kind === "finish") {
        return;
      }

      if (time < this.waitUntil) return;

      if (this.nodeIndex + 1 < nodes.length) {
        const next = nodes[this.nodeIndex + 1];
        if (next.kind === "p") {
          if (time >= next.busyUntil && !next.incoming) {
            this.state = "moving";
            this.targetIndex = this.nodeIndex + 1;
            next.incoming = true;
          } else {
            return;
          }
        } else {
          this.state = "moving";
          this.targetIndex = this.nodeIndex + 1;
        }
      } else {
        this.state = "finished";
      }
    }

    // Moving between nodes
    if (this.state === "moving" && this.targetIndex != null) {
      const target = nodes[this.targetIndex];
      const tx = target.x + target.w / 2;
      const ty = target.y + target.h / 2;
      const dx = tx - this.x;
      const dy = ty - this.y;
      const dist = Math.sqrt(dx * dx + dy * dy);
      if (dist === 0) {
        this.arrive(time);
        return;
      }

      const speed = BASE_CHIP_SPEED *
        (target.kind === "p" ? P_SPEED_MULT : 1.0);
      const step = speed * dt;

      if (step >= dist) {
        this.x = tx;
        this.y = ty;
        this.nodeIndex = this.targetIndex;
        this.arrive(time);
      } else {
        this.x += (dx / dist) * step;
        this.y += (dy / dist) * step;
      }
    }
  }

  arrive(time) {
    const node = nodes[this.nodeIndex];

    if (node.kind === "p") {
      node.incoming = false;
      const boxes = P_BOXES[node.name] || 1;
      const duration = STATION_TIME * boxes;
      node.busyUntil = time + duration;
      this.processEnd = node.busyUntil;
      this.state = "processing";
      this.targetIndex = null;
    } else if (node.kind === "s" || node.kind === "start") {
      this.waitUntil = time + S_WAIT_TIME;
      this.state = "waiting";
      this.targetIndex = null;
    } else if (node.kind === "finish") {
      finishedCount += 1;
      this.state = "waiting";
      this.waitUntil = Infinity;
      this.targetIndex = null;
    } else {
      if (this.nodeIndex + 1 < nodes.length) {
        this.state = "moving";
        this.targetIndex = this.nodeIndex + 1;
      } else {
        this.state = "finished";
        this.targetIndex = null;
      }
    }
  }
}

// --------- Simulation + rendering ---------

function update(dt) {
  if (!simulationRunning) return;

  totalTime += dt;

  const startIndex = nodes.findIndex(n => n.name === "Start");
  let startLen = 0;
  for (const c of chips) {
    if (c.state !== "finished" && c.nodeIndex === startIndex &&
        (c.state === "waiting" || c.state === "processing")) {
      startLen++;
    }
  }

  if (startLen >= 10) {
    spawnBlocked = true;
  }

  if (!spawnBlocked) {
    spawnTimer += dt;
    if (spawnTimer >= SPAWN_INTERVAL) {
      spawnTimer -= SPAWN_INTERVAL;
      chips.push(new Chip(nodes));

      startLen = 0;
      for (const c of chips) {
        if (c.state !== "finished" && c.nodeIndex === startIndex &&
            (c.state === "waiting" || c.state === "processing")) {
          startLen++;
        }
      }
      if (startLen >= 10) {
        spawnBlocked = true;
        p1PassesSinceBlock = 0;
      }
    }
  }

  for (const c of chips) {
    c.update(dt, totalTime);
  }
}

function draw() {
  ctx.fillStyle = "black";
  ctx.fillRect(0, 0, canvas.width, canvas.height);

  infoSpan.textContent =
    `Time: ${totalTime.toFixed(1)}s   Chips in system: ${chips.length}   Finished: ${finishedCount}`;

  ctx.strokeStyle = "white";
  ctx.lineWidth = 2;
  cells.forEach(c => {
    ctx.strokeRect(c.x, c.y, c.w, c.h);
  });

  labels.forEach(l => {
    // highlight selected P header
    if (l.name === selectedP) {
      ctx.fillStyle = "#333366";
      ctx.fillRect(l.x, l.y, l.w, l.h);
    }
    ctx.strokeStyle = "white";
    ctx.strokeRect(l.x, l.y, l.w, l.h);
    ctx.fillStyle = l.name.startsWith("P") ? "cyan" : "white";
    ctx.font = "16px Consolas";
    ctx.textAlign = "center";
    ctx.textBaseline = "middle";
    ctx.fillText(l.name, l.x + l.w / 2, l.y + l.h / 2);
  });

  const nodeQueues = {};
  chips.forEach(c => {
    if (c.state === "waiting" || c.state === "processing") {
      if (!nodeQueues[c.nodeIndex]) nodeQueues[c.nodeIndex] = [];
      nodeQueues[c.nodeIndex].push(c);
    }
  });

  const STACK_SPACING = 14;

  chips.forEach(c => {
    if (c.state === "moving") {
      ctx.fillStyle = "yellow";
      ctx.beginPath();
      ctx.arc(c.x, c.y, 10, 0, Math.PI * 2);
      ctx.fill();
    }
  });

  Object.entries(nodeQueues).forEach(([indexStr, queue]) => {
    const idx = parseInt(indexStr, 10);
    const node = nodes[idx];
    if (node.kind === "p") {
      if (queue.length > 0) {
        ctx.fillStyle = "yellow";
        ctx.beginPath();
        ctx.arc(node.x + node.w / 2, node.y + node.h / 2, 10, 0, Math.PI * 2);
        ctx.fill();
      }
    } else if (node.kind === "s" || node.kind === "start" || node.kind === "finish") {
      const baseX = node.x + node.w / 2;
      const baseY = node.y + node.h / 2;
      ctx.fillStyle = "yellow";
      queue.forEach((_, i) => {
        const yy = baseY + i * STACK_SPACING;
        ctx.beginPath();
        ctx.arc(baseX, yy, 10, 0, Math.PI * 2);
        ctx.fill();
      });
    }
  });
}

// --------- Helpers ---------

function resetSimulation() {
  createLayout();
  chips = [];
  spawnTimer = 0;
  totalTime = 0;
  spawnBlocked = false;
  p1PassesSinceBlock = 0;
  finishedCount = 0;
  simulationRunning = false;
}

// --------- Main loop ---------

function loop(timestamp) {
  const dt = (timestamp - lastTimestamp) / 1000;
  lastTimestamp = timestamp;

  update(dt);
  draw();

  requestAnimationFrame(loop);
}

startBtn.addEventListener("click", () => {
  simulationRunning = true;
});

stopBtn.addEventListener("click", () => {
  simulationRunning = false;
});

// Click handling for P headers (P1..P6)
canvas.addEventListener("click", (e) => {
  const rect = canvas.getBoundingClientRect();

  // Scale mouse position into canvas coordinate space
  const scaleX = canvas.width / rect.width;
  const scaleY = canvas.height / rect.height;

  const mx = (e.clientX - rect.left) * scaleX;
  const my = (e.clientY - rect.top) * scaleY;

  let clickedP = null;
  for (const l of labels) {
    if (!l.name.startsWith("P")) continue;
    if (mx >= l.x && mx <= l.x + l.w && my >= l.y && my <= l.y + l.h) {
      clickedP = l.name;
      break;
    }
  }

  if (!clickedP) return;

  // First selection
  if (selectedP === null) {
    selectedP = clickedP;
    return;
  }

  // Clicking same P again cancels
  if (clickedP === selectedP) {
    selectedP = null;
    return;
  }

  // Move 1 box from selectedP to clickedP, enforcing min 1 per P
  if (P_BOXES[selectedP] > 1) {
    P_BOXES[selectedP] -= 1;
    P_BOXES[clickedP] += 1;
    resetSimulation();
  }

  selectedP = null;
});

// Init
createLayout();
requestAnimationFrame(loop);
