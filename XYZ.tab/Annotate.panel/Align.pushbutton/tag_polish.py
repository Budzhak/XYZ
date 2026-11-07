# -*- coding: utf-8 -*-
"""
«Доводка марок: полки по тексту, прямые выноски в обход» — команда кнопки «По красоте».

Перенесено 01.11.2026 из разовой доводки марок на плане вентиляции Глаголево
(%TEMP%\\zb_tags\\zb_core6/7/8.py, 31.10.2026). Ставится ПОСЛЕ «Развести наложенные
марки» (declutter_tags) и чинит то, что осталось:
  1) марки-полки семейства «ADSK_M_Оборудование» (типы ADSK_Марка_15/25/30/40/50):
     тип с длиной полки по длине текста (полка не длиннее надписи), проверка по рамке;
  2) «плохие» марки — на воздуховоде/трубе, на элементе, на аннотации, на другой
     марке, косая выноска, выноска длиннее 20 мм, выноска через чужую марку —
     переставляются: перебор мест вдоль оси своего элемента (шаг 1 мм листа)
     с прямой выноской (вертикаль/горизонталь), затем с изломом под прямым
     углом («Г»). Цена: длина выноски, пересечения с трубами, элементами,
     аннотациями, чужими выносками; чужие выноски под рамкой. Для каждой марки
     примеряются лучшие варианты и берётся тот, где реально меньше проблем;
     если лучше не стало — марка остаётся как была;
  3) второй круг для оставшихся — выноска до 70 мм, поиск шире (+80 мм).
Где: выделенные марки; ничего не выделено — все марки вида (с вопросом).
Всё — одна группа транзакций (один Ctrl+Z). Оставшиеся плохие марки выделяются.
Проверено на плане (вид-план 1:50/1:100). На 3D-виде НЕ работает: рамки марок и
элементов берутся по габариту, а на аксонометрии габарит намного больше надписи
(проба 01.11.2026 на копии схемы листа 23: 136 из 146 марок «с замечаниями»,
отметки уехали на длинные косые выноски) — на 3D-виде команда отказывается;
для схем — «Оформить взрыв-схему по шагам».

Вызов из script.py:  tag_polish.run(doc, uidoc, tags)
Ядро (нужна открытая транзакция): polish(doc, view, targets) -> (moved, left, shelves)
"""
import math
import time
from Autodesk.Revit.DB import *

TITLE = u"Доводка марок"
GAP = 1.0          # мм листа: зазор марки до препятствий
STEP = 1.0         # мм листа: шаг сетки
MAXL = 25.0        # мм листа: самая длинная выноска (первый круг)
MAXL2 = 70.0       # второй круг — длинная выноска в обход
WIDE = 80.0        # второй круг — поиск шире, мм листа
LONG_BAD = 20.0    # выноска длиннее — марка «уехала»
TRY_TOP = 12       # сколько лучших вариантов примерять по-настоящему

CURVE_BICS = [BuiltInCategory.OST_DuctCurves, BuiltInCategory.OST_PipeCurves,
              BuiltInCategory.OST_FlexDuctCurves, BuiltInCategory.OST_FlexPipeCurves]
BOX_BICS = [BuiltInCategory.OST_DuctFitting, BuiltInCategory.OST_DuctAccessory,
            BuiltInCategory.OST_DuctTerminal, BuiltInCategory.OST_MechanicalEquipment,
            BuiltInCategory.OST_PipeFitting, BuiltInCategory.OST_PipeAccessory,
            BuiltInCategory.OST_PlumbingFixtures, BuiltInCategory.OST_Sprinklers,
            BuiltInCategory.OST_MechanicalControlDevices, BuiltInCategory.OST_FlexDuctCurves,
            BuiltInCategory.OST_FlexPipeCurves]


def iv(eid):
    try:
        return eid.Value
    except Exception:
        return eid.IntegerValue


class Fr(object):
    def __init__(self, view):
        self.R = view.RightDirection
        self.U = view.UpDirection
        self.N = self.R.CrossProduct(self.U)
        self.mm = view.Scale / 304.8

    def uv(self, p):
        return (p.DotProduct(self.R), p.DotProduct(self.U))

    def xyz(self, u, v, zref):
        return self.R * u + self.U * v + self.N * zref.DotProduct(self.N)

    def box(self, bb):
        if bb is None:
            return None
        tr = bb.Transform
        us, vs = [], []
        for x in (bb.Min.X, bb.Max.X):
            for y in (bb.Min.Y, bb.Max.Y):
                for z in (bb.Min.Z, bb.Max.Z):
                    u, v = self.uv(tr.OfPoint(XYZ(x, y, z)))
                    us.append(u)
                    vs.append(v)
        return [min(us), min(vs), max(us), max(vs)]


