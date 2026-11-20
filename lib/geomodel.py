"""Геометрия инженерной задачи: примитивы в миллиметрах и их контуры из отрезков и дуг.

Координаты физические: x вправо, y вверх, единица — 1 мм. Преобразование в SVG одно и однозначное:
x_svg = x, y_svg = -y (масштаб 1:1, viewBox в мм). Только стандартная библиотека Python.

Поддерживаемые примитивы:
- rect: x0, y0, x1, y1 — прямоугольник (расчётная область);
- rounded_rect: x0, y0, x1, y1 и радиусы углов {bottom_left, bottom_right, top_right, top_left} (0 — острый угол).
- path: d — путь SVG из отрезков и дуг окружностей (M, L, H, V, A, Z; координаты SVG), один замкнутый контур;
  так приходит геометрия из режима «полная перегенерация SVG».
Кривые Безье и эллиптические дуги не поддерживаются — задача с такой формой отклоняется явно (п. 15 ТЗ).
"""
from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Dict, List, Tuple, Union

P = Tuple[float, float]
CORNERS = ('bottom_left', 'bottom_right', 'top_right', 'top_left')
EPS = 1e-9


@dataclass(frozen=True)
class Line:
    a: P
    b: P


@dataclass(frozen=True)
class Arc:
    """Дуга окружности против часовой стрелки при sweep > 0 (по часовой при sweep < 0); углы в радианах."""
    c: P
    r: float
    start: float
    sweep: float

    @property
    def a(self) -> P:
        return (self.c[0] + self.r * math.cos(self.start), self.c[1] + self.r * math.sin(self.start))

    @property
    def b(self) -> P:
        e = self.start + self.sweep
        return (self.c[0] + self.r * math.cos(e), self.c[1] + self.r * math.sin(e))


Seg = Union[Line, Arc]


class GeometryError(ValueError):
    pass


# ---------------------------------------------------------------- примитивы -> контуры
def contour(obj: dict) -> List[Seg]:
    """Замкнутый контур примитива против часовой стрелки (для path — как записан, проверки ловят незамкнутость)."""
    kind = obj.get('type')
    if kind == 'path':
        rings = parse_svg_path(obj.get('d', ''))
        if len(rings) != 1:
            raise GeometryError(f'{obj.get("id")}: область должна быть одним контуром, а в path их {len(rings)}')
        return rings[0] if area(rings[0]) >= 0 else reverse(rings[0])
    if kind == 'rect':
        return contour({**obj, 'type': 'rounded_rect', 'radii': {}})
    if kind != 'rounded_rect':
        raise GeometryError(f'неподдерживаемый примитив {kind!r} (поддерживаются rect, rounded_rect)')
    x0, y0, x1, y1 = (float(obj[k]) for k in ('x0', 'y0', 'x1', 'y1'))
    if not (x1 > x0 and y1 > y0):
        raise GeometryError(f'{obj.get("id")}: нулевая или отрицательная ширина/высота')
    r = {k: float(obj.get('radii', {}).get(k, 0.0)) for k in CORNERS}
    # скругления соседних углов не должны перекрываться на общей стороне
    w, h = x1 - x0, y1 - y0
    for side, (k1, k2), length in (('нижней', ('bottom_left', 'bottom_right'), w), ('правой', ('bottom_right', 'top_right'), h),
                                   ('верхней', ('top_right', 'top_left'), w), ('левой', ('top_left', 'bottom_left'), h)):
        if r[k1] + r[k2] > length + EPS:
            raise GeometryError(f'{obj.get("id")}: радиусы {k1} = {r[k1]:g} и {k2} = {r[k2]:g} не помещаются на {side} стороне '
                                f'длиной {length:g} мм (превышение {r[k1] + r[k2] - length:g} мм)')
    # центры скруглений и углы, на которых начинается дуга каждого угла (обход против часовой)
    spec = {
        'bottom_left': ((x0 + r['bottom_left'], y0 + r['bottom_left']), math.pi),
        'bottom_right': ((x1 - r['bottom_right'], y0 + r['bottom_right']), -math.pi / 2),
        'top_right': ((x1 - r['top_right'], y1 - r['top_right']), 0.0),
        'top_left': ((x0 + r['top_left'], y1 - r['top_left']), math.pi / 2),
    }
    segs: List[Seg] = []
    pts = []  # для каждого угла: (точка входа, точка выхода)
    for k in CORNERS:
        c, s = spec[k]
        if r[k] < 0:
            raise GeometryError(f'{obj.get("id")}: отрицательный радиус {k}')
        if r[k] == 0:
            corner = {'bottom_left': (x0, y0), 'bottom_right': (x1, y0), 'top_right': (x1, y1), 'top_left': (x0, y1)}[k]
            pts.append((corner, corner, None))
        else:
            arc = Arc(c, r[k], s, math.pi / 2)
            pts.append((arc.a, arc.b, arc))
    for i, (pin, pout, arc) in enumerate(pts):
        if arc:
            segs.append(arc)
        nxt = pts[(i + 1) % 4][0]
        if dist(pout, nxt) > EPS:
            segs.append(Line(pout, nxt))
        elif dist(pout, nxt) < -EPS:
            pass
    return segs


