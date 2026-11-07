# -*- coding: utf-8 -*-
"""
«Выноски — равный шаг вдоль трубы» — команда кнопки «По красоте».

Марки остаются на месте; двигаются только концы выносок — ВДОЛЬ оси своего
элемента (трубы, воздуховода), так что вертикальные участки выносок
(от излома вниз к элементу) встают с одинаковым шагом и остаются
вертикальными: излом сдвигается по горизонтали вслед за концом.
  - «Равный шаг между крайними»: крайние выноски на месте, средние — поровну;
  - «Шаг N мм на листе»: выноски разносятся (или сводятся) вокруг их середины.
Порядок выносок слева направо сохраняется (новых перехлёстов не появляется).
После первой группы — рамкой следующие группы с тем же режимом, пока не Esc.
У разветвителя/фитинга конец едет вдоль прямого прохода (вход — основной выход);
у оборудования двигать некуда — конец остаётся на месте.
Работает на взрыв-схеме (с учётом смещения разноса).

«Развести слипшиеся выноски» (01.11.2026, из разовой работы по схеме отопления,
zb_tmp\\s23\\v2\\spread_23.py): среди выделенных марок (или всех марок труб и
воздуховодов на виде, если выделено меньше двух) находятся группы, чьи выноски
сходятся концами в одну точку (ближе 1,5 мм на листе) или лежат на одной линии
(параллельны, ближе 0,8 мм, перекрываются), и каждая группа разводится шагом
N мм на листе вдоль оси трубы — как «Шаг N мм». Одна транзакция (Ctrl+Z).

Вызов из script.py:   leader_spread.run(doc, uidoc, tags, config)
Ядро (нужна открытая транзакция): spread(doc, view, tags, step_mm=None),
converging_groups(doc, view, tags) -> [[марки], ...], spread_converging(doc, view, tags, step_mm)
"""
from Autodesk.Revit.DB import (
    BuiltInCategory, DisplacementElement, ElementId, FilteredElementCollector, IndependentTag, LeaderEndCondition,
    LocationCurve, Line, Transaction, XYZ,
)

TITLE = u"Выноски — равный шаг вдоль трубы"


def _iv(eid):
    try:
        return eid.Value
    except Exception:
        return eid.IntegerValue


def _disp_map(doc, view):
    out = {}
    try:
        for de in FilteredElementCollector(doc, view.Id).OfClass(DisplacementElement):
            d = de.GetAbsoluteDisplacement()
            for i in de.GetDisplacedElementIds():
                out[_iv(i)] = d
    except Exception:
        pass
    return out


def _axis(el):
    """Отрезок, вдоль которого можно двигать конец выноски: ось трубы/воздуховода;
    у фитинга/арматуры (разветвитель, муфта) — прямой проход между двумя
    соосными соединителями (вход — основной выход)."""
    loc = el.Location
    if isinstance(loc, LocationCurve) and isinstance(loc.Curve, Line):
        return loc.Curve.GetEndPoint(0), loc.Curve.GetEndPoint(1)
    try:
        cs = [c for c in el.MEPModel.ConnectorManager.Connectors]
    except Exception:
        return None
    best = None
    for i in range(len(cs)):
        for j in range(i + 1, len(cs)):
            a, b = cs[i], cs[j]
            try:
                if a.CoordinateSystem.BasisZ.DotProduct(b.CoordinateSystem.BasisZ) > -0.95:
                    continue
                L = a.Origin.DistanceTo(b.Origin)
            except Exception:
                continue
            if best is None or L > best[0]:
                best = (L, a.Origin, b.Origin)
    return (best[1], best[2]) if best is not None and best[0] > 1e-3 else None


