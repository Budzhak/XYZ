# -*- coding: utf-8 -*-
"""Взрыв-схема выбранных элементов: каждый следующий по цепочке соединений
сдвигается от предыдущего на заданный шаг (наборы разноса DisplacementElement).

v1.1 · 12.11.2026 (К-И17): выделены только трубы — раньше цепочка обрывалась на первом же
фитинге (его нет в выделении), ничего не разносилось, а окно писало «Готово».
Теперь фитинги и арматура между выделенными элементами подхватываются сами,
каждая несвязанная группа разносится от своего нижнего элемента, вид проверяется
(разнос бывает только на 3D-виде), а итог честно говорит, сколько сдвинуто и почему нет."""
import sys
import Autodesk.Revit.DB as RDB
from System.Collections.Generic import List
from pyrevit import revit
import xyz_forms as forms   # единый стиль окон XYZ (lib/xyz_forms.py)

TITLE = u'Вдребезги'
doc = revit.doc
uidoc = revit.uidoc
view = doc.ActiveView

# 0. Разнос в Revit возможен только на 3D-виде (не шаблон, не перспектива)
if not isinstance(view, RDB.View3D) or view.IsTemplate:
    forms.alert(u'Разнос (взрыв-схема) работает только на 3D-виде. Откройте 3D-вид и запустите снова.',
                title=TITLE)
    sys.exit()
if view.IsPerspective:
    forms.alert(u'На перспективном 3D-виде разнос не создаётся. Нужен ортогональный 3D-вид.', title=TITLE)
    sys.exit()

# 1. Выборка
sel_ids = list(uidoc.Selection.GetElementIds())
if not sel_ids:
    forms.alert(u'Выделите элементы систем (воздуховоды, трубы, фитинги, оборудование).', title=TITLE)
    sys.exit()


def _iv(eid):
    try:
        return eid.Value
    except AttributeError:
        return eid.IntegerValue


def connectors(el):
    mm = getattr(el, 'MEPModel', None)
    cm = None
    try:
        cm = mm.ConnectorManager if mm is not None else None
    except Exception:
        cm = None
    if cm is None:
        cm = getattr(el, 'ConnectorManager', None)
    if cm is None:
        return []
    try:
        return list(cm.Connectors)
    except Exception:
        return []


def neighbours(el):
    """[(соединитель el, соседний элемент)] — только физические соединения (без систем)."""
    out = []
    for c in connectors(el):
        try:
            if not c.IsConnected:
                continue
            refs = list(c.AllRefs)
        except Exception:
            continue
        for r in refs:
            o = r.Owner
            if o is None or o.Id == el.Id or isinstance(o, RDB.MEPSystem):
                continue
            out.append((c, o))
    return out


sel = set(_iv(i) for i in sel_ids)
elements = dict((_iv(i), doc.GetElement(i)) for i in sel_ids)
elements = dict((k, v) for k, v in elements.items() if v is not None)

# 2. Подхватить фитинги и арматуру, стоящие между выделенными элементами
#    (соединительная деталь, у которой 2+ соседа из выделения, или 1 сосед и она — конец цепочки)
FITTING_CATS = set(_iv(RDB.ElementId(b)) for b in (
    RDB.BuiltInCategory.OST_DuctFitting, RDB.BuiltInCategory.OST_PipeFitting,
    RDB.BuiltInCategory.OST_DuctAccessory, RDB.BuiltInCategory.OST_PipeAccessory,
    RDB.BuiltInCategory.OST_CableTrayFitting, RDB.BuiltInCategory.OST_ConduitFitting))
added = 0
for _ in range(3):                       # несколько проходов: фитинг за фитингом (отвод + переход)
    grow = {}
    for k, el in elements.items():
        for c, o in neighbours(el):
            ok = _iv(o.Id)
            if ok in elements or ok in grow or o.Category is None or _iv(o.Category.Id) not in FITTING_CATS:
                continue
            if sum(1 for _c, n in neighbours(o) if _iv(n.Id) in elements) >= 1:
                grow[ok] = o
    if not grow:
        break
    added += len(grow)
    elements.update(grow)

if not any(connectors(e) for e in elements.values()):
    forms.alert(u'У выделенных элементов нет соединителей — разносить нечего (нужны элементы систем).',
                title=TITLE)
    sys.exit()

# 3. Шаг
user_input = forms.ask_for_string(default='500', title=TITLE, prompt=u'Шаг разноса, мм:')
if not user_input:
    sys.exit()
try:
    step_mm = float(user_input.replace(',', '.'))
except ValueError:
    forms.alert(u'Шаг должен быть числом, мм (например 500).', title=TITLE)
    sys.exit()
try:
    step = RDB.UnitUtils.ConvertToInternalUnits(step_mm, RDB.UnitTypeId.Millimeters)
except Exception:
    step = step_mm / 304.8


def zmin(e):
    bb = e.get_BoundingBox(None)
    return bb.Min.Z if bb else 0.0


# 4. Разнос: обход каждой связной группы от её нижнего элемента
moved, already, failed = 0, 0, 0
disp = {}
t = RDB.Transaction(doc, TITLE + u': разнос')
t.Start()
try:
    for start in sorted(elements.values(), key=zmin):
        if _iv(start.Id) in disp:
            continue
        disp[_iv(start.Id)] = RDB.XYZ(0, 0, 0)            # база группы стоит на месте
        queue = [start]
        while queue:
            cur = queue.pop(0)
            cur_d = disp[_iv(cur.Id)]
            for c, nxt in neighbours(cur):
                nk = _iv(nxt.Id)
                if nk not in elements or nk in disp:
                    continue
                d = cur_d + c.CoordinateSystem.BasisZ.Multiply(step)
                disp[nk] = d
                queue.append(nxt)
                ids = List[RDB.ElementId]()
                ids.Add(nxt.Id)
                try:
                    if RDB.DisplacementElement.IsElementDisplacedInView(view, nxt.Id):
                        already += 1
                        continue
                except Exception:
                    pass
                try:
                    RDB.DisplacementElement.Create(doc, ids, d, view, None)
                    moved += 1
                except Exception:
                    failed += 1
    t.Commit()
except Exception:
    t.RollBack()
    raise

msg = [u'Сдвинуто элементов: %d' % moved]
if added:
    msg.append(u'Подхвачено фитингов и арматуры между выделенными: %d' % added)
if already:
    msg.append(u'Уже были в разносе на этом виде (не тронуты): %d — сначала «Сбросить разнос» в Revit' % already)
if failed:
    msg.append(u'Revit не дал сдвинуть: %d' % failed)
if moved == 0 and not already:
    msg.append(u'Ничего не сдвинулось: выделенные элементы не соединены между собой.')
if moved and not failed and not already:
    forms.toast(u'\n'.join(msg), title=TITLE)
else:
    forms.alert(u'\n'.join(msg), title=TITLE)