def objects_contours(geometry: dict) -> Dict[str, List[Seg]]:
    return {o['id']: contour(o) for o in geometry['objects']}


# ---------------------------------------------------------------- базовые измерения
def dist(p: P, q: P) -> float:
    return math.hypot(p[0] - q[0], p[1] - q[1])


def _angle_in(arc: Arc, ang: float) -> bool:
    """Лежит ли угол на дуге."""
    s, w = arc.start, arc.sweep
    if w < 0:
        s, w = s + w, -w
    d = (ang - s) % (2 * math.pi)
    return d <= w + 1e-12


def point_seg_dist(p: P, s: Seg) -> Tuple[float, P]:
    if isinstance(s, Line):
        (ax, ay), (bx, by) = s.a, s.b
        dx, dy = bx - ax, by - ay
        L2 = dx * dx + dy * dy
        t = 0.0 if L2 == 0 else max(0.0, min(1.0, ((p[0] - ax) * dx + (p[1] - ay) * dy) / L2))
        q = (ax + t * dx, ay + t * dy)
        return dist(p, q), q
    ang = math.atan2(p[1] - s.c[1], p[0] - s.c[0])
    if _angle_in(s, ang) and dist(p, s.c) > EPS:
        q = (s.c[0] + s.r * math.cos(ang), s.c[1] + s.r * math.sin(ang))
        return dist(p, q), q
    da, db = dist(p, s.a), dist(p, s.b)
    return (da, s.a) if da <= db else (db, s.b)


def intersections(s: Seg, t: Seg) -> List[P]:
    """Точки пересечения двух сегментов (касание тоже считается)."""
    if isinstance(s, Line) and isinstance(t, Line):
        return _line_line(s, t)
    if isinstance(s, Arc) and isinstance(t, Arc):
        return _arc_arc(s, t)
    line, arc = (s, t) if isinstance(s, Line) else (t, s)
    return _line_arc(line, arc)


def _line_line(s: Line, t: Line) -> List[P]:
    (x1, y1), (x2, y2), (x3, y3), (x4, y4) = s.a, s.b, t.a, t.b
    d = (x2 - x1) * (y4 - y3) - (y2 - y1) * (x4 - x3)
    if abs(d) < 1e-15:
        # параллельны: общие точки только при наложении на одной прямой
        out = [p for p in (s.a, s.b) if point_seg_dist(p, t)[0] < 1e-9] + [p for p in (t.a, t.b) if point_seg_dist(p, s)[0] < 1e-9]
        return out
    u = ((x3 - x1) * (y4 - y3) - (y3 - y1) * (x4 - x3)) / d
    v = ((x3 - x1) * (y2 - y1) - (y3 - y1) * (x2 - x1)) / d
    if -1e-12 <= u <= 1 + 1e-12 and -1e-12 <= v <= 1 + 1e-12:
        return [(x1 + u * (x2 - x1), y1 + u * (y2 - y1))]
    return []


def _line_arc(s: Line, a: Arc) -> List[P]:
    (x1, y1), (x2, y2) = s.a, s.b
    dx, dy = x2 - x1, y2 - y1
    fx, fy = x1 - a.c[0], y1 - a.c[1]
    A = dx * dx + dy * dy
    B = 2 * (fx * dx + fy * dy)
    C = fx * fx + fy * fy - a.r * a.r
    disc = B * B - 4 * A * C
    if A == 0 or disc < -1e-12:
        return []
    out = []
    for sgn in (-1, 1):
        t = (-B + sgn * math.sqrt(max(0.0, disc))) / (2 * A)
        if -1e-12 <= t <= 1 + 1e-12:
            p = (x1 + t * dx, y1 + t * dy)
            if _angle_in(a, math.atan2(p[1] - a.c[1], p[0] - a.c[0])):
                out.append(p)
    return out


