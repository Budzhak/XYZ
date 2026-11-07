# -*- coding: utf-8 -*-

# ============================================================
# БЛОК 1. Импорты
# ============================================================
from pyrevit import revit, forms, script
import xyz_forms as forms   # единый стиль окон XYZ (lib/xyz_forms.py)
from Autodesk.Revit.DB import *
from Autodesk.Revit.Exceptions import OperationCanceledException

doc = revit.doc
uidoc = revit.uidoc
view = doc.ActiveView

# Рабочая плоскость схемы (lib/xyz_plane.py, 17.10.2026): в покое — горизонтальная.
# Сбитая плоскость (после сбоя команды или ручных действий) ломает выноски и
# уводит текст высотных отметок от полки — проверяем в начале каждой команды.
import sys as _hp_sys
_hp_sys.modules.pop('xyz_plane', None)
import xyz_plane as _hp
try:
    _plane_was = _hp.ensure_flat(doc, view, u'По красоте (начало)')
except Exception:
    _plane_was = None
if _plane_was:
    forms.alert(u"Рабочая плоскость вида была {} — поставлена горизонтальная.\n\n"
                u"Если с тех пор, как она сменилась, вручную ставились или двигались "
                u"высотные отметки и марки — проверьте их: при такой плоскости текст "
                u"отметок уезжает от полки, а выноски могут ломаться.".format(
                    _hp.NAMES.get(_plane_was, _plane_was)),
                title=u"Рабочая плоскость")


# ============================================================
# БЛОК 2. Получение выделенных марок (IndependentTag)
# ============================================================
selected_ids = uidoc.Selection.GetElementIds()

tags = []
for eid in selected_ids:
    el = doc.GetElement(eid)
    if isinstance(el, IndependentTag):
        tags.append(el)

# Выделенные НЕ марки - область для режима "Умные выноски"
other_selected = []
for eid in selected_ids:
    el = doc.GetElement(eid)
    if el is not None and not isinstance(el, IndependentTag):
        other_selected.append(el)

ACTION_SMART = u"⚠ Умные выноски (карантин: нестабильно)"
ACTION_RENUMBER = u"Нумерация по часовой стрелке"
ACTION_CLICKNUM = u"Нумерация кликами (с введённого номера)"
ACTION_MERGE = u"Объединить одинаковые марки"
ACTION_STACK = u"Колонка с угловыми выносками (сторона по точке)"
ACTION_SPOTS = u"Высотные отметки на взрыв-схеме (по правилам)"
ACTION_PICKSPOT = u"Отметка на взрыв-схеме (выбранного элемента)"
ACTION_RESET = u"Сброс марок (выноска, сторона, длина)"
ACTION_DRESS = u"Оформить взрыв-схему по шагам (разнос, отметки, марки…)"
ACTION_DECLUTTER = u"Развести наложенные марки (обход марок, размеров, труб)"
ACTION_POLISH = u"Доводка марок: полка по тексту, прямые выноски в обход"
ACTION_SNAP = u"Конец выноски — в центр элемента"
ACTION_SPREAD = u"Выноски — равный шаг вдоль оси элемента"
ACTION_SETTINGS = u"Настройки: отступ между марками в колонке…"


# ============================================================
# БЛОК 3. Стартовое окно выбора действия
# ============================================================
right = view.RightDirection
up = view.UpDirection

ACTION_UNSTACK = u"⚠ Разнести наложенные (карантин: нестабильно)"
ACTION_MEASURE = u"Измерить шаг между отмеченными"
ACTION_REVERSE = u"Реверс выделенных"

ACTION_ALIGN_V = u"Друг под другом (вертикально)"
ACTION_ALIGN_H = u"Рядом друг с другом (горизонтально)"

# 17.10.2026: команды аннотаций вынесены отдельными кнопками на панель «Оформить»
# (lib/xyz_launch.py запускает этот скрипт с готовым выбором — sys.xyz_align_action).
# В меню «По красоте» остались только схемы, разведение и карантин.
import sys as _act_sys
_preset = getattr(_act_sys, 'xyz_align_action', None)
_act_sys.xyz_align_action = None

action_options = []
if isinstance(view, View3D):
    action_options.append(ACTION_DRESS)
if isinstance(view, View3D) and other_selected:
    action_options.append(ACTION_PICKSPOT)
    action_options.append(ACTION_SPOTS)
if not isinstance(view, View3D) or tags:
    action_options.append(ACTION_DECLUTTER)
    action_options.append(ACTION_POLISH)
if len(tags) >= 2:
    action_options.append(ACTION_UNSTACK)
action_options.append(ACTION_SMART)
action_options.append(ACTION_SETTINGS)

if _preset:
    action_choice = _preset
else:
    action_choice = forms.CommandSwitchWindow.show(
        action_options,
        message=u"Что сделать? (марки — на панели «Оформить»)"
    )

if not action_choice:
    raise SystemExit

# Карантин (lib/xyz_quarantine.py): нестабильные режимы - с предупреждением
if action_choice in (ACTION_SMART, ACTION_UNSTACK):
    import sys as _q_sys
    _q_sys.modules.pop('xyz_quarantine', None)
    import xyz_quarantine
    if not xyz_quarantine.confirm(u"Умные выноски" if action_choice == ACTION_SMART else u"Разнести наложенные"):
        raise SystemExit

# Всем командам, кроме "Умных выносок", нужны выделенные марки
# Настройки (17.10.2026): отступ колонки больше не спрашивается при каждом запуске
# «Колонки» — задаётся здесь (или Shift+щелчок по кнопке «Колонка»)
def _ask_stack_spacing():
    _cfg = script.get_config('xyz_align')
    _sp = forms.ask_for_string(default=_cfg.get_option('stack_spacing_mm', u"1.0"),
                               prompt=u"Отступ между рамками марок в колонке, мм на листе\n"
                                      u"(от масштаба вида не зависит; запоминается)",
                               title=u"Колонка марок — настройки")
    if _sp is None:
        return None
    try:
        _v = max(0.0, float(_sp.replace(u",", u".")))
    except Exception:
        forms.alert(u"Нужно число, например 1 или 1,5.", title=u"Колонка марок")
        return None
    _cfg.stack_spacing_mm = str(_v)
    script.save_config()
    return _v


