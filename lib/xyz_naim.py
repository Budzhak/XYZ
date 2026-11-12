# -*- coding: utf-8 -*-
"""Наименования по шаблонам — логика кнопки «Сделать → Наименования» (db 21.10.2026).

Ничего не пишет само: compute() — проба «было → станет», apply() пишет показанное.
Правила хранятся в файле, который выбирает инженер (по умолчанию рядом с моделью:
<имя файла модели>_XYZ_Наименования.json).

Правило: {'on': True, 'cat': 'OST_DuctFitting',
          'conds': [{'host': False, 'param': u'Модель', 'op': u'=', 'value': u'Отвод'}],
          'tpl': u'Отвод {ADSK_Размер_УголПоворота | округл 5}° …', 'keep': False}
Сверху вниз, первое подошедшее. keep=True — «не менять»: элемент пойман, наименование не трогаем.
Наименование, начинающееся с «!», не трогается никогда.

Шаблон:
  {Параметр}                 значение как в «Свойствах»: длины — в мм, углы — в градусах, без единиц
  {основа: Параметр}         параметр основы (для изоляции)
  {макс: A; B}, {мин: A; B}  большее / меньшее из значений
  {… | модификатор | …}      округл N, без знака, целое, половина, х, запятая, таблица <Имя>
  [ … ]                      необязательный кусок: выпадает, если в нём пустой параметр
  {{ }} [[ ]]                сами символы { } [ ]
"""
import io
import os
import re
import json

from Autodesk.Revit.DB import (BuiltInParameter, StorageType, UnitUtils, SpecTypeId, ElementId)

import xyz_qty as q

NAME_PARAM = u'ADSK_Наименование'
SECT_PARAM = u'db_Раздел'
SORT_PARAM = u'db_Сортировка'
CODE_PARAM = u'db_Категория'
UNIT_PARAM = u'db_Единица измерения'

CATS = q.CATS + [(u'Сантехнические приборы', 'OST_PlumbingFixtures'),
                 (u'Электрооборудование', 'OST_ElectricalEquipment')]
CAT_NAME = dict((k, n) for n, k in CATS)
OPS = q.OPS
MODS = [u'округл 5', u'без знака', u'целое', u'половина', u'первый', u'х', u'запятая']
MOD_HELP = [
    (u'округл 5', u'округлить до кратного 5 (87° → 85°; 0 → 5)'),
    (u'без знака', u'модуль числа (смещение утки −25 → 25)'),
    (u'целое', u'округлить до целого'),
    (u'половина', u'первая половина строки: «⌀200-⌀200» → «⌀200»'),
    (u'первый', u'часть до первого «-»: «⌀20-⌀6» → «⌀20», «⌀6.35» → «⌀6.35»'),
    (u'х', u'латинскую x заменить на русскую х: 400x600 → 400х600'),
    (u'запятая', u'точку заменить на запятую: 0.35 → 0,35'),
    (u'таблица <Имя>', u'подставить из вкладки «Таблицы»: первая строка, где значение ≤ «До» (или равно, если «До» — текст)'),
]

