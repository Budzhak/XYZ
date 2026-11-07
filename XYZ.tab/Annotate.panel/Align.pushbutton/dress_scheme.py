# -*- coding: utf-8 -*-
"""
Оформить взрыв-схему ПО ШАГАМ (XYZ -> По красоте -> «Оформить взрыв-схему: шаг…»).

Каждый шаг - отдельный запуск и отдельный Ctrl+Z. После шага инженер смотрит
и правит руками, потом запускает следующий. Работает по выделенным элементам
(или по всему виду), уже подписанное не трогает.

  1  Разнос выделенного вверх/вниз + линии траектории: одна на разрыв, по оси
     участка; фитинги между выделенными (и скрытые) добавляются сами.
     Воздуховоды и трубы.
  1а Перестроить линии траектории всех разносов вида по тому же правилу.
  Осевые линии смещаемых труб/воздуховодов/фитингов смещаются вместе с ними.
  2  Высотные отметки: несмещённые участки - высотная отметка Revit
     (db_Стрелка_Проектная_Планы_Вниз/Вверх): прямоугольный - низ, круглый - ось,
     плечо в точке, горизонтальная полка 3-12 мм; смещённые - марка-отметка.
     Схемы ТРУБ (фреон): отметка только там, где меняется высота (ходы одной
     высоты через короткие уступы — одна отметка; ход < 1 м — без отметки; пара
     жидкость/газ — один ход), по оси; оборудование — низ. Смещённое — марка-отметка
     («Отметка на взрыв-схеме»). Типы «db_Стрелка_Проектная_Схемы_Вверх/Вниз» —
     рабочая плоскость вида ставится горизонтальной (иначе текст уезжает от полки).
  3  Марки «Имя системы - Размер» - один раз на кусок системы (между разрывами
     взрыв-схемы)
  4  Полупрозрачность 50 %: «#прозрачно#» в «Комментарии» + фильтр db_Прозрачно_50
  5  Дроссель-клапаны на магистралях      (db_M_Несколько категорий : ADSK_Марка)
  6  Шумоглушители                         (то же)
  7  Оборудование                          (db_М_по_НК_Оборудование_№ пом)
  8  Тройники и крестовины, где сечение не прочитать (db_М_по_НК_3.0)
  9  Марки «Размер» на остальных участках другого сечения (в самом конце)

Раскладка марок: перебор мест (строка выше/ниже на 8-80 мм, справа/слева,
сдвиг по горизонтали). Нельзя: налезать на марки, отметки и их выноски.
Штраф: перекрывать воздуховоды (полосой по их ширине), длинная выноска.
Если чистого места нет - марка НЕ ставится, элемент попадает в отчёт и
выделяется после шага (подписать вручную).
"""
import math
from Autodesk.Revit.DB import *

FT_MM = 304.8
MIN_RUN_MM = 400.0
MIN_HZ_MM = 300.0
HARD = 1e5

T_SYS = (u'Воздуховоды_3.1', u'Имя системы - Размер')
T_SIZE = (u'Воздуховоды_2.0', u'Размер')
T_ACC = (u'Несколько категорий', u'ADSK_Марка')
T_FIT = (u'по_НК_3.0', u'2.5 _ db_Наименование краткое _ db_Размер')
T_EQ = (u'по_НК_Оборудование', u'db_М_по_НК_Имя типа_№ пом')
T_SPOT_DN = u'db_Стрелка_Проектная_Планы_Вниз'
T_SPOT_UP = u'db_Стрелка_Проектная_Планы_Вверх'
MARK = u'#прозрачно#'
FILTER_TR = u'db_Прозрачно_50'

STEPS = [
    ('explode', u"Разнос выделенного (и вложенный) + линии"),
    ('paths', u"Линии траектории: дополнить недостающие"),
    ('paths_reset', u"Линии траектории: перестроить все заново (ручные правки удалятся)"),
    ('addto', u"Перенести выделенное в другой набор разноса"),
    ('vrf', u"Схема VRF целиком: отметки → оборудование → разветвители и трубы"),
    ('elev', u"Высотные отметки"),
    ('ptags', u"Марки труб, разветвителей и EEV-китов"),
    ('xeq', u"Оборудование: ККБ — имя системы + марка с Q; VRF — модель, Qх, № пом."),
    ('sys', u"Марки «Имя системы - Размер»"),
    ('transp', u"Полупрозрачность 50 % (выделенное)"),
    ('damper', u"Дроссель-клапаны"),
    ('silencer', u"Шумоглушители"),
    ('equip', u"Оборудование"),
    ('tees', u"Тройники и крестовины"),
    ('size', u"Марки «Размер» на остальных участках"),
    # 01.11.2026: схемы отопления с коллекторами (код — dress_fan.py)
    ('fan', u"Веер лучей от выделенных коллекторов (разнос по высоте + марки)"),
    ('eqtags', u"Марки приборов: прямая выноска поодаль (выделенные приборы)"),
]

BIC = BuiltInCategory
C_DUCT = int(BIC.OST_DuctCurves)
C_FIT = int(BIC.OST_DuctFitting)
C_ACC = int(BIC.OST_DuctAccessory)
C_EQ = int(BIC.OST_MechanicalEquipment)
C_TERM = int(BIC.OST_DuctTerminal)
C_FLEX = int(BIC.OST_FlexDuctCurves)
C_INS = int(BIC.OST_DuctInsulations)


# ================================================================== общее
def _iv(eid):
    try:
        return eid.Value
    except Exception:
        return eid.IntegerValue


def _cat(el):
    try:
        return _iv(el.Category.Id)
    except Exception:
        return None


def _fam(el):
    try:
        return el.Symbol.FamilyName
    except Exception:
        return u''


def _sys(el):
    p = el.get_Parameter(BuiltInParameter.RBS_SYSTEM_NAME_PARAM)
    return (p.AsString() or u'') if p is not None else u''


def _size(el):
    p = el.get_Parameter(BuiltInParameter.RBS_CALCULATED_SIZE)
    return (p.AsString() or u'') if p is not None else u''


def _mont(el):
    p = el.LookupParameter(u"db_В монтаж")
    if p is None or not p.HasValue:
        return True
    return p.AsInteger() == 1


def _conns(el):
    try:
        cm = el.ConnectorManager if isinstance(el, MEPCurve) else el.MEPModel.ConnectorManager
    except Exception:
        cm = None
    if cm is None:
        return []
    return [c for c in cm.Connectors
            if c.Domain == Domain.DomainHvac and c.ConnectorType == ConnectorType.End]


def _next(c):
    for r in c.AllRefs:
        o = r.Owner
        if o.Id == c.Owner.Id or o.Category is None:
            continue
        if _cat(o) == C_INS or r.ConnectorType == ConnectorType.Logical:
            continue
        return r
    return None


def _find_tag_type(doc, fam_part, type_name):
    for s in FilteredElementCollector(doc).OfClass(FamilySymbol):
        try:
            if s.FamilyName.startswith(u'db_') and fam_part in s.FamilyName and \
                    s.get_Parameter(BuiltInParameter.ALL_MODEL_TYPE_NAME).AsString() == type_name:
                return s
        except Exception:
            pass
    return None


def _spot_type(doc, name):
    for t in FilteredElementCollector(doc).OfClass(SpotDimensionType):
        if t.get_Parameter(BuiltInParameter.ALL_MODEL_TYPE_NAME).AsString() == name:
            return t
    return None


def _overlap(a, b, m=0.0):
    return min(a[2], b[2]) - max(a[0], b[0]) > -m and min(a[3], b[3]) - max(a[1], b[1]) > -m


def _seg_hits_box(p, q, b):
    """Отрезок p-q (u,v) пересекает прямоугольник b."""
    (x0, y0), (x1, y1) = p, q
    if max(x0, x1) < b[0] or min(x0, x1) > b[2] or max(y0, y1) < b[1] or min(y0, y1) > b[3]:
        return False
    if b[0] <= x0 <= b[2] and b[1] <= y0 <= b[3]:
        return True
    n = 12
    for k in range(1, n + 1):
        x = x0 + (x1 - x0) * k / float(n)
        y = y0 + (y1 - y0) * k / float(n)
        if b[0] <= x <= b[2] and b[1] <= y <= b[3]:
            return True
    return False


class Occ(object):
    """Занятые места на листе (мм): рамки марок/отметок, их выноски, полосы воздуховодов."""
    def __init__(self):
        self.boxes = []
        self.segs = []
        self.cell = 2.0
        self.band = {}
        self.lines = []     # оси труб/воздуховодов на листе: выноска поперёк чужой трубы — штраф
        self.cross_w = 150.0
        self.soft = {}      # рамка марки-отметки -> её часть с текстом: выноска через указатель у полки — можно, через текст — нет (db, 4174296, 17.10)
        self.band_w = 6.0   # штраф за клетку полосы под рамкой марки (схемы труб — 25)

    def add_box(self, b):
        self.boxes.append(b)

    def add_seg(self, p, q):
        self.segs.append((p, q))

    def add_band(self, a, b, r, line=True):
        if line:
            self.lines.append((a, b))
        L = math.hypot(b[0] - a[0], b[1] - a[1])
        n = max(1, int(L / 1.0))
        rr = int(math.ceil(r / self.cell))
        for k in range(n + 1):
            u = a[0] + (b[0] - a[0]) * k / float(n)
            v = a[1] + (b[1] - a[1]) * k / float(n)
            i0, j0 = int(math.floor(u / self.cell)), int(math.floor(v / self.cell))
            for i in range(i0 - rr, i0 + rr + 1):
                for j in range(j0 - rr, j0 + rr + 1):
                    self.band[(i, j)] = 1

    def band_cells(self, b):
        c = 0
        for i in range(int(math.floor(b[0] / self.cell)), int(math.floor(b[2] / self.cell)) + 1):
            for j in range(int(math.floor(b[1] / self.cell)), int(math.floor(b[3] / self.cell)) + 1):
                if (i, j) in self.band:
                    c += 1
        return c

    def box_cost(self, b, margin=1.0):
        for o in self.boxes:
            if _overlap(b, o, margin):
                return HARD
        for (p, q) in self.segs:
            if _seg_hits_box(p, q, b):
                return HARD
        return self.band_cells(b) * self.band_w

    def lead_cost(self, pts):
        c = 0.0
        for k in range(len(pts) - 1):
            for o in self.boxes:
                if _seg_hits_box(pts[k], pts[k + 1], o):
                    hp = self.soft.get(o)
                    c += 300.0 if (hp is not None and not _seg_hits_box(pts[k], pts[k + 1], hp)) else 2000.0
        # пересечение с уже поставленными выносками других марок
        for k in range(len(pts) - 1):
            for (p, q) in self.segs:
                if _segs_cross(pts[k], pts[k + 1], p, q):
                    c += 300.0
        # выноска поперёк чужой трубы (правки db на С.Х.VRF2, 17.10): первые 1,5 мм от
        # точки привязки не считаются — там своя труба (3 мм: на узле разветвителя сходятся
        # несколько труб — марка ARBLN03321 у ARNU48 иначе не вставала, t17)
        if self.lines and len(pts) >= 2:
            (x0, y0), (x1, y1) = pts[0], pts[1]
            L = math.hypot(x1 - x0, y1 - y0)
            st = (x0 + (x1 - x0) * min(1.0, 3.0 / L), y0 + (y1 - y0) * min(1.0, 3.0 / L)) if L > 1e-6 else pts[0]
            pp = [st] + list(pts[1:])
            for k in range(len(pp) - 1):
                for (a, b) in self.lines:
                    if _segs_cross(pp[k], pp[k + 1], a, b):
                        c += self.cross_w
        return c + self.lead_band_cost(pts)

    def lead_band_cost(self, pts, skip=1.5):
        """Выноска вдоль чужих труб/воздуховодов: клетки полос под выноской
        (первые skip мм от точки привязки не считаются — она стоит на своей трубе)."""
        if not self.band:
            return 0.0
        cells, run = set(), 0.0
        for k in range(len(pts) - 1):
            (x0, y0), (x1, y1) = pts[k], pts[k + 1]
            L = math.hypot(x1 - x0, y1 - y0)
            n = max(1, int(L / 0.8))
            for m in range(n + 1):
                d = run + L * m / float(n)
                if d < skip:
                    continue
                u = x0 + (x1 - x0) * m / float(n)
                v = y0 + (y1 - y0) * m / float(n)
                cl = (int(math.floor(u / self.cell)), int(math.floor(v / self.cell)))
                if cl in self.band:
                    cells.add(cl)
            run += L
        return len(cells) * 3.0


class Ctx(object):
    """Всё, что нужно шагам: вид, смещения, что подписано, занятость."""
    def __init__(self, doc, view, elems, need_occ=True, exclude=None):
        import stack_tags
        self.doc, self.view = doc, view
        self.R, self.U = view.RightDirection, view.UpDirection
        self.mm = view.Scale / FT_MM
        self.rep, self.skipped, self.forced = {}, [], []
        self.angled = False   # схемы труб: выноски «вертикально, потом полка» (как у инженера)
        # базовые длины угловой выноски (мм листа): вертикаль, полка; шаг марок труб
        # ставит их по типу схемы (PIPE_LEAD). Тесно — длиннее (стандарт, 2.7).
        self.tV, self.tH = 15.0, 9.0
        self.group_of = None   # {Id элемента: ключ колонки} — колонки заданы заранее
        self.line = {}         # {Id элемента: 'L' жидкость / 'G' газ}
        self.group_kind = {}   # {ключ колонки: 'riser'} — пара на стояке
        self.with_sizes = False
        self.dvec, self.dset = {}, {}
        for de in FilteredElementCollector(doc, view.Id).OfClass(DisplacementElement):
            d = de.GetAbsoluteDisplacement()
            for i in de.GetDisplacedElementIds():
                self.dvec[_iv(i)] = d
                self.dset[_iv(i)] = _iv(de.Id)
        self.kinds = {}
        self.exclude = set(exclude or [])
        self.tags = [t for t in FilteredElementCollector(doc, view.Id).OfClass(IndependentTag)
                     if _iv(t.Id) not in self.exclude]
        try:
            self.sbox = view.GetSectionBox() if view.IsSectionBoxActive else None
        except Exception:
            self.sbox = None
        for t in self.tags:
            sym = doc.GetElement(t.GetTypeId())
            fn = sym.FamilyName if sym is not None else u''
            k = u'ОТМ' if u'Отметка' in fn else (u'ВОЗД' if u'Воздуховоды' in fn else u'ДР')
            try:
                tn = sym.get_Parameter(BuiltInParameter.ALL_MODEL_TYPE_NAME).AsString() or u''
            except Exception:
                tn = u''
            for i in t.GetTaggedLocalElementIds():
                ks = self.kinds.setdefault(_iv(i), set())
                ks.add(k)
                if k == u'ВОЗД':
                    ks.add(u'СИС' if u'Имя системы' in tn else u'РАЗ')
        self.spots = list(FilteredElementCollector(doc, view.Id).OfClass(SpotDimension))
        self.spotted = set()
        for sp in self.spots:
            for r in sp.References:
                self.spotted.add(_iv(r.ElementId))
        self.tagged = set(self.kinds.keys())
        from System.Collections.Generic import List
        cats = [BIC.OST_DuctCurves, BIC.OST_DuctFitting, BIC.OST_DuctAccessory,
                BIC.OST_MechanicalEquipment, BIC.OST_DuctTerminal, BIC.OST_FlexDuctCurves]
        mf = ElementMulticategoryFilter(List[BuiltInCategory](cats))
        self.all_els = list(FilteredElementCollector(doc, view.Id).WherePasses(mf).WhereElementIsNotElementType())
        self.scope = set(_iv(e.Id) for e in (elems or self.all_els))
        self.scope_given = set(_iv(e.Id) for e in elems) if elems else None
        self.occ = Occ()
        if need_occ:
            self._build_occ(stack_tags)

    # ---- координаты
    def uv(self, p):
        return (p.DotProduct(self.R) / self.mm, p.DotProduct(self.U) / self.mm)

    def visible_pt(self, p):
        """Точка (несмещённая) внутри 3D-подрезки вида."""
        if self.sbox is None:
            return True
        q = self.sbox.Transform.Inverse.OfPoint(p)
        mn, mx = self.sbox.Min, self.sbox.Max
        return mn.X <= q.X <= mx.X and mn.Y <= q.Y <= mx.Y and mn.Z <= q.Z <= mx.Z

    def dp(self, el):
        return self.dvec.get(_iv(el.Id), XYZ.Zero)

    def in_scope(self, el):
        if _iv(el.Id) not in self.scope:
            return False
        if _cat(el) in (C_DUCT, C_FIT):
            return _mont(el)
        return True

    def add(self, key, n=1):
        self.rep[key] = self.rep.get(key, 0) + n

    def _build_occ(self, stack_tags):
        rels = stack_tags.measure_exact(self.doc, self.view, self.tags, self.R, self.U, self.mm) if self.tags else []
        for t, rel in zip(self.tags, rels):
            hu, hv = self.uv(t.TagHeadPosition)
            if rel is None:
                rel = (-6 * self.mm, -2.5 * self.mm, 6 * self.mm, 2.5 * self.mm)
            bx = (hu + rel[0] / self.mm, hv + rel[1] / self.mm, hu + rel[2] / self.mm, hv + rel[3] / self.mm)
            self.occ.add_box(bx)
            try:
                ty_ = self.doc.GetElement(t.GetTypeId())
                if u'Отметка' in (ty_.FamilyName or u''):
                    tn = (Element.Name.GetValue(ty_) or u'').lower()
                    if u'вверху' in tn:
                        self.occ.soft[bx] = (bx[0], bx[1] + 4.0, bx[2], bx[3])
                    elif u'внизу' in tn:
                        self.occ.soft[bx] = (bx[0], bx[1], bx[2], bx[3] - 4.0)
            except Exception:
                pass
            self._add_leader_segs(t)
        for sp in self.spots:
            self._occ_spot(sp)
        for el in self.all_els:
            if _cat(el) not in (C_DUCT, C_FLEX):
                continue
            lc = el.Location
            if not isinstance(lc, LocationCurve):
                continue
            c = lc.Curve
            d = self.dp(el)
            a = self.uv(c.GetEndPoint(0) + d)
            b = self.uv(c.GetEndPoint(1) + d)
            r = 1.0
            try:
                sz = max([x.Width if x.Shape != ConnectorProfileType.Round else x.Radius * 2
                          for x in _conns(el)] or [0])
                r = max(1.0, sz * FT_MM / self.view.Scale / 2.0)
            except Exception:
                pass
            self.occ.add_band(a, b, r)

    def _add_leader_segs(self, t):
        try:
            if not t.HasLeader or t.LeaderEndCondition != LeaderEndCondition.Free:
                return
            for r in t.GetTaggedReferences():
                e = t.GetLeaderEnd(r)
                pts = [self.uv(e)]
                try:
                    if t.HasLeaderElbow(r):
                        pts.append(self.uv(t.GetLeaderElbow(r)))
                except Exception:
                    pass
                pts.append(self.uv(t.TagHeadPosition))
                for k in range(len(pts) - 1):
                    self.occ.add_seg(pts[k], pts[k + 1])
                break
        except Exception:
            pass

    def _occ_spot(self, sp):
        try:
            o = self.uv(sp.Origin)
            e = self.uv(sp.LeaderEndPosition)
            t = self.uv(sp.TextPosition)
            self.occ.add_box((t[0] - 8.5, t[1] - 2.8, t[0] + 8.5, t[1] + 2.8))
            self.occ.add_seg(o, e)
        except Exception:
            pass

    def report(self, title):
        lines = [title]
        for k in sorted(self.rep):
            lines.append(u"  {} — {}".format(k, self.rep[k]))
        if self.skipped:
            lines.append(u"  Не нашлось чистого места — {} (выделены, подпишите вручную)".format(len(self.skipped)))
        if len(lines) == 1:
            lines.append(u"  нечего добавлять — всё уже оформлено")
        return u"\n".join(lines)


def anchors_of(ctx, el, ts=(0.5, 0.35, 0.65, 0.2, 0.8)):
    """Точки привязки на видимой (внутри 3D-подрезки) части элемента."""
    lc = el.Location
    if isinstance(lc, LocationCurve):
        out = []
        for t in ts:
            p = lc.Curve.Evaluate(t, True)
            if ctx.visible_pt(p):
                out.append(p + ctx.dp(el))
        return out
    return [anchor_of(ctx, el)]


