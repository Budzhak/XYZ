# -*- coding: utf-8 -*-
"""Чей фильтр: какие фильтры вида действуют на выбранный элемент.

Выделите элемент (или ничего — тогда укажете его щелчком, в том числе в связи)
и нажмите кнопку. Окно покажет фильтры активного вида в порядке приоритета:
какие из них ловят элемент, по каким правилам, что делают с графикой — и даст
сразу выключить фильтр (флажок «Вкл.») или его видимость («Видим.»).
Изменения применяются кнопкой «Применить» одним шагом (Ctrl+Z).
Если фильтрами вида управляет шаблон — меняется шаблон (об этом пишет окно).
v3 · 22.10.2026: строки «Категория …» — видимость и графика категории элемента (вкладка категорий
«Видимость/Графика»); если ими управляет шаблон вида — правится шаблон. Владелец (шаблон/вид)
определяется отдельно для фильтров и для категорий.
v2 · 14.10.2026: «Графика ▾» — линии, штриховки, прозрачность, полутон фильтра прямо в окне
(как строка в «Видимость/Графика»); «Применить» — сразу на виде, окно не закрывается.
v2.2: «Блёклость» 0–100 — элементы фильтра бледнеют к белому, каждая система в своём цвете
(служебные фильтры «zz_блёк …», lib/xyz_fade.py)."""
import sys
from pyrevit import revit
import xyz_forms as forms
from Autodesk.Revit.DB import (BuiltInParameter, ElementId, RevitLinkInstance, Transaction, Color,
                               OverrideGraphicSettings, FilteredElementCollector, FillPatternElement,
                               FillPatternTarget, LinePatternElement)
from Autodesk.Revit.UI import ColorSelectionDialog, ItemSelectionDialogResult
from Autodesk.Revit.UI.Selection import ObjectType
from Autodesk.Revit.Exceptions import OperationCanceledException
import System
from System.Windows import (Thickness, TextWrapping, VerticalAlignment, HorizontalAlignment,
                            FontWeights, GridLength, GridUnitType, Visibility, ResizeMode)
from System.Windows.Controls import (Border, StackPanel, TextBlock, CheckBox, ScrollViewer,
                                     ScrollBarVisibility, Grid, ColumnDefinition, Orientation,
                                     Button, ComboBox, ComboBoxItem, Slider, WrapPanel)
from System.Windows.Input import Cursors
from System.Windows.Forms import Screen

sys.modules.pop('xyz_filters', None)
import xyz_filters as hf
sys.modules.pop('xyz_fade', None)
import xyz_fade

doc = revit.doc
uidoc = revit.uidoc
view = doc.ActiveView
TITLE = u'Чей фильтр'
# v3.5 · 12.11.2026: отчёт в файл — каждый запуск пишет %TEMP%\\xyz_whofilter_last.txt, кнопка «В файл» (К-И20).
# v3.4 · 07.11.2026: окно «Фильтры» открывается без задержки — сторож окна на user32 вместо UI Automation,
# Idling не крутится вхолостую.
# v3.2 · 02.11.2026: «Фильтры…» и «Изменить фильтр ▸» — открыть окно Revit «Фильтры» (нужный фильтр уже выделен),
# после «ОК»/«Отмена» в нём «Чей фильтр» открывается снова с тем же элементом и перечитывает фильтры.
__persistentengine__ = True
GO = {'filters': False, 'name': None}
WHO_ID = u'CustomCtrl_%CustomCtrl_%XYZ%Найти%WhoFilter'


def go_filters(name=None):
    """Закрыть окно и после него открыть «Фильтры» Revit; неприменённое — спросить."""
    try:
        if pending() and forms.alert(u'Есть неприменённые изменения. Применить их перед переходом в «Фильтры»?',
                                     title=TITLE, yes=True, no=True):
            apply_changes()
    except Exception:
        pass
    GO['filters'] = True
    GO['name'] = name
    dlg.Close()


def _dbg(m):
    try:
        import io, os, time as _t
        with io.open(os.path.join(os.environ.get('TEMP', 'C:\\Temp'), 'whofilter_dbg.txt'), 'a', encoding='utf-8') as fh:
            fh.write(u'%s %s\n' % (_t.strftime('%H:%M:%S'), m))
    except Exception:
        pass


def _norm(s):
    return (s or u'').replace(u'꞉', u':').replace(u'\xa0', u' ').strip().lower()


def _pick_w32(hdlg, name):
    """Выделить фильтр в дереве окна «Фильтры» сообщениями Windows (SysTreeView32 в том же процессе)."""
    import ctypes
    from ctypes import wintypes
    u = ctypes.windll.user32
    u.FindWindowExW.restype = ctypes.c_void_p
    u.FindWindowExW.argtypes = [ctypes.c_void_p, ctypes.c_void_p, ctypes.c_wchar_p, ctypes.c_wchar_p]
    u.SendMessageW.restype = ctypes.c_void_p
    u.SendMessageW.argtypes = [ctypes.c_void_p, ctypes.c_uint, ctypes.c_void_p, ctypes.c_void_p]
    u.GetWindow.restype = ctypes.c_void_p
    u.GetWindow.argtypes = [ctypes.c_void_p, ctypes.c_uint]

    def find_tree(h, depth=0):
        t = u.FindWindowExW(h, None, u'SysTreeView32', None)
        if t:
            return t
        if depth > 3:
            return None
        c = u.GetWindow(h, 5)          # GW_CHILD
        while c:
            r = find_tree(c, depth + 1)
            if r:
                return r
            c = u.GetWindow(c, 2)      # GW_HWNDNEXT
        return None

    class TVITEMW(ctypes.Structure):
        _fields_ = [('mask', ctypes.c_uint), ('hItem', ctypes.c_void_p), ('state', ctypes.c_uint),
                    ('stateMask', ctypes.c_uint), ('pszText', ctypes.c_wchar_p), ('cchTextMax', ctypes.c_int),
                    ('iImage', ctypes.c_int), ('iSelectedImage', ctypes.c_int), ('cChildren', ctypes.c_int),
                    ('lParam', ctypes.c_void_p)]

    tree = find_tree(ctypes.c_void_p(hdlg))
    _dbg(u'w32 tree: %s' % bool(tree))
    if not tree:
        try:
            u.GetClassNameW.argtypes = [ctypes.c_void_p, ctypes.c_wchar_p, ctypes.c_int]
            cb = ctypes.create_unicode_buffer(256)
            seen = []
            def walk(h, d):
                c = u.GetWindow(h, 5)
                while c and len(seen) < 80:
                    u.GetClassNameW(c, cb, 255)
                    seen.append(u'%d:%s' % (d, cb.value))
                    if d < 3:
                        walk(c, d + 1)
                    c = u.GetWindow(c, 2)
            u.GetClassNameW(ctypes.c_void_p(hdlg), cb, 255)
            _dbg(u'hdlg=%s class=%s' % (hdlg, cb.value))
            walk(ctypes.c_void_p(hdlg), 1)
            _dbg(u'children: ' + u', '.join(seen))
        except Exception as ex:
            _dbg(u'walk err %s' % ex)
    if not tree:
        return False
    buf = ctypes.create_unicode_buffer(512)

    def text(hi):
        it = TVITEMW()
        it.mask = 1                    # TVIF_TEXT
        it.hItem = hi
        it.pszText = ctypes.cast(buf, ctypes.c_wchar_p)
        it.cchTextMax = 511
        u.SendMessageW(tree, 0x113E, None, ctypes.cast(ctypes.byref(it), ctypes.c_void_p))   # TVM_GETITEMW
        return buf.value

    want = _norm(name)
    stack = [u.SendMessageW(tree, 0x110A, ctypes.c_void_p(0), None)]   # TVGN_ROOT
    n = 0
    while stack:
        hi = stack.pop()
        while hi:
            n += 1
            if _norm(text(hi)) == want:
                u.SendMessageW(tree, 0x110B, ctypes.c_void_p(9), ctypes.c_void_p(hi))   # TVM_SELECTITEM, TVGN_CARET
                u.SendMessageW(tree, 0x1114, None, ctypes.c_void_p(hi))                 # TVM_ENSUREVISIBLE
                _dbg(u'w32 selected (%d checked)' % n)
                return True
            ch = u.SendMessageW(tree, 0x110A, ctypes.c_void_p(4), ctypes.c_void_p(hi))   # TVGN_CHILD
            if ch:
                stack.append(ch)
            hi = u.SendMessageW(tree, 0x110A, ctypes.c_void_p(1), ctypes.c_void_p(hi))   # TVGN_NEXT
            if n > 5000:
                break
    _dbg(u'w32 not found among %d' % n)
    return False


