from typing import List, Tuple, Dict, Set, Optional


N = 13
MAX_STONES_BLACK = 80
BLACK_FIVE_IGNORE_SUICIDE = False

EMPTY, BLACK, WHITE = 0, 1, 2

DIRS_4 = [(-1, 0), (1, 0), (0, -1), (0, 1)]
DIRS_4_GOMOKU = [(0, 1), (1, 0), (1, 1), (1, -1)]  # 横、竖、两斜

Point = Tuple[int, int]  # (r,c)
LineId = Tuple[str, int]  # ('H',r) ('V',c) ('D1',r-c) ('D2',r+c)

black_color = '#F00'
black_name = '红'
white_color = '#5D5'
white_name = '绿'
