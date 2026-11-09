# -*- coding: utf-8 -*-
"""Марки без наездов (db, 08.11.2026).

Активный 3D-вид или план; выделенные марки (если выделены) или все марки вида.
1) Конец выноски «в космосе» (далеко от смещённого разносом хозяина) — ставится на
   хозяина: труба/воздуховод — середина, точечный элемент — LocationPoint.
2) Голова марки — туда, где рамка текста не пересекает трубы/воздуховоды,
   оборудование/приборы и уже поставленные марки (перебор кандидатов слева/справа
   на 4 расстояниях и 7 высотах). Размеры рамки — от масштаба вида.
Не трогает: марки с изломом выноски (излом не в голове), марки, стоящие колонкой
(одинаковый X головы, ровный шаг по Y), марки с несколькими выносками.
Shift+щелчок — только показать: выделяет марки, которые были бы передвинуты.

Перенос эталона C# (placer_reference.cs, проверен на модели Береста) на IronPython.
Все расстояния — футы модели в координатах вида (x — вправо, y — вверх).
"""
import sys
import math

sys.modules.pop('xyz_leader', None)
import xyz_leader
import xyz_forms as forms

from System.Collections.Generic import List
from Autodesk.Revit.DB import (
    BuiltInCategory, ElementId, FilteredElementCollector, IndependentTag,
    LeaderEndCondition, LocationCurve, LocationPoint, SubTransaction,
    Transaction, View3D, ViewPlan, XYZ,
)

TITLE = u'Марки без наездов'
TR_NAME = u'XYZ: Марки без наездов'

uidoc = __revit__.ActiveUIDocument   # noqa: F821
doc = uidoc.Document
view = doc.ActiveView

try:
    SHOW_ONLY = bool(__shiftclick__)    # noqa: F821  (pyRevit)
except NameError:
    SHOW_ONLY = False

# ------------------------------------------------------------------
# Настройки
# ------------------------------------------------------------------
# допуски для «не трогать» — мм на бумаге
ELBOW_TOL_MM = 0.5      # излом дальше этого от головы — марка с изломом
COL_X_TOL_MM = 0.3      # головы с разницей X меньше — «один X»
COL_MAX_STEP_MM = 15.0  # шаг по Y больше — уже не колонка
COL_STEP_TOL = 0.25     # колонка из 3+ марок: шаги равны с точностью 25 % (или 0,5 мм)
COL_MIN = 2             # сколько марок с одним X и шагом — уже колонка
GRID_CELL = 3.0         # ячейка сетки поиска (футы × S) — только ускорение

MEP_CURVES = [BuiltInCategory.OST_PipeCurves, BuiltInCategory.OST_FlexPipeCurves,
              BuiltInCategory.OST_DuctCurves, BuiltInCategory.OST_FlexDuctCurves]
MEP_BOXES = [BuiltInCategory.OST_PlumbingFixtures, BuiltInCategory.OST_MechanicalEquipment,
             BuiltInCategory.OST_DuctTerminal, BuiltInCategory.OST_DuctAccessory]
MECH_EQ = int(BuiltInCategory.OST_MechanicalEquipment)

# кандидаты головы (как в эталоне): отступ L·S от рамки, сторона, сдвиг по Y·S
CAND_L = (1.0, 1.6, 2.4, 3.4)
CAND_SX = (1, -1)
CAND_DY = (0.0, 0.9, -0.9, 1.8, -1.8, 2.7, -2.7)

_iv = xyz_leader._iv


def _mm(mm):
    """мм на бумаге -> футы модели при масштабе вида"""
    return mm / 304.8 * view.Scale


# ------------------------------------------------------------------
# Проверка вида
# ------------------------------------------------------------------
if isinstance(view, View3D):
    if view.IsPerspective:
        forms.alert(u'Перспективный 3D-вид не поддерживается — нужен изометрический 3D или план.',
                    title=TITLE, exitscript=True)
elif not isinstance(view, ViewPlan):
    forms.alert(u'Откройте 3D-вид (схему) или план.', title=TITLE, exitscript=True)

RT = view.RightDirection
UP = view.UpDirection
S = view.Scale / 50.0


