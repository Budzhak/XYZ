# -*- coding: utf-8 -*-
"""Значок у названия вкладки «XYZ».

pyRevit выполняет этот файл при запуске Revit и при каждом Reload.
В заголовок вкладки (mStackPanel кнопки вкладки) перед текстом
вставляется картинка tab_icon.png из папки расширения.
Таймер (раз в 3 с) работает, только пока значок, панель на «Изменить | …»
и (если включено) порядок вкладок не встали на место, — потом останавливается.
"""
import os
import sys
import traceback

LOG = os.path.join(os.environ.get('TEMP', ''), 'zb_tab_icon.log')


def _log(msg):
    try:
        import io
        if not isinstance(msg, type(u'')):
            try:
                msg = msg.decode('utf-8')
            except Exception:
                msg = repr(msg)
        with io.open(LOG, 'a', encoding='utf-8') as f:
            f.write(msg + u'\n')
    except Exception as ex:
        try:
            with open(LOG, 'a') as f:
                f.write('LOGFAIL ' + repr(ex) + ' | ' + repr(msg)[:2000] + '\n')
        except Exception:
            pass


_log('--- startup: ' + sys.version.split()[0])
try:
    _here = os.path.dirname(os.path.abspath(__file__))
except NameError:
    _here = os.path.join(os.environ.get('APPDATA', ''), 'pyRevit', 'Extensions', u'XYZ.extension'.encode('utf-8') if sys.version_info[0] < 3 else u'XYZ.extension')
_log('dir: ' + repr(_here))

_OK = True
try:
    import clr
    from System import AppDomain as _AD
    _loaded = dict((a.GetName().Name, a) for a in _AD.CurrentDomain.GetAssemblies())
    for _n in ('AdWindows', 'PresentationCore', 'PresentationFramework', 'WindowsBase'):
        try:
            if _n in _loaded:
                clr.AddReference(_loaded[_n])
            else:
                clr.AddReference(_n)
        except Exception:
            _log('AddReference fail: ' + _n + ' ' + traceback.format_exc())
    _log('refs ok')

    from System import TimeSpan, AppDomain
    from System.IO import FileStream, FileMode, FileAccess, FileShare
    from System.Windows import FrameworkElement, Thickness, VerticalAlignment
    from System.Windows.Controls import Image, StackPanel, Orientation
    from System.Windows.Media import VisualTreeHelper, RenderOptions, BitmapScalingMode
    from System.Windows.Media.Imaging import BitmapImage, BitmapCacheOption
    from System.Windows.Threading import DispatcherTimer
    from Autodesk.Windows import ComponentManager
    _log('imports ok')

except Exception:
    _OK = False
    _log(traceback.format_exc())

TAB_ID = u'XYZ'
ICON = os.path.join(_here, 'tab_icon.png')
MARK = 'db_tab_icon'
KEY = 'db_tab_icon_timer'
SIZE = 16

_state = {'panel': None}


def _bitmap():
    # Uri в Revit 2025 (.NET 8) из IronPython не импортируется — читаем файл потоком
    fs = FileStream(ICON, FileMode.Open, FileAccess.Read, FileShare.Read)
    try:
        bmp = BitmapImage()
        bmp.BeginInit()
        bmp.StreamSource = fs
        bmp.CacheOption = BitmapCacheOption.OnLoad
        bmp.EndInit()
        bmp.Freeze()
    finally:
        fs.Close()
    return bmp


def _find_tab():
    ribbon = ComponentManager.Ribbon
    if ribbon is None:
        return None, None
    for tab in ribbon.Tabs:
        if tab.Id == TAB_ID:
            return ribbon, tab
    return ribbon, None


def _find_panel(root, tab):
    stack = [root]
    while stack:
        o = stack.pop()
        if isinstance(o, FrameworkElement) and o.Name == 'mStackPanel' and o.DataContext is tab:
            return o
        try:
            n = VisualTreeHelper.GetChildrenCount(o)
        except Exception:
            n = 0
        for i in range(n):
            stack.append(VisualTreeHelper.GetChild(o, i))
    return None


def _has_icon(panel):
    for ch in panel.Children:
        if getattr(ch, 'Tag', None) == MARK:
            return True
    return False


_done = {'icon': False, 'ctx': False, 'tab': False, 'n': 0}


