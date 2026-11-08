# -*- coding: utf-8 -*-
"""Выровнять MEP: пять команд в одном меню.

1. На ось опорного        — элемент встаёт на ось опорного (параллельные — соосно,
                             непараллельные — так, чтобы оси пересеклись).
2. На высоту опорного     — сдвиг только по Z до пересечения с осью опорного.
3. Стояк строго вертикально — верхняя точка встаёт ровно над нижней.
4. Лежак строго горизонтально — конец у щелчка остаётся, второй встаёт на его отметку
                             (без отсоединения: отвод и соседняя труба подтягиваются).
5. По образцу              — щёлкнуть участок-образец, затем участок для сдвига;
                             на нём появляются 2 стрелки (вдоль / поперёк подводки)
                             с фактическим сдвигом; щелчок по стрелке ставит участок
                             на ту же линию, что образец, по этому направлению.

У фитингов и арматуры берётся ось соединителя, ближайшего к точке щелчка.
Команды работают по кругу до Esc; каждый шаг — отдельная операция (Ctrl+Z).
v8 · 08.11.2026 (стрелки — одна, в горизонте)
"""
from pyrevit import revit, script
import xyz_forms as forms
from Autodesk.Revit.DB import *
from System.Collections.Generic import List
from Autodesk.Revit.DB.Mechanical import FlexDuct
from Autodesk.Revit.DB.Plumbing import FlexPipe
from Autodesk.Revit.UI.Selection import ObjectType, ISelectionFilter
from Autodesk.Revit.Exceptions import OperationCanceledException

doc = revit.doc
uidoc = revit.uidoc
TOL = 1e-6
MM = 1.0 / 304.8

CMD_AXIS = u"На ось опорного"
CMD_HEIGHT = u"На высоту опорного"
CMD_VERT = u"Стояк строго вертикально"
CMD_HOR = u"Лежак строго горизонтально"
CMD_DIST = u"По образцу"
log = []


# ------------------------------------------------------------ выбор
def _connectors(el):
    try:
        if isinstance(el, MEPCurve):
            return list(el.ConnectorManager.Connectors)
        if isinstance(el, FamilyInstance) and el.MEPModel is not None and el.MEPModel.ConnectorManager is not None:
            return list(el.MEPModel.ConnectorManager.Connectors)
    except Exception:
        pass
    return []


def _is_curve(el):
    return isinstance(el, MEPCurve) and isinstance(el.Location, LocationCurve) \
        and not isinstance(el, FlexDuct) and not isinstance(el, FlexPipe)


class MepFilter(ISelectionFilter):
    def __init__(self, curves_only=False):
        self.curves_only = curves_only

    def AllowElement(self, el):
        if _is_curve(el):
            return True
        if self.curves_only:
            return False
        return len([c for c in _connectors(el) if c.ConnectorType == ConnectorType.End]) > 0

    def AllowReference(self, ref, pt):
        return True


def pick(prompt, curves_only=False):
    """(element, точка щелчка) или (None, None) по Esc."""
    try:
        ref = uidoc.Selection.PickObject(ObjectType.Element, MepFilter(curves_only), prompt)
    except OperationCanceledException:
        return None, None
    el = doc.GetElement(ref.ElementId)
    return el, ref.GlobalPoint


def axis_of(el, pt):
    """Ось элемента: (точка, единичное направление)."""
    if _is_curve(el):
        c = el.Location.Curve
        p0, p1 = c.GetEndPoint(0), c.GetEndPoint(1)
        return p0, (p1 - p0).Normalize()
    conns = [c for c in _connectors(el) if c.ConnectorType == ConnectorType.End]
    if not conns:
        return None, None
    if pt is None:
        c = conns[0]
    else:
        c = min(conns, key=lambda k: k.Origin.DistanceTo(pt))
    return c.Origin, c.CoordinateSystem.BasisZ.Normalize()


# ------------------------------------------------------------ геометрия
def closest_between_lines(p1, d1, p2, d2):
    """Ближайшие точки двух бесконечных прямых. None, если параллельны."""
    w = p1 - p2
    a = d1.DotProduct(d1)
    b = d1.DotProduct(d2)
    c = d2.DotProduct(d2)
    d = d1.DotProduct(w)
    e = d2.DotProduct(w)
    den = a * c - b * b
    if abs(den) < 1e-9:
        return None
    s = (b * e - c * d) / den
    t = (a * e - b * d) / den
    return p1 + d1 * s, p2 + d2 * t


