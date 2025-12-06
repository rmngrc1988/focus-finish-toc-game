import pygame
import sys
from dataclasses import dataclass
from typing import List, Tuple


# --------------------------------------------------
# BASIC SETTINGS
# --------------------------------------------------
WIDTH, HEIGHT = 1200, 340
FPS = 60

BG_COLOR = (0, 0, 0)
WHITE = (230, 230, 230)
CYAN = (0, 200, 255)
YELLOW = (255, 230, 0)

CELL_WIDTH = 40          # width of each station cell
NODE_HEIGHT = 30
TOP_ROW_Y = 120          # header row
PATH_Y = 170             # bottom boxes row

# bigger Start/Finish
START_FINISH_WIDTH = CELL_WIDTH * 2

BASE_CHIP_SPEED = 40.0          # base pixels per second
P_SPEED_MULTIPLIER = 1.1        # 10% faster when moving into a P
STATION_TIME = 0.25             # seconds per station/box

# number of processing boxes per P (does NOT include S boxes)
P_BOXES = {
    "P1": 2,
    "P2": 4,
    "P3": 7,   # initial constraint
    "P4": 2,
    "P5": 4,
    "P6": 1,
}

SPAWN_INTERVAL = 0.5            # time between automatic chips at Start
S_WAIT_TIME = 0.4               # minimum time a chip must stay on any S / Start / Finish

# spawning control: series of ten
SPAWN_BLOCKED = False
P1_PASSES_SINCE_BLOCK = 0

# throughput counter
FINISHED_COUNT = 0


# --------------------------------------------------
# NODE DATA
# --------------------------------------------------

@dataclass
class Node:
    name: str           # "Start", "P1", "S1", ..., "Finish"
    kind: str           # "start", "p", "s", "finish"
    rect: pygame.Rect
    busy_until: float = 0.0   # for P nodes: processing end time
    incoming: bool = False    # True if a chip is currently on the way to this P


def create_layout(p_boxes: dict) -> Tuple[List[Node], List[Tuple[str, pygame.Rect]], List[pygame.Rect]]:
    """
    Layout:

    Start, P1 cells, S1, P2 cells, S2, P3 cells, S3, P4 cells, S4, P5 cells, S5, P6 cells, Finish.

    p_boxes defines how many processing cells each P has (>=1). Each S is always 1 cell.
    """

    cells: List[pygame.Rect] = []
    x = 40

    # Start cell
    start_idx = len(cells)
    start_rect = pygame.Rect(x, PATH_Y - NODE_HEIGHT // 2,
                             START_FINISH_WIDTH, NODE_HEIGHT)
    cells.append(start_rect)
    x += START_FINISH_WIDTH

    # Helper: build P+S cells for P1..P5
    group_info = []  # list of dicts: {p_name, p_start, p_count, s_name, s_idx}

    for k in range(1, 6):  # P1..P5
        p_name = f"P{k}"
        p_count = p_boxes[p_name]

        p_start_idx = len(cells)
        for _ in range(p_count):
            r = pygame.Rect(x, PATH_Y - NODE_HEIGHT // 2,
                            CELL_WIDTH, NODE_HEIGHT)
            cells.append(r)
            x += CELL_WIDTH

        s_name = f"S{k}"
        s_idx = len(cells)
        s_rect = pygame.Rect(x, PATH_Y - NODE_HEIGHT // 2,
                             CELL_WIDTH, NODE_HEIGHT)
        cells.append(s_rect)
        x += CELL_WIDTH

        group_info.append({
            "p_name": p_name,
            "p_start": p_start_idx,
            "p_count": p_count,
            "s_name": s_name,
            "s_idx": s_idx,
        })

    # P6 cells (no S6)
    p6_start_idx = len(cells)
    p6_count = p_boxes["P6"]
    for _ in range(p6_count):
        r = pygame.Rect(x, PATH_Y - NODE_HEIGHT // 2,
                        CELL_WIDTH, NODE_HEIGHT)
        cells.append(r)
        x += CELL_WIDTH

    # Finish cell
    finish_idx = len(cells)
    finish_rect = pygame.Rect(x, PATH_Y - NODE_HEIGHT // 2,
                              START_FINISH_WIDTH, NODE_HEIGHT)
    cells.append(finish_rect)

    # Map names to cells/kinds
    name_to_cell = {}
    name_to_kind = {}

    name_to_cell["Start"] = start_idx
    name_to_kind["Start"] = "start"

    for info in group_info:
        p_name = info["p_name"]
        s_name = info["s_name"]
        name_to_cell[p_name] = info["p_start"]
        name_to_kind[p_name] = "p"
        name_to_cell[s_name] = info["s_idx"]
        name_to_kind[s_name] = "s"

    name_to_cell["P6"] = p6_start_idx
    name_to_kind["P6"] = "p"

    name_to_cell["Finish"] = finish_idx
    name_to_kind["Finish"] = "finish"

    # Node order for chip movement
    node_order = ["Start", "P1", "S1", "P2", "S2", "P3", "S3",
                  "P4", "S4", "P5", "S5", "P6", "Finish"]

    nodes: List[Node] = []
    for nm in node_order:
        rect = cells[name_to_cell[nm]]
        kind = name_to_kind[nm]
        nodes.append(Node(nm, kind, rect))

    # Top label rectangles
    label_rects: List[Tuple[str, pygame.Rect]] = []

    # Start label
    sr = cells[start_idx]
    label_rects.append(("Start",
                        pygame.Rect(sr.x, TOP_ROW_Y, sr.width, NODE_HEIGHT)))

    # P & S labels
    for info in group_info:
        p_name = info["p_name"]
        p_rect = pygame.Rect(cells[info["p_start"]].x,
                             TOP_ROW_Y,
                             info["p_count"] * CELL_WIDTH,
                             NODE_HEIGHT)
        label_rects.append((p_name, p_rect))

        s_name = info["s_name"]
        sr = cells[info["s_idx"]]
        label_rects.append((s_name,
                            pygame.Rect(sr.x, TOP_ROW_Y,
                                        sr.width, NODE_HEIGHT)))

    # P6 label
    p6_rect = pygame.Rect(cells[p6_start_idx].x,
                          TOP_ROW_Y,
                          p6_count * CELL_WIDTH,
                          NODE_HEIGHT)
    label_rects.append(("P6", p6_rect))

    # Finish label
    fr = cells[finish_idx]
    label_rects.append(("Finish",
                        pygame.Rect(fr.x, TOP_ROW_Y,
                                    fr.width, NODE_HEIGHT)))

    return nodes, label_rects, cells


