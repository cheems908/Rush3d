import math
import collections
import time as pytime
import traceback

from enum import Enum

from ursina import Ursina, Entity, Text, Button, color, mouse, camera, Vec3, Vec2, destroy, held_keys, time as u_time
from ursina.shaders import lit_with_shadows_shader, unlit_shader
from ursina.lights import DirectionalLight, AmbientLight


class Direction(Enum):
    HORIZONTAL = "horizontal"
    VERTICAL = "vertical"


class Vehicle:
    def __init__(self, id, name, color_hex, start_pos, length, direction, is_target=False):
        self.id = id
        self.name = name
        self.color_hex = color_hex
        self.position = start_pos
        self.length = length
        self.direction = direction
        self.is_target = is_target

    def get_cells(self, pos=None):
        if pos is None:
            pos = self.position
        if self.direction == Direction.HORIZONTAL:
            return [pos + i for i in range(self.length)]
        return [pos + i * 6 for i in range(self.length)]

    def can_move_to(self, new_pos, occupied_cells_without_me):
        cells = self.get_cells(new_pos)
        for cell in cells:
            if cell < 0 or cell > 35:
                return False
            if cell in occupied_cells_without_me:
                return False
        if self.direction == Direction.HORIZONTAL:
            if new_pos // 6 != (new_pos + self.length - 1) // 6:
                return False
            if new_pos // 6 != self.position // 6:
                return False
        else:
            if new_pos % 6 != (new_pos + (self.length - 1) * 6) % 6:
                return False
            if new_pos % 6 != self.position % 6:
                return False
        return True

    def clone(self):
        return Vehicle(self.id, self.name, self.color_hex, self.position, self.length, self.direction, self.is_target)


class Board:
    def __init__(self, vehicles=None):
        self.vehicles = vehicles if vehicles else []
        self.update_occupied()

    def update_occupied(self):
        self.occupied = {}
        for v in self.vehicles:
            for cell in v.get_cells():
                self.occupied[cell] = v.id

    def add_vehicle(self, vehicle):
        cells = vehicle.get_cells()
        for cell in cells:
            if cell < 0 or cell > 35:
                raise ValueError(f"Vehicle out of bounds: {vehicle.name} at cell {cell}")
        occ = set(self.occupied.keys())
        if any(c in occ for c in cells):
            raise ValueError(f"Vehicle overlaps existing: {vehicle.name}")
        self.vehicles.append(vehicle)
        self.update_occupied()

    def get_state(self):
        return tuple(sorted((v.id, v.position) for v in self.vehicles))

    def check_win(self):
        for v in self.vehicles:
            if v.is_target:
                cells = v.get_cells()
                if v.direction == Direction.HORIZONTAL and cells[-1] % 6 == 5 and cells[-1] // 6 == 2:
                    return True
        return False

    def get_possible_moves(self):
        moves = []
        for i, v in enumerate(self.vehicles):
            occupied_without_me = {c for c, vid in self.occupied.items() if vid != v.id}
            step = 1 if v.direction == Direction.HORIZONTAL else 6
            for s in [step, -step]:
                curr_pos = v.position + s
                while v.can_move_to(curr_pos, occupied_without_me):
                    moves.append((i, curr_pos))
                    curr_pos += s
        return moves

    def apply_move(self, vehicle_idx, new_pos):
        new_vehicles = [v.clone() for v in self.vehicles]
        new_vehicles[vehicle_idx].position = new_pos
        return Board(new_vehicles)


def solve_bfs(initial_board):
    start_state = initial_board.get_state()
    queue = collections.deque([(initial_board, [])])
    visited = {start_state}
    while queue:
        board, path = queue.popleft()
        if board.check_win():
            return path
        for v_idx, new_pos in board.get_possible_moves():
            new_board = board.apply_move(v_idx, new_pos)
            new_state = new_board.get_state()
            if new_state not in visited:
                visited.add(new_state)
                queue.append((new_board, path + [(v_idx, new_pos)]))
    return None