def anchor_of(ctx, el, t=0.5):
    lc = el.Location
    if isinstance(lc, LocationCurve):
        p = lc.Curve.Evaluate(t, True)
    elif isinstance(lc, LocationPoint):
        p = lc.Point
    else:
        bb = el.get_BoundingBox(None)
        p = (bb.Min + bb.Max) / 2.0
    return p + ctx.dp(el)


# ================================================================== раскладка марок
def place_tags(ctx, jobs, title):
    """jobs: [(el, symbol, [anchor3d, ...], what)]. Создаёт марки и раскладывает их
    КОМПАКТНО, как инженер руками («Сброс марок», «Колонка с угловыми выносками»):
    близкие марки - колонкой с угловыми выносками, одиночные - короткая прямая
    выноска вбок/вверх. Нет места - марка не ставится, элемент выделяется."""
    doc, view, mm = ctx.doc, ctx.view, ctx.mm
    jobs = [j for j in jobs if j[2]]
    created = []
    # Марки создаются на временной плоскости ВДОЛЬ ЭКРАНА (как «Колонка», «Сброс марок»).
    # На горизонтальной плоскости вида (её ставит шаг отметок) Revit рисует свободный
    # конец выноски не там, где он задан, — выноски «висят в воздухе» (14.10.2026).
    import xyz_plane
    xyz_plane.Transaction = Transaction
    ptok = xyz_plane.push(doc, view, view.ViewDirection, view.Origin, title + u": плоскость")
    try:
        _place_tags_in(ctx, jobs, title, created)
    finally:
        xyz_plane.pop(doc, view, ptok)


def _place_tags_in(ctx, jobs, title, created):
    doc, view, mm = ctx.doc, ctx.view, ctx.mm
    t = Transaction(doc, title + u": марки")
    t.Start()
    try:
        for el, sym, anchors, what in jobs:
            try:
                if not sym.IsActive:
                    sym.Activate()
                tg = IndependentTag.Create(doc, sym.Id, view.Id, Reference(el), True,
                                           TagOrientation.Horizontal, anchors[0])
                tg.LeaderEndCondition = LeaderEndCondition.Free
                created.append((tg, el, anchors, what))
            except Exception as ex:
                ctx.add(u'Ошибка: ' + unicode(ex)[:50])
        t.Commit()
    except Exception:
        t.RollBack()
        raise
    if created:
        tidy(ctx, created, title)


def tidy(ctx, items, title):
    """items: [(tag, el, [anchor3d...], what)]. Раскладка: кластеры близких точек
    привязки (до 25 мм на листе) - колонкой, одиночки - коротко рядом."""
    import stack_tags
    doc, view, mm = ctx.doc, ctx.view, ctx.mm
    rels = stack_tags.measure_exact(doc, view, [x[0] for x in items], ctx.R, ctx.U, mm)
    n = len(items)
    A = [ctx.uv(it[2][0]) for it in items]
    par = list(range(n))

    def find(i):
        while par[i] != i:
            par[i] = par[par[i]]
            i = par[i]
        return i
    if ctx.group_of is not None:
        # колонки заданы шагом (пары жидкость/газ одного участка, пара разветвителя)
        keyidx = {}
        for i in range(n):
            k = ctx.group_of.get(_iv(items[i][1].Id))
            if k is None:
                continue
            if k in keyidx:
                par[find(i)] = find(keyidx[k])
            else:
                keyidx[k] = i
    elif ctx.angled:
        # схемы труб: у инженера колонки по 2 (жидкость + газ), реже 3–4 марки
        # (ККБ1/ККБ2_ТЕСТ, 14.10) — объединяем ближайшие точки до 12 мм, не больше 4
        size = [1] * n
        pairs = sorted((math.hypot(A[i][0] - A[j][0], A[i][1] - A[j][1]), i, j)
                       for i in range(n) for j in range(i + 1, n))
        for dd, i, j in pairs:
            if dd >= 12.0:
                break
            ri, rj = find(i), find(j)
            if ri != rj and size[ri] + size[rj] <= 4:
                par[ri] = rj
                size[rj] += size[ri]
    else:
        for i in range(n):
            for j in range(i + 1, n):
                if math.hypot(A[i][0] - A[j][0], A[i][1] - A[j][1]) < 25.0:
                    par[find(i)] = find(j)
    groups = {}
    for i in range(n):
        groups.setdefault(find(i), []).append(i)
    to_delete = []
    t = Transaction(doc, title + u": раскладка")
    t.Start()
    try:
        def _prio(g):
            k = ctx.group_of.get(_iv(items[g[0]][1].Id), u'') if ctx.group_of is not None else u''
            first = 0 if (k.startswith(u'ref') or k.startswith(u'r1') or k.startswith(u'eev')) else 1
            return (first, -len(g))
        merged_done = set()
        for g in sorted(groups.values(), key=_prio):
            sz = [((rels[i] or (-6 * mm, -2.5 * mm, 6 * mm, 2.5 * mm))) for i in g]
            sz = [tuple(x / mm for x in r) for r in sz]
            ok = False
            gk = None
            if ctx.group_of is not None:
                gk = ctx.group_kind.get(ctx.group_of.get(_iv(items[g[0]][1].Id)))
            if id(g) in merged_done:
                continue
            if gk == 'riser' and len(g) == 2:
                ok = _riser_pair(ctx, items, g, sz)
            gkey = ctx.group_of.get(_iv(items[g[0]][1].Id), u'') if ctx.group_of is not None else u''
            if not ok and len(g) == 2 and gkey.startswith(u'ref'):
                # db на С.Х.VRF2: пара разветвителя и пара труб рядом — одна колонка из 4
                cu_ = sum(A[i][0] for i in g) / 2.0
                cv_ = sum(A[i][1] for i in g) / 2.0
                best_ = None
                for g2 in groups.values():
                    if g2 is g or len(g2) != 2 or id(g2) in merged_done:
                        continue
                    k2 = ctx.group_of.get(_iv(items[g2[0]][1].Id), u'')
                    if not k2.startswith(u'pair') or ctx.group_kind.get(k2) == 'riser':
                        continue
                    dd = math.hypot(sum(A[i][0] for i in g2) / 2.0 - cu_, sum(A[i][1] for i in g2) / 2.0 - cv_)
                    if dd < 20.0 and (best_ is None or dd < best_[0]):
                        best_ = (dd, g2)
                if best_ is not None:
                    gg = list(g) + list(best_[1])
                    szz = [tuple(x / mm for x in (rels[i] or (-6 * mm, -2.5 * mm, 6 * mm, 2.5 * mm))) for i in gg]
                    if _column(ctx, items, gg, szz, A):
                        merged_done.add(id(best_[1]))
                        for i in gg:
                            ctx.add(items[i][3])
                        continue
            if not ok and len(g) >= 2:
                # колонка от каждой согласованной точки участка (середина, ближе к концам) —
                # берём самую дешёвую; середина чуть предпочтительнее (+3 за шаг)
                nk = min(len(items[i][2]) for i in g)
                cands_ = []
                for ak in range(0, min(nk, 5)):
                    A2 = list(A)
                    for i in g:
                        A2[i] = ctx.uv(items[i][2][ak])
                    cst = _column(ctx, items, g, sz, A2, ak, dry=True)
                    if cst is not None:
                        cands_.append((cst + 3.0 * ak, ak, A2))
                if cands_:
                    cands_.sort(key=lambda x: x[0])
                    ok = _column(ctx, items, g, sz, cands_[0][2], cands_[0][1])
            if not ok:
                for k, i in enumerate(g):
                    if not _single(ctx, items[i], sz[k]):
                        to_delete.append(items[i][0].Id)
                        ctx.skipped.append(items[i][1].Id)
                    else:
                        ctx.add(items[i][3])
            else:
                for i in g:
                    ctx.add(items[i][3])
        for i in to_delete:
            doc.Delete(i)
        t.Commit()
    except Exception:
        t.RollBack()
        raise


def _reset_leader(tag):
    """Свежая свободная выноска без старого излома. Через «Прикреплённый конец» ->
    «Свободный»: так Revit пересчитывает марку на взрыв-схеме. Прежний способ
    (выключить/включить выноску) на смещённых и соседних элементах давал марку,
    нарисованную со сдвигом: конец выноски «висел в воздухе» (14.10.2026)."""
    try:
        if not tag.HasLeader:
            tag.HasLeader = True
        tag.LeaderEndCondition = LeaderEndCondition.Attached
        tag.Document.Regenerate()
        tag.LeaderEndCondition = LeaderEndCondition.Free
    except Exception:
        pass


def _set_tag(ctx, tag, a3, head_uv, elbow_uv=None):
    mm = ctx.mm
    au, av = ctx.uv(a3)
    head = a3 + ctx.R * ((head_uv[0] - au) * mm) + ctx.U * ((head_uv[1] - av) * mm)
    ref = None
    for r_ in tag.GetTaggedReferences():
        ref = r_
        break
    _reset_leader(tag)
    tag.TagHeadPosition = head
    try:
        tag.SetLeaderEnd(ref, a3)
        if elbow_uv is not None:
            tag.SetLeaderElbow(ref, a3 + ctx.R * ((elbow_uv[0] - au) * mm) + ctx.U * ((elbow_uv[1] - av) * mm))
    except Exception:
        pass


def _single(ctx, item, rel):
    """Одиночная марка: короткая прямая выноска вбок (как «Сброс марок»),
    иначе вверх/вниз по вертикали, иначе строка с изломом."""
    tag, el, anchors, what = item
    r0, q0, r1, q1 = rel
    cu, cv = (r0 + r1) / 2.0, (q0 + q1) / 2.0
    best = None
    for a3 in anchors:
        au, av = ctx.uv(a3)
        for L in (6.0, 9.0, 13.0, 18.0, 24.0):
            cands = [
                ('R', au + L - r0, av - cv, None, [(au, av), (au + L, av)]),
                ('L', au - L - r1, av - cv, None, [(au, av), (au - L, av)]),
                ('U', au - cu, av + L - q0, None, [(au, av), (au, av + L)]),
                ('D', au - cu, av - L - q1, None, [(au, av), (au, av - L)]),
            ]
            for sv in (1, -1):
                rowv = av + sv * (L + 4.0)
                cands.append(('ER', au + 2.0 - r0, rowv - cv, (au, rowv), [(au, av), (au, rowv), (au + 2.0, rowv)]))
                cands.append(('EL', au - 2.0 - r1, rowv - cv, (au, rowv), [(au, av), (au, rowv), (au - 2.0, rowv)]))
            vert = ctx.angled and isinstance(el, MEPCurve) and _sheet_vertical(ctx, el)
            if ctx.angled and L == 6.0 and not vert:
                # угловая выноска: базовые длины по типу схемы (стандарт, 2.7), тесно — длиннее
                tV, tH = ctx.tV, ctx.tH
                for V in _lens(tV, (0.0, -3.0, 4.0, 8.0, 13.0, 20.0, 30.0)):
                    for sv in (1, -1):
                        rowv = av + sv * V
                        for H in _lens(tH, (0.0, -4.0, 5.0, 10.0, 16.0)):
                            for sh in (1, -1):
                                hu = (au + sh * H - r0) if sh > 0 else (au - H - r1)
                                cands.append(('A', hu, rowv - cv, (au, rowv),
                                              [(au, av), (au, rowv), (au + sh * H, rowv)], V, H))
            for cd in cands:
                kind, hu, hv, elb, lead = cd[:5]
                box = (hu + r0, hv + q0, hu + r1, hv + q1)
                c = ctx.occ.box_cost(box)
                if c >= HARD:
                    continue
                if kind == 'A':
                    c += ctx.occ.lead_cost(lead) + abs(cd[5] - ctx.tV) * 0.6 + abs(cd[6] - ctx.tH) * 0.6
                elif ctx.angled and not vert:
                    c += ctx.occ.lead_cost(lead) + L * 1.5 + 25.0     # прямая выноска — только если иначе никак
                elif vert:
                    # стояк: только горизонтальная прямая выноска
                    if kind not in ('R', 'L'):
                        continue
                    c += ctx.occ.lead_cost(lead) + L * 1.0
                else:
                    c += ctx.occ.lead_cost(lead) + L * 1.5 + (0 if kind in ('R', 'L') else 4.0)
                if best is None or c < best[0]:
                    best = (c, a3, hu, hv, elb, box, lead)
    if best is None or best[0] >= 2000.0:
        return False
    c, a3, hu, hv, elb, box, lead = best
    if ctx.angled and elb is None and isinstance(el, MEPCurve) and _sheet_vertical(ctx, el):
        # вертикальная на листе труба: прямая выноска «С присоединённым концом» (17.10)
        _set_attached(ctx, tag, a3, (hu, hv))
        ctx.occ.add_box(box)
        for k in range(len(lead) - 1):
            ctx.occ.add_seg(lead[k], lead[k + 1])
        return True
    _set_tag(ctx, tag, a3, (hu, hv), elb)
    ctx.occ.add_box(box)
    for k in range(len(lead) - 1):
        ctx.occ.add_seg(lead[k], lead[k + 1])
    return True


def _lens(base, deltas, lo=3.0):
    out = []
    for d in deltas:
        x = round(base + d, 1)
        if x >= lo and x not in out:
            out.append(x)
    return out


def _segs_cross(p1, p2, q1, q2):
    def orient(a, b, c):
        return (b[0] - a[0]) * (c[1] - a[1]) - (b[1] - a[1]) * (c[0] - a[0])
    d1, d2 = orient(q1, q2, p1), orient(q1, q2, p2)
    d3, d4 = orient(p1, p2, q1), orient(p1, p2, q2)
    return ((d1 > 1e-9 and d2 < -1e-9) or (d1 < -1e-9 and d2 > 1e-9)) and \
           ((d3 > 1e-9 and d4 < -1e-9) or (d3 < -1e-9 and d4 > 1e-9))


def _leads_cross(a, b):
    n = 0
    for k in range(len(a) - 1):
        for m in range(len(b) - 1):
            if _segs_cross(a[k], a[k + 1], b[m], b[m + 1]):
                n += 1
    return n


def _pt_at_v(ctx, el, v):
    """Точка на (смещённой) оси трубы на заданной высоте листа v, иначе None."""
    c = el.Location.Curve
    d = ctx.dp(el)
    p0, p1 = c.GetEndPoint(0) + d, c.GetEndPoint(1) + d
    v0, v1 = ctx.uv(p0)[1], ctx.uv(p1)[1]
    if abs(v1 - v0) < 1e-6:
        return None
    t = (v - v0) / (v1 - v0)
    if t < 0.05 or t > 0.95:
        return None
    q = p0 + (p1 - p0) * t
    return q if ctx.visible_pt(q - d) else None


def _sheet_vertical(ctx, el):
    """Труба на листе вертикальная (стояк в изометрии)."""
    try:
        c = el.Location.Curve
        d = (c.GetEndPoint(1) - c.GetEndPoint(0)).Normalize()
        return abs(d.DotProduct(ctx.R)) < 0.3 * abs(d.DotProduct(ctx.U))
    except Exception:
        return False


def _riser_pair(ctx, items, g, sz):
    """Пара на стояке (трубы на листе вертикальные). Как у инженера (17.10.2026):
    марки одна над другой с шагом колонки, прямые горизонтальные выноски
    «С присоединённым концом» (не Г-образные). Если с одной стороны места нет —
    по обе стороны на одной высоте."""
    h = max(r[3] - r[1] for r in sz)
    step = h + 1.0
    us = [ctx.uv(items[k][2][0])[0] for k in g]
    vs0 = [ctx.uv(a)[1] for a in items[g[0]][2]]
    best = None
    for k0, vb in enumerate(vs0):
        for ax in (1, -1):
            # выноски горизонтальные — не пересекаются при любом порядке: жидкость сверху
            # (как у инженера на С.Х.VRF2: Х3 над Х5), иначе ближняя к стороне марки труба
            lines = [ctx.line.get(_iv(items[g[m]][1].Id)) for m in range(2)]
            if u'L' in lines and u'G' in lines:
                order = sorted(range(2), key=lambda m: 0 if lines[m] == u'L' else 1)
            else:
                order = sorted(range(2), key=lambda m: -ax * us[m])
            for dv in (0.0, -step):
                for L in (5.0, 8.0, 12.0, 16.0, 22.0):
                    edge = (max(us) + L) if ax > 0 else (min(us) - L)
                    plan, cost, ok = [], 0.0, True
                    for row, m in enumerate(order):
                        v = vb + dv - row * step
                        a3 = _pt_at_v(ctx, items[g[m]][1], v)
                        if a3 is None:
                            ok = False
                            break
                        r0, q0, r1, q1 = sz[m]
                        hu = (edge - r0) if ax > 0 else (edge - r1)
                        hv = v - (q0 + q1) / 2.0
                        box = (hu + r0, hv + q0, hu + r1, hv + q1)
                        c = ctx.occ.box_cost(box)
                        if c >= HARD:
                            ok = False
                            break
                        u = ctx.uv(a3)[0]
                        lead = [(u, v), (edge, v)]
                        cost += c + ctx.occ.lead_cost(lead)
                        plan.append((g[m], a3, hu, hv, box, lead))
                    if not ok:
                        continue
                    cost += L * 1.0 + k0 * 2.0
                    if best is None or cost < best[0]:
                        best = (cost, plan)
    if best is None or best[0] >= 2000.0:
        return _riser_sides(ctx, items, g, sz)
    for ii, a3, hu, hv, box, lead in best[1]:
        _set_attached(ctx, items[ii][0], a3, (hu, hv))
        ctx.occ.add_box(box)
        ctx.occ.add_seg(lead[0], lead[1])
    return True


def _set_attached(ctx, tag, a3, head_uv):
    """Марка с прямой выноской «С присоединённым концом», как у инженера (С.Х.VRF2,
    17.10.2026): марка создаётся заново в точке a3 на оси трубы (конец выноски — там),
    голова — на той же высоте листа. Без промежуточного свободного конца (от него
    оставался излом — выноска «Г»). Возвращает новую марку."""
    doc, view, mm = ctx.doc, ctx.view, ctx.mm
    au, av = ctx.uv(a3)
    head = a3 + ctx.R * ((head_uv[0] - au) * mm) + ctx.U * ((head_uv[1] - av) * mm)
    ref = None
    for r_ in tag.GetTaggedReferences():
        ref = r_
        break
    try:
        nt = IndependentTag.Create(doc, tag.GetTypeId(), view.Id, ref, True, TagOrientation.Horizontal, a3)
        nt.LeaderEndCondition = LeaderEndCondition.Attached
        nt.TagHeadPosition = head
        doc.Delete(tag.Id)
        return nt
    except Exception:
        try:
            tag.LeaderEndCondition = LeaderEndCondition.Attached
            tag.TagHeadPosition = head
        except Exception:
            pass
        return tag


def _riser_sides(ctx, items, g, sz):
    """Запасной вариант для стояка: марки по обе стороны на одной высоте."""
    i, j = g
    ai, aj = items[i][2], items[j][2]
    best = None
    for k in range(min(len(ai), len(aj))):
        ui, vi = ctx.uv(ai[k])
        uj, vj = ctx.uv(aj[k])
        if ui <= uj:
            L_ = (0, i, ai[k], ui, vi)
            R_ = (1, j, aj[k], uj, vj)
        else:
            L_ = (1, j, aj[k], uj, vj)
            R_ = (0, i, ai[k], ui, vi)
        for L in (5.0, 8.0, 12.0, 16.0, 22.0, 30.0):
            plan, cost, ok = [], 0.0, True
            for side, (gi, ii, a3, u, v) in ((-1, L_), (1, R_)):
                r0, q0, r1, q1 = sz[gi]
                hu = (u - L - r1) if side < 0 else (u + L - r0)
                hv = v - (q0 + q1) / 2.0
                box = (hu + r0, hv + q0, hu + r1, hv + q1)
                c = ctx.occ.box_cost(box)
                if c >= HARD:
                    ok = False
                    break
                lead = [(u, v), (u + side * L, v)]
                cost += c + ctx.occ.lead_cost(lead)
                plan.append((ii, a3, hu, hv, box, lead))
            if not ok:
                continue
            cost += L * 1.0 + k * 2.0
            if best is None or cost < best[0]:
                best = (cost, plan)
    if best is None or best[0] >= 2000.0:
        return False
    for ii, a3, hu, hv, box, lead in best[1]:
        _set_attached(ctx, items[ii][0], a3, (hu, hv))
        ctx.occ.add_box(box)
        ctx.occ.add_seg(lead[0], lead[1])
    return True