def _items(doc, view, tags):
    R = view.RightDirection
    dmap = _disp_map(doc, view)
    items, skipped = [], []
    for t in tags:
        try:
            if not t.HasLeader or t.LeaderEndCondition != LeaderEndCondition.Free:
                skipped.append((t, u"выноска не «Со свободным концом»"))
                continue
        except Exception:
            skipped.append((t, u"нет выноски"))
            continue
        ref = None
        for r in t.GetTaggedReferences():
            ref = r
            break
        el = doc.GetElement(ref.ElementId) if ref is not None else None
        if el is None:
            skipped.append((t, u"нет элемента"))
            continue
        end = t.GetLeaderEnd(ref)
        it = {'tag': t, 'ref': ref, 'end': end, 'u': end.DotProduct(R), 'p0': None, 'p1': None}
        d = dmap.get(_iv(el.Id), XYZ.Zero)
        seg = _axis(el)
        if seg is not None:
            p0, p1 = seg[0] + d, seg[1] + d
            if abs((p1 - p0).DotProduct(R)) * 304.8 / view.Scale > 0.05:   # не «в торец» на экране
                it['p0'], it['p1'] = p0, p1
        try:
            it['elbow'] = t.GetLeaderElbow(ref) if t.HasLeaderElbow(ref) else None
        except Exception:
            it['elbow'] = None
        items.append(it)
    return items, skipped


def spread(doc, view, tags, step_mm=None):
    """step_mm=None — равный шаг между крайними; иначе шаг на листе вокруг середины.
    Возвращает (перемещено, [(марка, причина)])."""
    R = view.RightDirection
    mm = view.Scale / 304.8
    items, skipped = _items(doc, view, tags)
    if len(items) < 2:
        return 0, skipped + [(it['tag'], u"нужно хотя бы две марки") for it in items]
    items.sort(key=lambda x: x['u'])
    n = len(items)
    if step_mm is None:
        u0, u1 = items[0]['u'], items[-1]['u']
        targets = [u0 + (u1 - u0) * k / (n - 1.0) for k in range(n)]
    else:
        c = sum(x['u'] for x in items) / float(n)
        s = step_mm * mm
        targets = [c + (k - (n - 1) / 2.0) * s for k in range(n)]
    moved = 0
    for it, ut in zip(items, targets):
        t, ref = it['tag'], it['ref']
        if it['p0'] is None:
            if abs(ut - it['u']) > 0.05 * mm:
                skipped.append((t, u"конец не на трубе/фитинге — остался на месте"))
            continue
        p0, p1 = it['p0'], it['p1']
        a, b = p0.DotProduct(R), p1.DotProduct(R)
        k = (ut - a) / (b - a)
        if k < 0.0 or k > 1.0:
            skipped.append((t, u"элемент короче нужного сдвига — конец у его края"))
            k = min(max(k, 0.0), 1.0)
        new_end = p0 + (p1 - p0) * k
        t.SetLeaderEnd(ref, new_end)
        if it['elbow'] is not None:
            e = it['elbow']
            try:
                t.SetLeaderElbow(ref, e + R * (new_end.DotProduct(R) - e.DotProduct(R)))
            except Exception:
                pass
        moved += 1
    return moved, skipped


def _curve_cats():
    out = set()
    for b in (BuiltInCategory.OST_PipeCurves, BuiltInCategory.OST_FlexPipeCurves,
              BuiltInCategory.OST_DuctCurves, BuiltInCategory.OST_FlexDuctCurves):
        out.add(_iv(ElementId(b)))
    return out


def view_curve_tags(doc, view):
    """Марки труб и воздуховодов на виде со свободным концом выноски."""
    cc = _curve_cats()
    out = []
    for t in FilteredElementCollector(doc, view.Id).OfClass(IndependentTag):
        try:
            ids = list(t.GetTaggedLocalElementIds())
            el = doc.GetElement(ids[0]) if ids else None
            if el is None or el.Category is None or _iv(el.Category.Id) not in cc:
                continue
            if t.HasLeader and t.LeaderEndCondition == LeaderEndCondition.Free:
                out.append(t)
        except Exception:
            continue
    return out