# ---------------- геометрия ----------------
def ov(a, b, g):
    return a[0] < b[2] + g and b[0] < a[2] + g and a[1] < b[3] + g and b[1] < a[3] + g


def seg_box(p, q, b, pad):
    x0, y0 = p
    dx, dy = q[0] - x0, q[1] - y0
    t0, t1 = 0.0, 1.0
    for pp, qq in ((-dx, x0 - (b[0] - pad)), (dx, (b[2] + pad) - x0),
                   (-dy, y0 - (b[1] - pad)), (dy, (b[3] + pad) - y0)):
        if abs(pp) < 1e-12:
            if qq < 0:
                return False
            continue
        r = qq / pp
        if pp < 0:
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


def pt_seg(p, a, b):
    dx, dy = b[0] - a[0], b[1] - a[1]
    l2 = dx * dx + dy * dy
    if l2 < 1e-12:
        return math.hypot(p[0] - a[0], p[1] - a[1])
    t = max(0.0, min(1.0, ((p[0] - a[0]) * dx + (p[1] - a[1]) * dy) / l2))
    return math.hypot(p[0] - a[0] - t * dx, p[1] - a[1] - t * dy)


def caps_box(a, b, r, bx):
    """капсула (отрезок a-b, радиус r) пересекает прямоугольник bx"""
    if seg_box(a, b, bx, r * 0.7071):
        if seg_box(a, b, bx, 0):
            return True
        # уточнение: расстояние от углов
        for c in ((bx[0], bx[1]), (bx[0], bx[3]), (bx[2], bx[1]), (bx[2], bx[3])):
            if pt_seg(c, a, b) < r:
                return True
        for p in (a, b):
            cu = min(max(p[0], bx[0]), bx[2])
            cv = min(max(p[1], bx[1]), bx[3])
            if math.hypot(p[0] - cu, p[1] - cv) < r:
                return True
        # отрезок проходит рядом со стороной
        if seg_box(a, b, bx, r):
            # параллельный стороне отрезок на расстоянии < r
            for c in ((bx[0], bx[1]), (bx[2], bx[3])):
                pass
            mu = [(bx[0] + bx[2]) / 2.0, (bx[1] + bx[3]) / 2.0]
            hw, hh = (bx[2] - bx[0]) / 2.0, (bx[3] - bx[1]) / 2.0
            n = 24
            for k in range(n + 1):
                t = k / float(n)
                x, y = a[0] + (b[0] - a[0]) * t, a[1] + (b[1] - a[1]) * t
                dx = max(abs(x - mu[0]) - hw, 0.0)
                dy = max(abs(y - mu[1]) - hh, 0.0)
                if math.hypot(dx, dy) < r:
                    return True
        return False
    return False


def seg_cross(p1, p2, p3, p4):
    def ccw(a, b, c):
        return (b[0] - a[0]) * (c[1] - a[1]) - (b[1] - a[1]) * (c[0] - a[0])
    d1, d2 = ccw(p3, p4, p1), ccw(p3, p4, p2)
    d3, d4 = ccw(p1, p2, p3), ccw(p1, p2, p4)
    return (d1 * d2 < 0) and (d3 * d4 < 0)


def clip_in(p, h, b):
    """точка входа отрезка p->h в рамку b (или h)"""
    if b[0] <= p[0] <= b[2] and b[1] <= p[1] <= b[3]:
        return p
    lo, hi = 0.0, 1.0
    for _ in range(30):
        m = (lo + hi) / 2.0
        x, y = p[0] + (h[0] - p[0]) * m, p[1] + (h[1] - p[1]) * m
        if b[0] <= x <= b[2] and b[1] <= y <= b[3]:
            hi = m
        else:
            lo = m
    return (p[0] + (h[0] - p[0]) * hi, p[1] + (h[1] - p[1]) * hi)


def edge_pt(p, b):
    return (min(max(p[0], b[0]), b[2]), min(max(p[1], b[1]), b[3]))


# ---------------- сбор ----------------
def half_width(e, fr):
    r = 0.0
    for bip in (BuiltInParameter.RBS_PIPE_OUTER_DIAMETER, BuiltInParameter.RBS_CURVE_DIAMETER_PARAM,
                BuiltInParameter.RBS_CURVE_WIDTH_PARAM):
        try:
            p = e.get_Parameter(bip)
            if p is not None and p.HasValue and p.AsDouble() > 0:
                r = p.AsDouble() / 2.0
                break
        except Exception:
            pass
    try:
        p = e.get_Parameter(BuiltInParameter.RBS_REFERENCE_INSULATION_THICKNESS)
        if p is not None and p.HasValue:
            r += p.AsDouble()
    except Exception:
        pass
    return max(r, 0.5 * fr.mm)


