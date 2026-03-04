# sword_go_gomoku.py
# 15x15 "五子围棋之剑气纵横" playable toy implementation (tkinter, stdlib only)
# Background board image: ./sword_board_15x15.png

from __future__ import annotations

import tkinter as tk
from gui import SwordGoUI
from AI_12 import ai_white, ai_black
from config import N, MAX_STONES_BLACK, BLACK_FIVE_IGNORE_SUICIDE


def main():
    root = tk.Tk()
    SwordGoUI(root, N, MAX_STONES_BLACK, BLACK_FIVE_IGNORE_SUICIDE, ai_white, ai_black)
    root.mainloop()


if __name__ == "__main__":
    main()