def delta_axis(ref_p, ref_d, tg_p, tg_d):
    """Вектор сдвига цели, чтобы её ось легла на ось опорного (или пересекла её)."""
    if abs(abs(ref_d.DotProduct(tg_d)) - 1) < 1e-6:          # параллельны — соосно
        v = tg_p - ref_p
        proj = ref_p + ref_d * v.DotProduct(ref_d)
        return proj - tg_p
    r = closest_between_lines(tg_p, tg_d, ref_p, ref_d)        # иначе — до пересечения
    if r is None:
        return None
    return r[1] - r[0]


def delta_height(ref_p, ref_d, tg_p, tg_d):
    """Сдвиг цели только по Z до пересечения с осью опорного."""
    rx, ry = XYZ(ref_d.X, ref_d.Y, 0), XYZ(tg_d.X, tg_d.Y, 0)
    if rx.GetLength() < 1e-6 and ry.GetLength() < 1e-6:
        return None                                            # обе вертикальны
    if ry.GetLength() < 1e-6:                                  # цель вертикальна — ничего
        return None
    if rx.GetLength() < 1e-6:                                  # опорный вертикален — высота любая
        return None
    # пересечение проекций в плане
    a1, b1 = XYZ(ref_p.X, ref_p.Y, 0), rx
    a2, b2 = XYZ(tg_p.X, tg_p.Y, 0), ry
    cross = b1.X * b2.Y - b1.Y * b2.X
    if abs(cross) < 1e-9:                                      # параллельны в плане
        v = tg_p - ref_p
        s = XYZ(v.X, v.Y, 0).DotProduct(rx) / rx.DotProduct(rx)
        z_r = ref_p.Z + ref_d.Z * s
        return XYZ(0, 0, z_r - tg_p.Z)
    dx, dy = a2.X - a1.X, a2.Y - a1.Y
    s = (dx * b2.Y - dy * b2.X) / cross                        # параметр на опорном
    t = (dx * b1.Y - dy * b1.X) / cross                        # параметр на цели
    z_r = ref_p.Z + ref_d.Z * s
    z_t = tg_p.Z + tg_d.Z * t
    return XYZ(0, 0, z_r - z_t)


def move(el, v, name):
    if v is None or v.GetLength() < 0.01 * MM:
        return u"уже на месте"
    with revit.Transaction(name):
        ElementTransformUtils.MoveElement(doc, el.Id, v)
    return u"сдвиг {:.0f} мм".format(v.GetLength() / MM)


# ------------------------------------------------------------ команды
def run_align(height_only):
    title = CMD_HEIGHT if height_only else CMD_AXIS
    ref, rpt = pick(u"{}: выберите опорный элемент (Esc — выход)".format(title))
    if ref is None:
        return
    rp, rd = axis_of(ref, rpt)
    if rp is None:
        forms.alert(u"У опорного элемента нет оси.", title=title)
        return
    n = 0
    while True:
        tg, tpt = pick(u"{}: выберите элемент для выравнивания (Esc — выход)".format(title))
        if tg is None:
            break
        if tg.Id == ref.Id:
            continue
        tp, td = axis_of(tg, tpt)
        if tp is None:
            continue
        v = delta_height(rp, rd, tp, td) if height_only else delta_axis(rp, rd, tp, td)
        if v is None:
            forms.alert(u"Для этой пары выравнивание не определено: например, оба элемента "
                        u"вертикальны или опорный — стояк (по высоте подойдёт любая отметка).", title=title)
            continue
        try:
            move(tg, v, title)
            n += 1
        except Exception as ex:
            forms.alert(u"Не удалось сдвинуть элемент:\n{}".format(ex), title=title)
    return n