def _arc_arc(s: Arc, t: Arc) -> List[P]:
    d = dist(s.c, t.c)
    if d < EPS:
        if abs(s.r - t.r) > EPS:
            return []
        # одна окружность: общие точки — концы, лежащие на другой дуге
        return [p for p in (s.a, s.b) if _angle_in(t, math.atan2(p[1] - t.c[1], p[0] - t.c[0]))] + \
               [p for p in (t.a, t.b) if _angle_in(s, math.atan2(p[1] - s.c[1], p[0] - s.c[0]))]
    if d > s.r + t.r + 1e-12 or d < abs(s.r - t.r) - 1e-12:
        return []
    a = (s.r * s.r - t.r * t.r + d * d) / (2 * d)
    h = math.sqrt(max(0.0, s.r * s.r - a * a))
    mx, my = s.c[0] + a * (t.c[0] - s.c[0]) / d, s.c[1] + a * (t.c[1] - s.c[1]) / d
    out = []
    for sgn in (-1, 1):
        p = (mx + sgn * h * (t.c[1] - s.c[1]) / d, my - sgn * h * (t.c[0] - s.c[0]) / d)
        if _angle_in(s, math.atan2(p[1] - s.c[1], p[0] - s.c[0])) and _angle_in(t, math.atan2(p[1] - t.c[1], p[0] - t.c[0])):
            out.append(p)
    return out


def seg_seg_dist(s: Seg, t: Seg) -> Tuple[float, P, P]:
    """Минимальное расстояние между сегментами и пара ближайших точек."""
    if intersections(s, t):
        p = intersections(s, t)[0]
        return 0.0, p, p
    best = (math.inf, s.a, t.a)
    for p in _candidates(s, t):
        d, q = point_seg_dist(p, t)
        if d < best[0]:
            best = (d, p, q)
    for p in _candidates(t, s):
        d, q = point_seg_dist(p, s)
        if d < best[0]:
            best = (d, q, p)
    return best


def _candidates(s: Seg, t: Seg) -> List[P]:
    """Точки сегмента s, среди которых есть ближайшая к t (концы и точки на прямой к центру дуги t)."""
    out = [s.a, s.b]
    if isinstance(s, Arc):
        # на дуге s: точка в направлении ближайшей точки t к центру s
        for p in ([t.c] if isinstance(t, Arc) else [point_seg_dist(s.c, t)[1]]):
            ang = math.atan2(p[1] - s.c[1], p[0] - s.c[0])
            for a in (ang, ang + math.pi):
                if _angle_in(s, a):
                    out.append((s.c[0] + s.r * math.cos(a), s.c[1] + s.r * math.sin(a)))
    elif isinstance(t, Arc):
        out.append(point_seg_dist(t.c, s)[1])
    return out


def contour_distance(c1: List[Seg], c2: List[Seg]) -> Tuple[float, P, P]:
    best = (math.inf, (0.0, 0.0), (0.0, 0.0))
    for s in c1:
        for t in c2:
            d = seg_seg_dist(s, t)
            if d[0] < best[0]:
                best = d
    return best


def area(c: List[Seg]) -> float:
    """Площадь со знаком (> 0 при обходе против часовой): формула Грина для отрезков и дуг."""
    total = 0.0
    for s in c:
        if isinstance(s, Line):
            total += s.a[0] * s.b[1] - s.b[0] * s.a[1]
        else:
            # ∮ x dy - y dx по дуге x = cx + r cos t, y = cy + r sin t
            cx, cy, r = s.c[0], s.c[1], s.r
            t0, t1 = s.start, s.start + s.sweep
            total += r * r * s.sweep + cx * r * (math.sin(t1) - math.sin(t0)) - cy * r * (math.cos(t1) - math.cos(t0))
    return total / 2


def bbox(c: List[Seg]) -> Tuple[float, float, float, float]:
    xs, ys = [], []
    for s in c:
        for p in (s.a, s.b):
            xs.append(p[0])
            ys.append(p[1])
        if isinstance(s, Arc):
            for k in range(4):
                ang = k * math.pi / 2
                if _angle_in(s, ang):
                    xs.append(s.c[0] + s.r * math.cos(ang))
                    ys.append(s.c[1] + s.r * math.sin(ang))
    return min(xs), min(ys), max(xs), max(ys)