def X(p):
    return p.DotProduct(RT)


def Y(p):
    return p.DotProduct(UP)


DISP = xyz_leader.displacements(doc, view)


def D(eid):
    return DISP.get(_iv(eid), XYZ.Zero)


# ------------------------------------------------------------------
# Сетка (ускорение перебора; результат тот же, что полный перебор)
# ------------------------------------------------------------------
class Grid(object):
    def __init__(self, cell):
        self.cell = cell
        self.cells = {}
        self.items = []

    def _range(self, x0, y0, x1, y1):
        c = self.cell
        return (int(math.floor(x0 / c)), int(math.floor(y0 / c)),
                int(math.floor(x1 / c)), int(math.floor(y1 / c)))

    def add(self, item, x0, y0, x1, y1):
        k = len(self.items)
        self.items.append(item)
        i0, j0, i1, j1 = self._range(min(x0, x1), min(y0, y1), max(x0, x1), max(y0, y1))
        for i in range(i0, i1 + 1):
            for j in range(j0, j1 + 1):
                self.cells.setdefault((i, j), []).append(k)

    def query(self, x0, y0, x1, y1):
        i0, j0, i1, j1 = self._range(min(x0, x1), min(y0, y1), max(x0, x1), max(y0, y1))
        seen = set()
        out = []
        cells = self.cells
        for i in range(i0, i1 + 1):
            for j in range(j0, j1 + 1):
                lst = cells.get((i, j))
                if not lst:
                    continue
                for k in lst:
                    if k not in seen:
                        seen.add(k)
                        out.append(self.items[k])
        return out


def seg_box(s, bx):
    """Отрезок s=[x0,y0,x1,y1] пересекает рамку bx=[x0,y0,x1,y1] (Лян — Барски)."""
    x0, y0 = s[0], s[1]
    dx, dy = s[2] - s[0], s[3] - s[1]
    t0, t1 = 0.0, 1.0
    p = (-dx, dx, -dy, dy)
    q = (x0 - bx[0], bx[2] - x0, y0 - bx[1], bx[3] - y0)
    for i in range(4):
        if abs(p[i]) < 1e-12:
            if q[i] < 0:
                return False
        else:
            r = q[i] / p[i]
            if p[i] < 0:
                if r > t1:
                    return False
                if r > t0:
                    t0 = r
            else:
                if r < t0:
                    return False
                if r < t1:
                    t1 = r
    return True


def box_box(a, b):
    return a[0] < b[2] and b[0] < a[2] and a[1] < b[3] and b[1] < a[3]


# ------------------------------------------------------------------
# Препятствия: трубы/воздуховоды (отрезки) и оборудование/приборы (рамки)
# ------------------------------------------------------------------
CELL = GRID_CELL * S
segs = Grid(CELL)
for c in MEP_CURVES:
    for e in FilteredElementCollector(doc, view.Id).OfCategory(c).WhereElementIsNotElementType():
        lc = e.Location
        if not isinstance(lc, LocationCurve):
            continue
        try:
            dd = D(e.Id)
            a = lc.Curve.GetEndPoint(0) + dd
            b = lc.Curve.GetEndPoint(1) + dd
        except Exception:
            continue
        s = [X(a), Y(a), X(b), Y(b)]
        segs.add(s, s[0], s[1], s[2], s[3])

boxes = Grid(CELL)
for c in MEP_BOXES:
    for e in FilteredElementCollector(doc, view.Id).OfCategory(c).WhereElementIsNotElementType():
        bb = e.get_BoundingBox(view)
        if bb is None:
            continue
        dd = D(e.Id)
        mn, mx = bb.Min, bb.Max
        x0, x1, y0, y1 = 1e9, -1e9, 1e9, -1e9
        for p in (mn, mx,
                  XYZ(mn.X, mx.Y, mn.Z), XYZ(mx.X, mn.Y, mx.Z),
                  XYZ(mn.X, mn.Y, mx.Z), XYZ(mx.X, mx.Y, mn.Z),
                  XYZ(mn.X, mx.Y, mx.Z), XYZ(mx.X, mn.Y, mn.Z)):
            q = p + dd
            qx, qy = X(q), Y(q)
            x0, x1 = min(x0, qx), max(x1, qx)
            y0, y1 = min(y0, qy), max(y1, qy)
        if (x1 - x0) < 0.3 * S and (y1 - y0) < 0.3 * S:
            continue
        bxx = [x0 + 0.15 * S, y0 + 0.15 * S, x1 - 0.15 * S, y1 - 0.15 * S]
        boxes.add(bxx, bxx[0], bxx[1], bxx[2], bxx[3])


