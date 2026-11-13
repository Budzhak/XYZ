# -*- coding: utf-8 -*-
"""Опоры (lib/xyz_opory.py), 13.11.2026.

Опорные конструкции под оборудование и трассы — по техкарте производителя.
Техкарта — внешний файл JSON (правила подбора: какой комплект под какой габарит / массу / размер,
шаг и отступы опор). Код от производителя и семейств не зависит: имена семейств, параметров
и формулы — только в техкарте.

Слои:
  calc(...), pick_size(...), spots(...)  — чистый расчёт, без Revit (проверяется отдельно);
  load_card / save_card / check_card     — файл техкарты;
  probe(doc, elements, card)             — только чтение: строки «объект → что станет»;
  apply(doc, rows, card)                 — ставит семейства (вызывать внутри транзакции).
"""
import io
import os
import json
import math

try:
    from Autodesk.Revit import DB
except Exception:      # расчётную часть можно гонять без Revit
    DB = None

MM = 1.0 / 304.8
HERE = os.path.dirname(os.path.abspath(__file__))
EXT = os.path.dirname(HERE)
CARDS_DIR = os.path.join(EXT, u'Техкарты')
DEFAULT_CARD = os.path.join(CARDS_DIR, u'Опоры_рамы_кровельные.json')
TEMPLATE_CARD = os.path.join(CARDS_DIR, u'Опоры_шаблон.json')
SET_KEY = 'opory'


# ====================================================================== формулы техкарты
class CardError(Exception):
    pass


_FUNCS = {
    u'вверх': lambda x, s=1.0: math.ceil(x / s - 1e-9) * s,
    u'вниз': lambda x, s=1.0: math.floor(x / s + 1e-9) * s,
    u'ближайшее': lambda x, s=1.0: math.floor(x / s + 0.5) * s,
    u'макс': lambda *a: max(a),
    u'мин': lambda *a: min(a),
    u'модуль': lambda x: abs(x),
}


def _tokens(s):
    out, i, n = [], 0, len(s)
    while i < n:
        c = s[i]
        if c.isspace():
            i += 1
        elif c.isdigit():
            j = i
            while j < n and (s[j].isdigit() or s[j] == u'.'):
                j += 1
            out.append(('n', float(s[i:j])))
            i = j
        elif c.isalpha() or c == u'_':
            j = i
            while j < n and (s[j].isalnum() or s[j] == u'_'):
                j += 1
            out.append(('w', s[i:j]))
            i = j
        elif c in u'+-*/(),;':
            out.append(('o', u',' if c == u';' else c))
            i += 1
        else:
            raise CardError(u'формула «%s»: непонятный знак «%s»' % (s, c))
    return out


def calc(expr, env):
    """Значение формулы техкарты: числа, + - * / ( ), переменные из env,
    функции вверх(x; шаг), вниз(x; шаг), ближайшее(x; шаг), макс(...), мин(...), модуль(x).
    Десятичный знак — точка, аргументы функций — через «;».
    Число или строка-число возвращаются как есть. Без eval — в файл правил нельзя вписать код."""
    if expr is None:
        return None
    if isinstance(expr, (int, float)) and not isinstance(expr, bool):
        return float(expr)
    src = u'%s' % expr
    tk = _tokens(src)
    pos = [0]

    def peek():
        return tk[pos[0]] if pos[0] < len(tk) else (None, None)

    def take():
        t = peek()
        pos[0] += 1
        return t

    def atom():
        k, v = take()
        if k == 'n':
            return v
        if k == 'o' and v == u'-':
            return -atom()
        if k == 'o' and v == u'+':
            return atom()
        if k == 'o' and v == u'(':
            r = summ()
            if take() != ('o', u')'):
                raise CardError(u'формула «%s»: нет закрывающей скобки' % src)
            return r
        if k == 'w':
            if peek() == ('o', u'('):
                take()
                args = []
                if peek() != ('o', u')'):
                    args.append(summ())
                    while peek() == ('o', u','):
                        take()
                        args.append(summ())
                if take() != ('o', u')'):
                    raise CardError(u'формула «%s»: нет закрывающей скобки' % src)
                f = _FUNCS.get(v.lower())
                if f is None:
                    raise CardError(u'формула «%s»: нет функции «%s»' % (src, v))
                return f(*args)
            if v not in env or env[v] is None:
                raise CardError(u'формула «%s»: нет значения «%s»' % (src, v))
            return float(env[v])
        raise CardError(u'формула «%s»: ошибка записи' % src)

    def prod():
        r = atom()
        while peek() in (('o', u'*'), ('o', u'/')):
            op = take()[1]
            b = atom()
            r = r * b if op == u'*' else r / b
        return r

    def summ():
        r = prod()
        while peek() in (('o', u'+'), ('o', u'-')):
            op = take()[1]
            b = prod()
            r = r + b if op == u'+' else r - b
        return r

    res = summ()
    if pos[0] != len(tk):
        raise CardError(u'формула «%s»: лишнее в конце' % src)
    return res