def _column(ctx, items, g, sz, A, ak=0, dry=False):
    """Колонка с угловыми выносками (как «Колонка» из «По красоте»): марки друг под
    другом, выноска от точки вертикально до строки и горизонтально к марке.
    Порядок строк — без пересечений выносок; если оба порядка чистые — жидкость
    сверху, газ под ней (стандарт, 2.5). Сторона и высота — по свободному месту,
    длины — от базовых по типу схемы (стандарт, 2.7)."""
    import itertools
    h = max(r[3] - r[1] for r in sz)
    step = h + 1.0
    us = [A[i][0] for i in g]
    vs = [A[i][1] for i in g]
    best = None
    if ctx.angled:
        gaps = _lens(ctx.tH, (0.0, -4.0, 4.0, 9.0, 15.0, 24.0))
        lifts = _lens(ctx.tV, (0.0, -3.0, 4.0, 9.0, 15.0, 24.0, -6.5))   # 3,5 мм — db у стояка ARNU24 (17.10)
    else:
        gaps, lifts = (4.0, 8.0, 14.0, 22.0), (6.0, 12.0, 20.0, 30.0)
    lines = [ctx.line.get(_iv(items[i][1].Id)) for i in g]
    for ax in (1, -1):
        for gap in gaps:
            edge = (max(us) + gap) if ax > 0 else (min(us) - gap)
            for ay in (1, -1):
                for lift in lifts:
                    top = (max(vs) + lift + (len(g) - 1) * step) if ay > 0 else (min(vs) - lift)
                    base = sorted(range(len(g)), key=lambda k: (-ax * us[k], -ay * vs[k]))
                    if ctx.angled and len(g) <= 4:
                        orders = [list(o) for o in itertools.permutations(range(len(g)))]
                    else:
                        orders = [base]
                    for order in orders:
                        plan, cost, okk = [], 0.0, True
                        for row, k in enumerate(order):
                            rr = (len(g) - 1 - row) if ay > 0 else row
                            rowv = top - rr * step
                            r0, q0, r1, q1 = sz[k]
                            hu = (edge - r0) if ax > 0 else (edge - r1)
                            hv = rowv - (q0 + q1) / 2.0
                            box = (hu + r0, hv + q0, hu + r1, hv + q1)
                            c = ctx.occ.box_cost(box)
                            if c >= HARD:
                                okk = False
                                break
                            lead = [(us[k], vs[k]), (us[k], rowv), (edge, rowv)]
                            cost += c + ctx.occ.lead_cost(lead)
                            plan.append((k, hu, hv, (us[k], rowv), box, lead, rowv))
                        if not okk:
                            continue
                        for x in range(len(plan)):
                            for y in range(x + 1, len(plan)):
                                cost += 1500.0 * _leads_cross(plan[x][5], plan[y][5])   # своя пара крест-накрест — почти запрет (стандарт 2.5)
                        # жидкость сверху, газ под ней — при прочих равных
                        for x in range(len(plan)):
                            for y in range(len(plan)):
                                if lines[plan[x][0]] == 'G' and lines[plan[y][0]] == 'L' and plan[x][6] > plan[y][6]:
                                    cost += 3.0
                        if ctx.angled:
                            cost += abs(gap - ctx.tH) * 0.6 + abs(lift - ctx.tV) * 0.6 + 4.0
                        else:
                            cost += gap * 1.0 + lift * 1.0
                        if best is None or cost < best[0]:
                            best = (cost, plan)
    if best is None or best[0] >= (2000.0 if ctx.angled else 2000.0 * len(g)):   # трубы: выноска через чужую марку — нельзя
        return None if dry else False
    if dry:
        return best[0]
    for k, hu, hv, elb, box, lead, rowv in best[1]:
        i = g[k]
        _set_tag(ctx, items[i][0], items[i][2][min(ak, len(items[i][2]) - 1)], (hu, hv), elb)
        ctx.occ.add_box(box)
        for q in range(len(lead) - 1):
            ctx.occ.add_seg(lead[q], lead[q + 1])
    return True


# ================================================================== шаги
C_PFIT = int(BIC.OST_PipeFitting)
C_PACC = int(BIC.OST_PipeAccessory)
C_PINS = int(BIC.OST_PipeInsulations)
C_PIPE = int(BIC.OST_PipeCurves)
SANDWICH_CATS = (C_FIT, C_ACC, C_PFIT, C_PACC)


def _conns_all(el):
    """Концевые соединители и воздуховодов, и труб."""
    try:
        cm = el.ConnectorManager if isinstance(el, MEPCurve) else el.MEPModel.ConnectorManager
    except Exception:
        cm = None
    if cm is None:
        return []
    return [c for c in cm.Connectors
            if c.ConnectorType == ConnectorType.End
            and c.Domain in (Domain.DomainHvac, Domain.DomainPiping)]


def _next_any(c):
    for r in c.AllRefs:
        o = r.Owner
        if o.Id == c.Owner.Id or o.Category is None:
            continue
        if _cat(o) in (C_INS, C_PINS) or r.ConnectorType != ConnectorType.End:
            continue
        return r
    return None


def _sandwiched(doc, inset, allowed=None):
    """Фитинги и арматура, зажатые между смещаемыми элементами (в т.ч. скрытые
    на виде): без них разрыв появился бы с обеих сторон участка.
    allowed(id) — можно ли брать элемент (например, только из того же набора)."""
    added = []
    changed = True
    while changed:
        changed = False
        for i in list(inset):
            el = doc.GetElement(ElementId(i))
            if el is None:
                continue
            for c in _conns_all(el):
                r = _next_any(c)
                if r is None or _iv(r.Owner.Id) in inset:
                    continue
                o = r.Owner
                if _cat(o) not in SANDWICH_CATS:
                    continue
                if allowed is not None and not allowed(_iv(o.Id)):
                    continue
                nbs = [_next_any(x) for x in _conns_all(o)]
                nbs = [x for x in nbs if x is not None]
                if nbs and all(_iv(x.Owner.Id) in inset for x in nbs) \
                        and DisplacementElement.IsAllowedAsDisplacedElement(o):
                    inset.add(_iv(o.Id))
                    added.append(o.Id)
                    changed = True
    return added


CL_CATS = [BIC.OST_PipeCurvesCenterLine, BIC.OST_PipeFittingCenterLine, BIC.OST_DuctCurvesCenterLine,
           BIC.OST_DuctFittingCenterLine, BIC.OST_FlexPipeCurvesCenterLine, BIC.OST_FlexDuctCurvesCenterLine,
           BIC.OST_CenterLines]
CL_IDS = set(int(c) for c in CL_CATS)


def _centerlines(doc, inset, taken, allowed=None):
    """Осевые линии труб/воздуховодов/фитингов — отдельные элементы; без них
    смещённый участок рисуется без оси, а ось остаётся на старом месте."""
    from System.Collections.Generic import List
    f = ElementMulticategoryFilter(List[BuiltInCategory](CL_CATS))
    out = []
    for i in list(inset):
        el = doc.GetElement(ElementId(i))
        if el is None or el.Category is None or _cat(el) in CL_IDS:
            continue
        try:
            deps = el.GetDependentElements(f)
        except Exception:
            continue
        for d in deps:
            k = _iv(d)
            if k in inset:
                continue
            if k in taken and (allowed is None or not allowed(k)):
                continue
            if DisplacementElement.IsAllowedAsDisplacedElement(doc.GetElement(d)):
                out.append(d)
                taken.add(k)
    return out


def _fix_centerlines(doc, view):
    """Осевая линия должна быть в том же наборе смещения, что и её труба/фитинг.
    Ручной разнос в Revit иногда кладёт оси в чужой набор (труба поднята, ось
    опущена), оставляет их на месте, или ось остаётся в наборе, когда трубы в нём
    уже нет (ось «висит» отдельно). Возвращает число исправленных осей."""
    from System.Collections.Generic import List
    des, owner, kids = _de_tree(doc, view)
    if not des:
        return 0
    f = ElementMulticategoryFilter(List[BuiltInCategory](CL_CATS))
    want = {}                                   # id оси -> id набора
    for k, d in des.items():
        for i in d.GetDisplacedElementIds():
            el = doc.GetElement(i)
            if el is None or el.Category is None or _cat(el) in CL_IDS:
                continue
            try:
                deps = el.GetDependentElements(f)
            except Exception:
                continue
            for c in deps:
                if owner.get(_iv(c)) != k:
                    want[_iv(c)] = k
    # обратный случай: ось в наборе, а её труба/фитинг нет (трубу убрали из
    # набора, или разнос делали на другой детализации) — ось убрать из набора
    cl_in = [c for c in owner if c not in want and
             doc.GetElement(ElementId(c)) is not None and _cat(doc.GetElement(ElementId(c))) in CL_IDS]
    if cl_in:
        host_cats = [BIC.OST_PipeCurves, BIC.OST_PipeFitting, BIC.OST_PipeAccessory, BIC.OST_DuctCurves,
                     BIC.OST_DuctFitting, BIC.OST_DuctAccessory, BIC.OST_FlexPipeCurves, BIC.OST_FlexDuctCurves]
        hf = ElementMulticategoryFilter(List[BuiltInCategory](host_cats))
        free_cl = set()
        for el in FilteredElementCollector(doc, view.Id).WherePasses(hf).WhereElementIsNotElementType():
            if _iv(el.Id) in owner:
                continue
            try:
                for c in el.GetDependentElements(f):
                    free_cl.add(_iv(c))
            except Exception:
                pass
        for c in cl_in:
            if c in free_cl:
                want[c] = None
    if not want:
        return 0
    sets = dict((k, set(_iv(i) for i in d.GetDisplacedElementIds())) for k, d in des.items())
    moved = 0
    for c, k in want.items():
        o = owner.get(c)
        if o is not None:
            if len(sets[o]) <= 1:
                continue                        # набор нельзя оставить пустым
            sets[o].discard(c)
        elif k is None or not DisplacementElement.IsAllowedAsDisplacedElement(doc.GetElement(ElementId(c))):
            continue
        if k is not None:
            sets[k].add(c)
        moved += 1
    # сначала убираем из старых наборов, потом добавляем в новые
    for k, d in des.items():
        cur = set(_iv(i) for i in d.GetDisplacedElementIds())
        if sets[k] < cur:
            d.SetDisplacedElementIds(List[ElementId]([ElementId(i) for i in sets[k]]))
    for k, d in des.items():
        cur = set(_iv(i) for i in d.GetDisplacedElementIds())
        if sets[k] != cur:
            d.SetDisplacedElementIds(List[ElementId]([ElementId(i) for i in sets[k]]))
    return moved


def _curve_end_near(doc, el, c, inset):
    """Участок (труба/воздуховод) набора у разрыва и параметр его конца (0 или 1)."""
    cur, cc = el, c
    for _ in range(8):
        if isinstance(cur, MEPCurve) and isinstance(cur.Location, LocationCurve):
            crv = cur.Location.Curve
            p = cc.Origin
            return cur, (0.0 if p.DistanceTo(crv.GetEndPoint(0)) < p.DistanceTo(crv.GetEndPoint(1)) else 1.0)
        nxt = None
        for x in _conns_all(cur):
            if x.Id == cc.Id:
                continue
            r = _next_any(x)
            if r is not None and _iv(r.Owner.Id) in inset:
                nxt = r
                break
        if nxt is None:
            return None, 0.0
        cur, cc = nxt.Owner, nxt
    return None, 0.0


PATH_KEEP_MM = 0.15     # своя линия набора ближе этого (мм на листе) к точке разрыва — линия уже есть.
                        # Было 6 мм: у пары труб (жидкость/газ) вторая линия считалась «уже есть» и не ставилась.


def _de_paths(de):
    try:
        return list(de.GetDependentElements(ElementClassFilter(DisplacementPath)))
    except Exception:
        return []


def _path_ends_uv(ctx, pids):
    """Концы линий траектории на листе (мм) — с учётом ручных правок инженера."""
    out = []
    opt = Options()
    opt.View = ctx.view
    for pid in pids:
        try:
            for o in ctx.doc.GetElement(pid).get_Geometry(opt):
                if isinstance(o, Curve) and o.IsBound:
                    out.append(ctx.uv(o.GetEndPoint(0)))
                    out.append(ctx.uv(o.GetEndPoint(1)))
        except Exception:
            pass
    return out


def _delete_paths_of(doc, des_list):
    from System.Collections.Generic import List
    ids = set()
    for de in des_list:
        for pid in _de_paths(de):
            ids.add(_iv(pid))
    if ids:
        doc.Delete(List[ElementId]([ElementId(i) for i in ids]))
    return len(ids)


def _subtree(des, kids, roots):
    out, stack = set(), list(roots)
    while stack:
        k = stack.pop()
        if k in out or k not in des:
            continue
        out.add(k)
        stack.extend(kids.get(k, []))
    return out


def _visible(ctx, el):
    """Элемент виден на виде: не скрыт категорией, «Скрыть на виде» и фильтром
    видимости. Разрыв со скрытым элементом (воздуховоды на схеме труб) — без линии."""
    cache = getattr(ctx, '_vis_cache', None)
    if cache is None:
        cache = ctx._vis_cache = {}
        view, doc = ctx.view, ctx.doc
        ctx._vis_ids = set(_iv(i) for i in FilteredElementCollector(doc, view.Id)
                           .WhereElementIsNotElementType().ToElementIds())
        flts = []
        try:
            for fid in view.GetFilters():
                if not view.GetFilterVisibility(fid):
                    fe = doc.GetElement(fid)
                    try:
                        flts.append(fe.GetElementFilter())
                    except Exception:
                        pass
        except Exception:
            pass
        ctx._vis_filters = flts
    i = _iv(el.Id)
    if i in cache:
        return cache[i]
    ok = i in ctx._vis_ids
    if ok:
        for f in ctx._vis_filters:
            try:
                if f is not None and f.PassesFilter(ctx.doc, el.Id):
                    ok = False
                    break
            except Exception:
                pass
    cache[i] = ok
    return ok


def _corner_path(ctx, de, own):
    """Набор без видимых разрывов (например, установки, подключённые только к
    скрытым на схеме воздуховодам) — по одной линии траектории от нижнего угла
    каждого оборудования (нет оборудования — самого крупного элемента), ближнего
    к зрителю: видно, откуда его сдвинули."""
    doc, view = ctx.doc, ctx.view
    cand = []
    for i in own:
        el = doc.GetElement(ElementId(i))
        if el is None or el.Category is None or _cat(el) in CL_IDS:
            continue
        bb = el.get_BoundingBox(None)
        if bb is None:
            continue
        d = bb.Max - bb.Min
        cand.append((_cat(el) == C_EQ, d.X * d.Y * d.Z, el, bb))
    if not cand:
        return 0
    eqs = [c for c in cand if c[0]]
    targets = eqs if eqs else [max(cand, key=lambda c: c[1])]
    vd = view.ViewDirection
    absd = de.GetAbsoluteDisplacement()
    base = absd - de.GetRelativeDisplacement()
    n = 0
    for _, _, el, bb in targets:
        corners = [XYZ(x, y, bb.Min.Z) for x in (bb.Min.X, bb.Max.X) for y in (bb.Min.Y, bb.Max.Y)]
        c = max(corners, key=lambda q: q.DotProduct(vd))
        ref, prm, p = _edge_near(doc, view, el, c + absd)
        if ref is None:
            continue
        try:
            if _make_path(doc, view, de, ref, prm, p - absd + base):
                n += 1
        except Exception:
            pass
    return n


def _short_shown_system(ctx, e):
    try:
        if not isinstance(e.Location, LocationCurve) or e.Location.Curve.Length * FT_MM > 500.0:
            return False
    except Exception:
        return False
    shown = getattr(ctx, '_shown_sys', None)
    if shown is None:
        shown = set()
        for bic in (BIC.OST_PipeCurves, BIC.OST_DuctCurves):
            for x in FilteredElementCollector(ctx.doc, ctx.view.Id).OfCategory(bic).WhereElementIsNotElementType():
                shown.add(_sys(x))
        shown.discard(u'')
        ctx._shown_sys = shown
    return _sys(e) in shown


def _through_hidden(ctx, hid, frm, inside, depth=6):
    """От скрытого фитинга/арматуры hid (сосед элемента frm) — по соединителям
    дальше, через скрытые фитинги и короткие скрытые вставки труб показанной на
    виде системы (до depth шагов),
    до первого ВИДИМОГО элемента вне набора. Возвращает точку стыка с ним
    (несмещённую) или None."""
    seen = set([_iv(frm.Id)])
    cur = [hid]
    for _ in range(depth):
        nxt = []
        for e in cur:
            if _cat(e) not in (C_PFIT, C_PACC, C_FIT, C_ACC):
                # труба/воздуховод: только короткая вставка (< 500 мм) той же системы,
                # что показана на виде (фреон у установки); чужие системы — нет
                if not _short_shown_system(ctx, e):
                    continue
            seen.add(_iv(e.Id))
            for c in _conns_all(e):
                r = _next_any(c)
                if r is None or _iv(r.Owner.Id) in seen:
                    continue
                o = r.Owner
                if _iv(o.Id) in inside:
                    continue
                if _visible(ctx, o):
                    return c.Origin
                nxt.append(o)
        cur = nxt
        if not cur:
            break
    return None


def _build_paths(ctx, de, own, inside=None, keep=True):
    """Одна линия траектории на разрыв: по оси участка, от его конца.
    own — элементы этого набора; inside — они же + элементы вложенных наборов
    (стык с вложенным набором — не разрыв этого набора: линию даёт вложенный)."""
    doc, view = ctx.doc, ctx.view
    inside = inside if inside is not None else own
    base = de.GetAbsoluteDisplacement() - de.GetRelativeDisplacement()
    done, pts = set(), []
    used_edges = {}                 # id элемента -> концы рёбер, уже взятые под линии
    tol = 0.15 * ctx.mm             # одна линия на соединитель: совпадением считается только одна и та же точка (0,15 мм на листе)
    n = 0
    # уже стоящие линии этого набора (в т.ч. поправленные вручную) не трогаем
    have = _path_ends_uv(ctx, _de_paths(de)) if keep else []
    for i in list(own):
        el = doc.GetElement(ElementId(i))
        if el is None:
            continue
        for c in _conns_all(el):
            r = _next_any(c)
            if r is None or _iv(r.Owner.Id) in inside:
                continue
            via = None
            if not _visible(ctx, r.Owner):
                # скрытый на виде переход/отвод между установкой и трубой: разрыв —
                # там, где за ним начинается видимый элемент; иначе (скрытый
                # воздуховод, канализация) разрыва не видно — линии нет
                via = _through_hidden(ctx, r.Owner, el, inside)
                if via is None:
                    continue
            crv_el, prm = (None, 0.0) if via is not None else _curve_end_near(doc, el, c, own)
            if crv_el is not None:
                key = (_iv(crv_el.Id), prm)
                if key in done:
                    continue
                done.add(key)
                p = crv_el.Location.Curve.GetEndPoint(int(prm))
                ref = Reference.ParseFromStableRepresentation(doc, crv_el.UniqueId + u":0:LINEAR")
            else:
                # в наборе нет трубы до разрыва (оборудование, фитинг) — линия от
                # ребра самого элемента, ближайшего к соединителю
                # геометрия с View приходит уже смещённой — ищем у смещённого соединителя
                # у каждого соединителя — своя линия: занятые концы рёбер пропускаем
                # (раньше два соединителя рядом брали один и тот же угол — линия была одна)
                ref, prm, p = _edge_near(doc, view, el, (via if via is not None else c.Origin) + de.GetAbsoluteDisplacement(),
                                         used_edges.get(_iv(el.Id)))
                if ref is None:
                    continue
                used_edges.setdefault(_iv(el.Id), set()).add((round(p.X * FT_MM), round(p.Y * FT_MM), round(p.Z * FT_MM)))
                p = p - de.GetAbsoluteDisplacement()        # несмещённая точка
                key = (_iv(el.Id), round(p.X, 3), round(p.Y, 3), round(p.Z, 3))
                if key in done:
                    continue
                done.add(key)
            uv = (p.DotProduct(ctx.R), p.DotProduct(ctx.U))
            if any(abs(uv[0] - q[0]) < tol and abs(uv[1] - q[1]) < tol for q in pts):
                continue
            if have:
                u0, v0 = ctx.uv(p + base)
                if any(math.hypot(u0 - a, v0 - b) < PATH_KEEP_MM for a, b in have):
                    continue
            try:
                if _make_path(doc, view, de, ref, prm, p + base):
                    pts.append(uv)
                    n += 1
            except Exception:
                pass
    return n