# ------------------------------------------------------------------
# Марки
# ------------------------------------------------------------------
def _refs(t):
    try:
        return list(t.GetTaggedReferences())
    except Exception:
        return []


def _half_size(t, host):
    """Полуширина/полувысота рамки текста марки (футы модели), как в эталоне."""
    try:
        txt = t.TagText or u''
    except Exception:
        txt = u''
    n = len(txt)
    if txt.startswith(u'H'):
        try:
            v = round(float(txt[3:].strip()) / 5.0) * 5.0
            n = len(u'H= %d' % int(v))
        except Exception:
            pass
    hw, hh = (0.16 * n + 0.15) * S, 0.38 * S
    cat = host.Category if host is not None else None
    if cat is not None and _iv(cat.Id) == MECH_EQ:
        hw, hh = 1.75 * S, 1.05 * S
    elif n > 14:
        hw = (0.16 * 14 + 0.15) * S
    return hw, hh


def _has_bad_elbow(t, r):
    """Излом есть и не совпадает с головой марки (в плоскости вида)."""
    try:
        if not t.HasLeaderElbow(r):
            return False
        el = t.GetLeaderElbow(r)
    except Exception:
        return False
    h = t.TagHeadPosition
    return math.hypot(X(el) - X(h), Y(el) - Y(h)) > _mm(ELBOW_TOL_MM)


all_tags = list(FilteredElementCollector(doc, view.Id).OfClass(IndependentTag))
if not all_tags:
    forms.alert(u'На виде нет марок.', title=TITLE, exitscript=True)

# что обрабатываем: выделенные марки, иначе все марки вида
sel_ids = set(_iv(i) for i in uidoc.Selection.GetElementIds())
sel_tags = [t for t in all_tags if _iv(t.Id) in sel_ids]
work_ids = set(_iv(t.Id) for t in (sel_tags or all_tags))
scope = u'выделенные марки' if sel_tags else u'все марки вида'

# --- колонки: один X головы, ровный шаг по Y (по всем маркам вида) ---
column_ids = set()
heads = []
for t in all_tags:
    try:
        h = t.TagHeadPosition
        heads.append((X(h), Y(h), _iv(t.Id)))
    except Exception:
        pass
heads.sort()
x_tol, max_step = _mm(COL_X_TOL_MM), _mm(COL_MAX_STEP_MM)
i = 0
while i < len(heads):
    j = i + 1
    while j < len(heads) and heads[j][0] - heads[j - 1][0] <= x_tol:
        j += 1
    grp = sorted(heads[i:j], key=lambda h: h[1])
    # разбить на подряд идущие с шагом не больше max_step
    runs, cur = [], [grp[0]]
    for h in grp[1:]:
        if h[1] - cur[-1][1] <= max_step:
            cur.append(h)
        else:
            runs.append(cur)
            cur = [h]
    runs.append(cur)
    for run in runs:
        if len(run) < COL_MIN:
            continue
        if len(run) >= 3:
            steps = [run[k + 1][1] - run[k][1] for k in range(len(run) - 1)]
            mean = sum(steps) / len(steps)
            if max(abs(s - mean) for s in steps) > max(COL_STEP_TOL * mean, _mm(0.5)):
                continue
        for h in run:
            column_ids.add(h[2])
    i = j

# --- разбор марок ---
info = []          # (t, r, ex, ey, hw, hh, fix)
placed = Grid(CELL)
n_col = n_elbow = n_multi = 0