def converging_groups(doc, view, tags, near_mm=1.5, line_mm=0.8):
    """Группы марок, у которых выноски сходятся концами в одну точку (ближе near_mm
    на листе) или лежат на одной линии (параллельны, ближе line_mm, перекрываются)."""
    import math
    R, U = view.RightDirection, view.UpDirection
    mm = view.Scale / 304.8
    its = []
    for t in tags:
        try:
            if not t.HasLeader or t.LeaderEndCondition != LeaderEndCondition.Free:
                continue
            ref = list(t.GetTaggedReferences())[0]
            e = t.GetLeaderEnd(ref)
            eb = t.GetLeaderElbow(ref) if t.HasLeaderElbow(ref) else None
            s = eb if eb is not None else t.TagHeadPosition
            its.append({'t': t, 'e': (e.DotProduct(R) / mm, e.DotProduct(U) / mm),
                        's': (s.DotProduct(R) / mm, s.DotProduct(U) / mm)})
        except Exception:
            continue
    n = len(its)
    par = list(range(n))

    def find(i):
        while par[i] != i:
            par[i] = par[par[i]]
            i = par[i]
        return i

    def seg(a):
        (ex, ey), (sx, sy) = a['e'], a['s']
        dx, dy = sx - ex, sy - ey
        return ex, ey, dx, dy, math.hypot(dx, dy)

    def close(a, b):
        ax, ay, adx, ady, aL = seg(a)
        bx, by, bdx, bdy, bL = seg(b)
        if math.hypot(ax - bx, ay - by) < near_mm:
            return True                       # концы в одной точке
        if aL < 0.5 or bL < 0.5:
            return False
        ux, uy = adx / aL, ady / aL
        if abs(ux * bdy / bL - uy * bdx / bL) > 0.05:
            return False                      # не параллельны
        d1 = abs((bx - ax) * uy - (by - ay) * ux)
        d2 = abs((bx + bdx - ax) * uy - (by + bdy - ay) * ux)
        if max(d1, d2) > line_mm:
            return False
        pa = sorted([0.0, aL])
        pb = sorted([(bx - ax) * ux + (by - ay) * uy, (bx + bdx - ax) * ux + (by + bdy - ay) * uy])
        return min(pa[1], pb[1]) - max(pa[0], pb[0]) > 0.5

    for i in range(n):
        for j in range(i + 1, n):
            if abs(its[i]['e'][0] - its[j]['e'][0]) > 80 and abs(its[i]['s'][0] - its[j]['s'][0]) > 80:
                continue
            if close(its[i], its[j]):
                a, b = find(i), find(j)
                if a != b:
                    par[a] = b
    groups = {}
    for i in range(n):
        groups.setdefault(find(i), []).append(its[i]['t'])
    return [g for g in groups.values() if len(g) > 1]


def spread_converging(doc, view, tags, step_mm):
    """Нужна открытая транзакция. Возвращает (групп, марок в группах, сдвинуто, [(марка, причина)])."""
    groups = converging_groups(doc, view, tags)
    moved, skipped = 0, []
    for g in groups:
        try:
            k, sk = spread(doc, view, g, step_mm)
        except Exception as ex:
            skipped.extend((t, u"ошибка: " + unicode(ex)[:60]) for t in g)
            continue
        moved += k
        skipped.extend(sk)
    return len(groups), sum(len(g) for g in groups), moved, skipped


def _ask_step(forms, config):
    last = u"4"
    try:
        last = config.get_option('spread_step', u"4") if config is not None else u"4"
    except Exception:
        pass
    s = forms.ask_for_string(default=last, prompt=u"Шаг между вертикальными выносками, мм на листе",
                             title=TITLE)
    if s is None:
        return None, None
    try:
        step = float(s.replace(u",", u"."))
        if step <= 0:
            raise ValueError
    except ValueError:
        forms.alert(u"Нужно положительное число, например 3 или 4.5.", title=TITLE)
        return None, None
    if config is not None:
        config.spread_step = s
    return step, s


def _report_skipped(uidoc, skipped):
    msg = u""
    if skipped:
        why = {}
        for _, w in skipped:
            why[w] = why.get(w, 0) + 1
        msg += u"\n\n" + u"\n".join(u"  {} — {}".format(k, v) for k, v in why.items())
        try:
            from System.Collections.Generic import List
            uidoc.Selection.SetElementIds(List[ElementId]([x.Id for x, _ in skipped]))
            msg += u"\n(эти марки выделены)"
        except Exception:
            pass
    return msg


