# -*- coding: utf-8 -*-
"""Отверстия (lib/xyz_holes.py), db 13.11.2026.

Задания на отверстия: пересечения своих сетей (воздуховоды, гибкие воздуховоды, трубы,
кабельные лотки) со стенами, перекрытиями и крышами из связей (IFC и RVT).
Только чтение: в модели ничего не создаётся и не меняется.

    links(doc)                    -> связи с числом стен / перекрытий / крыш
    find(doc, uidoc, opt)         -> (rows, stats)   opt — см. DEFAULTS
    COLUMNS                       -> колонки таблицы [(ключ, заголовок, тип)]

Как считается:
  ось сети (Location.Curve) режется телами конструкций связи (Solid.IntersectWithCurve);
  куски оси внутри тела — пересечения. Слои одной стены (несколько тел подряд по оси
  одной сети) склеиваются. Сеть, идущая вдоль конструкции (стояк в стене, труба в стяжке,
  длина в теле больше предела), пересечением не считается. Близкие отверстия в одной
  конструкции объединяются в одно прямоугольное.
"""
import math
import time

from Autodesk.Revit.DB import (
    BuiltInCategory, BuiltInParameter, ElementId, FilteredElementCollector, GeometryInstance,
    Line, LocationCurve, Options, RevitLinkInstance, Solid, SolidCurveIntersectionMode,
    SolidCurveIntersectionOptions, XYZ,
)

FT = 304.8

DEFAULTS = {
    'scope': 'view',            # selection | view | model
    'ducts': True, 'flex': True, 'pipes': True, 'trays': True,
    'walls': True, 'floors': True, 'roofs': True,
    'links': None,              # список Id связей; None — все загруженные
    'round_add': 100.0,         # круглое: D + round_add
    'rect_add': 50.0,           # прямоугольное: + rect_add с каждой стороны
    'insulation': True,         # размер сети — с изоляцией
    'round_to': 10.0,           # округлять размер отверстия вверх до, мм (0 — не округлять)
    'merge': 100.0,             # объединять отверстия в одной конструкции ближе, мм (0 — нет)
    'max_len': 1000.0,          # длина оси в теле больше — сеть идёт вдоль конструкции
    'min_size': 0.0,            # сети мельче (мм) не показывать
    'min_thick': 5.0,           # ось в теле короче (мм) — касание, не отверстие
    'skip_along': True,
    'level_mode': 'elev',       # этаж: elev — по отметке отверстия, element — уровень сети
}

KINDS = (('walls', BuiltInCategory.OST_Walls, u'Стена'),
         ('floors', BuiltInCategory.OST_Floors, u'Перекрытие'),
         ('roofs', BuiltInCategory.OST_Roofs, u'Крыша'))
NETS = (('ducts', BuiltInCategory.OST_DuctCurves, u'Воздуховод'),
        ('flex', BuiltInCategory.OST_FlexDuctCurves, u'Гибкий воздуховод'),
        ('pipes', BuiltInCategory.OST_PipeCurves, u'Труба'),
        ('trays', BuiltInCategory.OST_CableTray, u'Кабельный лоток'))

COLUMNS = [
    ('n', u'№', 'i'), ('level', u'Этаж', 's'), ('kind', u'Конструкция', 's'), ('sname', u'Имя конструкции', 's'),
    ('smat', u'Материал', 's'), ('thick', u'Толщина, мм', 'i'), ('net', u'Сеть', 's'), ('system', u'Система', 's'),
    ('nsize', u'Размер сети', 's'), ('ins', u'Изоляция, мм', 'i'), ('hole', u'Отверстие', 's'),
    ('hw', u'Ширина, мм', 'i'), ('hh', u'Высота, мм', 'i'), ('zc', u'Отм центра, мм', 'i'),
    ('zb', u'Отм низа, мм', 'i'), ('zrel', u'Низ от уровня, мм', 'i'), ('x', u'X, мм', 'i'), ('y', u'Y, мм', 'i'),
    ('cnt', u'Сетей', 'i'), ('ids', u'Id сетей', 's'), ('sid', u'Id конструкции', 's'), ('storey', u'Этаж АР', 's'),
    ('link', u'Связь', 's'), ('note', u'Примечание', 's'),
]