def collect_model(doc, view, fr):
    curves, boxes = [], []
    lim = 150 * fr.mm
    for bic in CURVE_BICS[:2]:
        for e in FilteredElementCollector(doc, view.Id).OfCategory(bic).WhereElementIsNotElementType():
            loc = e.Location
            if not isinstance(loc, LocationCurve):
                continue
            c = loc.Curve
            curves.append((iv(e.Id), fr.uv(c.GetEndPoint(0)), fr.uv(c.GetEndPoint(1)), half_width(e, fr)))
    for bic in BOX_BICS:
        try:
            col = FilteredElementCollector(doc, view.Id).OfCategory(bic).WhereElementIsNotElementType()
        except Exception:
            continue
        for e in col:
            if isinstance(e, ElementType):
                continue
            b = fr.box(e.get_BoundingBox(view))
            if b is None or (b[2] - b[0]) > lim or (b[3] - b[1]) > lim:
                continue
            boxes.append((iv(e.Id), b))
    return curves, boxes


def collect_annot(doc, view, fr, tag_ids):
    out = []
    lim = 60 * fr.mm
    for e in FilteredElementCollector(doc, view.Id).WhereElementIsNotElementType():
        if iv(e.Id) in tag_ids:
            continue
        if not isinstance(e, (SpatialElementTag, TextNote, Dimension, IndependentTag)):
            continue
        b = fr.box(e.get_BoundingBox(view))
        if b is None:
            continue
        if isinstance(e, Dimension) and not isinstance(e, SpotDimension):
            if (b[2] - b[0]) > lim and (b[3] - b[1]) > lim:
                continue
        out.append((iv(e.Id), b))
    return out


def measure(doc, view, fr, tags):
    """рамка текста марки относительно головы (выноску прижимаем к голове)"""
    rel = {}
    tiny = 0.05 * fr.mm
    heads = dict((iv(t.Id), t.TagHeadPosition) for t in tags)
    st = SubTransaction(doc)
    st.Start()
    try:
        for t in tags:
            try:
                h = t.TagHeadPosition
                if not t.HasLeader:
                    t.HasLeader = True
                if t.LeaderEndCondition != LeaderEndCondition.Free:
                    t.LeaderEndCondition = LeaderEndCondition.Free
                for r in t.GetTaggedReferences():
                    t.SetLeaderEnd(r, h + fr.R * tiny)
                    try:
                        if t.HasLeaderElbow(r):
                            t.SetLeaderElbow(r, h)
                    except Exception:
                        pass
            except Exception:
                pass
        doc.Regenerate()
        for t in tags:
            b = fr.box(t.get_BoundingBox(view))
            if b is None:
                continue
            hu, hv = fr.uv(heads[iv(t.Id)])
            rel[iv(t.Id)] = (b[0] - hu, b[1] - hv, b[2] - hu, b[3] - hv)
    finally:
        st.RollBack()
    # марка-полка (оборудование): текст над полкой, ниже полки пусто - рамку
    # обрезаем на 1 мм ниже головы (полка проходит через голову)
    for t in tags:
        k = iv(t.Id)
        r = rel.get(k)
        if r is not None and is_shelf(doc, t) and r[1] < -1.0 * fr.mm:
            rel[k] = (r[0], -1.0 * fr.mm, r[2], r[3])
    return rel


SHELF_FAM = u"ADSK_M_Оборудование"
SHELF_PREFIX = u"ADSK_Марка_"
CHAR_MM = 1.6       # ширина символа марки на листе, мм (замер: «16КП-04» = 11,8 мм; проверка по рамке)


def is_shelf(doc, t):
    s = doc.GetElement(t.GetTypeId())
    return s is not None and s.FamilyName == SHELF_FAM


def shelf_types(doc, sym):
    out = []
    for sid in sym.Family.GetFamilySymbolIds():
        s = doc.GetElement(sid)
        nm = Element.Name.GetValue(s)
        if not nm.startswith(SHELF_PREFIX):
            continue
        p = s.LookupParameter(u"Длина полки")
        if p is None:
            continue
        out.append((p.AsDouble() * 304.8, sid, nm))
    out.sort(key=lambda x: x[0])
    return out