def _fixed_obstacle(t):
    """Марку не двигаем — её рамка препятствие на нынешнем месте."""
    try:
        host = None
        ids = list(t.GetTaggedLocalElementIds())
        if ids:
            host = doc.GetElement(ids[0])
        hw, hh = _half_size(t, host)
        h = t.TagHeadPosition
        hx, hy = X(h), Y(h)
        b = [hx - hw, hy - hh, hx + hw, hy + hh]
        placed.add(b, b[0], b[1], b[2], b[3])
    except Exception:
        pass


for t in all_tags:
    tid = _iv(t.Id)
    if tid not in work_ids:
        _fixed_obstacle(t)
        continue
    refs = _refs(t)
    if not refs or not t.HasLeader:
        _fixed_obstacle(t)
        continue
    if tid in column_ids:
        n_col += 1
        _fixed_obstacle(t)
        continue
    if len(refs) > 1:
        n_multi += 1
        _fixed_obstacle(t)
        continue
    r = refs[0]
    if _has_bad_elbow(t, r):
        n_elbow += 1
        _fixed_obstacle(t)
        continue
    hids = list(t.GetTaggedLocalElementIds())
    he = doc.GetElement(hids[0]) if hids else None
    if he is None:
        _fixed_obstacle(t)
        continue
    try:
        E = t.GetLeaderEnd(r)
    except Exception:
        _fixed_obstacle(t)
        continue
    dd = D(he.Id)
    ex, ey = X(E), Y(E)
    tx, ty, fix = ex, ey, False
    loc = he.Location
    if isinstance(loc, LocationCurve):
        cv = loc.Curve
        a = cv.GetEndPoint(0) + dd
        b = cv.GetEndPoint(1) + dd
        ax, ay, bx, by = X(a), Y(a), X(b), Y(b)
        vx, vy = bx - ax, by - ay
        L2 = vx * vx + vy * vy
        tt = 0.5 if L2 < 1e-9 else max(0.0, min(1.0, ((ex - ax) * vx + (ey - ay) * vy) / L2))
        qx, qy = ax + tt * vx, ay + tt * vy
        if math.hypot(qx - ex, qy - ey) > 0.4 * S:
            tx, ty, fix = ax + 0.5 * vx, ay + 0.5 * vy, True
    elif isinstance(loc, LocationPoint):
        p = loc.Point + dd
        bb = he.get_BoundingBox(view)
        rad = 0.5 * S if bb is None else max(0.5 * S, 0.5 * bb.Min.DistanceTo(bb.Max))
        if math.hypot(X(p) - ex, Y(p) - ey) > rad:
            tx, ty, fix = X(p), Y(p), True
    hw, hh = _half_size(t, he)
    info.append((t, r, tx, ty, hw, hh, fix))

if not info:
    forms.alert(u'Нечего обрабатывать (%s).\nПропущено: колонки %d, изломы %d, несколько выносок %d.'
                % (scope, n_col, n_elbow, n_multi), title=TITLE, exitscript=True)


# ------------------------------------------------------------------
# Оценка места головы (как в эталоне)
# ------------------------------------------------------------------
def score(ex, ey, hx, hy, hw, hh):
    bx = [hx - hw, hy - hh, hx + hw, hy + hh]
    s = 0
    for sg in segs.query(bx[0], bx[1], bx[2], bx[3]):
        if seg_box(sg, bx):
            s += 3
    for b in boxes.query(bx[0], bx[1], bx[2], bx[3]):
        if box_box(bx, b):
            s += 3
    for b in placed.query(bx[0], bx[1], bx[2], bx[3]):
        if box_box(bx, b):
            s += 5
    lx = hx - hw if hx > ex else hx + hw
    if abs(hx - ex) < hw:
        lx = hx
    if abs(hx - ex) < hw:
        ly = hy - hh if hy > ey else hy + hh
    else:
        ly = hy
    ld = [ex + (lx - ex) * 0.15, ey + (ly - ey) * 0.15, lx, ly]
    for b in placed.query(ld[0], ld[1], ld[2], ld[3]):
        if seg_box(ld, b):
            s += 2
    return s