if action_choice == ACTION_SETTINGS:
    _ask_stack_spacing()
    raise SystemExit

if action_choice not in (ACTION_SMART, ACTION_CLICKNUM, ACTION_SPOTS, ACTION_PICKSPOT, ACTION_RESET, ACTION_DRESS, ACTION_DECLUTTER, ACTION_POLISH, ACTION_SNAP, ACTION_SPREAD) and not tags:
    forms.alert(u"Не выделено ни одной марки (IndependentTag).\n\n"
                u"Выделите марки и запустите инструмент снова.",
                title=u"Выравнивание марок")
    raise SystemExit


# ============================================================
# БЛОК 4. Режим "Измерить шаг" - считает шаг между уже выделенными
# марками (например, из ровного эталонного ряда) и сохраняет
# среднее значение, чтобы при следующем запуске "Выравнивания"
# оно подставилось по умолчанию
# ============================================================
if action_choice == ACTION_MEASURE:
    positions = [t.TagHeadPosition for t in tags]
    right_vals = [p.DotProduct(right) for p in positions]
    up_vals = [p.DotProduct(up) for p in positions]

    spread_right = max(right_vals) - min(right_vals)
    spread_up = max(up_vals) - min(up_vals)

    m_is_vertical = spread_up >= spread_right

    if m_is_vertical:
        sorted_coords = sorted(up_vals, reverse=True)
        direction_label = u"вертикально"
    else:
        sorted_coords = sorted(right_vals)
        direction_label = u"горизонтально"

    diffs_ft = [abs(sorted_coords[i] - sorted_coords[i + 1])
                for i in range(len(sorted_coords) - 1)]
    diffs_mm = [round(d * 304.8, 2) for d in diffs_ft]
    avg_mm = round(sum(diffs_mm) / len(diffs_mm), 2)
    min_mm = min(diffs_mm)
    max_mm = max(diffs_mm)

    config = script.get_config('xyz_align')
    config.last_measured_step_mm = str(avg_mm)
    script.save_config()

    report_lines = [
        u"Направление (авто-определено): {}".format(direction_label),
        u"Марок: {}".format(len(tags)),
        u"",
        u"Средний шаг: {} мм".format(avg_mm),
        u"Мин. шаг: {} мм".format(min_mm),
        u"Макс. шаг: {} мм".format(max_mm),
    ]

    if len(diffs_mm) > 1:
        report_lines.append(u"")
        report_lines.append(u"Все шаги (мм): {}".format(
            u", ".join(str(d) for d in diffs_mm)))

    if max_mm - min_mm > 0.5:
        report_lines.append(u"")
        report_lines.append(u"Внимание: шаги между разными парами марок заметно "
                            u"отличаются - возможно, выделены марки не из одного "
                            u"ровного ряда.")

    report_lines.append(u"")
    report_lines.append(u"Среднее значение сохранено - при следующем запуске "
                        u"выравнивания оно подставится по умолчанию.")

    forms.alert(u"\n".join(report_lines), title=u"Измерить шаг")
    raise SystemExit


# ============================================================
# БЛОК 4Б. Режим "Разнести наложенные (без шага)"
# Марки остаются на своих местах; только те, что наезжают друг
# на друга, раскладываются "лесенкой": разные уровни по высоте
# (симметрично относительно исходной линии ряда) и небольшой
# сдвиг вбок на полширины марки - чтобы выноска нижней марки
# не проходила сквозь верхнюю. Порядок в лесенке - по положению
# помеченных элементов, чтобы выноски не перекрещивались.
# ============================================================
def _eid_int(eid):
    try:
        return eid.Value
    except Exception:
        return eid.IntegerValue


def _box_ranges(bb, vec_a, vec_c):
    # Габарит в осях вида (bb может иметь собственный Transform)
    tr = bb.Transform
    a_vals, c_vals = [], []
    for x in (bb.Min.X, bb.Max.X):
        for y in (bb.Min.Y, bb.Max.Y):
            for z in (bb.Min.Z, bb.Max.Z):
                p = tr.OfPoint(XYZ(x, y, z))
                a_vals.append(p.DotProduct(vec_a))
                c_vals.append(p.DotProduct(vec_c))
    return min(a_vals), max(a_vals), min(c_vals), max(c_vals)


def _element_point(tag, near_point):
    # Точка помеченного элемента, куда "смотрит" выноска
    try:
        for tid in tag.GetTaggedLocalElementIds():
            el = doc.GetElement(tid)
            if el is None:
                continue
            loc = el.Location
            if isinstance(loc, LocationPoint):
                return loc.Point
            if isinstance(loc, LocationCurve):
                res = loc.Curve.Project(near_point)
                if res is not None:
                    return res.XYZPoint
                return loc.Curve.Evaluate(0.5, True)
            bb = el.get_BoundingBox(view)
            if bb is not None:
                return (bb.Min + bb.Max) * 0.5
    except Exception:
        pass
    return near_point


def _boxes_overlap(p, q, margin):
    return (p['na'] + p['a0'] < q['na'] + q['a1'] + margin and
            q['na'] + q['a0'] < p['na'] + p['a1'] + margin and
            p['nc'] + p['c0'] < q['nc'] + q['c1'] + margin and
            q['nc'] + q['c0'] < p['nc'] + p['c1'] + margin)