def _edge_near(doc, view, el, p, skip=None):
    """Ребро геометрии элемента с концом, ближайшим к точке p:
    (ссылка, параметр конца 0/1, точка конца) или (None, 0, None).
    skip — концы (округлённые до 1 мм), уже занятые линиями других соединителей."""
    skip = skip or set()

    def busy(q):
        return (round(q.X * FT_MM), round(q.Y * FT_MM), round(q.Z * FT_MM)) in skip
    opt = Options()
    opt.ComputeReferences = True
    opt.View = view
    best = [None, 0.0, None, 1e9]

    def scan(geo):
        for g in geo:
            if isinstance(g, GeometryInstance):
                scan(g.GetInstanceGeometry())
            elif isinstance(g, Solid):
                for e in g.Edges:
                    try:
                        if e.Reference is None:
                            continue
                        crv = e.AsCurve()
                        if not crv.IsBound:
                            continue
                        for k in (0, 1):
                            q = crv.GetEndPoint(k)
                            d = q.DistanceTo(p)
                            if d < best[3] and not busy(q):
                                best[:] = [e.Reference, float(k), q, d]
                    except Exception:
                        continue          # окружности и пр.: одно ребро не должно срывать поиск
            elif isinstance(g, Curve) and g.Reference is not None and g.IsBound:
                for k in (0, 1):
                    q = g.GetEndPoint(k)
                    d = q.DistanceTo(p)
                    if d < best[3] and not busy(q):
                        best[:] = [g.Reference, float(k), q, d]
    try:
        scan(el.get_Geometry(opt))
    except Exception:
        return None, 0.0, None
    return best[0], best[1], best[2]


def _de_tree(doc, view):
    """Наборы вида: {id: набор}, {id элемента: id набора}, {id набора: [дети]}."""
    des = dict((_iv(d.Id), d) for d in FilteredElementCollector(doc, view.Id).OfClass(DisplacementElement))
    owner, kids = {}, {}
    for k, d in des.items():
        for i in d.GetDisplacedElementIds():
            owner[_iv(i)] = k
        par = _iv(d.ParentId)
        if par in des:
            kids.setdefault(par, []).append(k)
    return des, owner, kids


def _inside(des, kids, k):
    """Элементы набора k и всех вложенных в него."""
    out = set()
    stack = [k]
    while stack:
        x = stack.pop()
        out |= set(_iv(i) for i in des[x].GetDisplacedElementIds())
        stack.extend(kids.get(x, []))
    return out


def _path_hits(doc, view, pid, p):
    """Линия траектории начинается в точке p (в плане вида, без учёта смещения)?"""
    try:
        opt = Options()
        opt.View = view
        g = doc.GetElement(pid).get_Geometry(opt)
        R, U = view.RightDirection, view.UpDirection
        for o in g:
            if isinstance(o, Line):
                for q in (o.GetEndPoint(0), o.GetEndPoint(1)):
                    v = q - p
                    # вдоль линии траектории (смещение) точка может уйти — сверяем поперёк неё
                    d = o.Direction
                    w = v - d.Multiply(v.DotProduct(d))
                    if w.GetLength() < 2.0 / FT_MM:
                        return True
        return False
    except Exception:
        return True


def _make_path(doc, view, de, ref, prm, p):
    """Линия траектории по ссылке ref (ось участка или ребро) от точки p.
    Параметр 0/1 у ссылки не всегда совпадает с ожидаемым концом — проверяем и
    при промахе ставим от другого конца."""
    pid = DisplacementPath.Create(doc, de, ref, prm)
    doc.Regenerate()
    if _path_hits(doc, view, pid, p):
        return True
    doc.Delete(pid)
    pid = DisplacementPath.Create(doc, de, ref, 1.0 - prm)
    doc.Regenerate()
    return True


def step_explode(ctx, elems, offset_mm):
    """Разнос выделенного на offset_mm по высоте + одна линия траектории на разрыв.
    Уже смещённые элементы уходят во вложенный набор (многоуровневая взрыв-схема):
    они изымаются из своего набора и смещаются ещё на offset_mm относительно него."""
    doc, view = ctx.doc, ctx.view
    from System.Collections.Generic import List
    des, owner, kids = _de_tree(doc, view)
    groups = {}
    for e in elems:
        k = owner.get(_iv(e.Id))            # None — ещё не смещён
        groups.setdefault(k, set()).add(_iv(e.Id))
    D = XYZ(0, 0, offset_mm / FT_MM)
    t = Transaction(doc, u"Разнос + линии траектории")
    t.Start()
    try:
        # линии траектории мешают перекладке элементов между наборами — убираем
        # ТОЛЬКО у затронутых наборов (и их вложенных); остальные (в т.ч.
        # поправленные вручную) не трогаем
        touched = _subtree(des, kids, [k for k in groups if k is not None])
        _delete_paths_of(doc, [des[k] for k in touched])
        taken = set(owner.keys())
        new_des = []
        for k, inset in groups.items():
            same = (lambda i, k=k: owner.get(i) == k)
            added = _sandwiched(doc, inset, same)
            cls = _centerlines(doc, inset, taken, same)
            cl_ids = set(_iv(c) for c in cls)
            try:
                extra = DisplacementElement.GetAdditionalElementsToDisplace(doc, view, List[ElementId]([ElementId(i) for i in inset]))
                for x in extra:
                    xi = _iv(x)
                    if xi not in inset and xi not in cl_ids and same(xi):
                        cls.append(x)
                        cl_ids.add(xi)
            except Exception:
                pass
            ids = [ElementId(i) for i in inset] + cls
            idset = set(_iv(i) for i in ids)
            if k is None:
                de = DisplacementElement.Create(doc, List[ElementId](ids), D, view, None)
                ctx.add(u'Смещено элементов', len(ids))
            else:
                par = des[k]
                rest = [i for i in par.GetDisplacedElementIds() if _iv(i) not in idset]
                if not rest:
                    # выделен весь набор — просто сдвигаем его дальше
                    par.SetRelativeDisplacement(par.GetRelativeDisplacement() + D)
                    ctx.add(u'Сдвинуто дальше целых наборов', 1)
                    continue
                # Revit сам изымает элементы из родительского набора, если создать
                # вложенный набор с parent = их набор (вручную изымать нельзя:
                # после изъятия Create с parent отказывает)
                de = DisplacementElement.Create(doc, List[ElementId](ids), D, view, par)
                ctx.add(u'Смещено элементов (следующий уровень)', len(ids))
            if added:
                ctx.add(u'  из них фитингов между выделенными', len(added))
            if cls:
                ctx.add(u'  из них осевых линий', len(cls))
            new_des.append(de)
        t.Commit()
    except Exception:
        t.RollBack()
        raise
    # линии траектории — только новым и затронутым наборам
    _paths_for(ctx, set(_iv(d.Id) for d in new_des) | touched)


def _paths_for(ctx, keys):
    doc, view = ctx.doc, ctx.view
    des, owner, kids = _de_tree(doc, view)
    keys = _subtree(des, kids, keys)
    t = Transaction(doc, u"Линии траектории")
    t.Start()
    try:
        n = 0
        for k in keys:
            de = des[k]
            own = set(_iv(i) for i in de.GetDisplacedElementIds())
            m = _build_paths(ctx, de, own, _inside(des, kids, k))
            if m == 0 and not _de_paths(de):
                m = _corner_path(ctx, de, own)
            n += m
        ctx.add(u'Линий траектории добавлено', n)
        t.Commit()
    except Exception:
        t.RollBack()
        raise


def step_addto(ctx, uidoc, elems):
    """Перенести выделенное (из любых наборов или несмещённое) в набор, элемент
    которого укажет инженер. В Revit «Добавить» в наборе смещения не берёт
    элементы чужого набора — здесь они сначала изымаются из своего."""
    doc, view = ctx.doc, ctx.view
    from System.Collections.Generic import List
    from Autodesk.Revit.UI.Selection import ObjectType, ISelectionFilter
    from Autodesk.Revit.Exceptions import OperationCanceledException
    des, owner, kids = _de_tree(doc, view)

    class _InSet(ISelectionFilter):
        def AllowElement(self, e):
            # щелчок по смещённому элементу в 3D часто попадает в сам «Набор смещения»
            return isinstance(e, DisplacementElement) or _iv(e.Id) in owner

        def AllowReference(self, r, p):
            return False

    try:
        ref = uidoc.Selection.PickObject(ObjectType.Element, _InSet(),
                                         u"Щёлкните любой элемент набора, В КОТОРЫЙ перенести выделенное (Esc — отмена)")
    except OperationCanceledException:
        ctx.add(u'Отменено', 0)
        return
    tk = _iv(ref.ElementId) if _iv(ref.ElementId) in des else owner.get(_iv(ref.ElementId))
    if tk is None:
        ctx.add(u'Указанный элемент не в наборе смещения — переносить некуда', 0)
        return
    move = set(_iv(e.Id) for e in elems) - set(_iv(i) for i in des[tk].GetDisplacedElementIds())
    if not move:
        ctx.add(u'Всё выделенное уже в этом наборе', 0)
        return
    # фитинги между переносимыми и их оси — тоже переносим
    _sandwiched(doc, move, lambda i: owner.get(i) != tk)
    f = ElementMulticategoryFilter(List[BuiltInCategory](CL_CATS))
    for i in list(move):
        el = doc.GetElement(ElementId(i))
        try:
            for c in el.GetDependentElements(f):
                if owner.get(_iv(c)) != tk:
                    move.add(_iv(c))
        except Exception:
            pass
    t = Transaction(doc, u"Перенести в набор разноса")
    t.Start()
    try:
        srcs = set(owner.get(i) for i in move if owner.get(i) is not None)
        touched = _subtree(des, kids, srcs | set([tk]))
        _delete_paths_of(doc, [des[k] for k in touched])
        skipped = 0
        took = set()
        by_src = {}
        for i in move:
            by_src.setdefault(owner.get(i), set()).add(i)
        for k, ids in by_src.items():
            if k is None:
                ok = [i for i in ids if DisplacementElement.IsAllowedAsDisplacedElement(doc.GetElement(ElementId(i)))]
                took |= set(ok)
                skipped += len(ids) - len(ok)
                continue
            src = des[k]
            rest = [x for x in src.GetDisplacedElementIds() if _iv(x) not in ids]
            if rest:
                src.SetDisplacedElementIds(List[ElementId](rest))
            elif not kids.get(k):
                doc.Delete(src.Id)              # набор опустел и без вложенных — удаляем
            else:
                skipped += len(ids)             # пустой набор с вложенными оставить нельзя
                continue
            took |= ids
        tgt = des[tk]
        allids = list(tgt.GetDisplacedElementIds()) + [ElementId(i) for i in took]
        tgt.SetDisplacedElementIds(List[ElementId](allids))
        ctx.add(u'Перенесено элементов', len(took))
        if skipped:
            ctx.add(u'Не перенесено (набор нельзя оставить пустым)', skipped)
        t.Commit()
    except Exception:
        t.RollBack()
        raise
    des2 = _de_tree(doc, view)[0]
    _paths_for(ctx, set(k for k in touched if k in des2))


def step_paths(ctx, quiet=False, reset=False):
    """Линии траектории разносов вида. По умолчанию — только ДОПОЛНИТЬ: где у
    набора на разрыве уже есть линия (в т.ч. поправленная вручную), её не трогаем.
    reset=True — удалить все и поставить заново по правилу."""
    doc, view = ctx.doc, ctx.view
    from System.Collections.Generic import List
    des, owner, kids = _de_tree(doc, view)
    if not des:
        ctx.add(u'На виде нет разносов', 0)
        return
    t = Transaction(doc, u"Линии траектории")
    t.Start()
    try:
        old = list(FilteredElementCollector(doc, view.Id).OfClass(DisplacementPath).ToElementIds()) if reset else []
        if old:
            doc.Delete(List[ElementId](old))
        if not quiet and reset:
            ctx.add(u'Удалено старых линий', len(old))
        taken = set(owner.keys())
        nf = ncl = 0
        for k, de in des.items():
            own = set(_iv(i) for i in de.GetDisplacedElementIds())
            before = set(own)
            _sandwiched(doc, own, lambda i: i not in taken)
            new = [ElementId(i) for i in own - before]
            taken |= set(_iv(x) for x in new)
            cls = _centerlines(doc, own, taken)
            if new or cls:
                de.SetDisplacedElementIds(List[ElementId](list(de.GetDisplacedElementIds()) + new + cls))
                nf += len(new)
                ncl += len(cls)
        try:
            ncl += _fix_centerlines(doc, view)
        except Exception:
            pass
        if nf:
            ctx.add(u'Добавлено фитингов в разносы', nf)
        if ncl:
            ctx.add(u'Осевых линий добавлено/переложено в разносы', ncl)
        des, owner, kids = _de_tree(doc, view)
        n = 0
        for k, de in des.items():
            own = set(_iv(i) for i in de.GetDisplacedElementIds())
            n += _build_paths(ctx, de, own, _inside(des, kids, k), keep=not reset)
        ctx.add(u'Линий траектории добавлено' if not reset else u'Линий траектории', n)
        t.Commit()
    except Exception:
        t.RollBack()
        raise


def _runs(ctx, ducts):
    did = set(_iv(d.Id) for d in ducts)
    parent = dict((x, x) for x in did)

    def find(x):
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    def walk_same(el, c):
        cc = c
        for _ in range(10):
            r = _next(cc)
            if r is None:
                return None
            o = r.Owner
            if _iv(o.Id) in did:
                return o
            if _cat(o) not in (C_FIT, C_ACC):
                return None
            f = _fam(o)
            if _cat(o) == C_FIT and any(w in f for w in (u'Тройник', u'Крестовина', u'Переходник', u'Врезка', u'Утка')):
                return None
            oth = [x for x in _conns(o) if not x.IsConnectedTo(r) and x.Id != r.Id]
            if len(oth) != 1:
                return None
            cc = oth[0]
        return None

    for d in ducts:
        for c in _conns(d):
            o = walk_same(d, c)
            if o is None:
                continue
            if _size(o) == _size(d) and _sys(o) == _sys(d) and \
                    ctx.dset.get(_iv(o.Id), 0) == ctx.dset.get(_iv(d.Id), 0):
                a, b = find(_iv(d.Id)), find(_iv(o.Id))
                if a != b:
                    parent[a] = b
    runs = {}
    for d in ducts:
        runs.setdefault(find(_iv(d.Id)), []).append(d)
    return list(runs.values())


def _len(d):
    return d.Location.Curve.Length * FT_MM


def _pieces(ctx):
    """Куски систем: элементы одной системы, связанные соединителями, в одном наборе
    смещения (разрыв взрыв-схемы делит систему на куски). Считается по всему виду."""
    els = [e for e in ctx.all_els if _cat(e) in (C_DUCT, C_FIT, C_ACC, C_FLEX)]
    ids = set(_iv(e.Id) for e in els)
    parent = dict((x, x) for x in ids)

    def find(x):
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x
    for e in els:
        for c in _conns(e):
            r = _next(c)
            if r is None:
                continue
            o = r.Owner
            j = _iv(o.Id)
            if j not in ids:
                continue
            if ctx.dset.get(j, 0) != ctx.dset.get(_iv(e.Id), 0):
                continue
            if _sys(o) != _sys(e):
                continue
            a, b = find(_iv(e.Id)), find(j)
            if a != b:
                parent[a] = b
    return find


def step_sys(ctx):
    """Марка «Имя системы - Размер» - один раз на каждый кусок системы (кусок = часть
    системы между разрывами взрыв-схемы); на остальных участках другого сечения -
    марка «Размер». Участок с любой маркой воздуховода не трогается."""
    sym = _find_tag_type(ctx.doc, *T_SYS)
    sym_sz = _find_tag_type(ctx.doc, *T_SIZE)
    if sym is None or sym_sz is None:
        ctx.add(u'Нет типа марки «Имя системы - Размер» или «Размер»', 0)
        return
    piece_of = _pieces(ctx)
    has_sys = set()
    for e in ctx.all_els:
        if _cat(e) == C_DUCT and u'СИС' in ctx.kinds.get(_iv(e.Id), ()):
            has_sys.add(piece_of(_iv(e.Id)))
    ducts = [e for e in ctx.all_els if _cat(e) == C_DUCT and ctx.in_scope(e)]
    by_piece = {}
    for run in _runs(ctx, ducts):
        if sum(_len(d) for d in run) < MIN_RUN_MM:
            continue
        by_piece.setdefault(piece_of(_iv(run[0].Id)), []).append(run)
    jobs_sys, jobs_sz = [], []
    for pc, runs in by_piece.items():
        runs.sort(key=lambda r: sum(_len(d) for d in r), reverse=True)
        need_sys = pc not in has_sys
        for run in runs:
            if any(u'ВОЗД' in ctx.kinds.get(_iv(d.Id), ()) for d in run):
                continue
            best = max(run, key=_len)
            anchors = anchors_of(ctx, best)
            if need_sys:
                jobs_sys.append((best, sym, anchors, u'Марки «Имя системы - Размер» (по одной на кусок системы)'))
                need_sys = False
            else:
                jobs_sz.append((best, sym_sz, anchors, u'Марки «Размер»'))
        if need_sys and runs:
            best = max(runs[0], key=_len)
            jobs_sys.append((best, sym, anchors_of(ctx, best),
                             u'Марки «Имя системы - Размер» (по одной на кусок системы)'))
    if ctx.with_sizes:
        place_tags(ctx, jobs_sz, u"Марки размеров")
    else:
        place_tags(ctx, jobs_sys, u"Марки систем")


def _is_main_damper(el):
    f = _fam(el)
    if u'Дроссель' not in f:
        return False
    if u'прямоуг' in f.lower():
        return True
    for c in _conns(el):
        for r in c.AllRefs:
            if r.Owner.Id != el.Id and _cat(r.Owner) == C_INS:
                return True
    return False


def _tee_needs(ctx, el, strict):
    cl = _conns(el)
    T, D, main_T, main_unl = 0, False, 0, 0
    for c in cl:
        r = _next(c)
        if r is None:
            continue
        o = r.Owner
        is_main = any(x.Id != c.Id and x.CoordinateSystem.BasisZ.DotProduct(c.CoordinateSystem.BasisZ) < -0.9
                      for x in cl)
        f = _fam(o)
        if (u'Переходник' in f or u'Утка' in f) and _iv(o.Id) not in ctx.tagged:
            T += 1
            if is_main:
                main_T += 1
        elif is_main and _iv(o.Id) not in ctx.tagged:
            main_unl += 1
        if not is_main and ctx.dset.get(_iv(o.Id), 0) != ctx.dset.get(_iv(el.Id), 0):
            D = True
    if u'штанообразный' in _fam(el):
        return True
    if T >= 2 or D:
        return True
    return strict and main_T >= 1 and main_unl >= 1


# ---------------------------------------------------------------------------
# Марки на схемах ТРУБ (фреон): трубы, разветвители (Y-Branch), EEV-киты
#   * трубы — марка «db_M_Трубы» по одной на «участок одного диаметра»: трубы
#     одной системы и диаметра, соединённые муфтами/отводами (2 соединителя);
#     разветвитель, переход, тройник участок разрывают; участок < 200 мм — без марки;
#   * разветвители (семейство с «Branch»/«Разветвит») и EEV-киты (оборудование с
#     «EEV») — «db_M_Несколько категорий : Имя типа»;
#   * уже подписанное не трогаем; близкие марки (пара жидкость/газ) — колонкой.
# ---------------------------------------------------------------------------
MIN_PIPE_TAG_MM = 0.0   # 17.10.2026: длина — не повод оставить участок без марки (стандарт, 2.9)
# базовые длины угловой выноски марок труб, мм листа (вертикаль, полка) — стандарт, 2.7
# V — вертикаль выноски, H — ВИДИМАЯ полка от крайней вертикали до края марки, мм листа.
# Правки db на С.Х.VRF2 (17.10): полка ~7,5 мм и у труб, и у разветвителей (было 12,6 — с полуширины марки).
PIPE_LEAD = {u'vrf': (10.0, 7.5), u'kkb': (14.0, 10.0)}
PAIR_RUN_GAP_MM = 450.0    # пара жидкость/газ: трубы рядом параллельно не дальше
LEAD_SPREAD_MM = 3.5       # расстояние между вертикалями выносок пары на листе (замечание инженера 17.10)