IDX = [-1]


def _filter_index(name):
    """Позиция фильтра в списке окна «Фильтры»: сначала фильтры по правилам, потом фильтры выбора,
    внутри — по алфавиту без учёта регистра (как в Revit)."""
    from Autodesk.Revit.DB import ParameterFilterElement, SelectionFilterElement
    from System import String, StringComparison
    import functools
    cmpf = lambda a, b: String.Compare(a, b, StringComparison.CurrentCultureIgnoreCase)
    rule = sorted([e.Name for e in FilteredElementCollector(doc).OfClass(ParameterFilterElement)],
                  key=functools.cmp_to_key(cmpf))
    sel = sorted([e.Name for e in FilteredElementCollector(doc).OfClass(SelectionFilterElement)],
                 key=functools.cmp_to_key(cmpf))
    if name in rule:
        return 1 + rule.index(name)                 # строка 0 — узел «Фильтры по правилам»
    if name in sel:
        return 1 + len(rule) + 1 + sel.index(name)  # +1 — узел «Фильтры выбора»
    return -1


def _pick_keys(hdlg, idx):
    """Список фильтров в «Фильтрах» — собственный элемент Revit (AfxWnd140u), без доступа извне.
    В нём при открытии выделен первый фильтр; шлём ему Home и «вниз» idx раз."""
    import ctypes
    u = ctypes.windll.user32
    u.GetWindow.restype = ctypes.c_void_p
    u.GetWindow.argtypes = [ctypes.c_void_p, ctypes.c_uint]
    u.GetClassNameW.argtypes = [ctypes.c_void_p, ctypes.c_wchar_p, ctypes.c_int]
    u.SendMessageW.restype = ctypes.c_void_p
    u.SendMessageW.argtypes = [ctypes.c_void_p, ctypes.c_uint, ctypes.c_void_p, ctypes.c_void_p]
    cb = ctypes.create_unicode_buffer(64)
    c = u.GetWindow(ctypes.c_void_p(hdlg), 5)
    lst = None
    while c:
        u.GetClassNameW(c, cb, 63)
        if cb.value.startswith(u'AfxWnd'):
            lst = c
            break
        c = u.GetWindow(c, 2)
    _dbg(u'keys: list=%s idx=%d' % (bool(lst), idx))
    if not lst or idx < 0:
        return False
    WM_KEYDOWN, WM_KEYUP, VK_HOME, VK_DOWN = 0x100, 0x101, 0x24, 0x28
    _dbg(u'keys: down x%d' % idx)
    def key(vk, n=1):
        for _ in range(n):
            u.SendMessageW(lst, WM_KEYDOWN, ctypes.c_void_p(vk), ctypes.c_void_p(1))
            u.SendMessageW(lst, WM_KEYUP, ctypes.c_void_p(vk), ctypes.c_void_p(0xC0000001))
    u.SetFocus.argtypes = [ctypes.c_void_p]
    u.SetFocus(lst)
    u.SendMessageW(lst, 0x000B, None, None)              # WM_SETREDRAW off (только список)
    try:
        key(VK_HOME)
        key(VK_DOWN, idx)
    finally:
        u.SendMessageW(lst, 0x000B, ctypes.c_void_p(1), None)
        u.RedrawWindow.argtypes = [ctypes.c_void_p, ctypes.c_void_p, ctypes.c_void_p, ctypes.c_uint]
        u.RedrawWindow(lst, None, None, 0x0001 | 0x0004 | 0x0100)
    return True


def _pick(win, name):
    """Выделить фильтр name в дереве окна «Фильтры»: сначала через UIA, иначе — фокус на дерево и набор имени
    (поиск по первым буквам, как при ручном вводе в списке Windows)."""
    return   # выделение фильтра в списке отключено по решению db 02.11 (переборка клавишами слишком медленная)
    from System.Windows.Automation import (AutomationElement, TreeScope, PropertyCondition, ControlType,
                                           SelectionItemPattern, ScrollItemPattern)
    items = win.FindAll(TreeScope.Descendants,
                        PropertyCondition(AutomationElement.ControlTypeProperty, ControlType.TreeItem))
    _dbg(u'tree items: %d, first: %s' % (items.Count, u' | '.join(items[i].Current.Name for i in range(min(4, items.Count)))))
    want = _norm(name)
    for i in range(items.Count):
        it = items[i]
        if _norm(it.Current.Name) == want:
            try:
                it.GetCurrentPattern(ScrollItemPattern.Pattern).ScrollIntoView()
            except Exception:
                pass
            it.GetCurrentPattern(SelectionItemPattern.Pattern).Select()
            _dbg(u'selected via UIA')
            return
    tree = win.FindFirst(TreeScope.Descendants,
                         PropertyCondition(AutomationElement.ControlTypeProperty, ControlType.Tree))
    _dbg(u'tree control: %s' % (tree is not None))
    if tree is not None:
        tree.SetFocus()
    import time as _tm
    _tm.sleep(0.35)   # фокус в окне «Фильтры» по умолчанию — на списке фильтров; набор имени = поиск по буквам
    import clr
    clr.AddReference('System.Windows.Forms')
    from System.Windows.Forms import SendKeys
    esc = u''.join((u'{%s}' % c) if c in u'+^%~(){}[]' else c for c in name.replace(u'꞉', u':'))
    SendKeys.SendWait(esc)
    _dbg(u'typed name')


def _relaunch_later(uiapp):
    """Запуск не из обработчика Idling (Revit запрещает подписки/команды изнутри него): таймер WPF на UI-потоке."""
    from System.Windows.Threading import DispatcherTimer
    from System import TimeSpan, EventHandler
    tm = DispatcherTimer()
    tm.Interval = TimeSpan.FromMilliseconds(250)

    def tick(s, e):
        tm.Stop()
        _relaunch(uiapp)
    tm.Tick += EventHandler(tick)
    tm.Start()
    _dbg(u'relaunch scheduled')


def _relaunch(uiapp):
    try:
        import clr
        clr.AddReference('AdWindows')
        from Autodesk.Windows import ComponentManager
        for tab in ComponentManager.Ribbon.Tabs:
            for pnl in tab.Panels:
                for it in pnl.Source.Items:
                    if getattr(it, 'Id', None) == WHO_ID:
                        it.CommandHandler.Execute(it)
                        _dbg(u'relaunch via ribbon (first)')
                        return
    except Exception as ex:
        _dbg(u'ribbon first err %s' % ex)
    _relaunch_post(uiapp)


def _relaunch_post(uiapp):
    from Autodesk.Revit.UI import RevitCommandId
    try:
        cid = RevitCommandId.LookupCommandId(WHO_ID)
        can = cid is not None and uiapp.CanPostCommand(cid)
        _dbg(u'relaunch cid=%s can=%s' % (cid is not None, can))
        if can:
            uiapp.PostCommand(cid)
            return
    except Exception as ex:
        _dbg(u'post err %s' % ex)
    try:
        import clr
        clr.AddReference('AdWindows')
        from Autodesk.Windows import ComponentManager
        for tab in ComponentManager.Ribbon.Tabs:
            for pnl in tab.Panels:
                for it in pnl.Source.Items:
                    if getattr(it, 'Id', None) == WHO_ID:
                        it.CommandHandler.Execute(it)
                        _dbg(u'relaunch via ribbon')
                        return
        _dbg(u'ribbon item not found')
    except Exception as ex:
        _dbg(u'ribbon err %s' % ex)