if action_choice == ACTION_UNSTACK:
    orig = {}
    for tag in tags:
        orig[tag.Id] = tag.TagHeadPosition

    # Ориентация ряда: вдоль какой оси вида разнесены марки
    _r = [orig[t.Id].DotProduct(right) for t in tags]
    _u = [orig[t.Id].DotProduct(up) for t in tags]
    if (max(_r) - min(_r)) >= (max(_u) - min(_u)):
        vec_a, vec_c = right, up      # горизонтальный ряд, уровни - по высоте
    else:
        vec_a, vec_c = up, right      # вертикальный столбец, уровни - вбок

    # Габарит "головы" марки. Прямо get_BoundingBox брать нельзя: Revit
    # включает в габарит марки и точку на помеченном элементе (даже без
    # выноски). Поэтому ставим два временных "двойника" марки далеко от
    # элемента - один вверх-вправо (даёт верхний правый угол головы),
    # другой вниз-влево (нижний левый угол). Транзакция откатывается.
    far = 2000.0 * view.Scale / 304.8          # 2 м листа
    diag = vec_a + vec_c
    items = []
    t_m = Transaction(doc, u"Замер марок")
    t_m.Start()
    try:
        twins = []
        for tag in tags:
            h = orig[tag.Id]
            try:
                ref = list(tag.GetTaggedReferences())[0]
                ta = IndependentTag.Create(doc, tag.GetTypeId(), view.Id, ref, False,
                                           tag.TagOrientation, h + diag * far)
                tb = IndependentTag.Create(doc, tag.GetTypeId(), view.Id, ref, False,
                                           tag.TagOrientation, h - diag * far)
                twins.append((tag, ta, tb))
            except Exception:
                twins.append((tag, None, None))
        doc.Regenerate()
        for tag, ta, tb in twins:
            h = orig[tag.Id]
            ha, hc = h.DotProduct(vec_a), h.DotProduct(vec_c)
            rel = None
            try:
                if ta is not None:
                    ba, bb_ = ta.get_BoundingBox(view), tb.get_BoundingBox(view)
                    pa, pb = ta.TagHeadPosition, tb.TagHeadPosition
                    _, a1, _, c1 = _box_ranges(ba, vec_a, vec_c)
                    a0, _, c0, _ = _box_ranges(bb_, vec_a, vec_c)
                    rel = (a0 - pb.DotProduct(vec_a), a1 - pa.DotProduct(vec_a),
                           c0 - pb.DotProduct(vec_c), c1 - pa.DotProduct(vec_c))
                    if rel[1] <= rel[0] or rel[3] <= rel[2]:
                        rel = None
            except Exception:
                rel = None
            if rel is None:
                mm1 = view.Scale / 304.8
                rel = (-6 * mm1, 6 * mm1, -2.5 * mm1, 2.5 * mm1)
            items.append({
                'tag': tag, 'a': ha, 'c': hc,
                'a0': rel[0], 'a1': rel[1], 'c0': rel[2], 'c1': rel[3],
                'ref': _element_point(tag, h).DotProduct(vec_a),
                'na': ha, 'nc': hc,
            })
    finally:
        t_m.RollBack()

    w_max = max(i['a1'] - i['a0'] for i in items)
    h_max = max(i['c1'] - i['c0'] for i in items)
    step_a = 0.65 * w_max     # сдвиг вбок: больше полширины - выноска не задевает соседа
    step_c = 1.25 * h_max     # шаг по высоте: высота марки + зазор
    margin = 0.05 * h_max

    # Группы наложенных марок (union-find)
    parent = list(range(len(items)))

    def _find(i):
        while parent[i] != i:
            parent[i] = parent[parent[i]]
            i = parent[i]
        return i

    def _union(i, j):
        ri, rj = _find(i), _find(j)
        if ri != rj:
            parent[rj] = ri
            return True
        return False

    for i in range(len(items)):
        for j in range(i + 1, len(items)):
            if _boxes_overlap(items[i], items[j], 0.0):
                _union(i, j)

    def _layout(mirror):
        groups = {}
        for i in range(len(items)):
            groups.setdefault(_find(i), []).append(items[i])
        n_moved = 0
        for g in groups.values():
            if len(g) == 1:
                g[0]['na'], g[0]['nc'] = g[0]['a'], g[0]['c']
                continue
            n = len(g)
            n_moved += n
            center_a = sum(i['a'] for i in g) / float(n)
            center_c = sum(i['c'] for i in g) / float(n)
            order = sorted(g, key=lambda i: (round(i['ref'], 6), round(i['a'], 6),
                                             _eid_int(i['tag'].Id)))
            sign = -1.0 if mirror else 1.0
            for k, it in enumerate(order):
                off = k - (n - 1) / 2.0
                it['na'] = center_a + off * step_a
                it['nc'] = center_c + sign * off * step_c
        return n_moved

    def _solve(mirror):
        # Если разложенная группа задела соседнюю марку - объединяем
        # их в одну группу и раскладываем заново
        n_moved = 0
        for _ in range(100):
            n_moved = _layout(mirror)
            merged = False
            for i in range(len(items)):
                for j in range(i + 1, len(items)):
                    if _find(i) != _find(j) and _boxes_overlap(items[i], items[j], margin):
                        merged = _union(i, j) or merged
            if not merged:
                break
        return n_moved

    def _apply(use_new):
        for it in items:
            h = orig[it['tag'].Id]
            if use_new:
                h = h + vec_a * (it['na'] - it['a']) + vec_c * (it['nc'] - it['c'])
            it['tag'].TagHeadPosition = h

    def _run_transaction(name, use_new):
        t = Transaction(doc, name)
        t.Start()
        try:
            _apply(use_new)
            status = t.Commit()
        except Exception:
            if t.HasStarted() and not t.HasEnded():
                t.RollBack()
            raise
        if status != TransactionStatus.Committed:
            raise Exception(u"Транзакция не зафиксирована: {}".format(status))
        uidoc.RefreshActiveView()

    OPT_ACCEPT = u"Принять"
    OPT_MIRROR = u"Отразить лесенку"
    OPT_CANCEL = u"Отмена (вернуть как было)"

    def _run_unstack():
        n_moved = _solve(False)
        if n_moved == 0:
            forms.alert(u"Наложенных друг на друга марок не найдено.",
                        title=u"Разнести наложенные")
            return

        mirror = False
        _run_transaction(u"Разнести наложенные марки", True)
        while True:
            choice = forms.CommandSwitchWindow.show(
                [OPT_ACCEPT, OPT_MIRROR, OPT_CANCEL],
                message=u"Разнесено марок: {}. Что сделать?".format(n_moved))
            if choice == OPT_ACCEPT:
                return
            if choice == OPT_MIRROR:
                mirror = not mirror
                _solve(mirror)
                _run_transaction(u"Отразить лесенку", True)
                continue
            # Отмена или закрытие окна (Esc) - возвращаем исходное положение
            _run_transaction(u"Отмена разнесения марок", False)
            return

    try:
        _run_unstack()
    except Exception as ex:
        forms.alert(u"Ошибка:\n\n{}".format(ex), title=u"Ошибка")