def seg_points(s: Seg, step: float = 0.5) -> List[P]:
    """Точки вдоль сегмента (для проверки включения и области правки)."""
    if isinstance(s, Line):
        n = max(1, int(math.ceil(dist(s.a, s.b) / step)))
        return [(s.a[0] + (s.b[0] - s.a[0]) * i / n, s.a[1] + (s.b[1] - s.a[1]) * i / n) for i in range(n + 1)]
    n = max(2, int(math.ceil(abs(s.sweep) * s.r / step)))
    return [(s.c[0] + s.r * math.cos(s.start + s.sweep * i / n), s.c[1] + s.r * math.sin(s.start + s.sweep * i / n)) for i in range(n + 1)]


def point_in_contour(p: P, c: List[Seg]) -> bool:
    """Чётность пересечений горизонтального луча вправо с контуром; дуги — точно (пересечение с окружностью).
    Луч сдвинут на 1e-9 мм, чтобы не попадать точно в вершины."""
    px, py = p[0], p[1] + 1e-9
    inside = False
    for s in c:
        if isinstance(s, Line):
            (x1, y1), (x2, y2) = s.a, s.b
            if (y1 > py) != (y2 > py) and x1 + (py - y1) * (x2 - x1) / (y2 - y1) > px:
                inside = not inside
        else:
            dy = py - s.c[1]
            if abs(dy) >= s.r:
                continue
            dx = math.sqrt(s.r * s.r - dy * dy)
            for x in (s.c[0] - dx, s.c[0] + dx):
                if x > px and _angle_in(s, math.atan2(dy, x - s.c[0])):
                    inside = not inside
    return inside


def same_seg(s: Seg, t: Seg, tol: float = 1e-9) -> bool:
    if type(s) is not type(t):
        return False
    if isinstance(s, Line):
        return dist(s.a, t.a) <= tol and dist(s.b, t.b) <= tol
    return dist(s.c, t.c) <= tol and abs(s.r - t.r) <= tol and dist(s.a, t.a) <= tol and dist(s.b, t.b) <= tol


# ---------------------------------------------------------------- SVG
def to_svg_path(c: List[Seg], nd: int = 6) -> str:
    """d для SVG: y_svg = -y; дуга против часовой в физических координатах — sweep-flag 0 в SVG."""
    f = lambda v: f'{round(v, nd) + 0:g}'
    a0 = c[0].a
    parts = [f'M{f(a0[0])},{f(-a0[1])}']
    for s in c:
        if isinstance(s, Line):
            parts.append(f'L{f(s.b[0])},{f(-s.b[1])}')
        else:
            large = 1 if abs(s.sweep) > math.pi else 0
            sweep_flag = 0 if s.sweep > 0 else 1
            parts.append(f'A{f(s.r)},{f(s.r)} 0 {large} {sweep_flag} {f(s.b[0])},{f(-s.b[1])}')
    parts.append('Z')
    return ' '.join(parts)


# ---------------------------------------------------------------- путь SVG -> контуры
def parse_svg_path(d: str) -> List[List[Seg]]:
    """Путь SVG (координаты SVG, y вниз) -> контуры в физических координатах (y вверх)."""
    import re
    toks = re.findall(r'[MmLlHhVvAaZzCcSsQqTt]|[-+]?(?:\d+\.?\d*|\.\d+)(?:[eE][-+]?\d+)?', d)
    rings: List[List[Seg]] = []
    cur: List[Seg] = []
    pos = start = (0.0, 0.0)
    i, cmd = 0, None

    def take(n):
        nonlocal i
        vals = [float(v) for v in toks[i:i + n]]
        if len(vals) < n:
            raise GeometryError('путь SVG оборван')
        i += n
        return vals

    def phys(p):
        return (p[0], -p[1])

    while i < len(toks):
        if toks[i].isalpha():
            cmd = toks[i]
            i += 1
            if cmd in 'Zz':
                if dist(pos, start) > 1e-9:
                    cur.append(Line(phys(pos), phys(start)))
                pos = start
                if cur:
                    rings.append(cur)
                cur = []
                continue
        if cmd is None:
            raise GeometryError('путь SVG без команды')
        c = cmd.upper()
        rel = cmd.islower()
        if c in 'CSQT':
            raise GeometryError('кривые Безье не поддерживаются (только отрезки и дуги окружностей)')
        if c == 'M':
            x, y = take(2)
            if cur:
                rings.append(cur)
                cur = []
            pos = start = (pos[0] + x, pos[1] + y) if rel else (x, y)
            cmd = 'l' if rel else 'L'
        elif c in 'LHV':
            if c == 'L':
                x, y = take(2)
                b = (pos[0] + x, pos[1] + y) if rel else (x, y)
            elif c == 'H':
                (x,) = take(1)
                b = (pos[0] + x if rel else x, pos[1])
            else:
                (y,) = take(1)
                b = (pos[0], pos[1] + y if rel else y)
            if dist(pos, b) > 1e-12:
                cur.append(Line(phys(pos), phys(b)))
            pos = b
        elif c == 'A':
            rx, ry, rot, large, sweep, x, y = take(7)
            b = (pos[0] + x, pos[1] + y) if rel else (x, y)
            if abs(rx - ry) > 1e-6 * max(rx, ry, 1.0):
                raise GeometryError('эллиптические дуги не поддерживаются (только окружности)')
            if dist(pos, b) > 1e-12:
                cur.append(_svg_arc(phys(pos), phys(b), rx, int(large), int(sweep)))
            pos = b
    if cur:
        rings.append(cur)  # незамкнутый контур остаётся как есть — проверка сообщит
    return rings