def open_filters_and_return(name):
    """«Фильтры» Revit через PostCommand; сторож UIA выделяет фильтр и ждёт закрытия окна,
    затем Idling один раз запускает «Чей фильтр» заново (выделение элемента сохраняется)."""
    import time
    import clr
    from System import EventHandler
    from System.Threading import Thread, ThreadStart
    from Autodesk.Revit.UI import RevitCommandId, PostableCommand
    from Autodesk.Revit.UI.Events import IdlingEventArgs
    try:
        IDX[0] = _filter_index(name) if name else -1
    except Exception as ex:
        _dbg(u'idx err %s' % ex)
    uiapp = __revit__
    st = {'seen': False, 'gone': False, 't0': time.time()}

    def watcher():
        # v3.4 · 07.11.2026: без UI Automation. UIA из фонового потока опрашивал окна самого Revit
        # каждые 0,25 с — вызовы уходили в UI-поток Revit и тормозили открытие «Фильтров» на секунды.
        # Теперь — user32.FindWindowW по заголовку (мгновенно, UI-поток не трогает) + проверка процесса.
        try:
            import ctypes
            u = ctypes.windll.user32
            u.FindWindowW.restype = ctypes.c_void_p
            u.FindWindowW.argtypes = [ctypes.c_wchar_p, ctypes.c_wchar_p]
            u.GetWindowThreadProcessId.argtypes = [ctypes.c_void_p, ctypes.POINTER(ctypes.c_ulong)]
            u.IsWindowVisible.argtypes = [ctypes.c_void_p]
            from System.Diagnostics import Process
            pid = Process.GetCurrentProcess().Id

            def dlg_open():
                for title in (u'Фильтры', u'Filters'):
                    h = u.FindWindowW(None, title)
                    if h and u.IsWindowVisible(h):
                        p = ctypes.c_ulong(0)
                        u.GetWindowThreadProcessId(h, ctypes.byref(p))
                        if p.value == pid:
                            return True
                return False
            _dbg(u'watcher(w32) start pid=%s name=%s' % (pid, name))
            while time.time() - st['t0'] < 1800:
                if dlg_open():
                    if not st['seen']:
                        _dbg(u'dialog seen %.2f s' % (time.time() - st['t0']))
                    st['seen'] = True
                elif st['seen']:
                    st['gone'] = True
                    return
                time.sleep(0.1 if not st['seen'] else 0.3)
        except Exception as ex:
            _dbg(u'watcher err %s' % ex)
            st['gone'] = st['seen']

    def on_idle(s, e):
        if st['gone'] or not st.get('lg'):
            st['lg'] = 1
            _dbg(u'idle seen=%s gone=%s' % (st['seen'], st['gone']))
        if st['gone'] or (not st['seen'] and time.time() - st['t0'] > 20):
            try:
                uiapp.Idling -= HANDLER[0]
            except Exception:
                pass
            if st['gone']:
                _relaunch_later(uiapp)
        # v3.4: без SetRaiseWithoutDelay — Idling не крутится вхолостую, пока открыты «Фильтры»

    HANDLER = [EventHandler[IdlingEventArgs](on_idle)]
    th = Thread(ThreadStart(watcher))
    th.IsBackground = True
    th.Start()
    uiapp.PostCommand(RevitCommandId.LookupPostableCommandId(PostableCommand.Filters))
    uiapp.Idling += HANDLER[0]
    _dbg(u'posted Filters, idling subscribed')


def _iv(eid):
    try:
        return eid.Value
    except Exception:
        return eid.IntegerValue


# ------------------------------------------------------------ графика фильтра: OverrideGraphicSettings <-> dict
def _col(c):
    try:
        return (int(c.Red), int(c.Green), int(c.Blue)) if (c is not None and c.IsValid) else None
    except Exception:
        return None


def _rc(t):
    return Color(System.Byte(t[0]), System.Byte(t[1]), System.Byte(t[2]))


EMPTY = dict(pl_color=None, pl_weight=-1, pl_pat=-1,
             sfg_vis=True, sfg_pat=-1, sfg_color=None, sbg_vis=True, sbg_pat=-1, sbg_color=None, transp=0,
             cl_color=None, cl_weight=-1, cl_pat=-1,
             cfg_vis=True, cfg_pat=-1, cfg_color=None, cbg_vis=True, cbg_pat=-1, cbg_color=None, halftone=False)


def read_ogs(o):
    w = lambda v: v if v > 0 else -1
    return dict(pl_color=_col(o.ProjectionLineColor), pl_weight=w(o.ProjectionLineWeight),
                pl_pat=_iv(o.ProjectionLinePatternId),
                sfg_vis=bool(o.IsSurfaceForegroundPatternVisible), sfg_pat=_iv(o.SurfaceForegroundPatternId),
                sfg_color=_col(o.SurfaceForegroundPatternColor),
                sbg_vis=bool(o.IsSurfaceBackgroundPatternVisible), sbg_pat=_iv(o.SurfaceBackgroundPatternId),
                sbg_color=_col(o.SurfaceBackgroundPatternColor),
                transp=int(o.Transparency),
                cl_color=_col(o.CutLineColor), cl_weight=w(o.CutLineWeight), cl_pat=_iv(o.CutLinePatternId),
                cfg_vis=bool(o.IsCutForegroundPatternVisible), cfg_pat=_iv(o.CutForegroundPatternId),
                cfg_color=_col(o.CutForegroundPatternColor),
                cbg_vis=bool(o.IsCutBackgroundPatternVisible), cbg_pat=_iv(o.CutBackgroundPatternId),
                cbg_color=_col(o.CutBackgroundPatternColor),
                halftone=bool(o.Halftone))


IDS = {}    # int -> ElementId образцов (без конструктора ElementId(int))


def _eid(v):
    return IDS.get(v, ElementId.InvalidElementId)


def build_ogs(d):
    o = OverrideGraphicSettings()
    if d['pl_color']:
        o.SetProjectionLineColor(_rc(d['pl_color']))
    if d['pl_weight'] > 0:
        o.SetProjectionLineWeight(d['pl_weight'])
    if d['pl_pat'] > 0 or d['pl_pat'] in IDS:
        o.SetProjectionLinePatternId(_eid(d['pl_pat']))
    if d['cl_color']:
        o.SetCutLineColor(_rc(d['cl_color']))
    if d['cl_weight'] > 0:
        o.SetCutLineWeight(d['cl_weight'])
    if d['cl_pat'] > 0 or d['cl_pat'] in IDS:
        o.SetCutLinePatternId(_eid(d['cl_pat']))
    for p, pat, col, vis in (('sfg', o.SetSurfaceForegroundPatternId, o.SetSurfaceForegroundPatternColor,
                              o.SetSurfaceForegroundPatternVisible),
                             ('sbg', o.SetSurfaceBackgroundPatternId, o.SetSurfaceBackgroundPatternColor,
                              o.SetSurfaceBackgroundPatternVisible),
                             ('cfg', o.SetCutForegroundPatternId, o.SetCutForegroundPatternColor,
                              o.SetCutForegroundPatternVisible),
                             ('cbg', o.SetCutBackgroundPatternId, o.SetCutBackgroundPatternColor,
                              o.SetCutBackgroundPatternVisible)):
        if d[p + '_pat'] > 0:
            pat(_eid(d[p + '_pat']))
        if d[p + '_color']:
            col(_rc(d[p + '_color']))
        if not d[p + '_vis']:
            vis(False)
    if d['transp'] > 0:
        o.SetSurfaceTransparency(d['transp'])
    if d['halftone']:
        o.SetHalftone(True)
    return o


NOCH = u'— без изменений'
WEIGHTS = [(-1, u'—')] + [(i, u'%d' % i) for i in range(1, 17)]
FILLS = [(-1, NOCH)]
_fl = []
for fp in FilteredElementCollector(doc).OfClass(FillPatternElement):
    try:
        pat = fp.GetFillPattern()
        model = pat.Target == FillPatternTarget.Model
        _fl.append((0 if pat.IsSolidFill else 1, model, fp.Name.lower(), _iv(fp.Id),
                    fp.Name + (u'  (модель)' if model else u'')))
        IDS[_iv(fp.Id)] = fp.Id
    except Exception:
        pass