# ============================================================
# БЛОК 4В. Режим "Реверс выделенных"
# Марки меняются местами: порядок позиций вдоль ряда/столбца
# переворачивается (для двух марок - просто обмен местами).
# Выноски перестраиваются Revit автоматически.
# ============================================================
if action_choice == ACTION_REVERSE:
    rev_pos = [(t, t.TagHeadPosition) for t in tags]
    _r = [p.DotProduct(right) for _, p in rev_pos]
    _u = [p.DotProduct(up) for _, p in rev_pos]
    if (max(_r) - min(_r)) >= (max(_u) - min(_u)):
        rev_pos.sort(key=lambda tp: (tp[1].DotProduct(right), -tp[1].DotProduct(up)))
    else:
        rev_pos.sort(key=lambda tp: (-tp[1].DotProduct(up), tp[1].DotProduct(right)))

    rev_tags = [tp[0] for tp in rev_pos]
    rev_points = [tp[1] for tp in rev_pos]
    rev_points.reverse()

    t_rev = Transaction(doc, u"Реверс марок")
    t_rev.Start()
    try:
        for tag, p in zip(rev_tags, rev_points):
            tag.TagHeadPosition = p
        status = t_rev.Commit()
        if status != TransactionStatus.Committed:
            forms.alert(u"Транзакция не зафиксирована: {}".format(status), title=u"Ошибка")
    except Exception as ex:
        if t_rev.HasStarted() and not t_rev.HasEnded():
            t_rev.RollBack()
        forms.alert(u"Ошибка при реверсе:\n\n{}".format(ex), title=u"Ошибка")
    uidoc.RefreshActiveView()


# ============================================================
# БЛОК 4Г. Режим "Умные выноски" - автоматическая расстановка марок
# на виде без пересечений (код - в smart_tags.py рядом со script.py)
# ============================================================
if action_choice == ACTION_SMART:
    import os
    import sys
    _here = os.path.dirname(os.path.abspath(__file__))
    if _here not in sys.path:
        sys.path.insert(0, _here)
    try:
        sys.modules.pop('smart_tags', None)   # всегда свежая версия модуля (без перезапуска Revit)
        import smart_tags
        smart_tags.run(doc, uidoc, other_selected)
    except Exception as ex:
        import traceback
        forms.alert(u"Ошибка в «Умных выносках»:\n\n{}".format(traceback.format_exc()),
                    title=u"Ошибка")


# ============================================================
# БЛОК 4Г2. "Колонка с угловыми выносками" - марки друг под другом,
# выноски ломаные под прямым углом без пересечений (stack_tags.py)
# ============================================================
if action_choice == ACTION_STACK:
    import os
    import sys
    _here = os.path.dirname(os.path.abspath(__file__))
    if _here not in sys.path:
        sys.path.insert(0, _here)
    try:
        sys.modules.pop('smart_tags', None)
        sys.modules.pop('stack_tags', None)
        import stack_tags
        # сторона колонки - по точке вставки (правее элементов -
        # колонка справа, по левому краю; левее - слева, по правому краю)
        _var = 0
        # отступ — из настроек (без окна); Shift+щелчок по кнопке — сначала окно настроек
        try:
            _shift = bool(__shiftclick__)    # noqa: F821  (pyRevit)
        except NameError:
            _shift = False
        if _shift:
            _spv = _ask_stack_spacing()
        else:
            try:
                _spv = max(0.0, float(script.get_config('xyz_align').get_option('stack_spacing_mm', u"1.0")))
            except Exception:
                _spv = 1.0
        if _spv is not None:
                stack_tags.run(doc, uidoc, tags, _var, spacing_mm=_spv, interactive=True)
                if stack_tags.LAST_BAD:
                    try:
                        from System.Collections.Generic import List as _L
                        uidoc.Selection.SetElementIds(_L[ElementId](stack_tags.LAST_BAD))
                    except Exception:
                        pass
                    forms.alert(u"Не удалось выстроить выноски у {} марок (выделены).\n\n"
                                u"Подробности — в журнале %TEMP%\\zb_plane_log.txt.".format(
                                    len(stack_tags.LAST_BAD)),
                                title=u"Колонка марок")
    except Exception as ex:
        import traceback
        forms.alert(u"Ошибка в «Колонке марок»:\n\n{}".format(traceback.format_exc()),
                    title=u"Ошибка")


