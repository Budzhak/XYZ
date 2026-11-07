# -*- coding: utf-8 -*-
"""
Шаги «Оформить взрыв-схему» для схем отопления с коллекторами
(XYZ -> По красоте -> «Оформить взрыв-схему по шагам»).

Перенесено 01.11.2026 из разовой работы по схеме радиаторного отопления
(лист 23 Глаголево, 31.10-01.11.2026: zb_tmp\\s23\\v2\\s23lib.py, apply_23.py,
zb_tmp\\s23\\v3\\tags_23.py). Жёсткие Id видов, коллекторов и типов марок убраны:
всё берётся из выделения и из модели.

  fan    «Веер лучей от выделенных коллекторов»
         Выделить коллекторы (оборудование). Луч — подача + обратка от выхода
         коллектора до прибора. Каждый луч целиком сдвигается по высоте на свой
         шаг (на листе — N мм между соседними лучами), коллектор остаётся на месте.
         Уже смещённое — вложенный набор в свой (Revit сам изымает из родителя).
         Выход, который ведёт в магистраль (котёл, насосная группа, гидрострелка,
         другой коллектор, больше 400 элементов) или не доходит до прибора, — не луч.
         Потом марки затронутых элементов раскладываются заново:
         отметки -> оборудование -> трубы (dress_scheme.tidy). Марка, которой нет
         места, остаётся где была (не удаляется) и выделяется после шага.
         Высотные отметки не пересчитываются.

  eqtags «Марки приборов: прямая выноска поодаль»
         Выделить приборы (или их марки — тогда по марке её прибор). Марка встаёт
         поодаль от прибора с ПРЯМОЙ выноской: вверх 10-20 мм листа предпочтительно,
         тесно — сбоку ~10 мм или вниз, иначе «Г» (вертикаль + полка). Обходит марки,
         отметки и их выноски, трубы (полосой), видимое оборудование и тексты.
         Соседние марки выравниваются в ряд. Если в проекте загружено семейство
         марок «db_ADSK_M_Оборудование» с типами «ADSK_Марка» / «ADSK_Наименование
         краткое», марки ADSK_Марка_* / ADSK_Наименование краткое_* переводятся на них
         (подпись в рамке, как марки труб). Без места — марка остаётся где была.

Вход: run(ctx_factory, doc, uidoc, step, elems, gap_mm) из dress_scheme.run_step.
"""
import math
from Autodesk.Revit.DB import *
from System.Collections.Generic import List

FT = 304.8
MAX_RAY = 400
STOP_WORDS = (u'STOUT', u'SDG', u'Гидравлич', u'гидрострел', u'Распределительный', u'Бак', u'TRM',
              u'Котел', u'котел', u'Котёл', u'котёл', u'BAXI', u'Насос', u'насос')
EQ_TAG_FAM = u'db_ADSK_M_Оборудование'
GAPS = (8.0, 10.0, 12.0, 14.0, 16.0, 18.0, 20.0, 24.0, 28.0, 34.0, 42.0, 50.0, 60.0, 75.0, 90.0)

C_PIPE = int(BuiltInCategory.OST_PipeCurves)
C_EQ = int(BuiltInCategory.OST_MechanicalEquipment)


def _iv(eid):
    try:
        return eid.Value
    except Exception:
        return eid.IntegerValue


def _cat(e):
    try:
        return _iv(e.Category.Id)
    except Exception:
        return 0


def _conns(el):
    try:
        m = el.MEPModel.ConnectorManager
    except Exception:
        try:
            m = el.ConnectorManager
        except Exception:
            m = None
    if m is None:
        return []
    return [c for c in m.Connectors]


def _nbrs(el):
    out = []
    for c in _conns(el):
        try:
            if not c.IsConnected:
                continue
            for r in c.AllRefs:
                o = r.Owner
                if o is None or isinstance(o, MEPSystem) or _iv(o.Id) == _iv(el.Id):
                    continue
                out.append(o)
        except Exception:
            pass
    return out


def _n_connected(el):
    n = 0
    for c in _conns(el):
        try:
            if c.IsConnected:
                n += 1
        except Exception:
            pass
    return n