FILLS += [(v, lbl) for _, _, _, v, lbl in sorted(_fl)]
LINEPATS = [(-1, NOCH)]
try:
    _sid = LinePatternElement.GetSolidPatternId()
    IDS[_iv(_sid)] = _sid
    LINEPATS.append((_iv(_sid), u'Сплошная'))
except Exception:
    pass
for lp in sorted(FilteredElementCollector(doc).OfClass(LinePatternElement), key=lambda x: x.Name.lower()):
    IDS[_iv(lp.Id)] = lp.Id
    LINEPATS.append((_iv(lp.Id), lp.Name))


# ------------------------------------------------------------ 1. какие элементы
targets = []      # (элемент, документ связи или None, подпись)
links_sel = []    # выделенные целиком экземпляры связей
for eid in uidoc.Selection.GetElementIds():
    el = doc.GetElement(eid)
    if isinstance(el, RevitLinkInstance):
        links_sel.append(el)
    elif el is not None and el.Category is not None:
        targets.append((el, None, u''))
# v3.1 · 22.10.2026: элемент связи, выделенный Tab, — сразу в окно, без вопроса «что указать?»
try:
    for ref in uidoc.Selection.GetReferences():
        if _iv(ref.LinkedElementId) <= 0:
            continue
        inst = doc.GetElement(ref.ElementId)
        ldoc = inst.GetLinkDocument() if isinstance(inst, RevitLinkInstance) else None
        lel = ldoc.GetElement(ref.LinkedElementId) if ldoc is not None else None
        if lel is not None and lel.Category is not None:
            targets.append((lel, ldoc, u'связь «%s»' % ldoc.Title))
except Exception:
    pass
if not targets and links_sel:
    # выделена связь целиком — сразу указать элемент в ней
    try:
        ref = uidoc.Selection.PickObject(ObjectType.LinkedElement, u'Укажите элемент в связи')
        inst = doc.GetElement(ref.ElementId)
        ldoc = inst.GetLinkDocument()
        targets.append((ldoc.GetElement(ref.LinkedElementId), ldoc, u'связь «%s»' % ldoc.Title))
    except OperationCanceledException:
        raise SystemExit
if not targets:
    ch = forms.CommandSwitchWindow.show([u'Элемент проекта', u'Элемент в связи'],
                                        message=u'Чей фильтр: что указать?')
    if not ch:
        raise SystemExit
    try:
        if ch == u'Элемент в связи':
            ref = uidoc.Selection.PickObject(ObjectType.LinkedElement, u'Укажите элемент в связи')
            inst = doc.GetElement(ref.ElementId)
            ldoc = inst.GetLinkDocument()
            el = ldoc.GetElement(ref.LinkedElementId)
            targets.append((el, ldoc, u'связь «%s»' % ldoc.Title))
        else:
            ref = uidoc.Selection.PickObject(ObjectType.Element, u'Укажите элемент')
            targets.append((doc.GetElement(ref.ElementId), None, u''))
    except OperationCanceledException:
        raise SystemExit
targets = targets[:200]

# ------------------------------------------------------------ 2. где живут настройки (вид или шаблон)
# v3 · 22.10.2026: всё, чем управляет шаблон вида (фильтры, видимость/графика категорий), правится
# в шаблоне; то, что шаблон не держит, — на самом виде. Владелец определяется отдельно для каждой настройки.
TPL = doc.GetElement(view.ViewTemplateId) if _iv(view.ViewTemplateId) > 0 else None
_NON = set()
if TPL is not None:
    try:
        _NON = set(_iv(x) for x in TPL.GetNonControlledTemplateParameterIds())
    except Exception:
        _NON = set()


def owner_for(bip):
    """Где менять настройку: шаблон, если он её держит, иначе вид."""
    if TPL is not None and _iv(ElementId(bip)) not in _NON:
        return TPL
    return view


owner = owner_for(BuiltInParameter.VIS_GRAPHICS_FILTERS)
tpl_notes = []
if owner is not view:
    tpl_notes.append(u'фильтры')


def cat_owner(cat):
    from Autodesk.Revit.DB import CategoryType
    try:
        ct = cat.CategoryType
    except Exception:
        ct = None
    bip = BuiltInParameter.VIS_GRAPHICS_MODEL
    if ct == CategoryType.Annotation:
        bip = BuiltInParameter.VIS_GRAPHICS_ANNOTATION
    elif ct == CategoryType.AnalyticalModel:
        bip = BuiltInParameter.VIS_GRAPHICS_ANALYTICAL_MODEL
    return owner_for(bip)


try:
    fids = list(owner.GetOrderedFilters())
except Exception:
    fids = list(owner.GetFilters())

# ------------------------------------------------------------ 3. проверка
rows = []
fids = [i for i in fids if not xyz_fade.is_helper(doc.GetElement(i))]
for k, fid in enumerate(fids, start=1):
    f = doc.GetElement(fid)
    hits, unknown, why = 0, 0, set()
    caches = {}
    for el, ldoc, _ in targets:
        ok, reason = hf.applies(doc, f, el, ldoc, caches.setdefault(id(ldoc), {}))
        if ok:
            hits += 1
        elif ok is None:
            unknown += 1
        if reason:
            why.add(reason)
    try:
        enabled = owner.GetIsFilterEnabled(fid)
    except Exception:
        enabled = True
    visible = owner.GetFilterVisibility(fid)
    ogs = owner.GetFilterOverrides(fid)
    cats = hf.category_names(doc, f) if hasattr(f, 'GetCategories') else []
    rows.append(dict(order=k, fid=fid, f=f, name=f.Name, hits=hits, unknown=unknown, why=why,
                     enabled=enabled, visible=visible, ogs=hf.overrides_text(ogs),
                     color=hf.swatch_color(ogs), cats=cats, rules=hf.filter_rules_text(doc, f),
                     orig=read_ogs(ogs), cur=read_ogs(ogs)))
    fd = xyz_fade.current(doc, owner, f) if hasattr(f, 'GetCategories') else 0
    rows[-1].update(fade_orig=fd, fade_cur=fd, fade_n=len(xyz_fade.helpers(doc, owner, f)) if fd else 0,
                    kind='flt', own=owner)

# ---- строки категорий выбранных элементов («Видимость/Графика» → вкладка категорий)
_seen = set()
for el, ldoc, _ in targets:
    cat = el.Category
    if cat is None:
        continue
    cats_chain = [cat]
    try:
        if cat.Parent is not None:
            cats_chain.insert(0, cat.Parent)     # сначала родительская категория, потом подкатегория
    except Exception:
        pass
    for c in cats_chain:
        key = _iv(c.Id)
        if key in _seen or len(_seen) >= 6:
            continue
        cid = c.Id
        if ldoc is not None:                     # категория связи: встроенные id совпадают с проектом
            pc = doc.Settings.Categories
            try:
                pcat = None
                for pcc in pc:
                    if _iv(pcc.Id) == key:
                        pcat = pcc
                        break
                if pcat is None and c.Parent is not None:
                    par = pc.get_Item(c.Parent.Name)
                    pcat = par.SubCategories.get_Item(c.Name) if par is not None else None
                if pcat is None:
                    continue
                cid = pcat.Id
            except Exception:
                continue
        _seen.add(key)
        co = cat_owner(c)
        try:
            ogs = co.GetCategoryOverrides(cid)
            hidden = co.GetCategoryHidden(cid)
        except Exception:
            continue
        if co is not view and u'видимость/графику категорий' not in tpl_notes:
            tpl_notes.append(u'видимость/графику категорий')
        can_hide = True
        try:
            can_hide = co.CanCategoryBeHidden(cid)
        except Exception:
            pass
        rows.append(dict(order=u'Кат.', fid=cid, f=None, name=u'Категория «%s»' % (
            (c.Parent.Name + u' : ' + c.Name) if c.Parent is not None else c.Name),
            hits=1, unknown=0, why=set(), enabled=True, visible=not hidden, ogs=hf.overrides_text(ogs),
            color=hf.swatch_color(ogs), cats=[], rules=u'настройка категории в «Видимость/Графика»'
            + (u' (шаблон «%s»)' % co.Name if co is not view else u' (вид)'),
            orig=read_ogs(ogs), cur=read_ogs(ogs), fade_orig=0, fade_cur=0, fade_n=0,
            kind='cat', own=co, can_hide=can_hide))