# --------------------------------------------------
# CHIP (POKER CHIP) OBJECT
# --------------------------------------------------

class Chip:
    def __init__(self, nodes: List[Node]):
        self.nodes = nodes
        self.node_index = 0
        self.x, self.y = nodes[0].rect.center
        self.state = "waiting"    # "waiting", "moving", "processing", "finished"
        self.target_index = None
        self.process_end_time = 0.0
        self.wait_until = 0.0     # for S/Start/Finish mandatory pause

    def update(self, dt: float, current_time: float):
        global SPAWN_BLOCKED, P1_PASSES_SINCE_BLOCK

        if self.state == "finished":
            return

        # PROCESSING at P node
        if self.state == "processing":
            self.x, self.y = self.nodes[self.node_index].rect.center
            if current_time >= self.process_end_time:
                p_node = self.nodes[self.node_index]
                p_node.busy_until = 0.0

                # Leaving P1? Track completions for spawn gating.
                if p_node.name == "P1" and SPAWN_BLOCKED:
                    P1_PASSES_SINCE_BLOCK += 1
                    if P1_PASSES_SINCE_BLOCK >= 1: 
                        SPAWN_BLOCKED = False
                        P1_PASSES_SINCE_BLOCK = 0

                if self.node_index + 1 < len(self.nodes):
                    self.state = "moving"
                    self.target_index = self.node_index + 1
                else:
                    self.state = "finished"
            return

        # WAITING at Start / S / Finish
        if self.state == "waiting":
            node = self.nodes[self.node_index]
            self.x, self.y = node.rect.center

            # Finish: chips stay here forever to show throughput pile
            if node.kind == "finish":
                return

            # Enforce minimum wait time on Start and S nodes
            if current_time < self.wait_until:
                return

            # Only leave if there *is* a next node
            if self.node_index + 1 < len(self.nodes):
                next_node = self.nodes[self.node_index + 1]

                if next_node.kind == "p":
                    # STRICT rule: only move toward P if it is fully free
                    if (current_time >= next_node.busy_until) and (not next_node.incoming):
                        self.state = "moving"
                        self.target_index = self.node_index + 1
                        next_node.incoming = True
                    else:
                        return
                else:
                    # P -> S or S -> (non-P) just moves when wait is over
                    self.state = "moving"
                    self.target_index = self.node_index + 1
            else:
                self.state = "finished"

        # MOVING between nodes
        if self.state == "moving" and self.target_index is not None:
            target_node = self.nodes[self.target_index]
            tx, ty = target_node.rect.center
            dx = tx - self.x
            dy = ty - self.y
            dist = (dx * dx + dy * dy) ** 0.5

            if dist == 0:
                self._arrive_at_node(current_time)
                return

            # 10% faster when heading into a P node
            speed = BASE_CHIP_SPEED * (P_SPEED_MULTIPLIER if target_node.kind == "p" else 1.0)
            step = speed * dt

            if step >= dist:
                self.x, self.y = tx, ty
                self.node_index = self.target_index
                self._arrive_at_node(current_time)
            else:
                self.x += dx / dist * step
                self.y += dy / dist * step

    def _arrive_at_node(self, current_time: float):
        global P_BOXES, FINISHED_COUNT

        node = self.nodes[self.node_index]

        if node.kind == "p":
            node.incoming = False
            boxes = P_BOXES.get(node.name, 1)
            duration = STATION_TIME * boxes
            node.busy_until = current_time + duration
            self.process_end_time = node.busy_until
            self.state = "processing"
            self.target_index = None

        elif node.kind in ("s", "start"):
            # queue spots – chips stop here and accumulate; set wait timer
            self.wait_until = current_time + S_WAIT_TIME
            self.state = "waiting"
            self.target_index = None

        elif node.kind == "finish":
            # Count throughput once when reaching Finish, then sit there forever
            FINISHED_COUNT += 1
            self.state = "waiting"
            self.wait_until = float("inf")
            self.target_index = None

        else:
            if self.node_index + 1 < len(self.nodes):
                self.state = "moving"
                self.target_index = self.node_index + 1
            else:
                self.state = "finished"
                self.target_index = None