def _is_stop(e, coll):
    """Конец луча «в магистраль»: другой коллектор, котёл/насосная группа/гидрострелка
    (по имени семейства и типа) или оборудование с пятью и больше подключёнными
    соединителями. 01.11.2026: было «три и больше» — узел нижнего подключения прибора
    (Oventrop Multiflex: две трубы + два патрубка прибора = 4) считался магистралью,
    и на листе 23 не находилось ни одного луча (проба на копии вида)."""
    if _iv(e.Id) in coll:
        return True
    if _cat(e) == C_EQ:
        try:
            nm = e.Symbol.FamilyName + u' ' + e.Name
        except Exception:
            nm = u''
        for w in STOP_WORDS:
            if w in nm:
                return True
        if _n_connected(e) >= 5:
            return True
    return False


class _Tx(object):
    def __init__(self, doc, name):
        self.t = SubTransaction(doc) if doc.IsModifiable else Transaction(doc, name)

    def __enter__(self):
        self.t.Start()
        return self

    def __exit__(self, et, ev, tb):
        if et is None:
            self.t.Commit()
        else:
            self.t.RollBack()
        return False


# ================================================================== лучи
def rays(doc, view, coll_ids, log):
    """[(Id коллектора, [Id элементов луча на виде], положение выхода по вертикали экрана)]"""
    inview = set(_iv(e.Id) for e in FilteredElementCollector(doc, view.Id).WhereElementIsNotElementType())
    U = view.UpDirection
    coll = set(coll_ids)
    res = []
    for cid in coll_ids:
        col = doc.GetElement(ElementId(cid))
        raw = []
        skipped = 0
        for c in _conns(col):
            if not c.IsConnected:
                continue
            for r in c.AllRefs:
                o = r.Owner
                if o is None or isinstance(o, MEPSystem) or _iv(o.Id) == cid:
                    continue
                if _is_stop(o, coll):
                    skipped += 1
                    continue
                seen = set([_iv(o.Id)])
                q = [o]
                bad = dev = False
                while q and not bad:
                    e = q.pop()
                    for n in _nbrs(e):
                        k = _iv(n.Id)
                        if k in seen or k == cid:
                            continue
                        if _is_stop(n, coll):
                            bad = True
                            break
                        seen.add(k)
                        q.append(n)
                    if _cat(e) == C_EQ:
                        dev = True
                    if len(seen) > MAX_RAY:
                        bad = True
                if bad or not dev:
                    skipped += 1
                    continue
                raw.append((seen, c.Origin.DotProduct(U)))
        # подача и обратка одного прибора — один луч
        groups = []
        for s, u in raw:
            hit = [g for g in groups if g[0] & s]
            ns, nu = set(s), [u]
            for g in hit:
                ns |= g[0]
                nu += g[1]
                groups.remove(g)
            groups.append((ns, nu))
        for s, us in groups:
            ids = [i for i in s if i in inview]
            res.append((cid, ids, sum(us) / len(us)))
        log(u'Коллектор {}: лучей {}, выходов в магистраль/без прибора {}'.format(cid, len(groups), skipped))
    return res


def plan_fan(view, R, coll_ids, gap_mm, log):
    """Веер: лучи коллектора по высоте выхода на экране, шаг gap_mm на листе,
    симметрично относительно коллектора."""
    U = view.UpDirection
    k = max(abs(U.Z), 0.3) * 0.87
    step = gap_mm * view.Scale / k / FT
    offs = {}
    for cid in coll_ids:
        rr = sorted([r for r in R if r[0] == cid], key=lambda r: r[2])
        m = len(rr)
        for j, (c, ids, u) in enumerate(rr):
            dz = (j - (m - 1) / 2.0) * step
            for i in ids:
                offs[i] = XYZ(0, 0, dz)
        if m:
            log(u'Коллектор {}: шаг по высоте {} мм модели, размах {} мм'.format(
                cid, int(round(step * FT)), int(round((m - 1) * step * FT))))
    return offs


def displace(doc, view, offs):
    """offs: {Id: XYZ}. Одинаковый сдвиг — один набор; уже смещённые — вложенный набор в свой."""
    des, owner = {}, {}
    for de in FilteredElementCollector(doc, view.Id).OfClass(DisplacementElement):
        des[_iv(de.Id)] = de
        for i in de.GetDisplacedElementIds():
            owner[_iv(i)] = _iv(de.Id)
    grp = {}
    for i, v in offs.items():
        if v.GetLength() < 1e-4:
            continue
        el = doc.GetElement(ElementId(i))
        if el is None or not DisplacementElement.IsAllowedAsDisplacedElement(el):
            continue
        key = (owner.get(i), round(v.X, 3), round(v.Y, 3), round(v.Z, 3))
        grp.setdefault(key, (v, []))[1].append(i)
    n = bad = 0
    with _Tx(doc, u'Веер лучей: разнос'):
        for key, (v, ids) in grp.items():
            par = des.get(key[0]) if key[0] is not None else None
            try:
                DisplacementElement.Create(doc, List[ElementId]([ElementId(i) for i in ids]), v, view, par)
                n += 1
            except Exception:
                for i in ids:
                    try:
                        DisplacementElement.Create(doc, List[ElementId]([ElementId(i)]), v, view, par)
                        n += 1
                    except Exception:
                        bad += 1
    return n, bad