def _pipe_tag_types(doc):
    pipe_t, multi_t = None, None
    for s in FilteredElementCollector(doc).OfClass(FamilySymbol):
        try:
            cid = _iv(s.Category.Id) if s.Category is not None else 0
            fn = s.FamilyName or u''
            tn = s.get_Parameter(BuiltInParameter.ALL_MODEL_TYPE_NAME).AsString() or u''
        except Exception:
            continue
        if not fn.startswith(u'db_'):
            continue
        if cid == int(BIC.OST_PipeTags) and fn.endswith(u'_Трубы'):
            if pipe_t is None or tn == fn:
                pipe_t = s
        if cid == int(BIC.OST_MultiCategoryTags) and u'Несколько категорий' in fn and tn == u'Имя типа':
            multi_t = s
    return pipe_t, multi_t


def _pipe_size_runs(pipes):
    ids = dict((_iv(p.Id), p) for p in pipes)
    par = dict((k, k) for k in ids)

    def find(k):
        while par[k] != k:
            par[k] = par[par[k]]
            k = par[k]
        return k

    def same(a, b):
        return abs(a.Diameter - b.Diameter) < 1e-6

    def union(a, b):
        ra, rb = find(_iv(a.Id)), find(_iv(b.Id))
        if ra != rb:
            par[ra] = rb
    for p in pipes:
        for c in _conns_all(p):
            r = _next_any(c)
            if r is None:
                continue
            o = r.Owner
            io = _iv(o.Id)
            if io in ids:
                if same(p, ids[io]):
                    union(p, ids[io])
                continue
            if _cat(o) not in (C_PFIT, C_PACC):
                continue
            cs = _conns_all(o)
            if len(cs) != 2:
                continue
            for c2 in cs:
                r2 = _next_any(c2)
                if r2 is None:
                    continue
                q = ids.get(_iv(r2.Owner.Id))
                if q is not None and q.Id != p.Id and same(p, q):
                    union(p, q)
    runs = {}
    for k, p in ids.items():
        runs.setdefault(find(k), []).append(p)
    return list(runs.values())


# рефнеты: разветвители (Y-Branch), объединители наружных блоков (Outdoor Coupler), гребёнки (Header)
REFNET_WORDS = (u'branch', u'разветвит', u'coupler', u'header', u'refnet', u'рефнет', u'гребён', u'гребен')


def _scheme_kind(ctx, els):
    for e in els:
        if _cat(e) == C_PACC and u'ARBLN' in (_type_name(e) or u''):
            return u'vrf'
        if u'VRF' in _sys(e).upper():
            return u'vrf'
    return u'kkb'


def _type_name(el):
    try:
        t = el.Document.GetElement(el.GetTypeId())
        return Element.Name.GetValue(t) if t is not None else u''
    except Exception:
        return u''


def _crv_dir(c):
    p0, p1 = c.GetEndPoint(0), c.GetEndPoint(1)
    d = p1 - p0
    L = d.GetLength()
    return (p0, d / L, L) if L > 1e-6 else (p0, None, 0.0)


def _pair_size_runs(ctx, runs):
    """Пары участков жидкость/газ: разные системы или диаметры, тот же набор разноса,
    трубы параллельно рядом (до PAIR_RUN_GAP_MM) на большей части длины.
    Возвращает [(i, j, (труба_i, труба_j, середина перекрытия))]."""
    gap = PAIR_RUN_GAP_MM / FT_MM
    info = []
    for run in runs:
        segs = []
        for p in run:
            p0, d, L = _crv_dir(p.Location.Curve)
            if d is not None:
                segs.append((p, p0, d, L))
        info.append((segs, sum(x[3] for x in segs), ctx.dset.get(_iv(run[0].Id), 0),
                     _sys(run[0]), run[0].Diameter))
    cand = []
    for i in range(len(runs)):
        si, Li, di, yi, Di = info[i]
        for j in range(i + 1, len(runs)):
            sj, Lj, dj, yj, Dj = info[j]
            # набор разноса сравниваем по каждой паре труб: участок со стояком бывает
            # в разных наборах (горизонталь разнесена, стояк — нет)
            if (yi == yj and abs(Di - Dj) * FT_MM < 0.5) or not si or not sj:
                continue
            tot, best = 0.0, None
            for (p, p0, d1, L1) in si:
                for (q, q0, d2, L2) in sj:
                    if abs(d1.DotProduct(d2)) < 0.99 or \
                            ctx.dset.get(_iv(p.Id), 0) != ctx.dset.get(_iv(q.Id), 0):
                        continue
                    w = q0 - p0
                    along = w.DotProduct(d1)
                    lat = (w - d1 * along).GetLength()
                    if lat > gap:
                        continue
                    t0 = along
                    t1 = (q0 + d2 * L2 - p0).DotProduct(d1)
                    lo, hi = max(0.0, min(t0, t1)), min(L1, max(t0, t1))
                    ov = hi - lo
                    if ov <= 0.3 * min(L1, L2):
                        continue
                    tot += ov
                    if best is None or ov > best[0]:
                        best = (ov, p, q, p0 + d1 * ((lo + hi) / 2.0), p0, d1, lo, hi)
            if best is None:
                continue
            ratio = tot / max(1e-6, min(Li, Lj))
            # стояк пары часто входит в длинные участки с горизонтальными кусками —
            # хватает и большого общего параллельного куска (С.Х.VRF2, 17.10)
            if ratio > 0.4 or tot * FT_MM >= 1500.0:
                cand.append((ratio, i, j, best[1:]))
    cand.sort(key=lambda x: -x[0])
    used, out = set(), []
    for ratio, i, j, bp in cand:
        if i in used or j in used:
            continue
        used.add(i)
        used.add(j)
        out.append((i, j, bp))
    return out


def _refnet_pairs(ctx, refs):
    """Разветвитель — два семейства «…_Gas» и «…_Liquid» в одном месте: пара строк."""
    def base(e):
        n = _type_name(e)
        for suf in (u'_Gas', u'_Liquid', u'_gas', u'_liquid'):
            if n.endswith(suf):
                return n[:-len(suf)], (u'G' if u'as' in suf else u'L')
        return n, None
    out, used = [], set()
    pts = dict((_iv(e.Id), anchor_of(ctx, e)) for e in refs)
    for a in refs:
        ia = _iv(a.Id)
        if ia in used:
            continue
        ba, la = base(a)
        best = None
        for b in refs:
            ib = _iv(b.Id)
            if ib == ia or ib in used:
                continue
            bb, lb = base(b)
            if bb != ba or la is None or lb is None or la == lb:
                continue
            if ctx.dset.get(ia, 0) != ctx.dset.get(ib, 0):
                continue
            d = pts[ia].DistanceTo(pts[ib])
            if d * FT_MM < 1500.0 and (best is None or d < best[0]):
                best = (d, b, lb)
        if best is not None:
            used.add(ia)
            used.add(_iv(best[1].Id))
            out.append((a, la, best[1], best[2]))
    return out, used


def _refnet_keepout(ctx, els, r=2.5):
    for e in els:
        if _cat(e) not in (C_PACC, C_PFIT):
            continue
        nm = (_type_name(e) or u'') + u' ' + (getattr(getattr(e, 'Symbol', None), 'FamilyName', u'') or u'')
        low = nm.lower()
        if u'ARBLN' not in nm and not any(w in low for w in REFNET_WORDS):
            continue
        try:
            lp = e.Location
            p = lp.Point if isinstance(lp, LocationPoint) else None
            if p is None:
                bb = e.get_BoundingBox(None)
                p = (bb.Min + bb.Max) * 0.5
            u, v = ctx.uv(p + ctx.dp(e))
            ctx.occ.add_box((u - r, v - r, u + r, v + r))
        except Exception:
            pass


def _eq_boxes(ctx):
    """Оборудование — в занятость (марки труб на блоки не ставим)."""
    for e in FilteredElementCollector(ctx.doc, ctx.view.Id).OfCategory(BIC.OST_MechanicalEquipment) \
            .WhereElementIsNotElementType():
        if getattr(e, 'SuperComponent', None) is not None:
            continue
        # рамка по видимой геометрии блока (габарит семейства в изометрии намного больше
        # силуэта — точки марок под блоком попадали «в блок», пара рассыпалась, 17.10)
        box = None
        try:
            gb = _geo_uv_box(ctx, e)
            if gb is not None:
                box = (gb[0] + 0.5, gb[1] + 0.5, gb[2] - 0.5, gb[3] - 0.5)
        except Exception:
            box = None
        if box is None:
            bb = e.get_BoundingBox(None)
            if bb is None:
                continue
            d = ctx.dp(e)
            us, vs = [], []
            for x in (bb.Min.X, bb.Max.X):
                for y in (bb.Min.Y, bb.Max.Y):
                    for z in (bb.Min.Z, bb.Max.Z):
                        u, v = ctx.uv(XYZ(x, y, z) + d)
                        us.append(u)
                        vs.append(v)
            cu, cv = (min(us) + max(us)) / 2.0, (min(vs) + max(vs)) / 2.0
            hu, hv = (max(us) - min(us)) * 0.42, (max(vs) - min(vs)) * 0.42
            box = (cu - hu, cv - hv, cu + hu, cv + hv)
        if not hasattr(ctx, 'eq_box'):
            ctx.eq_box = {}
        ctx.eq_box[_iv(e.Id)] = box
        ctx.occ.add_box(box)


def _path_bands(ctx):
    """Линии траектории разноса (пунктир) — в занятость: выноски вдоль них сливаются."""
    opt = Options()
    opt.View = ctx.view
    for e in FilteredElementCollector(ctx.doc, ctx.view.Id).OfClass(DisplacementPath):
        try:
            geo = e.get_Geometry(opt)
        except Exception:
            geo = None
        if geo is None:
            continue
        for g in geo:
            if isinstance(g, Curve):
                ctx.occ.add_band(ctx.uv(g.GetEndPoint(0)), ctx.uv(g.GetEndPoint(1)), 0.6, line=False)
            elif isinstance(g, PolyLine):
                pts = list(g.GetCoordinates())
                for k in range(len(pts) - 1):
                    ctx.occ.add_band(ctx.uv(pts[k]), ctx.uv(pts[k + 1]), 0.6, line=False)


def step_pipe_tags(ctx):
    """Марки труб, разветвителей и EEV-китов по стандарту оформления схем (17.10.2026):
    * марка на КАЖДОМ участке одного диаметра, короткие тоже (2.9);
    * пара жидкость/газ одного участка — одна колонка из 2 строк (2.4); порядок —
      без пересечений выносок, при прочих равных жидкость сверху (2.5);
    * пара разветвителя «…_Gas/…_Liquid» — своя пара строк (3.2);
    * длины выносок — базовые по типу схемы, тесно — длиннее (2.7)."""
    doc, view = ctx.doc, ctx.view
    pipe_t, multi_t = _pipe_tag_types(doc)
    if pipe_t is None:
        ctx.add(u'Нет марки труб «db_M_Трубы» в проекте', 0)
    if multi_t is None:
        ctx.add(u'Нет марки «db_M_Несколько категорий : Имя типа»', 0)
    picked = ctx.scope_given
    els = _pipe_view_els(ctx)
    pipes = [e for e in els if _cat(e) == C_PIPE and isinstance(e.Location, LocationCurve)]
    kind = _scheme_kind(ctx, els)
    ctx.tV, ctx.tH = PIPE_LEAD[kind]
    # «уже подписано» — только марками, не марками-отметками (отметки ставятся раньше)
    tagged = set(i for i, ks in ctx.kinds.items() if any(k != u'ОТМ' for k in ks))
    ctx.group_of = {}
    ctx.occ.band_w = 25.0   # марка на трубе — почти запрет (замечание 17.10)
    # трубы и оборудование — в занятость
    for p in pipes:
        c = p.Location.Curve
        d = ctx.dp(p)
        r = max(0.6, p.Diameter * FT_MM / view.Scale / 2.0 + 0.3)
        ctx.occ.add_band(ctx.uv(c.GetEndPoint(0) + d), ctx.uv(c.GetEndPoint(1) + d), r)
    _eq_boxes(ctx)
    _path_bands(ctx)
    jobs = []
    if pipe_t is not None:
        runs = []
        for run in _pipe_size_runs(pipes):
            if picked is not None and not any(_iv(p.Id) in picked for p in run):
                continue
            if any(_iv(p.Id) in tagged for p in run):
                continue
            if sum(p.Location.Curve.Length for p in run) * FT_MM < MIN_PIPE_TAG_MM:
                continue
            runs.append(run)
        chosen = {}
        for i, j, (pa, pb, mid, p0, d1, lo, hi) in _pair_size_runs(ctx, runs):
            key = u'pair%d' % i
            cb = pb.Location.Curve
            du = d1.DotProduct(ctx.R) / ctx.mm      # мм листа на фут вдоль трубы
            dv = d1.DotProduct(ctx.U) / ctx.mm
            # стояк — только если обе трубы под марками вертикальны на листе (db: наклонную
            # пару 4174296/4174309 рядом со стояком переделал в обычную колонку)
            if abs(du) < 0.3 * abs(dv) and _sheet_vertical(ctx, pa) and _sheet_vertical(ctx, pb):
                # стояк: точки обеих труб на одной высоте листа
                q0 = cb.GetEndPoint(0)
                d2 = (cb.GetEndPoint(1) - q0).Normalize()
                d2u = d2.DotProduct(ctx.U)
                an_a, an_b = [], []
                for t in (0.5, 0.35, 0.65, 0.25, 0.75, 0.15, 0.85):
                    pa_pt = p0 + d1 * (lo + (hi - lo) * t)
                    if abs(d2u) < 1e-9:
                        continue
                    sq = (pa_pt - q0).DotProduct(ctx.U) / d2u
                    if sq < 0 or sq > cb.Length:
                        continue
                    pb_pt = q0 + d2 * sq
                    if ctx.visible_pt(pa_pt) and ctx.visible_pt(pb_pt):
                        an_a.append(pa_pt + ctx.dp(pa))
                        an_b.append(pb_pt + ctx.dp(pb))
                if not an_a:
                    continue
                chosen[i] = (pa, an_a)
                chosen[j] = (pb, an_b)
                ctx.group_kind[key] = 'riser'
            else:
                # вертикальные выноски пары не сливаются: точки раздвинуты вдоль трубы
                # так, чтобы на листе между вертикалями было ~LEAD_SPREAD_MM
                L1 = pa.Location.Curve.Length
                half = LEAD_SPREAD_MM / max(abs(du), 1e-6) / 2.0
                # точки пары — согласованно, в нескольких местах перекрытия (середина, ближе
                # к концам): колонке, не легшей от середины, есть куда сдвинуться вдвоём
                # (db на С.Х.VRF2 ставил пару у конца хода — 4174296/4174309)
                an_a, an_b = [], []
                for cf in (0.5, 0.75, 0.25, 0.88, 0.12):
                    c = lo + (hi - lo) * cf
                    best_ab = None
                    for sg in (1.0, -1.0):
                        ta = min(max(c - sg * half, 0.08 * L1), 0.92 * L1)
                        a_try = p0 + d1 * ta
                        b_try = cb.Project(p0 + d1 * (c + sg * half)).XYZPoint
                        sep = abs(ctx.uv(a_try)[0] - ctx.uv(b_try)[0])
                        sc = abs(min(sep, LEAD_SPREAD_MM) - LEAD_SPREAD_MM)
                        if best_ab is None or sc < best_ab[0]:
                            best_ab = (sc, a_try, b_try)
                    a_pt, b_pt = best_ab[1], best_ab[2]
                    if ctx.visible_pt(a_pt) and ctx.visible_pt(b_pt):
                        an_a.append(a_pt + ctx.dp(pa))
                        an_b.append(b_pt + ctx.dp(pb))
                if not an_a:
                    a_pt = mid
                    b_pt = cb.Project(mid).XYZPoint
                    if not (ctx.visible_pt(a_pt) and ctx.visible_pt(b_pt)):
                        continue
                    an_a, an_b = [a_pt + ctx.dp(pa)], [b_pt + ctx.dp(pb)]
                chosen[i] = (pa, an_a)
                chosen[j] = (pb, an_b)
            ctx.group_of[_iv(pa.Id)] = key
            ctx.group_of[_iv(pb.Id)] = key
            small = pa if pa.Diameter <= pb.Diameter else pb
            for x in (pa, pb):
                ctx.line[_iv(x.Id)] = u'L' if x.Id == small.Id else u'G'
            ctx.add(u'Пар жидкость/газ (колонка из 2)')
        for i, run in enumerate(runs):
            if i in chosen:
                el, an = chosen[i]
                jobs.append((el, pipe_t, an, u'Марки труб'))
                continue
            best = None
            for p in sorted(run, key=lambda x: x.Location.Curve.Length, reverse=True):
                an = anchors_of(ctx, p)
                if an:
                    best = (p, an)
                    break
            if best is not None:
                ctx.group_of[_iv(best[0].Id)] = u'one%d' % i
                jobs.append((best[0], pipe_t, best[1], u'Марки труб'))
    if multi_t is not None:
        refs = []
        for e in els:
            if _cat(e) != C_PACC:
                continue
            fn = (_fam(e) + u' ' + _type_name(e)).lower()
            if not any(w in fn for w in REFNET_WORDS) and u'arbln' not in fn and u'arcnn' not in fn:
                continue
            if (picked is not None and _iv(e.Id) not in picked) or _iv(e.Id) in tagged:
                continue
            refs.append(e)
        pairs, used = _refnet_pairs(ctx, refs)
        for a, la, b, lb in pairs:
            key = u'ref%d' % _iv(a.Id)
            ca = [(anchor_of(ctx, a), 0.0)] + [(c.Origin + ctx.dp(a), 0.5) for c in _conns_all(a)]
            cbb = [(anchor_of(ctx, b), 0.0)] + [(c.Origin + ctx.dp(b), 0.5) for c in _conns_all(b)]
            bestp = None
            for (x, wx) in ca:
                for (y, wy) in cbb:
                    sep = abs(ctx.uv(x)[0] - ctx.uv(y)[0])
                    sc = abs(min(sep, LEAD_SPREAD_MM) - LEAD_SPREAD_MM) + wx + wy
                    if bestp is None or sc < bestp[0]:
                        bestp = (sc, x, y)
            for e, ln, pt in ((a, la, bestp[1]), (b, lb, bestp[2])):
                ctx.group_of[_iv(e.Id)] = key
                ctx.line[_iv(e.Id)] = ln
                jobs.append((e, multi_t, [pt, anchor_of(ctx, e)], u'Марки разветвителей'))
        for e in refs:
            if _iv(e.Id) not in used:
                ctx.group_of[_iv(e.Id)] = u'r1%d' % _iv(e.Id)
                jobs.append((e, multi_t, [anchor_of(ctx, e)], u'Марки разветвителей'))
        for e in FilteredElementCollector(doc, view.Id).OfCategory(BIC.OST_MechanicalEquipment) \
                .WhereElementIsNotElementType():
            if getattr(e, 'SuperComponent', None) is not None or u'EEV' not in _fam(e):
                continue
            if (picked is not None and _iv(e.Id) not in picked) or _iv(e.Id) in tagged:
                continue
            ctx.group_of[_iv(e.Id)] = u'eev%d' % _iv(e.Id)
            jobs.append((e, multi_t, [anchor_of(ctx, e)], u'Марки EEV-китов'))
    if not jobs:
        ctx.add(u'Нечего подписывать', 0)
        return
    ctx.angled = True
    place_tags(ctx, jobs, u"Марки труб и разветвителей")


T_XNAME = (u'db_М_по_НК', u'db_Имя системы')
T_XINFO = (u'db_M_Несколько категорий', u'Завод_Марка_Qт_Qх')
T_XVRF = (u'db_М_по_НК_Имя типа_Qх_№ пом', u'db_М_по_НК_Имя типа_Qх_№ пом')


def _sym_exact(doc, fam, typ):
    for s_ in FilteredElementCollector(doc).OfClass(FamilySymbol):
        try:
            if s_.FamilyName == fam and Element.Name.GetValue(s_) == typ:
                return s_
        except Exception:
            pass
    return None


def _pstr(el, name):
    p = el.LookupParameter(name)
    if p is None:
        return u''
    return (p.AsString() or p.AsValueString() or u'').strip()