G = u'из оц. стали'
DEFAULT_RULES = [
    # воздуховоды
    {'cat': 'OST_DuctCurves', 'conds': [(u'Семейство', u'содержит', u'круглого')],
     'tpl': u'Воздуховод ' + G + u' ⌀{Диаметр} мм, б = {Диаметр | таблица Толщина стали (кругл.)} мм'},
    {'cat': 'OST_DuctCurves', 'conds': [],
     'tpl': u'Воздуховод ' + G + u' {макс: Ширина; Высота}х{мин: Ширина; Высота} мм, '
            u'б = {макс: Ширина; Высота | таблица Толщина стали (прям.)} мм'},
    {'cat': 'OST_FlexDuctCurves', 'conds': [], 'tpl': u'Воздуховод гибкий теплоизолированный ⌀{Диаметр} мм'},
    # фасонка
    {'cat': 'OST_DuctFitting', 'conds': [(u'Семейство', u'содержит', u'штанообразный')], 'keep': True},
    {'cat': 'OST_DuctFitting', 'conds': [(u'Модель', u'=', u'Соединение')], 'keep': True},
    {'cat': 'OST_DuctFitting', 'conds': [(u'Модель', u'=', u'Отвод'), (u'Семейство', u'содержит', u'Круглый')],
     'tpl': u'Отвод {ADSK_Размер_УголПоворота | округл 5}° ' + G + u' {Размер | половина} мм'},
    {'cat': 'OST_DuctFitting', 'conds': [(u'Модель', u'=', u'Отвод')],
     'tpl': u'Отвод {ADSK_Размер_УголПоворота | округл 5}° ' + G + u' {ADSK_Размер_Ширина}х{ADSK_Размер_Высота} мм'},
    {'cat': 'OST_DuctFitting', 'conds': [(u'Модель', u'=', u'Переход')],
     'tpl': u'Переход ' + G + u' {Размер} мм, l={ADSK_Размер_Длина} мм[, тип № {db_Тип перехода}]'},
    {'cat': 'OST_DuctFitting', 'conds': [(u'Модель', u'=', u'Утка')],
     'tpl': u'Утка ' + G + u' {Размер} мм, h={ADSK_Размер_Высота | без знака} мм, l={ADSK_Размер_Длина} мм'},
    {'cat': 'OST_DuctFitting', 'conds': [(u'Модель', u'=', u'Тройник')], 'tpl': u'Тройник ' + G + u' {Размер} мм'},
    {'cat': 'OST_DuctFitting', 'conds': [(u'Модель', u'=', u'Крестовина')], 'tpl': u'Крестовина ' + G + u' {Размер} мм'},
    {'cat': 'OST_DuctFitting', 'conds': [(u'Модель', u'=', u'Врезка')], 'tpl': u'Врезка ' + G + u' {Размер | половина} мм'},
    {'cat': 'OST_DuctFitting', 'conds': [(u'Модель', u'=', u'Заглушка')], 'tpl': u'Заглушка ' + G + u' {Размер | х} мм'},
    # изоляция воздуховодов
    {'cat': 'OST_DuctInsulations', 'conds': [(u'Тип', u'содержит', u'AL CLAD')],
     'tpl': u'Теплоизоляция из вспененного каучука {Толщина изоляции} мм с покрытием AL CLAD'},
    {'cat': 'OST_DuctInsulations', 'conds': [(u'Тип', u'начинается с', u'db_K-Flex')],
     'tpl': u'Теплоизоляция из вспененного каучука {Толщина изоляции} мм'},
    # трубы
    {'cat': 'OST_PipeCurves', 'conds': [(u'Тип', u'начинается с', u'LG pipe')],
     'tpl': u'Труба медная ⌀{Внешний диаметр}х{Внешний диаметр | таблица Стенка меди LG} мм'},
    {'cat': 'OST_PipeCurves', 'conds': [(u'Тип', u'содержит', u'Медь дюймовая')],
     'tpl': u'Труба медная ⌀{Внешний диаметр}х{Толщина стенки | запятая} мм'},
    {'cat': 'OST_PipeCurves', 'conds': [(u'Тип', u'содержит', u'нержавеющей')],
     'tpl': u'Труба из нержавеющей стали AISI 304 ⌀{Внешний диаметр}х{Толщина стенки | запятая} мм'},
    {'cat': 'OST_PipeCurves', 'conds': [(u'Тип', u'содержит', u'PN10')],
     'tpl': u'Труба полипропиленовая PN10 ⌀{Внешний диаметр}х{Толщина стенки | запятая} мм'},
    {'cat': 'OST_PipeCurves', 'conds': [(u'Тип', u'содержит', u'PN20')],
     'tpl': u'Труба полипропиленовая PN20 ⌀{Внешний диаметр}х{Толщина стенки | запятая} мм'},
    {'cat': 'OST_PipeCurves', 'conds': [(u'Тип', u'содержит', u'капиллярная')],
     'tpl': u'Трубка капиллярная ⌀{Внешний диаметр}х{Толщина стенки | запятая} мм'},
    # изоляция труб
    {'cat': 'OST_PipeInsulations', 'conds': [(u'Тип', u'содержит', u'AL CLAD')],
     'tpl': u'Трубки теплоизоляционные из вспененного каучука с покрытием AL CLAD, b={Толщина изоляции} мм '
            u'для {Размер трубы | первый}'},
    {'cat': 'OST_PipeInsulations', 'conds': [],
     'tpl': u'Трубки теплоизоляционные, b={Толщина изоляции} мм для {Размер трубы | первый}'},
]

