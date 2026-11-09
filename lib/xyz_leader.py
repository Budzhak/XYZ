# -*- coding: utf-8 -*-
"""Прямая выноска марки к указанной точке (db, 18.10.2026).

Щелчок по марке → точка, где должна стоять марка. Выноска становится прямой:
- точка выше/ниже нынешнего конца выноски → вертикальная выноска, конец выноски
  сдвигается вдоль оси трубы туда, где она под маркой;
- левее/правее → горизонтальная, конец сдвигается туда, где труба на высоте марки;
- если труба так не проходит (вертикальная на листе, марка за её концами) — другое
  направление; не выходит и оно — выноска с изломом (вертикаль, потом полка).
Марки на точечных элементах (оборудование, арматура): конец выноски остаётся, марка
встаёт строго над/под/сбоку от него.

    import xyz_leader
    xyz_leader.straight(doc, view, tag, head_xyz)   # в открытой транзакции
"""
from Autodesk.Revit.DB import (DisplacementElement, FilteredElementCollector, LeaderEndCondition,
                               LocationCurve, LocationPoint, XYZ)


def displacements(doc, view):
    out = {}
    for de in FilteredElementCollector(doc, view.Id).OfClass(DisplacementElement):
        d = de.GetAbsoluteDisplacement()
        for i in de.GetDisplacedElementIds():
            out[_iv(i)] = d
    return out


def _iv(eid):
    try:
        return eid.Value
    except AttributeError:
        return eid.IntegerValue


def _reset(tag):
    try:
        if not tag.HasLeader:
            tag.HasLeader = True
        tag.LeaderEndCondition = LeaderEndCondition.Attached
        tag.Document.Regenerate()
        tag.LeaderEndCondition = LeaderEndCondition.Free
    except Exception:
        pass


def _ref(tag):
    for r in tag.GetTaggedReferences():
        return r
    return None


def solve(view, a, b, head, cur=None, t_lo=0.02):
    """Точка на отрезке a–b (3D, уже со смещением разноса) под/над/сбоку от head.
    cur — нынешний конец выноски (для выбора направления). -> (t, режим 'v'|'h'|'elbow')."""
    R, U = view.RightDirection, view.UpDirection
    au, av, bu, bv = a.DotProduct(R), a.DotProduct(U), b.DotProduct(R), b.DotProduct(U)
    hu, hv = head.DotProduct(R), head.DotProduct(U)
    if cur is None:
        cu, cv = (au + bu) / 2.0, (av + bv) / 2.0
    else:
        cu, cv = cur.DotProduct(R), cur.DotProduct(U)
    prefer = 'v' if abs(hv - cv) >= abs(hu - cu) else 'h'

    def tpar(mode):
        den = (bu - au) if mode == 'v' else (bv - av)
        L = ((bu - au) ** 2 + (bv - av) ** 2) ** 0.5
        if L < 1e-9 or abs(den) < 0.15 * L:      # труба почти вдоль выноски — так нельзя
            return None
        t = ((hu - au) / den) if mode == 'v' else ((hv - av) / den)
        return t

    # 09.11 (db: «Прямая выноска» демонстрировала угловую): если щелчок за пределами участка,
    # раньше выходил излом. Теперь конец выноски прижимается к ближайшему краю участка,
    # а марка сдвигается вдоль выноски — выноска остаётся прямой. Излом — только если труба
    # идёт вдоль обоих направлений (на листе почти точка).
    best = None
    for k, mode in enumerate((prefer, 'h' if prefer == 'v' else 'v')):
        t = tpar(mode)
        if t is None:
            continue
        tc = max(t_lo, min(1.0 - t_lo, t))
        # насколько сдвинется марка от точки щелчка (в единицах вида)
        eu, ev = au + (bu - au) * tc, av + (bv - av) * tc
        shift = abs(hv - ev) if mode == 'h' else abs(hu - eu)
        if tc == t:
            return t, mode
        cost = shift + (0 if k == 0 else 1e-6)
        if best is None or cost < best[0]:
            best = (cost, tc, mode)
    if best is not None:
        return best[1], best[2]
    # излом: ближайшая к марке точка трубы
    L2 = (bu - au) ** 2 + (bv - av) ** 2
    t = 0.5 if L2 < 1e-12 else ((hu - au) * (bu - au) + (hv - av) * (bv - av)) / L2
    return max(0.05, min(0.95, t)), 'elbow'


def straight(doc, view, tag, head, disp=None):
    """Перерисовать марку прямой выноской к точке head (3D). Возвращает режим."""
    R, U = view.RightDirection, view.UpDirection
    disp = disp if disp is not None else displacements(doc, view)
    ref = _ref(tag)
    host = None
    for e in tag.GetTaggedLocalElements():
        host = e
        break
    cur = None
    try:
        if tag.HasLeader and tag.LeaderEndCondition == LeaderEndCondition.Free:
            cur = tag.GetLeaderEnd(ref)
    except Exception:
        cur = None
    d = disp.get(_iv(host.Id), XYZ.Zero) if host is not None else XYZ.Zero
    lc = host.Location if host is not None else None
    if isinstance(lc, LocationCurve):
        c = lc.Curve
        a, b = c.GetEndPoint(0) + d, c.GetEndPoint(1) + d
        t, mode = solve(view, a, b, head, cur)
        end = a + (b - a) * t
    else:
        if cur is None:
            p = lc.Point if isinstance(lc, LocationPoint) else None
            if p is None:
                bb = host.get_BoundingBox(None)
                p = (bb.Min + bb.Max) * 0.5
            cur = p + d
        end = cur
        du, dv = (head - end).DotProduct(R), (head - end).DotProduct(U)
        mode = 'v' if abs(dv) >= abs(du) else 'h'
    # марка строго над/под (или сбоку от) концом выноски
    du, dv = (head - end).DotProduct(R), (head - end).DotProduct(U)
    if mode == 'v':
        head = end + U * dv
    elif mode == 'h':
        head = end + R * du
    _reset(tag)
    tag.TagHeadPosition = head
    try:
        tag.SetLeaderEnd(ref, end)
    except Exception:
        pass
    # излом — всегда задать явно: у марки, которая раньше была с изломом, Revit оставляет
    # старый излом и после сброса выноски — выноска «ломается» (db, С.Х.ККБ1, 18.10).
    # Для прямой выноски излом ставится на саму линию (середина) — линия остаётся прямой.
    try:
        if mode == 'elbow':
            tag.SetLeaderElbow(ref, end + U * dv)
        else:
            tag.SetLeaderElbow(ref, end + (head - end) * 0.5)
    except Exception:
        pass
    return mode