def pick_size(rule, env):
    """Размер комплекта по правилу техкарты.
    rule: {"от": формула, "округление": "вверх"|"вниз"|"ближайшее", "шаг_мм": N, "ряд_мм": [...],
           "мин_мм": N, "макс_мм": N} или просто число / формула.
    Возвращает (значение, None) или (None, причина)."""
    if not isinstance(rule, dict):
        return calc(rule, env), None
    x = calc(rule.get(u'от'), env)
    how = rule.get(u'округление', u'вверх')
    row = rule.get(u'ряд_мм')
    if row:
        row = sorted(float(v) for v in row)
        if how == u'вверх':
            fit = [v for v in row if v >= x - 1e-6]
            if not fit:
                return None, u'%.0f мм больше наибольшего в ряду (%.0f)' % (x, row[-1])
            v = fit[0]
        elif how == u'вниз':
            fit = [v for v in row if v <= x + 1e-6]
            if not fit:
                return None, u'%.0f мм меньше наименьшего в ряду (%.0f)' % (x, row[0])
            v = fit[-1]
        else:
            v = min(row, key=lambda r: (abs(r - x), r))
    else:
        step = float(rule.get(u'шаг_мм') or 1)
        f = _FUNCS.get(how)
        if f is None:
            raise CardError(u'округление «%s» — такого нет (вверх, вниз, ближайшее)' % how)
        v = f(x, step)
    lo, hi = rule.get(u'мин_мм'), rule.get(u'макс_мм')
    if lo is not None and v < float(lo):
        v = float(lo)
    if hi is not None and v > float(hi) + 1e-6:
        return None, u'%.0f мм больше допустимого по техкарте (%.0f)' % (v, float(hi))
    return v, None


def spots(length, step, end=0.0, min_count=1):
    """Места опор вдоль участка длиной length: расстояния от начала, мм.
    step — наибольший шаг по техкарте, end — отступ крайних опор от концов.
    Опоры ставятся равномерно: шаг факт. ≤ step."""
    if length <= 0 or step <= 0:
        return []
    if length <= 2.0 * end + 1e-6:
        return [length / 2.0]
    span = length - 2.0 * end
    n = int(math.ceil(span / step - 1e-9)) + 1
    n = max(n, int(min_count), 2)
    return [end + span * i / (n - 1) for i in range(n)]


def fmt(x):
    if x is None:
        return u''
    return (u'%.0f' % x) if abs(x - round(x)) < 0.05 else (u'%.1f' % x)


def text_of(tpl, env):
    """Шаблон имени: {L} → значение переменной без дробной части."""
    out = tpl
    for k, v in env.items():
        if v is not None and (u'{%s}' % k) in out:
            out = out.replace(u'{%s}' % k, fmt(v) if isinstance(v, (int, float)) else u'%s' % v)
    return out


# ====================================================================== файл техкарты
def load_card(path):
    with io.open(path, encoding='utf-8-sig') as f:
        card = json.loads(f.read())
    problems = check_card(card)
    return card, problems


def save_card(card, path):
    txt = json.dumps(card, indent=1, ensure_ascii=False)
    if not isinstance(txt, type(u'')):
        txt = txt.decode('utf-8')
    with io.open(path, 'w', encoding='utf-8') as f:
        f.write(txt)