DEFAULT_TABLES = {
    u'Толщина стали (кругл.)': [[u'200', u'0,5'], [u'450', u'0,6'], [u'800', u'0,7'], [u'1250', u'1,0'],
                                [u'1600', u'1,2'], [u'2000', u'1,4']],
    u'Толщина стали (прям.)': [[u'250', u'0,5'], [u'1000', u'0,7'], [u'2000', u'0,9']],
    u'Стенка меди LG': [[u'9.53', u'0,35'], [u'12.71', u'0,4'], [u'19.06', u'0,5'], [u'28.59', u'0,6'],
                        [u'60', u'1,0']],
}

# раздел ведомости по коду db_Категория (db 20.10, «Общая для сметы»)
S1, S2, S3 = u'1. Оборудование', u'2. Воздуховоды и соединительные элементы', u'3. Воздухораспределители'
S4, S5, S6 = (u'4. Фреонопроводы и соединительные элементы', u'5. Конденсатопроводы (дренаж)',
              u'6. Опорные конструкции и крепёж')
DEFAULT_SECTIONS = [
    [u'01', S1, u''], [u'02', S1, u''], [u'10', S3, u''], [u'11', S2, u'шт.'], [u'12', S2, u'м'],
    [u'13', S2, u'м'], [u'14', S2, u'шт.'], [u'15', S2, u'м²'], [u'03', S4, u''], [u'21', S4, u'м'],
    [u'22', S4, u''], [u'25', S4 + u' / ' + S5, u'м'], [u'04', S5, u''], [u'20', S5, u''], [u'23', S5, u'м'],
    [u'24', S5, u''], [u'05', S6, u''], [u'30', S6, u''],
]
# код для элементов, у которых db_Категория пустая
DEFAULT_CAT_CODES = [['OST_DuctCurves', u'12'], ['OST_DuctFitting', u'14'], ['OST_FlexDuctCurves', u'13'],
                     ['OST_DuctInsulations', u'15'], ['OST_DuctAccessory', u'11']]
# порядок раздела «1. Оборудование»: вентустановки по db_Позиция, наружные блоки по системам в этом порядке,
# внутренние блоки, прочее LG, всё остальное
DEFAULT_EQ_ORDER = [u'ККБ1', u'ККБ2', u'VRF1', u'VRF2', u'HYDROKIT']
NO_SORT_CODES = [u'10']


def _rule(d):
    return {'on': True, 'cat': d['cat'], 'keep': bool(d.get('keep')), 'tpl': d.get('tpl', u''),
            'conds': [{'host': False, 'param': p, 'op': o, 'value': v} for p, o, v in d['conds']]}


def default_settings():
    return {'rules': [_rule(d) for d in DEFAULT_RULES],
            'tables': dict((k, [list(r) for r in v]) for k, v in DEFAULT_TABLES.items()),
            'sections': [list(r) for r in DEFAULT_SECTIONS],
            'cat_codes': [list(r) for r in DEFAULT_CAT_CODES],
            'eq_order': list(DEFAULT_EQ_ORDER),
            'skip_excl': True, 'frames': None, 'ws_off': [], 'scope': 'model'}


SAVE_KEYS = ('rules', 'tables', 'sections', 'cat_codes', 'eq_order', 'frames', 'ws_off', 'scope')


def sig(st):
    return json.dumps([st.get(k) for k in ('rules', 'tables', 'sections', 'cat_codes', 'eq_order')], sort_keys=True, ensure_ascii=False)