def retidy_keep(DS, doc, view, moved, log):
    """Переразложить марки элементов moved: отметки -> оборудование -> трубы.
    Марка без места не удаляется (остаётся где была). Возвращает [Id таких марок]."""
    keep = []
    orig_single = DS._single

    def _single_keep(ctx, item, sz):
        ok = orig_single(ctx, item, sz)
        if not ok:
            keep.append(item[0].Id)
        return True
    tags = []
    for t in FilteredElementCollector(doc, view.Id).OfClass(IndependentTag):
        try:
            h = list(t.GetTaggedLocalElementIds())
        except Exception:
            continue
        if h and _iv(h[0]) in moved:
            tags.append(t)

    def kind(t):
        sym = doc.GetElement(t.GetTypeId())
        fn = sym.FamilyName if sym is not None else u''
        if u'Отметка' in fn:
            return 0
        if _cat(doc.GetElement(list(t.GetTaggedLocalElementIds())[0])) == C_EQ:
            return 1
        return 2
    DS._single = _single_keep
    try:
        for kk, title in ((0, u'Марки-отметки'), (1, u'Марки оборудования'), (2, u'Марки труб')):
            ts = [t for t in tags if t.IsValidObject and kind(t) == kk]
            if not ts:
                continue
            n0 = len(keep)
            ctx = DS.Ctx(doc, view, None, True, exclude=[_iv(t.Id) for t in ts])
            ctx.angled = True
            items = []
            for t in ts:
                el = doc.GetElement(list(t.GetTaggedLocalElementIds())[0])
                anchors = DS.anchors_of(ctx, el)
                if anchors:
                    items.append((t, el, anchors, title))
            DS.tidy(ctx, items, title)
            log(u'{}: переразложено {}, без места (оставлены где были) {}'.format(title, len(items), len(keep) - n0))
    finally:
        DS._single = orig_single
    return keep


def step_fan(DS, ctx, elems, gap_mm):
    doc, view = ctx.doc, ctx.view
    lines = []
    coll = [_iv(e.Id) for e in (elems or []) if _cat(e) == C_EQ]
    if not coll:
        ctx.add(u'Не выделено ни одного коллектора (категория «Оборудование»)')
        return []
    R = rays(doc, view, coll, lines.append)
    if not R:
        ctx.add(u'Лучей не найдено (выходы ведут в магистраль или не доходят до прибора)')
        ctx.notes.extend(lines)
        return []
    offs = plan_fan(view, R, coll, gap_mm, lines.append)
    n, bad = displace(doc, view, offs)
    ctx.add(u'Лучей сдвинуто', len(R))
    ctx.add(u'Наборов смещения создано', n)
    if bad:
        ctx.add(u'Элементов не удалось сдвинуть', bad)
    moved = set(i for i, v in offs.items() if v.GetLength() > 1e-4)
    keep = retidy_keep(DS, doc, view, moved, lines.append)
    ctx.notes.extend(lines)
    if keep:
        ctx.add(u'Марок без места (оставлены где были, выделены)', len(keep))
    return keep


# ================================================================== марки приборов
def _hidden_filters(doc, view):
    out = []
    for fid in view.GetFilters():
        if view.GetFilterVisibility(fid):
            continue
        pf = doc.GetElement(fid)
        try:
            cats = set(_iv(c) for c in pf.GetCategories())
        except Exception:
            continue
        try:
            ef = pf.GetElementFilter()
        except Exception:
            ef = None
        out.append((cats, ef))
    return out


def _is_hidden(e, hf, view):
    try:
        if e.IsHidden(view):
            return True
    except Exception:
        pass
    c = _cat(e)
    for cats, ef in hf:
        if c in cats and (ef is None or ef.PassesFilter(e)):
            return True
    return False