def check_card(card):
    """Список замечаний к техкарте (пустой — всё в порядке)."""
    bad = []
    if not isinstance(card, dict):
        return [u'техкарта должна быть объектом JSON']
    kits = card.get(u'комплекты')
    if not isinstance(kits, list) or not kits:
        bad.append(u'нет раздела «комплекты»')
        kits = []
    for i, k in enumerate(kits):
        nm = k.get(u'название', u'№%d' % (i + 1))
        if k.get(u'для') not in (u'оборудование', u'трасса'):
            bad.append(u'%s: «для» — «оборудование» или «трасса»' % nm)
        if k.get(u'пример'):
            continue
        if not k.get(u'семейство'):
            bad.append(u'%s: не указано «семейство»' % nm)
        if k.get(u'для') == u'трасса' and not k.get(u'шаг_мм'):
            bad.append(u'%s: не указан «шаг_мм»' % nm)
    return bad


def model_key(doc):
    return doc.Title


def current_path(doc):
    """Техкарта, выбранная для этой модели в прошлый раз (xyz_settings, ключ opory), иначе стандартная."""
    try:
        import xyz_settings
        p = ((xyz_settings.get(SET_KEY) or {}).get('cards') or {}).get(model_key(doc))
        if p and os.path.exists(p):
            return p
    except Exception:
        pass
    return DEFAULT_CARD


def remember_path(doc, path):
    try:
        import xyz_settings
        st = dict(xyz_settings.get(SET_KEY) or {})
        m = dict(st.get('cards') or {})
        m[model_key(doc)] = path
        st['cards'] = m
        xyz_settings.set(SET_KEY, st)
    except Exception:
        pass


# ====================================================================== чтение модели
def _name(e):
    return DB.Element.Name.GetValue(e)


def _iv(eid):
    try:
        return eid.Value
    except Exception:
        return eid.IntegerValue


def _pval(el, name):
    """Число (мм для длин) или строка из параметра экземпляра, затем типа."""
    for host in (el, el.Document.GetElement(el.GetTypeId())):
        if host is None:
            continue
        p = host.LookupParameter(name)
        if p is None or not p.HasValue:
            continue
        st = p.StorageType
        if st == DB.StorageType.Double:
            v = p.AsDouble()
            try:
                if p.Definition.GetDataType() == DB.SpecTypeId.Length:
                    v = v / MM
            except Exception:
                pass
            return v
        if st == DB.StorageType.Integer:
            return float(p.AsInteger())
        if st == DB.StorageType.String:
            s = p.AsString()
            if s:
                try:
                    return float(s.replace(u',', u'.').strip())
                except Exception:
                    return s
    return None


def _mass(el, names):
    for n in names:
        v = _pval(el, n)
        if isinstance(v, float) and v > 0:
            return v
    return None


def footprint(el):
    """Габарит оборудования в его собственных осях.
    Возвращает dict: l, w — длина и ширина в плане (l ≥ w), h — высота, мм;
    cx, cy — центр в плане, zmin, zmax (футы); ang — угол длинной стороны к оси X, рад."""
    bb = el.get_BoundingBox(None)
    if bb is None:
        return None
    dx, dy = bb.Max.X - bb.Min.X, bb.Max.Y - bb.Min.Y
    cx, cy = (bb.Min.X + bb.Max.X) / 2.0, (bb.Min.Y + bb.Max.Y) / 2.0
    ax = DB.XYZ.BasisX if dx >= dy else DB.XYZ.BasisY
    l, w = max(dx, dy), min(dx, dy)
    try:                      # повёрнутое не по осям: габарит в осях семейства
        tr = el.GetTransform()
        bx = tr.BasisX
        ortho = abs(abs(bx.X) - 1) < 1e-6 or abs(abs(bx.Y) - 1) < 1e-6
        if not ortho and abs(tr.BasisZ.Z - 1) < 1e-6:
            g = el.GetOriginalGeometry(DB.Options())
            gb = g.GetBoundingBox() if g is not None else None
            if gb is not None:
                lx, ly = gb.Max.X - gb.Min.X, gb.Max.Y - gb.Min.Y
                c = tr.OfPoint(DB.XYZ((gb.Min.X + gb.Max.X) / 2.0, (gb.Min.Y + gb.Max.Y) / 2.0, 0))
                cx, cy = c.X, c.Y
                ax = tr.BasisX if lx >= ly else tr.BasisY
                l, w = max(lx, ly), min(lx, ly)
    except Exception:
        pass
    return {'l': l / MM, 'w': w / MM, 'h': (bb.Max.Z - bb.Min.Z) / MM, 'cx': cx, 'cy': cy,
            'zmin': bb.Min.Z, 'zmax': bb.Max.Z, 'ang': math.atan2(ax.Y, ax.X)}


