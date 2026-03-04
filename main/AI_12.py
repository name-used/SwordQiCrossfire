# AI_10.py (patched)
# 五子围棋之剑气纵横：启发式 AI（黑：五子棋/先手；白：围棋/后手）
#
# 黑（五子棋）优先级（落子需处理黑自杀禁手等规则异常；剑气格=剑气线覆盖的空点）：
# 1) “成5”但【必须触发新的剑气线】（claimed 新增）才算最高优先级（允许落在剑气格）
# 2) 逃子：若白下一手可提（对白可落气==1），且逃后下一步无法立即提子 -> 逃（排除剑气格）
# 3) 活4：一般排除剑气格；但【若该活4的两端开口都为剑气格】则允许在剑气格落子
# 4) 冲4（排除剑气格）
# 5) 活3（排除剑气格）
# 6) 战区活跃点（排除剑气格）拆分：
#    6a) 九宫格内有 1-2 个己方棋子且敌方<=1 的点
#    6b) 其余战区点：随机落子，但若九宫格总棋子>=5 则重抽（最多 7 次）
#        * 九宫格统计时：越界格一律按“白棋”计（用于避边界点）
# 7) 全局可选落点（排除剑气格）
# 若全局只剩剑气格可走：黑 pass（不堵唯一活气眼）
#
# 白（围棋）优先级（排除剑气格；永不 pass，除非无合法手）：
# 1) 提子
# 2) 堵冲4（黑若下一手可成冲4的点）
# 3) 堵活3（黑若下一手可成活3的点）
# 4) 赶吃（本手打吃：制造某黑群对白可落气==1）
# 5) 抢黑方优先点（复用黑的候选点，排除剑气格）
# 6) 否则：去黑多白少区域外围扩张
#
# 说明：所有候选点都以 try-play 验证，绝不把非法点交给 GUI。

import copy
import random
from collections import deque

try:
    from game import BLACK, WHITE
except Exception:
    BLACK, WHITE = 1, 2

EMPTY = 0
DIR4 = [(1, 0), (-1, 0), (0, 1), (0, -1)]


# ---------- 基础工具 ----------

def _N(st):
    return int(getattr(st, "N", len(st.board)))


def _inb(st, r, c):
    f = getattr(st, "inb", None)
    if callable(f):
        return f(r, c)
    n = _N(st)
    return 0 <= r < n and 0 <= c < n


def _board(st):
    return st.board


def _clone_state(st):
    for name in ("clone", "copy"):
        f = getattr(st, name, None)
        if callable(f):
            try:
                return f()
            except TypeError:
                pass
    return copy.deepcopy(st)


def _try_play(st, move):
    ns = _clone_state(st)
    try:
        ns.play(move)
        return ns
    except Exception:
        return None


def _legal_moves(st, player):
    f = getattr(st, "legal_moves", None)
    if callable(f):
        try:
            ms = f(player)
        except TypeError:
            ms = f()
        return list(ms) if ms is not None else []
    # fallback
    b = _board(st)
    n = _N(st)
    out = []
    for r in range(n):
        for c in range(n):
            if b[r][c] == EMPTY:
                out.append((r, c))
    return out


def _all_empty_points(st):
    b = _board(st)
    n = _N(st)
    out = []
    for r in range(n):
        for c in range(n):
            if b[r][c] == EMPTY:
                out.append((r, c))
    return out


def _sword_empty_points(st):
    pts = set()
    claimed = getattr(st, "claimed", None)
    line_points = getattr(st, "line_points", None)
    if not claimed or not line_points:
        return pts
    b = _board(st)
    for lid in claimed:
        for (r, c) in line_points[lid]:
            if b[r][c] == EMPTY:
                pts.add((r, c))
    return pts


def _stone_count(st, color):
    b = _board(st)
    return sum(1 for row in b for v in row if v == color)


def _neighbors4(st, r, c):
    for dr, dc in DIR4:
        rr, cc = r + dr, c + dc
        if _inb(st, rr, cc):
            yield rr, cc


# ---------- 围棋 group / liberties ----------