# ------------------------------------------------------------------ файл правил
def _rules_path_new(doc):
    p = doc.PathName or u''
    if p:
        d, f = os.path.split(p)
        return os.path.join(d, os.path.splitext(f)[0] + u'_XYZ_Наименования.json')
    return os.path.join(os.environ.get('APPDATA', u''), u'pyRevit', (doc.Title or u'модель') + u'_XYZ_Наименования.json')

def rules_path(doc):
    """Файл правил XYZ; если его нет, а есть файл, сохранённый до переименования плагина (30.10.2026), — старый."""
    new = _rules_path_new(doc)
    old = new.replace(u'_XYZ_', u'_\u0425\u0423\u0419_')
    if not os.path.exists(new) and os.path.exists(old):
        return old
    return new



def current_path(doc):
    try:
        import xyz_settings
        p = (xyz_settings.get('names_rules') or {}).get(q.model_key(doc))
        if p:
            return p
    except Exception:
        pass
    return rules_path(doc)


def remember_path(doc, path):
    try:
        import xyz_settings
        m = dict(xyz_settings.get('names_rules') or {})
        m[q.model_key(doc)] = path
        xyz_settings.set('names_rules', m)
    except Exception:
        pass


def load_settings(doc, path=None):
    """(settings, path, из_файла)."""
    path = path or current_path(doc)
    st = default_settings()
    if os.path.exists(path):
        try:
            with io.open(path, 'r', encoding='utf-8') as f:
                st.update(json.load(f))
            return st, path, True
        except Exception:
            pass
    return st, path, False


def save_settings(doc, st, path=None):
    path = path or current_path(doc)
    data = dict((k, st.get(k)) for k in SAVE_KEYS)
    data['skip_excl'] = True
    txt = json.dumps(data, ensure_ascii=False, indent=1)
    if not isinstance(txt, type(u'')):
        txt = txt.decode('utf-8')
    with io.open(path, 'w', encoding='utf-8') as f:
        f.write(txt)
    remember_path(doc, path)
    return path


# ------------------------------------------------------------------ значения параметров
_UNITS = {}


def _valid_units(spec):
    k = spec.TypeId
    if k not in _UNITS:
        try:
            _UNITS[k] = set(u.TypeId for u in UnitUtils.GetValidUnits(spec))
        except Exception:
            _UNITS[k] = set()
    return _UNITS[k]


def num(v):
    """Число без хвостовых нулей, точка — десятичный знак: 315, 6.35, 0.5."""
    r = round(v, 2)
    if abs(r - round(r)) < 1e-9:
        return u'%d' % int(round(r))
    return (u'%.2f' % r).rstrip(u'0').rstrip(u'.')


def _double(p):
    v = p.AsDouble()
    try:
        ut = p.GetUnitTypeId()
    except Exception:
        return num(v)
    t = ut.TypeId
    if t in _valid_units(SpecTypeId.Length):
        return num(v * 304.8)
    if t in _valid_units(SpecTypeId.Angle):
        return num(v * 180.0 / 3.141592653589793)
    if t in _valid_units(SpecTypeId.Area):
        return num(v * 0.09290304)
    if t in _valid_units(SpecTypeId.Volume):
        return num(v * 0.028316846592)
    try:
        return num(UnitUtils.ConvertFromInternalUnits(v, ut))
    except Exception:
        return num(v)


def value(doc, el, name):
    """Значение параметра для шаблона. None — параметра нет, u'' — пустой."""
    if el is None:
        return None
    if name in (u'Семейство', u'Тип'):
        return q.pstr(doc, el, name)
    if name == u'Категория':
        return el.Category.Name if el.Category is not None else u''
    p = q.find_param(doc, el, name)
    if p is None:
        return None
    if not p.HasValue:
        return u''
    st = p.StorageType
    if st == StorageType.String:
        return p.AsString() or u''
    if st == StorageType.Double:
        return _double(p)
    if st == StorageType.Integer:
        vs = None
        try:
            vs = p.AsValueString()
        except Exception:
            pass
        return vs if vs else u'%d' % p.AsInteger()
    try:
        return p.AsValueString() or u''
    except Exception:
        return u''