def shorten_shelves(doc, view, fr, tags):
    """марки ADSK_Марка_50: полка по длине текста (типоразмер того же
    семейства ADSK_Марка_15/25/30/40/50 - текст марки тот же)"""
    changed = {}
    for t in tags:
        sym = doc.GetElement(t.GetTypeId())
        if sym is None or sym.FamilyName != SHELF_FAM:
            continue
        if not Element.Name.GetValue(sym).startswith(SHELF_PREFIX):
            continue
        txt = t.TagText or u""
        need = len(txt) * CHAR_MM + 2.0
        types = shelf_types(doc, sym)
        pick = None
        for ln, sid, nm in types:
            if ln >= need:
                pick = (ln, sid, nm)
                break
        if pick is None or iv(pick[1]) == iv(sym.Id):
            continue
        old = Element.Name.GetValue(sym)
        t.ChangeTypeId(pick[1])
        changed[iv(t.Id)] = (old, pick[2], types)
    if not changed:
        return changed
    doc.Regenerate()
    # проверка: текст не шире полки (иначе - следующий типоразмер)
    for _ in range(3):
        rel = measure(doc, view, fr, [doc.GetElement(ElementId(i)) for i in changed])
        bumped = False
        for i, (old, nm, types) in changed.items():
            r = rel.get(i)
            t = doc.GetElement(ElementId(i))
            cur = Element.Name.GetValue(doc.GetElement(t.GetTypeId()))
            ln = [x for x in types if x[2] == cur][0][0]
            w = (r[2] - r[0]) / fr.mm if r else 0
            if w > ln + 0.5:
                nxt = [x for x in types if x[0] > ln]
                if nxt:
                    t.ChangeTypeId(nxt[0][1])
                    changed[i] = (old, nxt[0][2], types)
                    bumped = True
        if not bumped:
            break
        doc.Regenerate()
    return changed


def host_of(doc, t):
    for i in t.GetTaggedLocalElementIds():
        e = doc.GetElement(i)
        if e is not None:
            return e
    return None


def leader_info(doc, t, fr):
    """(конец, излом или None) в uv; None если без выноски"""
    if not t.HasLeader:
        return None
    ref = None
    for r in t.GetTaggedReferences():
        ref = r
        break
    end = None
    try:
        end = fr.uv(t.GetLeaderEnd(ref))
    except Exception:
        end = None
    if end is None:
        h = host_of(doc, t)
        hp = t.TagHeadPosition
        if h is not None and isinstance(h.Location, LocationCurve):
            try:
                end = fr.uv(h.Location.Curve.Project(hp).XYZPoint)
            except Exception:
                end = None
        if end is None and h is not None:
            try:
                end = fr.uv(h.Location.Point)
            except Exception:
                end = fr.uv(hp)
    elb = None
    try:
        if t.HasLeaderElbow(ref):
            elb = fr.uv(t.GetLeaderElbow(ref))
    except Exception:
        pass
    return end, elb