# ============================================================
# БЛОК 4Г3. "Сброс марок" - тип выноски, сторона, длина выноски,
# ровная выноска без излома (reset_tags.py рядом со script.py)
# ============================================================
if action_choice == ACTION_RESET:
    import os
    import sys
    _here = os.path.dirname(os.path.abspath(__file__))
    if _here not in sys.path:
        sys.path.insert(0, _here)
    try:
        sys.modules.pop('stack_tags', None)
        sys.modules.pop('reset_tags', None)
        import reset_tags
        _cfg = script.get_config('xyz_align')
        _set = reset_tags.ask(_cfg)          # прошлые настройки подставляются сами
        if _set:
            script.save_config()
            # выделенные заранее марки - сразу, дальше щелчками по одной, Esc - готово
            reset_tags.pick_loop(doc, uidoc, _set, tags)
    except Exception as ex:
        import traceback
        forms.alert(u"Ошибка в «Сбросе марок»:\n\n{}".format(traceback.format_exc()),
                    title=u"Ошибка")


# ============================================================
# БЛОК 4Г5. "Оформить взрыв-схему по шагам" - разнос, отметки, марки систем,
# полупрозрачность, клапаны, шумоглушители, оборудование, тройники (dress_scheme.py)
# ============================================================
if action_choice == ACTION_DRESS:
    import os
    import sys
    _here = os.path.dirname(os.path.abspath(__file__))
    if _here not in sys.path:
        sys.path.insert(0, _here)
    try:
        for _m in ('dress_scheme', 'stack_tags', 'xyz_elev_marks'):
            sys.modules.pop(_m, None)
        import dress_scheme
        _cfg = script.get_config('xyz_align')
        _labels = [x[1] for x in dress_scheme.STEPS]
        _strict_lbl = u"Тройники: строже (и при одном переходе)"
        _res = forms.CommandSwitchWindow.show(
            _labels, message=u"Оформить взрыв-схему: какой шаг?",
            switches={_strict_lbl: _cfg.get_option('dress_strict', u'0') == u'1'})
        _choice, _states = _res if isinstance(_res, tuple) else (_res, {})
        if _choice:
            _step = [x[0] for x in dress_scheme.STEPS if x[1] == _choice][0]
            _strict = bool(_states.get(_strict_lbl))
            _cfg.dress_strict = u'1' if _strict else u'0'
            _elems = list(other_selected) or None
            _go = True
            _off = 0.0
            if _step in ('explode', 'transp', 'addto', 'fan', 'eqtags') and not _elems:
                forms.alert(u"Для этого шага выделите элементы на виде.", title=_choice)
                _go = False
            if _go and _step == 'explode':
                _s = forms.ask_for_string(default=_cfg.get_option('dress_offset', u"2500"),
                                          prompt=u"На сколько сместить выделенное, мм модели\n"
                                                 u"(плюс — вверх, минус — вниз)",
                                          title=_choice)
                if _s is None:
                    _go = False
                else:
                    try:
                        _off = float(_s.replace(u",", u".").replace(u" ", u""))
                        _cfg.dress_offset = _s
                    except Exception:
                        forms.alert(u"Нужно число, например 2500 или -1500.", title=_choice)
                        _go = False
            if _go and _step == 'fan':
                # 01.11.2026: веер лучей от коллекторов (dress_fan.py) — шаг между лучами на листе
                _s = forms.ask_for_string(default=_cfg.get_option('dress_fan_gap', u"2.5"),
                                          prompt=u"Шаг между лучами на листе, мм\n"
                                                 u"(лучи коллектора разносятся по высоте веером)",
                                          title=_choice)
                if _s is None:
                    _go = False
                else:
                    try:
                        _off = float(_s.replace(u",", u".").replace(u" ", u""))
                        if _off <= 0:
                            raise ValueError
                        _cfg.dress_fan_gap = _s
                    except Exception:
                        forms.alert(u"Нужно положительное число, например 2.5.", title=_choice)
                        _go = False
            _pick = None
            if _go and _step == 'elev':
                # окно выбора, как в «Распознать»: каким объектам ставить отметки
                sys.modules.pop('xyz_pick', None)
                import xyz_pick
                _cand = dress_scheme.elev_candidates(doc, view, _elems)
                if not _cand:
                    forms.alert(u"На виде нет труб, воздуховодов, оборудования или арматуры.", title=_choice)
                    _go = False
                else:
                    _prev = set((_cfg.get_option('dress_elev_pick', u'') or u'').split(u'\n')) - {u''}

                    def _chk(key, el, _prev=_prev):
                        if _prev:
                            return u' | '.join(key) in _prev
                        return dress_scheme.elev_default(key, el)
                    _pick = xyz_pick.pick_groups(
                        doc, _cand, u"Высотные отметки: для каких объектов?",
                        ok_text=u"Поставить отметки", checked=_chk,
                        note=(u"Источник: выделенное ({} шт.).".format(len(_cand)) if _elems else
                              u"Источник: весь вид «{}».".format(view.Name)) +
                             u" Трубы — отметка там, где меняется высота; оборудование, арматура и др. — низ."
                             u" Уже отмеченное не трогается. Выбор запоминается.")
                    if _pick is None:
                        _go = False
                    else:
                        _keys = set()
                        for _i in _pick:
                            _e = doc.GetElement(_i)
                            if _e is not None:
                                _keys.add(u' | '.join(xyz_pick.group_key(doc, _e)[0]))
                        _cfg.dress_elev_pick = u'\n'.join(sorted(_keys))
            if _go and _step not in ('explode', 'transp', 'paths', 'paths_reset', 'addto', 'elev') and not _elems:
                _go = forms.alert(u"Ничего не выделено — оформить весь вид?", title=_choice, yes=True, no=True)
            script.save_config()
            if _go:
                _tg = TransactionGroup(doc, _choice)
                _tg.Start()
                try:
                    _msg, _skipped = dress_scheme.run_step(doc, uidoc, _step, None if _pick is not None else _elems,
                                                           _strict, _off, _pick)
                    _tg.Assimilate()
                except Exception:
                    _tg.RollBack()
                    raise
                if _skipped:
                    from System.Collections.Generic import List as _L
                    uidoc.Selection.SetElementIds(_L[ElementId](_skipped))
                forms.alert(_msg + u"\n\nПосмотрите результат, поправьте вручную и запускайте следующий шаг.",
                            title=_choice)
    except Exception as ex:
        import traceback
        forms.alert(u"Ошибка в «Оформить взрыв-схему»:\n\n{}".format(traceback.format_exc()),
                    title=u"Ошибка")