def make_vertical(el):
    c = el.Location.Curve
    p0, p1 = c.GetEndPoint(0), c.GetEndPoint(1)
    lo, hi = (p0, p1) if p0.Z <= p1.Z else (p1, p0)
    if abs(hi.Z - lo.Z) < 1 * MM:
        return u"не вертикальный"
    new_hi = XYZ(lo.X, lo.Y, hi.Z)
    if new_hi.DistanceTo(hi) < 0.01 * MM:
        return u"уже вертикальный"
    with revit.Transaction(CMD_VERT):
        el.Location.Curve = Line.CreateBound(lo, new_hi) if p0.Z <= p1.Z else Line.CreateBound(new_hi, lo)
    return u"верх сдвинут на {:.0f} мм".format(new_hi.DistanceTo(hi) / MM)


def run_vertical():
    pre = [doc.GetElement(i) for i in uidoc.Selection.GetElementIds()]
    pre = [e for e in pre if _is_curve(e)]
    for e in pre:
        try:
            make_vertical(e)
        except Exception:
            pass
    while True:
        el, _ = pick(u"{}: выберите вертикальную трубу/воздуховод (Esc — выход)".format(CMD_VERT), curves_only=True)
        if el is None:
            break
        try:
            make_vertical(el)
        except Exception as ex:
            forms.alert(u"Не удалось:\n{}".format(ex), title=CMD_VERT)


def make_horizontal(el, pt=None):
    """Убирает уклон: конец, ближний к щелчку, остаётся, у второго Z = как у первого.
    Соединения не разрываются — Revit двигает отвод и подтягивает соседние трубы."""
    c = el.Location.Curve
    p0, p1 = c.GetEndPoint(0), c.GetEndPoint(1)
    dz = abs(p1.Z - p0.Z)
    if dz < 0.001 * MM:
        return u"уже горизонтальный"
    if dz > 0.5 * c.Length:
        return u"это не лежак"
    keep0 = pt is None or p0.DistanceTo(pt) <= p1.DistanceTo(pt)
    with revit.Transaction(CMD_HOR):
        if keep0:
            el.Location.Curve = Line.CreateBound(p0, XYZ(p1.X, p1.Y, p0.Z))
        else:
            el.Location.Curve = Line.CreateBound(XYZ(p0.X, p0.Y, p1.Z), p1)
    c2 = doc.GetElement(el.Id).Location.Curve
    left = abs(c2.GetEndPoint(1).Z - c2.GetEndPoint(0).Z)
    if left > 0.001 * MM:
        return u"уклон остался: {:.1f} мм".format(left / MM)
    return u"перепад {:.1f} мм убран".format(dz / MM)


def run_horizontal():
    pre = [doc.GetElement(i) for i in uidoc.Selection.GetElementIds()]
    pre = [e for e in pre if _is_curve(e)]
    for e in pre:
        try:
            make_horizontal(e)
        except Exception:
            pass
    last = u""
    while True:
        el, pt = pick(u"{}: щёлкните лежак ближе к концу, который не двигать{} (Esc — выход)".format(CMD_HOR, last),
                      curves_only=True)
        if el is None:
            break
        try:
            last = u" (прошлый: {})".format(make_horizontal(el, pt))
        except Exception as ex:
            forms.alert(u"Не удалось:\n{}".format(ex), title=CMD_HOR)


def mid_axis(el):
    c = el.Location.Curve
    return (c.GetEndPoint(0) + c.GetEndPoint(1)) * 0.5


def curve_dir(el):
    c = el.Location.Curve
    return (c.GetEndPoint(1) - c.GetEndPoint(0)).Normalize()


def _perp(v, axis):
    w = v - axis * v.DotProduct(axis)
    return w.Normalize() if w.GetLength() > 1e-6 else None


def _neighbour_dirs(el):
    """Направления труб, примыкающих к участку через фитинги (или напрямую)."""
    out = []
    for c in _connectors(el):
        for r in c.AllRefs:
            o = r.Owner
            if o is None or o.Id == el.Id:
                continue
            cands = [o] if _is_curve(o) else []
            if not cands:
                for c2 in _connectors(o):
                    for r2 in c2.AllRefs:
                        o2 = r2.Owner
                        if o2 is not None and o2.Id != el.Id and o2.Id != o.Id and _is_curve(o2):
                            cands.append(o2)
            for p in cands:
                out.append(curve_dir(p))
    return out