# ---------------- оценка ----------------
class World(object):
    def __init__(self, doc, view, fr, tags, rel):
        self.doc, self.view, self.fr = doc, view, fr
        self.tags = dict((iv(t.Id), t) for t in tags)
        self.rel = rel
        self.curves, self.boxes = collect_model(doc, view, fr)
        self.annot = collect_annot(doc, view, fr, set(self.tags.keys()))
        cb = view.CropBox
        self.crop = fr.box(cb) if view.CropBoxActive else None
        self.tbox = {}
        self.lead = {}
        self.host = {}
        for i in self.tags:
            h = host_of(doc, self.tags[i])
            self.host[i] = iv(h.Id) if h is not None else -1
            self.refresh(i)

    def refresh(self, i):
        t = self.tags[i]
        if i not in self.rel:
            return
        hu, hv = self.fr.uv(t.TagHeadPosition)
        r = self.rel[i]
        self.tbox[i] = [hu + r[0], hv + r[1], hu + r[2], hv + r[3]]
        li = leader_info(self.doc, t, self.fr)
        if li is None:
            self.lead[i] = None
        else:
            end, elb = li
            self.lead[i] = (end, elb, (hu, hv))

    def lead_segs(self, i, to_head=False):
        """отрезки выноски: до головы (to_head) или до края рамки"""
        ld = self.lead.get(i)
        if ld is None:
            return []
        end, elb, h = ld
        b = self.tbox[i]
        if elb is not None and math.hypot(elb[0] - end[0], elb[1] - end[1]) > 1e-6 and \
                math.hypot(elb[0] - h[0], elb[1] - h[1]) > 1e-6 and \
                pt_seg(elb, end, h) > 0.3 * self.fr.mm:
            return [(end, elb), (elb, h if to_head else clip_in(elb, h, b))]
        return [(end, h if to_head else clip_in(end, h, b))]

    def problems(self, i):
        """список причин, почему марка плохая"""
        fr = self.fr
        g = 0.3 * fr.mm
        b = self.tbox.get(i)
        if b is None:
            return []
        hid = self.host.get(i)
        bs = [b[0] + g, b[1] + g, b[2] - g, b[3] - g]
        out = []
        for cid, a, c, r in self.curves:
            if caps_box(a, c, r, bs):
                out.append(u"на воздуховоде/трубе %d" % cid)
        for eid, bb in self.boxes:
            if eid != hid and ov(bs, bb, 0):
                out.append(u"на элементе %d" % eid)
        for eid, bb in self.annot:
            if ov(bs, bb, 0):
                out.append(u"на аннотации %d" % eid)
        for j, bb in self.tbox.items():
            if j != i and ov(bs, bb, 0):
                out.append(u"на марке %d" % j)
        ld = self.lead.get(i)
        if ld is not None:
            tol = 0.4 * fr.mm
            for p, q in self.lead_segs(i, True):
                if abs(p[0] - q[0]) > tol and abs(p[1] - q[1]) > tol:
                    out.append(u"косая выноска")
                    break
            segs = self.lead_segs(i)
            ln = sum(math.hypot(q[0] - p[0], q[1] - p[1]) for p, q in segs) / fr.mm
            if ln > LONG_BAD:
                out.append(u"длинная выноска %.0f мм" % ln)
            for j, bb in self.tbox.items():
                if j == i:
                    continue
                for p, q in segs:
                    if seg_box(p, q, bb, -g):
                        out.append(u"выноска через марку %d" % j)
                        break
        return out

    # ---------- кандидаты ----------
    def prepare(self, i, cu, cv, rad):
        """препятствия вокруг точки (ускорение перебора)"""
        def near(b):
            return b[2] > cu - rad and b[0] < cu + rad and b[3] > cv - rad and b[1] < cv + rad
        self.l_curves = [x for x in self.curves
                         if near([min(x[1][0], x[2][0]) - x[3], min(x[1][1], x[2][1]) - x[3],
                                  max(x[1][0], x[2][0]) + x[3], max(x[1][1], x[2][1]) + x[3]])]
        self.l_boxes = [x for x in self.boxes if near(x[1])]
        self.l_annot = [x for x in self.annot if near(x[1])]
        self.l_tags = [(j, b) for j, b in self.tbox.items() if j != i and near(b)]
        segs = []
        for j in self.tbox:
            if j == i:
                continue
            for p, q in self.lead_segs(j):
                if near([min(p[0], q[0]), min(p[1], q[1]), max(p[0], q[0]), max(p[1], q[1])]):
                    segs.append((p, q))
        self.l_leads = segs

    def free_box(self, b):
        g = GAP * self.fr.mm
        bx = [b[0] - g, b[1] - g, b[2] + g, b[3] + g]
        if self.crop is not None:
            c = self.crop
            if b[0] < c[0] or b[1] < c[1] or b[2] > c[2] or b[3] > c[3]:
                return False
        for j, bb in self.l_tags:
            if ov(bx, bb, 0):
                return False
        for eid, bb in self.l_annot:
            if ov(bx, bb, 0):
                return False
        for eid, bb in self.l_boxes:
            if ov(bx, bb, 0):
                return False
        for cid, a, c, r in self.l_curves:
            if caps_box(a, c, r, bx):
                return False
        return True

    def box_pen(self, b):
        """штраф: чужие выноски под рамкой"""
        n = 0.0
        for p, q in self.l_leads:
            if seg_box(p, q, b, 0):
                n += 15
        return n

    def lead_cost(self, segs, hid):
        """цена выноски; None - запрещена (через чужую марку)"""
        fr = self.fr
        n = 0.0
        for p, q in segs:
            for j, bb in self.l_tags:
                if seg_box(p, q, bb, 0.3 * fr.mm):
                    return None
            for eid, bb in self.l_annot:
                if seg_box(p, q, bb, -0.5 * fr.mm):
                    n += 6
            for eid, bb in self.l_boxes:
                if eid != hid and seg_box(p, q, bb, -0.3 * fr.mm):
                    n += 3
            for cid, a, c, r in self.l_curves:
                if cid == hid:
                    continue
                if seg_cross(p, q, a, c):
                    n += 4
                # выноска вдоль воздуховода (поверх него)
                ln = math.hypot(q[0] - p[0], q[1] - p[1]) / fr.mm
                if ln > 2:
                    k = int(ln / 2) + 1
                    inside = 0
                    for m in range(k + 1):
                        x = (p[0] + (q[0] - p[0]) * m / float(k), p[1] + (q[1] - p[1]) * m / float(k))
                        if pt_seg(x, a, c) < r:
                            inside += 1
                    if inside > 2:
                        n += 2.0 * inside * ln / (k + 1)
            for a, c in self.l_leads:
                if seg_cross(p, q, a, c):
                    n += 8
        return n

    def head_for(self, r, O, D, d):
        """голова марки, ближний край рамки на расстоянии d от O по оси D,
        голова на линии выноски"""
        if D[0] > 0.5:
            return (O[0] + d - r[0], O[1])
        if D[0] < -0.5:
            return (O[0] - d - r[2], O[1])
        if D[1] > 0.5:
            return (O[0], O[1] + d - r[1])
        return (O[0], O[1] - d - r[3])

    def candidates(self, i):
        fr = self.fr
        mm = fr.mm
        t = self.tags[i]
        h = host_of(self.doc, t)
        r = self.rel[i]
        if h is None:
            return []
        hid = iv(h.Id)
        shelf = is_shelf(self.doc, t)        # марка-полка: выноска только к концу полки
        AX = [(1, 0), (-1, 0), (0, 1), (0, -1)]
        anchors = []   # (E uv, E xyz, [(D, clear)])
        loc = h.Location
        if isinstance(loc, LocationCurve) and isinstance(loc.Curve, Line):
            c = loc.Curve
            a3, b3 = c.GetEndPoint(0), c.GetEndPoint(1)
            a, b = fr.uv(a3), fr.uv(b3)
            ln = math.hypot(b[0] - a[0], b[1] - a[1])
            hw = half_width(h, fr)
            if ln < 1e-6:
                return []
            du, dv = (b[0] - a[0]) / ln, (b[1] - a[1]) / ln
            if abs(du) > 0.999:
                dirs = [((0, 1), hw), ((0, -1), hw)]
            elif abs(dv) > 0.999:
                dirs = [((1, 0), hw), ((-1, 0), hw)]
            else:
                return []
            k = int(ln / (STEP * mm))
            for s in range(1, max(k, 1)):
                tt = s * STEP * mm
                if tt < hw or tt > ln - hw:
                    continue
                P = (a[0] + du * tt, a[1] + dv * tt)
                if self.crop is not None:
                    cc = self.crop
                    if not (cc[0] < P[0] < cc[2] and cc[1] < P[1] < cc[3]):
                        continue
                anchors.append((P, a3 + (b3 - a3) * (tt / ln), dirs))
            cu, cv = (a[0] + b[0]) / 2.0, (a[1] + b[1]) / 2.0
            rad = ln / 2.0 + 80 * mm
        else:
            hb = fr.box(h.get_BoundingBox(self.view))
            if hb is None:
                return []
            try:
                p3 = h.Location.Point
            except Exception:
                p3 = t.TagHeadPosition
            cu, cv = (hb[0] + hb[2]) / 2.0, (hb[1] + hb[3]) / 2.0
            rad = 130 * mm
            E = (cu, cv)
            anchors.append((E, fr.xyz(cu, cv, p3),
                            [((1, 0), hb[2] - cu), ((-1, 0), cu - hb[0]),
                             ((0, 1), hb[3] - cv), ((0, -1), cv - hb[1])]))
            for kk in range(1, 30):
                for sg in (1, -1):
                    vv = cv + sg * kk * STEP * mm
                    if hb[1] + 0.2 * (hb[3] - hb[1]) <= vv <= hb[3] - 0.2 * (hb[3] - hb[1]):
                        anchors.append(((cu, vv), fr.xyz(cu, vv, p3),
                                        [((1, 0), hb[2] - cu), ((-1, 0), cu - hb[0])]))
                    uu = cu + sg * kk * STEP * mm
                    if hb[0] + 0.2 * (hb[2] - hb[0]) <= uu <= hb[2] - 0.2 * (hb[2] - hb[0]):
                        anchors.append(((uu, cv), fr.xyz(uu, cv, p3),
                                        [((0, 1), hb[3] - cv), ((0, -1), cv - hb[1])]))
        self.prepare(i, cu, cv, rad)
        out = []
        g = GAP * mm
        maxl = MAXL
        # 1) прямая выноска
        for E, E3, dirs in anchors:
            for D, clear in dirs:
                if shelf and D[1] != 0:
                    continue
                d = clear + g
                while d <= clear + maxl * mm:
                    head = self.head_for(r, E, D, d)
                    bx = [head[0] + r[0], head[1] + r[1], head[0] + r[2], head[1] + r[3]]
                    if self.free_box(bx):
                        near = (E[0] + D[0] * d, E[1] + D[1] * d)
                        lc = self.lead_cost([(E, near)], hid)
                        if lc is not None:
                            ln = (d - clear) / mm
                            out.append((ln + max(0.0, ln - 12.0) + lc + self.box_pen(bx), head, E3, None, 'straight'))
                            break
                    d += STEP * mm
        out.sort(key=lambda x: x[0])
        if out and out[0][0] <= 4.0:
            return out
        # 2) выноска с изломом под прямым углом (Г)
        st = 1.5 * STEP * mm
        anch = anchors if len(anchors) < 40 else anchors[::2]
        for E, E3, dirs in anch:
            for D, clear in dirs:
                a = clear + g
                while a <= clear + maxl * mm:
                    el = (E[0] + D[0] * a, E[1] + D[1] * a)
                    for P in ((D[1], D[0]), (-D[1], -D[0])):
                        if shelf and P[1] != 0:
                            continue
                        bb = g
                        while bb <= maxl * mm:
                            head = self.head_for(r, el, P, bb)
                            bx = [head[0] + r[0], head[1] + r[1], head[0] + r[2], head[1] + r[3]]
                            if self.free_box(bx):
                                near = (el[0] + P[0] * bb, el[1] + P[1] * bb)
                                lc = self.lead_cost([(E, el), (el, near)], hid)
                                if lc is not None:
                                    ln = (a - clear) / mm + bb / mm
                                    out.append((ln + max(0.0, ln - 12.0) + 3.0 + lc + self.box_pen(bx),
                                                head, E3, el, 'L'))
                                break
                            bb += st
                    a += st
        out.sort(key=lambda x: x[0])
        return out