def _svg_arc(a: P, b: P, r: float, large: int, sweep: int) -> Arc:
    """Дуга SVG в физических координатах: отражение y меняет направление, sweep-flag 0 -> против часовой."""
    ccw = sweep == 0
    mx, my = (a[0] + b[0]) / 2, (a[1] + b[1]) / 2
    half = dist(a, b) / 2
    r = max(r, half)
    h = math.sqrt(max(0.0, r * r - half * half))
    ux, uy = (b[0] - a[0]) / (2 * half), (b[1] - a[1]) / (2 * half)
    # центр слева от хорды при обходе против часовой малой дугой
    left = (ccw and not large) or (not ccw and large)
    nx, ny = (-uy, ux) if left else (uy, -ux)
    c = (mx + nx * h, my + ny * h)
    t0 = math.atan2(a[1] - c[1], a[0] - c[0])
    t1 = math.atan2(b[1] - c[1], b[0] - c[0])
    sw = (t1 - t0) % (2 * math.pi)
    if not ccw:
        sw -= 2 * math.pi
    if sw == 0:
        sw = 2 * math.pi if ccw else -2 * math.pi
    return Arc(c, r, t0, sw)


def interior_point(c: List[Seg]) -> P:
    """Точка внутри контура (для метки области FEMM): центр габарита или ближайшая к нему внутренняя точка сетки."""
    x0, y0, x1, y1 = bbox(c)
    cx, cy = (x0 + x1) / 2, (y0 + y1) / 2
    if point_in_contour((cx, cy), c):
        return (cx, cy)
    n = 40
    best = None
    for i in range(1, n):
        for j in range(1, n):
            p = (x0 + (x1 - x0) * i / n, y0 + (y1 - y0) * j / n)
            if point_in_contour(p, c) and min(point_seg_dist(p, s)[0] for s in c) > 1e-3 * max(x1 - x0, y1 - y0):
                d = dist(p, (cx, cy))
                if best is None or d < best[0]:
                    best = (d, p)
    if best is None:
        raise GeometryError('не найдена внутренняя точка контура')
    return best[1]


def _tangent(s: Seg, at_end: bool) -> P:
    if isinstance(s, Line):
        L = dist(s.a, s.b)
        return ((s.b[0] - s.a[0]) / L, (s.b[1] - s.a[1]) / L)
    t = s.start + (s.sweep if at_end else 0.0)
    k = 1 if s.sweep > 0 else -1
    return (-k * math.sin(t), k * math.cos(t))


def sharp_corners(c: List[Seg], deg: float = 1.0) -> List[P]:
    """Вершины контура, где касательная терпит излом больше deg градусов (острые углы)."""
    out = []
    for i, s in enumerate(c):
        t = c[(i + 1) % len(c)]
        u, v = _tangent(s, True), _tangent(t, False)
        ang = math.degrees(math.acos(max(-1.0, min(1.0, u[0] * v[0] + u[1] * v[1]))))
        if ang > deg:
            out.append(s.b)
    return out


def same_contour(c1: List[Seg], c2: List[Seg], tol: float = 1e-6) -> bool:
    """Совпадение контуров как множеств точек (независимо от записи: начальной точки, разбиения, примитива)."""
    def covered(a, b):
        return all(min(point_seg_dist(p, s)[0] for s in b) <= tol for seg in a for p in seg_points(seg, 0.2))
    return covered(c1, c2) and covered(c2, c1)


def reverse(c: List[Seg]) -> List[Seg]:
    """Тот же контур в обратном направлении обхода."""
    return [Line(s.b, s.a) if isinstance(s, Line) else Arc(s.c, s.r, s.start + s.sweep, -s.sweep) for s in reversed(c)]