if not rows:
    forms.alert(u'На виде «%s» нет фильтров, и у элемента не нашлось категории.' % view.Name, title=TITLE)
    raise SystemExit

# ---- «Графика элемента» на самом виде (не фильтр) — только показать
el_notes = []
for el, ldoc, _ in targets[:50]:
    if ldoc is not None:
        continue
    try:
        if hf.overrides_text(view.GetElementOverrides(el.Id)):
            el_notes.append(_iv(el.Id))
    except Exception:
        pass
tpl_note = u''
if tpl_notes:
    tpl_note = (u'Шаблоном «%s» управляются %s — изменения запишутся в шаблон и коснутся всех видов '
                u'с этим шаблоном.' % (TPL.Name, u' и '.join(tpl_notes)))
if el_notes:
    tpl_note += (u'\nУ элемента задана «Графика элемента» на самом виде (id %s) — она главнее фильтров и '
                 u'категорий; здесь не меняется.' % u', '.join(str(x) for x in el_notes[:5]))
    tpl_note = tpl_note.strip()

# ------------------------------------------------------------ 3а. отчёт в файл (К-И20)
# Каждый запуск пишет отчёт в %TEMP%\xyz_whofilter_last.txt (его читает Claude при разборе вида без окна),
# кнопка «В файл» сохраняет копию в «Документы\XYZ\Чей фильтр» и открывает папку; там хранятся
# только последние 10 отчётов, старые удаляются сами. Файл в %TEMP% один и каждый раз перезаписывается.
def _report_text():
    import datetime
    L = []
    L.append(u'Чей фильтр · %s' % datetime.datetime.now().strftime('%d.%m.%Y %H:%M'))
    L.append(u'Модель: %s' % doc.Title)
    L.append(u'Вид: %s (id %s)%s' % (view.Name, _iv(view.Id), (u' · шаблон «%s»' % TPL.Name) if TPL else u''))
    for el, ldoc, lab in targets[:50]:
        try:
            from Autodesk.Revit.DB import Element as _El
            tn = _El.Name.GetValue((ldoc or doc).GetElement(el.GetTypeId()))
        except Exception:
            tn = u''
        L.append(u'Элемент: id %s · %s · %s%s' % (_iv(el.Id), el.Category.Name if el.Category else u'?', tn,
                                                   (u' · ' + lab) if lab else u''))
    if len(targets) > 50:
        L.append(u'… и ещё элементов: %d' % (len(targets) - 50))
    if tpl_note:
        L.append(u'')
        L.append(tpl_note)
    L.append(u'')
    for r in rows:
        if r['kind'] == 'flt':
            act = u'ДЕЙСТВУЕТ' if r['hits'] else (u'неизвестно' if r['unknown'] else u'не действует')
            L.append(u'[%s] Фильтр «%s» — %s (элементов: %d из %d)' % (r['order'], r['name'], act, r['hits'], len(targets)))
        else:
            L.append(u'[%s] %s' % (r['order'], r['name']))
        L.append(u'    вкл.: %s · видимость: %s' % (u'да' if r['enabled'] else u'нет', u'да' if r['visible'] else u'нет'))
        if r.get('cats'):
            L.append(u'    категории: %s' % u', '.join(r['cats']))
        if r.get('rules'):
            L.append(u'    правила: %s' % r['rules'])
        if r.get('ogs'):
            g = r['ogs']
            L.append(u'    графика: %s' % (u', '.join(g) if isinstance(g, (list, tuple)) else g))
        if r.get('fade_cur'):
            L.append(u'    блёклость: %s' % r['fade_cur'])
        if r.get('why'):
            L.append(u'    почему: %s' % u'; '.join(sorted(r['why'])))
    return u'\n'.join(L) + u'\n'


def _write_report(path):
    import io
    import os
    d = os.path.dirname(path)
    if d and not os.path.isdir(d):
        os.makedirs(d)
    with io.open(path, 'w', encoding='utf-8-sig') as fh:
        fh.write(_report_text())
    return path


try:
    import os as _os
    _write_report(_os.path.join(System.IO.Path.GetTempPath(), u'xyz_whofilter_last.txt'))
except Exception:
    pass


KEEP_REPORTS = 10      # в папке «Документы\\XYZ\\Чей фильтр» хранятся только последние 10 отчётов


def _prune(folder):
    """Оставить в папке последние KEEP_REPORTS отчётов, остальные удалить (только свои *.txt)."""
    import os
    try:
        fs = [os.path.join(folder, f) for f in os.listdir(folder) if f.lower().endswith(u'.txt')]
        fs.sort(key=os.path.getmtime, reverse=True)
        for f in fs[KEEP_REPORTS:]:
            try:
                os.remove(f)
            except Exception:
                pass
    except Exception:
        pass


def on_to_file(s, e):
    import os
    import re
    import datetime
    try:
        base = os.path.join(System.Environment.GetFolderPath(System.Environment.SpecialFolder.MyDocuments),
                            u'XYZ', u'Чей фильтр')
        nm = re.sub(r'[\\/:*?"<>|]+', u'_', view.Name)[:60]
        path = _write_report(os.path.join(base, u'%s_%s.txt' % (nm, datetime.datetime.now().strftime('%Y-%m-%d_%H-%M-%S'))))
        _prune(base)
        System.Diagnostics.Process.Start(u'explorer.exe', u'/select,"%s"' % path)
    except Exception as ex:
        forms.alert(u'Не удалось сохранить отчёт:\n%s' % ex, title=TITLE)


# ------------------------------------------------------------ 4. окно
B = forms._brush
n_t = len(targets)
el0, ld0, lab0 = targets[0]
try:
    tname = doc.GetElement(el0.GetTypeId()).Name if ld0 is None else ld0.GetElement(el0.GetTypeId()).Name
except Exception:
    tname = u''
head = u'%s · %s%s' % (el0.Category.Name, tname, (u' · ' + lab0) if lab0 else u'')
if n_t > 1:
    head = u'Выделено элементов: %d (первый: %s)' % (n_t, head)

dlg = forms._Dialog(TITLE, width=900)
dlg.ResizeMode = ResizeMode.CanResize
n_hit = sum(1 for r in rows if r['hits'] and r['kind'] == 'flt')
n_flt = sum(1 for r in rows if r['kind'] == 'flt')
dlg._s.Text = u'%s · вид «%s» · действуют фильтров: %d из %d' % (head, view.Name, n_hit, n_flt)
dlg._s.Visibility = Visibility.Visible
if tpl_note:
    t = TextBlock()
    t.Text = tpl_note
    t.TextWrapping = TextWrapping.Wrap
    t.Foreground = B(forms.RED)
    t.Margin = Thickness(0, 0, 0, 8)
    dlg.body.Children.Add(t)
hint = TextBlock()
hint.Text = (u'Сверху вниз — по приоритету (при конфликте побеждает фильтр выше в списке «Видимость/Графика»). '
             u'«Вкл.» — фильтр работает; «Видим.» — элементы фильтра показаны; «Графика ▾» — линии, штриховки, '
             u'прозрачность, полутон, как в «Видимость/Графика». «Применить» — сразу на виде, окно остаётся открытым.')
hint.TextWrapping = TextWrapping.Wrap
hint.Foreground = B(forms.MUTE)
hint.FontSize = 11.5
hint.Margin = Thickness(0, 0, 0, 8)
dlg.body.Children.Add(hint)
show_all = CheckBox()
show_all.Content = u'Показать и те фильтры, что не действуют на элемент'
show_all.Margin = Thickness(0, 0, 0, 8)
dlg.body.Children.Add(show_all)