def place(doc, fr, t, head_uv, end3, elbow_uv):
    ref = None
    for r in t.GetTaggedReferences():
        ref = r
        break
    old = t.TagHeadPosition
    head = fr.xyz(head_uv[0], head_uv[1], old)
    t.HasLeader = True
    t.LeaderEndCondition = LeaderEndCondition.Attached
    doc.Regenerate()
    t.LeaderEndCondition = LeaderEndCondition.Free
    t.TagHeadPosition = head
    t.SetLeaderEnd(ref, end3)
    if elbow_uv is None:
        elb = end3 + (head - end3) * 0.5
    else:
        elb = fr.xyz(elbow_uv[0], elbow_uv[1], end3)
    try:
        t.SetLeaderElbow(ref, elb)
    except Exception:
        pass



# ---------------- доводка (из zb_core7.fix + zb_core8.fix8) ----------------
class WorldWide(World):
    """второй круг: поиск шире"""
    def prepare(self, i, cu, cv, rad):
        World.prepare(self, i, cu, cv, rad + WIDE * self.fr.mm)


def lead_len(W, i):
    return sum(math.hypot(q[0] - p[0], q[1] - p[1]) for p, q in W.lead_segs(i)) / W.fr.mm


def score(W, i, long_ok=False):
    """(серьёзные проблемы, пересечения выноски, длина), список причин"""
    pr = [p for p in W.problems(i) if not (long_ok and p.startswith(u"длинная выноска"))]
    hid = W.host.get(i)
    cross = []
    for p, q in W.lead_segs(i):
        for cid, a, c, r in W.curves:
            if cid != hid and seg_cross(p, q, a, c):
                cross.append(u"выноска через трубу/воздуховод %d" % cid)
        for eid, bb in W.boxes:
            if eid != hid and seg_box(p, q, bb, -0.3 * W.fr.mm):
                cross.append(u"выноска через элемент %d" % eid)
        for eid, bb in W.annot:
            if seg_box(p, q, bb, -0.5 * W.fr.mm):
                cross.append(u"выноска через аннотацию %d" % eid)
    b = W.tbox.get(i)
    if b is not None:
        for j in W.tags:
            if j == i:
                continue
            for p, q in W.lead_segs(j):
                if seg_box(p, q, b, -0.3 * W.fr.mm):
                    pr.append(u"чужая выноска %d под маркой" % j)
                    break
    return (len(pr), len(cross), lead_len(W, i)), pr + cross