def _family_symbols(doc, fam_name):
    out = []
    for s in DB.FilteredElementCollector(doc).OfClass(DB.FamilySymbol):
        try:
            if s.FamilyName == fam_name:
                out.append(s)
        except Exception:
            pass
    return out


def _kit_instances(doc, card):
    """Уже стоящие в модели экземпляры семейств из техкарты: [(id, bbox)]."""
    fams = set(k.get(u'семейство') for k in card.get(u'комплекты', []) if k.get(u'семейство'))
    out = []
    if not fams:
        return out
    for fi in DB.FilteredElementCollector(doc).OfClass(DB.FamilyInstance):
        try:
            if fi.Symbol.FamilyName in fams and fi.SuperComponent is None:
                bb = fi.get_BoundingBox(None)
                if bb is not None:
                    out.append((_iv(fi.Id), bb))
        except Exception:
            pass
    return out


def _has_support(fp, placed, tol=300 * MM):
    for i, bb in placed:
        if bb.Min.X <= fp['cx'] <= bb.Max.X and bb.Min.Y <= fp['cy'] <= bb.Max.Y \
                and abs(bb.Max.Z - fp['zmin']) <= tol:
            return i
    return None


def _match(kit, kind, cat, fam, env):
    if kit.get(u'пример') or kit.get(u'для') != kind:
        return False
    c = kit.get(u'условия') or {}
    cats = c.get(u'категории')
    if cats and cat not in cats:
        return False
    inc = c.get(u'семейство_содержит')
    if inc and not [s for s in inc if s.lower() in fam.lower()]:
        return False
    exc = c.get(u'семейство_не_содержит')
    if exc and [s for s in exc if s.lower() in fam.lower()]:
        return False
    for key, var, sign in ((u'масса_до_кг', 'm', 1), (u'масса_от_кг', 'm', -1),
                           (u'длина_до_мм', 'l', 1), (u'длина_от_мм', 'l', -1),
                           (u'ширина_до_мм', 'w', 1), (u'ширина_от_мм', 'w', -1),
                           (u'размер_до_мм', 's', 1), (u'размер_от_мм', 's', -1)):
        lim = c.get(key)
        if lim is None:
            continue
        v = env.get(var)
        if v is None:
            if var == 'm':
                continue        # масса не заполнена — условие по массе проверить нельзя, см. «замечание»
            return False
        if sign * (v - float(lim)) > 1e-6:
            return False
    return True


def base_distance(doc, view3d, fp):
    """Расстояние от низа объекта до ближайшей поверхности под ним (в т. ч. в связях), мм; None — не найдено."""
    if view3d is None:
        return None
    try:
        ri = DB.ReferenceIntersector(view3d)
        ri.FindReferencesInRevitLinks = True
        ri.TargetType = DB.FindReferenceTarget.Face
        o = DB.XYZ(fp['cx'], fp['cy'], fp['zmin'] - 20 * MM)
        best = None
        for r in ri.Find(o, DB.XYZ(0, 0, -1)):
            ref = r.GetReference()
            el = doc.GetElement(ref.ElementId)
            cat = el.Category.Name if el is not None and el.Category is not None else u''
            if isinstance(el, DB.RevitLinkInstance):
                try:
                    le = el.GetLinkDocument().GetElement(ref.LinkedElementId)
                    cat = le.Category.Name if le is not None and le.Category is not None else u''
                except Exception:
                    cat = u''
            if cat in (u'Перекрытия', u'Крыши', u'Фундамент несущей конструкции', u'Floors', u'Roofs'):
                if best is None or r.Proximity < best:
                    best = r.Proximity
        return (best + 20 * MM) / MM if best is not None else None
    except Exception:
        return None