def _restart_timer(*args):
    try:
        _done['icon'] = False
        _done['n'] = 0
        tm = AppDomain.CurrentDomain.GetData(KEY)
        if tm is not None and not tm.IsEnabled:
            tm.Start()
    except Exception:
        _log('restart timer: ' + traceback.format_exc())


def ensure_icon(*args):
    try:
        panel = _state['panel']
        if panel is not None and panel.IsLoaded and _has_icon(panel):
            _done['icon'] = True
            return
        ribbon, tab = _find_tab()
        if tab is None:
            return
        panel = _find_panel(ribbon, tab)
        if panel is None:
            return
        _state['panel'] = panel
        if _has_icon(panel):
            _done['icon'] = True
            return
        img = Image()
        img.Source = _bitmap()
        img.Width = SIZE
        img.Height = SIZE
        img.Margin = Thickness(0, 0, 4, 0)
        img.VerticalAlignment = VerticalAlignment.Center
        img.Tag = MARK
        RenderOptions.SetBitmapScalingMode(img, BitmapScalingMode.HighQuality)
        if isinstance(panel, StackPanel):
            panel.Orientation = Orientation.Horizontal
        panel.Children.Insert(0, img)
        _done['icon'] = True
        try:
            panel.Unloaded += _restart_timer   # Revit пересоздал заголовок (сворачивание ленты, тема) — проверить снова
        except Exception:
            pass
    except Exception:
        _log(traceback.format_exc())


_log('icon exists: ' + str(os.path.exists(ICON)))
if _OK and os.path.exists(ICON):
    try:
        old = AppDomain.CurrentDomain.GetData(KEY)
        if old is not None:
            try:
                old.Stop()
            except Exception:
                pass
        _log('make timer')
        timer = DispatcherTimer()
        timer.Interval = TimeSpan.FromSeconds(3)
        timer.Tick += ensure_icon
        timer.Start()
        AppDomain.CurrentDomain.SetData(KEY, timer)
        ensure_icon()
        _log('timer started')
    except Exception:
        _log(traceback.format_exc())


# ------------------------------------------------------------------
# Марки-отметки на взрыв-схемах (lib/xyz_elev_marks.py): обработчик изменений
# модели пересчитывает значения и положение марок db_М_Отметка_Схемы при
# изменении геометрии элементов и смещений на взрыв-схемах.
# Регистрируется, только если включён (xyz_settings 'elev_marks_auto', кнопка «Автопилот»).
# ------------------------------------------------------------------
try:
    _lib = os.path.join(_here, 'lib')
    if _lib not in sys.path:
        sys.path.append(_lib)
    sys.modules.pop('xyz_settings', None)
    import xyz_settings
    if xyz_settings.get('elev_marks_auto'):
        sys.modules.pop('xyz_elev_marks', None)
        import xyz_elev_marks
        xyz_elev_marks.register(__revit__.ActiveAddInId)
        _log('xyz_elev_marks updater registered')
    else:
        _log('xyz_elev_marks updater off (elev_marks_auto = False)')
except Exception:
    _log('xyz_elev_marks: ' + traceback.format_exc())


# ------------------------------------------------------------------
# Панель «XYZ» на контекстной вкладке «Изменить | …», lib/xyz_ctxpanel.py.
# Вкладка XYZ строится не сразу — ставим по таймеру (тот же, что для значка), если панели нет.
# После Reload pyRevit кнопки XYZ пересоздаются — переставляем панель заново.
# ------------------------------------------------------------------
try:
    sys.modules.pop('xyz_ctxpanel', None)
    import xyz_ctxpanel
    _ctx_uiapp = __revit__
    xyz_ctxpanel.remove()

    def _ensure_ctx(*args):
        try:
            _done['ctx'] = bool(xyz_ctxpanel.ensure(_ctx_uiapp))
        except Exception:
            _log('ctxpanel: ' + traceback.format_exc())

    _ctx_timer = AppDomain.CurrentDomain.GetData(KEY)
    if _ctx_timer is not None:
        _ctx_timer.Tick += _ensure_ctx
    _ensure_ctx()
    _log('ctxpanel hooked')
except Exception:
    _log('ctxpanel: ' + traceback.format_exc())


