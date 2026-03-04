from dataclasses import dataclass
from typing import List, Tuple, Dict, Set, Optional

from config import (
    EMPTY, BLACK, WHITE, DIRS_4, DIRS_4_GOMOKU,
    Point, LineId,
    black_color, black_name, white_color, white_name
)


def opponent(color: int) -> int:
    return WHITE if color == BLACK else BLACK


@dataclass
class GameState:
    N: int
    black_stone_limit: int
    black_five_ignore_suicide: bool
    board: List[List[int]]
    claimed: Set[LineId]
    placed_black: int = 0
    placed_white: int = 0
    turn: int = BLACK
    consecutive_passes: int = 0

    # 预计算
    line_points: Dict[LineId, List[Point]] = None
    point_lines: Dict[Point, List[LineId]] = None

    @staticmethod
    def new(N, black_stone_limit, black_five_ignore_suicide) -> "GameState":
        board = [[EMPTY] * N for _ in range(N)]
        line_points: Dict[LineId, List[Point]] = {}
        point_lines: Dict[Point, List[LineId]] = {(r, c): [] for r in range(N) for c in range(N)}

        # 行
        for r in range(N):
            lid = ('H', r)
            pts = [(r, c) for c in range(N)]
            line_points[lid] = pts
            for p in pts:
                point_lines[p].append(lid)

        # 列
        for c in range(N):
            lid = ('V', c)
            pts = [(r, c) for r in range(N)]
            line_points[lid] = pts
            for p in pts:
                point_lines[p].append(lid)

        # 主对角线 NW-SE: r-c = k
        for k in range(-(N - 1), (N - 1) + 1):
            pts = [(r, c) for r in range(N) for c in range(N) if r - c == k]
            lid = ('D1', k)
            line_points[lid] = pts
            for p in pts:
                point_lines[p].append(lid)

        # 副对角线 NE-SW: r+c = s
        for s in range(0, 2 * (N - 1) + 1):
            pts = [(r, c) for r in range(N) for c in range(N) if r + c == s]
            lid = ('D2', s)
            line_points[lid] = pts
            for p in pts:
                point_lines[p].append(lid)

        return GameState(N, black_stone_limit, black_five_ignore_suicide, board=board, claimed=set(), line_points=line_points, point_lines=point_lines)

    def inb(self, r: int, c: int) -> bool:
        return 0 <= r < self.N and 0 <= c < self.N

    def stones_left(self, color: int) -> int:
        if color == BLACK:
            used = self.placed_black
            return self.black_stone_limit - used
        else:
            return 1

    def is_white_forbidden(self, r: int, c: int) -> bool:
        if self.board[r][c] != EMPTY:
            return False
        return any(lid in self.claimed for lid in self.point_lines[(r, c)])

    def is_black_immune(self, r: int, c: int) -> bool:
        if self.board[r][c] != BLACK:
            return False
        return any(lid in self.claimed for lid in self.point_lines[(r, c)])

    def _would_trigger_new_sword_line_if_black_place(self, r: int, c: int) -> bool:
        """黑若在 (r,c) 落子，是否会形成 >=5 且产生【至少一条未 claimed 的新线】"""
        if not self.inb(r, c) or self.board[r][c] != EMPTY:
            return False

        self.board[r][c] = BLACK
        try:
            for dr, dc in DIRS_4_GOMOKU:
                run = 1
                rr, cc = r - dr, c - dc
                while self.inb(rr, cc) and self.board[rr][cc] == BLACK:
                    run += 1
                    rr, cc = rr - dr, cc - dc
                rr, cc = r + dr, c + dc
                while self.inb(rr, cc) and self.board[rr][cc] == BLACK:
                    run += 1
                    rr, cc = rr + dr, cc + dc

                if run >= 5:
                    # 按 _after_black_move 的映射得到线 id:contentReference[oaicite:2]{index=2}
                    if (dr, dc) == (0, 1):
                        lid = ('H', r)
                    elif (dr, dc) == (1, 0):
                        lid = ('V', c)
                    elif (dr, dc) == (1, 1):
                        lid = ('D1', r - c)
                    else:  # (1, -1)
                        lid = ('D2', r + c)

                    if lid not in self.claimed:
                        return True
            return False
        finally:
            self.board[r][c] = EMPTY

    def legal_moves(self, color: int) -> List[Point]:
        if self.stones_left(color) <= 0:
            return []
        moves = []
        for r in range(self.N):
            for c in range(self.N):
                if self.board[r][c] != EMPTY:
                    continue
                # 白：剑气线空点禁入（其它一律允许）
                if color == WHITE and self.is_white_forbidden(r, c):
                    continue
                # 黑：严格禁止“自杀落子”（不考虑落子后触发剑气/提子等任何效果）
                if color == BLACK and self._would_be_suicide_black_strict(r, c):
                    ignore = self.black_five_ignore_suicide
                    if not (ignore and self._would_trigger_new_sword_line_if_black_place(r, c)):
                        continue
                moves.append((r, c))
        return moves

    def _would_be_suicide_black_strict(self, r: int, c: int) -> bool:
        # 黑落子后：如果在“未触发剑气、未发生任何提子/清空效果前”自身棋串就无气，则非法
        if self.board[r][c] != EMPTY:
            return True

        self.board[r][c] = BLACK
        grp_b = self._collect_group(r, c, BLACK)
        ok = self._count_liberties(grp_b) > 0
        self.board[r][c] = EMPTY
        return not ok

    def play(self, move: Optional[Point]) -> None:
        # move=None => Pass
        if self.is_over():
            return

        color = self.turn
        if move is None:
            self.consecutive_passes += 1
            self.turn = opponent(self.turn)
            return

        r, c = move
        if not self.inb(r, c) or self.board[r][c] != EMPTY:
            raise ValueError("illegal: \n已经有其它棋子了")
        if self.stones_left(color) <= 0:
            raise ValueError("no stones left")
        if color == WHITE:
            if self.is_white_forbidden(r, c):
                raise ValueError(f"illegal: \n{white_name}无法在剑气上落子")
        else:
            ignore = getattr(self, "black_five_ignore_suicide", False)
            if (not ignore) or (not self._would_make_five(r, c)):
                if self._would_be_suicide_black_strict(r, c):
                    raise ValueError(f"illegal: \n{black_name}无法自杀落子\n（即使能成剑气也不允许）")

        self.consecutive_passes = 0
        self.board[r][c] = color

        if color == BLACK:
            self.placed_black += 1
            self._after_black_move(r, c)
        else:
            self.placed_white += 1
            self._after_white_move(r, c)

        self.turn = opponent(self.turn)

    def _after_black_move(self, r: int, c: int) -> None:
        # 检查这一步是否在某方向形成 >=5 连
        new_lines: Set[LineId] = set()
        for dr, dc in DIRS_4_GOMOKU:
            run = 1
            rr, cc = r - dr, c - dc
            while self.inb(rr, cc) and self.board[rr][cc] == BLACK:
                run += 1
                rr, cc = rr - dr, cc - dc
            rr, cc = r + dr, c + dc
            while self.inb(rr, cc) and self.board[rr][cc] == BLACK:
                run += 1
                rr, cc = rr + dr, cc + dc

            if run >= 5:
                if (dr, dc) == (0, 1):
                    new_lines.add(('H', r))
                elif (dr, dc) == (1, 0):
                    new_lines.add(('V', c))
                elif (dr, dc) == (1, 1):
                    new_lines.add(('D1', r - c))
                elif (dr, dc) == (1, -1):
                    new_lines.add(('D2', r + c))

        # 触发剑气：该线白子清空 + 线内空点白禁入（通过 claimed 实现）
        for lid in [x for x in new_lines if x not in self.claimed]:
            self.claimed.add(lid)
            for rr, cc in self.line_points[lid]:
                if self.board[rr][cc] == WHITE:
                    self.board[rr][cc] = EMPTY

    def _after_white_move(self, r: int, c: int) -> None:
        # 围棋提子：对相邻黑棋群，若无气 => 提走“非免提”部分
        to_remove: List[Point] = []
        seen: Set[Point] = set()
        for dr, dc in DIRS_4:
            rr, cc = r + dr, c + dc
            if not self.inb(rr, cc) or self.board[rr][cc] != BLACK or (rr, cc) in seen:
                continue
            grp = self._collect_group(rr, cc, BLACK)
            for p in grp:
                seen.add(p)
            if self._count_liberties(grp) == 0:
                for gr, gc in grp:
                    if not self.is_black_immune(gr, gc):
                        to_remove.append((gr, gc))
        for rr, cc in to_remove:
            self.board[rr][cc] = EMPTY

    def _collect_group(self, r: int, c: int, color: int) -> List[Point]:
        stack = [(r, c)]
        group: List[Point] = []
        seen: Set[Point] = {(r, c)}
        while stack:
            rr, cc = stack.pop()
            group.append((rr, cc))
            for dr, dc in DIRS_4:
                r2, c2 = rr + dr, cc + dc
                if self.inb(r2, c2) and (r2, c2) not in seen and self.board[r2][c2] == color:
                    seen.add((r2, c2))
                    stack.append((r2, c2))
        return group

    def _count_liberties(self, group: List[Point]) -> int:
        # “气”=相邻空点（哪怕对白禁入，也仍是空点，因此仍算气）
        libs: Set[Point] = set()
        for r, c in group:
            for dr, dc in DIRS_4:
                rr, cc = r + dr, c + dc
                if self.inb(rr, cc) and self.board[rr][cc] == EMPTY:
                    libs.add((rr, cc))
        return len(libs)

    def _would_make_five(self, r: int, c: int) -> bool:
        self.board[r][c] = BLACK
        try:
            for dr, dc in DIRS_4_GOMOKU:
                run = 1
                rr, cc = r - dr, c - dc
                while self.inb(rr, cc) and self.board[rr][cc] == BLACK:
                    run += 1
                    rr, cc = rr - dr, cc - dc
                rr, cc = r + dr, c + dc
                while self.inb(rr, cc) and self.board[rr][cc] == BLACK:
                    run += 1
                    rr, cc = rr + dr, cc + dc
                if run >= 5:
                    return True
            return False
        finally:
            self.board[r][c] = EMPTY

    def is_over(self) -> bool:
        if self.consecutive_passes >= 2:
            return True
        # if self.placed_black >= MAX_STONES_EACH and self.placed_white >= MAX_STONES_EACH:
        #     return True
        return all(self.board[r][c] != EMPTY for r in range(self.N) for c in range(self.N))

    def score(self) -> Tuple[int, int]:
        """
        终局/比分（简化版）：
        - 黑：存活黑子 + 剑气格（claimed 线上的空点）
        - 白：存活白子
        """
        black_stones = sum(1 for r in range(self.N) for c in range(self.N) if self.board[r][c] == BLACK)
        white_stones = sum(1 for r in range(self.N) for c in range(self.N) if self.board[r][c] == WHITE)

        claimed_empty = 0
        for r in range(self.N):
            for c in range(self.N):
                if self.board[r][c] != EMPTY:
                    continue
                if any(lid in self.claimed for lid in self.point_lines[(r, c)]):
                    claimed_empty += 1

        black_score = black_stones + claimed_empty
        white_score = white_stones
        return black_score, white_score