def _group_and_libs(st, r, c, color, forbid_libs: set):
    b = _board(st)
    if b[r][c] != color:
        return set(), set()
    q = deque([(r, c)])
    seen = {(r, c)}
    group = {(r, c)}
    libs = set()
    while q:
        x, y = q.popleft()
        for xx, yy in _neighbors4(st, x, y):
            v = b[xx][yy]
            if v == EMPTY:
                if (xx, yy) not in forbid_libs:
                    libs.add((xx, yy))
            elif v == color and (xx, yy) not in seen:
                seen.add((xx, yy))
                group.add((xx, yy))
                q.append((xx, yy))
    return group, libs


def _all_groups(st, color, forbid_libs: set):
    n = _N(st)
    b = _board(st)
    seen = set()
    out = []
    for r in range(n):
        for c in range(n):
            if b[r][c] == color and (r, c) not in seen:
                g, libs = _group_and_libs(st, r, c, color, forbid_libs)
                seen |= g
                out.append((g, libs))
    return out


# ---------- 五子棋形：成5/活4/冲4/活3 ----------

def _count_dir(st, r, c, color, dr, dc):
    b = _board(st)
    n = _N(st)
    k = 0
    rr, cc = r + dr, c + dc
    while 0 <= rr < n and 0 <= cc < n and b[rr][cc] == color:
        k += 1
        rr += dr
        cc += dc
    return k


def _end_cell(st, r, c, dr, dc, steps):
    rr = r + dr * (steps + 1)
    cc = c + dc * (steps + 1)
    return rr, cc


def _is_empty_like(st, r, c):
    if not _inb(st, r, c):
        return False
    return _board(st)[r][c] == EMPTY


def _gomoku_patterns_if_place(st, r, c, color):
    b = _board(st)
    if b[r][c] != EMPTY:
        return (False, False, False, False)

    lines = [((1, 0), (-1, 0)), ((0, 1), (0, -1)), ((1, 1), (-1, -1)), ((1, -1), (-1, 1))]
    is_five = live4 = rush4 = live3 = False

    for (d1, d2) in lines:
        a = _count_dir(st, r, c, color, d1[0], d1[1])
        b2 = _count_dir(st, r, c, color, d2[0], d2[1])
        total = a + b2 + 1

        if total >= 5:
            is_five = True

        e1 = _end_cell(st, r, c, d1[0], d1[1], a)
        e2 = _end_cell(st, r, c, d2[0], d2[1], b2)
        open1 = _is_empty_like(st, e1[0], e1[1])
        open2 = _is_empty_like(st, e2[0], e2[1])

        if total == 4 and open1 and open2:
            live4 = True
        elif total == 4 and (open1 ^ open2):
            rush4 = True
        elif total == 3 and open1 and open2:
            live3 = True

    return (is_five, live4, rush4, live3)


def _live4_open_ends_if_place(st, r, c, color):
    """返回所有能形成活4的方向的两端开口坐标 [(end1, end2), ...]"""
    b = _board(st)
    if b[r][c] != EMPTY:
        return []
    ends = []
    lines = [((1, 0), (-1, 0)), ((0, 1), (0, -1)), ((1, 1), (-1, -1)), ((1, -1), (-1, 1))]
    for (d1, d2) in lines:
        a = _count_dir(st, r, c, color, d1[0], d1[1])
        b2 = _count_dir(st, r, c, color, d2[0], d2[1])
        total = a + b2 + 1
        if total != 4:
            continue
        e1 = _end_cell(st, r, c, d1[0], d1[1], a)
        e2 = _end_cell(st, r, c, d2[0], d2[1], b2)
        if _is_empty_like(st, e1[0], e1[1]) and _is_empty_like(st, e2[0], e2[1]):
            ends.append((e1, e2))
    return ends


# ---------- 黑方：逃子 / 白方：提子与赶吃 ----------

def _black_escape_moves(st, sword_empty: set):
    black_groups = _all_groups(st, BLACK, forbid_libs=set())
    danger_moves = set()

    for g, _ in black_groups:
        any_stone = next(iter(g))
        # 计算对白可落的气（排除剑气格）
        _, libs_for_white = _group_and_libs(st, any_stone[0], any_stone[1], BLACK, forbid_libs=sword_empty)
        if len(libs_for_white) == 1:
            lib = next(iter(libs_for_white))
            # 补这口气（不走剑气格）
            if lib not in sword_empty:
                danger_moves.add(lib)
            # 周围扩气点
            for (x, y) in g:
                for xx, yy in _neighbors4(st, x, y):
                    if _board(st)[xx][yy] == EMPTY and (xx, yy) not in sword_empty:
                        danger_moves.add((xx, yy))

    return danger_moves