def find_3d(doc):
    v = doc.ActiveView
    if isinstance(v, DB.View3D) and not v.IsTemplate:
        return v
    for v in DB.FilteredElementCollector(doc).OfClass(DB.View3D):
        if not v.IsTemplate and _name(v) == u'{3D}':
            return v
    return None


def _route_info(el):
    """Прямой участок трассы: dict или None."""
    loc = el.Location
    if not isinstance(loc, DB.LocationCurve) or not isinstance(loc.Curve, DB.Line):
        return None
    ln = loc.Curve
    p0, p1 = ln.GetEndPoint(0), ln.GetEndPoint(1)
    d = {'p0': p0, 'p1': p1, 'len': ln.Length / MM, 'D': None, 'B': None, 'A': None}
    for key, bip in (('D', DB.BuiltInParameter.RBS_PIPE_OUTER_DIAMETER), ('D', DB.BuiltInParameter.RBS_CURVE_DIAMETER_PARAM),
                     ('B', DB.BuiltInParameter.RBS_CURVE_WIDTH_PARAM), ('A', DB.BuiltInParameter.RBS_CURVE_HEIGHT_PARAM),
                     ('B', DB.BuiltInParameter.RBS_CABLETRAY_WIDTH_PARAM), ('A', DB.BuiltInParameter.RBS_CABLETRAY_HEIGHT_PARAM)):
        if d[key] is None:
            p = el.get_Parameter(bip)
            if p is not None and p.HasValue and p.AsDouble() > 0:
                d[key] = p.AsDouble() / MM
    d['s'] = max(d['D'] or 0, d['B'] or 0, d['A'] or 0) or None
    d['half'] = ((d['A'] or d['D'] or 0) / 2.0)
    d['vert'] = abs(p1.Z - p0.Z) > 0.5 * ln.Length
    return d


# ====================================================================== проба
STATUS_OK, STATUS_HAS, STATUS_NO, STATUS_BAD = u'поставить', u'уже стоит', u'нет правила', u'не выходит'


def probe(doc, elements, card, view3d=None, overrides=None):
    """Только чтение. Строки пробы: dict с ключами
    id, obj, cat, kind, size, mass, kit, type, new_type, count, top, base, status, note и служебными (_...)."""
    rows = []
    placed = _kit_instances(doc, card)
    kit_fams = set(k.get(u'семейство') for k in card.get(u'комплекты', []))
    mass_names = card.get(u'параметры_массы') or [u'ADSK_Масса']
    ov = overrides or {}
    for el in elements:
        cat = el.Category.Name if el.Category is not None else u''
        fam = u''
        try:
            fam = el.Symbol.FamilyName
        except Exception:
            pass
        tname = u''
        try:
            tname = _name(doc.GetElement(el.GetTypeId()))
        except Exception:
            pass
        row = {'id': _iv(el.Id), 'obj': (fam + u' : ' + tname) if fam else (cat + u' : ' + tname), 'cat': cat,
               'kind': u'', 'size': u'', 'mass': None, 'kit': u'', 'type': u'', 'new_type': False, 'count': 0,
               'top': None, 'base': None, 'status': STATUS_NO, 'note': u'', '_el': el}
        rows.append(row)
        if fam in kit_fams:
            row['note'] = u'это сама опорная конструкция'
            continue
        route = _route_info(el)
        try:
            if route is not None:
                _probe_route(doc, el, cat, fam, route, card, row)
            elif isinstance(el, DB.FamilyInstance):
                _probe_equipment(doc, el, cat, fam, card, row, placed, mass_names, view3d, ov)
            else:
                row['note'] = u'не оборудование и не прямой участок трассы'
        except CardError as ex:
            row['status'] = STATUS_BAD
            row['note'] = u'%s' % ex
    return rows