def _ovl(a, b, m=0.0):
    return min(a[2], b[2]) - max(a[0], b[0]) > -m and min(a[3], b[3]) - max(a[1], b[1]) > -m


def _hit(p, q, b, eps=0.05):
    """Точно: отрезок p-q (u,v) проходит через прямоугольник b (касание краем — нет).
    01.11.2026: DS._seg_hits_box проверяет 12 точек на отрезке — выноска 90 мм
    «перешагивала» рамку высотой 5 мм (проба на копии листа 23: выноска через две марки)."""
    (x0, y0), (x1, y1) = p, q
    x_lo, y_lo, x_hi, y_hi = b[0] + eps, b[1] + eps, b[2] - eps, b[3] - eps
    if x_lo > x_hi or y_lo > y_hi:
        return False
    dx, dy = x1 - x0, y1 - y0
    t0, t1 = 0.0, 1.0
    for pp, qq in ((-dx, x0 - x_lo), (dx, x_hi - x0), (-dy, y0 - y_lo), (dy, y_hi - y0)):
        if abs(pp) < 1e-12:
            if qq < 0:
                return False
        else:
            t = qq / pp
            if pp < 0:
                if t > t0:
                    t0 = t
            elif t < t1:
                t1 = t
            if t0 > t1:
                return False
    return True


def _frame_types(doc):
    """Типы марок «в рамке»: {'ADSK_Марка': Id, 'ADSK_Наименование краткое': Id} или {}."""
    out = {}
    for s in FilteredElementCollector(doc).OfClass(FamilySymbol):
        try:
            if s.FamilyName != EQ_TAG_FAM:
                continue
            nm = Element.Name.GetValue(s) or u''
        except Exception:
            continue
        if nm in (u'ADSK_Марка', u'ADSK_Наименование краткое'):
            out[nm] = s.Id
    return out