GRID = 10.0     # ячейка сетки поиска, футы
EPS = 0.003     # ~1 мм


def _iv(eid):
    try:
        return int(eid.Value)
    except Exception:
        return int(eid.IntegerValue)


def _ps(el, name):
    try:
        p = el.LookupParameter(name)
        if p is not None and p.HasValue:
            return p.AsString() or u''
    except Exception:
        pass
    return u''


def _pd(el, bip):
    try:
        p = el.get_Parameter(bip)
        if p is not None and p.HasValue:
            v = p.AsDouble()
            if v > 1e-9:
                return v
    except Exception:
        pass
    return None


# ------------------------------------------------------------------ связи и конструкции
def links(doc):
    """[{id, name, loaded, counts{walls,floors,roofs}}] — все экземпляры связей."""
    out = []
    for li in FilteredElementCollector(doc).OfClass(RevitLinkInstance):
        ld = li.GetLinkDocument()
        d = {'id': _iv(li.Id), 'name': (li.Name or u'').split(u' : ')[0], 'loaded': ld is not None, 'counts': {}}
        if ld is not None:
            for key, bic, _ in KINDS:
                d['counts'][key] = FilteredElementCollector(ld).OfCategory(bic).WhereElementIsNotElementType().GetElementCount()
        out.append(d)
    return out


class _Struct(object):
    __slots__ = ('el', 'kind', 'label', 'mn', 'mx', 'solids', 'lk')


class _Link(object):
    def __init__(self, inst):
        self.inst = inst
        self.id = _iv(inst.Id)
        self.name = (inst.Name or u'').split(u' : ')[0]
        self.doc = inst.GetLinkDocument()
        self.T = inst.GetTotalTransform()
        self.ident = self.T.IsIdentity
        self.Ti = None if self.ident else self.T.Inverse
        self.structs = []
        self.cells = {}

    def add(self, s):
        k = len(self.structs)
        self.structs.append(s)
        i0, j0 = int(math.floor(s.mn.X / GRID)), int(math.floor(s.mn.Y / GRID))
        i1, j1 = int(math.floor(s.mx.X / GRID)), int(math.floor(s.mx.Y / GRID))
        cells = self.cells
        for i in range(i0, i1 + 1):
            for j in range(j0, j1 + 1):
                c = cells.get((i, j))
                if c is None:
                    cells[(i, j)] = [k]
                else:
                    c.append(k)

    def query(self, x0, y0, x1, y1):
        i0, j0 = int(math.floor(x0 / GRID)), int(math.floor(y0 / GRID))
        i1, j1 = int(math.floor(x1 / GRID)), int(math.floor(y1 / GRID))
        seen = set()
        cells = self.cells
        for i in range(i0, i1 + 1):
            for j in range(j0, j1 + 1):
                c = cells.get((i, j))
                if c:
                    seen.update(c)
        return seen


_OPT = Options()


def _solids(el):
    out = []
    stack = []
    try:
        ge = el.get_Geometry(_OPT)
    except Exception:
        ge = None
    if ge is not None:
        stack.append(ge)
    while stack:
        for go in stack.pop():
            if isinstance(go, Solid):
                try:
                    if go.Faces.Size > 0 and go.Volume > 1e-6:
                        out.append(go)
                except Exception:
                    pass
            elif isinstance(go, GeometryInstance):
                try:
                    stack.append(go.GetInstanceGeometry())
                except Exception:
                    pass
    return out