def _probe_equipment(doc, el, cat, fam, card, row, placed, mass_names, view3d, ov):
    row['kind'] = u'оборудование'
    fp = footprint(el)
    if fp is None:
        row['note'] = u'у элемента нет габарита'
        return
    m = _mass(el, mass_names)
    row['mass'] = m
    row['size'] = u'%sх%sх%s' % (fmt(fp['l']), fmt(fp['w']), fmt(fp['h']))
    row['_fp'] = fp
    has = _has_support(fp, placed)
    if has is not None:
        row['status'] = STATUS_HAS
        row['note'] = u'под объектом стоит опора, id %d' % has
        return
    env = {'l': fp['l'], 'w': fp['w'], 'h': fp['h'], 'm': m}
    kit = None
    for k in card.get(u'комплекты', []):
        if _match(k, u'оборудование', cat, fam, env):
            kit = k
            break
    if kit is None:
        row['note'] = u'в техкарте нет комплекта под этот объект (категория, габарит или масса)'
        return
    row['kit'] = kit.get(u'название', u'')
    row['_kit'] = kit
    row['base'] = base_distance(doc, view3d, fp)
    env['база'] = row['base']
    sizes = {}
    for var in kit.get(u'порядок_размеров') or sorted((kit.get(u'размеры') or {}).keys()):
        rule = (kit.get(u'размеры') or {}).get(var)
        if var in ov and ov[var] is not None:
            v, why = float(ov[var]), None
        else:
            if isinstance(rule, dict) and rule.get(u'от') == u'база' and env.get(u'база') is None:
                rule = rule.get(u'по_умолчанию_мм')
            v, why = pick_size(rule, env)
        if v is None:
            row['status'] = STATUS_BAD
            row['note'] = u'%s: %s' % (var, why)
            return
        sizes[var] = v
        env[var] = v
    row['_env'] = env
    row['type'] = text_of(kit.get(u'тип_имя', u''), env)
    row['count'] = 1
    syms = _family_symbols(doc, kit.get(u'семейство'))
    if not syms and not (kit.get(u'файл_семейства') and os.path.exists(kit.get(u'файл_семейства'))):
        row['status'] = STATUS_BAD
        row['note'] = u'семейство «%s» не загружено в проект' % kit.get(u'семейство')
        return
    row['new_type'] = not [s for s in syms if _name(s) == row['type']]
    row['top'] = fp['zmin'] / MM
    row['status'] = STATUS_OK
    notes = []
    if m is None and (kit.get(u'условия') or {}).get(u'масса_до_кг') is not None:
        notes.append(u'масса не заполнена — несущая способность не проверена')
    if row['base'] is not None and u'H' in sizes and abs(row['base'] - sizes[u'H']) > 50:
        notes.append(u'ВНИМАНИЕ: до основания %s мм, а высота комплекта %s — проверьте высоту (поле H в окне)'
                     % (fmt(row['base']), fmt(sizes[u'H'])))
    for part in kit.get(u'состав') or []:
        try:
            notes.append(u'%s × %s' % (part.get(u'что', u''), fmt(calc(part.get(u'количество', 1), env))))
        except CardError:
            pass
    row['note'] = u'; '.join(notes)


def _probe_route(doc, el, cat, fam, route, card, row):
    row['kind'] = u'трасса'
    row['_route'] = route
    row['size'] = (u'Ø%s' % fmt(route['D'])) if route['D'] else u'%sх%s' % (fmt(route['B']), fmt(route['A']))
    row['size'] += u', L=%s' % fmt(route['len'])
    if route['vert']:
        row['note'] = u'вертикальный участок — в этой версии не обрабатывается'
        return
    env = {'D': route['D'], 'B': route['B'], 'A': route['A'], 's': route['s'], 'len': route['len']}
    kit = None
    for k in card.get(u'комплекты', []):
        if _match(k, u'трасса', cat, fam, env):
            kit = k
            break
    if kit is None:
        row['note'] = u'в техкарте нет правила для такой трассы'
        return
    row['kit'] = kit.get(u'название', u'')
    row['_kit'] = kit
    step = calc(kit.get(u'шаг_мм'), env)
    end = calc(kit.get(u'отступ_от_концов_мм', 0), env)
    pts = spots(route['len'], step, end, kit.get(u'не_меньше_шт', 1))
    for var in kit.get(u'порядок_размеров') or sorted((kit.get(u'размеры') or {}).keys()):
        v, why = pick_size((kit.get(u'размеры') or {}).get(var), env)
        if v is None:
            row['status'] = STATUS_BAD
            row['note'] = u'%s: %s' % (var, why)
            return
        env[var] = v
    row['_env'] = env
    row['_spots'] = pts
    row['count'] = len(pts)
    row['type'] = text_of(kit.get(u'тип_имя', u''), env)
    syms = _family_symbols(doc, kit.get(u'семейство'))
    fact = (pts[1] - pts[0]) if len(pts) > 1 else 0
    row['note'] = u'шаг по техкарте %s, факт. %s мм' % (fmt(step), fmt(fact))
    if not syms:
        row['status'] = STATUS_BAD
        row['note'] += u'; семейство «%s» не загружено в проект' % kit.get(u'семейство')
        return
    row['new_type'] = bool(row['type']) and not [s for s in syms if _name(s) == row['type']]
    row['top'] = (min(route['p0'].Z, route['p1'].Z)) / MM - route['half']
    row['status'] = STATUS_OK