panel = StackPanel()
sv = ScrollViewer()
sv.VerticalScrollBarVisibility = ScrollBarVisibility.Auto
sv.HorizontalScrollBarVisibility = ScrollBarVisibility.Disabled
sv.MaxHeight = max(240, Screen.PrimaryScreen.WorkingArea.Height - 330)
sv.Content = panel
frame = Border()
frame.BorderBrush = B(forms.LINE)
frame.BorderThickness = Thickness(1)
frame.Background = B('#FFFFFF')
frame.Child = sv
dlg.body.Children.Add(frame)

state = {}       # fid -> [enabled, visible]
row_borders = []


# ---- мелкие элементы управления редактора графики
def _hex(c):
    return '#%02X%02X%02X' % c


def pick_color(cur):
    """Окно выбора цвета Revit (как в «Видимость/Графика»); если не открылось — стандартное Windows."""
    try:
        d = ColorSelectionDialog()
        if cur:
            d.SetDialogInitialColor(_rc(cur))
        if d.Show() == ItemSelectionDialogResult.Confirmed:
            c = d.SelectedColor
            return (int(c.Red), int(c.Green), int(c.Blue))
        return None
    except Exception:
        from System.Windows.Forms import ColorDialog, DialogResult
        from System.Drawing import Color as DColor
        d = ColorDialog()
        d.FullOpen = True
        if cur:
            d.Color = DColor.FromArgb(cur[0], cur[1], cur[2])
        if d.ShowDialog() == DialogResult.OK:
            return (int(d.Color.R), int(d.Color.G), int(d.Color.B))
        return None


def color_btn(cur, on_change):
    b = Button()
    b.MinWidth = 0
    b.Width = 46
    b.Height = 24
    b.Padding = Thickness(3)
    b.Margin = Thickness(4, 1, 0, 1)
    b.ToolTip = u'Цвет: щелчок — выбрать, правый щелчок — без переопределения'
    sw = Border()
    sw.Width = 34
    sw.Height = 14
    sw.BorderBrush = B(forms.LINE)
    sw.BorderThickness = Thickness(1)
    lab = TextBlock()
    lab.FontSize = 10
    lab.HorizontalAlignment = HorizontalAlignment.Center
    sw.Child = lab
    b.Content = sw
    val = [cur]

    def paint():
        if val[0]:
            sw.Background = B(_hex(val[0]))
            lab.Text = u''
        else:
            sw.Background = B('#FFFFFF')
            lab.Text = u'—'
    paint()

    def click(s, e):
        c = pick_color(val[0])
        if c:
            val[0] = c
            paint()
            on_change(c)

    def clear(s, e):
        val[0] = None
        paint()
        on_change(None)
    b.Click += click
    b.MouseRightButtonUp += clear
    return b


def combo(items, cur, width, on_change, tip=None):
    cb = ComboBox()
    cb.Width = width
    cb.Margin = Thickness(4, 1, 0, 1)
    if tip:
        cb.ToolTip = tip
    vals = [v for v, _ in items]
    if cur not in vals:
        items = list(items) + [(cur, u'(id %s)' % cur)]
    sel = 0
    for i, (v, lbl) in enumerate(items):
        it = ComboBoxItem()
        it.Content = lbl
        it.Tag = v
        cb.Items.Add(it)
        if v == cur:
            sel = i
    cb.SelectedIndex = sel

    def changed(s, e):
        if s.SelectedItem is not None:
            on_change(s.SelectedItem.Tag)
    cb.SelectionChanged += changed
    return cb


def check(cur, text, on_change, tip=None):
    c = CheckBox()
    c.Content = text
    c.IsChecked = bool(cur)
    c.VerticalAlignment = VerticalAlignment.Center
    c.Margin = Thickness(4, 1, 4, 1)
    if tip:
        c.ToolTip = tip

    def ch(s, e):
        on_change(bool(s.IsChecked))
    c.Checked += ch
    c.Unchecked += ch
    return c


def fill_editor(host, r):
    """Редактор графики фильтра (как строка в «Видимость/Графика»)."""
    host.Children.Clear()
    d = r['cur']

    def setter(key):
        def f(v):
            d[key] = v
            mark_dirty(r)
        return f

    wrap = WrapPanel()

    def group(title, lines):
        bd = Border()
        bd.BorderBrush = B(forms.LINE)
        bd.BorderThickness = Thickness(1)
        bd.Padding = Thickness(8, 4, 8, 6)
        bd.Margin = Thickness(0, 0, 8, 6)
        bd.Background = B('#FAFAFA')
        sp = StackPanel()
        h = TextBlock()
        h.Text = title
        h.FontWeight = FontWeights.SemiBold
        h.Margin = Thickness(0, 0, 0, 2)
        sp.Children.Add(h)
        for lbl, ctrls, keys in lines:
            row = StackPanel()
            row.Orientation = Orientation.Horizontal
            tb = TextBlock()
            tb.Text = lbl
            tb.Width = 112
            tb.VerticalAlignment = VerticalAlignment.Center
            tb.FontSize = 12
            row.Children.Add(tb)
            for c in ctrls:
                row.Children.Add(c)
            row.Children.Add(reset_btn(keys, lbl))
            sp.Children.Add(row)
        bd.Child = sp
        wrap.Children.Add(bd)

    def reset_btn(keys, lbl):
        """↺ — сбросить только эту строку (без переопределения), остальные настройки не трогать."""
        b = Button()
        b.Content = u'↺'
        b.MinWidth = 0
        b.Width = 26
        b.Height = 24
        b.Padding = Thickness(0)
        b.Margin = Thickness(6, 1, 0, 1)
        b.ToolTip = u'Сбросить только «%s» (без переопределения)' % lbl
        changed = any(d[k] != EMPTY[k] for k in keys)
        b.IsEnabled = changed
        b.Opacity = 1.0 if changed else 0.35

        def click(s, e):
            for k in keys:
                d[k] = EMPTY[k]
            mark_dirty(r)
            fill_editor(host, r)
        b.Click += click
        return b

    def lines_row(p):
        return (u'Линии', [color_btn(d[p + '_color'], setter(p + '_color')),
                           combo(WEIGHTS, d[p + '_weight'], 52, setter(p + '_weight'), u'Вес линий'),
                           combo(LINEPATS, d[p + '_pat'], 128, setter(p + '_pat'), u'Образец линий')],
                (p + '_color', p + '_weight', p + '_pat'))

    def pat_row(p, lbl):
        return (lbl, [check(d[p + '_vis'], u'', setter(p + '_vis'), u'Видимость штриховки'),
                      combo(FILLS, d[p + '_pat'], 150, setter(p + '_pat'), u'Образец штриховки'),
                      color_btn(d[p + '_color'], setter(p + '_color'))],
                (p + '_vis', p + '_pat', p + '_color'))

    sl = Slider()
    sl.Minimum = 0
    sl.Maximum = 100
    sl.Width = 150
    sl.IsSnapToTickEnabled = True
    sl.TickFrequency = 5
    sl.Value = d['transp']
    sl.Margin = Thickness(4, 3, 0, 1)
    sl_t = TextBlock()
    sl_t.Text = u'%d %%' % d['transp']
    sl_t.Margin = Thickness(6, 0, 0, 0)
    sl_t.VerticalAlignment = VerticalAlignment.Center

    def sl_ch(s, e):
        v = int(round(s.Value))
        sl_t.Text = u'%d %%' % v
        if v != d['transp']:
            d['transp'] = v
            mark_dirty(r)
    sl.ValueChanged += sl_ch

    group(u'Проекция / поверхность', [lines_row('pl'), pat_row('sfg', u'Штриховка: перед.'),
                                      pat_row('sbg', u'Штриховка: задн.'), (u'Прозрачность', [sl, sl_t], ('transp',))])
    group(u'Сечение', [lines_row('cl'), pat_row('cfg', u'Штриховка: перед.'), pat_row('cbg', u'Штриховка: задн.')])
    host.Children.Add(wrap)

    bottom = StackPanel()
    bottom.Orientation = Orientation.Horizontal
    bottom.Children.Add(check(d['halftone'], u'Полутон', setter('halftone')))
    if hasattr(r['f'], 'GetCategories'):
        fl = TextBlock()
        fl.Text = u'Блёклость'
        fl.Margin = Thickness(14, 0, 0, 0)
        fl.VerticalAlignment = VerticalAlignment.Center
        tip = (u'Насколько бледнее: 0 — как сейчас, 100 — белый (не видно).\n'
               u'Каждая система бледнеет в своём цвете: на каждую — служебный фильтр «zz_блёк …» '
               u'в конце списка фильтров вида. Цвета берутся с вида в момент «Применить».')
        fl.ToolTip = tip
        bottom.Children.Add(fl)
        fs = Slider()
        fs.Minimum = 0
        fs.Maximum = 100
        fs.Width = 150
        fs.IsSnapToTickEnabled = True
        fs.TickFrequency = 5
        fs.Value = r['fade_cur']
        fs.Margin = Thickness(6, 3, 0, 1)
        fs.ToolTip = tip
        fs_t = TextBlock()
        fs_t.Text = u'%d %%' % r['fade_cur']
        fs_t.Margin = Thickness(6, 0, 0, 0)
        fs_t.VerticalAlignment = VerticalAlignment.Center

        def fs_ch(s, e):
            v = int(round(s.Value))
            fs_t.Text = u'%d %%' % v
            if v != r['fade_cur']:
                r['fade_cur'] = v
                mark_dirty(r)
        fs.ValueChanged += fs_ch
        bottom.Children.Add(fs)
        bottom.Children.Add(fs_t)
    rb = Button()
    rb.Content = u'Сбросить всю графику'
    rb.MinWidth = 0
    rb.Padding = Thickness(10, 2, 10, 2)
    rb.Margin = Thickness(16, 0, 0, 0)
    rb.ToolTip = u'Убрать все переопределения графики этого фильтра (применится кнопкой «Применить»)'

    def reset(s, e):
        d.update(EMPTY)
        mark_dirty(r)
        fill_editor(host, r)
    rb.Click += reset
    bottom.Children.Add(rb)
    host.Children.Add(bottom)