def _load_links(doc, opt, stats):
    want = opt.get('links')
    res = []
    for inst in FilteredElementCollector(doc).OfClass(RevitLinkInstance):
        if inst.GetLinkDocument() is None:
            continue
        if want is not None and _iv(inst.Id) not in want:
            continue
        lk = _Link(inst)
        for key, bic, label in KINDS:
            if not opt.get(key):
                continue
            for el in FilteredElementCollector(lk.doc).OfCategory(bic).WhereElementIsNotElementType():
                bb = el.get_BoundingBox(None)
                if bb is None:
                    continue
                s = _Struct()
                s.el, s.kind, s.label, s.mn, s.mx, s.solids, s.lk = el, key, label, bb.Min, bb.Max, None, lk
                lk.add(s)
        stats['structs'] += len(lk.structs)
        if lk.structs:
            res.append(lk)
    return res


# ------------------------------------------------------------------ сети
def _curves(doc, uidoc, opt):
    scope = opt.get('scope') or 'view'
    cats = dict((int(bic), (key, label)) for key, bic, label in NETS if opt.get(key))
    out = []
    if scope == 'selection':
        for eid in uidoc.Selection.GetElementIds():
            el = doc.GetElement(eid)
            if el is not None and el.Category is not None and _iv(el.Category.Id) in cats:
                out.append((el, cats[_iv(el.Category.Id)][1]))
        return out
    for key, bic, label in NETS:
        if not opt.get(key):
            continue
        if scope == 'view':
            col = FilteredElementCollector(doc, doc.ActiveView.Id)
        else:
            col = FilteredElementCollector(doc)
        for el in col.OfCategory(bic).WhereElementIsNotElementType():
            out.append((el, label))
    return out


def _net_size(el, label):
    """(d, w, h, ins) в футах; d — круглое, иначе w×h."""
    d = w = h = None
    if label == u'Труба':
        d = _pd(el, BuiltInParameter.RBS_PIPE_OUTER_DIAMETER) or _pd(el, BuiltInParameter.RBS_PIPE_DIAMETER_PARAM)
    elif label == u'Кабельный лоток':
        w = _pd(el, BuiltInParameter.RBS_CABLETRAY_WIDTH_PARAM)
        h = _pd(el, BuiltInParameter.RBS_CABLETRAY_HEIGHT_PARAM)
    else:
        w = _pd(el, BuiltInParameter.RBS_CURVE_WIDTH_PARAM)
        h = _pd(el, BuiltInParameter.RBS_CURVE_HEIGHT_PARAM)
        if not (w and h):
            w = h = None
            d = _pd(el, BuiltInParameter.RBS_CURVE_DIAMETER_PARAM)
    ins = _pd(el, BuiltInParameter.RBS_REFERENCE_INSULATION_THICKNESS) or 0.0
    return d, w, h, ins


def _basis(el, dv):
    """Оси сечения прямоугольной сети (ширина, высота) в модели."""
    try:
        for c in el.ConnectorManager.Connectors:
            cs = c.CoordinateSystem
            return cs.BasisX, cs.BasisY
    except Exception:
        pass
    z = XYZ.BasisZ
    bx = z.CrossProduct(dv)
    if bx.GetLength() < 1e-6:
        bx = XYZ.BasisX
    bx = bx.Normalize()
    return bx, dv.CrossProduct(bx).Normalize()


def _seg_box(a, b, mn, mx, pad):
    """Отрезок a-b задевает габарит (Лян — Барски, 3D)."""
    t0, t1 = 0.0, 1.0
    for p0, d, lo, hi in ((a.X, b.X - a.X, mn.X - pad, mx.X + pad),
                          (a.Y, b.Y - a.Y, mn.Y - pad, mx.Y + pad),
                          (a.Z, b.Z - a.Z, mn.Z - pad, mx.Z + pad)):
        if abs(d) < 1e-12:
            if p0 < lo or p0 > hi:
                return False
        else:
            ta, tb = (lo - p0) / d, (hi - p0) / d
            if ta > tb:
                ta, tb = tb, ta
            if ta > t0:
                t0 = ta
            if tb < t1:
                t1 = tb
            if t0 > t1:
                return False
    return True