def _try_play_as_turn(st, move, turn_color):
    ns = _clone_state(st)
    try:
        ns.turn = turn_color
    except Exception:
        pass
    try:
        ns.play(move)
        return ns
    except Exception:
        return None

def _count_white_immediate_captures(st_like, sword_empty):
    """
    统计：白下一手是否能“直接提子”（真实提子：黑子数量下降）。
    注意：这里必须用真实 play() 去触发 _after_white_move 的提子逻辑。
    """
    # st_like 的 turn 可能不是白；我们强制按白回合模拟
    before = _stone_count(st_like, BLACK)

    cap_moves = 0
    for g, _ in _all_groups(st_like, BLACK, forbid_libs=set()):
        any_stone = next(iter(g))
        _, libs_for_white = _group_and_libs(
            st_like, any_stone[0], any_stone[1], BLACK, forbid_libs=sword_empty
        )
        if len(libs_for_white) != 1:
            continue
        lib = next(iter(libs_for_white))

        ns = _try_play_as_turn(st_like, lib, WHITE)
        if ns is not None and _stone_count(ns, BLACK) < before:
            cap_moves += 1
    return cap_moves

def _white_capture_moves(st, legal_white, sword_empty):
    before = _stone_count(st, BLACK)
    moves = []
    for mv in legal_white:
        if mv in sword_empty:
            continue
        ns = _try_play(st, mv)
        if ns is None:
            continue
        after = _stone_count(ns, BLACK)
        if after < before:
            moves.append(mv)
    return moves


def _white_atari_moves(st, legal_white, sword_empty):
    moves = []
    for mv in legal_white:
        if mv in sword_empty:
            continue
        ns = _try_play(st, mv)
        if ns is None:
            continue
        for g, _ in _all_groups(ns, BLACK, forbid_libs=set()):
            any_stone = next(iter(g))
            _, libs_for_white = _group_and_libs(ns, any_stone[0], any_stone[1], BLACK, forbid_libs=sword_empty)
            if len(libs_for_white) == 1:
                moves.append(mv)
                break
    return moves


# ---------- 战区 / 区域扩张 ----------

def _battle_zone_points(st):
    n = _N(st)
    b = _board(st)
    pts = set()

    # 棋子九宫格
    for r in range(n):
        for c in range(n):
            if b[r][c] != EMPTY:
                for dr in (-1, 0, 1):
                    for dc in (-1, 0, 1):
                        rr, cc = r + dr, c + dc
                        if 0 <= rr < n and 0 <= cc < n:
                            pts.add((rr, cc))

    # 剑气线点九宫格（包括非空）
    claimed = getattr(st, "claimed", None)
    line_points = getattr(st, "line_points", None)
    if claimed and line_points:
        for lid in claimed:
            for (r, c) in line_points[lid]:
                for dr in (-1, 0, 1):
                    for dc in (-1, 0, 1):
                        rr, cc = r + dr, c + dc
                        if 0 <= rr < n and 0 <= cc < n:
                            pts.add((rr, cc))
    return pts


def _count_3x3_stones_edge_white(st, r, c):
    """
    九宫格计数（用于战区点筛选）：
    - 统计黑子/白子/总棋子（不含空点）
    - 越界格一律按“白棋”计入（让边界点天然更不优）
    """
    n = _N(st)
    b = _board(st)
    bc = wc = tot = 0
    for dr in (-1, 0, 1):
        for dc in (-1, 0, 1):
            rr, cc = r + dr, c + dc
            if 0 <= rr < n and 0 <= cc < n:
                v = b[rr][cc]
                if v == BLACK:
                    bc += 1
                    tot += 1
                elif v == WHITE:
                    wc += 1
                    tot += 1
            else:
                # 越界当白棋
                wc += 1
                tot += 1
    return bc, wc, tot