# --------------------------------------------------
# MAIN GAME LOOP
# --------------------------------------------------

def main():
    global P_BOXES, SPAWN_BLOCKED, P1_PASSES_SINCE_BLOCK, FINISHED_COUNT

    pygame.init()
    screen = pygame.display.set_mode((WIDTH, HEIGHT))
    pygame.display.set_caption("Focus & Finish ToC Game")
    clock = pygame.time.Clock()
    font = pygame.font.SysFont("consolas", 18)

    nodes, label_rects, cells = create_layout(P_BOXES)

    chips: List[Chip] = []
    spawn_timer = 0.0
    total_time = 0.0

    SPAWN_BLOCKED = False
    P1_PASSES_SINCE_BLOCK = 0
    FINISHED_COUNT = 0

    # Simulation control
    simulation_running = False

    # Buttons: START, STOP
    start_button = pygame.Rect(WIDTH - 190, 20, 80, 30)
    stop_button = pygame.Rect(WIDTH - 100, 20, 80, 30)

    # For box-moving interactions
    selected_p_name = None  # first P clicked (source)

    running = True
    while running:
        dt = clock.tick(FPS) / 1000.0

        # --------------- EVENTS --------------- #
        for event in pygame.event.get():
            if event.type == pygame.QUIT:
                running = False

            elif event.type == pygame.MOUSEBUTTONDOWN and event.button == 1:
                mx, my = event.pos

                # Start/stop buttons
                if start_button.collidepoint(event.pos):
                    simulation_running = True
                elif stop_button.collidepoint(event.pos):
                    simulation_running = False
                else:
                    # Click on a P header to move one box between Ps
                    clicked_p = None
                    for name, rect in label_rects:
                        if name.startswith("P") and rect.collidepoint(mx, my):
                            clicked_p = name
                            break

                    if clicked_p is not None:
                        if selected_p_name is None:
                            # first selection (source)
                            selected_p_name = clicked_p
                        else:
                            # second selection (target)
                            if clicked_p != selected_p_name:
                                # move 1 box from selected_p_name to clicked_p
                                if P_BOXES[selected_p_name] > 1:
                                    P_BOXES[selected_p_name] -= 1
                                    P_BOXES[clicked_p] += 1

                                    # rebuild layout and reset simulation
                                    nodes, label_rects, cells = create_layout(P_BOXES)
                                    chips = []
                                    spawn_timer = 0.0
                                    total_time = 0.0
                                    simulation_running = False
                                    SPAWN_BLOCKED = False
                                    P1_PASSES_SINCE_BLOCK = 0
                                    FINISHED_COUNT = 0
                            # clear selection regardless
                            selected_p_name = None

        # ------------- SIMULATION ------------- #
        if simulation_running:
            total_time += dt

            # count how many chips are at Start (waiting/processing)
            start_index = next(i for i, n in enumerate(nodes) if n.name == "Start")
            start_len = 0
            for chip in chips:
                if chip.state in ("waiting", "processing") and chip.node_index == start_index:
                    start_len += 1

            # if we already have 10 or more in Start, block spawning
            if start_len >= 10:
                SPAWN_BLOCKED = True

            # spawn chips only if not blocked
            if not SPAWN_BLOCKED:
                spawn_timer += dt
                if spawn_timer >= SPAWN_INTERVAL:
                    spawn_timer -= SPAWN_INTERVAL
                    chips.append(Chip(nodes))

                    # re-count start backlog including the new chip
                    start_len = 0
                    for chip in chips:
                        if chip.state in ("waiting", "processing") and chip.node_index == start_index:
                            start_len += 1
                    if start_len >= 10:
                        SPAWN_BLOCKED = True
                        P1_PASSES_SINCE_BLOCK = 0

            # Update chips
            for chip in chips:
                chip.update(dt, total_time)

        # Do NOT remove chips at Finish; we want them to pile there
        chips = [c for c in chips if c.state != "finished"]

        # Collect queues per node
        node_queues = {}
        for chip in chips:
            if chip.state in ("waiting", "processing"):
                node_queues.setdefault(chip.node_index, []).append(chip)

        # P stats (chips currently at each P)
        p_counts = {"P1": 0, "P2": 0, "P3": 0, "P4": 0, "P5": 0, "P6": 0}
        for node_index, queue in node_queues.items():
            node = nodes[node_index]
            if node.name in p_counts:
                p_counts[node.name] = len(queue)

        # --------------- DRAW --------------- #
        screen.fill(BG_COLOR)

        # HUD
        hud_y = 20
        time_text = f"Time: {total_time:5.1f}s   Chips in system: {len(chips)}   Finished: {FINISHED_COUNT}"
        screen.blit(font.render(time_text, True, WHITE), (40, hud_y))

        hud_y += 22
        p_text = "   ".join([f"{name}:{p_counts[name]:2d}"
                             for name in ["P1", "P2", "P3", "P4", "P5", "P6"]])
        screen.blit(font.render(p_text, True, WHITE), (40, hud_y))

        hud_y += 22
        boxes_text = "Stations (boxes): " + "   ".join(
            [f"{p}:{P_BOXES[p]}" for p in ["P1", "P2", "P3", "P4", "P5", "P6"]]
        )
        screen.blit(font.render(boxes_text, True, WHITE), (40, hud_y))

        hud_y += 22
        tip = "Click a P, then another P, to move 1 box from the first to the second (min 1 box per P)."
        screen.blit(font.render(tip, True, WHITE), (40, hud_y))

        # Buttons
        def draw_button(rect, text, kind):
            if kind == "start":
                color = (0, 150, 0) if simulation_running else (80, 80, 80)
            else:  # stop
                color = (150, 0, 0) if not simulation_running else (80, 80, 80)
            pygame.draw.rect(screen, color, rect)
            pygame.draw.rect(screen, WHITE, rect, 2)
            label = font.render(text, True, WHITE)
            label_rect = label.get_rect(center=rect.center)
            screen.blit(label, label_rect)

        draw_button(start_button, "START", "start")
        draw_button(stop_button, "STOP", "stop")

        # Bottom path cells
        for cell in cells:
            pygame.draw.rect(screen, WHITE, cell, 2)

        # Top labels (highlight selected source P)
        for name, rect in label_rects:
            if name == selected_p_name:
                pygame.draw.rect(screen, (80, 80, 160), rect)  # highlight source P
            pygame.draw.rect(screen, WHITE, rect, 2)
            color = CYAN if name.startswith("P") else WHITE
            label = font.render(name, True, color)
            label_rect = label.get_rect(center=rect.center)
            screen.blit(label, label_rect)

        # Draw moving chips
        for chip in chips:
            if chip.state == "moving":
                pygame.draw.circle(screen, YELLOW, (int(chip.x), int(chip.y)), 10)

        # Draw chips at nodes:
        #   - P: only one processing chip (center)
        #   - Start / S / Finish: stacked backlog columns
        STACK_SPACING = 14
        for node_index, queue in node_queues.items():
            node = nodes[node_index]
            if node.kind == "p":
                if queue:  # one processing chip max
                    pygame.draw.circle(screen, YELLOW, node.rect.center, 10)
            elif node.kind in ("s", "start", "finish"):
                base_x, base_y = node.rect.center
                for i, _ in enumerate(queue):
                    draw_y = base_y + i * STACK_SPACING
                    pygame.draw.circle(screen, YELLOW,
                                       (int(base_x), int(draw_y)), 10)

        pygame.display.flip()

    pygame.quit()
    sys.exit()


if __name__ == "__main__":
    main()