# ============================================================
# БЛОК 4Г4. "Отметка на взрыв-схеме (выбранного элемента)" - марка-отметка
# на заранее выделенных элементах: прямоугольный - низ, круглый - ось (lib/xyz_elev_marks.py)
# ============================================================
if action_choice == ACTION_PICKSPOT:
    try:
        import sys
        sys.modules.pop('xyz_elev_marks', None)
        import xyz_elev_marks
        # 17.10.2026: вместо списка строк — 4 кнопки-картинки 2×2 (xyz_forms.pick_spot_side)
        _side = forms.pick_spot_side(u"Отметка на взрыв-схеме")
        if _side:
            xyz_elev_marks.place_selected(doc, uidoc, other_selected, _side,
                                      alert=lambda m: forms.alert(m, title=u"Отметка"))
    except Exception as ex:
        import traceback
        forms.alert(u"Ошибка в «Отметке на взрыв-схеме»:\n\n{}".format(traceback.format_exc()),
                    title=u"Ошибка")


# ============================================================
# БЛОК 4Г3. "Высотные отметки на взрыв-схеме" (spot_marks.py)
# ============================================================
if action_choice == ACTION_SPOTS:
    import os
    import sys
    _here = os.path.dirname(os.path.abspath(__file__))
    if _here not in sys.path:
        sys.path.insert(0, _here)
    try:
        sys.modules.pop('spot_marks', None)
        import spot_marks
        _filters = []
        for _fid in view.GetFilters():
            _f = doc.GetElement(_fid)
            if isinstance(_f, ParameterFilterElement):
                _filters.append(_f.Name)
        _none = u"(все воздуховоды на виде)"
        _fi = forms.CommandSwitchWindow.show([_none] + _filters,
                                             message=u"Текущий объём в монтаж (фильтр вида):")
        if _fi:
            _fe = forms.CommandSwitchWindow.show([u"(не исключать)"] + _filters,
                                                 message=u"Ранее выданный объём (фильтр вида):")
            _set = {'f_inc': _fi if _fi != _none else None,
                    'f_exc': _fe if _fe and _fe != u"(не исключать)" else None}
            _t = Transaction(doc, u"Высотные отметки на взрыв-схеме")
            _t.Start()
            _rep = spot_marks.run(doc, uidoc, _set)
            _t.Commit()
            forms.alert(_rep, title=u"Высотные отметки")
    except Exception as ex:
        import traceback
        try:
            if _t.HasStarted() and not _t.HasEnded():
                _t.RollBack()
        except Exception:
            pass
        forms.alert(u"Ошибка в «Высотных отметках»:\n\n{}".format(traceback.format_exc()),
                    title=u"Ошибка")


# ============================================================
# БЛОК 4Д. "Нумерация по часовой стрелке" - записывает номера в параметр
# элементов выделенных марок, обходя их по кругу (код - в renumber.py)
# ============================================================
if action_choice in (ACTION_RENUMBER, ACTION_CLICKNUM):
    import os
    import sys
    _here = os.path.dirname(os.path.abspath(__file__))
    if _here not in sys.path:
        sys.path.insert(0, _here)
    try:
        sys.modules.pop('renumber', None)   # всегда свежая версия модуля (без перезапуска Revit)
        import renumber
        if action_choice == ACTION_CLICKNUM:
            renumber.run_click(doc, uidoc)
        else:
            renumber.run(doc, uidoc, tags)
    except Exception as ex:
        import traceback
        forms.alert(u"Ошибка нумерации:\n\n{}".format(traceback.format_exc()),
                    title=u"Ошибка")


# ============================================================
# БЛОК 4Е. "Объединить одинаковые марки" - одна марка с несколькими
# основами вместо нескольких одинаковых (код - в merge_tags.py)
# ============================================================
if action_choice == ACTION_MERGE:
    import os
    import sys
    _here = os.path.dirname(os.path.abspath(__file__))
    if _here not in sys.path:
        sys.path.insert(0, _here)
    try:
        sys.modules.pop('merge_tags', None)   # всегда свежая версия модуля (без перезапуска Revit)
        import merge_tags
        merge_tags.run(doc, uidoc, tags)
    except Exception as ex:
        import traceback
        forms.alert(u"Ошибка объединения:\n\n{}".format(traceback.format_exc()),
                    title=u"Ошибка")


# ============================================================
# БЛОК 4З. "Конец выноски — в центр элемента": у марок со свободным
# концом выноски конец переносится на ось трубы/воздуховода или в центр
# семейства (с учётом разноса). Код - в leader_snap.py
# ============================================================
if action_choice == ACTION_SNAP:
    import os
    import sys
    _here = os.path.dirname(os.path.abspath(__file__))
    if _here not in sys.path:
        sys.path.insert(0, _here)
    try:
        sys.modules.pop('leader_snap', None)
        import leader_snap
        leader_snap.run(doc, uidoc, tags)
    except Exception as ex:
        import traceback
        forms.alert(u"Ошибка переноса выносок:\n\n{}".format(traceback.format_exc()),
                    title=u"Ошибка")