# ====================================================================== применение
def _set(el, name, val):
    p = el.LookupParameter(name)
    if p is None or p.IsReadOnly:
        return False
    st = p.StorageType
    if st == DB.StorageType.String:
        p.Set(u'%s' % (fmt(val) if isinstance(val, float) else val))
    elif st == DB.StorageType.Integer:
        p.Set(int(round(float(val))))
    elif st == DB.StorageType.Double:
        v = float(val)
        try:
            if p.Definition.GetDataType() == DB.SpecTypeId.Length:
                v = v * MM
        except Exception:
            pass
        p.Set(v)
    else:
        return False
    return True


def _value(spec, env):
    """Значение параметра из техкарты: {"текст": "..."} — строка-шаблон, иначе формула."""
    if isinstance(spec, dict) and u'текст' in spec:
        return text_of(spec[u'текст'], env)
    return calc(spec, env)


def _ensure_symbol(doc, kit, env, type_name, log):
    syms = _family_symbols(doc, kit.get(u'семейство'))
    if not syms and kit.get(u'файл_семейства'):
        doc.LoadFamily(kit.get(u'файл_семейства'))
        syms = _family_symbols(doc, kit.get(u'семейство'))
    if not syms:
        raise CardError(u'семейство «%s» не загружено' % kit.get(u'семейство'))
    if not type_name:
        return syms[0]
    for s in syms:
        if _name(s) == type_name:
            return s
    src = [s for s in syms if _name(s) == kit.get(u'образец_типа')] or syms
    s = src[0].Duplicate(type_name)
    for pname, spec in (kit.get(u'параметры_типа') or {}).items():
        if not _set(s, pname, _value(spec, env)):
            log.append(u'тип «%s»: параметр «%s» не записан' % (type_name, pname))
    log.append(u'создан тип «%s»' % type_name)
    return s


def _level_for(doc, el, z):
    lv = None
    try:
        lv = doc.GetElement(el.LevelId)
    except Exception:
        pass
    if not isinstance(lv, DB.Level):
        p = el.get_Parameter(DB.BuiltInParameter.RBS_START_LEVEL_PARAM)
        if p is not None:
            lv = doc.GetElement(p.AsElementId())
    if not isinstance(lv, DB.Level):
        lvs = sorted(DB.FilteredElementCollector(doc).OfClass(DB.Level), key=lambda l: l.Elevation)
        below = [l for l in lvs if l.Elevation <= z + 1e-6]
        lv = below[-1] if below else lvs[0]
    return lv