# ------------------------------------------------------------------
# Расстановка
# ------------------------------------------------------------------
plan = []          # (t, r, Eold, ex, ey, bdx, bdy, fix)
n_left = 0
before = 0
for (t, r, ex, ey, hw, hh, fix) in info:
    Eold = t.GetLeaderEnd(r)
    H = t.TagHeadPosition
    cdx, cdy = X(H) - X(Eold), Y(H) - Y(Eold)
    sc0 = score(ex, ey, ex + cdx, ey + cdy, hw, hh)
    before += sc0
    bdx, bdy, best, bestd = cdx, cdy, sc0, 0.0
    if sc0 > 0:
        for L in CAND_L:
            for sx in CAND_SX:
                for dy in CAND_DY:
                    dx = sx * (hw + L * S)
                    dyy = dy * S
                    s = score(ex, ey, ex + dx, ey + dyy, hw, hh)
                    dist = abs(dx) + abs(dyy)
                    if s < best or (s == best and dist < bestd - 1e-9 and s < sc0):
                        best, bdx, bdy, bestd = s, dx, dyy, dist
    b = [ex + bdx - hw, ey + bdy - hh, ex + bdx + hw, ey + bdy + hh]
    placed.add(b, b[0], b[1], b[2], b[3])
    if best > 0:
        n_left += 1
    if fix or abs(bdx - cdx) > 1e-6 or abs(bdy - cdy) > 1e-6:
        plan.append((t, r, Eold, ex, ey, bdx, bdy, fix))

skipped = n_col + n_elbow + n_multi
skip_txt = (u'Не тронуты: колонки — %d, с изломом — %d, с несколькими выносками — %d (всего %d).'
            % (n_col, n_elbow, n_multi, skipped))
n_move_space = sum(1 for p in plan if p[7])

# ------------------------------------------------------------------
# Только показать (Shift+щелчок)
# ------------------------------------------------------------------
if SHOW_ONLY:
    ids = List[ElementId]()
    for p in plan:
        ids.Add(p[0].Id)
    uidoc.Selection.SetElementIds(ids)
    forms.alert(u'Только показать (%s): ничего не передвинуто.\n\n'
                u'Были бы передвинуты: %d (выделены)\n'
                u'из них конец выноски «из космоса»: %d\n'
                u'Останутся с наездами: %d\n\n%s'
                % (scope, len(plan), n_move_space, n_left, skip_txt), title=TITLE)
    sys.exit()

# ------------------------------------------------------------------
# Применить — одна транзакция
# ------------------------------------------------------------------
moved = moved_space = errors = 0
err_ids = []
tr = Transaction(doc, TR_NAME)
tr.Start()
try:
    for (t, r, Eold, ex, ey, bdx, bdy, fix) in plan:
        st = SubTransaction(doc)
        st.Start()
        try:
            En = Eold + RT.Multiply(ex - X(Eold)) + UP.Multiply(ey - Y(Eold))
            Hn = En + RT.Multiply(bdx) + UP.Multiply(bdy)
            t.TagHeadPosition = Hn
            if t.LeaderEndCondition == LeaderEndCondition.Free:
                t.SetLeaderEnd(r, En)
            if t.HasLeaderElbow(r):
                t.SetLeaderElbow(r, Hn)
            st.Commit()
            moved += 1
            if fix:
                moved_space += 1
        except Exception:
            st.RollBack()
            errors += 1
            err_ids.append(t.Id)
    tr.Commit()
except Exception as ex:
    if tr.HasStarted() and not tr.HasEnded():
        tr.RollBack()
    forms.alert(u'Не получилось, изменения отменены:\n%s' % ex, title=TITLE, exitscript=True)

msg = (u'Обработаны %s: %d.\n\n'
       u'Передвинуто: %d\n'
       u'из них конец выноски «из космоса» — на хозяина: %d\n'
       u'Остались с наездами (лучше места не нашлось): %d\n\n%s'
       % (scope, len(info), moved, moved_space, n_left, skip_txt))
if errors:
    ids = List[ElementId]()
    for i in err_ids:
        ids.Add(i)
    uidoc.Selection.SetElementIds(ids)
    msg += u'\n\nНе удалось передвинуть: %d (выделены).' % errors
forms.alert(msg, title=TITLE)