def mark_dirty(r):
    dirty = r['cur'] != r['orig'] or r['fade_cur'] != r['fade_orig']
    r['tb_edit'].Text = u'Графика ▴ (не применено)' if dirty else (
        u'Графика ▴' if r['ed'].Visibility == Visibility.Visible else u'Графика ▾')


def g_text(r, ogs):
    txt = hf.overrides_text(ogs)
    if r['fade_orig']:
        txt.append(u'блёклость %d%% (систем: %d)' % (r['fade_orig'], r['fade_n']))
    return txt


def cur_ogs(r):
    if r['kind'] == 'cat':
        return r['own'].GetCategoryOverrides(r['fid'])
    return r['own'].GetFilterOverrides(r['fid'])


def paint_row(r):
    """Обновить подпись «Графика: …» и цветной квадрат после применения."""
    ogs = cur_ogs(r)
    txt = g_text(r, ogs)
    r['tb_g'].Text = u'Графика: ' + (u', '.join(txt) if txt else u'без переопределений')
    c = hf.swatch_color(ogs)
    r['sw'].Background = B(_hex(c)) if c else B('#FFFFFF')


def make_row(r):
    g = Grid()
    for w in (GridLength(30), GridLength(1, GridUnitType.Star), GridLength.Auto):
        cd = ColumnDefinition()
        cd.Width = w
        g.ColumnDefinitions.Add(cd)
    sw = Border()
    sw.Width = 18
    sw.Height = 18
    sw.VerticalAlignment = VerticalAlignment.Top
    sw.Margin = Thickness(0, 2, 0, 0)
    sw.BorderBrush = B(forms.LINE)
    sw.BorderThickness = Thickness(1)
    if r['color']:
        sw.Background = B(_hex(r['color']))
    r['sw'] = sw
    g.Children.Add(sw)
    txt = StackPanel()
    t1 = TextBlock()
    mark = u''
    if r['kind'] == 'cat':
        mark = u''
    elif r['hits']:
        mark = u'  ✔ действует' + (u' (%d из %d)' % (r['hits'], n_t) if n_t > 1 else u'')
    elif r['unknown']:
        mark = u'  ? не проверить'
    t1.Text = u'%s. %s%s' % (r['order'], r['name'], mark)
    t1.FontWeight = FontWeights.SemiBold
    t1.TextWrapping = TextWrapping.Wrap
    if r['kind'] == 'cat' and not r['visible']:
        t1.Foreground = B(forms.RED)
        t1.Text += u' — СКРЫТА'
    elif r['kind'] == 'cat':
        pass
    elif r['hits'] and not r['visible'] and r['enabled']:
        t1.Foreground = B(forms.RED)
        t1.Text += u' — СКРЫВАЕТ'
    elif r['hits']:
        t1.Foreground = B(forms.GREEN)
    txt.Children.Add(t1)
    for key, s_, sz in ((None, u'Категории: ' + u', '.join(r['cats'][:12]) + (u' …' if len(r['cats']) > 12 else u''), 11.5),
                        (None, u'Правила: ' + r['rules'], 11.5),
                        ('tb_g', u'Графика: ' + (u', '.join(g_text(r, cur_ogs(r))) or u'без переопределений'), 11.5),
                        (None, u'; '.join(sorted(r['why'])) if (r['why'] and not r['hits']) else u'', 11)):
        if not s_:
            continue
        tb = TextBlock()
        tb.Text = s_
        tb.TextWrapping = TextWrapping.Wrap
        tb.FontSize = sz
        tb.Foreground = B(forms.MUTE)
        txt.Children.Add(tb)
        if key:
            r[key] = tb
    # раскрывашка редактора графики
    te = TextBlock()
    te.Text = u'Графика ▾'
    te.Foreground = B(forms.GREEN)
    te.FontWeight = FontWeights.SemiBold
    te.FontSize = 12
    te.Cursor = Cursors.Hand
    te.Margin = Thickness(0, 3, 0, 0)
    te.HorizontalAlignment = HorizontalAlignment.Left
    te.ToolTip = u'Линии, штриховки, прозрачность, полутон этого фильтра'
    txt.Children.Add(te)
    r['tb_edit'] = te
    if r['kind'] == 'flt':
        tf = TextBlock()
        tf.Text = u'Изменить фильтр в Revit ▸'
        tf.Foreground = B(forms.MUTE)
        tf.FontSize = 11.5
        tf.Cursor = Cursors.Hand
        tf.Margin = Thickness(0, 2, 0, 0)
        tf.HorizontalAlignment = HorizontalAlignment.Left
        tf.ToolTip = u'Открыть окно Revit «Фильтры» (категории, правила). После «ОК» или «Отмена» это окно откроется снова.'
        tf.MouseLeftButtonUp += lambda s, e, n=r['name']: go_filters(n)
        txt.Children.Add(tf)
    ed = StackPanel()
    ed.Visibility = Visibility.Collapsed
    ed.Margin = Thickness(0, 6, 0, 2)
    txt.Children.Add(ed)
    r['ed'] = ed

    def toggle(s, e):
        if ed.Visibility == Visibility.Visible:
            ed.Visibility = Visibility.Collapsed
        else:
            if not ed.Children.Count:
                fill_editor(ed, r)
            ed.Visibility = Visibility.Visible
        mark_dirty(r)
    te.MouseLeftButtonUp += toggle

    Grid.SetColumn(txt, 1)
    g.Children.Add(txt)
    box = StackPanel()
    box.Orientation = Orientation.Horizontal
    box.VerticalAlignment = VerticalAlignment.Top
    box.Margin = Thickness(10, 0, 0, 0)
    st = state.setdefault(_iv(r['fid']), [r['enabled'], r['visible']])
    for i, lbl in ((0, u'Вкл.'), (1, u'Видим.')):
        if r['kind'] == 'cat' and (i == 0 or not r.get('can_hide', True)):
            continue
        cb = CheckBox()
        cb.Content = lbl
        cb.IsChecked = st[i]
        cb.Margin = Thickness(8, 0, 0, 0)

        def ch(s, e, i=i, st=st):
            st[i] = bool(s.IsChecked)
        cb.Checked += ch
        cb.Unchecked += ch
        box.Children.Add(cb)
    Grid.SetColumn(box, 2)
    g.Children.Add(box)
    bd = Border()
    bd.Padding = Thickness(10, 6, 10, 6)
    bd.BorderBrush = B(forms.LINE)
    bd.BorderThickness = Thickness(0, 0, 0, 1)
    bd.Background = B('#F3F6FB') if r['kind'] == 'cat' else (B('#F1F8F2') if r['hits'] else B('#FFFFFF'))
    bd.Child = g
    panel.Children.Add(bd)
    row_borders.append((bd, r))