def _normal_at(solid, pts, dv):
    """Нормаль грани, через которую ось входит в тело или выходит из него. Точка на ребре лежит
    сразу на нескольких гранях — берётся грань, нормаль которой ближе всего к оси."""
    best, bd = None, -1.0
    try:
        for f in solid.Faces:
            for pt in pts:
                r = f.Project(pt)
                if r is not None and r.Distance < EPS:
                    n = f.ComputeNormal(r.UVPoint)
                    d = abs(n.DotProduct(dv))
                    if d > bd:
                        best, bd = n, d
    except Exception:
        pass
    return best


# ------------------------------------------------------------------ поиск
def find(doc, uidoc, opt=None, progress=None):
    """Возвращает (rows, stats). rows — список словарей по ключам COLUMNS (+ 'elids': [int])."""
    o = dict(DEFAULTS)
    o.update(opt or {})
    stats = {'touch': 0, 'structs': 0, 'nosolid': 0, 'curves': 0, 'raw': 0, 'along': 0, 'small': 0, 'cross': 0,
             'holes': 0, 'errors': 0, 'time': {}, 'by_level': {}, 'by_kind': {},
             'why': {'len': 0, 'vert': 0, 'edge': 0, 'angle': 0}}
    t0 = time.time()
    lks = _load_links(doc, o, stats)
    stats['time']['links'] = time.time() - t0

    t0 = time.time()
    curves = _curves(doc, uidoc, o)
    stats['curves'] = len(curves)
    sopt = SolidCurveIntersectionOptions()
    sopt.ResultType = SolidCurveIntersectionMode.CurveSegmentsInside
    max_len = (o['max_len'] or 0) / FT
    min_size = (o['min_size'] or 0) / FT
    merge = (o['merge'] or 0) / FT
    levels = {}
    crossings = []
    n_done = 0
    for el, label in curves:
        n_done += 1
        if progress is not None and n_done % 200 == 0:
            progress(n_done, len(curves))
        loc = el.Location
        if not isinstance(loc, LocationCurve):
            continue
        cv = loc.Curve
        if cv is None or not cv.IsBound:
            continue
        d, w, h, ins = _net_size(el, label)
        if d is None and w is None:
            continue
        if min_size and max(d or 0, w or 0, h or 0) < min_size:
            stats['small'] += 1
            continue
        segs = []        # (s0, s1, p0, p1, struct, normal) — s: расстояние от начала оси
        for lk in lks:
            c = cv if lk.ident else cv.CreateTransformed(lk.Ti)
            a, b = c.GetEndPoint(0), c.GetEndPoint(1)
            is_line = isinstance(c, Line)
            if is_line:
                x0, x1, y0, y1 = min(a.X, b.X), max(a.X, b.X), min(a.Y, b.Y), max(a.Y, b.Y)
                z0, z1 = min(a.Z, b.Z), max(a.Z, b.Z)
            else:
                pts = list(c.Tessellate())
                x0, x1 = min(p.X for p in pts), max(p.X for p in pts)
                y0, y1 = min(p.Y for p in pts), max(p.Y for p in pts)
                z0, z1 = min(p.Z for p in pts), max(p.Z for p in pts)
            for k in lk.query(x0, y0, x1, y1):
                s = lk.structs[k]
                if s.mx.Z < z0 - EPS or s.mn.Z > z1 + EPS or s.mx.X < x0 - EPS or s.mn.X > x1 + EPS \
                        or s.mx.Y < y0 - EPS or s.mn.Y > y1 + EPS:
                    continue
                if is_line and not _seg_box(a, b, s.mn, s.mx, EPS):
                    continue
                if s.solids is None:
                    s.solids = _solids(s.el)
                    if not s.solids:
                        stats['nosolid'] += 1
                for sol in s.solids:
                    try:
                        r = sol.IntersectWithCurve(c, sopt)
                        n = r.SegmentCount
                    except Exception:
                        stats['errors'] += 1
                        continue
                    for i in range(n):
                        sc = r.GetCurveSegment(i)
                        p0, p1 = sc.GetEndPoint(0), sc.GetEndPoint(1)
                        if p0.DistanceTo(p1) < EPS:
                            continue
                        nr = _normal_at(sol, (p0, p1), (p1 - p0).Normalize())
                        s0, s1 = a.DistanceTo(p0), a.DistanceTo(p1)
                        if s0 > s1:
                            s0, s1, p0, p1 = s1, s0, p1, p0
                        if not lk.ident:
                            p0, p1 = lk.T.OfPoint(p0), lk.T.OfPoint(p1)
                            if nr is not None:
                                nr = lk.T.OfVector(nr)
                        segs.append((s0, s1, p0, p1, s, nr))
        if not segs:
            continue
        stats['raw'] += len(segs)
        segs.sort(key=lambda x: x[0])
        # --- склейка слоёв одной конструкции по оси сети
        groups = []
        g_end = 0.0
        for sg in segs:
            if groups and groups[-1][0][4].kind == sg[4].kind and sg[0] <= g_end + max(merge, EPS):
                groups[-1].append(sg)
                g_end = max(g_end, sg[1])
            else:
                groups.append([sg])
                g_end = sg[1]
        ca, cb = cv.GetEndPoint(0), cv.GetEndPoint(1)
        try:
            lvl = el.ReferenceLevel
        except Exception:
            lvl = None
        if lvl is None:
            try:
                lvl = doc.GetElement(el.LevelId)
            except Exception:
                lvl = None
        for g in groups:
            p0 = g[0][2]
            p1 = g[0][3]
            for sg in g:      # самый дальний конец
                if sg[1] >= max(x[1] for x in g):
                    p1 = sg[3]
            length = p0.DistanceTo(p1)
            dv = (p1 - p0).Normalize()
            kind = g[0][4].kind
            nr = None
            for sg in g:
                if sg[5] is not None:
                    nr = sg[5]
                    break
            along = False
            if max_len and length > max_len:
                along = True
                stats['why']['len'] += 1
            if kind == 'walls':
                if abs(dv.Z) > 0.8:
                    if not along:
                        stats['why']['vert'] += 1
                    along = True
                hn = XYZ(nr.X, nr.Y, 0) if nr is not None else XYZ(dv.X, dv.Y, 0)
                if hn.GetLength() < 0.3:
                    hn = XYZ(dv.X, dv.Y, 0)
                if hn.GetLength() < 1e-6:
                    hn = XYZ.BasisX
                n = hn.Normalize()
                if n.X < -1e-9 or (abs(n.X) <= 1e-9 and n.Y < 0):
                    n = n.Negate()
                uv, vv = XYZ.BasisZ.CrossProduct(n), XYZ.BasisZ
            else:
                n = XYZ.BasisZ
                uv, vv = XYZ.BasisX, XYZ.BasisY
                if nr is not None and abs(nr.Z) < 0.3 and abs(dv.Z) < 0.5:      # вошли через торец плиты
                    if not along:
                        stats['why']['edge'] += 1
                    along = True
            cosang = abs(dv.DotProduct(n))
            if cosang < 0.5:
                if not along:
                    stats['why']['angle'] += 1
                along = True
            if along:
                stats['along'] += 1
                if o.get('skip_along'):
                    continue
            thick = abs((p1 - p0).DotProduct(n))
            if not along and thick * FT < (o.get('min_thick') or 0):
                stats['touch'] += 1
                continue
            ia = ins if o.get('insulation') else 0.0
            if d is not None:
                su = sv = d + 2 * ia
                rnd = True
            else:
                bx, by = _basis(el, dv)
                ww, hh = w + 2 * ia, h + 2 * ia
                su = ww * abs(bx.DotProduct(uv)) + hh * abs(by.DotProduct(uv))
                sv = ww * abs(bx.DotProduct(vv)) + hh * abs(by.DotProduct(vv))
                if su < min(ww, hh) * 0.5 or sv < min(ww, hh) * 0.5:      # сечение не определилось
                    su, sv = ww, hh
                rnd = False
            mid = (p0 + p1) * 0.5
            note = []
            if p0.DistanceTo(ca) < EPS or p0.DistanceTo(cb) < EPS or p1.DistanceTo(ca) < EPS or p1.DistanceTo(cb) < EPS:
                note.append(u'сеть заканчивается в конструкции')
            if along:
                note.append(u'сеть идёт вдоль конструкции')
            ang = 0
            if not along and cosang < 0.94:
                ang = int(round(math.degrees(math.acos(min(1.0, cosang)))))
            sids = []
            for sg in g:
                if sg[4] not in sids:
                    sids.append(sg[4])
            if lvl is not None:
                levels[_iv(lvl.Id)] = lvl
            crossings.append({
                'el': el, 'label': label, 'kind': kind, 'structs': sids, 'n': n, 'uv': uv, 'vv': vv,
                'mid': mid, 'thick': thick, 'round': rnd, 'su': su, 'sv': sv, 'd': d, 'w': w, 'h': h, 'ins': ins,
                'lvl': lvl, 'note': note, 'ang': ang, 'zlo': min(p0.Z, p1.Z), 'zhi': max(p0.Z, p1.Z),
            })
    stats['cross'] = len(crossings)
    stats['time']['cross'] = time.time() - t0

    # --- отверстия: запас, объединение близких в одной конструкции
    t0 = time.time()
    radd, qadd = (o['round_add'] or 0) / FT, (o['rect_add'] or 0) / FT
    for c in crossings:
        if c['round']:
            c['hu'] = c['hv'] = c['su'] + radd
        else:
            c['hu'], c['hv'] = c['su'] + 2 * qadd, c['sv'] + 2 * qadd
        c['u'], c['v'] = c['mid'].DotProduct(c['uv']), c['mid'].DotProduct(c['vv'])
    parent = list(range(len(crossings)))

    def root(i):
        while parent[i] != i:
            parent[i] = parent[parent[i]]
            i = parent[i]
        return i

    if merge > 0:
        buckets = {}
        for i, c in enumerate(crossings):
            for s in c['structs']:
                buckets.setdefault((s.lk.id, _iv(s.el.Id)), []).append(i)
        for lst in buckets.values():
            lst.sort(key=lambda i: crossings[i]['u'])
            for a in range(len(lst)):
                ca_ = crossings[lst[a]]
                for b in range(a + 1, len(lst)):
                    cb_ = crossings[lst[b]]
                    gu = (cb_['u'] - ca_['u']) - (ca_['hu'] + cb_['hu']) / 2.0
                    if gu > merge + 20.0:
                        break
                    if ca_['kind'] != cb_['kind'] or abs(ca_['n'].DotProduct(cb_['n'])) < 0.99:
                        continue
                    if ca_['kind'] == 'walls' and abs((cb_['mid'] - ca_['mid']).DotProduct(ca_['n'])) > max(ca_['thick'], cb_['thick']) + 1.0:
                        continue
                    if ca_['kind'] != 'walls' and (ca_['zlo'] > cb_['zhi'] + 1.0 or cb_['zlo'] > ca_['zhi'] + 1.0):
                        continue
                    gv = abs(cb_['v'] - ca_['v']) - (ca_['hv'] + cb_['hv']) / 2.0
                    if gu < merge and gv < merge:
                        ra, rb = root(lst[a]), root(lst[b])
                        if ra != rb:
                            parent[rb] = ra
    groups = {}
    for i in range(len(crossings)):
        groups.setdefault(root(i), []).append(crossings[i])

    rto = o['round_to'] or 0

    def up(mm):
        if rto > 0:
            return int(math.ceil(mm / rto - 1e-6) * rto)
        return int(round(mm))

    all_levels = []
    try:
        from Autodesk.Revit.DB import Level
        all_levels = sorted(FilteredElementCollector(doc).OfClass(Level), key=lambda l: l.Elevation)
    except Exception:
        pass

    def _prefix(name):
        return name.split(u'.')[0] if u'.' in name else u''

    def level_by_z(z, base):
        """Самый высокий уровень не выше z (допуск 50 мм) из той же группы уровней, что уровень сети
        (группа — часть имени до первой точки: «Л.Э01» и «Л.Кровля» — одно здание)."""
        pref = _prefix(base.Name) if base is not None else None
        best = None
        for l in all_levels:
            if pref is not None and _prefix(l.Name) != pref:
                continue
            if l.Elevation <= z + 50.0 / FT:
                best = l
        return best or base

    rows = []
    for g in groups.values():
        c0 = g[0]
        u0 = min(c['u'] - c['hu'] / 2.0 for c in g)
        u1 = max(c['u'] + c['hu'] / 2.0 for c in g)
        v0 = min(c['v'] - c['hv'] / 2.0 for c in g)
        v1 = max(c['v'] + c['hv'] / 2.0 for c in g)
        center = c0['mid'] + c0['uv'] * ((u0 + u1) / 2.0 - c0['u']) + c0['vv'] * ((v0 + v1) / 2.0 - c0['v'])
        single = len(g) == 1
        hw, hh = up((u1 - u0) * FT), up((v1 - v0) * FT)
        if single and c0['round']:
            hole = u'Ø%d' % hw
        else:
            hole = u'%dх%d' % (hw, hh)
        kind = c0['kind']
        if kind == 'walls':
            zc = center.Z
            zb = zc - hh / FT / 2.0
        else:
            zb = min(c['zlo'] for c in g)
            zc = (zb + max(c['zhi'] for c in g)) / 2.0
        lvl = None
        for c in g:
            if c['lvl'] is not None and (lvl is None or c['lvl'].Elevation < lvl.Elevation):
                lvl = c['lvl']
        if o.get('level_mode') != 'element':
            lvl = level_by_z(zc if kind == 'walls' else max(c['zhi'] for c in g), lvl)
        structs = []
        for c in g:
            for s in c['structs']:
                if s not in structs:
                    structs.append(s)
        names, mats, storeys, lnames = [], [], [], []
        for s in structs:
            nm = _ps(s.el, u'IfcName') or (s.el.Name or u'')
            if not _ps(s.el, u'IfcName'):
                try:
                    t = s.lk.doc.GetElement(s.el.GetTypeId())
                    if t is not None:
                        nm = t.get_Parameter(BuiltInParameter.SYMBOL_NAME_PARAM).AsString() or nm
                except Exception:
                    pass
            for lst, val in ((names, nm), (mats, _ps(s.el, u'IfcMaterial')), (storeys, _ps(s.el, u'IfcSpatialContainer')),
                             (lnames, s.lk.name)):
                if val and val not in lst:
                    lst.append(val)
        nets, systems, sizes, notes, ids = [], [], [], [], []
        for c in g:
            el = c['el']
            ids.append(_iv(el.Id))
            if c['label'] not in nets:
                nets.append(c['label'])
            sn = u''
            try:
                p = el.get_Parameter(BuiltInParameter.RBS_SYSTEM_NAME_PARAM)
                sn = (p.AsString() or u'') if p is not None else u''
            except Exception:
                pass
            if sn and sn not in systems:
                systems.append(sn)
            if c['d'] is not None:
                sz = u'Ø%d' % int(round(c['d'] * FT))
            else:
                sz = u'%dх%d' % (int(round(c['w'] * FT)), int(round(c['h'] * FT)))
            if sz not in sizes:
                sizes.append(sz)
            for nt in c['note']:
                if nt not in notes:
                    notes.append(nt)
        ang = max(c['ang'] for c in g)
        if ang:
            notes.append(u'под углом %d° к нормали' % ang if single else u'под углом до %d° к нормали' % ang)
        if not single:
            notes.insert(0, u'объединено: %d' % len(g))
        if len(structs) > 1:
            notes.append(u'слоёв: %d' % len(structs))
        rows.append({
            'n': 0, 'level': lvl.Name if lvl is not None else u'', '_lz': lvl.Elevation if lvl is not None else -1e9,
            'kind': KINDS[[k[0] for k in KINDS].index(kind)][2], 'sname': u'; '.join(names), 'smat': u'; '.join(mats),
            'thick': int(round(max(c['thick'] for c in g) * FT)), 'net': u'; '.join(nets), 'system': u'; '.join(systems),
            'nsize': u'; '.join(sizes), 'ins': int(round(max(c['ins'] for c in g) * FT)), 'hole': hole,
            'hw': hw, 'hh': hh, 'zc': int(round(zc * FT)), 'zb': int(round(zb * FT)),
            'zrel': int(round((zb - lvl.Elevation) * FT)) if lvl is not None else None,
            'x': int(round(center.X * FT)), 'y': int(round(center.Y * FT)), 'cnt': len(g),
            'ids': u', '.join(u'%d' % i for i in ids), 'sid': u', '.join(u'%d' % _iv(s.el.Id) for s in structs),
            'storey': u'; '.join(storeys), 'link': u'; '.join(lnames), 'note': u'; '.join(notes), 'elids': ids,
        })
    rows.sort(key=lambda r: (r['_lz'], r['level'], r['kind'], r['y'], r['x']))
    for i, r in enumerate(rows):
        r['n'] = i + 1
        stats['by_level'][r['level'] or u'(без уровня)'] = stats['by_level'].get(r['level'] or u'(без уровня)', 0) + 1
        stats['by_kind'][r['kind']] = stats['by_kind'].get(r['kind'], 0) + 1
    stats['holes'] = len(rows)
    stats['time']['holes'] = time.time() - t0
    stats['time']['total'] = sum(stats['time'].values())
    stats['level_order'] = []
    for r in rows:
        k = r['level'] or u'(без уровня)'
        if k not in stats['level_order']:
            stats['level_order'].append(k)
    return rows, stats