def step_eqtags(DS, ctx, elems):
    import stack_tags as ST
    doc, view = ctx.doc, ctx.view
    R, U, mm = ctx.R, ctx.U, ctx.mm
    uv = ctx.uv
    sel = set(_iv(e.Id) for e in (elems or []))
    tags = []
    for t in FilteredElementCollector(doc, view.Id).OfClass(IndependentTag):
        try:
            hs = list(t.GetTaggedLocalElementIds())
        except Exception:
            continue
        if not hs:
            continue
        el = doc.GetElement(hs[0])
        if not isinstance(el, FamilyInstance) or _cat(el) != C_EQ:
            continue
        if _iv(el.Id) not in sel and _iv(t.Id) not in sel:
            continue
        tags.append((t, el))
    if not tags:
        ctx.add(u'У выделенного нет марок оборудования на этом виде')
        return []
    # 1. тип «в рамке» (если семейство загружено)
    ft = _frame_types(doc)
    nchg = 0
    if ft:
        tr = Transaction(doc, u'Марки приборов: тип в рамке')
        tr.Start()
        try:
            for t, el in tags:
                nm = Element.Name.GetValue(doc.GetElement(t.GetTypeId())) or u''
                new = None
                if nm.startswith(u'ADSK_Марка') and u'ADSK_Марка' in ft:
                    new = ft[u'ADSK_Марка']
                elif nm.startswith(u'ADSK_Наименование краткое') and u'ADSK_Наименование краткое' in ft:
                    new = ft[u'ADSK_Наименование краткое']
                if new is not None and _iv(t.GetTypeId()) != _iv(new):
                    t.ChangeTypeId(new)
                    nchg += 1
            tr.Commit()
        except Exception:
            tr.RollBack()
            raise
    if nchg:
        ctx.add(u'Марок переведено на тип «в рамке» ({})'.format(EQ_TAG_FAM), nchg)
    # 2. занятость: марки/отметки и выноски (Ctx), трубы полосами, оборудование, тексты
    ctx2 = DS.Ctx(doc, view, None, True, exclude=[_iv(t.Id) for t, el in tags])
    occ = ctx2.occ
    occ.band_w = 40.0
    hf = _hidden_filters(doc, view)
    for bic in (BuiltInCategory.OST_PipeCurves, BuiltInCategory.OST_FlexPipeCurves):
        for p in FilteredElementCollector(doc, view.Id).OfCategory(bic).WhereElementIsNotElementType():
            if _is_hidden(p, hf, view):
                continue
            lc = p.Location
            if not isinstance(lc, LocationCurve):
                continue
            d = ctx2.dp(p)
            c = lc.Curve
            if not (ctx2.visible_pt(c.GetEndPoint(0)) or ctx2.visible_pt(c.GetEndPoint(1))):
                continue
            try:
                pts = list(c.Tessellate())
            except Exception:
                pts = [c.GetEndPoint(0), c.GetEndPoint(1)]
            for k in range(len(pts) - 1):
                occ.add_band(uv(pts[k] + d), uv(pts[k + 1] + d), 0.8)
    for bic in (BuiltInCategory.OST_PipeFitting, BuiltInCategory.OST_PipeAccessory):
        for e in FilteredElementCollector(doc, view.Id).OfCategory(bic).WhereElementIsNotElementType():
            if _is_hidden(e, hf, view):
                continue
            bb = e.get_BoundingBox(None)
            if bb is None:
                continue
            c = uv((bb.Min + bb.Max) / 2.0 + ctx2.dp(e))
            occ.add_band((c[0] - 0.3, c[1]), (c[0] + 0.3, c[1]), 1.0, line=False)
    eqbox = {}
    for e in FilteredElementCollector(doc, view.Id).OfCategory(BuiltInCategory.OST_MechanicalEquipment) \
            .WhereElementIsNotElementType():
        if getattr(e, 'SuperComponent', None) is not None or _is_hidden(e, hf, view):
            continue
        gb = DS._geo_uv_box(ctx2, e)
        if gb is not None:
            eqbox[_iv(e.Id)] = gb

    def box_of(bb, tr=None):
        us, vs = [], []
        for x in (bb.Min.X, bb.Max.X):
            for y in (bb.Min.Y, bb.Max.Y):
                for z in (bb.Min.Z, bb.Max.Z):
                    p = XYZ(x, y, z)
                    q = uv(tr.OfPoint(p) if tr is not None else p)
                    us.append(q[0])
                    vs.append(q[1])
        return (min(us), min(vs), max(us), max(vs))
    for tn in FilteredElementCollector(doc, view.Id).OfClass(TextNote):
        bb = tn.get_BoundingBox(view)
        if bb is not None:
            occ.add_box(box_of(bb))
    crop = None
    try:
        if view.CropBoxActive:
            b = box_of(view.CropBox, view.CropBox.Transform)
            crop = (b[0] + 3, b[1] + 3, b[2] - 3, b[3] - 3)
    except Exception:
        crop = None
    # 3. размеры марок
    rels = ST.measure_exact(doc, view, [t for t, el in tags], R, U, mm)
    items = []
    for (t, el), rel in zip(tags, rels):
        if rel is None:
            rel = (-12 * mm, -2.5 * mm, 12 * mm, 2.5 * mm)
        r = tuple(x / mm for x in rel)
        # на 3D-виде measure_exact занижает ширину длинных подписей (лист 23: PURMO… 51,5 мм
        # по картинке) — берём не меньше оценки по числу знаков самой длинной строки
        txt = t.TagText or u''
        longest = max([len(s) for s in txt.split(u'\n')] or [0])
        wq = max(r[2] - r[0], 1.8 * longest + 1.5)
        cu_, cv_ = (r[0] + r[2]) / 2.0, (r[1] + r[3]) / 2.0
        hh = max(r[3] - r[1], 5.0) / 2.0
        r = (cu_ - wq / 2.0, cv_ - hh, cu_ + wq / 2.0, cv_ + hh)
        E = eqbox.get(_iv(el.Id))
        bb = el.get_BoundingBox(None)
        c3 = (bb.Min + bb.Max) / 2.0 + ctx2.dp(el)
        if E is None:
            cu, cv = uv(c3)
            E = (cu - 3, cv - 3, cu + 3, cv + 3)
        h = el.HandOrientation
        L = abs((bb.Max.X - bb.Min.X) * h.X) + abs((bb.Max.Y - bb.Min.Y) * h.Y)
        items.append({'t': t, 'el': el, 'rel': r, 'E': E, 'c3': c3, 'cuv': uv(c3), 'L': L / mm,
                      'ax': (h.DotProduct(R), h.DotProduct(U))})

    def cands(it, extra_v=()):
        r0, q0, r1, q1 = it['rel']
        w, hgt = r1 - r0, q1 - q0
        E = it['E']
        cu, cv = it['cuv']
        out = []
        anchors = [(cu + it['ax'][0] * it['L'] * f, cv + it['ax'][1] * it['L'] * f, abs(f))
                   for f in (0.0, -0.25, 0.25, -0.4, 0.4)]
        for au, av, f in anchors:
            for dr in ('U', 'D'):
                edge = E[3] if dr == 'U' else E[1]
                sv = 1.0 if dr == 'U' else -1.0
                st = (au, edge)
                gl = list(GAPS)
                for vv in extra_v:
                    g = (vv - hgt / 2.0 - edge) if dr == 'U' else (edge - vv - hgt / 2.0)
                    if 6.0 <= g <= 60.0:
                        gl.append(g)
                for g in gl:
                    if dr == 'U':
                        box = (au - w / 2.0, edge + g, au + w / 2.0, edge + g + hgt)
                    else:
                        box = (au - w / 2.0, edge - g - hgt, au + w / 2.0, edge - g)
                    lb = (au, edge + sv * g)
                    pen = (0.0 if 10.0 <= g <= 20.0 else min(abs(g - 10.0), abs(g - 20.0)) * 0.8) + \
                          (0.0 if dr == 'U' else 10.0) + f * 6.0
                    out.append((box, (au, av), [st, lb], pen, dr, None))
                vl = [10.0, 15.0, 20.0, 28.0, 36.0, 46.0, 58.0, 72.0, 90.0]
                for vv in extra_v:
                    V = (vv - edge) * sv
                    if 6.0 <= V <= 60.0:
                        vl.append(V)
                for V in vl:
                    row = edge + sv * V
                    for H in (6.0, 10.0, 16.0, 24.0, 34.0, 48.0, 64.0):
                        for sh in (1.0, -1.0):
                            lb = (au + sh * H, row)
                            box = (lb[0], row - hgt / 2.0, lb[0] + w, row + hgt / 2.0) if sh > 0 else \
                                  (lb[0] - w, row - hgt / 2.0, lb[0], row + hgt / 2.0)
                            pen = 8.0 + abs(V - 15.0) * 0.4 + abs(H - 8.0) * 0.4 + \
                                (0.0 if dr == 'U' else 6.0) + f * 6.0
                            out.append((box, (au, av), [st, (au, row), lb], pen, 'G' + dr, (au, row)))
            for dr in ('L', 'R'):
                edge = E[2] if dr == 'R' else E[0]
                vs = [av, (E[1] + E[3]) / 2.0, E[3] - (E[3] - E[1]) * 0.2] + list(extra_v)
                for vv in vs:
                    if not (E[1] + 1.0 <= vv <= E[3] - 1.0):
                        continue
                    st = (edge, vv)
                    for g in GAPS:
                        if dr == 'R':
                            box = (edge + g, vv - hgt / 2.0, edge + g + w, vv + hgt / 2.0)
                            lb = (edge + g, vv)
                        else:
                            box = (edge - g - w, vv - hgt / 2.0, edge - g, vv + hgt / 2.0)
                            lb = (edge - g, vv)
                        out.append((box, (au, vv), [st, lb], abs(g - 10.0) * 0.8 + 6.0 + f * 6.0, dr, None))
        return out

    def cost(it, c):
        box, a, pts, pen, kind, elb = c
        if crop is not None and (box[0] < crop[0] or box[1] < crop[1] or box[2] > crop[2] or box[3] > crop[3]):
            return None
        bc = occ.box_cost(box, 1.5)
        if bc >= DS.HARD:
            return None
        for k, E in eqbox.items():
            if _ovl(box, E, 1.5):
                return None
        lc = occ.lead_cost(pts)
        if lc >= 1500.0:
            return None
        for k, E in eqbox.items():
            if k == _iv(it['el'].Id):
                continue
            for q in range(len(pts) - 1):
                if _hit(pts[q], pts[q + 1], E):
                    lc += 500.0
        # точная проверка (DS._seg_hits_box и box_cost смотрят 12 точек на отрезке):
        # выноска не через чужие рамки, рамка не на чужой выноске
        for o in occ.boxes:
            for q in range(len(pts) - 1):
                if _hit(pts[q], pts[q + 1], o):
                    hp = occ.soft.get(o)
                    if hp is None or _hit(pts[q], pts[q + 1], hp):
                        return None
        for (p0, p1) in occ.segs:
            if _hit(p0, p1, box):
                return None
        return bc + lc + pen

    def place_best(it):
        ev = []
        for p in items:
            if p is it or p.get('ch') is None:
                continue
            b = p['ch'][0]
            if abs((b[0] + b[2]) / 2.0 - it['cuv'][0]) < 140.0 and abs((b[1] + b[3]) / 2.0 - it['cuv'][1]) < 60.0:
                ev.append((b[1] + b[3]) / 2.0)
        best = None
        for c in cands(it, ev):
            cs = cost(it, c)
            if cs is None:
                continue
            cvv = (c[0][1] + c[0][3]) / 2.0
            for vv in ev:
                if abs(cvv - vv) < 0.3 and cs < 100.0:
                    cs -= 6.0          # в ряд с соседней маркой
                    break
            if best is None or cs < best[0]:
                best = (cs, c)
        return best

    def occ_add(it):
        box, a, pts = it['ch'][0], it['ch'][1], it['ch'][2]
        occ.add_box(box)
        for q in range(len(pts) - 1):
            occ.add_seg(pts[q], pts[q + 1])

    def occ_del(it):
        box, a, pts = it['ch'][0], it['ch'][1], it['ch'][2]
        try:
            occ.boxes.remove(box)
        except Exception:
            pass
        for q in range(len(pts) - 1):
            try:
                occ.segs.remove((pts[q], pts[q + 1]))
            except Exception:
                pass

    for it in items:
        it['ch'] = None
        it['nfree'] = sum(1 for c in cands(it) if (cost(it, c) or 999) < 40.0)
    order = sorted(items, key=lambda x: x['nfree'])
    fails = []
    for it in order:
        b = place_best(it)
        if b is None:
            fails.append(it)
            continue
        it['ch'], it['cost'] = b[1], b[0]
        occ_add(it)
    for it in fails:                       # без места — остаются где стоят
        hu, hv = uv(it['t'].TagHeadPosition)
        r0, q0, r1, q1 = it['rel']
        occ.add_box((hu + r0, hv + q0, hu + r1, hv + q1))
    for ps in range(3):
        for it in order:
            if it['ch'] is None:
                continue
            occ_del(it)
            b = place_best(it)
            if b is not None and b[0] < it['cost'] - 0.01:
                it['ch'], it['cost'] = b[1], b[0]
            occ_add(it)
    # 4. установка
    tr = Transaction(doc, u'Марки приборов: прямые выноски')
    tr.Start()
    try:
        for it in items:
            if it['ch'] is None:
                continue
            box, a, pts, pen, kind, elb = it['ch']
            lb = pts[-1]
            t = it['t']
            r0, q0, r1, q1 = it['rel']
            hu, hv = box[0] - r0, box[1] - q0
            cu, cv = it['cuv']
            a3 = it['c3'] + R * ((a[0] - cu) * mm) + U * ((a[1] - cv) * mm)
            head = a3 + R * ((hu - a[0]) * mm) + U * ((hv - a[1]) * mm)
            ref = list(t.GetTaggedReferences())[0]
            DS._reset_leader(t)
            t.TagHeadPosition = head
            t.SetLeaderEnd(ref, a3)
            if elb is not None:
                el3 = a3 + R * ((elb[0] - a[0]) * mm) + U * ((elb[1] - a[1]) * mm)
            else:
                lb3 = a3 + R * ((lb[0] - a[0]) * mm) + U * ((lb[1] - a[1]) * mm)
                el3 = a3 + (lb3 - a3) * 0.5
            try:
                t.SetLeaderElbow(ref, el3)
            except Exception:
                pass
            t.TagHeadPosition = head
            ctx.add(u'Марок приборов поставлено' + (u' (прямая выноска)' if elb is None else u' (выноска «Г»)'))
        tr.Commit()
    except Exception:
        tr.RollBack()
        raise
    keep = [it['t'].Id for it in fails]
    if keep:
        ctx.add(u'Марок без места (оставлены где были, выделены)', len(keep))
    return keep


# ================================================================== вход
def run(DS, ctx, step, elems, gap_mm=2.5):
    """Возвращает [ElementId] для выделения после шага; пояснения — в ctx.notes."""
    if not hasattr(ctx, 'notes'):
        ctx.notes = []
    if step == 'fan':
        return step_fan(DS, ctx, elems, gap_mm if gap_mm and gap_mm > 0 else 2.5)
    if step == 'eqtags':
        return step_eqtags(DS, ctx, elems)
    return []