def _snapshot(t):
    ref = list(t.GetTaggedReferences())[0]
    end = elb = None
    cond = has = None
    try:
        has = t.HasLeader
        cond = t.LeaderEndCondition
    except Exception:
        pass
    try:
        end = t.GetLeaderEnd(ref)
    except Exception:
        pass
    try:
        if t.HasLeaderElbow(ref):
            elb = t.GetLeaderElbow(ref)
    except Exception:
        pass
    return (t.TagHeadPosition, end, elb, has, cond)


def _restore(t, snap):
    ref = list(t.GetTaggedReferences())[0]
    head, end, elb, has, cond = snap
    try:
        if has is not None and t.HasLeader != has:
            t.HasLeader = has
        if cond is not None and has and t.LeaderEndCondition != cond:
            t.LeaderEndCondition = cond
    except Exception:
        pass
    t.TagHeadPosition = head
    try:
        if end is not None and t.LeaderEndCondition == LeaderEndCondition.Free:
            t.SetLeaderEnd(ref, end)
        if elb is not None:
            t.SetLeaderElbow(ref, elb)
    except Exception:
        pass


def _try_best(doc, W, fr, i, long_ok):
    """примерить лучшие варианты по-настоящему; оставить лучший, если лучше, чем было"""
    t = W.tags[i]
    s0, p0 = score(W, i, long_ok)
    cands = W.candidates(i)
    if not cands:
        return False
    best = (s0, None)
    snap = _snapshot(t)
    for cnd in cands[:TRY_TOP]:
        cost, head_uv, end3, elb, kind = cnd
        try:
            place(doc, fr, t, head_uv, end3, elb)
            doc.Regenerate()
        except Exception:
            continue
        W.refresh(i)
        s, p = score(W, i, long_ok)
        if s < best[0]:
            best = (s, cnd)
        if s[0] == 0 and s[1] == 0:
            break
    if best[1] is None:
        _restore(t, snap)
        doc.Regenerate()
        W.refresh(i)
        return False
    cost, head_uv, end3, elb, kind = best[1]
    place(doc, fr, t, head_uv, end3, elb)
    doc.Regenerate()
    W.refresh(i)
    return True