def examples(doc, el, names):
    out = {}
    for n in names:
        try:
            v = value(doc, el, n)
        except Exception:
            v = None
        out[n] = v
    return out


# ------------------------------------------------------------------ шаблон
class TplError(Exception):
    pass


_NUM = re.compile(u'-?\\d+(?:[.,]\\d+)?')


def _tonum(s):
    m = _NUM.search(s or u'')
    if not m:
        raise TplError(u'не число: «%s»' % s)
    return float(m.group(0).replace(u',', u'.'))


def parse(tpl):
    """Шаблон → список узлов: ('t', текст) | ('p', содержимое) | ('o', [узлы]). Ошибка синтаксиса — TplError."""
    out = []
    stack = [out]
    i = 0
    n = len(tpl)
    buf = []

    def flush():
        if buf:
            stack[-1].append(('t', u''.join(buf)))
            del buf[:]
    while i < n:
        ch = tpl[i]
        nx = tpl[i + 1] if i + 1 < n else u''
        if ch in u'{}[]' and nx == ch:
            buf.append(ch)
            i += 2
            continue
        if ch == u'{':
            j = tpl.find(u'}', i + 1)
            if j < 0:
                raise TplError(u'нет закрывающей «}»')
            flush()
            stack[-1].append(('p', tpl[i + 1:j].strip()))
            i = j + 1
            continue
        if ch == u'}':
            raise TplError(u'лишняя «}» (сама скобка пишется «}}»)')
        if ch == u'[':
            if len(stack) > 1:
                raise TplError(u'«[ ]» внутри «[ ]» не бывает')
            flush()
            sub = []
            stack[-1].append(('o', sub))
            stack.append(sub)
            i += 1
            continue
        if ch == u']':
            if len(stack) == 1:
                raise TplError(u'лишняя «]» (сама скобка пишется «]]»)')
            flush()
            stack.pop()
            i += 1
            continue
        buf.append(ch)
        i += 1
    flush()
    if len(stack) > 1:
        raise TplError(u'нет закрывающей «]»')
    return out


def _ref(doc, el, host, ref):
    ref = ref.strip()
    m = re.match(u'^основа\\s*:\\s*(.+)$', ref)
    if m:
        if host is None:
            return None, u'нет основы'
        v = value(doc, host, m.group(1).strip())
        return v, (u'у основы нет «%s»' % m.group(1).strip()) if v is None else None
    v = value(doc, el, ref)
    return v, (u'нет параметра «%s»' % ref) if v is None else None


def lookup(tables, tname, v):
    rows = tables.get(tname)
    if rows is None:
        raise TplError(u'нет таблицы «%s»' % tname)
    try:
        x = _tonum(v)
    except TplError:
        x = None
    for r in rows:
        lim = (r[0] if len(r) > 0 else u'') or u''
        val = (r[1] if len(r) > 1 else u'') or u''
        try:
            lf = float(lim.replace(u',', u'.'))
        except Exception:
            lf = None
        if lf is not None and x is not None:
            if x <= lf + 1e-9:
                return val
        elif lim.strip() == (v or u'').strip():
            return val
    raise TplError(u'«%s» нет в таблице «%s»' % (v, tname))