def hex_to_ursina_color(hex_color: str):
    h = hex_color.lstrip('#')
    r = int(h[0:2], 16) / 255.0
    g = int(h[2:4], 16) / 255.0
    b = int(h[4:6], 16) / 255.0
    return color.rgba(r, g, b, 1)


class RushHourUrsina:
    def __init__(self):
        self.app = Ursina(borderless=False)

        window_title = Text("3D STABLE RENDERER (Ursina)", origin=(0, 0), scale=1.6, y=0.46, color=color.yellow)
        self._ = window_title

        AmbientLight(color=color.rgba(0.35, 0.35, 0.4, 1))
        DirectionalLight(direction=Vec3(1, -2, 1), color=color.rgba(0.9, 0.9, 0.9, 1))

        self.pivot = Entity()
        self.grid_parent = Entity(parent=self.pivot)
        self.vehicles_parent = Entity(parent=self.pivot)

        self.rotation_y = 45.0
        self.camera_dist = 15.0

        camera.position = (0, 9.0, -self.camera_dist)
        camera.look_at(Vec3(0, 0, 0))

        self.level_data = self.init_levels()
        self.current_level_idx = 0
        self.board = None
        self.selected_vehicle_idx = None
        self.move_history = []
        self.moves_count = 0

        self.status = Text("3D Consistency Engine Active", origin=(-0.5, 0), scale=1.0, x=-0.83, y=-0.39, color=color.orange)
        self.metrics = Text("Render: 0.0ms | Error: 0.000000", origin=(-0.5, 0), scale=0.9, x=-0.83, y=0.39, color=color.lime)
        self.level_text = Text("Level 1 | Moves: 0", origin=(-0.5, 0), scale=1.0, x=-0.83, y=0.33, color=color.white)
        self.help = Text("LMB drag car: move | LMB drag empty: rotate | RMB drag: rotate | wheel: zoom", origin=(0, 0), scale=0.85, y=-0.46, color=color.azure)

        self.floor_tiles = []
        self.tile_by_cell = {}
        self.vehicle_entities = []
        self.vehicle_ent_by_idx = {}

        self.highlight_overlays = []
        self.preview_overlays = []

        self.is_rotating = False
        self.last_mouse = Vec2(0, 0)
        self.drag_mode = None
        self.drag_vehicle_idx = None
        self.drag_start_pos = None
        self.drag_preview_pos = None
        self.drag_mouse_start = Vec2(0, 0)

        self._build_ui_buttons()
        self.load_level(0)

        self.last_render_ms = 0.0
        self._render_timer = 0.0

        self.validation_active = False
        self.validation_angle = 0
        self.validation_errors = []
        self.validation_original_angle = 45.0

        

    def _is_ui_entity(self, e):
        if e is None:
            return False
        p = e
        while p is not None:
            if p == camera.ui:
                return True
            p = getattr(p, 'parent', None)
        return False

    def _resolve_pick(self, e):
        p = e
        while p is not None:
            if hasattr(p, 'vehicle_idx') or hasattr(p, 'cell'):
                return p
            p = getattr(p, 'parent', None)
        return None

    def _input(self, key):
        if key == 'scroll up':
            self.camera_dist = max(8.0, self.camera_dist - 1.2)
            camera.position = (0, 9.0, -self.camera_dist)
            camera.look_at(Vec3(0, 0, 0))
            return
        if key == 'scroll down':
            self.camera_dist = min(26.0, self.camera_dist + 1.2)
            camera.position = (0, 9.0, -self.camera_dist)
            camera.look_at(Vec3(0, 0, 0))
            return

        if key == 'left mouse down':
            hovered = self._resolve_pick(mouse.hovered_entity)
            if hovered is not None and self._is_ui_entity(hovered):
                self.drag_mode = None
                self.drag_vehicle_idx = None
                return

            if hovered is not None and hasattr(hovered, 'vehicle_idx'):
                self.selected_vehicle_idx = hovered.vehicle_idx
                self.status.text = f"Selected {self.board.vehicles[self.selected_vehicle_idx].name}"
                self.status.color = color.lime
                self._sync_vehicle_entities()
                self._update_move_range_highlight()

                self.drag_mode = 'move'
                self.drag_vehicle_idx = self.selected_vehicle_idx
                self.drag_start_pos = self.board.vehicles[self.drag_vehicle_idx].position
                self.drag_preview_pos = self.drag_start_pos
                self.drag_mouse_start = Vec2(mouse.x, mouse.y)
                self.last_mouse = Vec2(mouse.x, mouse.y)
                return

            if hovered is not None and hasattr(hovered, 'cell') and self.selected_vehicle_idx is not None:
                self.drag_mode = 'move'
                self.drag_vehicle_idx = self.selected_vehicle_idx
                self.drag_start_pos = self.board.vehicles[self.drag_vehicle_idx].position
                self.drag_preview_pos = self.drag_start_pos
                self.drag_mouse_start = Vec2(mouse.x, mouse.y)
                self.last_mouse = Vec2(mouse.x, mouse.y)
                return

            self.drag_mode = 'rotate'
            self.drag_mouse_start = Vec2(mouse.x, mouse.y)
            self.last_mouse = Vec2(mouse.x, mouse.y)
            return

        if key == 'left mouse up':
            if self.drag_mode == 'move' and self.drag_vehicle_idx is not None:
                v_idx = self.drag_vehicle_idx
                start_pos = self.drag_start_pos
                preview_pos = self.drag_preview_pos
                self.drag_mode = None
                self.drag_vehicle_idx = None
                self.drag_start_pos = None
                self.drag_preview_pos = None

                if preview_pos is not None and start_pos is not None:
                    if preview_pos != start_pos:
                        self._execute_move(v_idx, preview_pos)
                    else:
                        self._sync_vehicle_entities()
                self._clear_preview_overlays()
                self._update_move_range_highlight()
                return

            if self.drag_mode == 'rotate':
                self.drag_mode = None
                return

            return

        if key == 'escape':
            self.selected_vehicle_idx = None
            self._sync_vehicle_entities()
            return

    def init_levels(self):
        levels = []

        b1 = Board()
        b1.add_vehicle(Vehicle(0, "Red Car", "#e74c3c", 13, 2, Direction.HORIZONTAL, True))
        b1.add_vehicle(Vehicle(1, "Yellow Car", "#f1c40f", 0, 2, Direction.VERTICAL))
        b1.add_vehicle(Vehicle(2, "Green Car", "#2ecc71", 4, 2, Direction.HORIZONTAL))
        b1.add_vehicle(Vehicle(3, "Blue Truck (L3)", "#3498db", 7, 3, Direction.HORIZONTAL))
        b1.add_vehicle(Vehicle(4, "Purple Car", "#9b59b6", 15, 2, Direction.VERTICAL))
        b1.add_vehicle(Vehicle(5, "Orange Truck", "#e67e22", 18, 3, Direction.VERTICAL))
        levels.append(b1)

        b2 = Board()
        b2.add_vehicle(Vehicle(0, "Red Car", "#e74c3c", 12, 2, Direction.HORIZONTAL, True))
        b2.add_vehicle(Vehicle(1, "Blue Car (L2)", "#3498db", 0, 2, Direction.HORIZONTAL))
        b2.add_vehicle(Vehicle(2, "Yellow Car", "#f1c40f", 2, 2, Direction.VERTICAL))
        b2.add_vehicle(Vehicle(3, "Purple Truck", "#8e44ad", 5, 3, Direction.VERTICAL))
        b2.add_vehicle(Vehicle(4, "Green Car", "#2ecc71", 9, 2, Direction.HORIZONTAL))
        b2.add_vehicle(Vehicle(5, "Orange Car", "#e67e22", 14, 2, Direction.VERTICAL))
        b2.add_vehicle(Vehicle(6, "Gray Truck", "#7f8c8d", 30, 3, Direction.HORIZONTAL))
        levels.append(b2)

        b3 = Board()
        b3.add_vehicle(Vehicle(0, "Red Car", "#e74c3c", 13, 2, Direction.HORIZONTAL, True))
        b3.add_vehicle(Vehicle(1, "Purple Truck", "#8e44ad", 0, 3, Direction.HORIZONTAL))
        b3.add_vehicle(Vehicle(2, "Yellow Car", "#f1c40f", 3, 2, Direction.VERTICAL))
        b3.add_vehicle(Vehicle(3, "Orange Truck", "#e67e22", 5, 3, Direction.VERTICAL))
        b3.add_vehicle(Vehicle(4, "Green Car", "#2ecc71", 6, 2, Direction.HORIZONTAL))
        b3.add_vehicle(Vehicle(5, "Blue Car (L2)", "#3498db", 10, 2, Direction.VERTICAL))
        b3.add_vehicle(Vehicle(6, "Gray Car", "#7f8c8d", 12, 2, Direction.VERTICAL))
        b3.add_vehicle(Vehicle(7, "Lime Car", "#2ecc71", 19, 2, Direction.HORIZONTAL))
        b3.add_vehicle(Vehicle(8, "Navy Truck", "#2c3e50", 22, 3, Direction.VERTICAL))
        b3.add_vehicle(Vehicle(9, "Teal Car", "#16a085", 31, 2, Direction.HORIZONTAL))
        levels.append(b3)

        b4 = Board()
        b4.add_vehicle(Vehicle(0, "Red Car", "#e74c3c", 14, 2, Direction.HORIZONTAL, True))
        b4.add_vehicle(Vehicle(1, "Yellow Car", "#f1c40f", 0, 2, Direction.VERTICAL))
        b4.add_vehicle(Vehicle(2, "Blue Truck (L3)", "#3498db", 1, 3, Direction.HORIZONTAL))
        b4.add_vehicle(Vehicle(3, "Green Car", "#2ecc71", 4, 2, Direction.VERTICAL))
        b4.add_vehicle(Vehicle(4, "Purple Car", "#9b59b6", 5, 2, Direction.VERTICAL))
        b4.add_vehicle(Vehicle(5, "Gray Car", "#7f8c8d", 12, 2, Direction.VERTICAL))
        b4.add_vehicle(Vehicle(6, "Orange Car", "#e67e22", 19, 2, Direction.HORIZONTAL))
        b4.add_vehicle(Vehicle(7, "Cyan Truck", "#16a085", 21, 3, Direction.VERTICAL))
        b4.add_vehicle(Vehicle(8, "Navy Car", "#2c3e50", 22, 2, Direction.VERTICAL))
        b4.add_vehicle(Vehicle(9, "Pink Car", "#e84393", 24, 2, Direction.HORIZONTAL))
        b4.add_vehicle(Vehicle(10, "Brown Truck", "#d35400", 30, 3, Direction.HORIZONTAL))
        b4.add_vehicle(Vehicle(11, "Dark Green Car", "#006266", 29, 2, Direction.VERTICAL))
        levels.append(b4)

        return levels

    def _build_ui_buttons(self):
        self.buttons = []

        def mk_btn(text, x, y, on_click, tint):
            b = Button(text=text, color=tint, scale=(0.12, 0.045), position=(x, y), text_color=color.white)
            b.on_click = on_click
            self.buttons.append(b)
            return b

        mk_btn("UNDO", -0.28, -0.37, self.undo_move, color.azure)
        mk_btn("RESET", -0.14, -0.37, self.reset_level, color.orange)
        mk_btn("HINT", 0.00, -0.37, self.show_hint, color.violet)
        mk_btn("VALIDATE", 0.14, -0.37, self.start_validation, color.red)
        mk_btn("RESET VIEW", 0.30, -0.37, self.reset_view, color.light_gray)

        self.level_buttons = []
        for i in range(4):
            b = Button(text=f"LEVEL {i+1}", color=color.green, scale=(0.10, 0.04), position=(-0.22 + i * 0.12, -0.30), text_color=color.white)
            b.on_click = (lambda idx=i: self.load_level(idx))
            self.level_buttons.append(b)

    def reset_view(self):
        self.rotation_y = 45.0
        self.camera_dist = 15.0

    def load_level(self, idx):
        self.current_level_idx = idx
        orig = self.level_data[idx]
        self.board = Board([v.clone() for v in orig.vehicles])
        self.selected_vehicle_idx = None
        self.move_history = []
        self.moves_count = 0
        self.status.text = "3D Consistency Engine Active"
        self.status.color = color.orange
        self._rebuild_scene()

    def reset_level(self):
        self.load_level(self.current_level_idx)

    def undo_move(self):
        if not self.move_history:
            return
        v_idx, old_pos = self.move_history.pop()
        self.board.vehicles[v_idx].position = old_pos
        self.board.update_occupied()
        self.moves_count = max(0, self.moves_count - 1)
        self.selected_vehicle_idx = None
        self._sync_vehicle_entities()

    def show_hint(self):
        self.status.text = "Calculating path..."
        self.status.color = color.violet
        path = solve_bfs(self.board)
        if path:
            v_idx, _ = path[0]
            self.selected_vehicle_idx = v_idx
            self.status.text = f"Hint: Move {self.board.vehicles[v_idx].name}"
            self.status.color = color.violet
            self._sync_vehicle_entities()
        else:
            self.status.text = "No escape path!"
            self.status.color = color.red

    def start_validation(self):
        if self.validation_active:
            return
        self.validation_active = True
        self.validation_angle = 0
        self.validation_errors = []
        self.validation_original_angle = self.rotation_y
        self.status.text = "Running 360° Geometry Sweep..."
        self.status.color = color.yellow

    def calculate_geometry_error(self):
        if not self.board.vehicles:
            return 0.0
        v = self.board.vehicles[0]
        r0, c0 = v.position // 6, v.position % 6
        if v.direction == Direction.HORIZONTAL:
            r1, c1 = r0, c0 + v.length
        else:
            r1, c1 = r0 + v.length, c0
        p1 = self._cell_to_world(r0, c0)
        p2 = self._cell_to_world(r1, c1)
        dist = (p2 - p1).length()
        expected = float(v.length)
        return abs(dist - expected)

    def _cell_to_world(self, r, c):
        x = (c - 2.5)
        z = (2.5 - r)
        return Vec3(x, 0, z)

    def _rebuild_scene(self):
        for e in self.floor_tiles:
            destroy(e)
        for e in self.vehicle_entities:
            destroy(e)
        self._clear_highlights()
        self._clear_preview_overlays()
        self.floor_tiles = []
        self.tile_by_cell = {}
        self.vehicle_entities = []
        self.vehicle_ent_by_idx = {}

        for r in range(6):
            for c in range(6):
                base = color.rgba(0.12, 0.12, 0.13, 1) if (r + c) % 2 == 0 else color.rgba(0.10, 0.10, 0.11, 1)
                if r == 2 and c == 5:
                    base = color.rgba(0.35, 0.05, 0.05, 1)
                tile = Entity(
                    parent=self.grid_parent,
                    model='cube',
                    position=self._cell_to_world(r, c),
                    scale=(0.98, 0.08, 0.98),
                    color=base,
                    shader=lit_with_shadows_shader,
                    collider='box',
                )
                tile.cell = r * 6 + c
                self.floor_tiles.append(tile)
                self.tile_by_cell[tile.cell] = tile

        for i, v in enumerate(self.board.vehicles):
            ent = self._create_vehicle_entity(i, v)
            self.vehicle_entities.append(ent)
            self.vehicle_ent_by_idx[i] = ent

        self._sync_vehicle_entities()
        self._sync_pivot_rotation()
        self._update_move_range_highlight()

    def _create_vehicle_entity(self, idx, v: Vehicle):
        r0, c0 = v.position // 6, v.position % 6
        base = hex_to_ursina_color(v.color_hex)

        if v.direction == Direction.HORIZONTAL:
            center = self._cell_to_world(r0, c0 + (v.length - 1) / 2.0)
        else:
            center = self._cell_to_world(r0 + (v.length - 1) / 2.0, c0)

        ent = Entity(
            parent=self.vehicles_parent,
            model='obj/car1.obj',
            position=center + Vec3(0, 0.45, 0),
            scale=0.44,
            color=base,
            shader=lit_with_shadows_shader,
            collider='box',
        )
        ent.vehicle_idx = idx
        return ent

    def _sync_vehicle_entities(self):
        for i, ent in self.vehicle_ent_by_idx.items():
            v = self.board.vehicles[i]
            r0, c0 = v.position // 6, v.position % 6

            if v.direction == Direction.HORIZONTAL:
                ent.position = self._cell_to_world(r0, c0 + (v.length - 1) / 2.0) + Vec3(0, 0.45, 0)
            else:
                ent.position = self._cell_to_world(r0 + (v.length - 1) / 2.0, c0) + Vec3(0, 0.45, 0)

            base = hex_to_ursina_color(v.color_hex)
            if i == self.selected_vehicle_idx:
                base = color.rgba(min(1.0, base.r + 0.15), min(1.0, base.g + 0.15), min(1.0, base.b + 0.15), 1)
            ent.color = base

        self.level_text.text = f"Level {self.current_level_idx + 1} | Moves: {self.moves_count}"

    def _occupied_without_vehicle(self, vehicle_id):
        return {c for c, vid in self.board.occupied.items() if vid != vehicle_id}

    def _valid_positions_for_vehicle(self, v: Vehicle):
        occ = self._occupied_without_vehicle(v.id)
        positions = {v.position}
        step = 1 if v.direction == Direction.HORIZONTAL else 6
        for s in [step, -step]:
            curr = v.position + s
            while v.can_move_to(curr, occ):
                positions.add(curr)
                curr += s
        return positions

    def _best_pos_for_target_cell(self, v: Vehicle, target_cell: int):
        occ = self._occupied_without_vehicle(v.id)
        if v.direction == Direction.HORIZONTAL:
            tr = target_cell // 6
            if tr != v.position // 6:
                return None
            for h in range(target_cell - v.length + 1, target_cell + 1):
                if v.can_move_to(h, occ):
                    step = 1 if h > v.position else -1
                    clear = True
                    for p in range(v.position + step, h + step, step):
                        if not v.can_move_to(p, occ):
                            clear = False
                            break
                    if clear:
                        return h
            return None

        tc = target_cell % 6
        if tc != v.position % 6:
            return None
        for h in range(target_cell - (v.length - 1) * 6, target_cell + 6, 6):
            if h % 6 == tc and v.can_move_to(h, occ):
                step = 6 if h > v.position else -6
                clear = True
                for p in range(v.position + step, h + step, step):
                    if not v.can_move_to(p, occ):
                        clear = False
                        break
                if clear:
                    return h
        return None

    def _clear_highlights(self):
        for e in self.highlight_overlays:
            destroy(e)
        self.highlight_overlays = []

    def _clear_preview_overlays(self):
        for e in self.preview_overlays:
            destroy(e)
        self.preview_overlays = []

    def _set_highlight_cells(self, cells, tint):
        self._clear_highlights()
        for cell in sorted(set(cells)):
            tile = self.tile_by_cell.get(cell)
            if tile is None:
                continue
            overlay = Entity(
                parent=self.grid_parent,
                model='cube',
                position=tile.position + Vec3(0, 0.075, 0),
                scale=(0.985, 0.02, 0.985),
                color=tint,
                shader=unlit_shader,
            )
            self.highlight_overlays.append(overlay)

    def _set_preview_cells(self, cells, tint):
        self._clear_preview_overlays()
        for cell in sorted(set(cells)):
            tile = self.tile_by_cell.get(cell)
            if tile is None:
                continue
            overlay = Entity(
                parent=self.grid_parent,
                model='cube',
                position=tile.position + Vec3(0, 0.095, 0),
                scale=(0.99, 0.02, 0.99),
                color=tint,
                shader=unlit_shader,
            )
            self.preview_overlays.append(overlay)

    def _update_move_range_highlight(self):
        if self.selected_vehicle_idx is None or self.board is None:
            self._clear_highlights()
            return
        v = self.board.vehicles[self.selected_vehicle_idx]
        positions = self._valid_positions_for_vehicle(v)
        cells = set()
        for p in positions:
            cells.update(v.get_cells(p))
        self._set_highlight_cells(cells, color.rgba(38, 217, 64, 90))

    def _cell_from_world_point(self, world_point):
        local = self.pivot.world_to_local_point(world_point)
        c = int(round(local.x + 2.5))
        r = int(round(2.5 - local.z))
        if r < 0 or r > 5 or c < 0 or c > 5:
            return None
        return r * 6 + c

    def _target_cell_from_mouse(self):
        hovered = self._resolve_pick(mouse.hovered_entity)
        if hovered is not None and hasattr(hovered, 'cell'):
            return hovered.cell
        try:
            wp = getattr(mouse, 'world_point', None)
        except Exception:
            wp = None
        if wp is None:
            return None
        return self._cell_from_world_point(wp)

    def _set_vehicle_preview(self, v_idx, pos):
        ent = self.vehicle_ent_by_idx.get(v_idx)
        if ent is None:
            return
        v = self.board.vehicles[v_idx]
        r0, c0 = pos // 6, pos % 6
        if v.direction == Direction.HORIZONTAL:
            ent.position = self._cell_to_world(r0, c0 + (v.length - 1) / 2.0) + Vec3(0, 0.45, 0)
        else:
            ent.position = self._cell_to_world(r0 + (v.length - 1) / 2.0, c0) + Vec3(0, 0.45, 0)

    def _sync_pivot_rotation(self):
        self.pivot.rotation_y = self.rotation_y

    def _try_click_cell(self, cell):
        clicked_vehicle_idx = None
        for i, v in enumerate(self.board.vehicles):
            if cell in v.get_cells():
                clicked_vehicle_idx = i
                break

        if self.selected_vehicle_idx is None:
            if clicked_vehicle_idx is not None:
                self.selected_vehicle_idx = clicked_vehicle_idx
                self.status.text = f"Selected {self.board.vehicles[clicked_vehicle_idx].name}"
                self.status.color = color.lime
                self._sync_vehicle_entities()
            return

        if clicked_vehicle_idx == self.selected_vehicle_idx:
            self.selected_vehicle_idx = None
            self._sync_vehicle_entities()
            return

        if clicked_vehicle_idx is not None:
            self.selected_vehicle_idx = clicked_vehicle_idx
            self._sync_vehicle_entities()
            return

        self._try_move_to_cell(self.selected_vehicle_idx, cell)

    def _try_move_to_cell(self, v_idx, target_cell):
        v = self.board.vehicles[v_idx]
        occ = {c for c, vid in self.board.occupied.items() if vid != v.id}

        if v.direction == Direction.HORIZONTAL:
            tr = target_cell // 6
            if tr != v.position // 6:
                return
            best_pos = None
            for h in range(target_cell - v.length + 1, target_cell + 1):
                if v.can_move_to(h, occ):
                    step = 1 if h > v.position else -1
                    clear = True
                    for p in range(v.position + step, h + step, step):
                        if not v.can_move_to(p, occ):
                            clear = False
                            break
                    if clear:
                        best_pos = h
                        break
            if best_pos is not None:
                self._execute_move(v_idx, best_pos)
        else:
            tc = target_cell % 6
            if tc != v.position % 6:
                return
            best_pos = None
            for h in range(target_cell - (v.length - 1) * 6, target_cell + 6, 6):
                if h % 6 == tc and v.can_move_to(h, occ):
                    step = 6 if h > v.position else -6
                    clear = True
                    for p in range(v.position + step, h + step, step):
                        if not v.can_move_to(p, occ):
                            clear = False
                            break
                    if clear:
                        best_pos = h
                        break
            if best_pos is not None:
                self._execute_move(v_idx, best_pos)

    def _execute_move(self, v_idx, new_pos):
        self.move_history.append((v_idx, self.board.vehicles[v_idx].position))
        self.board.vehicles[v_idx].position = new_pos
        self.board.update_occupied()
        self.moves_count += 1
        self.selected_vehicle_idx = None
        self._sync_vehicle_entities()
        if self.board.check_win():
            self.status.text = f"Success! Escaped Level {self.current_level_idx + 1}!"
            self.status.color = color.yellow
            if self.current_level_idx < len(self.level_data) - 1:
                self.load_level(self.current_level_idx + 1)
            else:
                self.load_level(0)

    def _update(self):
        self._render_timer += u_time.dt
        if self._render_timer >= 0.15:
            err = self.calculate_geometry_error()
            self.metrics.text = f"Render: {self.last_render_ms:.1f}ms | Error: {err:.6f}"
            self._render_timer = 0.0

        start = pytime.perf_counter()

        if self.validation_active:
            self.rotation_y = float(self.validation_angle)
            self._sync_pivot_rotation()
            self.validation_errors.append(self.calculate_geometry_error())
            self.validation_angle += 1
            if self.validation_angle > 360:
                max_err = max(self.validation_errors) if self.validation_errors else 0.0
                self.rotation_y = self.validation_original_angle
                self.validation_active = False
                if max_err < 0.001:
                    self.status.text = f"Validation Passed | Max Deviation: {max_err:.8f}"
                    self.status.color = color.lime
                else:
                    self.status.text = f"Validation Failed | Max Deviation: {max_err:.8f}"
                    self.status.color = color.red
                self._sync_pivot_rotation()

        if self.drag_mode == 'move' and self.drag_vehicle_idx is not None and held_keys['left mouse']:
            v_idx = self.drag_vehicle_idx
            v = self.board.vehicles[v_idx]
            dx = mouse.x - self.drag_mouse_start.x
            dy = mouse.y - self.drag_mouse_start.y

            cam_right = getattr(camera, 'right', Vec3(1, 0, 0))
            cam_up = getattr(camera, 'up', Vec3(0, 1, 0))
            rot = math.radians(self.rotation_y)

            if v.direction == Direction.HORIZONTAL:
                ax_lx, az_lz = 1.0, 0.0
                step_size = 1
            else:
                ax_lx, az_lz = 0.0, -1.0
                step_size = 6

            ax_wx = ax_lx * math.cos(rot) + az_lz * math.sin(rot)
            az_wz = -ax_lx * math.sin(rot) + az_lz * math.cos(rot)
            axis_world = Vec3(ax_wx, 0, az_wz)

            sx = axis_world.dot(cam_right)
            sy = axis_world.dot(cam_up)
            proj = dx * sx + dy * sy

            threshold = 0.07
            steps = int(round(proj / threshold))
            desired = self.drag_start_pos + steps * step_size

            valid_positions = sorted(self._valid_positions_for_vehicle(v))
            if valid_positions:
                best = min(valid_positions, key=lambda p: abs(p - desired))
                if best != self.drag_preview_pos:
                    self.drag_preview_pos = best
                    self._set_vehicle_preview(v_idx, best)
                    self._set_preview_cells(v.get_cells(best), color.rgba(242, 214, 38, 110))

        if self.drag_mode == 'rotate' and held_keys['left mouse']:
            dx = (mouse.x - self.last_mouse.x)
            self.rotation_y -= dx * 220
            self.last_mouse = Vec2(mouse.x, mouse.y)
            self._sync_pivot_rotation()

        if held_keys['right mouse']:
            if not self.is_rotating:
                self.is_rotating = True
                self.last_mouse = Vec2(mouse.x, mouse.y)
            dx = (mouse.x - self.last_mouse.x)
            self.rotation_y -= dx * 220
            self.last_mouse = Vec2(mouse.x, mouse.y)
            self._sync_pivot_rotation()
        else:
            self.is_rotating = False

        self.last_render_ms = (pytime.perf_counter() - start) * 1000.0

    def run(self):
        self.app.run()


if __name__ == '__main__':
    _game = RushHourUrsina()
    _game._fatal_error = False

    def update():
        if getattr(_game, '_fatal_error', False):
            return
        try:
            _game._update()
        except Exception as e:
            _game._fatal_error = True
            _game.status.text = f"Error: {type(e).__name__}"
            _game.status.color = color.red
            traceback.print_exc()

    def input(key):
        if getattr(_game, '_fatal_error', False):
            return
        try:
            _game._input(key)
        except Exception as e:
            _game._fatal_error = True
            _game.status.text = f"Error: {type(e).__name__}"
            _game.status.color = color.red
            traceback.print_exc()

    _game.run()