def polish(doc, view, targets, passes=3):
    """targets — марки, которые можно двигать (остальные марки вида — препятствия).
    Нужна открытая транзакция. Возвращает (moved {Id: раз}, left {Id: [причины]}, shelves {Id: (было, стало)})."""
    global MAXL
    fr = Fr(view)
    tags = [t for t in FilteredElementCollector(doc, view.Id).OfClass(IndependentTag)]
    tid = set(iv(t.Id) for t in targets)
    ch = shorten_shelves(doc, view, fr, [t for t in tags if iv(t.Id) in tid])
    shelves = dict((i, (v[0], v[1])) for i, v in ch.items())
    rel = measure(doc, view, fr, tags)
    moved, tried = {}, set()
    maxl0 = MAXL
    try:
        for rnd, (Wcls, maxl, long_ok) in enumerate(((World, maxl0, False), (WorldWide, MAXL2, True))):
            MAXL = maxl
            W = Wcls(doc, view, fr, tags, rel)
            for ps in range(passes if rnd == 0 else 1):
                bad = {}
                for i in W.tags:
                    if i not in tid:
                        continue
                    pr = W.problems(i)
                    if rnd:      # второй круг — только настоящие проблемы (длинная выноска — не повод)
                        pr = [x for x in pr if not x.startswith(u"длинная выноска")]
                    if pr:
                        bad[i] = pr
                if not bad:
                    break
                order = sorted(bad.keys(), key=lambda i: (i in tried, not is_shelf(doc, W.tags[i]), -len(bad[i])))
                any_move = False
                for i in order:
                    if _try_best(doc, W, fr, i, long_ok):
                        moved[i] = moved.get(i, 0) + 1
                        any_move = True
                    else:
                        tried.add(i)
                if not any_move:
                    break
    finally:
        MAXL = maxl0
    W = World(doc, view, fr, tags, rel)
    left = {}
    for i in W.tags:
        if i in tid:
            pr = W.problems(i)
            if pr:
                left[i] = pr
    return moved, left, shelves


def run(doc, uidoc, tags):
    import xyz_forms as forms
    view = doc.ActiveView
    if isinstance(view, View3D):
        # 01.11.2026: на 3D-схеме доводка портит раскладку (рамки по габариту неверны)
        forms.alert(u"Доводка марок работает только на планах и разрезах.\n\n"
                    u"На 3D-схеме марки раскладывают шаги «Оформить взрыв-схему по шагам» "
                    u"(«Марки приборов: прямая выноска поодаль» и др.).", title=TITLE)
        return
    targets = list(tags or [])
    if not targets:
        targets = [t for t in FilteredElementCollector(doc, view.Id).OfClass(IndependentTag)]
        if not targets:
            forms.alert(u"На виде нет марок.", title=TITLE)
            return
        if not forms.alert(u"Марки не выделены — довести все марки вида ({} шт.)?\n\n"
                           u"Сначала лучше «Развести наложенные марки», доводка — после.".format(len(targets)),
                           title=TITLE, yes=True, no=True):
            return
    t0 = time.time()
    tg = TransactionGroup(doc, TITLE)
    tg.Start()
    try:
        t = Transaction(doc, TITLE)
        t.Start()
        try:
            moved, left, shelves = polish(doc, view, targets)
            t.Commit()
        except Exception:
            t.RollBack()
            raise
        tg.Assimilate()
    except Exception:
        if tg.HasStarted():
            tg.RollBack()
        raise
    msg = u"Марок проверено: {}.\nПереставлено: {}.\nПолка по тексту (тип сменён): {}.".format(
        len(targets), len(moved), len(shelves))
    if left:
        why = {}
        for i, pr in left.items():
            for p in pr:
                k = p.rstrip(u"0123456789 ").replace(u" мм", u"")
                why[k] = why.get(k, 0) + 1
        msg += u"\n\nОсталось с замечаниями: {} (выделены, поправьте вручную):\n".format(len(left))
        msg += u"\n".join(u"  {} — {}".format(k, v) for k, v in sorted(why.items()))
        try:
            from System.Collections.Generic import List
            uidoc.Selection.SetElementIds(List[ElementId]([ElementId(i) for i in left]))
        except Exception:
            pass
    msg += u"\n\nВремя: {:.0f} с. Отмена — один Ctrl+Z.".format(time.time() - t0)
    forms.alert(msg, title=TITLE)
