import math
import collections
import time as pytime
import traceback
import os
import random
import json

from enum import Enum

from ursina import Ursina, Entity, Text, Button, color, mouse, camera, Vec3, Vec2, destroy, held_keys, time as u_time, load_model, Mesh, invoke, curve, window, application
from ursina.shaders import lit_with_shadows_shader, unlit_shader
from ursina.lights import DirectionalLight, AmbientLight

try:
    import winsound
except Exception:
    winsound = None


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

        self.ui_bg = color.rgba(0.96, 0.97, 0.98, 0.78)
        self.ui_text = color.rgba(0.14, 0.14, 0.16, 1)
        self.ui_muted = color.rgba(0.30, 0.30, 0.34, 1)
        self.ui_shadow = color.rgba(0, 0, 0, 0.10)
        self.ui_border = color.rgba(0, 0, 0, 0.06)

        self.btn_undo = color.rgba(0.18, 0.38, 0.62, 1)
        self.btn_reset = color.rgba(0.72, 0.38, 0.15, 1)
        self.btn_hint = color.rgba(0.42, 0.28, 0.60, 1)
        self.btn_validate = color.rgba(0.65, 0.22, 0.25, 1)
        self.btn_neutral = color.rgba(0.28, 0.34, 0.44, 1)

        camera.clear_color = color.rgba(0.93, 0.94, 0.95, 1)
        try:
            window.color = color.rgba(0.93, 0.94, 0.95, 1)
        except Exception:
            pass

        self.dev_overlay_enabled = False
        try:
            for attr in ('exit_button', 'fps_counter', 'entity_counter', 'collider_counter', 'cog_button'):
                widget = getattr(window, attr, None)
                if widget is not None:
                    widget.enabled = False
                    if hasattr(widget, 'visible'):
                        widget.visible = False
        except Exception:
            pass

        self.top_panel = self._glass_panel(scale=(0.40, 0.34), position=(0.67, 0.30))
        self.bottom_panel = self._glass_panel(scale=(0.24, 0.82), position=(-0.74, 0.00))
        self.top_ui = Entity(parent=camera.ui, position=(0.67, 0.30))
        self.bottom_ui = Entity(parent=camera.ui, position=(-0.74, 0.00))

        self.title_text = Text("Rush Hour", parent=self.top_ui, origin=(-0.5, 0), x=-0.17, y=0.10, scale=1.20, color=color.rgba(0.46, 0.38, 0.22, 1))

        AmbientLight(color=color.rgba(0.35, 0.35, 0.4, 1))
        DirectionalLight(direction=Vec3(1, -2, 1), color=color.rgba(0.9, 0.9, 0.9, 1))

        self.pivot = Entity()
        self.grid_parent = Entity(parent=self.pivot)
        self.vehicles_parent = Entity(parent=self.pivot)

        self.rotation_y = 45.0
        self.camera_dist = 15.0

        self._camera_base_pos = Vec3(0, 9.0, -self.camera_dist)
        self._camera_shake_t = 0.0
        self._camera_shake_strength = 0.0
        self._camera_shake_until = 0.0
        self._bump_cooldown_until = 0.0
        self._set_camera_base()

        self._ortho_height = 20.0
        self._ortho_zoom = 1.0
        self._ortho_margin = 1.08
        self._ortho_last_aspect = None
        self._ortho_film_h = 0.0

        self.level_data = self.init_levels()
        self.current_level_idx = 0
        self.optimal_moves_cache = {}
        self.optimal_moves = None
        self.board = None
        self.selected_vehicle_idx = None
        self.move_history = []
        self.moves_count = 0

        self.level_elapsed = 0.0
        self._save_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'rush_hour_save.json')
        self._save_data = self._load_save()
        self._save_data.setdefault('achievements', {})
        self._save_data.setdefault('stats', {})
        self._save_data.setdefault('tutorial', {})
        self._save_data['stats'].setdefault('rotation_units', 0)
        self._save_data['stats'].setdefault('rotations', 0)
        self._save_data['stats'].setdefault('snapshots', 0)
        self._save_data['stats'].setdefault('hints_used_total', 0)
        self._save_data['stats'].setdefault('levels_cleared', {})

        self.level_text = Text("", parent=self.top_ui, origin=(-0.5, 0), x=-0.17, y=0.055, scale=0.68, color=self.ui_text)
        self.status = Text("Ready", parent=self.top_ui, origin=(-0.5, 0), x=-0.17, y=-0.06, scale=0.62, color=self.ui_text)
        self.help = Text("Controls:\nDrag car to move\nDrag empty space to rotate\nWheel: zoom\nV: switch view\nP: save screenshot", parent=self.top_ui, origin=(-0.5, 0), x=-0.17, y=-0.13, scale=0.48, color=self.ui_muted)

        self.floor_tiles = []
        self.tile_by_cell = {}
        self.vehicle_entities = []
        self.vehicle_ent_by_idx = {}

        self.highlight_overlays = []
        self.preview_overlays = []

        self.vehicle_models = {
            2: {'model': None, 'source_len': 1.0, 'source_min_y': 0.0},
            3: {'model': None, 'source_len': 1.0, 'source_min_y': 0.0},
        }
        self.vehicle_obj_base_scale = 1.0
        self._init_vehicle_models()

        self._select_pulse_speed = 4.0
        self._select_hover_amp = 0.05

        self._move_animating = False
        self._move_anim_end = 0.0
        self._move_anim_duration = 0.12

        self.is_ortho = False
        self._camera_3d_pos = Vec3(0, 9.0, -self.camera_dist)
        self._camera_3d_rot = Vec3(0, 0, 0)

        self.hint_used_this_level = False

        self._toast_panel = None
        self._toast_until = 0.0

        self.is_rotating = False
        self.last_mouse = Vec2(0, 0)
        self.drag_mode = None
        self.drag_vehicle_idx = None
        self.drag_start_pos = None
        self.drag_preview_pos = None
        self.drag_mouse_start = Vec2(0, 0)

        self._tutorial_active = False
        self._tutorial_step = 0
        self._tutorial_step_done = False
        self._tutorial_step_started_at = 0.0
        self._tutorial_rotate_ref = 0.0
        self._tutorial_target_vehicle_idx = None
        self._tutorial_move_target_pos = None
        self._tutorial_vehicle_highlight = None
        self._tutorial_road_overlays = []
        self._tutorial_dest_overlays = []
        self._tutorial_ui_highlights = []
        self._tutorial_panel = None
        self._tutorial_panel_shadow = None
        self._tutorial_panel_border = None
        self._tutorial_ui = None
        self._tutorial_title = None
        self._tutorial_body = None
        self._tutorial_btn_next = None
        self._tutorial_btn_skip = None
        self._tutorial_layout = 'intro'
        self._tutorial_shown_this_session = False

        self._build_ui_buttons()
        self.load_level(0)

        self.last_render_ms = 0.0
        self._render_timer = 0.0

        self.validation_active = False
        self.validation_angle = 0
        self.validation_errors = []
        self.validation_original_angle = 45.0
        # ====== 开屏界面 ======
        self.splash_shown = True

        # 全屏半透明遮罩
        self.splash_overlay = Button(
            parent=camera.ui, text='',
            scale=(2.2, 2.2),
            color=color.rgba(0.08, 0.08, 0.10, 0.92),  # 或你设定的任意颜色
            radius=0,
            collider=None  # ← 添加这一行，关闭碰撞检测
        )

        # 标题
        self.splash_title = Text("RUSH HOUR 3D", parent=camera.ui, origin=(0,0),
                                 scale=2.8, y=0.15, color=color.rgba(0.95, 0.85, 0.45, 1))

        # 开始按钮
        self.splash_btn = Button(
            text="START", parent=camera.ui,
            scale=(0.25, 0.08), y=-0.1, radius=0.5,
            color=color.rgba(0.22, 0.40, 0.30, 0.9),
            highlight_color=color.rgba(0.28, 0.50, 0.38, 1),
            pressed_color=color.rgba(0.18, 0.32, 0.24, 1),
            text_color=color.rgba(1,1,1,0.95),
            on_click=self._dismiss_splash
        )

        

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

    def _set_camera_base(self):
        self._camera_base_pos = Vec3(0, 9.0, -self.camera_dist)
        camera.position = self._camera_base_pos
        camera.look_at(Vec3(0, 0, 0))

    def _beep(self, kind):
        if winsound is None:
            return
        try:
            if kind == 'select':
                winsound.Beep(880, 60)
            elif kind == 'move':
                winsound.Beep(660, 45)
            elif kind == 'bump':
                winsound.Beep(220, 70)
        except Exception:
            pass

    def _dismiss_splash(self):
        # 如果已经隐藏，避免重复执行
        if not getattr(self, 'splash_shown', True):
            return
        self.splash_shown = False

        # 所有元素一起淡出
        self.splash_title.animate('color', color.clear, duration=0.4)
        self.splash_btn.animate('color', color.clear, duration=0.4)
        if self.splash_btn.text_entity:
            self.splash_btn.text_entity.animate('color', color.clear, duration=0.4)

        self.splash_overlay.animate_color(color.clear, duration=0.5, curve=curve.out_quad)

        # 动画结束后销毁
        invoke(self._remove_splash, delay=0.55)

    def _remove_splash(self):
        destroy(self.splash_overlay)
        destroy(self.splash_title)
        destroy(self.splash_btn)
        # 可选：清除引用
        self.splash_overlay = None
        self.splash_title = None
        self.splash_btn = None

    def _load_save(self):
        try:
            if os.path.exists(self._save_path):
                with open(self._save_path, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                if isinstance(data, dict):
                    data.setdefault('levels', {})
                    return data
        except Exception:
            pass
        return {'levels': {}}

    def _save(self):
        try:
            with open(self._save_path, 'w', encoding='utf-8') as f:
                json.dump(self._save_data, f, ensure_ascii=False, indent=2)
        except Exception:
            pass

    def _glass_panel(self, scale, position):
        radius = 0.18

        border = Button(parent=camera.ui, text='', scale=(scale[0] + 0.003, scale[1] + 0.003), position=position, color=self.ui_border, radius=radius)
        border.shader = unlit_shader
        border.collider = None
        border.z = 0.01

        panel = Button(parent=camera.ui, text='', scale=scale, position=position, color=self.ui_bg, radius=radius)
        panel.shader = unlit_shader
        panel.collider = None
        panel.z = 0.0

        panel._border = border
        return panel

    def _set_button_label(self, button, text, scale=0.50, z=-0.12):
        label = getattr(button, '_label_entity', None)
        if label is None:
            label = Text(
                text=text,
                parent=button.parent,
                origin=(0, 0),
                position=(button.x, button.y, z),
                scale=scale,
                color=getattr(button, 'text_color', color.black),
            )
            button._label_entity = label
        else:
            label.text = text
            label.parent = button.parent
            label.position = (button.x, button.y, z)
            label.scale = scale
            label.color = getattr(button, 'text_color', color.black)
        button.text = ''
        return label

    def _show_toast(self, title, subtitle=None, duration=2.2):
        if self._toast_panel is not None:
            try:
                destroy(self._toast_panel.get('bg'))
                destroy(self._toast_panel.get('border'))
                destroy(self._toast_panel.get('ui'))
            except Exception:
                pass
            self._toast_panel = None
        self._toast_until = pytime.perf_counter() + float(duration)
        bg = self._glass_panel(scale=(0.62, 0.16), position=(0, 0.30))
        border = getattr(bg, '_border', None)
        ui = Entity(parent=camera.ui, position=(0, 0.30))
        bg.color = color.rgba(self.ui_bg.r, self.ui_bg.g, self.ui_bg.b, 0)
        if border is not None:
            border.color = color.rgba(self.ui_border.r, self.ui_border.g, self.ui_border.b, 0)
        bg.animate_color(self.ui_bg, duration=0.22, curve=curve.out_quad)
        if border is not None:
            border.animate_color(self.ui_border, duration=0.22, curve=curve.out_quad)

        Text(title, parent=ui, origin=(0, 0), scale=1.15, y=0.03, color=color.rgba(1, 0.88, 0.45, 1))
        if subtitle:
            Text(subtitle, parent=ui, origin=(0, 0), scale=0.85, y=-0.04, color=self.ui_text)

        self._toast_panel = {'bg': bg, 'border': border, 'ui': ui}

    def _unlock_achievement(self, key, title, subtitle=None):
        ach = self._save_data.setdefault('achievements', {})
        if ach.get(key):
            return
        ach[key] = {'unlocked_at': pytime.time()}
        self._save()
        self._show_toast(f"Achievement Unlocked: {title}", subtitle)
        self._beep('select')

    def toggle_view_mode(self):
        self._tutorial_on_toggle_view()
        self.is_ortho = not self.is_ortho
        if self.is_ortho:
            self._camera_3d_pos = Vec3(camera.position)
            self._camera_3d_rot = Vec3(camera.rotation)
            camera.orthographic = True
            self._apply_ortho_lens(force=True)
            camera.position = (0, self._ortho_height, 0)
            camera.rotation = (90, 0, 0)
            self.rotation_y = 0.0
            self._sync_pivot_rotation()
            self._show_toast("2D View", "Orthographic top-down")
        else:
            camera.orthographic = False
            camera.position = self._camera_3d_pos
            camera.rotation = self._camera_3d_rot
            camera.look_at(Vec3(0, 0, 0))
            self._show_toast("3D View", "Perspective")

    def _apply_ortho_lens(self, force=False):
        if not self.is_ortho and not force:
            return
        try:
            aspect = float(window.aspect_ratio)
        except Exception:
            aspect = 16 / 9
        zoom = float(self._ortho_zoom)
        if (not force) and self._ortho_last_aspect is not None:
            if abs(self._ortho_last_aspect - aspect) < 1e-6 and abs(getattr(self, '_ortho_last_zoom', 0.0) - zoom) < 1e-6:
                return
        self._ortho_last_aspect = aspect
        self._ortho_last_zoom = zoom

        board_size = 6.0
        film_h = (board_size * self._ortho_margin) / max(0.001, zoom)
        film_w = film_h * max(0.001, aspect)
        self._ortho_film_h = film_h

        try:
            lens = application.base.cam.node().getLens()
            lens.setFilmSize(film_w, film_h)
        except Exception:
            try:
                lens = camera.getLens()
                lens.setFilmSize(film_w, film_h)
            except Exception:
                pass

    def take_screenshot(self):
        base_dir = os.path.dirname(os.path.abspath(__file__))
        out_dir = os.path.join(base_dir, 'screenshots')
        os.makedirs(out_dir, exist_ok=True)
        t = self._format_time(self.level_elapsed)
        opt = self.optimal_moves
        opt_s = str(opt) if opt is not None else "?"
        stamp = pytime.strftime('%Y%m%d_%H%M%S', pytime.localtime())
        name = f"level{self.current_level_idx+1}_moves{self.moves_count}-{opt_s}_time{t.replace(':','-')}__{stamp}"
        name = ''.join(ch if ch.isalnum() or ch in '._-@' else '_' for ch in name)

        wm_panel = Button(parent=camera.ui, text='', scale=(0.72, 0.10), x=0.0, y=-0.40, color=color.rgba(0.96, 0.97, 0.98, 0.82), radius=0.18)
        wm_panel.shader = unlit_shader
        wm_panel.collider = None
        Text(f"Level {self.current_level_idx+1}   Moves {self.moves_count}/{opt_s}   Time {t}", parent=wm_panel, origin=(0, 0), scale=0.95, y=0, color=color.rgba(0.14, 0.14, 0.16, 1))

        def _snap():
            try:
                from ursina import application
                prefix = os.path.join(out_dir, name)
                application.base.screenshot(namePrefix=prefix, defaultFilename=0)
                self._save_data['stats']['snapshots'] = int(self._save_data['stats'].get('snapshots', 0)) + 1
                self._save()
                self._show_toast("Saved Screenshot", os.path.join('screenshots', name + '.png'))
            finally:
                destroy(wm_panel)

        invoke(_snap, delay=0.05)

    def _format_time(self, seconds):
        seconds = max(0.0, float(seconds))
        m = int(seconds // 60)
        s = seconds - m * 60
        return f"{m:02d}:{s:04.1f}"

    def _get_optimal_moves(self, idx):
        if idx in self.optimal_moves_cache:
            return self.optimal_moves_cache[idx]
        try:
            orig = self.level_data[idx]
            b = Board([v.clone() for v in orig.vehicles])
            path = solve_bfs(b)
            value = len(path) if path else None
        except Exception:
            value = None
        self.optimal_moves_cache[idx] = value
        return value

    def _stars_for_moves(self, moves, optimal, elapsed):
        moves = int(moves)
        elapsed = float(elapsed)
        if optimal is None:
            if elapsed <= 45.0:
                return 3
            if elapsed <= 90.0:
                return 2
            return 1

        diff = moves - int(optimal)
        if diff <= 1 and elapsed <= 45.0:
            return 3
        if diff <= 4 and elapsed <= 90.0:
            return 2
        return 1

    def _stars_text(self, count):
        c = max(1, min(3, int(count)))
        return f"Stars: {'*' * c}{'-' * (3 - c)}"

    def _update_hud(self):
        opt = self.optimal_moves
        opt_s = str(opt) if opt is not None else "?"
        t = self._format_time(self.level_elapsed)

        best = self._save_data.get('levels', {}).get(str(self.current_level_idx), {})
        best_time = best.get('best_time')
        best_moves = best.get('best_moves')
        best_time_s = self._format_time(best_time) if isinstance(best_time, (int, float)) else "--:--.-"
        best_moves_s = str(best_moves) if isinstance(best_moves, int) else "-"

        self.level_text.text = (
            f"Level {self.current_level_idx + 1}\n"
            f"Moves: {self.moves_count}/{opt_s} | Time: {t}\n"
            f"Best: {best_moves_s} moves | {best_time_s}"
        )

    def _trigger_shake(self, strength=0.22, duration=0.16):
        now = pytime.perf_counter()
        if now < self._bump_cooldown_until:
            return
        self._bump_cooldown_until = now + 0.12
        self._camera_shake_strength = max(self._camera_shake_strength, float(strength))
        self._camera_shake_until = max(self._camera_shake_until, now + float(duration))
        self._beep('bump')

    def _pulse_color(self, c, k):
        r = max(0.0, min(1.0, c.r * k))
        g = max(0.0, min(1.0, c.g * k))
        b = max(0.0, min(1.0, c.b * k))
        return color.rgba(r, g, b, 1)

    def _load_vehicle_models(self):
        base_dir = os.path.dirname(os.path.abspath(__file__))
        obj_dir = os.path.join(base_dir, 'obj')
        models = {2: None, 3: None}
        if not os.path.isdir(obj_dir):
            return models

        def _try_load(filename):
            p = os.path.join(obj_dir, filename)
            if os.path.exists(p):
                try:
                    return load_model(f"obj/{filename}")
                except Exception:
                    return None
            return None

        car = _try_load('car1.obj')
        if car is not None:
            models[2] = car

        truck = _try_load('big_car.obj')
        if truck is not None:
            models[3] = truck
        elif car is not None:
            models[3] = car

        if models[2] is None and models[3] is None:
            for name in sorted(os.listdir(obj_dir)):
                if name.lower().endswith('.obj'):
                    m = _try_load(name)
                    if m is not None:
                        models[2] = m
                        models[3] = m
                        break
        return models

    def _init_vehicle_models(self):
        loaded = self._load_vehicle_models()
        for length, m in loaded.items():
            entry = self.vehicle_models[length]
            if m is None:
                entry['model'] = None
                entry['source_len'] = 1.0
                entry['source_min_y'] = 0.0
                continue
            entry['model'] = m
            try:
                vs = m.vertices
                xs = [v[0] for v in vs]
                ys = [v[1] for v in vs]
                zs = [v[2] for v in vs]
                x_size = (max(xs) - min(xs)) if xs else 1.0
                z_size = (max(zs) - min(zs)) if zs else 1.0
                entry['source_len'] = max(0.001, max(x_size, z_size))
                entry['source_min_y'] = min(ys) if ys else 0.0
            except Exception:
                entry['source_len'] = 1.0
                entry['source_min_y'] = 0.0

    def _clone_vehicle_mesh(self, model):
        if model is None:
            return None
        try:
            return Mesh(
                vertices=list(getattr(model, 'vertices', []) or []),
                triangles=list(getattr(model, 'triangles', []) or []),
                uvs=list(getattr(model, 'uvs', []) or []),
                normals=list(getattr(model, 'normals', []) or []),
                colors=list(getattr(model, 'colors', []) or []),
                mode=getattr(model, 'mode', 'triangle'),
            )
        except Exception:
            return model

    def _input(self, key):
        if self._move_animating:
            return
        if key in ('v', 'V'):
            self.toggle_view_mode()
            return
        if key in ('h', 'H'):  
            self.show_hint()
            return
        if key in ('p', 'P'):
            self.take_screenshot()
            return
        if self._tutorial_active and self._tutorial_step == 0:
            return
        if key == 'scroll up':
            self._tutorial_on_zoom()
            if self.is_ortho:
                self._ortho_zoom = min(15.0, self._ortho_zoom * 1.08)
                self._apply_ortho_lens(force=True)
            else:
                self.camera_dist = max(8.0, self.camera_dist - 1.2)
                self._set_camera_base()
            return
        if key == 'scroll down':
            self._tutorial_on_zoom()
            if self.is_ortho:
                self._ortho_zoom = max(0.3, self._ortho_zoom / 1.08)
                self._apply_ortho_lens(force=True)
            else:
                self.camera_dist = min(26.0, self.camera_dist + 1.2)
                self._set_camera_base()
            return

        if key == 'left mouse down':
            hovered = self._resolve_pick(mouse.hovered_entity)
            if hovered is not None and self._is_ui_entity(hovered):
                self.drag_mode = None
                self.drag_vehicle_idx = None
                return
                
            if getattr(self, '_active_hint_move', None) is not None:
                hint_v_idx, _ = self._active_hint_move
                clicked_v_idx = getattr(hovered, 'vehicle_idx', None) if hovered else None
                if clicked_v_idx != hint_v_idx:
                    self._active_hint_move = None
                    self._update_move_range_highlight()

            if hovered is not None and hasattr(hovered, 'vehicle_idx'):
                self.selected_vehicle_idx = hovered.vehicle_idx
                self.status.text = f"Selected {self.board.vehicles[self.selected_vehicle_idx].name}"
                self.status.color = color.rgba(0.62, 0.78, 0.70, 1)
                self._sync_vehicle_entities()
                self._update_move_range_highlight()
                self._beep('select')

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
            if self.is_ortho:
                self.drag_mode = 'rotate2d'
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
        b3.add_vehicle(Vehicle(0, "Red Car", "#e74c3c", 12, 2, Direction.HORIZONTAL, True))     
        b3.add_vehicle(Vehicle(1, "Purple Car", "#9b59b6", 14, 2, Direction.VERTICAL))       
        b3.add_vehicle(Vehicle(2, "Yellow Car", "#f1c40f", 8, 2, Direction.HORIZONTAL))         
        b3.add_vehicle(Vehicle(3, "Green Car", "#2ecc71", 26, 2, Direction.HORIZONTAL))        
        b3.add_vehicle(Vehicle(4, "Orange Truck", "#e67e22", 18, 3, Direction.VERTICAL))          
        b3.add_vehicle(Vehicle(5, "Blue Truck", "#3498db", 5, 3, Direction.VERTICAL))        
        levels.append(b3) 

        b4 = Board()
        b4.add_vehicle(Vehicle(0, "Red Car", "#e74c3c", 13, 2, Direction.HORIZONTAL, True))
        b4.add_vehicle(Vehicle(2, "Yellow Car", "#f1c40f", 6, 2, Direction.VERTICAL))
        b4.add_vehicle(Vehicle(3, "Purple Truck", "#8e44ad", 7, 2, Direction.HORIZONTAL))
        b4.add_vehicle(Vehicle(4, "Green Car", "#2ecc71", 18, 2, Direction.HORIZONTAL))
        b4.add_vehicle(Vehicle(5, "Orange Car", "#e67e22", 20, 2, Direction.VERTICAL))
        b4.add_vehicle(Vehicle(6, "Gray Truck", "#7f8c8d", 25, 2, Direction.VERTICAL))
        b4.add_vehicle(Vehicle(7, "Lime Car", "#2ecc71", 32, 2, Direction.HORIZONTAL))
        b4.add_vehicle(Vehicle(8, "Lie Car", "#2ecc71", 34, 2, Direction.HORIZONTAL))
        b4.add_vehicle(Vehicle(9, "Purple ruck", "#8e44ad", 3, 2, Direction.VERTICAL))
        b4.add_vehicle(Vehicle(10, "Blue Cr (L2)", "#3498db", 4, 3, Direction.VERTICAL))
        b4.add_vehicle(Vehicle(11, "Yellw Car", "#f1c40f", 5, 2, Direction.VERTICAL))
        levels.append(b4)

        return levels

    def _build_ui_buttons(self):
        self.buttons = []
        self.action_buttons = {}
        self.action_buttons_by_text = {}

        def style_btn(b, base):
            b.text_color = color.rgba(0, 0, 0, 0.98)
            c = color.rgba(base.r, base.g, base.b, 1)
            b.color = c
            b.highlight_color = c
            b.pressed_color = c
            b.text_size = 0.5
            b.highlight_text_size = 0.5
            b.highlight_text_color = b.text_color
            if getattr(b, 'text_entity', None) is not None:
                b.text_entity.enabled = True
                b.text_entity.z = -0.10
            return b

        def mk_btn(text, x, y, on_click, tint, scale_xy=(0.115, 0.045), label_scale=0.50):
            b = Button(text=text, parent=self.bottom_ui, scale=(0.115, 0.045), position=(x, y), radius=0.95)
            b.scale = scale_xy
            style_btn(b, tint)
            b.on_click = on_click
            self._set_button_label(b, text, scale=label_scale)
            self.buttons.append(b)
            return b

        action_x = 0.0
        gap = 0.015
        base_h = 0.065
        labels = [
            ("UNDO", self.undo_move, self.btn_undo, base_h, 0.56),
            ("RESET", self.reset_level, self.btn_reset, base_h, 0.56),
            ("HINT", self.show_hint, self.btn_hint, base_h, 0.56),
            ("RESET VIEW", self.reset_view, self.btn_neutral, base_h, 0.44),
            ("2D/3D", self.toggle_view_mode, self.btn_neutral, base_h, 0.52),
        ]
        
        def make_level_cb(idx):
            return lambda: self.load_level(idx)

        for i in range(4):
            labels.append((f"LEVEL {i+1}", make_level_cb(i), color.rgba(0.20, 0.42, 0.32, 1), base_h, 0.46))

        total_h = sum(h for _, _, _, h, _ in labels) + gap * (len(labels) - 1)
        y = total_h / 2 - labels[0][3] / 2
        
        self.level_buttons = []
        for t, cb, c, h, label_scale in labels:
            b = mk_btn(t, action_x, y, cb, c, scale_xy=(0.18, h), label_scale=label_scale)
            if t.startswith("LEVEL"):
                self.level_buttons.append(b)
            else:
                self.action_buttons[t] = b
                self.action_buttons_by_text[t.upper()] = b
            y -= h + gap

    def reset_view(self):
        self.rotation_y = 45.0
        self.camera_dist = 15.0
        self._set_camera_base()

    def load_level(self, idx):
        if getattr(self, 'hide_end_screen', None):
            self.hide_end_screen()
        self.current_level_idx = idx
        orig = self.level_data[idx]
        self.board = Board([v.clone() for v in orig.vehicles])
        self.selected_vehicle_idx = None
        self.move_history = []
        self.moves_count = 0
        self.level_elapsed = 0.0
        self.optimal_moves = self._get_optimal_moves(idx)
        self.hint_used_this_level = False
        self._active_hint_move = None
        self.status.text = "Ready to play"
        self.status.color = self.ui_muted
        self._rebuild_scene()
        self._update_hud()
        self._tutorial_maybe_start()

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
        self._active_hint_move = None
        self._sync_vehicle_entities()
        self._update_hud()

    def show_hint(self):
        self.status.text = "Calculating path..."
        self.status.color = self.btn_hint
        if not self.hint_used_this_level:
            self.hint_used_this_level = True
            self._save_data['stats']['hints_used_total'] = int(self._save_data['stats'].get('hints_used_total', 0)) + 1
            self._save()
        path = solve_bfs(self.board)
        if path:
            v_idx, new_pos = path[0]
            self.selected_vehicle_idx = v_idx
            self._active_hint_move = (v_idx, new_pos)
            self.status.text = f"Hint: Move {self.board.vehicles[v_idx].name}"
            self.status.color = self.btn_hint
            self._sync_vehicle_entities()
            self._update_hud()
            self._update_move_range_highlight()
        else:
            self.status.text = "No move hint available"
            self.status.color = self.ui_muted
            self._active_hint_move = None
            self._update_move_range_highlight()

    def start_validation(self):
        if self.validation_active:
            return
        self.validation_active = True
        self.validation_angle = 0
        self.validation_errors = []
        self.validation_original_angle = self.rotation_y
        self.status.text = "Running 360° Geometry Sweep..."
        self.status.color = color.rgba(0.78, 0.72, 0.50, 1)

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
                base = color.rgba(0.82, 0.84, 0.86, 1) if (r + c) % 2 == 0 else color.rgba(0.78, 0.80, 0.82, 1)
                if r == 2 and c == 5:
                    base = color.rgba(0.80, 0.62, 0.62, 1)
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
            collider_scale = (0.98 * v.length, 0.55, 0.92)
        else:
            center = self._cell_to_world(r0 + (v.length - 1) / 2.0, c0)
            collider_scale = (0.92, 0.55, 0.98 * v.length)

        ent = Entity(parent=self.vehicles_parent, position=center)
        ent.vehicle_idx = idx

        collider_ent = Entity(
            parent=ent,
            model='cube',
            scale=collider_scale,
            color=color.rgba(0, 0, 0, 0),
            shader=unlit_shader,
            collider='box',
        )
        collider_ent.vehicle_idx = idx
        ent.collider_ent = collider_ent

        model_info = self.vehicle_models.get(v.length, {'model': None, 'source_len': 1.0, 'source_min_y': 0.0})
        obj_model = model_info['model']
        source_len = model_info['source_len']
        source_min_y = model_info['source_min_y']

        if obj_model is None:
            visual = Entity(
                parent=ent,
                model='cube',
                scale=collider_scale,
                color=base,
                shader=lit_with_shadows_shader,
            )
            visual.vehicle_idx = idx
            ent.visual = visual
            return ent

        desired_len = 0.98 * float(v.length)
        s = self.vehicle_obj_base_scale * (desired_len / source_len)

        visual_mesh = self._clone_vehicle_mesh(obj_model)
        visual = Entity(parent=ent, model=(visual_mesh if visual_mesh is not None else 'cube'), shader=lit_with_shadows_shader, color=base)
        visual.vehicle_idx = idx
        visual.rotation_y = 90 if v.direction == Direction.VERTICAL else 0
        visual.scale = Vec3(s, s, s)
        visual.y = (-source_min_y * s) + 0.03
        ent.visual = visual
        return ent

    def _sync_vehicle_entities(self):
        for i, ent in self.vehicle_ent_by_idx.items():
            v = self.board.vehicles[i]
            r0, c0 = v.position // 6, v.position % 6

            if v.direction == Direction.HORIZONTAL:
                ent.position = self._cell_to_world(r0, c0 + (v.length - 1) / 2.0)
            else:
                ent.position = self._cell_to_world(r0 + (v.length - 1) / 2.0, c0)

            base = hex_to_ursina_color(v.color_hex)
            if i == self.selected_vehicle_idx:
                base = color.rgba(min(1.0, base.r + 0.15), min(1.0, base.g + 0.15), min(1.0, base.b + 0.15), 1)
            visual = getattr(ent, 'visual', None)
            if visual is None:
                ent.color = base
            else:
                visual.color = base
                visual._rest_color = base
                if getattr(visual, 'model', None) != 'cube' and self.vehicle_models.get(v.length, {}).get('model') is not None:
                    model_info = self.vehicle_models[v.length]
                    desired_len = 0.98 * float(v.length)
                    s = self.vehicle_obj_base_scale * (desired_len / model_info['source_len'])
                    visual.rotation_y = 90 if v.direction == Direction.VERTICAL else 0
                    visual.scale = Vec3(s, s, s)
                    visual.y = (-model_info['source_min_y'] * s) + 0.03
                visual._rest_y = float(getattr(visual, 'y', 0.0))

        self._update_hud()

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
            
        if getattr(self, '_active_hint_move', None) is not None:
            hint_v_idx, hint_new_pos = self._active_hint_move
            if self.selected_vehicle_idx == hint_v_idx:
                v = self.board.vehicles[hint_v_idx]
                cells = self._tutorial_path_cells(v, int(v.position), int(hint_new_pos))
                self._set_highlight_cells(cells, color.rgba(0.15, 0.75, 0.95, 0.35))
                return

        self._clear_highlights()

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
            ent.position = self._cell_to_world(r0, c0 + (v.length - 1) / 2.0)
        else:
            ent.position = self._cell_to_world(r0 + (v.length - 1) / 2.0, c0)

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
                self.status.color = color.rgba(0.62, 0.78, 0.70, 1)
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
        ent = self.vehicle_ent_by_idx.get(v_idx)
        old_pos = self.board.vehicles[v_idx].position
        self.move_history.append((v_idx, self.board.vehicles[v_idx].position))
        self.board.vehicles[v_idx].position = new_pos
        self.board.update_occupied()
        self.moves_count += 1
        self.selected_vehicle_idx = None
        self._active_hint_move = None
        self._beep('move')

        if ent is not None:
            v = self.board.vehicles[v_idx]
            r0, c0 = new_pos // 6, new_pos % 6
            if v.direction == Direction.HORIZONTAL:
                target = self._cell_to_world(r0, c0 + (v.length - 1) / 2.0)
            else:
                target = self._cell_to_world(r0 + (v.length - 1) / 2.0, c0)
            self._move_animating = True
            self._move_anim_end = pytime.perf_counter() + self._move_anim_duration
            ent.animate_position(target, duration=self._move_anim_duration, curve=curve.out_quad)
            invoke(self._finish_move_animation, v_idx, delay=self._move_anim_duration)
        else:
            self._sync_vehicle_entities()

        self._clear_preview_overlays()
        self._update_move_range_highlight()
        self._update_hud()
        self._tutorial_on_move(v_idx, old_pos, new_pos)

        if self.board.check_win():
            stars = self._stars_for_moves(self.moves_count, self.optimal_moves, self.level_elapsed)
            self._record_result(stars)
            self.status.text = f"{self._stars_text(stars)} Clear!"
            self.status.color = color.rgba(0.78, 0.72, 0.50, 1)
            self._show_toast("Great!", f"{self._stars_text(stars)}  Time {self._format_time(self.level_elapsed)}")
            if self.current_level_idx < len(self.level_data) - 1:
                next_idx = self.current_level_idx + 1
                invoke(self.load_level, next_idx, delay=0.9)
            else:
                invoke(self.show_end_screen, delay=0.9)

    def _finish_move_animation(self, v_idx):
        self._move_animating = False
        self._sync_vehicle_entities()

    def _record_result(self, stars):
        levels = self._save_data.setdefault('levels', {})
        key = str(self.current_level_idx)
        entry = levels.setdefault(key, {})
        t = float(self.level_elapsed)
        m = int(self.moves_count)
        if not isinstance(entry.get('best_time'), (int, float)) or t < float(entry.get('best_time')):
            entry['best_time'] = t
        if not isinstance(entry.get('best_moves'), int) or m < int(entry.get('best_moves')):
            entry['best_moves'] = m
        entry['last_time'] = t
        entry['last_moves'] = m
        entry['last_stars'] = int(stars)

        stats = self._save_data.setdefault('stats', {})
        cleared = stats.setdefault('levels_cleared', {})
        cleared.setdefault(key, {})
        cleared[key]['cleared'] = True
        if not self.hint_used_this_level:
            cleared[key]['cleared_without_hint'] = True
        if self.optimal_moves is not None and m == int(self.optimal_moves):
            cleared[key]['cleared_optimal'] = True

        if self.current_level_idx in (2, 3) and t <= 60.0:
            self._unlock_achievement('fast_hand', 'Quick Hands', 'Clear a hard level under 1:00')

        self._check_meta_achievements()
        self._save()

    def _check_meta_achievements(self):
        cleared = self._save_data.get('stats', {}).get('levels_cleared', {})
        if len(cleared.keys()) >= len(self.level_data):
            all_no_hint = all(cleared.get(str(i), {}).get('cleared_without_hint') for i in range(len(self.level_data)))
            if all_no_hint:
                self._unlock_achievement('no_hints', 'Hint-Proof', 'Clear all levels without using hints')

            all_opt = True
            for i in range(len(self.level_data)):
                opt = self._get_optimal_moves(i)
                best_moves = self._save_data.get('levels', {}).get(str(i), {}).get('best_moves')
                if opt is None or not isinstance(best_moves, int) or best_moves != int(opt):
                    all_opt = False
                    break
            if all_opt:
                self._unlock_achievement('perfectionist', 'Perfectionist', 'Clear all levels in optimal moves')

    def hide_end_screen(self):
        for attr in ('_end_screen_bg', '_end_screen_ui'):
            ent = getattr(self, attr, None)
            if ent is not None:
                destroy(ent)
                setattr(self, attr, None)

    def show_end_screen(self):
        self.hide_end_screen()
        self._end_screen_bg = Button(
            parent=camera.ui,
            color=color.rgba(0, 0, 0, 0.75),
            scale=(2.5, 1.5),
            z=0.05
        )
        self._end_screen_ui = Entity(parent=camera.ui, z=0.04)

        Button(
            parent=self._end_screen_ui,
            color=self.ui_bg,
            scale=(0.6, 0.4),
            radius=0.1
        )

        Text(
            "Congratulations!",
            parent=self._end_screen_ui,
            origin=(0, 0),
            y=0.10,
            scale=1.8,
            color=color.rgba(0.46, 0.38, 0.22, 1)
        )
        Text(
            "You have completed all levels.",
            parent=self._end_screen_ui,
            origin=(0, 0),
            y=0.02,
            scale=1.0,
            color=self.ui_text
        )

        btn_play_again = Button(
            text="Play Again",
            parent=self._end_screen_ui,
            scale=(0.25, 0.06),
            position=(0, -0.08),
            radius=0.5,
            color=color.rgba(self.btn_undo.r, self.btn_undo.g, self.btn_undo.b, 1),
            text_color=color.rgba(0, 0, 0, 0.98)
        )
        btn_play_again.highlight_color = btn_play_again.color
        btn_play_again.pressed_color = btn_play_again.color
        if getattr(btn_play_again, 'text_entity', None) is not None:
            btn_play_again.text_entity.enabled = True
            btn_play_again.text_entity.z = -0.10
        btn_play_again.z = 0.03
        self._set_button_label(btn_play_again, "Play Again", scale=0.6)

        def on_play_again():
            self.hide_end_screen()
            self._tutorial_active = False
            self.load_level(0)

        btn_play_again.on_click = on_play_again

    def _update(self):
        if self.is_ortho:
            camera.position = (0, self._ortho_height, 0)
            camera.rotation = (90, 0, 0)
            self._apply_ortho_lens()

            wheel = 0
            for attr in ('wheel_y', 'mouse_wheel', 'scroll_y'):
                try:
                    wheel = getattr(mouse, attr, 0)
                except Exception:
                    wheel = 0
                if wheel:
                    break
            if wheel:
                self._tutorial_on_zoom()
                if wheel > 0:
                    self._ortho_zoom = min(15.0, self._ortho_zoom * 1.10)
                else:
                    self._ortho_zoom = max(0.3, self._ortho_zoom / 1.10)
                self._apply_ortho_lens(force=True)

        if not self._move_animating:
            self.level_elapsed += u_time.dt
        if self._move_animating and pytime.perf_counter() >= self._move_anim_end:
            self._move_animating = False

        self._render_timer += u_time.dt
        if self._render_timer >= 0.15:
            self._update_hud()
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
                    self.status.color = color.rgba(0.62, 0.78, 0.70, 1)
                else:
                    self.status.text = f"Validation Failed | Max Deviation: {max_err:.8f}"
                    self.status.color = self.btn_validate
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
                minp = valid_positions[0]
                maxp = valid_positions[-1]
                best = min(valid_positions, key=lambda p: abs(p - desired))
                if best != self.drag_preview_pos:
                    self.drag_preview_pos = best
                    self._set_vehicle_preview(v_idx, best)
                    self._set_preview_cells(v.get_cells(best), color.rgba(0.95, 0.85, 0.15, 0.42))
                if steps != 0:
                    if desired < minp and best == minp:
                        self._trigger_shake()
                    elif desired > maxp and best == maxp:
                        self._trigger_shake()

        if self.drag_mode == 'rotate2d' and held_keys['left mouse']:
            dx = (mouse.x - self.last_mouse.x)
            self.rotation_y -= dx * 220
            self._count_rotation(abs(dx * 220))
            self.last_mouse = Vec2(mouse.x, mouse.y)
            self._sync_pivot_rotation()

        if (not self.is_ortho) and self.drag_mode == 'rotate' and held_keys['left mouse']:
            dx = (mouse.x - self.last_mouse.x)
            self.rotation_y -= dx * 220
            self._count_rotation(abs(dx * 220))
            self.last_mouse = Vec2(mouse.x, mouse.y)
            self._sync_pivot_rotation()

        if self.is_ortho and held_keys['right mouse']:
            if not self.is_rotating:
                self.is_rotating = True
                self.last_mouse = Vec2(mouse.x, mouse.y)
            dx = (mouse.x - self.last_mouse.x)
            self.rotation_y -= dx * 220
            self._count_rotation(abs(dx * 220))
            self.last_mouse = Vec2(mouse.x, mouse.y)
            self._sync_pivot_rotation()
        elif (not self.is_ortho) and held_keys['right mouse']:
            if not self.is_rotating:
                self.is_rotating = True
                self.last_mouse = Vec2(mouse.x, mouse.y)
            dx = (mouse.x - self.last_mouse.x)
            self.rotation_y -= dx * 220
            self._count_rotation(abs(dx * 220))
            self.last_mouse = Vec2(mouse.x, mouse.y)
            self._sync_pivot_rotation()
        else:
            self.is_rotating = False

        if self._toast_panel is not None and pytime.perf_counter() >= self._toast_until:
            panel = self._toast_panel
            self._toast_panel = None
            bg = panel.get('bg')
            border = panel.get('border')
            ui = panel.get('ui')
            try:
                if bg is not None:
                    bg.animate_color(color.rgba(bg.color.r, bg.color.g, bg.color.b, 0), duration=0.22, curve=curve.out_quad)
                    invoke(destroy, bg, delay=0.24)
                if border is not None:
                    border.animate_color(color.rgba(border.color.r, border.color.g, border.color.b, 0), duration=0.22, curve=curve.out_quad)
                    invoke(destroy, border, delay=0.24)
                if ui is not None:
                    invoke(destroy, ui, delay=0.24)
            except Exception:
                if bg is not None:
                    destroy(bg)
                if border is not None:
                    destroy(border)
                if ui is not None:
                    destroy(ui)

        if self.selected_vehicle_idx is not None:
            t = pytime.perf_counter()
            pulse = 1.0 + 0.08 * math.sin(t * self._select_pulse_speed)
            hover = self._select_hover_amp * (0.5 + 0.5 * math.sin(t * self._select_pulse_speed))
            for i, ent in self.vehicle_ent_by_idx.items():
                visual = getattr(ent, 'visual', None)
                if visual is None:
                    continue
                rest_y = getattr(visual, '_rest_y', float(getattr(visual, 'y', 0.0)))
                rest_c = getattr(visual, '_rest_color', getattr(visual, 'color', color.white))
                if i == self.selected_vehicle_idx:
                    visual.y = rest_y + hover
                    visual.color = self._pulse_color(rest_c, pulse)
                else:
                    visual.y = rest_y
                    visual.color = rest_c

        if not self.is_ortho:
            now = pytime.perf_counter()
            if now < self._camera_shake_until and self._camera_shake_strength > 0.0:
                remain = max(0.0, self._camera_shake_until - now)
                decay = min(1.0, remain / 0.16)
                s = self._camera_shake_strength * decay
                ox = random.uniform(-s, s)
                oy = random.uniform(-s, s)
                camera.position = self._camera_base_pos + Vec3(ox, oy, 0)
            else:
                self._camera_shake_strength = 0.0
                self._camera_shake_until = 0.0
                camera.position = self._camera_base_pos

        self._tutorial_update()

        self.last_render_ms = (pytime.perf_counter() - start) * 1000.0

    def _tutorial_seen(self):
        return False

    def _tutorial_mark_seen(self):
        return

    def _tutorial_maybe_start(self):
        if self.current_level_idx != 0:
            self._tutorial_stop(mark_seen=False)
            return
        if self._tutorial_active:
            return
        if self._tutorial_seen():
            return
        self._tutorial_start()

    def _tutorial_start(self):
        self._tutorial_active = True
        self._tutorial_step = 0
        self._tutorial_step_done = False
        self._tutorial_step_started_at = pytime.perf_counter()
        self._tutorial_rotate_ref = float(self.rotation_y)
        self._tutorial_target_vehicle_idx = self._tutorial_find_target_vehicle_idx()
        self._tutorial_layout = 'intro'
        self._tutorial_build_ui(layout='intro')
        self._tutorial_apply_step()

    def _tutorial_stop(self, mark_seen):
        if mark_seen:
            self._tutorial_mark_seen()
        self._tutorial_active = False
        self._tutorial_step = 0
        self._tutorial_step_done = False
        self._tutorial_clear_vehicle_highlight()
        self._tutorial_clear_grid_highlights()
        self._tutorial_clear_ui_highlights()
        self._tutorial_destroy_ui()

    def _tutorial_find_target_vehicle_idx(self):
        if self.board is None:
            return None
        for i, v in enumerate(self.board.vehicles):
            if getattr(v, 'is_target', False):
                return i
        return 0 if self.board.vehicles else None

    def _tutorial_build_ui(self, layout='intro'):
        self._tutorial_destroy_ui()
        self._tutorial_layout = layout
        scale = (0.36, 0.31)
        pos = (0.60, -0.29)  # Aligned to same left edge as top_panel (0.67 - 0.40/2 = 0.47). pos.x = 0.47 + 0.36/2 = 0.65
        
        # Align with top_panel left edge exactly
        # top_panel left = 0.67 - (0.40 / 2) = 0.47
        # tutorial left = pos_x - (0.40 / 2) = 0.47 -> pos_x = 0.67
        scale = (0.40, 0.31)
        pos = (0.67, -0.32)

        radius = 0.18
        base_z = 0.20

        border = Button(parent=camera.ui, text='', scale=(scale[0] + 0.003, scale[1] + 0.003), position=pos, color=self.ui_border, radius=radius)
        border.shader = unlit_shader
        border.collider = None
        border.z = base_z + 0.01

        panel = Button(parent=camera.ui, text='', scale=scale, position=pos, color=self.ui_bg, radius=radius)
        panel.shader = unlit_shader
        panel.collider = 'box'
        panel.z = base_z + 0.00

        ui = Entity(parent=camera.ui, position=pos)
        ui.z = base_z - 0.01

        pad_x = 0.03
        title_x = -(scale[0] / 2) + pad_x
        title_y = (scale[1] / 2) - 0.065
        body_y = title_y - 0.085
        btn_y = -(scale[1] / 2) + 0.055

        title = Text("", parent=ui, origin=(-0.5, 0), x=title_x, y=title_y, scale=1.05, color=color.rgba(0.46, 0.38, 0.22, 1))
        body = Text("", parent=ui, origin=(-0.5, 0), x=title_x, y=body_y, scale=0.76, color=self.ui_text)

        btn_skip = Button(text="Skip", parent=ui, scale=(0.080, 0.035), position=(scale[0] / 2 - 0.20, btn_y), radius=0.95)
        btn_skip.color = color.rgba(self.btn_neutral.r, self.btn_neutral.g, self.btn_neutral.b, 1)
        btn_skip.text_color = color.rgba(0, 0, 0, 0.98)
        btn_skip.highlight_color = btn_skip.color
        btn_skip.pressed_color = btn_skip.color
        btn_skip.text_size = 0.5
        btn_skip.highlight_text_size = 0.5
        btn_skip.highlight_text_color = btn_skip.text_color
        if getattr(btn_skip, 'text_entity', None) is not None:
            btn_skip.text_entity.enabled = True
            btn_skip.text_entity.z = -0.10
        btn_skip.z = -0.01
        btn_skip.on_click = lambda: self._tutorial_stop(mark_seen=True)
        self._set_button_label(btn_skip, "Skip", scale=0.52)

        btn_next_text = "Next" if layout == 'steps' else "Start Tutorial"
        btn_next_w = 0.120 if layout == 'steps' else 0.160
        btn_next = Button(text=btn_next_text, parent=ui, scale=(btn_next_w, 0.035), position=(scale[0] / 2 - 0.075, btn_y), radius=0.95)
        btn_next.color = color.rgba(self.btn_undo.r, self.btn_undo.g, self.btn_undo.b, 1)
        btn_next.text_color = color.rgba(0, 0, 0, 0.98)
        btn_next.highlight_color = btn_next.color
        btn_next.pressed_color = btn_next.color
        btn_next.text_size = 0.5
        btn_next.highlight_text_size = 0.5
        btn_next.highlight_text_color = btn_next.text_color
        if getattr(btn_next, 'text_entity', None) is not None:
            btn_next.text_entity.enabled = True
            btn_next.text_entity.z = -0.10
        btn_next.z = -0.01
        btn_next.on_click = (self._tutorial_next_clicked if layout == 'steps' else self._tutorial_start_clicked)
        self._set_button_label(btn_next, btn_next_text, scale=0.52)

        self._tutorial_panel_shadow = None
        self._tutorial_panel_border = border
        self._tutorial_panel = panel
        self._tutorial_ui = ui
        self._tutorial_title = title
        self._tutorial_body = body
        self._tutorial_btn_skip = btn_skip
        self._tutorial_btn_next = btn_next
        self._tutorial_flash_bg = None
        
        if layout == 'intro':
            flash_bg = Button(parent=camera.ui, text='', scale=scale, position=pos, color=color.rgba(1, 0.88, 0.25, 0), radius=radius)
            flash_bg.shader = unlit_shader
            flash_bg.collider = None
            flash_bg.z = panel.z - 0.005
            self._tutorial_flash_bg = flash_bg

    def _tutorial_destroy_ui(self):
        for e in (getattr(self, '_tutorial_panel', None), 
                  getattr(self, '_tutorial_panel_border', None), 
                  getattr(self, '_tutorial_panel_shadow', None),
                  getattr(self, '_tutorial_flash_bg', None)):
            if e is not None:
                destroy(e)
        if self._tutorial_ui is not None:
            destroy(self._tutorial_ui)
        self._tutorial_panel = None
        self._tutorial_panel_border = None
        self._tutorial_panel_shadow = None
        self._tutorial_ui = None
        self._tutorial_title = None
        self._tutorial_body = None
        self._tutorial_btn_next = None
        self._tutorial_btn_skip = None

    def _tutorial_start_clicked(self):
        if not self._tutorial_active:
            return
        if self._tutorial_step != 0:
            return
        self._tutorial_step = 1
        self._tutorial_step_done = False
        self._tutorial_step_started_at = pytime.perf_counter()
        self._tutorial_rotate_ref = float(self.rotation_y)
        self._tutorial_target_vehicle_idx = self._tutorial_find_target_vehicle_idx()
        self._tutorial_clear_vehicle_highlight()
        self._tutorial_clear_grid_highlights()
        self._tutorial_destroy_ui()
        self._tutorial_build_ui(layout='steps')
        self._tutorial_apply_step()

    def _tutorial_next_clicked(self):
        if not self._tutorial_active:
            return
        requires_action = self._tutorial_step in (1, 2, 3)
        if requires_action and not self._tutorial_step_done:
            self._show_toast("Complete this step first", "Do the action once, then click Next")
            return
        if self._tutorial_step >= 4:
            self._tutorial_stop(mark_seen=True)
            return
        self._tutorial_step += 1
        self._tutorial_step_done = False
        self._tutorial_step_started_at = pytime.perf_counter()
        self._tutorial_rotate_ref = float(self.rotation_y)
        self._tutorial_apply_step()

    def _tutorial_apply_step(self):
        if not self._tutorial_active:
            return
        self._tutorial_clear_ui_highlights()
        self._tutorial_clear_grid_highlights()
        self._tutorial_target_vehicle_idx = self._tutorial_find_target_vehicle_idx()

        if self._tutorial_step == 0:
            self._tutorial_set_text(
                "Tutorial (Level 1)",
                "Goal: move the red car\nto the red exit.\n\nThis quick tutorial teaches\nthe core controls.\n\nClick Start Tutorial\nto begin."
            )
            if self._tutorial_btn_next is not None:
                self._tutorial_btn_next.text = "Start Tutorial"
                self._set_button_label(self._tutorial_btn_next, "Start Tutorial", scale=0.42)
            self._tutorial_clear_vehicle_highlight()
            return

        if self._tutorial_step == 1:
            self._tutorial_move_target_pos = None
            self._tutorial_set_text(
                "Step 1 — Move the car",
                "Click the highlighted red car,\nthen drag it onto the\nhighlighted destination tiles."
            )
            if self._tutorial_btn_next is not None:
                self._tutorial_btn_next.text = "Next"
                self._set_button_label(self._tutorial_btn_next, "Next", scale=0.42)
            self._tutorial_set_vehicle_highlight(True)
            if self.board is not None and self._tutorial_target_vehicle_idx is not None:
                v = self.board.vehicles[self._tutorial_target_vehicle_idx]
                valid_positions = sorted(self._valid_positions_for_vehicle(v))
                if len(valid_positions) <= 1:
                    self._tutorial_move_target_pos = None
                    self._tutorial_step_done = True
                    self._show_toast("No move available", "Click Next to continue")
                elif valid_positions:
                    curr = int(v.position)
                    target_pos = valid_positions[0] if int(valid_positions[0]) != curr else int(valid_positions[-1])
                    self._tutorial_move_target_pos = int(target_pos)
                    road_cells = self._tutorial_path_cells(v, curr, int(target_pos))
                    self._tutorial_set_road_highlight(road_cells, color.rgba(0.15, 0.75, 0.95, 0.22))
                    self._tutorial_set_dest_highlight(v.get_cells(int(target_pos)), color.rgba(1.0, 0.88, 0.25, 0.35))
            return

        if self._tutorial_step == 2:
            self._tutorial_set_text(
                "Step 2 — Rotate the camera",
                "Click empty space,\nthen drag the mouse\nto rotate the view."
            )
            if self._tutorial_btn_next is not None:
                self._tutorial_btn_next.text = "Next"
                self._set_button_label(self._tutorial_btn_next, "Next", scale=0.42)
            self._tutorial_clear_vehicle_highlight()
            return

        if self._tutorial_step == 3:
            self._tutorial_set_text(
                "Step 3 — Zoom",
                "Use the mouse wheel\nto zoom in and out."
            )
            if self._tutorial_btn_next is not None:
                self._tutorial_btn_next.text = "Next"
                self._set_button_label(self._tutorial_btn_next, "Next", scale=0.42)
            return

        if self._tutorial_step == 4:
            self._tutorial_set_text(
                "Step 4 — Toggle View",
                "Press 'V' to switch between\n2D and 3D view."
            )
            if self._tutorial_btn_next is not None:
                self._tutorial_btn_next.text = "Finish"
                self._set_button_label(self._tutorial_btn_next, "Finish", scale=0.40)
            return
        self._tutorial_stop(mark_seen=True)

    def _tutorial_path_cells(self, v: Vehicle, start_pos: int, end_pos: int):
        if start_pos == end_pos:
            return list(v.get_cells(start_pos))
        step = 1 if v.direction == Direction.HORIZONTAL else 6
        s = step if end_pos > start_pos else -step
        cells = set()
        p = start_pos
        while True:
            cells.update(v.get_cells(p))
            if p == end_pos:
                break
            p += s
            if abs(p - start_pos) > 60:
                break
        return sorted(cells)

    def _tutorial_clear_grid_highlights(self):
        for e in self._tutorial_road_overlays:
            destroy(e)
        for e in self._tutorial_dest_overlays:
            destroy(e)
        self._tutorial_road_overlays = []
        self._tutorial_dest_overlays = []

    def _tutorial_set_road_highlight(self, cells, tint):
        for cell in sorted(set(cells)):
            tile = self.tile_by_cell.get(cell)
            if tile is None:
                continue
            overlay = Entity(
                parent=self.grid_parent,
                model='cube',
                position=tile.position + Vec3(0, 0.080, 0),
                scale=(0.985, 0.02, 0.985),
                color=tint,
                shader=unlit_shader,
            )
            overlay.collider = None
            self._tutorial_road_overlays.append(overlay)

    def _tutorial_set_dest_highlight(self, cells, tint):
        for cell in sorted(set(cells)):
            tile = self.tile_by_cell.get(cell)
            if tile is None:
                continue
            overlay = Entity(
                parent=self.grid_parent,
                model='cube',
                position=tile.position + Vec3(0, 0.105, 0),
                scale=(0.99, 0.02, 0.99),
                color=tint,
                shader=unlit_shader,
            )
            overlay.collider = None
            self._tutorial_dest_overlays.append(overlay)

    def _tutorial_set_text(self, title, body):
        if self._tutorial_title is not None:
            self._tutorial_title.text = title
        if self._tutorial_body is not None:
            self._tutorial_body.text = body

    def _tutorial_add_ui_highlight(self, target_btn):
        try:
            hl = Entity(parent=target_btn, model='quad', scale=(1.14, 1.65), color=color.rgba(1, 0.88, 0.25, 0.22), shader=unlit_shader)
            hl.z = -0.20
            hl.collider = None
        except Exception:
            return
        self._tutorial_ui_highlights.append(hl)

    def _tutorial_clear_ui_highlights(self):
        for e in self._tutorial_ui_highlights:
            destroy(e)
        self._tutorial_ui_highlights = []

    def _tutorial_set_vehicle_highlight(self, enabled):
        if not enabled:
            self._tutorial_clear_vehicle_highlight()
            return
        if self._tutorial_vehicle_highlight is not None:
            return
        idx = self._tutorial_target_vehicle_idx
        if idx is None:
            return
        ent = self.vehicle_ent_by_idx.get(idx)
        if ent is None:
            return
        try:
            hl = Entity(parent=ent, model='cube', scale=(1.08, 1.55, 1.12), color=color.rgba(1, 0.88, 0.25, 0.22), shader=unlit_shader)
            hl.y = 0.0
            hl.collider = None
        except Exception:
            return
        self._tutorial_vehicle_highlight = hl

    def _tutorial_clear_vehicle_highlight(self):
        if self._tutorial_vehicle_highlight is not None:
            destroy(self._tutorial_vehicle_highlight)
        self._tutorial_vehicle_highlight = None

    def _tutorial_on_move(self, v_idx, old_pos, new_pos):
        if not self._tutorial_active:
            return
        if self._tutorial_step == 1 and not self._tutorial_step_done:
            if self._tutorial_target_vehicle_idx is not None and v_idx == self._tutorial_target_vehicle_idx:
                target_pos = self._tutorial_move_target_pos
                if target_pos is not None and int(new_pos) == int(target_pos):
                    self._tutorial_step_done = True
                    self._show_toast("Nice!", "Click Next to continue")

    def _tutorial_on_zoom(self):
        if not self._tutorial_active:
            return
        if self._tutorial_step == 3 and not self._tutorial_step_done:
            self._tutorial_step_done = True
            self._show_toast("Great!", "Click Next to continue")

    def _tutorial_on_toggle_view(self):
        if not self._tutorial_active:
            return
        if self._tutorial_step == 4 and not self._tutorial_step_done:
            self._tutorial_step_done = True
            self._show_toast("Great!", "Click Finish to end the tutorial")

    def _tutorial_update(self):
        if not self._tutorial_active:
            return
        if self.current_level_idx != 0:
            self._tutorial_stop(mark_seen=False)
            return

        if self._tutorial_layout == 'intro' and getattr(self, '_tutorial_flash_bg', None):
            t = pytime.perf_counter() * 5.0
            alpha = (math.sin(t) * 0.5 + 0.5) * 0.35
            self._tutorial_flash_bg.color = color.rgba(1, 0.88, 0.25, alpha)

        if self._tutorial_step == 2 and not self._tutorial_step_done:
            if self.drag_mode in ('rotate', 'rotate2d') and held_keys['left mouse'] and abs(float(self.rotation_y) - float(self._tutorial_rotate_ref)) >= 12.0:
                self._tutorial_step_done = True
                self._show_toast("Good!", "Click Next to continue")

        if self._tutorial_step == 1:
            if self._tutorial_vehicle_highlight is None:
                self._tutorial_set_vehicle_highlight(True)
            if self._tutorial_vehicle_highlight is not None:
                t = pytime.perf_counter()
                pulse = 1.0 + 0.06 * math.sin(t * 4.0)
                a = 0.18 + 0.10 * (0.5 + 0.5 * math.sin(t * 4.0))
                self._tutorial_vehicle_highlight.scale_x = 1.08 * pulse
                self._tutorial_vehicle_highlight.scale_y = 1.55 * pulse
                self._tutorial_vehicle_highlight.scale_z = 1.12 * pulse
                self._tutorial_vehicle_highlight.color = color.rgba(1, 0.88, 0.25, a)
        else:
            self._tutorial_clear_vehicle_highlight()

    def _count_rotation(self, delta_degrees):
        stats = self._save_data.setdefault('stats', {})
        units = int(stats.get('rotation_units', 0))
        acc = float(units) * 10.0
        acc += float(delta_degrees)
        new_units = int(acc // 10.0)
        if new_units != units:
            stats['rotation_units'] = new_units
            stats['rotations'] = int(stats.get('rotations', 0)) + (new_units - units)
            self._save()
            if int(stats.get('rotations', 0)) >= 100:
                self._unlock_achievement('explorer', 'Explorer', 'Rotate the view 100 times')

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