def modify(v, mod, tables):
    mod = mod.strip()
    if not mod:
        return v
    if mod.startswith(u'округл'):
        try:
            k = float(mod[len(u'округл'):].strip().replace(u',', u'.') or u'1')
        except Exception:
            raise TplError(u'«%s»: после «округл» нужно число' % mod)
        x = _tonum(v)
        r = k * round(x / k)
        if r == 0 and x > 0:
            r = k
        return num(r)
    if mod == u'без знака':
        return num(abs(_tonum(v)))
    if mod == u'целое':
        return u'%d' % int(round(_tonum(v)))
    if mod == u'половина':
        return v[:len(v) // 2]
    if mod == u'первый':
        return v.split(u'-')[0].strip()
    if mod in (u'х', u'x'):
        return v.replace(u'x', u'х')
    if mod == u'запятая':
        return v.replace(u'.', u',')
    if mod.startswith(u'таблица'):
        return lookup(tables, mod[len(u'таблица'):].strip(), v)
    raise TplError(u'неизвестный модификатор «%s»' % mod)


def placeholder(doc, el, host, body, tables):
    """(значение, причина_пусто). Пустое значение: u''. Ошибка — TplError."""
    parts = body.split(u'|')
    head = parts[0].strip()
    m = re.match(u'^(макс|мин)\\s*:\\s*(.+)$', head)
    if m:
        vals = []
        for ref in m.group(2).split(u';'):
            v, why = _ref(doc, el, host, ref)
            if v is None:
                return None, why
            if v != u'':
                vals.append(v)
        if not vals:
            return u'', u'пусто: {%s}' % head
        nums = [(_tonum(v), v) for v in vals]
        v = (max if m.group(1) == u'макс' else min)(nums)[1]
    else:
        v, why = _ref(doc, el, host, head)
        if v is None:
            return None, why
        if v == u'':
            return u'', u'пусто: {%s}' % head
    for mod in parts[1:]:
        v = modify(v, mod, tables)
    return v, None


def render(doc, el, host, tpl, tables, nodes=None):
    """(текст, None) или (None, причина)."""
    try:
        nodes = nodes if nodes is not None else parse(tpl)
        out = []
        for kind, x in nodes:
            if kind == 't':
                out.append(x)
            elif kind == 'p':
                v, why = placeholder(doc, el, host, x, tables)
                if not v:
                    return None, why
                out.append(v)
            else:
                part = []
                ok = True
                for k2, y in x:
                    if k2 == 't':
                        part.append(y)
                        continue
                    v, why = placeholder(doc, el, host, y, tables)
                    if not v:
                        ok = False
                        break
                    part.append(v)
                if ok:
                    out.append(u''.join(part))
        return re.sub(u'\\s{2,}', u' ', u''.join(out)).strip(), None
    except TplError as ex:
        return None, u'%s' % ex
    except Exception as ex:
        return None, u'ошибка: %s' % ex


def check(tpl, tables):
    """Проверка шаблона без элемента: None или текст ошибки."""
    try:
        nodes = parse(tpl)
    except TplError as ex:
        return u'%s' % ex
    for kind, x in nodes:
        for body in ([x] if kind == 'p' else [y for k2, y in x if k2 == 'p'] if kind == 'o' else []):
            for mod in body.split(u'|')[1:]:
                mod = mod.strip()
                if mod.startswith(u'таблица') and mod[len(u'таблица'):].strip() not in tables:
                    return u'нет таблицы «%s»' % mod[len(u'таблица'):].strip()
                if not (mod.startswith(u'округл') or mod.startswith(u'таблица') or mod in MODS or mod == u'x'):
                    return u'неизвестный модификатор «%s»' % mod
    return None


# ------------------------------------------------------------------ правила
def _by_cat(rules):
    d = {}
    for i, r in enumerate(rules):
        if r.get('on'):
            d.setdefault(q.cat_id(r['cat']), []).append(i)
    return d


def cond_ok(doc, el, host, c):
    if (c.get('param') or u'') == u'Категория':
        src = host if c.get('host') else el
        c = dict(c, param=u'Семейство')
        v = (src.Category.Name if (src is not None and src.Category is not None) else u'')
        w = c.get('value') or u''
        op = c.get('op') or u'='
        return {u'=': v == w, u'≠': v != w, u'содержит': w in v, u'не содержит': w not in v,
                u'начинается с': v.startswith(w)}.get(op, False)
    return q.cond_ok(doc, el, host, c)


def first_rule(doc, el, host, rules, idx):
    for i in idx:
        if all(cond_ok(doc, el, host, c) for c in rules[i]['conds']):
            return i
    return None


def scan(doc, items, rules, tables):
    """Для шага 2: (сколько поймало каждое правило, пример по каждому правилу (эл, было, стало|None, ошибка))."""
    cnt = [0] * len(rules)
    ex = [None] * len(rules)
    by = _by_cat(rules)
    nodes = {}
    for el, f in items:
        if el.Category is None:
            continue
        idx = by.get(q._iv(el.Category.Id))
        if not idx:
            continue
        old = q.pstr(doc, el, NAME_PARAM)
        if old.startswith(u'!'):
            continue
        host = q.host_of(doc, el)
        i = first_rule(doc, el, host, rules, idx)
        if i is None:
            continue
        cnt[i] += 1
        r = rules[i]
        if r.get('keep'):
            if ex[i] is None:
                ex[i] = (el, old, old, None)
            continue
        cur = ex[i]
        if cur is not None and (cur[3] is None and cur[2] != cur[1]):
            continue
        if i not in nodes:
            try:
                nodes[i] = parse(r.get('tpl') or u'')
            except TplError as e:
                nodes[i] = None
                ex[i] = (el, old, None, u'%s' % e)
                continue
        if nodes[i] is None:
            continue
        new, why = render(doc, el, host, r.get('tpl') or u'', tables, nodes[i])
        # пример: лучше тот, где что-то меняется; иначе — первый
        if cur is None or (new is not None and new != old) or (cur[3] is None and new is None):
            ex[i] = (el, old, new, why)
    return cnt, ex


def compute(doc, items, rules, tables):
    """Проба наименований. Ничего не пишет."""
    res = {'changes': [], 'fail': [], 'norule': [], 'same': 0, 'kept': 0, 'excl': 0,
           'counts': [0] * len(rules), 'new_name': {}}
    by = _by_cat(rules)
    nodes = {}
    for el, f in items:
        if el.Category is None:
            continue
        idx = by.get(q._iv(el.Category.Id))
        if not idx:
            continue
        old = q.pstr(doc, el, NAME_PARAM)
        if old.startswith(u'!'):
            res['excl'] += 1
            continue
        host = q.host_of(doc, el)
        i = first_rule(doc, el, host, rules, idx)
        if i is None:
            res['norule'].append((el, old))
            continue
        res['counts'][i] += 1
        r = rules[i]
        if r.get('keep'):
            res['kept'] += 1
            continue
        if i not in nodes:
            try:
                nodes[i] = parse(r.get('tpl') or u'')
            except TplError:
                nodes[i] = None
        new, why = render(doc, el, host, r.get('tpl') or u'', tables, nodes[i])
        if new is None:
            res['fail'].append((el, old, i, why))
            continue
        if new == old:
            res['same'] += 1
            continue
        p = q.find_param(doc, el, NAME_PARAM)
        if p is None:
            res['fail'].append((el, old, i, u'нет параметра ' + NAME_PARAM))
            continue
        if p.IsReadOnly or q._iv(p.Element.Id) != q._iv(el.Id):
            res['fail'].append((el, old, i, u'наименование только для чтения (формула или параметр типа)'))
            continue
        res['changes'].append((el, old, new, i))
        res['new_name'][q._iv(el.Id)] = new
    return res


# ------------------------------------------------------------------ разделы и сортировка
def _ws_name(doc, el):
    try:
        return doc.GetWorksetTable().GetWorkset(el.WorksetId).Name
    except Exception:
        return u''


def _rank(dev, order):
    for i, x in enumerate(order):
        if x and x in dev:
            return i
    return len(order)


def eq_key(doc, el, code, nm, order):
    s = lambda n: q.pstr(doc, el, n)
    mk = s(u'ADSK_Марка').strip()
    dev = s(u'ADSK_Имя устройства')
    pos = s(u'db_Позиция')
    mf = s(u'ADSK_Завод-изготовитель').upper()
    tail = u'|' + nm + u'|' + mk
    if code == u'01' and pos:
        try:
            return u'1|%07.2f|%s' % (float(pos.replace(u',', u'.')), dev) + tail
        except Exception:
            pass
    if u'LG' in mf:
        if nm.startswith(u'Наружный блок'):
            return u'2|%d|%s' % (_rank(dev, order), dev) + tail
        if nm.startswith(u'Внутренний блок') or nm.startswith(u'Гидромодуль'):
            return u'3|%d|%s' % (_rank(dev, order), dev) + tail
        return u'4' + tail
    return u'5|' + code + tail


def section_of(doc, el, code, sect_map):
    """Раздел по коду. Код 25 (изоляция труб) — по основе: дренаж (код основы 23/24 или рабочий набор
    db_Дренаж) → раздел кода 23, иначе → раздел кода 21."""
    if code == u'25':
        h = q.host_of(doc, el)
        hc = q.pstr(doc, h, CODE_PARAM) if h is not None else u''
        drain = hc in (u'23', u'24') or (h is not None and _ws_name(doc, h) == u'db_Дренаж')
        return sect_map.get(u'23' if drain else u'21', (u'', u''))[0]
    return sect_map.get(code, (u'', u''))[0]


def compute_sections(doc, items, st, new_names):
    """(изменения, ключи_вручную).
    изменения: [(эл, наименование, параметр, было, станет)] — db_Категория (если пусто), db_Единица измерения
    (если пусто), db_Раздел, db_Сортировка. new_names — наименования, которые запишутся (id → новое).
    Ключ сортировки, заданный не по формуле (не кончается на «|наименование|марка»), не трогаем — он в списке
    ключи_вручную: [(эл, наименование, ключ_сейчас, ключ_по_формуле)]."""
    sect_map = {}
    for r in st.get('sections') or []:
        if r and r[0]:
            sect_map[(r[0] or u'').strip()] = ((r[1] if len(r) > 1 else u'') or u'', (r[2] if len(r) > 2 else u'') or u'')
    cat_codes = dict((q.cat_id(r[0]), (r[1] or u'').strip()) for r in (st.get('cat_codes') or [])
                     if r and r[0] and len(r) > 1 and r[1])
    order = [x for x in (st.get('eq_order') or []) if x]
    out = []
    manual = []
    for el, f in items:
        if el.Category is None:
            continue
        old_nm = q.pstr(doc, el, NAME_PARAM)
        nm = new_names.get(q._iv(el.Id))
        if nm is None:
            nm = old_nm
        if nm.startswith(u'!'):
            continue
        code = q.pstr(doc, el, CODE_PARAM)
        if not code:
            c2 = cat_codes.get(q._iv(el.Category.Id))
            if not c2:
                continue
            out.append((el, nm, CODE_PARAM, u'', c2))
            code = c2
        if code not in sect_map:
            continue
        unit = sect_map[code][1]
        if unit and not q.pstr(doc, el, UNIT_PARAM):
            out.append((el, nm, UNIT_PARAM, u'', unit))
        sect = section_of(doc, el, code, sect_map)
        if sect:
            cur = q.pstr(doc, el, SECT_PARAM)
            if cur != sect:
                out.append((el, nm, SECT_PARAM, cur, sect))
        if code in NO_SORT_CODES:
            continue
        if sect.startswith(u'1.'):
            key = eq_key(doc, el, code, nm, order)
        else:
            key = code + u'|' + nm + u'|' + q.pstr(doc, el, u'ADSK_Марка').strip()
        cur = q.pstr(doc, el, SORT_PARAM)
        if cur == key:
            continue
        mk = q.pstr(doc, el, u'ADSK_Марка')
        if cur and not (cur.endswith(u'|' + old_nm + u'|' + mk.strip()) or cur.endswith(u'|' + old_nm + u'|' + mk)):
            manual.append((el, nm, cur, key))
            continue
        out.append((el, nm, SORT_PARAM, cur, key))
    return out, manual


# ------------------------------------------------------------------ запись
def _set(el, name, v):
    p = el.LookupParameter(name)
    if p is None or p.IsReadOnly or p.StorageType != StorageType.String:
        return False
    p.Set(v)
    return True


def apply(doc, changes, sect_changes):
    """Внутри транзакции. (наименований, прочих значений, ошибок)."""
    nn = ns = ne = 0
    for el, old, new, i in changes:
        try:
            if _set(el, NAME_PARAM, new):
                nn += 1
            else:
                ne += 1
        except Exception:
            ne += 1
    for el, nm, par, old, new in sect_changes:
        try:
            if _set(el, par, new):
                ns += 1
            else:
                ne += 1
        except Exception:
            ne += 1
    return nn, ns, ne
