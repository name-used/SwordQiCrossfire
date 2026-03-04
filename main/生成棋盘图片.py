import math

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.lines import Line2D

def make_board_png(N, out_path, dpi=240):
    assert N % 2 == 1 and N >= 5
    half = (N - 1) // 2
    coords = list(range(-half, half + 1))
    minc, maxc = -half, half

    fig, ax = plt.subplots(figsize=(10, 10), dpi=dpi)
    ax.set_aspect("equal")
    ax.axis("off")

    pad = 1.35
    ax.set_xlim(minc - pad, maxc + pad)
    ax.set_ylim(minc - pad, maxc + pad)

    lw_grid = 1.0
    lw_axis = 3.0
    lw_border = 2.2
    lw_flower = 3.2
    color = "black"

    # 网格 + 轴加粗 + 边框稍粗
    for x in coords:
        lw = lw_axis if x == 0 else lw_grid
        if x in (minc, maxc):
            lw = max(lw, lw_border)
        ax.add_line(Line2D([x, x], [minc, maxc], linewidth=lw, color=color))
    for y in coords:
        lw = lw_axis if y == 0 else lw_grid
        if y in (minc, maxc):
            lw = max(lw, lw_border)
        ax.add_line(Line2D([minc, maxc], [y, y], linewidth=lw, color=color))

    # 数字坐标（不写 x/y）
    label_offset = 0.65
    fs = 10
    for x in coords:
        ax.text(x, minc - label_offset, f"{x}", ha="center", va="center", fontsize=fs, color=color)
        ax.text(x, maxc + label_offset, f"{x}", ha="center", va="center", fontsize=fs, color=color)
    for y in coords:
        ax.text(minc - label_offset, y, f"{y}", ha="center", va="center", fontsize=fs, color=color)
        ax.text(maxc + label_offset, y, f"{y}", ha="center", va="center", fontsize=fs, color=color)

    # 花心位置：边到中心点的一半
    d = math.ceil(half / 2)

    star_cross = {(0, 0), (0, d), (0, -d), (d, 0), (-d, 0)}
    star_diag  = {(d, d), (-d, d), (d, -d), (-d, -d)}
    stars = list(star_cross | star_diag)

    # 大黑点
    ax.scatter([p[0] for p in stars], [p[1] for p in stars], s=120, color=color)

    # “炮位花心格”画在 (±d,±d)
    def draw_flower(x, y, d0=0.34, l=0.30):
        corners = [
            (x + d0, y + d0, +1, +1),
            (x - d0, y + d0, -1, +1),
            (x + d0, y - d0, +1, -1),
            (x - d0, y - d0, -1, -1),
        ]
        for cx, cy, sx, sy in corners:
            ax.add_line(Line2D([cx, cx + sx * l], [cy, cy], linewidth=lw_flower, color=color))
            ax.add_line(Line2D([cx, cx], [cy, cy + sy * l], linewidth=lw_flower, color=color))

    for x, y in star_diag:
        draw_flower(x, y)

    plt.savefig(out_path, bbox_inches="tight", pad_inches=0.2)
    plt.close(fig)

for n in (13, 15, 17):
    make_board_png(n, f"sword_board_{n}x{n}.png")

print("done:", "sword_board_13x13.png", "sword_board_17x17.png")