# ------------------------------------------------------------------
# Вкладка «XYZ» — сразу после «Вставить» (db, 18.10.2026), только если включено
# в настройках: xyz_settings 'tab_after_insert' (по умолчанию выключено).
# Revit ставит вкладки надстроек в конец; переносим и следим тем же таймером
# (после Reload pyRevit или загрузки других надстроек вкладка снова уезжает в конец).
# ------------------------------------------------------------------
AFTER_TAB = u'Insert'


def _ensure_tab_order(*args):
    try:
        import xyz_settings
        if not xyz_settings.get('tab_after_insert'):
            _done['tab'] = True               # по умолчанию порядок вкладок не трогаем
            return
        ribbon = ComponentManager.Ribbon
        if ribbon is None:
            return
        tabs = ribbon.Tabs
        xyz_tab = ins = -1
        for i in range(tabs.Count):
            tid = tabs[i].Id
            if tid == TAB_ID:
                xyz_tab = i
            elif tid == AFTER_TAB:
                ins = i
        if xyz_tab >= 0 and xyz_tab == ins + 1:
            _done['tab'] = True
            return
        if xyz_tab < 0 or ins < 0:
            return
        # Move() Revit не перерисовывает (вкладка остаётся в конце) — только Remove + Insert
        tab = tabs[xyz_tab]
        active = ribbon.ActiveTab
        tabs.Remove(tab)
        for i in range(tabs.Count):
            if tabs[i].Id == AFTER_TAB:
                tabs.Insert(i + 1, tab)
                break
        try:
            ribbon.ActiveTab = active
        except Exception:
            pass
    except Exception:
        _log('tab order: ' + traceback.format_exc())


try:
    _ord_timer = AppDomain.CurrentDomain.GetData(KEY)
    if _ord_timer is not None:
        _ord_timer.Tick += _ensure_tab_order
    _ensure_tab_order()
    _log('tab order hooked')
except Exception:
    _log('tab order: ' + traceback.format_exc())


# ------------------------------------------------------------------
# Таймер больше не нужен, когда всё на месте (или через 5 минут на всякий случай).
# ------------------------------------------------------------------
def _stop_when_done(*args):
    try:
        _done['n'] += 1
        if (_done['icon'] and _done['ctx'] and _done['tab']) or _done['n'] >= 100:
            tm = AppDomain.CurrentDomain.GetData(KEY)
            if tm is not None:
                tm.Stop()
            _log('timer stopped: %s' % dict(_done))
    except Exception:
        _log('timer stop: ' + traceback.format_exc())


try:
    _stop_timer = AppDomain.CurrentDomain.GetData(KEY)
    if _stop_timer is not None:
        _stop_timer.Tick += _stop_when_done
except Exception:
    _log('timer stop hook: ' + traceback.format_exc())


# ------------------------------------------------------------------
# Кнопка, перенесённая в стопку на живой ленте (без перезапуска Revit), после Reload
# продолжает ссылаться на старую сборку pyRevit и старый путь скрипта («Can not find
# target file»). Переназначаем её на свежую сборку — ту же, что у соседней кнопки стопки.
# (db 18.10.2026: «Прямая выноска» → S4.stack)
# ------------------------------------------------------------------
_REPOINT = [((u'Оформить', u'Annotate'), u'Straight', u'NumClick', u'xyz_xyz_annotate_s4_straight')]


def _repoint_buttons():
    try:
        for p in __revit__.GetRibbonPanels(TAB_ID):
            items = dict((it.Name, it) for it in p.GetItems())
            for pan, name, neigh, cls in _REPOINT:
                if p.Name not in pan or name not in items or neigh not in items:
                    continue
                b, n = items[name], items[neigh]
                if b.AssemblyName != n.AssemblyName or b.ClassName != cls:
                    b.AssemblyName = n.AssemblyName
                    b.ClassName = cls
                    _log('repoint %s -> %s' % (name, cls))
    except Exception:
        _log('repoint: ' + traceback.format_exc())


_repoint_buttons()


# ------------------------------------------------------------------
# Новый год (db, 07.11.2026): фон панелей со снежинками, ёлочками и мигающей гирляндой,
# раз в минуту над лентой пролетает Дед Мороз. Сам включается 15.12–15.01 (lib/xyz_newyear.py).
# Значки кнопок не меняются.
# ------------------------------------------------------------------
try:
    sys.modules.pop('xyz_newyear', None)
    import xyz_newyear
    _log('newyear: %s' % xyz_newyear.start())
except Exception:
    _log('newyear: ' + traceback.format_exc())