def summary(stats):
    """Одна-две строки итога для окна."""
    t = stats['time'].get('total', 0)
    by = u', '.join(u'%s — %d' % (k, stats['by_level'][k]) for k in stats.get('level_order', []))
    kinds = u', '.join(u'%s — %d' % (k, v) for k, v in sorted(stats['by_kind'].items()))
    s = (u'Отверстий: %d (пересечений %d; сетей проверено %d, конструкций %d). %s. По этажам: %s. '
         u'Вдоль конструкций: %d, касаний: %d. Время: %.1f с.'
         % (stats['holes'], stats['cross'], stats['curves'], stats['structs'], kinds or u'—', by or u'—',
            stats['along'], stats['touch'], t))
    if stats['nosolid']:
        s += u' Конструкций без тела (сетка, не проверены): %d.' % stats['nosolid']
    if stats['errors']:
        s += u' Ошибок геометрии: %d.' % stats['errors']
    return s


def to_csv(rows, path):
    import io
    lines = [u';'.join(c[1] for c in COLUMNS)]
    for r in rows:
        vals = []
        for key, _, typ in COLUMNS:
            v = r.get(key)
            v = u'' if v is None else (u'%s' % v)
            vals.append(v.replace(u';', u','))
        lines.append(u';'.join(vals))
    with io.open(path, 'w', encoding='utf-8-sig') as f:
        f.write(u'\r\n'.join(lines))
    return path