def _region_expand_moves(st, legal_white, sword_empty):
    n = _N(st)
    b = _board(st)

    bins = 4
    hs = max(1, n // bins)
    best = None
    best_score = -10 ** 9

    for r in range(0, n, hs):
        for c in range(0, n, hs):
            r2 = min(n, r + hs)
            c2 = min(n, c + hs)
            bc = wc = 0
            empties = []
            for rr in range(r, r2):
                for cc in range(c, c2):
                    if b[rr][cc] == BLACK:
                        bc += 1
                    elif b[rr][cc] == WHITE:
                        wc += 1
                    elif (rr, cc) in legal_white and (rr, cc) not in sword_empty:
                        empties.append((rr, cc))
            if not empties:
                continue
            score = (bc * 3 - wc * 2) + len(empties) * 0.1
            if score > best_score:
                best_score = score
                best = (r, c, r2, c2, empties)

    if not best:
        return []

    r, c, r2, c2, empties = best
    cr = (r + r2 - 1) / 2.0
    cc = (c + c2 - 1) / 2.0
    empties.sort(key=lambda p: -((p[0] - cr) ** 2 + (p[1] - cc) ** 2))
    return empties[:12]


# ---------- 触发新剑气线评分 ----------

def _score_new_sword_lines(st, new_lines):
    """
    粗评分：偏好：
    - 线更长/更“居中”
    - 线内白子多、空位多（更赚）
    """
    b = _board(st)
    line_points = getattr(st, "line_points", None)
    if not line_points:
        return 0
    n = _N(st)
    center = (n - 1) / 2.0

    score = 0
    for lid in new_lines:
        pts = line_points.get(lid, [])
        if not pts:
            continue
        whites = 0
        empties = 0
        dist = 0.0
        for r, c in pts:
            if b[r][c] == WHITE:
                whites += 1
            elif b[r][c] == EMPTY:
                empties += 1
            dist += abs(r - center) + abs(c - center)
        dist /= max(1, len(pts))
        score += 400 * whites + 50 * empties - 5 * dist + 10 * len(pts)
    return score


# ---------- AI：黑 / 白 ----------

def ai_black(st):
    n = _N(st)
    sword_empty = _sword_empty_points(st)

    empties = _all_empty_points(st)
    legal_black = list(_legal_moves(st, BLACK))

    # 黑：如果非剑气格无手可走（只剩剑气格），直接 pass
    nonsword_set = set(p for p in empties if p not in sword_empty)
    nonsword_legal = [mv for mv in legal_black if mv in nonsword_set]
    if not nonsword_legal:
        # 仍允许：若有“触发新剑气线”的手（可能在剑气格）就走，否则 pass
        base_claimed = set(getattr(st, "claimed", set()))
        scored = []
        for mv in legal_black:
            ns = _try_play(st, mv)
            if ns is None:
                continue
            new_lines = set(getattr(ns, "claimed", set())) - base_claimed
            if not new_lines:
                continue
            s = _score_new_sword_lines(st, new_lines)
            if mv in sword_empty:
                s -= 80
            scored.append((s, mv))
        if scored:
            scored.sort(key=lambda x: x[0], reverse=True)
            top_s = scored[0][0]
            top = [mv for s, mv in scored if s == top_s]
            return random.choice(top)
        return None

    # 先手第一步：走中心（若合法）
    if _stone_count(st, BLACK) + _stone_count(st, WHITE) == 0:
        center = (n // 2, n // 2)
        if center in legal_black and _try_play(st, center) is not None:
            return center

    # 帮助函数：从候选里随机取一个能 try_play 的
    def pick_from(cands, allow_sword: bool):
        cands = list(cands)
        random.shuffle(cands)
        for mv in cands:
            if not allow_sword and mv in sword_empty:
                continue
            if mv not in empties:
                continue
            if _try_play(st, mv) is not None:
                return mv
        return None

    # 1) 成5：只有“新增剑气线”才算最高优先级（允许剑气格）
    base_claimed = set(getattr(st, "claimed", set()))
    scored = []
    for mv in legal_black:
        ns = _try_play(st, mv)
        if ns is None:
            continue
        new_lines = set(getattr(ns, "claimed", set())) - base_claimed
        if not new_lines:
            continue
        s = _score_new_sword_lines(st, new_lines)
        if mv in sword_empty:
            s -= 80
        scored.append((s, mv))
    if scored:
        scored.sort(key=lambda x: x[0], reverse=True)
        top_s = scored[0][0]
        top = [mv for s, mv in scored if s == top_s]
        return random.choice(top)

    # 2) 逃子（排除剑气格）：只有“逃后能减少立即被提的风险”才算有效逃子
    escape_cands = _black_escape_moves(st, sword_empty=sword_empty)

    # 先计算：如果黑啥也不管，白下一手“真实提子”的可能数
    base_caps = _count_white_immediate_captures(st, sword_empty=sword_empty)

    if base_caps > 0 and escape_cands:
        good = []
        for mv0 in escape_cands:
            ns = _try_play(st, mv0)  # 黑走一步，ns.turn 应该已经轮到白
            if ns is None:
                continue
            sword2 = _sword_empty_points(ns)
            caps2 = _count_white_immediate_captures(ns, sword_empty=sword2)

            # ✅只要“立即可提次数”下降，就说明这手逃子至少救了点东西（哪怕救不全）
            if caps2 < base_caps:
                good.append(mv0)

        mv = pick_from(good, allow_sword=False)
        if mv is not None:
            return mv

    # 没有有效逃子就别硬逃，继续走后续（活4/冲4/战区…）
    # 3) 活4：优先非剑气格；若落在剑气格则要求“该活4的两端开口都为剑气格”
    live4_nonsword = []
    for (r, c) in nonsword_set:
        _, l4, _, _ = _gomoku_patterns_if_place(st, r, c, BLACK)
        if l4:
            live4_nonsword.append((r, c))
    mv = pick_from(live4_nonsword, allow_sword=False)
    if mv is not None:
        return mv

    # 允许的“剑气格活4”（两端开口均为剑气格）
    live4_sword_ok = []
    for (r, c) in sword_empty:
        if (r, c) not in empties:
            continue
        ends = _live4_open_ends_if_place(st, r, c, BLACK)
        if not ends:
            continue
        # 只要存在一个方向满足“两端开口都是剑气格”即可
        ok = False
        for (e1, e2) in ends:
            if (e1 in sword_empty) and (e2 in sword_empty):
                ok = True
                break
        if ok:
            live4_sword_ok.append((r, c))
    mv = pick_from(live4_sword_ok, allow_sword=True)
    if mv is not None:
        return mv

    # 4) 冲4（排除剑气格）
    rush4 = []
    for (r, c) in nonsword_set:
        _, _, r4, _ = _gomoku_patterns_if_place(st, r, c, BLACK)
        if r4:
            rush4.append((r, c))
    mv = pick_from(rush4, allow_sword=False)
    if mv is not None:
        return mv

    # 5) 活3（排除剑气格）
    live3 = []
    for (r, c) in nonsword_set:
        _, _, _, l3 = _gomoku_patterns_if_place(st, r, c, BLACK)
        if l3:
            live3.append((r, c))
    mv = pick_from(live3, allow_sword=False)
    if mv is not None:
        return mv

    # 6a/6b) 战区活跃点（复用 AI_6 的拆分逻辑；九宫格越界按白棋计）
    battle = _battle_zone_points(st)
    battle_empties = [p for p in battle if p in empties and p not in sword_empty]

    battle_good = []
    battle_rest = []
    for (r, c) in battle_empties:
        bc, wc, tot = _count_3x3_stones_edge_white(st, r, c)
        if 1 <= bc <= 2 and wc <= 1:
            battle_good.append((r, c))
        else:
            battle_rest.append((r, c))

    mv = pick_from(battle_good, allow_sword=False)
    if mv is not None:
        return mv

    if battle_rest:
        rest = battle_rest[:]
        for _ in range(7):
            mv_try = random.choice(rest)
            bc, wc, tot = _count_3x3_stones_edge_white(st, mv_try[0], mv_try[1])
            if tot >= 5:
                continue
            if _try_play(st, mv_try) is not None:
                return mv_try
        mv = pick_from(rest, allow_sword=False)
        if mv is not None:
            return mv

    # 7) 全局可选落点（排除剑气格）
    mv = pick_from(nonsword_legal, allow_sword=False)
    if mv is not None:
        return mv

    return None


def _black_new_sword_lines_if_place(st, r, c):
    """
    快速判断：黑若在 (r,c) 落子，会新增哪些剑气线（只看“成>=5连”的那条线；忽略提子/清空对白子的影响）。
    返回 set(LineId)（可能同时新增多条：十字/双斜同时>=5）。
    """
    b = _board(st)
    if b[r][c] != EMPTY:
        return set()

    claimed = set(getattr(st, "claimed", set()) or set())
    new_lines = set()

    # (dr,dc) 与 LineId 的映射
    dirs = [((0, 1), ('H', r)),
        ((1, 0), ('V', c)),
        ((1, 1), ('D1', r - c)),
        ((1, -1), ('D2', r + c))]

    for (dr, dc), lid in dirs:
        a = _count_dir(st, r, c, BLACK, dr, dc)
        b2 = _count_dir(st, r, c, BLACK, -dr, -dc)
        if a + b2 + 1 >= 5 and lid not in claimed:
            new_lines.add(lid)

    return new_lines


def _stones_in_lines_that_make_five_if_place(st, r, c):
    """
    返回：若黑在 (r,c) 落子会“成>=5连”，那么每个满足方向对应的黑子集合（不含 (r,c) 自己）。
    list[set[(rr,cc)]]
    """
    b = _board(st)
    if b[r][c] != EMPTY:
        return []

    out = []
    dirs = [(0, 1), (1, 0), (1, 1), (1, -1)]
    for dr, dc in dirs:
        a = _count_dir(st, r, c, BLACK, dr, dc)
        b2 = _count_dir(st, r, c, BLACK, -dr, -dc)
        total = a + b2 + 1
        if total < 5:
            continue
        stones = set()
        for i in range(1, a + 1):
            stones.add((r + dr * i, c + dc * i))
        for i in range(1, b2 + 1):
            stones.add((r - dr * i, c - dc * i))
        if stones:
            out.append(stones)
    return out


def _stones_in_lines_that_make_live4_if_place(st, r, c):
    """
    返回：若黑在 (r,c) 落子会“形成活4（总连子=4 且两端皆为空）”，每个满足方向对应的黑子集合（不含 (r,c)）。
    list[set[(rr,cc)]]
    """
    b = _board(st)
    if b[r][c] != EMPTY:
        return []

    out = []
    lines = [((1, 0), (-1, 0)), ((0, 1), (0, -1)), ((1, 1), (-1, -1)), ((1, -1), (-1, 1))]
    for (d1, d2) in lines:
        a = _count_dir(st, r, c, BLACK, d1[0], d1[1])
        b2 = _count_dir(st, r, c, BLACK, d2[0], d2[1])
        total = a + b2 + 1
        if total != 4:
            continue
        e1 = _end_cell(st, r, c, d1[0], d1[1], a)
        e2 = _end_cell(st, r, c, d2[0], d2[1], b2)
        if not (_is_empty_like(st, e1[0], e1[1]) and _is_empty_like(st, e2[0], e2[1])):
            continue

        stones = set()
        for i in range(1, a + 1):
            stones.add((r + d1[0] * i, c + d1[1] * i))
        for i in range(1, b2 + 1):
            stones.add((r + d2[0] * i, c + d2[1] * i))
        if stones:
            out.append(stones)

    return out


def _white_defense_disrupt(st, threat_points, kind: str, legal_white_set: set, sword_empty: set):
    """
    当“要堵的孔位是剑气格（白禁手）”导致无法直接堵时：
    在威胁线附近挑一个“看起来就很像在防守”的点（打吃/靠近/准备提子），尽量把黑的下一手威胁压下去。

    kind:
      - "five": threat_points 是黑“一步成5”的点
      - "live4": threat_points 是黑“一步成活4”的点
    """
    if not threat_points:
        return None

    n = _N(st)
    center = (n - 1) / 2.0

    def center_dist2(p):
        return (p[0] - center) ** 2 + (p[1] - center) ** 2

    # 1) 生成候选：围着威胁点 & 威胁线上的黑子 取 4邻空点
    cands = set()
    for (tr, tc) in threat_points:
        # 威胁点附近
        for rr, cc in _neighbors4(st, tr, tc):
            if _board(st)[rr][cc] == EMPTY:
                cands.add((rr, cc))

        # 威胁线上的黑子附近
        if kind == "five":
            stone_sets = _stones_in_lines_that_make_five_if_place(st, tr, tc)
        else:
            stone_sets = _stones_in_lines_that_make_live4_if_place(st, tr, tc)

        for ss in stone_sets:
            for (sr, sc) in ss:
                for rr, cc in _neighbors4(st, sr, sc):
                    if _board(st)[rr][cc] == EMPTY:
                        cands.add((rr, cc))

    # 过滤：白合法 & 非剑气格
    cands = [mv for mv in cands if (mv in legal_white_set and mv not in sword_empty)]
    if not cands:
        return None

    # 2) 评估：模拟白落子后，黑的“同类威胁”还剩多少
    before_black = _stone_count(st, BLACK)

    best_mv = None
    best_key = None

    # 为了不太慢：候选太多时，先按“离中心近 & 离威胁点近”粗筛一轮
    if len(cands) > 40:
        # 离任何 threat 最近距离
        def min_d2_to_threat(p):
            md = 10 ** 9
            for q in threat_points:
                d2 = (p[0] - q[0]) ** 2 + (p[1] - q[1]) ** 2
                if d2 < md:
                    md = d2
            return md

        cands.sort(key=lambda p: (min_d2_to_threat(p), center_dist2(p)))
        cands = cands[:40]

    for mv in cands:
        ns = _try_play(st, mv)
        if ns is None:
            continue

        after_black = _stone_count(ns, BLACK)
        capture_gain = before_black - after_black  # >0 表示这步白直接提了黑子

        legal_black2 = set(_legal_moves(ns, BLACK))

        new_sword_threats = 0
        five_threats = 0
        live4_threats = 0

        for p in threat_points:
            if p not in legal_black2:
                continue
            is_five, l4, _, _ = _gomoku_patterns_if_place(ns, p[0], p[1], BLACK)

            if kind == "five":
                if is_five:
                    five_threats += 1
                    if _black_new_sword_lines_if_place(ns, p[0], p[1]):
                        new_sword_threats += 1
            else:
                if l4:
                    live4_threats += 1

        # key 越小越好：优先“把威胁数量压下去”，其次“顺手提子”，再其次靠中心一点
        if kind == "five":
            key = (new_sword_threats, five_threats, -capture_gain, center_dist2(mv))
        else:
            key = (live4_threats, -capture_gain, center_dist2(mv))

        if best_key is None or key < best_key:
            best_key = key
            best_mv = mv

            # 已经把同类威胁清空：直接收手（看起来就很聪明）
            if kind == "five" and key[0] == 0 and key[1] == 0:
                break
            if kind == "live4" and key[0] == 0:
                break

    return best_mv


def ai_white(st):
    """
    白（围棋/后手）优先级（按你的最终口径）：
    1) 提子
    2) 堵冲4：黑下一手能成5（优先：还能触发新的剑气线）
    3) 堵活3：黑下一手能做出活4
    4) 赶吃（本手打吃：制造对白可落气==1）
    5) 抢黑最想走的位置
    6) 扩张 / 兜底（尽量别往边角瞎扔）
    * 白永不 pass，除非无合法手。
    """
    sword_empty = _sword_empty_points(st)
    legal_white = [mv for mv in _legal_moves(st, WHITE) if mv not in sword_empty]
    if not legal_white:
        return None

    legal_white_set = set(legal_white)

    def pick(cands, shuffle=True):
        cands = [mv for mv in cands if mv in legal_white_set and mv not in sword_empty]
        if shuffle:
            random.shuffle(cands)
        for mv in cands:
            if _try_play(st, mv) is not None:
                return mv
        return None

    # 1) 提子
    caps = _white_capture_moves(st, legal_white, sword_empty)
    mv = pick(caps, shuffle=True)
    if mv is not None:
        return mv

    # 黑方可走集合（用于剔除“黑自杀禁手”等伪威胁）
    legal_black = list(_legal_moves(st, BLACK))
    legal_black_set = set(legal_black)

    # ========== 2) 堵冲4：黑下一手能成5 ==========
    # 注意：威胁点必须从 legal_moves(BLACK) 推导（避免把黑自杀禁手当威胁）
    threat_new_sword = []  # [(score, p)]
    threat_make_five = []  # [p]
    for p in legal_black:
        r, c = p
        is_five, _, _, _ = _gomoku_patterns_if_place(st, r, c, BLACK)
        if not is_five:
            continue

        new_lines = _black_new_sword_lines_if_place(st, r, c)
        if new_lines:
            sc = _score_new_sword_lines(st, new_lines)
            threat_new_sword.append((sc, p))
        else:
            threat_make_five.append(p)

    if threat_new_sword or threat_make_five:
        threat_new_sword.sort(key=lambda x: x[0], reverse=True)
        mv = pick([p for _, p in threat_new_sword], shuffle=False)
        if mv is not None:
            return mv

        mv = pick(threat_make_five, shuffle=False)
        if mv is not None:
            return mv

        # ⚠️ 走到这里，说明“该堵的孔位很可能是剑气格（白禁手）”
        # 给一个轻量的“防守型替代手”，避免看起来发呆。
        mv = _white_defense_disrupt(
            st,
            threat_points=[p for _, p in threat_new_sword] + threat_make_five,
            kind="five",
            legal_white_set=legal_white_set,
            sword_empty=sword_empty,
        )
        if mv is not None:
            return mv

    # ========== 3) 堵活3：黑下一手能做活4 ==========
    block_live4 = []
    for p in legal_black:
        r, c = p
        _, l4, _, _ = _gomoku_patterns_if_place(st, r, c, BLACK)
        if l4:
            block_live4.append(p)

    if block_live4:
        # 先尝试直接堵端点（若端点不是剑气格，白一般能落）
        mv = pick(block_live4, shuffle=False)
        if mv is not None:
            return mv

        # 如果端点恰好都在剑气格（白禁手），就用“防守替代手”
        mv = _white_defense_disrupt(
            st,
            threat_points=block_live4,
            kind="live4",
            legal_white_set=legal_white_set,
            sword_empty=sword_empty,
        )
        if mv is not None:
            return mv

    # 4) 赶吃（打吃）
    ataris = _white_atari_moves(st, legal_white, sword_empty)
    mv = pick(ataris, shuffle=True)
    if mv is not None:
        return mv

    # 5) 抢黑方优先点（粗排序）
    black_wants = []
    for p in legal_black:
        if p in sword_empty:
            continue
        r, c = p
        is_five, l4, r4, l3 = _gomoku_patterns_if_place(st, r, c, BLACK)
        if is_five:
            black_wants.append((0, p))
        elif l4:
            black_wants.append((1, p))
        elif r4:
            black_wants.append((2, p))
        elif l3:
            black_wants.append((3, p))

    black_wants.sort(key=lambda x: x[0])
    mv = pick([p for _, p in black_wants], shuffle=True)
    if mv is not None:
        return mv

    # 6) 扩张：去黑多白少区域外围扩张
    region_moves = _region_expand_moves(st, legal_white_set, sword_empty)
    mv = pick(region_moves, shuffle=True)
    if mv is not None:
        return mv

    # 7) 兜底：优先战区/中心附近，避免“没事往边角扔”
    battle = _battle_zone_points(st)
    battle_legal = [p for p in battle if p in legal_white_set and p not in sword_empty]
    if battle_legal:
        n = _N(st)
        center = (n - 1) / 2.0
        battle_legal.sort(key=lambda p: (p[0] - center) ** 2 + (p[1] - center) ** 2)
        return random.choice(battle_legal[: min(8, len(battle_legal))])

    # 最后再随机（但仍偏中心一点）
    n = _N(st)
    center = (n - 1) / 2.0
    legal_white.sort(key=lambda p: (p[0] - center) ** 2 + (p[1] - center) ** 2)
    return random.choice(legal_white[: min(12, len(legal_white))])