def axes_for(el):
    """Два направления поперёк участка: [0] по примыкающей трубе, [1] поперёк."""
    d = curve_dir(el)
    a1 = None
    for nd in _neighbour_dirs(el):
        a1 = _perp(nd, d)
        if a1 is not None:
            break
    if a1 is None:
        if abs(d.Z) > 0.9:
            a1 = XYZ.BasisX
        else:
            a1 = _perp(XYZ.BasisZ, d)
    a2 = d.CrossProduct(a1).Normalize()
    return [a1, a2]


AXIS_NAMES = [u"вдоль подводки", u"поперёк подводки"]
AXIS_COLORS = [Color(220, 40, 40), Color(30, 100, 230)]


def _solid_fill():
    for fp in FilteredElementCollector(doc).OfClass(FillPatternElement):
        try:
            if fp.GetFillPattern().IsSolidFill:
                return fp.Id
        except Exception:
            pass
    return None


def _arrow_solids(o, d, L, hl, b_d):
    """Одна плоская стрелка в горизонтальной плоскости (db 08.11: «только в одном исполнении, в горизонте»).
    Вертикальная стрелка (сдвиг по высоте) — плоскостью к виду, иначе её не видно."""
    hw, sw = hl * 0.55, hl * 0.2
    s = d.CrossProduct(XYZ.BasisZ)
    if s.GetLength() < 1e-6:
        try:
            s = d.CrossProduct(doc.ActiveView.ViewDirection)
        except Exception:
            s = XYZ.BasisX
        if s.GetLength() < 1e-6:
            s = XYZ.BasisX
    s = s.Normalize()
    n = d.CrossProduct(s).Normalize()
    th = sw * 0.8
    base = o - n * (th / 2)
    P = lambda t, w: base + d * t + s * w
    pts = [P(0, -sw), P(L - hl, -sw), P(L - hl, -hw), P(L, 0), P(L - hl, hw), P(L - hl, sw), P(0, sw)]
    loop = CurveLoop()
    for i in range(len(pts)):
        loop.Append(Line.CreateBound(pts[i], pts[(i + 1) % len(pts)]))
    return [GeometryCreationUtilities.CreateExtrusionGeometry(List[CurveLoop]([loop]), n, th)]


def _view_size():
    try:
        uiv = [v for v in uidoc.GetOpenUIViews() if v.ViewId == doc.ActiveView.Id][0]
        c = uiv.GetZoomCorners()
        return c[0].DistanceTo(c[1])
    except Exception:
        return 3000 * MM


def _visible_ids(view):
    try:
        if view.IsInTemporaryViewMode(TemporaryViewMode.TemporaryHideIsolate):
            return [e.Id for e in FilteredElementCollector(doc, view.Id).WhereElementIsNotElementType()
                    if view.IsElementVisibleInTemporaryViewMode(TemporaryViewMode.TemporaryHideIsolate, e.Id)]
    except Exception:
        pass
    return None


def _isolate(view, ids):
    try:
        view.IsolateElementsTemporary(List[ElementId](ids))
    except Exception:
        pass