def step_xeq(ctx):
    """Оборудование и канальные охладители на схеме холодоснабжения — как у инженера
    (С.Х.ККБ1/ККБ2_ТЕСТ, 14.10.2026): под (или над) элементом вертикальная стопка —
    ближе к элементу марка «db_Имя системы» (если параметр заполнен), дальше —
    «Завод_Марка_Qт_Qх». Выноски строго вертикальные, от низа (верха) элемента по
    центру. Наружный блок (имя системы пустое) — одна марка, обычно над ним.
    EEV-киты подписываются в шаге «Марки труб…»."""
    import stack_tags
    doc, view = ctx.doc, ctx.view
    t_name, t_info = _sym_exact(doc, *T_XNAME), _sym_exact(doc, *T_XINFO)
    # VRF (17.10.2026): одна марка «марка кондиционера, Qх, № помещения» — производитель
    # один, имя системы не пишем; ККБ — «Имя системы» + «Завод_Марка_Qт_Qх»
    ctx.xeq_vrf = _scheme_kind(ctx, _pipe_view_els(ctx)) == u'vrf'
    if ctx.xeq_vrf:
        t_vrf = _sym_exact(doc, *T_XVRF)
        if t_vrf is None:
            ctx.add(u'Нет марки «db_М_по_НК_Имя типа_Qх_№ пом»', 0)
            return
        t_name, t_info = None, t_vrf
    if t_info is None:
        ctx.add(u'Нет марки «db_M_Несколько категорий : Завод_Марка_Qт_Qх»', 0)
        return
    # трубы — в занятость: марка оборудования не ложится на трубу
    ctx.occ.band_w = 25.0
    for pp in _pipe_view_els(ctx):
        if _cat(pp) != C_PIPE or not isinstance(pp.Location, LocationCurve):
            continue
        cc = pp.Location.Curve
        dd = ctx.dp(pp)
        ctx.occ.add_band(ctx.uv(cc.GetEndPoint(0) + dd), ctx.uv(cc.GetEndPoint(1) + dd),
                         max(0.6, pp.Diameter * FT_MM / view.Scale / 2.0 + 0.3))
    has = {}
    for t in ctx.tags:
        try:
            tn = Element.Name.GetValue(doc.GetElement(t.GetTypeId()))
        except Exception:
            continue
        for i in t.GetTaggedLocalElementIds():
            has.setdefault(_iv(i), set()).add(tn)
    els = []
    for e in FilteredElementCollector(doc, view.Id).WhereElementIsNotElementType():
        c = _cat(e)
        if c not in (C_EQ, C_ACC) or getattr(e, 'SuperComponent', None) is not None:
            continue
        if ctx.scope_given is not None and _iv(e.Id) not in ctx.scope_given:
            continue
        if c == C_EQ and u'EEV' in _fam(e):
            continue
        et = doc.GetElement(e.GetTypeId())
        if c == C_ACC and not (et is not None and _pstr(et, u'ADSK_Завод-изготовитель')):
            continue
        els.append(e)
    created = []
    import xyz_plane
    xyz_plane.Transaction = Transaction
    ptok = xyz_plane.push(doc, view, view.ViewDirection, view.Origin, u"Оборудование: плоскость")
    try:
        _xeq_in(ctx, els, t_name, t_info, has, created)
    finally:
        xyz_plane.pop(doc, view, ptok)


def _geo_uv_box(ctx, e):
    """Рамка (u0, v0, u1, v1) видимой геометрии элемента на листе. Геометрия с
    Options.View уже со смещением разноса (проверено 17.10 на С.Х.VRF2) — не добавлять."""
    opt = Options()
    opt.View = ctx.view
    us, vs = [], []

    def add(p):
        u, v = ctx.uv(p)
        us.append(u)
        vs.append(v)

    def scan(geo):
        for g in geo:
            if isinstance(g, GeometryInstance):
                scan(g.GetInstanceGeometry())
            elif isinstance(g, Solid):
                if g.Volume <= 0:
                    continue
                for ed in g.Edges:
                    for p in ed.Tessellate():
                        add(p)
            elif isinstance(g, Curve):
                try:
                    for p in g.Tessellate():
                        add(p)
                except Exception:
                    pass
            elif isinstance(g, Mesh):
                for p in g.Vertices:
                    add(p)
    try:
        scan(e.get_Geometry(opt))
    except Exception:
        return None
    if not us:
        return None
    return (min(us), min(vs), max(us), max(vs))


def _xeq_in(ctx, els, t_name, t_info, has, created):
    import stack_tags
    doc, view = ctx.doc, ctx.view
    t = Transaction(doc, u"Оборудование: марки")
    t.Start()
    try:
        for e in els:
            hv = has.get(_iv(e.Id), set())
            want = []
            if t_name is not None and _pstr(e, u'db_Имя системы') and T_XNAME[1] not in hv:
                want.append(t_name)
            if T_XINFO[1] not in hv and T_XVRF[1] not in hv:
                want.append(t_info)
            if not want:
                continue
            bb = e.get_BoundingBox(None)
            if bb is None:
                continue
            tags = []
            for sym in want:
                if not sym.IsActive:
                    sym.Activate()
                c3 = (bb.Min + bb.Max) * 0.5 + ctx.dp(e)
                tg = IndependentTag.Create(doc, sym.Id, view.Id, Reference(e), True, TagOrientation.Horizontal, c3)
                tg.LeaderEndCondition = LeaderEndCondition.Free
                tags.append(tg)
            created.append((e, tags, bb))
        t.Commit()
    except Exception:
        t.RollBack()
        raise
    if not created:
        ctx.add(u'Нечего подписывать', 0)
        return
    allt = [tg for e, ts, bb in created for tg in ts]
    rels = stack_tags.measure_exact(doc, view, allt, ctx.R, ctx.U, ctx.mm)
    rel = dict((_iv(tg.Id), r) for tg, r in zip(allt, rels))
    mm = ctx.mm
    t = Transaction(doc, u"Оборудование: раскладка")
    t.Start()
    try:
        for e, ts, bb in created:
            d = ctx.dp(e)
            # габарит элемента на экране — по видимой геометрии (габаритный ящик семейства
            # бывает больше блока: зоны обслуживания и т.п. — марки уезжали далеко)
            gb = _geo_uv_box(ctx, e)
            if gb is None:
                pts = [XYZ(x, y, z) + d for x in (bb.Min.X, bb.Max.X) for y in (bb.Min.Y, bb.Max.Y)
                       for z in (bb.Min.Z, bb.Max.Z)]
                uvs = [ctx.uv(p) for p in pts]
                gb = (min(p[0] for p in uvs), min(p[1] for p in uvs), max(p[0] for p in uvs), max(p[1] for p in uvs))
            u0, v0, u1, v1 = gb
            cu = (u0 + u1) / 2.0
            szs = []
            for tg in ts:
                r = rel.get(_iv(tg.Id)) or (-8 * mm, -2.5 * mm, 8 * mm, 2.5 * mm)
                szs.append(tuple(x / mm for x in r))
            best = None
            # варианты: вся стопка снизу, вся сверху, имя сверху + марка снизу
            variants = [('D', [-1] * len(ts)), ('U', [1] * len(ts))]
            if len(ts) == 2:
                variants.append(('S', [1, -1]))
            vrf = getattr(ctx, 'xeq_vrf', False)
            if vrf and len(ts) == 1:
                # правки db (С.Х.VRF2 17.10): над блоком тесно — марка сбоку, выноска
                # горизонтальная ~10 мм листа до края марки, на высоте верхней части блока
                variants += [('R', [2]), ('L', [-2])]
            for vn, sides in variants:
                gaps0 = ((6.0, 10.0, 14.0, 20.0, 28.0) if vn in ('U', 'D', 'S') else (8.0, 10.0, 14.0, 20.0)) if vrf \
                    else (3.0, 6.0, 10.0, 16.0)
                for gap0 in gaps0:
                    plan, cost, ok = [], 0.0, True
                    off = {1: gap0, -1: gap0}
                    for tg, sz, sd in zip(ts, szs, sides):
                        r0, q0, r1, q1 = sz
                        hgt = q1 - q0
                        if sd in (2, -2):
                            av_ = v0 + (v1 - v0) * 0.75
                            au_ = u1 if sd > 0 else u0
                            hu = (au_ + gap0 - r0) if sd > 0 else (au_ - gap0 - r1)
                            hv = av_ - (q0 + q1) / 2.0
                            box = (hu + r0, hv + q0, hu + r1, hv + q1)
                            c = ctx.occ.box_cost(box)
                            if c >= HARD:
                                ok = False
                                break
                            lead = [(au_, av_), ((hu + r0) if sd > 0 else (hu + r1), av_)]
                            cost += c + ctx.occ.lead_cost(lead)
                            plan.append((tg, hu, hv, (au_, av_), box, lead))
                            continue
                        if sd < 0:
                            top = v0 - off[-1]
                            hv = top - q1
                            off[-1] += hgt + 1.0
                            anchor_v = v0
                        else:
                            bot = v1 + off[1]
                            hv = bot - q0
                            off[1] += hgt + 1.0
                            anchor_v = v1
                        hu = cu - (r0 + r1) / 2.0
                        box = (hu + r0, hv + q0, hu + r1, hv + q1)
                        c = ctx.occ.box_cost(box)
                        if c >= HARD:
                            ok = False
                            break
                        lead = [(cu, anchor_v), (cu, (hv + q0) if sd > 0 else (hv + q1))]
                        cost += c + ctx.occ.lead_cost(lead)
                        plan.append((tg, hu, hv, (cu, anchor_v), box, lead))
                    if not ok:
                        continue
                    if vrf:
                        # VRF1: марка над блоком ~10 мм листа по центру (13 из 17), реже под ним;
                        # сбоку — если над блоком выноска пересекла бы трубы/марки (VRF2, db)
                        cost += abs(gap0 - 10.0) * 0.6 + {'D': 3.0, 'U': 0.0, 'S': 2.0, 'R': 7.0, 'L': 8.0}[vn]
                    else:
                        cost += gap0 * 1.0 + {'D': 0.0, 'U': 3.0, 'S': 2.0}[vn]
                    if not _pstr(e, u'db_Имя системы') and vn == 'U':
                        cost -= 4.0      # наружный блок: марка над ним
                    if best is None or cost < best[0]:
                        best = (cost, plan)
            if best is None:
                for tg in ts:
                    doc.Delete(tg.Id)
                ctx.skipped.append(e.Id)
                continue
            for tg, hu, hv, (au, av), box, lead in best[1]:
                # конец выноски: центр элемента по горизонтали экрана, низ (верх) габарита;
                # сбоку — край габарита на 3/4 высоты
                base = (bb.Min + bb.Max) * 0.5 + d
                bu, bv = ctx.uv(base)
                a3 = base + ctx.R * ((au - bu) * mm) + ctx.U * ((av - bv) * mm)
                ref = None
                for r_ in tg.GetTaggedReferences():
                    ref = r_
                    break
                _reset_leader(tg)
                tg.TagHeadPosition = base + ctx.R * ((hu - bu) * mm) + ctx.U * ((hv - bv) * mm)
                try:
                    tg.SetLeaderEnd(ref, a3)
                except Exception:
                    pass
                ctx.occ.add_box(box)
                ctx.occ.add_seg(lead[0], lead[1])
            ctx.add(u'Подписано оборудования и охладителей')
        t.Commit()
    except Exception:
        t.RollBack()
        raise


def step_tags(ctx, kind, strict=False):
    doc = ctx.doc
    if kind in ('damper', 'silencer'):
        sym = _find_tag_type(doc, *T_ACC)
    elif kind == 'equip':
        sym = _find_tag_type(doc, *T_EQ)
    else:
        sym = _find_tag_type(doc, *T_FIT)
    if sym is None:
        ctx.add(u'Нет типа марки для этого шага', 0)
        return
    what = dict(STEPS)[kind]
    jobs = []
    for el in ctx.all_els:
        if not ctx.in_scope(el) or _iv(el.Id) in ctx.tagged:
            continue
        cid = _cat(el)
        ok = False
        if kind == 'damper':
            ok = cid == C_ACC and _is_main_damper(el)
        elif kind == 'silencer':
            ok = cid == C_ACC and u'Шумоглуш' in _fam(el)
        elif kind == 'equip':
            ok = cid == C_EQ and getattr(el, 'SuperComponent', None) is None
        elif kind == 'tees':
            f = _fam(el)
            ok = cid == C_FIT and (u'Тройник' in f or u'Крестовина' in f) and _tee_needs(ctx, el, strict)
        if ok:
            jobs.append((el, sym, anchors_of(ctx, el), what))
    place_tags(ctx, jobs, what)


# ---------------------------------------------------------------------------
# Высотные отметки на схемах ТРУБ (фреон, ККБ) — по образцу инженера (лист 9.3)
#   * горизонтальные участки: одна отметка на «ход» — цепочку горизонтальных
#     труб и фитингов одной высоты в одном наборе разноса; параллельные трубы
#     пары (жидкость/газ) на той же высоте — один ход; короче 1 м — без отметки;
#     отметка по оси трубы, плечо 3-12 мм, полка «Вверх»/«Вниз»;
#   * оборудование — отметка НИЗА (нижнее ребро, ближнее к зрителю); одинаковые
#     блоки рядом (наружные блоки в ряд) — одна отметка на группу.
# ---------------------------------------------------------------------------
T_SPOT_DN_SCH = u'db_Стрелка_Проектная_Схемы_Вниз'
T_SPOT_UP_SCH = u'db_Стрелка_Проектная_Схемы_Вверх'
MIN_PIPE_RUN_MM = 1000.0
PAIR_GAP_MM = 300.0
PAIR_DZ_MM = 30.0
EQ_CLUSTER_MM = 3000.0


def _pipe_view_els(ctx):
    from System.Collections.Generic import List
    cats = [BIC.OST_PipeCurves, BIC.OST_PipeFitting, BIC.OST_PipeAccessory]
    mf = ElementMulticategoryFilter(List[BuiltInCategory](cats))
    return list(FilteredElementCollector(ctx.doc, ctx.view.Id).WherePasses(mf).WhereElementIsNotElementType())


def _flat_z(el):
    """Высота, если все концевые соединители элемента на одной отметке (±5 мм)."""
    cs = _conns_all(el)
    if not cs:
        return None
    zs = [c.Origin.Z for c in cs]
    if (max(zs) - min(zs)) * FT_MM > 5.0:
        return None
    return sum(zs) / len(zs)


def _pipe_runs(ctx, pipes):
    """Ходы: цепочки горизонтальных труб/фитингов одной высоты в одном наборе разноса.
    Обход по соединителям — скрытые на виде фитинги тоже связывают ход."""
    seen, runs = set(), []
    for p in pipes:
        i0 = _iv(p.Id)
        if i0 in seen:
            continue
        z0 = _flat_z(p)
        if z0 is None:
            continue
        s0 = ctx.dset.get(i0, 0)
        run, stack = [], [p]
        seen.add(i0)
        while stack:
            e = stack.pop()
            if _cat(e) == C_PIPE:
                run.append(e)
            for c in _conns_all(e):
                r = _next_any(c)
                if r is None:
                    continue
                o = r.Owner
                io = _iv(o.Id)
                if io in seen or ctx.dset.get(io, 0) != s0:
                    continue
                if _cat(o) not in (C_PIPE, C_PFIT, C_PACC):
                    continue
                z = _flat_z(o)
                if z is None or abs(z - z0) * FT_MM > 5.0:
                    continue
                seen.add(io)
                stack.append(o)
        if run:
            runs.append({'pipes': run, 'z': z0, 'set': s0,
                         'L': sum(x.Location.Curve.Length for x in run) * FT_MM})
    return runs


def _runs_paired(a, b):
    """Ходы пары (жидкость/газ): та же высота и набор, идут рядом параллельно."""
    if a['set'] != b['set'] or abs(a['z'] - b['z']) * FT_MM > PAIR_DZ_MM:
        return False
    gap = PAIR_GAP_MM / FT_MM
    for p in a['pipes']:
        c1 = p.Location.Curve
        p0, p1 = c1.GetEndPoint(0), c1.GetEndPoint(1)
        d1 = XYZ(p1.X - p0.X, p1.Y - p0.Y, 0)
        if d1.GetLength() < 1e-6:
            continue
        d1 = d1.Normalize()
        for q in b['pipes']:
            # пара жидкость/газ — разные системы или разные диаметры; две ветки
            # одной системы и диаметра рядом — не пара (С.Х.VRF1, 16.10.2026)
            if _sys(p) == _sys(q) and abs(p.Diameter - q.Diameter) * FT_MM < 0.5:
                continue
            c2 = q.Location.Curve
            q0, q1 = c2.GetEndPoint(0), c2.GetEndPoint(1)
            d2 = XYZ(q1.X - q0.X, q1.Y - q0.Y, 0)
            if d2.GetLength() < 1e-6 or abs(d1.DotProduct(d2.Normalize())) < 0.99:
                continue
            w = XYZ(q0.X - p0.X, q0.Y - p0.Y, 0)
            lat = abs(w.X * d1.Y - w.Y * d1.X)
            if lat > gap:
                continue
            a0, a1 = 0.0, c1.Length
            t0 = w.DotProduct(d1)
            t1 = XYZ(q1.X - p0.X, q1.Y - p0.Y, 0).DotProduct(d1)
            ov = min(a1, max(t0, t1)) - max(a0, min(t0, t1))
            if ov > 0.5 * min(c1.Length, c2.Length):
                return True
    return False


def _pair_gap(a, b):
    """Как _runs_paired, но возвращает наименьший боковой зазор (мм) или None."""
    if a['set'] != b['set'] or abs(a['z'] - b['z']) * FT_MM > PAIR_DZ_MM:
        return None
    gap, best = PAIR_GAP_MM / FT_MM, None
    for p in a['pipes']:
        c1 = p.Location.Curve
        p0, p1 = c1.GetEndPoint(0), c1.GetEndPoint(1)
        d1 = XYZ(p1.X - p0.X, p1.Y - p0.Y, 0)
        if d1.GetLength() < 1e-6:
            continue
        d1 = d1.Normalize()
        for q in b['pipes']:
            if _sys(p) == _sys(q) and abs(p.Diameter - q.Diameter) * FT_MM < 0.5:
                continue
            c2 = q.Location.Curve
            q0, q1 = c2.GetEndPoint(0), c2.GetEndPoint(1)
            d2 = XYZ(q1.X - q0.X, q1.Y - q0.Y, 0)
            if d2.GetLength() < 1e-6 or abs(d1.DotProduct(d2.Normalize())) < 0.99:
                continue
            w = XYZ(q0.X - p0.X, q0.Y - p0.Y, 0)
            lat = abs(w.X * d1.Y - w.Y * d1.X)
            if lat > gap:
                continue
            t0 = w.DotProduct(d1)
            t1 = XYZ(q1.X - p0.X, q1.Y - p0.Y, 0).DotProduct(d1)
            ov = min(c1.Length, max(t0, t1)) - max(0.0, min(t0, t1))
            if ov > 0.5 * min(c1.Length, c2.Length):
                v = lat * FT_MM - ov * FT_MM * 0.001
                if best is None or v < best:
                    best = v
    return best


def _spot_search(ctx, crv, d, tpars=(0.5, 0.35, 0.65, 0.2, 0.8), force=False, up_first=False):
    """Лучшее место отметки на кривой (модельные координаты, d — смещение разноса).
    force — если чистого места нет, всё равно вернуть наименее плохое."""
    best = None
    for tpar in tpars:
        p = crv.Evaluate(tpar, True)
        au, av = ctx.uv(p + d)
        for L in (3.0, 5.0, 8.0, 12.0):
            for su in (-1, 1):
                for up, sv in ((False, -1), (True, 1)):
                    eu = au + su * L
                    tu, tv = eu + su * 7.0, av + sv * 5.3
                    box = (tu - 8.5, tv - 2.8, tu + 8.5, tv + 2.8)
                    c = ctx.occ.box_cost(box)
                    if c >= HARD and not force:
                        continue
                    # инженер (ККБ1/ККБ2, 14.10): полка короткая (~3 мм); у труб текст
                    # чаще НАД полкой, у оборудования — под ней
                    c += ctx.occ.lead_cost([(au, av), (eu, av)]) + (L - 3.0) * 1.0 \
                        + ((0 if up else 1.0) if up_first else (0 if not up else 1.0)) \
                        + (tpars.index(tpar) * 1.5 if tpars[0] > 0.9 or tpars[0] < 0.1 else abs(tpar - 0.5) * 6.0)
                    if best is None or c < best[0]:
                        best = (c, p, su, L, up, box, (au, av), (eu, av))
    if best is None or (best[0] >= 2000.0 and not force):
        return None
    return best