def _place(doc, sym, lv, cx, cy, top, ang, align_plan, align_z, shift=None):
    """Экземпляр в точке; поворот вокруг вертикали; совмещение по габариту:
    центр габарита в плане → (cx, cy), верх габарита → top."""
    from Autodesk.Revit.DB.Structure import StructuralType
    if not sym.IsActive:
        sym.Activate()
        doc.Regenerate()
    p = DB.XYZ(cx, cy, top)
    inst = doc.Create.NewFamilyInstance(p, sym, lv, StructuralType.NonStructural)
    doc.Regenerate()
    lp = inst.Location.Point
    if abs(ang) > 1e-9:
        DB.ElementTransformUtils.RotateElement(doc, inst.Id, DB.Line.CreateBound(lp, lp + DB.XYZ.BasisZ), ang)
        doc.Regenerate()
    bb = inst.get_BoundingBox(None)
    lp = inst.Location.Point
    dx = (cx - (bb.Min.X + bb.Max.X) / 2.0) if align_plan == u'центр габарита' else (cx - lp.X)
    dy = (cy - (bb.Min.Y + bb.Max.Y) / 2.0) if align_plan == u'центр габарита' else (cy - lp.Y)
    if align_z == u'верх габарита':
        dz = top - bb.Max.Z
    elif align_z == u'низ габарита':
        dz = top - bb.Min.Z
    else:
        dz = top - lp.Z
    if shift:
        c, s = math.cos(ang), math.sin(ang)
        dx += (shift[0] * c - shift[1] * s) * MM
        dy += (shift[0] * s + shift[1] * c) * MM
        dz += shift[2] * MM
    if abs(dx) + abs(dy) + abs(dz) > 1e-9:
        DB.ElementTransformUtils.MoveElement(doc, inst.Id, DB.XYZ(dx, dy, dz))
    return inst


def _after(doc, inst, el, kit, env, log):
    for pname, spec in (kit.get(u'параметры_экземпляра') or {}).items():
        if not _set(inst, pname, _value(spec, env)):
            log.append(u'id %d: параметр «%s» не записан' % (_iv(inst.Id), pname))
    for pname in kit.get(u'как_у_объекта') or []:
        v = _pval(el, pname)
        if v is not None:
            _set(inst, pname, v)
    if kit.get(u'рабочий_набор', u'как у объекта') == u'как у объекта' and doc.IsWorkshared:
        try:
            p = inst.get_Parameter(DB.BuiltInParameter.ELEM_PARTITION_PARAM)
            if p is not None and not p.IsReadOnly:
                p.Set(el.WorksetId.IntegerValue)
        except Exception:
            pass


def apply(doc, rows, card):
    """Ставит комплекты для строк со статусом «поставить». Вызывать внутри открытой транзакции.
    Возвращает (ids созданных, журнал)."""
    made, log = [], []
    for row in rows:
        if row.get('status') != STATUS_OK:
            continue
        kit, env, el = row['_kit'], row['_env'], row['_el']
        al = kit.get(u'совмещение') or {}
        shift = [calc(v, env) for v in (al.get(u'сдвиг_мм') or [0, 0, 0])]
        try:
            sym = _ensure_symbol(doc, kit, env, row['type'], log)
            if row['kind'] == u'оборудование':
                fp = row['_fp']
                lv = _level_for(doc, el, fp['zmin'])
                inst = _place(doc, sym, lv, fp['cx'], fp['cy'], fp['zmin'], fp['ang'],
                              al.get(u'в_плане', u'центр габарита'), al.get(u'по_высоте', u'верх габарита'), shift)
                _after(doc, inst, el, kit, env, log)
                made.append(_iv(inst.Id))
            else:
                r = row['_route']
                d = (r['p1'] - r['p0']).Normalize()
                ang = math.atan2(d.Y, d.X) + (math.pi / 2.0 if kit.get(u'поворот', u'поперёк') == u'поперёк' else 0.0)
                lv = _level_for(doc, el, r['p0'].Z)
                for t in row['_spots']:
                    p = r['p0'] + d.Multiply(t * MM)
                    z = p.Z - (r['half'] * MM if al.get(u'по_высоте', u'верх габарита') != u'точка вставки' else 0)
                    inst = _place(doc, sym, lv, p.X, p.Y, z, ang,
                                  al.get(u'в_плане', u'точка вставки'), al.get(u'по_высоте', u'верх габарита'), shift)
                    _after(doc, inst, el, kit, env, log)
                    made.append(_iv(inst.Id))
        except CardError as ex:
            log.append(u'id %d: %s' % (row['id'], ex))
    return made, log


def totals(rows):
    """Итог пробы: {(комплект, тип): штук} для строк «поставить»."""
    t = {}
    for r in rows:
        if r.get('status') == STATUS_OK:
            k = (r['kit'], r['type'], r['new_type'])
            t[k] = t.get(k, 0) + r['count']
    return t
