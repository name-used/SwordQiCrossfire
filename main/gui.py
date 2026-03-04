import io
import os
import random
import statistics
import tkinter as tk
import wave
import winsound
from tkinter import messagebox
from typing import List

from PIL import Image, ImageTk

from config import (
    EMPTY, BLACK, WHITE, black_color, black_name, white_color, white_name
)
from game import GameState


# ----- GUI -----
class SwordGoUI:
    def __init__(self, root: tk.Tk, N, black_stone_limit, black_five_ignore_suicide, ai_white, ai_black):
        self.root = root
        self.root.title("五子围棋之剑气纵横 (Toy)")
        self.N = N
        self.black_stone_limit = black_stone_limit
        self.black_five_ignore_suicide = black_five_ignore_suicide
        self.state = GameState.new(self.N, self.black_stone_limit, self.black_five_ignore_suicide)
        self.ai_white = ai_white
        self.ai_black = ai_black

        # 特效锁（播放期间不接受输入/AI）
        self.fx_running = False

        # 结算模式1：黑棋耗尽后，自动随机填满（白子）
        self.settle_filling = False
        self.settle_job = None
        self.settle_delay_ms = 200

        # === 背景图（必须与脚本同目录） ===
        self.bg_img = None
        self.bg_item = None
        self.grid_x: List[float] = []
        self.grid_y: List[float] = []
        self.cell = 42.0  # fallback
        self.size_w = 800
        self.size_h = 800

        img_path = os.path.join(os.path.dirname(__file__), f"sword_board_{self.N}x{self.N}.png")
        try:
            self.bg_img = tk.PhotoImage(file=img_path)
            self.size_w = int(self.bg_img.width())
            self.size_h = int(self.bg_img.height())
        except Exception as e:
            messagebox.showerror(
                "背景图加载失败",
                f"未能加载背景图：{img_path}\n\n请确认图片存在且为 PNG。\n错误：{e}"
            )
            raise

        # 让左侧(棋盘)随窗口伸缩
        root.grid_rowconfigure(0, weight=1)
        root.grid_columnconfigure(0, weight=1)

        # 让左侧(棋盘)随窗口伸缩
        root.grid_rowconfigure(0, weight=1)
        root.grid_columnconfigure(0, weight=1)

        # 先给一个合理初始窗口大小（你可以改）
        root.geometry("1080x760")

        # Canvas 改成可伸缩
        self.canvas = tk.Canvas(root, highlightthickness=0, bg="white")
        self.canvas.grid(row=0, column=0, rowspan=20, sticky="nsew")

        # === 读取原始背景图（不直接贴原尺寸）===
        img_path = os.path.join(os.path.dirname(__file__), f"sword_board_{self.N}x{self.N}.png")
        self.bg_pil0 = Image.open(img_path).convert("RGBA")
        self.bg_w0, self.bg_h0 = self.bg_pil0.size

        # 先占位一个 bg item（后面 resize 时会真正贴图）
        self.bg_img = None
        self.bg_item = self.canvas.create_image(0, 0, anchor="nw", tags=("bg",))

        # 先用原图做一次“校准”（得到原始网格交叉点像素坐标）
        self.size_w = self.bg_w0
        self.size_h = self.bg_h0
        self.bg_img_tmp = tk.PhotoImage(file=img_path)  # 给你现有扫描函数用
        self.bg_img = self.bg_img_tmp
        self._calibrate_grid_from_bg()

        # 保存一份“原始网格像素坐标”，后面缩放只做线性变换
        self.grid_x0 = self.grid_x[:]
        self.grid_y0 = self.grid_y[:]
        self.cell0 = float(self.cell)

        # resize 节流
        self._resize_job = None
        self.canvas.bind("<Configure>", self._on_canvas_resize)

        # ✅ 右侧固定宽度侧栏
        SIDE_W = 220
        self.side = tk.Frame(root, width=SIDE_W)
        self.side.grid(row=0, column=1, rowspan=20, sticky="nsew", padx=10, pady=10)
        # self.side.grid(row=0, column=1, sticky="ns", padx=10, pady=100)
        self.side.grid_propagate(False)

        # 让 side 内部只有 1 列，并且可拉伸（用于统一控件宽度）
        self.side.columnconfigure(0, weight=1)

        # side 内部：row0=信息栏，row1/row3=弹簧，row2=控制区（居中）
        self.side.grid_rowconfigure(0, weight=0)
        self.side.grid_rowconfigure(1, weight=1)
        self.side.grid_rowconfigure(2, weight=0)
        self.side.grid_rowconfigure(3, weight=1)

        # --- ✅ 固定高度信息栏（不再挤按钮） ---
        INFO_H = 260
        self.info_box = tk.Frame(self.side, height=INFO_H)
        # self.info_box.grid(row=0, column=0, sticky="ew")
        self.info_box.grid(row=0, column=0, sticky="ew", pady=(80, 0))
        self.info_box.grid_propagate(False)

        self.info = tk.StringVar()
        self.info_label = tk.Label(
            self.info_box,
            textvariable=self.info,
            justify="left", anchor="nw",
            font=("Consolas", 11),
            wraplength=SIDE_W - 20
        )
        # 填满固定框：信息再多也不会改变高度
        self.info_label.place(x=0, y=0, relwidth=1, relheight=1)

        # --- ✅ 控制区：整体放在中间，单列等宽对齐 ---
        self.ctrl = tk.Frame(self.side)
        self.ctrl.grid(row=2, column=0, sticky="ew")
        self.ctrl.columnconfigure(0, weight=1)

        BTN_W = 18  # 视觉等宽；若你更喜欢 “铺满”，也可以去掉 width，改 sticky="ew"

        def _grid_widget(w, r, pady=(2, 0)):
            w.grid(row=r, column=0, sticky="w", pady=pady)

        # Pass
        _grid_widget(tk.Button(self.ctrl, text="Pass（停一手）", width=BTN_W, command=self.pass_turn), 0, pady=(0, 8))

        # 结算 / 重开
        _grid_widget(tk.Button(self.ctrl, text="结算/比分", width=BTN_W, command=self.show_score), 1)
        _grid_widget(tk.Button(self.ctrl, text="重开", width=BTN_W, command=self.restart), 2, pady=(2, 10))

        # AI 模式
        # self.ai_var = tk.StringVar(value="Human vs Human")
        self.ai_var = tk.StringVar(value="Human Black vs AI White")
        ai_menu = tk.OptionMenu(
            self.ctrl, self.ai_var,
            "Human vs Human", "Human Black vs AI White", "AI Black vs Human White", "AI Black vs AI White",
            command=lambda *_: self.root.after_idle(self._trigger_ai_if_needed)
        )
        ai_menu.config(width=BTN_W)
        _grid_widget(ai_menu, 3, pady=(0, 10))

        # Board 尺寸
        self.board_sizes = (13, 15, 17)
        self.board_var = tk.IntVar(value=self.N)

        _grid_widget(tk.Label(self.ctrl, text="Board", font=("Consolas", 10)), 4, pady=(0, 2))

        board_menu = tk.OptionMenu(self.ctrl, self.board_var, *self.board_sizes, command=self.on_board_change)
        board_menu.config(width=BTN_W)
        _grid_widget(board_menu, 5, pady=(0, 0))

        # 黑棋棋子上限（仅限制先手/五子棋方）：50~150，松手即重开
        _grid_widget(tk.Label(self.ctrl, text=f"{black_name}上限", font=("Consolas", 10)), 6, pady=(10, 2))
        self.black_limit_var = tk.IntVar(value=self.state.black_stone_limit)
        self.black_limit_scale = tk.Scale(
            self.ctrl,
            from_=50, to=150,
            orient="horizontal",
            length=160,
            showvalue=True,
            variable=self.black_limit_var,
            resolution=1
        )
        self.black_limit_scale.grid(row=7, column=0, sticky="w")
        self.black_limit_scale.bind("<ButtonRelease-1>", self._on_black_limit_release)

        # 落子规范
        self.black_five_ignore_var = tk.BooleanVar(value=self.black_five_ignore_suicide)
        chk = tk.Checkbutton(
            self.ctrl,
            text="成五落子无视围棋绝地",
            variable=self.black_five_ignore_var,
            command=self._on_toggle_black_five
        )
        chk.config(width=BTN_W, anchor="w")
        _grid_widget(chk, 8, pady=(0, 10))

        # 立刻做一次初始适配
        self._apply_canvas_resize(self.canvas.winfo_width(), self.canvas.winfo_height())

        self.canvas.bind("<Button-1>", self.on_click_left)  # 落子
        self.canvas.bind("<Button-3>", self.on_click_right)  # Pass

        self.redraw()
        # self.root.after(50, self._warmup_audio)  # 50ms 后预热，避免和初始化抢时序
        # self.root.after(50, lambda: self._warmup_audio(seconds=0.3))
        self.root.after(200, self._warmup_audio_file)
        # 有些机器更玄学：再补一次“二段预热”更稳
        self.root.after(800, self._warmup_audio_file)

        self._suspend_resize = False

        # AI 启动
        self.root.after_idle(self._trigger_ai_if_needed)
        self.ai_jobs = set()

    def after_tracked(self, ms, fn):
        jid = None

        def _wrapped():
            # 执行时自动清理
            self.ai_jobs.discard(jid)
            fn()

        jid = self.root.after(ms, _wrapped)
        self.ai_jobs.add(jid)
        return jid

    # ---------- 背景网格自动校准 ----------
    @staticmethod
    def _is_dark(color) -> bool:
        # tkinter PhotoImage.get 可能返回 "#RRGGBB" 或 "r g b" 或 "black"
        if isinstance(color, (tuple, list)) and len(color) >= 3:
            r, g, b = int(color[0]), int(color[1]), int(color[2])
            return (r < 80) and (g < 80) and (b < 80)

        if not isinstance(color, str):
            return False

        s = color.strip().lower()
        if s == "black":
            return True
        if s.startswith("#") and len(s) == 7:
            try:
                r = int(s[1:3], 16)
                g = int(s[3:5], 16)
                b = int(s[5:7], 16)
                return (r < 80) and (g < 80) and (b < 80)
            except Exception:
                return False
        if " " in s:
            parts = s.split()
            if len(parts) >= 3:
                try:
                    r, g, b = int(parts[0]), int(parts[1]), int(parts[2])
                    return (r < 80) and (g < 80) and (b < 80)
                except Exception:
                    return False
        return False

    def _find_line_centers_1d(self, axis: str) -> List[float]:
        """
        在图片里找出网格线的中心 x(或y) 像素坐标。
        axis='x' => 找竖线；axis='y' => 找横线
        """
        w, h = self.size_w, self.size_h
        step = 2  # 采样步长（越小越准，但更慢）
        samples = 45

        if axis == "x":
            idx_max = w
            # 取多条 y 采样（避开上下边缘）
            ys = [int(h * (0.15 + 0.7 * i / (samples - 1))) for i in range(samples)]
            counts = []
            for x in range(0, idx_max, step):
                cnt = 0
                for y in ys:
                    if self._is_dark(self.bg_img.get(x, y)):
                        cnt += 1
                counts.append(cnt)
        else:
            idx_max = h
            xs = [int(w * (0.15 + 0.7 * i / (samples - 1))) for i in range(samples)]
            counts = []
            for y in range(0, idx_max, step):
                cnt = 0
                for x in xs:
                    if self._is_dark(self.bg_img.get(x, y)):
                        cnt += 1
                counts.append(cnt)

        maxc = max(counts) if counts else 0
        if maxc <= 0:
            return []

        # 尝试多档阈值，找到至少 N 条“强线”
        thresholds = [0.88, 0.84, 0.80, 0.76, 0.72, 0.68, 0.64, 0.60]
        best_groups = None
        best_thr = None

        for t in thresholds:
            thr = max(3, int(maxc * t))
            hot = [i for i, v in enumerate(counts) if v >= thr]
            if not hot:
                continue

            groups = []
            start = hot[0]
            prev = hot[0]
            for i in hot[1:]:
                if i == prev + 1:
                    prev = i
                else:
                    groups.append((start, prev))
                    start = prev = i
            groups.append((start, prev))

            if len(groups) >= self.N:
                best_groups = groups
                best_thr = thr
                break

        if best_groups is None:
            return []

        # 每个 group 计算中心，并按强度挑前 N 个（避免文字/花心格噪声）
        group_infos = []
        for a, b in best_groups:
            # center in pixel
            center = (a + b) / 2.0 * step
            strength = sum(counts[a:b + 1]) / (b - a + 1)
            group_infos.append((strength, center))

        group_infos.sort(key=lambda x: x[0], reverse=True)
        picked = group_infos[:self.N]
        centers = sorted([c for _, c in picked])
        return centers

    def _calibrate_grid_from_bg(self):
        cx = self._find_line_centers_1d("x")
        cy = self._find_line_centers_1d("y")

        if len(cx) == self.N and len(cy) == self.N:
            self.grid_x = cx
            self.grid_y = cy
            diffs = [self.grid_x[i + 1] - self.grid_x[i] for i in range(self.N - 1)]
            self.cell = float(statistics.median(diffs))
            return

        # fallback：按“尽量铺满画布”的均匀网格（如果识别失败也能用）
        margin = 40
        usable_w = self.size_w - 2 * margin
        usable_h = self.size_h - 2 * margin
        cell = min(usable_w, usable_h) / (self.N - 1)
        self.cell = float(cell)
        self.grid_x = [margin + i * cell for i in range(self.N)]
        self.grid_y = [margin + i * cell for i in range(self.N)]

    def _on_canvas_resize(self, event):
        # resize 事件会很频繁，做个节流
        if event.width < 50 or event.height < 50:
            return
        # resize 事件会很频繁，做个节流
        if event.width < 50 or event.height < 50:
            return
        if getattr(self, "_suspend_resize", False):
            return
        if self._resize_job is not None:
            self.root.after_cancel(self._resize_job)
        self._resize_job = self.root.after(40, lambda: self._apply_canvas_resize(event.width, event.height))

    def _apply_canvas_resize(self, cw: int, ch: int):
        self._resize_job = None

        # 棋盘是正方形：取较小边作为贴图大小，并居中
        side = max(200, min(cw, ch))
        s = side / self.bg_w0  # 原图->新图缩放比例（你的图是正方形，w0==h0）

        dx = (cw - side) / 2.0
        dy = (ch - side) / 2.0

        # 生成缩放后的背景
        bg = self.bg_pil0.resize((side, side), Image.LANCZOS)
        self.bg_img = ImageTk.PhotoImage(bg)

        # 更新 canvas 上的背景图
        self.canvas.itemconfig(self.bg_item, image=self.bg_img)
        self.canvas.coords(self.bg_item, dx, dy)

        # 同步缩放网格映射（关键：棋子/落点对齐）
        self.grid_x = [dx + x * s for x in self.grid_x0]
        self.grid_y = [dy + y * s for y in self.grid_y0]
        self.cell = self.cell0 * s

        # 让特效用当前 canvas 尺寸
        self.size_w = cw
        self.size_h = ch

        # 重新画棋子/红点（不要删 bg）
        self.redraw()

    # ---------- 交互 ----------
    def _beep(self):
        # Windows 下尽量用 MessageBeep，避免 Tk 的 visual bell 造成“闪一下/抖一下”的观感
        try:
            winsound.MessageBeep()
            return
        except Exception:
            pass
        try:
            self.root.bell()
        except Exception:
            pass

    def restart(self):
        if self.fx_running:
            return

        while self.ai_jobs:
            try:
                self.root.after_cancel(self.ai_jobs.pop())
            except Exception:
                pass
        # self.redraw()
        self.settle_filling = False

        self.state = GameState.new(self.N, self.black_stone_limit, self.black_five_ignore_suicide)

        # ✅ 统一走 resize->redraw 的路径：避免切盘/重开时“网格坐标未按当前 canvas 同步”引发错位/异常
        try:
            self.canvas.update_idletasks()
        except Exception:
            pass
        cw = max(200, int(self.canvas.winfo_width()))
        ch = max(200, int(self.canvas.winfo_height()))
        self.root.after(120, self._apply_canvas_resize(cw, ch))  # 内部会 redraw()

        self.root.after_idle(self._trigger_ai_if_needed)

    def pass_turn(self):
        if self.fx_running:
            return
        if self.state.is_over():
            self.show_score()
            return
        self.play_and_fx(None)
        self.maybe_ai_move()

    def on_click_right(self, _):
        self.pass_turn()

    def on_click_left(self, event):
        if self.fx_running or self.settle_filling:
            return
        if self.state.is_over():
            self.show_score()
            return

        r, c = self.pixel_to_rc(event.x, event.y)
        if r is None:
            return

        # Human move only when it's human's turn under current mode
        mode = self.ai_var.get()
        if mode == "Human Black vs AI White" and self.state.turn == WHITE:
            return
        if mode == "AI Black vs Human White" and self.state.turn == BLACK:
            return
        if mode == "AI Black vs AI White":
            return

        try:
            self.play_and_fx((r, c))
        except Exception as e:
            self._beep()
            self.info.set(self.info.get().split("\n\n")[0] + "\n\n" + str(e))
            return

        self._post_move_checks()
        if (not self.settle_filling) and (not self.state.is_over()):
            self.after_tracked(200, self.maybe_ai_move)

    def _trigger_ai_if_needed(self):
        self.after_tracked(500, self.maybe_ai_move)

    def maybe_ai_move(self):
        if self.fx_running:
            # 特效期间，稍后再试
            self.after_tracked(60, self.maybe_ai_move)
            return
        if self.settle_filling:
            return

        mode = self.ai_var.get()
        if self.state.is_over():
            return

        if mode == "Human vs Human":
            return

        if mode == "Human Black vs AI White" and self.state.turn == WHITE:
            self.play_and_fx(self.ai_white(self.state))
            self._post_move_checks()
            return

        if mode == "AI Black vs Human White" and self.state.turn == BLACK:
            self.play_and_fx(self.ai_black(self.state))
            self._post_move_checks()
            return

        if mode == "AI Black vs AI White":
            if self.state.turn == BLACK:
                self.play_and_fx(self.ai_black(self.state))
            else:
                self.play_and_fx(self.ai_white(self.state))
            self._post_move_checks()
            if (not self.state.is_over()) and (not self.settle_filling):
                self.after_tracked(400, self.maybe_ai_move)
            return

    def on_board_change(self, val):
        # OptionMenu 传进来通常是 str
        self.set_board_size(int(val))

    def _on_black_limit_release(self, _event=None):
        """拖动条松手：同步黑棋棋子上限，并直接重开。"""
        try:
            val = int(self.black_limit_var.get())
        except Exception:
            return
        self.set_black_limit(val)

    def _on_toggle_black_five(self):
        if self.fx_running:
            return
        self.black_five_ignore_suicide = bool(self.black_five_ignore_var.get())
        self.restart()

    def set_black_limit(self, new_limit: int):
        if self.fx_running:
            return
        try:
            new_limit = int(new_limit)
        except Exception:
            return
        new_limit = max(50, min(150, new_limit))
        if new_limit == self.state.black_stone_limit:
            return

        self.black_stone_limit = new_limit
        try:
            self.black_limit_var.set(new_limit)
        except Exception:
            pass
        self.restart()

    def set_board_size(self, new_n: int):
        """切换 13/15/17：重新加载底图&网格标定，然后复用 restart 的刷新链路。"""
        if self.fx_running:
            return
        if new_n == self.N:
            return
        if new_n not in (13, 15, 17):
            return

        # 暂停 Configure->resize，避免半更新状态被拿去缩放/重绘
        self._suspend_resize = True
        try:
            if self._resize_job is not None:
                self.root.after_cancel(self._resize_job)
        except Exception:
            pass
        self._resize_job = None
        self.N = new_n
        try:
            self.board_var.set(new_n)
        except Exception:
            pass

        img_path = os.path.join(os.path.dirname(__file__), f"sword_board_{self.N}x{self.N}.png")

        # 更新“原始底图”(PIL)：给 _apply_canvas_resize 用
        self.bg_pil0 = Image.open(img_path).convert("RGBA")
        self.bg_w0, self.bg_h0 = self.bg_pil0.size

        # 用 tk.PhotoImage 做一次扫描校准（_calibrate_grid_from_bg 依赖 PhotoImage.get）
        self.size_w = self.bg_w0
        self.size_h = self.bg_h0
        self.bg_img_tmp = tk.PhotoImage(file=img_path)
        self.bg_img = self.bg_img_tmp
        self._calibrate_grid_from_bg()

        # 保存“原始网格坐标”，供缩放线性变换
        self.grid_x0 = self.grid_x[:]
        self.grid_y0 = self.grid_y[:]
        self.cell0 = float(self.cell)

        self.root.title(f"五子围棋之剑气纵横 (Toy) - {self.N}x{self.N}")

        self._suspend_resize = False
        self.restart()

    # ---------- 坐标映射（基于校准后的 grid_x/grid_y） ----------

    def pixel_to_rc(self, x: int, y: int):
        if not self.grid_x or not self.grid_y:
            return None, None

        # 找最近的交叉点
        c = min(range(self.N), key=lambda i: abs(self.grid_x[i] - x))
        r = min(range(self.N), key=lambda i: abs(self.grid_y[i] - y))

        px = self.grid_x[c]
        py = self.grid_y[r]
        if abs(px - x) > self.cell * 0.35 or abs(py - y) > self.cell * 0.35:
            return None, None
        return r, c

    def rc_to_pixel(self, r: int, c: int):
        return self.grid_x[c], self.grid_y[r]

    # ---------- UI ----------

    def _playable_empty_count(self) -> int:
        # 可落子空位数：不统计剑气格（剑气格已算进黑结算）
        cnt = 0
        for r in range(self.N):
            for c in range(self.N):
                if self.state.board[r][c] == EMPTY and (not self.state.is_white_forbidden(r, c)):
                    cnt += 1
        return cnt

    def _show_score_popup(self):
        b, w = self.state.score()
        e = self._playable_empty_count()
        msg = f"""{black_name}: {b}
{white_name}: {w}
可落子空位：{e}

胜者: {black_name if b > w else (white_name if w > b else '平局')}"""
        messagebox.showinfo("比分", msg)

    def _start_settle_mode1_if_needed(self) -> bool:
        """黑棋棋子耗尽 => 结算模式1：自动随机填子到无法落子。"""
        if self.settle_filling:
            return True
        if self.state.stones_left(BLACK) > 0:
            return False

        # 若白已无合法落点（已经填到头/只剩剑气格），直接弹窗
        if not self.state.legal_moves(WHITE):
            self._show_score_popup()
            return True

        self.settle_filling = True
        # 延迟一点点，给 UI 刷新/特效收尾
        self.settle_job = self.root.after(self.settle_delay_ms, self._settle_fill_step)
        return True

    def _settle_fill_step(self):
        if not self.settle_filling:
            return

        # 特效期间先别动（避免与动画/音效并发）
        if self.fx_running:
            self.settle_job = self.root.after(self.settle_delay_ms, self._settle_fill_step)
            return

        # 模式1：只让白反复落子（不走 AI，不 Pass，不触发连续 pass 终局）
        try:
            self.state.consecutive_passes = 0
        except Exception:
            pass
        try:
            self.state.turn = WHITE
        except Exception:
            pass

        legal = self.state.legal_moves(WHITE)
        if not legal:
            self.settle_filling = False
            self.settle_job = None
            self._show_score_popup()
            return

        mv = random.choice(legal)
        try:
            self.state.play(mv)
        except Exception:
            # 极小概率竞态/非法：再试一次
            self.settle_job = self.root.after(1, self._settle_fill_step)
            return

        self.redraw()
        self.settle_job = self.root.after(self.settle_delay_ms, self._settle_fill_step)

    def _post_move_checks(self):
        # 优先模式1
        if self._start_settle_mode1_if_needed():
            return
        # 模式2：双方不下/点击结算/棋盘满 => 直接结算弹窗
        if self.state.is_over():
            self._show_score_popup()

    def show_score(self):
        # 如果黑棋耗尽 => 先走结算模式1
        if self._start_settle_mode1_if_needed():
            return
        # 否则模式2：直接弹窗
        self._show_score_popup()

    def redraw(self):
        # 不要 delete("all")，否则背景会被删
        self.canvas.delete("marks")
        self.canvas.delete("stones")
        # fx 不删，让动画自己删（也避免一落子把特效刷掉）

        # 白禁入空点（红点）
        dot = max(5, round(self.cell * 0.15))
        ring = max(3, round(dot * 0.65))
        for r in range(self.N):
            for c in range(self.N):
                if self.state.is_white_forbidden(r, c):
                    x, y = self.rc_to_pixel(r, c)
                    self.canvas.create_oval(
                        x - dot, y - dot, x + dot, y + dot,
                        fill="#d4af37", outline="#b22222", width=ring, tags=("marks",)
                    )

        # 落子
        rad = max(12, int(self.cell * 0.36))
        for r in range(self.N):
            for c in range(self.N):
                v = self.state.board[r][c]
                if v == EMPTY:
                    continue
                x, y = self.rc_to_pixel(r, c)
                if v == BLACK:
                    self.canvas.create_oval(
                        x - rad, y - rad, x + rad, y + rad,
                        fill=black_color, outline="#000", tags=("stones",)
                    )
                    if self.state.is_black_immune(r, c):
                        self.canvas.create_oval(
                            x - rad + 3, y - rad + 3, x + rad - 3, y + rad - 3,
                            outline="#d4af37", width=2, tags=("stones",)
                        )
                else:
                    self.canvas.create_oval(
                        x - rad, y - rad, x + rad, y + rad,
                        fill=white_color, outline="#000", tags=("stones",)
                    )

        turn = black_name if self.state.turn == BLACK else white_name
        b_left = self.state.stones_left(BLACK)
        w_left = self.state.stones_left(WHITE)
        claimed = len(self.state.claimed)
        b_sc, w_sc = self.state.score()
        e_sc = self._playable_empty_count()

        lines = [
            f"回合: {turn}",
            f"{black_name}剩余棋子: {b_left}",
            f"{white_name}剩余棋子：不限",
            f"已触发剑气线: {claimed}",
            f"【结算】{b_sc} ： {w_sc} ： {e_sc}",
            "",
            "操作",
            "左键落子",
            "右键Pass",
            f"红点={white_name}禁入空点",
            f"{black_name}子金圈=剑气免提",
        ]
        if self.state.is_over():
            lines.insert(3, f"【已结束】{black_name} {b_sc} : {white_name} {w_sc}")
        self.info.set("\n".join(lines))

    # ---------- 特效 ----------
    def play_and_fx(self, move):
        """执行一步（含落子/提子/触发剑气），并在触发新剑气线时播放特效。"""
        old_claimed = set(self.state.claimed)
        old_board = [row[:] for row in self.state.board]

        self.state.play(move)
        self.redraw()

        new_lines = list(self.state.claimed - old_claimed)

        # ✅ 普通落子：播放落子音
        # move is None 表示 Pass，不播
        if move is not None and not new_lines:
            self._play_place_sound()

        if not new_lines:
            return

        removed_whites = []
        for lid in new_lines:
            for rr, cc in self.state.line_points[lid]:
                if old_board[rr][cc] == WHITE:
                    removed_whites.append((rr, cc))

        # ✅ 触发剑气：animate_sword 内部会播放 sword.wav
        self.animate_sword(new_lines, removed_whites)

    def _line_endpoints(self, lid):
        pts = self.state.line_points[lid]
        # 找到对应该线的两个端点（按“从小到大”排序取首尾）
        if lid[0] == 'H':
            pts2 = sorted(pts, key=lambda p: p[1])
        elif lid[0] == 'V':
            pts2 = sorted(pts, key=lambda p: p[0])
        elif lid[0] == 'D1':  # r-c 固定，按 r 增
            pts2 = sorted(pts, key=lambda p: p[0])
        else:  # 'D2' r+c 固定，按 r 增
            pts2 = sorted(pts, key=lambda p: p[0])

        (r0, c0), (r1, c1) = pts2[0], pts2[-1]
        x0, y0 = self.rc_to_pixel(r0, c0)
        x1, y1 = self.rc_to_pixel(r1, c1)
        return x0, y0, x1, y1

    def _play_place_sound(self):
        """播放落子音效：优先 place*.wav（与脚本同目录），失败则 bell。"""
        base = os.path.dirname(__file__)
        cands = ["place.wav", "place1.wav", "place2.wav", "place3.wav"]
        wavs = [os.path.join(base, n) for n in cands if os.path.exists(os.path.join(base, n))]

        try:
            if wavs:
                winsound.PlaySound(random.choice(wavs), winsound.SND_FILENAME | winsound.SND_ASYNC)
            else:
                winsound.MessageBeep()
        except Exception:
            try:
                # self.root.bell()
                self._beep()
            except Exception:
                pass

    def _play_sword_sound(self):
        """播放剑气音效：优先 sword.wav（与脚本同目录），失败则 bell。"""
        wav = os.path.join(os.path.dirname(__file__), "sword.wav")
        try:
            if os.path.exists(wav):
                winsound.PlaySound(wav, winsound.SND_FILENAME | winsound.SND_ASYNC)
            else:
                winsound.MessageBeep()
        except Exception:
            try:
                # self.root.bell()
                self._beep()
            except Exception:
                pass

    def animate_sword(self, new_lines, removed_whites):
        """剑气纵横特效：发光线 + 粒子扫线 + 白子爆散 + 音效。"""
        self.fx_running = True

        # 音效：优先播放 sword.wav（与脚本同目录），失败再兜底 bell
        self._play_sword_sound()

        fx_tag = f"fx_{random.randint(0, 10 ** 9)}"

        # 文字提示
        cx = self.size_w // 2
        cy = 32
        title = self.canvas.create_text(
            cx, cy, text="剑气纵横！", font=("Microsoft YaHei", 20, "bold"),
            fill="#8b0000", tags=(fx_tag, "fx")
        )

        # 发光线（多层描边假装 glow）
        line_items = []
        for lid in new_lines:
            x0, y0, x1, y1 = self._line_endpoints(lid)
            o1 = self.canvas.create_line(
                x0, y0, x1, y1, width=18, fill="#ffd700",
                capstyle="round", tags=(fx_tag, "fx")
            )
            o2 = self.canvas.create_line(
                x0, y0, x1, y1, width=10, fill="#ff8c00",
                capstyle="round", tags=(fx_tag, "fx")
            )
            o3 = self.canvas.create_line(
                x0, y0, x1, y1, width=4, fill="#fffacd",
                capstyle="round", tags=(fx_tag, "fx")
            )
            line_items.append((o1, o2, o3))

        # 白子虚影缩小
        ghost_items = []
        base_rad = max(12, int(self.cell * 0.36))
        for r, c in removed_whites:
            x, y = self.rc_to_pixel(r, c)
            g = self.canvas.create_oval(
                x - base_rad, y - base_rad, x + base_rad, y + base_rad,
                fill="#f8f8ff", outline="", tags=(fx_tag, "fx")
            )
            ghost_items.append((g, x, y))

        # 粒子沿线扫过
        particles = []
        for lid in new_lines:
            x0, y0, x1, y1 = self._line_endpoints(lid)
            for i in range(10):
                p = self.canvas.create_oval(0, 0, 0, 0, fill="#fffacd", outline="", tags=(fx_tag, "fx"))
                particles.append((p, x0, y0, x1, y1, i / 10.0))

        total_frames = 18
        frame_ms = 30

        def step(frame: int):
            self.canvas.move(title, 0, -1)

            pulse = (frame if frame <= total_frames // 2 else total_frames - frame)
            w_outer = 18 + pulse
            w_mid = 10 + pulse * 0.6
            w_core = 4 + pulse * 0.3
            for o1, o2, o3 in line_items:
                self.canvas.itemconfig(o1, width=w_outer)
                self.canvas.itemconfig(o2, width=w_mid)
                self.canvas.itemconfig(o3, width=w_core)

            if ghost_items:
                scale = max(0.0, 1.0 - frame / total_frames)
                rad = base_rad * scale
                for g, x, y in ghost_items:
                    self.canvas.coords(g, x - rad, y - rad, x + rad, y + rad)

            speed = 0.09
            pr = 3
            for idx in range(len(particles)):
                p, x0, y0, x1, y1, t = particles[idx]
                t2 = t + speed
                particles[idx] = (p, x0, y0, x1, y1, t2)
                if t2 > 1.0:
                    self.canvas.coords(p, -10, -10, -10, -10)
                    continue
                x = x0 + (x1 - x0) * t2
                y = y0 + (y1 - y0) * t2
                self.canvas.coords(p, x - pr, y - pr, x + pr, y + pr)

            if frame < total_frames:
                self.root.after(frame_ms, lambda: step(frame + 1))
            else:
                self.canvas.delete(fx_tag)
                self.fx_running = False

        step(0)

    def _warmup_audio(self, seconds: float = 1.0, sr: int = 44100):
        """播放一段静音 WAV 以预热 winsound（无可闻声音）。"""
        if getattr(self, "_audio_warmed", False):
            return
        self._audio_warmed = True

        try:
            # 先 purge 一下（无声）
            try:
                winsound.PlaySound(None, winsound.SND_PURGE)
            except Exception:
                pass

            # 生成 16-bit PCM mono 的静音 wav（内存）
            nframes = int(seconds * sr)
            buf = io.BytesIO()
            with wave.open(buf, "wb") as wf:
                wf.setnchannels(1)
                wf.setsampwidth(2)  # 16-bit
                wf.setframerate(sr)
                wf.writeframes(b"\x00\x00" * nframes)

            # ⚠️ 必须把 bytes 缓存在对象上，避免播放时被 GC
            self._silence_wav_bytes = buf.getvalue()

            winsound.PlaySound(
                self._silence_wav_bytes,
                winsound.SND_MEMORY | winsound.SND_ASYNC
            )
        except Exception:
            # 非 Windows / winsound 不可用时，直接跳过
            pass

    def _ensure_silence_wav(self, seconds: float = 1.0, sr: int = 44100) -> str:
        """生成一个 1 秒静音 wav 文件（只生成一次），返回路径。"""
        base = os.path.dirname(__file__)
        path = os.path.join(base, "__silence_1s.wav")

        if os.path.exists(path):
            return path

        nframes = int(seconds * sr)
        with wave.open(path, "wb") as wf:
            wf.setnchannels(1)  # mono
            wf.setsampwidth(2)  # 16-bit PCM
            wf.setframerate(sr)
            wf.writeframes(b"\x00\x00" * nframes)

        return path

    def _warmup_audio_file(self):
        """用静音 wav 预热 winsound（无可闻声音）。"""
        if getattr(self, "_audio_warmed", False):
            return
        self._audio_warmed = True

        try:
            wav = self._ensure_silence_wav(seconds=1.0)

            # 清一下旧播放（无声）
            try:
                winsound.PlaySound(None, winsound.SND_PURGE)
            except Exception:
                pass

            winsound.PlaySound(wav, winsound.SND_FILENAME | winsound.SND_ASYNC)

        except Exception:
            pass