for r in rows:
    make_row(r)


def refresh(s=None, e=None):
    allv = bool(show_all.IsChecked)
    shown = 0
    for bd, r in row_borders:
        vis = allv or r['hits'] or r['unknown']
        bd.Visibility = Visibility.Visible if vis else Visibility.Collapsed
        shown += 1 if vis else 0
    if not shown and not allv:
        show_all.IsChecked = True


show_all.Checked += refresh
show_all.Unchecked += refresh
refresh()


# ------------------------------------------------------------ 5. применить (окно остаётся открытым)
def pending():
    return [r for r in rows
            if state[_iv(r['fid'])] != [r['enabled'], r['visible']] or r['cur'] != r['orig']
            or r['fade_cur'] != r['fade_orig']]


FADE_LIMIT = 25


def apply_changes():
    changes = pending()
    if not changes:
        return True
    for r in changes:
        if r['fade_cur'] and r['fade_cur'] != r['fade_orig'] and not r['fade_orig']:
            n = xyz_fade.count(doc, view, r['f'])
            if n > FADE_LIMIT and not forms.alert(
                    u'Для блёклости «%s» понадобится служебных фильтров: %d (по одному на систему).\n\n'
                    u'Много фильтров может замедлить перерисовку вида. Продолжить?' % (r['name'], n),
                    title=TITLE, yes=True, no=True):
                r['fade_cur'] = r['fade_orig']
                if r['ed'].Children.Count:
                    fill_editor(r['ed'], r)
                mark_dirty(r)
    changes = pending()
    if not changes:
        return True
    # цвет линий/штриховки у самого фильтра перекрывает блёклость (в Revit главнее фильтр выше в списке,
    # а служебные стоят в конце) — предложить убрать
    CK = ('pl_color', 'cl_color', 'sfg_color', 'sbg_color', 'cfg_color', 'cbg_color')
    for r in changes:
        if r['fade_cur'] and any(r['cur'][c] for c in CK):
            if forms.alert(u'У фильтра «%s» задан свой цвет линий или штриховки — он перекроет блёклость, '
                           u'и все его системы будут этого цвета.\n\nУбрать цвета у фильтра (полутон и прозрачность '
                           u'останутся)?' % r['name'], title=TITLE, yes=True, no=True):
                for c in CK:
                    r['cur'][c] = None
                if r['ed'].Children.Count:
                    fill_editor(r['ed'], r)
    notes = []
    t = Transaction(doc, TITLE + (u': шаблон «%s»' % TPL.Name if any(r['own'] is not view for r in changes) else u': фильтры вида'))
    t.Start()
    try:
        for r in changes:
            en, vi = state[_iv(r['fid'])]
            o = r['own']
            if r['kind'] == 'cat':
                if vi != r['visible']:
                    o.SetCategoryHidden(r['fid'], not vi)
                if r['cur'] != r['orig']:
                    o.SetCategoryOverrides(r['fid'], build_ogs(r['cur']))
                continue
            if en != r['enabled']:
                o.SetIsFilterEnabled(r['fid'], en)
            if vi != r['visible']:
                o.SetFilterVisibility(r['fid'], vi)
            if r['cur'] != r['orig']:
                o.SetFilterOverrides(r['fid'], build_ogs(r['cur']))
        # блёклость — после остальных изменений (цвета берутся из настроек фильтров, перерисовка не нужна)
        for r in changes:
            if r['kind'] == 'flt' and (r['fade_cur'] != r['fade_orig'] or (r['fade_cur'] and r['cur'] != r['orig'])):
                n, nt = xyz_fade.apply(doc, view, owner, r['f'], r['fade_cur'], hf)
                r['fade_n'] = n
                notes.extend(u'«%s»: %s' % (r['name'], x) for x in nt)
                if r['fade_cur'] and not n:
                    notes.append(u'«%s»: на виде нет элементов этого фильтра — блёклость не задана' % r['name'])
        t.Commit()
    except Exception:
        if t.HasStarted() and not t.HasEnded():
            t.RollBack()
        import traceback
        forms.alert(u'Не удалось применить:\n\n' + traceback.format_exc(), title=TITLE)
        return False
    for r in changes:
        r['enabled'], r['visible'] = state[_iv(r['fid'])]
        r['orig'] = dict(r['cur'])
        r['fade_orig'] = r['fade_cur']
        paint_row(r)
        mark_dirty(r)
    try:
        uidoc.RefreshActiveView()
    except Exception:
        pass
    if notes:
        forms.alert(u'\n'.join(notes[:20]), title=TITLE)
    return True


def on_apply(s, e):
    apply_changes()


def on_ok(s, e):
    if apply_changes():
        dlg.Close()


def on_close(s, e):
    if pending() and forms.alert(u'Есть неприменённые изменения. Применить их?', title=TITLE, yes=True, no=True):
        apply_changes()
    dlg.Close()


def on_unfade(s, e):
    n = sum(1 for i in owner.GetFilters() if xyz_fade.is_helper(doc.GetElement(i)))
    if not n:
        forms.alert(u'На этом виде блёклости нет.', title=TITLE)
        return
    if not forms.alert(u'Убрать всю блёклость с вида (служебных фильтров: %d)?' % n, title=TITLE, yes=True, no=True):
        return
    t = Transaction(doc, TITLE + u': убрать блёклость')
    t.Start()
    xyz_fade.remove_all(doc, owner)
    t.Commit()
    for r in rows:
        r['fade_orig'] = r['fade_cur'] = r['fade_n'] = 0
        if r['ed'].Children.Count:
            fill_editor(r['ed'], r)
        paint_row(r)
        mark_dirty(r)
    try:
        uidoc.RefreshActiveView()
    except Exception:
        pass


tf_b = Button()
tf_b.Content = u'В файл'
tf_b.Margin = Thickness(0, 0, 8, 0)
tf_b.MinWidth = 70
tf_b.ToolTip = u'Сохранить отчёт (фильтры, правила, графика) в «Документы\\XYZ\\Чей фильтр» и открыть папку'
tf_b.Click += on_to_file
dlg.footer.Children.Add(tf_b)
fb = Button()
fb.Content = u'Фильтры…'
fb.Margin = Thickness(0, 0, 8, 0)
fb.MinWidth = 90
fb.ToolTip = u'Окно Revit «Фильтры»: категории и правила. После «ОК» или «Отмена» это окно откроется снова.'
fb.Click += lambda s, e: go_filters(None)
dlg.footer.Children.Add(fb)
ub = Button()
ub.Content = u'Убрать всю блёклость'
ub.Margin = Thickness(0, 0, 24, 0)
ub.MinWidth = 90
ub.ToolTip = u'Удалить все служебные фильтры «zz_блёк …» с этого вида (или шаблона)'
ub.Click += on_unfade
dlg.footer.Children.Add(ub)

for text, handler, primary, cancel in ((u'Закрыть', on_close, False, True), (u'Применить', on_apply, False, False),
                                       (u'ОК', on_ok, True, False)):
    b = Button()
    b.Content = text
    b.Margin = Thickness(8, 0, 0, 0)
    b.MinWidth = 90
    b.IsDefault = primary
    b.IsCancel = cancel
    b.Click += handler
    dlg.footer.Children.Add(b)

forms.adaptive(dlg, 'whofilter')
dlg.ShowDialog()
if GO['filters']:
    open_filters_and_return(GO['name'])