def choose_shift(riser, shifts, vis):
    """shifts: [(ось, вектор сдвига, мм)]. Рисует у участка цветные стрелки
    фактического сдвига, ждёт щелчка. Возвращает вектор или None.
    Стрелки — временные, откатываются (в модели и в отмене не остаются)."""
    view = doc.ActiveView
    cand = [(i, v) for i, v in enumerate(shifts) if v is not None and v.GetLength() > 0.5 * MM]
    if not cand:
        return None
    labels = u", ".join(u"{} {} {:.0f} мм".format(u"красная" if i == 0 else u"синяя", AXIS_NAMES[i], v.GetLength() / MM)
                        for i, v in cand)
    try:
        hidden = view.GetCategoryHidden(ElementId(BuiltInCategory.OST_GenericModel))
    except Exception:
        hidden = False
    if hidden:
        opts = [u"{} {:.0f} мм".format(AXIS_NAMES[i], v.GetLength() / MM) for i, v in cand]
        ch = forms.CommandSwitchWindow.show(opts, message=u"Куда сдвинуть участок?")
        return cand[opts.index(ch)][1] if ch in opts else None
    o = mid_axis(riser)
    b_d = curve_dir(riser)
    size = _view_size()
    hl = size * 0.04
    Lmin = size * 0.15
    fill = _solid_fill()
    ids = {}
    tg = TransactionGroup(doc, CMD_DIST)
    tg.Start()
    chosen = None
    try:
        t = Transaction(doc, u"стрелки")
        t.Start()
        for i, v in cand:
            d = v.Normalize()
            L = max(v.GetLength(), Lmin)
            ds = DirectShape.CreateElement(doc, ElementId(BuiltInCategory.OST_GenericModel))
            ds.SetShape(List[GeometryObject](_arrow_solids(o, d, L, min(hl, L * 0.45), b_d)))
            ogs = OverrideGraphicSettings()
            col = AXIS_COLORS[i]
            ogs.SetProjectionLineColor(col)
            ogs.SetProjectionLineWeight(6)
            if fill is not None:
                ogs.SetSurfaceForegroundPatternId(fill)
                ogs.SetSurfaceForegroundPatternColor(col)
            view.SetElementOverrides(ds.Id, ogs)
            ids[ds.Id.Value] = v
        if vis is not None:
            _isolate(view, vis + [ElementId(k) for k in ids])
        t.Commit()
        uidoc.RefreshActiveView()
        try:
            ref = uidoc.Selection.PickObject(ObjectType.Element, IdFilter(ids.keys()),
                u"{}: щёлкните стрелку ({}) (Esc — пропустить)".format(CMD_DIST, labels))
            chosen = ids.get(ref.ElementId.Value)
        except OperationCanceledException:
            chosen = None
    finally:
        tg.RollBack()
        if vis is not None:
            _isolate(view, vis)
        uidoc.RefreshActiveView()
    return chosen


class IdFilter(ISelectionFilter):
    def __init__(self, ids):
        self.ids = set(ids)

    def AllowElement(self, el):
        return el.Id.Value in self.ids

    def AllowReference(self, ref, pt):
        return True


def run_distance():
    smp, _ = pick(u"{}: щёлкните участок-образец (Esc — выход)".format(CMD_DIST), curves_only=True)
    if smp is None:
        return
    m1 = mid_axis(smp)
    log.append(u"Образец: участок {}".format(smp.Id.Value))
    vis = _visible_ids(doc.ActiveView)
    last = u""
    while True:
        tg, _ = pick(u"{}: щёлкните участок, который сдвинуть{} (Esc — выход)".format(CMD_DIST, last),
                     curves_only=True)
        if tg is None:
            break
        if tg.Id == smp.Id:
            continue
        m2 = mid_axis(tg)
        axes = axes_for(tg)
        shifts = [a * (m1 - m2).DotProduct(a) for a in axes]
        if all(x.GetLength() <= 0.5 * MM for x in shifts):
            last = u" (прошлый уже как образец)"
            log.append(u"Участок {}: уже как образец".format(tg.Id.Value))
            continue
        v = choose_shift(tg, shifts, vis)
        if v is None:
            last = u" (прошлый пропущен)"
            continue
        try:
            res = move(tg, v, CMD_DIST)
            last = u" (прошлый: {})".format(res)
            log.append(u"Участок {}: {}".format(tg.Id.Value, res))
        except Exception as ex:
            log.append(u"Ошибка: {}".format(ex))
            forms.alert(u"Не удалось сдвинуть элемент:\n{}".format(ex), title=CMD_DIST)


# ------------------------------------------------------------ меню
choice = forms.CommandSwitchWindow.show(
    [CMD_AXIS, CMD_HEIGHT, CMD_VERT, CMD_HOR, CMD_DIST],
    message=u"Выровнять MEP",
    title=u"Трубы, воздуховоды, лотки, короба, фитинги")
if choice == CMD_AXIS:
    run_align(False)
elif choice == CMD_HEIGHT:
    run_align(True)
elif choice == CMD_VERT:
    run_vertical()
elif choice == CMD_HOR:
    run_horizontal()
elif choice == CMD_DIST:
    try:
        run_distance()
    except Exception:
        import traceback
        log.append(traceback.format_exc())
    if any(l.startswith(u"Ошибка") or u"Traceback" in l for l in log):
        out = script.get_output()
        out.print_md(u"**{}** — журнал".format(CMD_DIST))
        for line in log:
            print(line)