def _spot_create(ctx, ref, best, t_dn, t_up):
    c, p, su, L, up, box, a, b = best
    end = p + ctx.R * (su * L * ctx.mm)
    sp = ctx.doc.Create.NewSpotElevation(ctx.view, ref, p, p, end, p, True)
    typ = t_up if up else t_dn
    if typ is not None:
        sp.ChangeTypeId(typ.Id)
    ctx.occ.add_box(box)
    ctx.occ.add_seg(a, b)
    return sp


def _eq_bottom_edge(ctx, el):
    """Нижнее горизонтальное ребро оборудования, ближнее к зрителю: (Reference, Curve)."""
    opt = Options()
    opt.ComputeReferences = True
    opt.DetailLevel = ViewDetailLevel.Fine
    cands = []
    vd = ctx.view.ViewDirection

    def scan(geo, tr):
        for g in geo:
            if isinstance(g, GeometryInstance):
                scan(g.GetSymbolGeometry(), tr.Multiply(g.Transform))
            elif isinstance(g, Solid) and g.Volume > 0:
                for e in g.Edges:
                    if e.Reference is None:
                        continue
                    cv = e.AsCurve()
                    if not isinstance(cv, Line):
                        continue
                    cv = cv.CreateTransformed(tr)
                    if abs(cv.Direction.Z) > 0.01 or cv.Length * FT_MM < 50:
                        continue
                    m = cv.Evaluate(0.5, True)
                    cands.append((m.Z, -m.DotProduct(vd), e.Reference, cv))
    try:
        scan(el.get_Geometry(opt), Transform.Identity)
    except Exception:
        return None, None
    if not cands:
        return None, None
    zmin = min(x[0] for x in cands)
    low = [x for x in cands if x[0] - zmin < 0.005]
    low.sort(key=lambda x: x[1])
    return low[0][2], low[0][3]


def _ensure_flat_plane(ctx):
    """Типы отметок «…Схемы…» рассчитаны на ГОРИЗОНТАЛЬНУЮ рабочую плоскость
    3D-вида (так на видах инженера). Выравнивание марок, «Колонка» и «Отметка на
    взрыв-схеме» ставят виду плоскость вдоль экрана — тогда текст отметок уезжает
    от полки. Возвращает True, если плоскость пришлось поменять."""
    v = ctx.view
    sp = v.SketchPlane
    try:
        if sp is not None and abs(sp.GetPlane().Normal.Z) > 0.999:
            return False
    except Exception:
        pass
    v.SketchPlane = SketchPlane.Create(ctx.doc, Plane.CreateByNormalAndOrigin(XYZ.BasisZ, XYZ.Zero))
    return True


def _mark_side_search(ctx, crv, d, tpars=(0.5, 0.35, 0.65, 0.2, 0.8), force=False):
    """Место марки-отметки (xyz_elev_marks) на смещённом элементе: точка и сторона полки."""
    best = None
    for tpar in tpars:
        p = crv.Evaluate(tpar, True)
        u, v = ctx.uv(p + d)
        for side, box in (('R', (u - 1, v - 6, u + 15, v + 1)), ('L', (u - 15, v - 6, u + 1, v + 1)),
                          ('UR', (u - 1, v - 1, u + 15, v + 6)), ('UL', (u - 15, v - 1, u + 1, v + 6))):
            c = ctx.occ.box_cost(box)
            if c >= HARD and not force:
                continue
            c += (tpars.index(tpar) * 1.5 if tpars[0] > 0.9 or tpars[0] < 0.1 else abs(tpar - 0.5) * 6.0) \
                + (0 if side == 'R' else 0.5)
            if best is None or c < best[0]:
                best = (c, p, side, box)
    return best


def _z_end_tpars(ctx, p):
    """Отметка у колена на перепад (правило инженера 17.10.2026, С.Х.VRF2/VRF1/ККБ):
    если конец трубы через отвод выходит на вертикальную трубу — точки у этого конца
    (параметр 0..1 от начала трубы), иначе None."""
    c = p.Location.Curve
    p0, p1 = c.GetEndPoint(0), c.GetEndPoint(1)
    out = []
    for cn in _conns_all(p):
        r = _next_any(cn)
        if r is None:
            continue
        o = r.Owner
        nxt = []
        if _cat(o) == C_PIPE:
            nxt = [o]
        elif len(_conns_all(o)) == 2:
            for c2 in _conns_all(o):
                r2 = _next_any(c2)
                if r2 is not None and r2.Owner.Id != p.Id and _cat(r2.Owner) == C_PIPE:
                    nxt.append(r2.Owner)
        for q in nxt:
            qc = q.Location.Curve
            dq = qc.GetEndPoint(1) - qc.GetEndPoint(0)
            if dq.GetLength() > 1e-6 and abs(dq.Normalize().Z) > 0.7:
                at_start = cn.Origin.DistanceTo(p0) < cn.Origin.DistanceTo(p1)
                out.append(0.0 if at_start else 1.0)
    if not out:
        return None
    e = out[0]
    ts = (0.97, 0.93, 0.88, 0.8, 0.7, 0.55, 0.4, 0.25, 0.1, 0.04)
    return tuple((1.0 - t) if e == 0.0 else t for t in ts)


def _place_any(ctx, el, ref, crv, t_dn, t_up, dmap, tpars=(0.5, 0.35, 0.65, 0.2, 0.8), force=False):
    up_first = _cat(el) == C_PIPE
    """Несмещённый элемент — отметка Revit; смещённый — марка-отметка
    («Отметка на взрыв-схеме»): Revit рисует свою отметку на несмещённом месте.
    force — нет чистого места: поставить в наименее плохое (элемент — в ctx.forced).
    ref = None — у элемента нет ребра для отметки Revit: марка-отметка и на несмещённом."""
    import xyz_elev_marks
    d = ctx.dp(el)
    for frc in ((False, True) if force else (False,)):
        if d.GetLength() > 1e-6 or ref is None:
            b = _mark_side_search(ctx, crv, d, tpars, frc)
            if b is None:
                continue
            tg = xyz_elev_marks.place(ctx.doc, ctx.view, el, None, b[1], b[2], None, dmap, None)
            ctx.occ.add_box(b[3])
            ok = tg is not None
        else:
            b = _spot_search(ctx, crv, d, tpars, frc, up_first)
            if b is None:
                continue
            try:
                _spot_create(ctx, ref, b, t_dn, t_up)
                ok = True
            except Exception:
                # Revit не дал поставить отметку на это ребро — марка-отметка
                bm = _mark_side_search(ctx, crv, d, tpars, True)
                tg = xyz_elev_marks.place(ctx.doc, ctx.view, el, None, bm[1], bm[2], None, dmap, None) if bm else None
                if bm:
                    ctx.occ.add_box(bm[3])
                ok = tg is not None
        if ok and frc:
            ctx.forced.append(el.Id)
        return ok
    return False


def _is_point_obj(el):
    """Семейство-экземпляр (не труба/воздуховод/фитинг, не вложенное)."""
    if not isinstance(el, FamilyInstance) or getattr(el, 'SuperComponent', None) is not None:
        return False
    return _cat(el) not in (C_PIPE, C_PFIT, C_DUCT, C_FIT, C_FLEX)


def _bottom_line(ctx, el):
    """(Reference, Curve) низа объекта: нижнее ребро; нет ребра — (None, отрезок
    по низу габарита вдоль экрана) — тогда ставится марка-отметка."""
    ref, crv = _eq_bottom_edge(ctx, el)
    if crv is not None:
        return ref, crv
    bb = el.get_BoundingBox(None)
    if bb is None:
        return None, None
    c = (bb.Min + bb.Max) * 0.5
    p = XYZ(c.X, c.Y, bb.Min.Z)
    h = ctx.R * (5.0 * ctx.mm)
    return None, Line.CreateBound(p - h, p + h)


def _cluster_same_level(ctx, groups, glen):
    """Отметка — только где меняется высота: ходы одной высоты, связанные через
    короткие уступы/подъёмы (вертикальные трубы, фитинги, ходы < 1 м; до 3 м пути),
    — одна отметка. Возвращает список кластеров (списков индексов групп)."""
    owner = {}
    for gi, g in enumerate(groups):
        for r in g:
            for p in r['pipes']:
                owner[_iv(p.Id)] = gi
    qual = set(gi for gi in range(len(groups)) if glen[gi] >= MIN_PIPE_RUN_MM)
    par = list(range(len(groups)))

    def find(k):
        while par[k] != k:
            par[k] = par[par[k]]
            k = par[k]
        return k
    lim = 3000.0 / FT_MM
    for gi in qual:
        g = groups[gi]
        z0, s0 = g[0]['z'], g[0]['set']
        start = [p for r in g for p in r['pipes']]
        seen = set(_iv(p.Id) for p in start)
        front = [(p, 0.0) for p in start]
        while front:
            e, dist = front.pop()
            for c in _conns_all(e):
                rr = _next_any(c)
                if rr is None:
                    continue
                o = rr.Owner
                io = _iv(o.Id)
                if io in seen:
                    continue
                seen.add(io)
                oj = owner.get(io)
                if oj is not None and oj in qual:
                    og = groups[oj]
                    if oj != gi and og[0]['set'] == s0 and abs(og[0]['z'] - z0) * FT_MM < 5.0:
                        par[find(oj)] = find(gi)
                    continue                      # за другой длинный ход не идём
                if _cat(o) not in (C_PIPE, C_PFIT, C_PACC):
                    continue
                L = o.Location.Curve.Length if isinstance(o.Location, LocationCurve) else 0.0
                if dist + L <= lim:
                    front.append((o, dist + L))
    cl = {}
    for gi in qual:
        cl.setdefault(find(gi), []).append(gi)
    return list(cl.values())


def _pipe_leg(ctx, p):
    """Участок хода между рефнетами (тройниками): горизонтальные трубы и фитинги
    одной высоты в одном наборе разноса; через фитинг с 3+ соединителями не идём."""
    z0 = _flat_z(p)
    if z0 is None:
        return [p]
    s0 = ctx.dset.get(_iv(p.Id), 0)
    seen, leg, stack = set([_iv(p.Id)]), [], [p]
    while stack:
        e = stack.pop()
        if _cat(e) == C_PIPE:
            leg.append(e)
        for c in _conns_all(e):
            r = _next_any(c)
            if r is None:
                continue
            o = r.Owner
            io = _iv(o.Id)
            if io in seen or ctx.dset.get(io, 0) != s0:
                continue
            if _cat(o) not in (C_PIPE, C_PFIT, C_PACC):
                continue
            z = _flat_z(o)
            if z is None or abs(z - z0) * FT_MM > 5.0:
                continue
            if _cat(o) != C_PIPE and len(_conns_all(o)) > 2:
                continue                      # рефнет — граница участка
            seen.add(io)
            stack.append(o)
    return leg


def _leg_bounds(ctx, leg):
    """Что на концах участка: 'Z' — перепад высоты (стояк/наклон), 'EQ' — прибор
    (концевой участок), 'BREAK' — разрыв взрыв-схемы (сосед в другом наборе
    разноса), 'TEE' — рефнет, 'OPEN' — свободный конец."""
    own = set(_iv(x.Id) for x in leg)
    z0 = _flat_z(leg[0])
    s0 = ctx.dset.get(_iv(leg[0].Id), 0)
    out = []
    for e in leg:
        for c in _conns_all(e):
            r = _next_any(c)
            if r is None:
                out.append('OPEN')
                continue
            o = r.Owner
            io = _iv(o.Id)
            if io in own:
                continue
            if _cat(o) not in (C_PIPE, C_PFIT, C_PACC):
                out.append('EQ')
            elif ctx.dset.get(io, 0) != s0:
                out.append('BREAK')
            else:
                z = _flat_z(o)
                if z is None or abs(z - z0) * FT_MM > 5.0:
                    out.append('Z')
                elif _cat(o) != C_PIPE and len(_conns_all(o)) > 2:
                    out.append('TEE')
                else:                         # фитинг той же высоты (отвод) — смотрим дальше
                    own.add(io)
                    for c2 in _conns_all(o):
                        r2 = _next_any(c2)
                        if r2 is not None and _iv(r2.Owner.Id) not in own:
                            o2 = r2.Owner
                            if _cat(o2) not in (C_PIPE, C_PFIT, C_PACC):
                                out.append('EQ')
                            elif ctx.dset.get(_iv(o2.Id), 0) != s0:
                                out.append('BREAK')
                            else:
                                z2 = _flat_z(o2)
                                out.append('Z' if (z2 is None or abs(z2 - z0) * FT_MM > 5.0) else 'TEE')
    return out


ELEV_MIN_PIECE_MM = 600.0   # вставка между отводами короче — отметку на длинный ход рядом (правки db, С.Х.VRF2 17.10)


def _end_ts(at_start):
    # у конца хода; если там рисунок блока (3903634 у ARNU76, t17) — дальше по ходу
    ts = (0.97, 0.93, 0.88, 0.8, 0.7, 0.55, 0.4, 0.25, 0.1, 0.04)
    return tuple((1.0 - t) if at_start else t for t in ts)


def _long_same_z(ctx, p, allp_ids):
    """Короткая вставка у перепада → ближайшая длинная труба той же высоты (через
    отводы/переходы, в пределах участка) и параметры точек у конца, обращённого к вставке."""
    z0 = _flat_z(p)
    if z0 is None:
        return None
    seen = {_iv(p.Id)}
    front = [p]
    found = []
    for _depth in range(4):
        nxt_front = []
        for q in front:
            for cn in _conns_all(q):
                r = _next_any(cn)
                if r is None:
                    continue
                o = r.Owner
                cands = []
                if _cat(o) == C_PIPE:
                    cands = [(o, r)]
                elif len(_conns_all(o)) == 2:
                    for c2 in _conns_all(o):
                        r2 = _next_any(c2)
                        if r2 is not None and r2.Owner.Id != q.Id and _cat(r2.Owner) == C_PIPE:
                            cands.append((r2.Owner, r2))
                for w, rw in cands:
                    wi = _iv(w.Id)
                    if wi in seen or wi not in allp_ids:
                        continue
                    seen.add(wi)
                    zw = _flat_z(w)
                    if zw is None or abs(zw - z0) * FT_MM > 5.0:
                        continue
                    c = w.Location.Curve
                    at_start = rw.Origin.DistanceTo(c.GetEndPoint(0)) < rw.Origin.DistanceTo(c.GetEndPoint(1))
                    found.append((c.Length, w, at_start))
                    nxt_front.append(w)
        front = nxt_front
        if not front:
            break
    # db (С.Х.VRF2): не первый попавшийся, а самый длинный ход этой высоты рядом
    # (4180135 → 4175104 L4202 мимо 4175101 L1390; 3903668 → 3903634 L5199)
    found = [f for f in found if f[0] * FT_MM >= ELEV_MIN_PIECE_MM]
    if not found:
        return None
    L, w, at_start = max(found, key=lambda f: f[0])
    return w, _end_ts(at_start)


def _elev_order(ctx, allp):
    """Трубы для отметки (правило db 17.10): у колена на перепад, но на ДЛИННОМ ходе —
    короткую вставку между отводами (< ELEV_MIN_PIECE_MM) заменяет ближайшая длинная
    труба той же высоты, точка — у её конца со стороны перепада. Потом остальные.
    Параметры точек — в ctx.elev_t[id]."""
    if not hasattr(ctx, 'elev_t'):
        ctx.elev_t = {}
    ids = set(_iv(p.Id) for p in allp)
    z, used = [], set()
    for p in sorted(allp, key=lambda x: x.Location.Curve.Length, reverse=True):
        tp = _z_end_tpars(ctx, p)
        if tp is None:
            continue
        if p.Location.Curve.Length * FT_MM < ELEV_MIN_PIECE_MM:
            alt = _long_same_z(ctx, p, ids)
            if alt is not None:
                p, tp = alt
        if _iv(p.Id) in used:
            continue
        used.add(_iv(p.Id))
        ctx.elev_t[_iv(p.Id)] = tp
        z.append(p)
    rest = [p for p in allp if _iv(p.Id) not in used]
    rest = sorted(rest, key=lambda x: x.Location.Curve.Length, reverse=True)
    return (z + rest)[:6]


def _elev_tp(ctx, p):
    return getattr(ctx, 'elev_t', {}).get(_iv(p.Id)) or _z_end_tpars(ctx, p) or (0.5, 0.35, 0.65, 0.2, 0.8)