# ============================================================
# БЛОК 4И. "Выноски — равный шаг вдоль трубы": марки на месте, концы
# выносок едут вдоль оси трубы, вертикальные участки - с равным шагом.
# Код - в leader_spread.py
# ============================================================
if action_choice == ACTION_SPREAD:
    import os
    import sys
    _here = os.path.dirname(os.path.abspath(__file__))
    if _here not in sys.path:
        sys.path.insert(0, _here)
    try:
        sys.modules.pop('leader_spread', None)
        import leader_spread
        _cfg = script.get_config('xyz_align')
        leader_spread.run(doc, uidoc, tags, _cfg)
        script.save_config()
    except Exception as ex:
        import traceback
        forms.alert(u"Ошибка «Выноски — равный шаг»:\n\n{}".format(traceback.format_exc()),
                    title=u"Ошибка")


# ============================================================
# БЛОК 4Ж. "Развести наложенные марки" - марки, наехавшие на марки,
# номера помещений, размеры и тексты, уходят на ближайшее свободное
# место с выноской; трубы и воздуховоды по возможности обходятся
# (код - в declutter_tags.py)
# ============================================================
if action_choice == ACTION_DECLUTTER:
    import os
    import sys
    _here = os.path.dirname(os.path.abspath(__file__))
    if _here not in sys.path:
        sys.path.insert(0, _here)
    try:
        sys.modules.pop('declutter_tags', None)   # всегда свежая версия модуля
        import declutter_tags
        declutter_tags.run(doc, uidoc, tags)
    except Exception as ex:
        import traceback
        forms.alert(u"Ошибка раскладки марок:\n\n{}".format(traceback.format_exc()),
                    title=u"Ошибка")


# ============================================================
# БЛОК 4Ж2. "Доводка марок" (01.11.2026): после «Развести наложенные» — полки
# ADSK_Марка_* по длине текста, плохие марки на прямую выноску / «Г» в обход
# (код - в tag_polish.py)
# ============================================================
if action_choice == ACTION_POLISH:
    import os
    import sys
    _here = os.path.dirname(os.path.abspath(__file__))
    if _here not in sys.path:
        sys.path.insert(0, _here)
    try:
        sys.modules.pop('tag_polish', None)   # всегда свежая версия модуля
        import tag_polish
        tag_polish.run(doc, uidoc, tags)
    except Exception as ex:
        import traceback
        forms.alert(u"Ошибка доводки марок:\n\n{}".format(traceback.format_exc()),
                    title=u"Ошибка")