def run_converging(doc, uidoc, tags, config=None):
    """«Развести слипшиеся выноски»: среди tags (меньше двух — все марки труб и
    воздуховодов на виде)."""
    import xyz_forms as forms
    view = doc.ActiveView
    scope = u"среди выделенных"
    if not tags or len(tags) < 2:
        tags = view_curve_tags(doc, view)
        scope = u"на всём виде (марки труб и воздуховодов)"
    groups = converging_groups(doc, view, tags)
    if not groups:
        forms.alert(u"Слипшихся выносок {} не найдено (проверено марок: {}).".format(scope, len(tags)), title=TITLE)
        return
    step, s = _ask_step(forms, config)
    if step is None:
        return
    t = Transaction(doc, u"Развести слипшиеся выноски")
    t.Start()
    try:
        ng, nt, moved, skipped = spread_converging(doc, view, tags, step)
        t.Commit()
    except Exception:
        t.RollBack()
        raise
    msg = u"Слипшиеся выноски {}: групп {}, марок в них {}. Сдвинуто концов: {} (шаг {} мм на листе).".format(
        scope, ng, nt, moved, s)
    forms.alert(msg + _report_skipped(uidoc, skipped) + u"\n\nОтмена — один Ctrl+Z.", title=TITLE)


def _tag_filter():
    from Autodesk.Revit.UI.Selection import ISelectionFilter

    class TagFilter(ISelectionFilter):
        def AllowElement(self, el):
            return isinstance(el, IndependentTag)

        def AllowReference(self, ref, pt):
            return False
    return TagFilter()


def run(doc, uidoc, tags, config=None):
    import xyz_forms as forms
    view = doc.ActiveView
    A_EQ = u"Равный шаг между крайними (крайние на месте)"
    A_STEP = u"Задать шаг, мм на листе (разнести или свести)…"
    A_CONV = u"Развести слипшиеся выноски (сходятся в точку / на одной линии)…"
    if not tags or len(tags) < 2:
        # 01.11.2026: без выделения — поиск слипшихся выносок на всём виде
        if forms.alert(u"Выделено меньше двух марок.\n\nНайти на всём виде марки труб и воздуховодов, "
                       u"у которых выноски сходятся в одну точку или лежат на одной линии, "
                       u"и развести их с шагом?", title=TITLE, yes=True, no=True):
            run_converging(doc, uidoc, None, config)
        return
    ch = forms.CommandSwitchWindow.show([A_EQ, A_STEP, A_CONV], message=TITLE)
    if not ch:
        return
    if ch == A_CONV:
        run_converging(doc, uidoc, tags, config)
        return
    step = None
    s = None
    if ch == A_STEP:
        step, s = _ask_step(forms, config)
        if step is None:
            return
    mode = u"шаг {} мм".format(s) if step is not None else u"равный шаг между крайними"
    rounds, total, moved_all, skipped_all = 0, 0, 0, []

    def apply(group):
        t = Transaction(doc, TITLE)
        t.Start()
        try:
            n, sk = spread(doc, view, group, step)
            t.Commit()
        except Exception:
            t.RollBack()
            raise
        return n, sk

    # 1) выделенные заранее
    n, sk = apply(tags)
    rounds, total, moved_all = 1, len(tags), n
    skipped_all.extend(sk)
    # 2) дальше — рамкой следующие группы с тем же режимом, пока не Esc
    from Autodesk.Revit.Exceptions import OperationCanceledException
    flt = _tag_filter()
    while True:
        try:
            uidoc.RefreshActiveView()
        except Exception:
            pass
        try:
            picked = uidoc.Selection.PickElementsByRectangle(
                flt, u"{}: рамкой — следующие выноски ({}; групп {}). Esc — готово".format(TITLE, mode, rounds))
        except OperationCanceledException:
            break
        group = [e for e in picked if isinstance(e, IndependentTag)]
        if len(group) < 2:
            continue
        n, sk = apply(group)
        rounds += 1
        total += len(group)
        moved_all += n
        skipped_all.extend(sk)
    msg = u"Групп: {}. Сдвинуто концов выносок: {} из {}.".format(rounds, moved_all, total)
    if skipped_all:
        why = {}
        for _, w in skipped_all:
            why[w] = why.get(w, 0) + 1
        msg += u"\n\n" + u"\n".join(u"  {} — {}".format(k, v) for k, v in why.items())
        try:
            from System.Collections.Generic import List
            uidoc.Selection.SetElementIds(List[ElementId]([x.Id for x, _ in skipped_all]))
            msg += u"\n(эти марки выделены)"
        except Exception:
            pass
    forms.alert(msg + u"\n\nКаждая группа — свой шаг Ctrl+Z.", title=TITLE)