def step_elev_pipes(ctx, pick=None):
    """Отметки на схеме труб. Возвращает True, если на виде есть трубы.
    pick — множество Id, отмеченных в окне выбора (None — как раньше: трубы и
    оборудование выделенного или всего вида)."""
    import xyz_elev_marks
    doc = ctx.doc
    t_dn, t_up = _spot_type(doc, T_SPOT_DN_SCH), _spot_type(doc, T_SPOT_UP_SCH)
    els = _pipe_view_els(ctx)
    pipes = [e for e in els if _cat(e) == C_PIPE and isinstance(e.Location, LocationCurve)]
    if not pipes:
        return False
    picked = pick if pick is not None else ctx.scope_given
    for p in pipes:
        c = p.Location.Curve
        d = ctx.dp(p)
        r = max(0.6, p.Diameter * FT_MM / ctx.view.Scale / 2.0 + 0.3)
        ctx.occ.add_band(ctx.uv(c.GetEndPoint(0) + d), ctx.uv(c.GetEndPoint(1) + d), r)
    # блоки — в занятость: отметки не ставим на рисунок блока (db, С.Х.VRF2: «+4.1…» на ARNU48)
    _eq_boxes(ctx)
    # разветвители — тоже: их марки ставятся позже, точка выноски должна быть свободна
    # (отметка низа ARNU48 легла текстом на ARBLN03321 — его марка не встала, t20)
    _refnet_keepout(ctx, els)
    runs = _pipe_runs(ctx, pipes)
    par = list(range(len(runs)))

    def find(k):
        while par[k] != k:
            par[k] = par[par[k]]
            k = par[k]
        return k
    for a in range(len(runs)):
        for b in range(a + 1, len(runs)):
            if find(a) != find(b) and _runs_paired(runs[a], runs[b]):
                par[find(a)] = find(b)
    gmap = {}
    for k, r in enumerate(runs):
        gmap.setdefault(find(k), []).append(r)
    groups = list(gmap.values())
    glen = [max(r['L'] for r in g) for g in groups]
    clusters = _cluster_same_level(ctx, groups, glen)
    dmap = xyz_elev_marks.disp_map(doc, ctx.view)

    t = Transaction(doc, u"Высотные отметки (трубы)")
    t.Start()
    try:
        if _ensure_flat_plane(ctx):
            ctx.add(u'Рабочая плоскость вида сделана горизонтальной (для типов «Схемы»)')
        placed = set()

        def has_mark(ps):
            return any(_iv(p.Id) in placed or _iv(p.Id) in ctx.spotted or
                       u'ОТМ' in ctx.kinds.get(_iv(p.Id), ()) for p in ps)

        # 1) обязательные участки (правило инженера, 16.10.2026): концевые участки
        #    (ответвления к приборам), участки до и после перепада высоты, на
        #    взрыв-схеме — до и после разрыва. Участок — между рефнетами; пара
        #    жидкость/газ — одна отметка; короче 1 м — без отметки.
        legs, seen_l = [], set()
        for p in pipes:
            if _iv(p.Id) in seen_l or _flat_z(p) is None:
                continue
            leg = _pipe_leg(ctx, p)
            for x in leg:
                seen_l.add(_iv(x.Id))
            L = sum(x.Location.Curve.Length for x in leg) * FT_MM
            if L < MIN_PIPE_RUN_MM:
                continue
            bnd = _leg_bounds(ctx, leg)
            if any(b in ('Z', 'EQ', 'BREAK') for b in bnd):
                legs.append({'pipes': leg, 'z': _flat_z(p), 'set': ctx.dset.get(_iv(p.Id), 0), 'L': L})
        lpar = list(range(len(legs)))

        def lfind(k):
            while lpar[k] != k:
                lpar[k] = lpar[lpar[k]]
                k = lpar[k]
            return k
        cand = []                             # пара — один к одному, ближайшая (без цепочек)
        for a in range(len(legs)):
            for b in range(a + 1, len(legs)):
                g = _pair_gap(legs[a], legs[b])
                if g is not None:
                    same = _sys(legs[a]['pipes'][0]) == _sys(legs[b]['pipes'][0])
                    cand.append((1 if same else 0, g, a, b))
        mate = {}
        for _s, _g, a, b in sorted(cand):
            if a in mate or b in mate:
                continue
            mate[a], mate[b] = b, a
            lpar[b] = a
        lgroups = {}
        for k, lg in enumerate(legs):
            lgroups.setdefault(lfind(k), []).append(lg)
        for lg in lgroups.values():
            allp = [p for r in lg for p in r['pipes']]
            if picked is not None and not any(_iv(p.Id) in picked for p in allp):
                continue
            if has_mark(allp):
                continue
            ok = False
            for frc in ((False, True) if pick is not None else (False,)):
                for p in _elev_order(ctx, allp):
                    ref = Reference.ParseFromStableRepresentation(doc, p.UniqueId + u":0:LINEAR")
                    try:
                        if _place_any(ctx, p, ref, p.Location.Curve, t_dn, t_up, dmap, force=frc,
                                      tpars=_elev_tp(ctx, p)):
                            ok = True
                            placed.add(_iv(p.Id))
                            break
                    except Exception as ex:
                        ctx.add(u'Ошибка отметки трубы: ' + unicode(ex)[:50])
                if ok:
                    break
            if ok:
                ctx.add(u'Отметки: концевые участки, перепады, разрывы')
            else:
                ctx.skipped.append(allp[0].Id)

        # 2) остальные ходы: одна отметка на высоту, если на ней ещё нет ни одной
        for cl in clusters:
            allp = [p for gi in cl for r in groups[gi] for p in r['pipes']]
            if picked is not None and not any(_iv(p.Id) in picked for p in allp):
                continue
            if has_mark(allp):
                continue
            ok = False
            for p in _elev_order(ctx, allp):
                ref = Reference.ParseFromStableRepresentation(doc, p.UniqueId + u":0:LINEAR")
                try:
                    if _place_any(ctx, p, ref, p.Location.Curve, t_dn, t_up, dmap,
                                  force=pick is not None and p is allp[0],
                                  tpars=_elev_tp(ctx, p)):
                        ok = True
                        placed.add(_iv(p.Id))
                        break
                except Exception as ex:
                    ctx.add(u'Ошибка отметки трубы: ' + unicode(ex)[:50])
            if ok:
                ctx.add(u'Отметки труб (смена высоты)')
            else:
                ctx.skipped.append(allp[0].Id)
        # оборудование (или всё отмеченное в окне: арматура, охладители…) — низ
        if pick is not None:
            eqs = [doc.GetElement(ElementId(i)) for i in pick]
            eqs = [e for e in eqs if e is not None and _is_point_obj(e)]
        else:
            eqs = [e for e in FilteredElementCollector(doc, ctx.view.Id).OfCategory(BIC.OST_MechanicalEquipment)
                   .WhereElementIsNotElementType()
                   if getattr(e, 'SuperComponent', None) is None]
        done = []
        for el in eqs:
            i = _iv(el.Id)
            if picked is not None and i not in picked:
                continue
            if pick is not None:
                ref, crv = _bottom_line(ctx, el)
            else:
                ref, crv = _eq_bottom_edge(ctx, el)
            if crv is None or (ref is None and pick is None):
                ctx.skipped.append(el.Id)
                continue
            z = crv.GetEndPoint(0).Z
            loc = crv.Evaluate(0.5, True)
            key = (_iv(el.GetTypeId()), ctx.dset.get(i, 0))
            if i in ctx.spotted or u'ОТМ' in ctx.kinds.get(i, ()) or \
                    any(k == key and abs(z - zz) * FT_MM < 10 and loc.DistanceTo(ll) * FT_MM < EQ_CLUSTER_MM
                        for k, zz, ll in done):
                done.append((key, z, loc))
                continue
            try:
                okp = _place_any(ctx, el, ref, crv, t_dn, t_up, dmap, tpars=(0.5, 0.25, 0.75, 0.1, 0.9),
                                 force=pick is not None)
                if not okp:
                    # своя рамка блока мешает указателю на его низ — без неё, но не на чужие блоки
                    own = getattr(ctx, 'eq_box', {}).get(i)
                    if own is not None and own in ctx.occ.boxes:
                        # рамку блока ужать на 2,5 мм: указатель у края можно, текст на рисунке блока — нет
                        k_ = ctx.occ.boxes.index(own)
                        sh = (own[0] + 2.5, own[1] + 2.5, own[2] - 2.5, own[3] - 2.5)
                        ctx.occ.boxes[k_] = sh if sh[2] > sh[0] and sh[3] > sh[1] else (0, 0, 0, 0)
                        try:
                            okp = _place_any(ctx, el, ref, crv, t_dn, t_up, dmap, tpars=(0.5, 0.25, 0.75, 0.1, 0.9),
                                             force=pick is not None)
                        finally:
                            ctx.occ.boxes[k_] = own
                if okp:
                    ctx.add(u'Отметки низа оборудования' if _cat(el) == C_EQ else u'Отметки низа арматуры и др.')
                    done.append((key, z, loc))
                else:
                    ctx.skipped.append(el.Id)
            except Exception as ex:
                ctx.add(u'Ошибка отметки оборудования: ' + unicode(ex)[:50])
                ctx.skipped.append(el.Id)
        t.Commit()
    except Exception:
        t.RollBack()
        raise
    return True


def step_elev(ctx, pick=None):
    import xyz_elev_marks
    pipe_mode = step_elev_pipes(ctx, pick)
    doc, view, mm = ctx.doc, ctx.view, ctx.mm
    t_dn, t_up = _spot_type(doc, T_SPOT_DN), _spot_type(doc, T_SPOT_UP)

    def is_hz(d):
        c = d.Location.Curve
        v = (c.GetEndPoint(1) - c.GetEndPoint(0)).Normalize()
        return abs(v.Z) < 0.1 and c.Length * FT_MM >= MIN_HZ_MM

    def key(d):
        return (ctx.dset.get(_iv(d.Id), 0), _sys(d), int(round(d.Location.Curve.GetEndPoint(0).Z * FT_MM / 10.0)))

    done = set()
    for d in ctx.all_els:
        if _cat(d) == C_DUCT and isinstance(d.Location, LocationCurve) and is_hz(d) and \
                (_iv(d.Id) in ctx.spotted or u'ОТМ' in ctx.kinds.get(_iv(d.Id), ())):
            done.add(key(d))
    groups = {}
    for d in ctx.all_els:
        if _cat(d) == C_DUCT and isinstance(d.Location, LocationCurve) and is_hz(d) and \
                (ctx.in_scope(d) if pick is None else _iv(d.Id) in pick):
            groups.setdefault(key(d), []).append(d)
    dmap = xyz_elev_marks.disp_map(doc, view)
    t = Transaction(doc, u"Высотные отметки")
    t.Start()
    try:
        for k, ds_ in groups.items():
            if k in done:
                continue
            ok = False
            for d in sorted(ds_, key=_len, reverse=True)[:3]:
                if k[0] != 0:
                    p = d.Location.Curve.Evaluate(0.5, True)
                    try:
                        tg = xyz_elev_marks.place(doc, view, d, None, p, 'R', None, dmap, None)
                        _occ_mark(ctx, tg)
                        ctx.add(u'Отметки на смещённых участках')
                        ok = True
                    except Exception as ex:
                        ctx.add(u'Ошибка отметки: ' + unicode(ex)[:50])
                    break
                if _place_spot(ctx, d, t_dn, t_up):
                    ctx.add(u'Высотные отметки Revit')
                    ok = True
                    break
            if not ok and k[0] == 0:
                ctx.skipped.append(ds_[0].Id)
        # оборудование - низ (на схеме труб уже отмечено выше)
        if pipe_mode:
            pts = []
        elif pick is not None:
            pts = [ctx.doc.GetElement(ElementId(i)) for i in pick]
            pts = [e for e in pts if e is not None and _is_point_obj(e)]
        else:
            pts = [e for e in ctx.all_els if _cat(e) == C_EQ and ctx.in_scope(e)
                   and getattr(e, 'SuperComponent', None) is None]
        for el in pts:
            i = _iv(el.Id)
            if i in ctx.spotted or u'ОТМ' in ctx.kinds.get(i, ()):
                continue
            p = xyz_elev_marks._bottom_point_fi(el)
            if p is None:
                continue
            try:
                tg = xyz_elev_marks.place(doc, view, el, None, p, 'R', None, dmap, None)
                _occ_mark(ctx, tg)
                ctx.add(u'Отметки низа оборудования' if _cat(el) == C_EQ else u'Отметки низа арматуры и др.')
            except Exception as ex:
                ctx.add(u'Ошибка отметки: ' + unicode(ex)[:50])
        t.Commit()
    except Exception:
        t.RollBack()
        raise


def _is_round(d):
    p = d.get_Parameter(BuiltInParameter.RBS_CURVE_DIAMETER_PARAM)
    return p is not None and p.HasValue and p.AsDouble() > 0


def _bottom_edge(ctx, d):
    """Нижнее ребро прямоугольного воздуховода, ближнее к зрителю (так ставит инженер:
    ссылка «…:9:LINEAR» / «…:18:LINEAR»). Возвращает (Reference, Curve) или (None, None)."""
    opt = Options()
    opt.ComputeReferences = True
    opt.DetailLevel = ViewDetailLevel.Fine
    axis = d.Location.Curve
    ad = (axis.GetEndPoint(1) - axis.GetEndPoint(0)).Normalize()
    cands = []
    for g in d.get_Geometry(opt):
        if not isinstance(g, Solid):
            continue
        for e in g.Edges:
            c = e.AsCurve()
            if not isinstance(c, Line) or e.Reference is None:
                continue
            if abs(c.Direction.DotProduct(ad)) < 0.99:
                continue
            m = c.Evaluate(0.5, True)
            cands.append((m.Z, -m.DotProduct(ctx.view.ViewDirection), e.Reference, c))
    if not cands:
        return None, None
    zmin = min(x[0] for x in cands)
    low = [x for x in cands if x[0] - zmin < 0.005]
    low.sort(key=lambda x: x[1])
    return low[0][2], low[0][3]


def _place_spot(ctx, d, t_dn, t_up):
    """Высотная отметка Revit, как у инженера (проверено по его исправлениям 09.10):
    прямоугольный воздуховод - НИЗ (нижнее ребро, ближнее к зрителю), круглый - ОСЬ;
    плечо выноски в самой точке, горизонтальная полка 3-13 мм, текст у конца полки
    под ней («Вниз») или над ней («Вверх»). Место - без наложений; нет места - False."""
    doc, view, mm = ctx.doc, ctx.view, ctx.mm
    if _is_round(d):
        ref = Reference.ParseFromStableRepresentation(doc, d.UniqueId + u":0:LINEAR")
        crv = d.Location.Curve
    else:
        ref, crv = _bottom_edge(ctx, d)
        if ref is None:
            return False
    best = None
    for tpar in (0.5, 0.35, 0.65, 0.2, 0.8):
        p = crv.Evaluate(tpar, True)
        au, av = ctx.uv(p)
        for L in (3.0, 5.0, 8.0, 12.0):
            for su in (-1, 1):
                for up, sv in ((False, -1), (True, 1)):
                    eu = au + su * L
                    tu, tv = eu + su * 7.0, av + sv * 5.3
                    box = (tu - 8.5, tv - 2.8, tu + 8.5, tv + 2.8)
                    c = ctx.occ.box_cost(box)
                    if c >= HARD:
                        continue
                    c += ctx.occ.lead_cost([(au, av), (eu, av)]) + L * 0.5 + (0 if not up else 1.0) \
                        + abs(tpar - 0.5) * 6.0
                    if best is None or c < best[0]:
                        best = (c, p, su, L, up, box, (au, av), (eu, av))
    if best is None or best[0] >= 2000.0:
        return False
    c, p, su, L, up, box, a, b = best
    end = p + ctx.R * (su * L * mm)
    sp = doc.Create.NewSpotElevation(view, ref, p, p, end, p, True)
    typ = t_up if up else t_dn
    if typ is not None:
        sp.ChangeTypeId(typ.Id)
    ctx.occ.add_box(box)
    ctx.occ.add_seg(a, b)
    return True


def _occ_mark(ctx, tag):
    if tag is None:
        return
    try:
        u, v = ctx.uv(tag.TagHeadPosition)
        nm = tag.Document.GetElement(tag.GetTypeId()).get_Parameter(BuiltInParameter.ALL_MODEL_TYPE_NAME).AsString()
        left, up = u'влево' in nm, u'вверху' in nm
        u0, u1 = (u - 15, u + 1) if left else (u - 1, u + 15)
        v0, v1 = (v - 1, v + 6) if up else (v - 6, v + 1)
        ctx.occ.add_box((u0, v0, u1, v1))
    except Exception:
        pass


def step_transp(ctx, elems):
    """«#прозрачно#» в «Комментарии» выделенных (если пусто) + фильтр db_Прозрачно_50 на виде.
    Если все выделенные уже помечены - метка снимается (переключатель)."""
    doc, view = ctx.doc, ctx.view

    def cm(e):
        p = e.get_Parameter(BuiltInParameter.ALL_MODEL_INSTANCE_COMMENTS)
        return p
    marked = [e for e in elems if cm(e) is not None and (cm(e).AsString() or u'') == MARK]
    t = Transaction(doc, u"Полупрозрачность 50 %")
    t.Start()
    try:
        if elems and len(marked) == len(elems):
            for e in marked:
                cm(e).Set(u'')
            ctx.add(u'Снята полупрозрачность', len(marked))
        else:
            busy = 0
            for e in elems:
                p = cm(e)
                if p is None or p.IsReadOnly:
                    continue
                if p.AsString():
                    if p.AsString() != MARK:
                        busy += 1
                    continue
                p.Set(MARK)
                ctx.add(u'Помечено полупрозрачными')
            if busy:
                ctx.add(u'Пропущено: «Комментарии» уже заполнены', busy)
        f = _ensure_filter(doc)
        if not view.IsFilterApplied(f.Id):
            view.AddFilter(f.Id)
        ogs = OverrideGraphicSettings()
        ogs.SetSurfaceTransparency(50)
        view.SetFilterOverrides(f.Id, ogs)
        view.SetFilterVisibility(f.Id, True)
        t.Commit()
    except Exception:
        t.RollBack()
        raise


def _ensure_filter(doc):
    for f in FilteredElementCollector(doc).OfClass(ParameterFilterElement):
        if f.Name == FILTER_TR:
            return f
    from System.Collections.Generic import List
    cats = List[ElementId]()
    for b in (BIC.OST_DuctCurves, BIC.OST_DuctFitting, BIC.OST_DuctAccessory, BIC.OST_MechanicalEquipment,
              BIC.OST_DuctTerminal, BIC.OST_FlexDuctCurves, BIC.OST_PipeCurves, BIC.OST_PipeFitting,
              BIC.OST_PipeAccessory):
        cats.Add(ElementId(b))
    pid = ElementId(BuiltInParameter.ALL_MODEL_INSTANCE_COMMENTS)
    try:
        rule = ParameterFilterRuleFactory.CreateContainsRule(pid, MARK)
    except TypeError:
        rule = ParameterFilterRuleFactory.CreateContainsRule(pid, MARK, False)
    rules = List[FilterRule]()
    rules.Add(rule)
    return ParameterFilterElement.Create(doc, FILTER_TR, cats, ElementParameterFilter(rules))


# ================================================================== вход
def run_tidy(doc, tags):
    """Переразложить готовые марки (компактно, колонками) - для исправления."""
    view = doc.ActiveView
    ids = [_iv(t.Id) for t in tags]
    ctx = Ctx(doc, view, None, True, exclude=ids)
    items = []
    for t in tags:
        el = doc.GetElement(list(t.GetTaggedLocalElementIds())[0])
        a = None
        try:
            for r in t.GetTaggedReferences():
                a = t.GetLeaderEnd(r)
                break
        except Exception:
            a = None
        anchors = anchors_of(ctx, el) or ([a] if a is not None else [])
        items.append((t, el, anchors, u'Переразложено марок'))
    tidy(ctx, items, u"Переразложить марки")
    return ctx.report(u"Переразложить марки"), ctx.skipped


ELEV_CATS = ('OST_PipeCurves', 'OST_DuctCurves', 'OST_MechanicalEquipment', 'OST_PipeAccessory',
             'OST_DuctAccessory', 'OST_DuctTerminal', 'OST_PlumbingFixtures', 'OST_Sprinklers',
             'OST_FlexDuctCurves')


def elev_candidates(doc, view, elems=None):
    """Кандидаты для окна «Высотные отметки: для каких объектов?» — выделенное или
    всё на виде из категорий ELEV_CATS (без вложенных семейств)."""
    from System.Collections.Generic import List
    cats = [int(getattr(BIC, n)) for n in ELEV_CATS if hasattr(BIC, n)]
    if elems:
        src = elems
    else:
        mf = ElementMulticategoryFilter(List[BuiltInCategory]([getattr(BIC, n) for n in ELEV_CATS if hasattr(BIC, n)]))
        src = FilteredElementCollector(doc, view.Id).WherePasses(mf).WhereElementIsNotElementType()
    out = []
    for e in src:
        if e.Category is None or _cat(e) not in cats:
            continue
        if getattr(e, 'SuperComponent', None) is not None:
            continue
        out.append(e.Id)
    return out


def elev_default(key, el):
    """Что отмечено в окне сразу: трубы, воздуховоды, оборудование (как было раньше)."""
    return _cat(el) in (C_PIPE, C_DUCT, C_EQ)


def run_step(doc, uidoc, step, elems, strict=False, offset_mm=0.0, pick=None):
    view = doc.ActiveView
    if not isinstance(view, View3D):
        return u"Нужен 3D-вид (схема).", []
    need_occ = step not in ('explode', 'transp', 'paths', 'paths_reset', 'addto', 'fan', 'eqtags')
    ctx = Ctx(doc, view, elems, need_occ)
    title = dict(STEPS)[step]
    if step == 'explode':
        step_explode(ctx, elems or [], offset_mm)
    elif step == 'paths':
        step_paths(ctx)
    elif step == 'paths_reset':
        step_paths(ctx, reset=True)
    elif step == 'addto':
        step_addto(ctx, uidoc, elems or [])
    elif step == 'elev':
        step_elev(ctx, set(_iv(i) for i in pick) if pick is not None else None)
    elif step == 'xeq':
        step_xeq(ctx)
    elif step == 'vrf':
        # порядок VRF (стандарт, раздел 0): разнос уже сделан → отметки → оборудование →
        # разветвители и трубы. Каждый шаг — новый Ctx: раскладка обходит уже поставленное.
        parts = []
        for name, fn in ((u'Высотные отметки', lambda c: step_elev(c, None)),
                         (u'Оборудование', step_xeq),
                         (u'Разветвители и трубы', step_pipe_tags)):
            c = ctx if not parts else Ctx(doc, view, elems, True)
            fn(c)
            parts.append(c.report(name))
            if c is not ctx:
                ctx.skipped.extend(c.skipped)
                ctx.forced.extend(c.forced)
        return u'\n\n'.join(parts), ctx.skipped + ctx.forced
    elif step == 'ptags':
        step_pipe_tags(ctx)
    elif step == 'sys':
        step_sys(ctx)
    elif step == 'size':
        ctx.with_sizes = True
        step_sys(ctx)
    elif step == 'transp':
        step_transp(ctx, elems or [])
    elif step in ('fan', 'eqtags'):
        # схемы отопления с коллекторами (01.11.2026): веер лучей, марки приборов
        import sys as _sys
        _sys.modules.pop('dress_fan', None)
        import dress_fan
        ctx.notes = []
        keep = dress_fan.run(_sys.modules[__name__], ctx, step, elems or [], offset_mm)
        rep = ctx.report(title)
        if ctx.notes:
            rep += u"\n" + u"\n".join(u"  " + x for x in ctx.notes)
        return rep, list(keep)
    else:
        step_tags(ctx, step, strict)
    if ctx.forced:
        ctx.add(u'Поставлено поверх других (чистого места нет, выделены — поправьте)', len(ctx.forced))
    return ctx.report(title), ctx.skipped + ctx.forced