# ============================================================
# Режимы выравнивания (для "Разнести наложенные" и "Реверс" - не выполняются,
# скрипт просто доходит до конца без SystemExit)
# ============================================================
if action_choice not in (ACTION_STACK, ACTION_RESET, ACTION_DECLUTTER, ACTION_POLISH, ACTION_SNAP, ACTION_SPREAD, ACTION_DRESS, ACTION_SPOTS, ACTION_PICKSPOT, ACTION_UNSTACK, ACTION_REVERSE, ACTION_SMART, ACTION_RENUMBER,
                         ACTION_MERGE, ACTION_CLICKNUM):

    # ============================================================
    # БЛОК 5. Режимы выравнивания - проверка, что марок хватает
    # ============================================================
    if len(tags) == 1:
        forms.alert(u"Выделена только одна марка.\n\n"
                    u"Для выравнивания необходимо выделить несколько марок.",
                    title=u"Выравнивание марок")
        raise SystemExit

    is_vertical = action_choice.startswith(u"Друг")


    # ============================================================
    # БЛОК 6. Рабочая плоскость для PickPoint (нужна на разрезах/фасадах)
    # ============================================================
    # Плоскость временная: после щелчка виду возвращается прежняя (иначе типы
    # высотных отметок «…Схемы…» на 3D-виде рисуются с текстом далеко от полки)
    import sys as _pl_sys
    _pl_sys.modules.pop('xyz_plane', None)
    import xyz_plane
    try:
        _plane_tok = xyz_plane.push(doc, view, view.ViewDirection, view.Origin,
                                    u"Подготовка рабочей плоскости")
    except Exception as ex:
        forms.alert(u"Не удалось задать рабочую плоскость:\n\n{}".format(str(ex)),
                    title=u"Ошибка")
        raise SystemExit


    # ============================================================
    # БЛОК 7. Указание точки привязки
    # ============================================================
    try:
        anchor_point = uidoc.Selection.PickPoint(
            u"Укажите точку для размещения первой марки"
        )
    except OperationCanceledException:
        xyz_plane.pop(doc, view, _plane_tok)
        forms.alert(u"Выбор точки отменён.", title=u"Выравнивание марок")
        raise SystemExit
    except Exception as ex:
        xyz_plane.pop(doc, view, _plane_tok)
        forms.alert(u"Ошибка при выборе точки:\n\n{}".format(str(ex)), title=u"Ошибка")
        raise SystemExit
    xyz_plane.pop(doc, view, _plane_tok)


    # ============================================================
    # БЛОК 8. Запоминаем исходные позиции (для отката пробного варианта)
    # ============================================================
    original_positions = {}
    for tag in tags:
        original_positions[tag.Id] = tag.TagHeadPosition


    # ============================================================
    # БЛОК 8Б. Точка-ориентир для сортировки - НЕ текущее положение
    # самой марки (оно может быть уже перепутано), а точка, куда
    # "смотрит" выноска: свободный конец выноски, либо ближайшая
    # к точке привязки точка помеченного элемента (так Revit и
    # строит присоединённую выноску)
    # ============================================================
    def get_reference_point(tag):
        # 1. Свободный конец выноски (для Attached GetLeaderEnd бросает исключение)
        try:
            if tag.HasLeader and tag.LeaderEndCondition == LeaderEndCondition.Free:
                for r in tag.GetTaggedReferences():
                    try:
                        p = tag.GetLeaderEnd(r)
                        if p is not None:
                            return p
                    except Exception:
                        continue
        except Exception:
            pass

        # 2. Сам помеченный элемент
        try:
            for tid in tag.GetTaggedLocalElementIds():
                el = doc.GetElement(tid)
                if el is None:
                    continue
                loc = el.Location
                if isinstance(loc, LocationPoint):
                    return loc.Point
                if isinstance(loc, LocationCurve):
                    curve = loc.Curve
                    # Ближайшая к точке привязки точка кривой, а не середина:
                    # у параллельных труб одинаковой длины середины совпадают
                    # по одной из осей, и сортировка по ним не работает
                    try:
                        res = curve.Project(anchor_point)
                        if res is not None:
                            return res.XYZPoint
                    except Exception:
                        pass
                    return curve.Evaluate(0.5, True)
                bb = el.get_BoundingBox(view)
                if bb is not None:
                    return (bb.Min + bb.Max) * 0.5
        except Exception:
            pass

        return tag.TagHeadPosition


    ref_points = {}
    for tag in tags:
        ref_points[tag.Id] = get_reference_point(tag)


    # ============================================================
    # БЛОК 9. Сортировка
    # Сортируем по той оси, вдоль которой помеченные элементы реально
    # разнесены (например, параллельные трубы в плане при горизонтальном
    # ряду марок разнесены по вертикали, а не по горизонтали).
    # Направление (прямой/обратный порядок) выбирается автоматически
    # по наименьшему числу пересечений выносок; "реверс" его переворачивает.
    # ============================================================
    def along_val(p):
        return -p.DotProduct(up) if is_vertical else p.DotProduct(right)

    def across_val(p):
        return p.DotProduct(right) if is_vertical else -p.DotProduct(up)

    _al = [along_val(ref_points[t.Id]) for t in tags]
    _ac = [across_val(ref_points[t.Id]) for t in tags]
    use_along = (max(_al) - min(_al)) >= (max(_ac) - min(_ac))

    def sort_key(tag):
        p = ref_points[tag.Id]
        a, c = round(along_val(p), 6), round(across_val(p), 6)
        return (a, c) if use_along else (c, a)

    tags_sorted = sorted(tags, key=sort_key)
    step_direction = -up if is_vertical else right


    def _uv(p):
        return (p.DotProduct(right), p.DotProduct(up))

    def _cross(o, a, b):
        return (a[0] - o[0]) * (b[1] - o[1]) - (a[1] - o[1]) * (b[0] - o[0])

    def _segments_intersect(p1, p2, p3, p4):
        d1 = _cross(p3, p4, p1)
        d2 = _cross(p3, p4, p2)
        d3 = _cross(p1, p2, p3)
        d4 = _cross(p1, p2, p4)
        return (d1 * d2 < 0) and (d3 * d4 < 0)

    def count_crossings(order, spacing_ft):
        segs = []
        for i, tag in enumerate(order):
            head = anchor_point + step_direction * (spacing_ft * i)
            segs.append((_uv(head), _uv(ref_points[tag.Id])))
        n = 0
        for i in range(len(segs)):
            for j in range(i + 1, len(segs)):
                if _segments_intersect(segs[i][0], segs[i][1], segs[j][0], segs[j][1]):
                    n += 1
        return n

    def best_order(spacing_ft):
        fwd = list(tags_sorted)
        rev = list(reversed(tags_sorted))
        if count_crossings(rev, spacing_ft) < count_crossings(fwd, spacing_ft):
            return rev
        return fwd


    # ============================================================
    # БЛОК 10. Размещение марок - все на одной общей линии от anchor_point
    # (порядок передаётся явно - чтобы можно было передать развёрнутый
    # список после ответа "реверс" в цикле подбора ниже)
    # ============================================================
    def place_tags(spacing_ft, order):
        current_point = anchor_point
        for tag in order:
            tag.TagHeadPosition = current_point
            current_point = current_point + step_direction * spacing_ft


    # ============================================================
    # БЛОК 11. Интерактивный подбор шага
    # (если ранее выбирали "Измерить шаг" - подставляем то значение
    # по умолчанию вместо жёсткого "10")
    # ============================================================
    config = script.get_config('xyz_align')
    default_spacing_mm = config.get_option('last_measured_step_mm', "10")

    while True:
        spacing_str = forms.ask_for_string(
            default=default_spacing_mm,
            prompt=u"Шаг между марками, мм\n\n0 = все марки в одной точке",
            title=u"Выравнивание марок"
        )

        if spacing_str is None:
            raise SystemExit

        try:
            spacing_mm = float(spacing_str.replace(",", "."))
            if spacing_mm < 0:
                raise ValueError
        except ValueError:
            forms.alert(u"Введите неотрицательное число.\nНапример: 0, 10 или 15.5",
                        title=u"Некорректный шаг")
            continue

        spacing_ft = spacing_mm / 304.8

        current_order = best_order(spacing_ft)

        t = Transaction(doc, u"Выравнивание марок - пробный вариант")
        t.Start()
        try:
            place_tags(spacing_ft, current_order)
            t.Commit()
        except Exception as ex:
            try:
                t.RollBack()
            except Exception:
                pass
            forms.alert(u"Ошибка при выравнивании:\n\n{}".format(str(ex)), title=u"Ошибка")
            raise SystemExit

        uidoc.RefreshActiveView()

        result = forms.alert(
            u"Марки расставлены с шагом {} мм.\n\nУстраивает результат?".format(spacing_mm),
            title=u"Выравнивание марок",
            yes=True, no=True
        )

        if result:
            break

        # Не устроило - откатываем пробную расстановку к исходным позициям
        t_restore = Transaction(doc, u"Отмена пробного выравнивания")
        t_restore.Start()
        try:
            for tag in tags_sorted:
                tag.TagHeadPosition = original_positions[tag.Id]
            t_restore.Commit()
        except Exception as ex:
            try:
                t_restore.RollBack()
            except Exception:
                pass
            forms.alert(u"Не удалось вернуть исходное положение:\n\n{}".format(str(ex)),
                        title=u"Ошибка")
            raise SystemExit

        uidoc.RefreshActiveView()


        default_spacing_mm = spacing_str