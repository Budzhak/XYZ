# -*- coding: utf-8 -*-
"""Панель «XYZ» на контекстной вкладке «Изменить | …».

Revit показывает вкладку «Изменить | <категория>» (Id «Modify»), когда что-то выделено.
Через AdWindows добавляем туда свою панель с копиями наших кнопок. Кнопка запускает
команду pyRevit так же, как с ленты: UIApplication.PostCommand(<Id кнопки>).
Обработчик — свой ICommand (у копий родной обработчик Revit делает кнопки серыми): при нажатии
находит такую же «живую» кнопку на вкладке XYZ и вызывает её родной обработчик — как щелчок мышью.
PostCommand — только запасной путь (после Reload pyRevit для части кнопок молча не срабатывал).
Ставится из startup.py (ensure — раз в 3 с проверяет, что панель на месте).

    import xyz_ctxpanel
    xyz_ctxpanel.install(uiapp)          # из startup.py
"""
import clr
clr.AddReference('AdWindows')
clr.AddReference('PresentationCore')
from System.Windows.Input import ICommand
import Autodesk.Windows as aw
from Autodesk.Revit.UI import RevitCommandId

PANEL_ID = u'XYZ_ctx'
TAB_ID = u'Modify'
XYZ_TAB = u'XYZ'
# какие кнопки (окончание Id «...%<папка кнопки>»), по порядку
BUTTONS = (u'Analis', u'WhoFilter', u'TypeFilter', u'Align', u'MEPAlign', u'Cut3D')
# кнопки только для 3D-вида (db 06.11.2026: «Подрезать 3D» на планах не нужна)
VIEW3D_ONLY = (u'Cut3D',)
VA_KEY = u'XYZ_ctx_viewactivated'
# панель «Оформить» (17.10.2026): малые кнопки без подписи, стопками по 3
COMPACT = ((u'Stack', u'Snap', u'Spread'), (u'Reset', u'Reverse', u'AlignV'),
           (u'AlignH', u'Measure', u'Merge'), (u'NumClick', u'NumClock', u'Straight'))
COMPACT_PANEL = (u'Оформить', u'Annotate')   # название панели (ru / en)


def _walk(items):
    """Все кнопки, в т.ч. внутри стопок (RibbonRowPanel) и выпадающих."""
    for it in items:
        yield it
        sub = getattr(it, 'Items', None)
        if sub is not None:
            try:
                for x in _walk(sub):
                    yield x
            except Exception:
                pass


def compact(uiapp=None):
    """Убрать подписи у кнопок панели «Оформить» на вкладке XYZ — только значки."""
    xyz_tab = _tab(title=XYZ_TAB)
    if xyz_tab is None:
        return 0
    n = 0
    for p in _live_panels(xyz_tab):
        if p.Source is None or p.Source.Title not in COMPACT_PANEL:
            continue
        for it in _walk(p.Source.Items):
            if isinstance(it, aw.RibbonButton) and it.ShowText:
                it.ShowText = False
                n += 1
    return n

_keep = []      # держим ссылки, чтобы сборщик мусора не удалил обработчики


def _log(msg):
    try:
        import io, os, tempfile
        with io.open(os.path.join(tempfile.gettempdir(), u'xyz_ctxpanel_log.txt'), 'a', encoding='utf-8') as f:
            f.write(u'%s\n' % msg)
    except Exception:
        pass


class _Post(ICommand):
    """Запуск команды по её Id (Id кнопки pyRevit)."""
    def __init__(self, uiapp):
        self.uiapp = uiapp

    def add_CanExecuteChanged(self, handler):
        pass

    def remove_CanExecuteChanged(self, handler):
        pass

    def CanExecute(self, parameter):
        return True

    def Execute(self, parameter):
        # AdWindows передаёт сюда саму кнопку (RibbonButton), Id команды — в её CommandParameter
        try:
            cmd_id = getattr(parameter, 'CommandParameter', None) or parameter
            # 1) как обычное нажатие: живая кнопка на вкладке XYZ и её родной обработчик Revit
            #    (PostCommand после Reload pyRevit для части кнопок молча не срабатывал)
            orig = _find_live(u'%s' % cmd_id)
            if orig is not None and orig.CommandHandler is not None:
                h = orig.CommandHandler
                if h.CanExecute(orig):
                    h.Execute(orig)
                    return
            cid = RevitCommandId.LookupCommandId(u'%s' % cmd_id)
            if cid is None:
                _log(u'нет команды %s' % cmd_id)
                return
            if hasattr(self.uiapp, 'PostCommand'):
                self.uiapp.PostCommand(cid)
        except Exception as ex:
            _log(u'ошибка: %s' % ex)


def _find_live(cmd_id):
    xyz_tab = _tab(title=XYZ_TAB)
    if xyz_tab is None:
        return None
    for p in _live_panels(xyz_tab):
        for it in _walk(p.Source.Items):
            if it.Id == cmd_id:
                return it
    return None


def _live_panels(tab):
    """Панели вкладки, видимые на ленте. После Reload pyRevit старые панели (до
    переименования) остаются скрытыми до перезапуска Revit — их кнопки не брать."""
    return [p for p in tab.Panels if p.Source is not None and p.IsVisible]


def _tab(tid=None, title=None):
    for t in aw.ComponentManager.Ribbon.Tabs:
        if (tid and t.Id == tid) or (title and t.Title == title):
            return t
    return None


def _is3d_view(view):
    try:
        from Autodesk.Revit.DB import View3D
        return isinstance(view, View3D)
    except Exception:
        return True


def _set_3d_visible(is3d):
    mod = _tab(TAB_ID)
    if mod is None:
        return
    ids = set(u'XYZ_ctx_' + b for b in VIEW3D_ONLY)
    for p in mod.Panels:
        if p.Source is None or p.Source.Id != PANEL_ID:
            continue
        for it in _walk(p.Source.Items):
            if getattr(it, 'Id', None) in ids:
                it.IsVisible = bool(is3d)


def _on_view(sender, e):
    try:
        _set_3d_visible(_is3d_view(e.CurrentActiveView))
    except Exception as ex:
        _log(u'view: %s' % ex)


def hook_view(uiapp):
    """Показывать кнопки VIEW3D_ONLY только на 3D-виде: событие ViewActivated (одно на сессию,
    после Reload pyRevit старый обработчик снимается)."""
    from System import AppDomain
    try:
        old = AppDomain.CurrentDomain.GetData(VA_KEY)
        if old is not None:
            try:
                uiapp.ViewActivated -= old
            except Exception:
                pass
        uiapp.ViewActivated += _on_view
        AppDomain.CurrentDomain.SetData(VA_KEY, _on_view)
        _keep.append(_on_view)
    except Exception as ex:
        _log(u'hook_view: %s' % ex)


def ensure(uiapp):
    """Поставить панель, если её нет (вызывать по таймеру: вкладка XYZ появляется не сразу)."""
    mod = _tab(TAB_ID)
    if mod is None or _tab(title=XYZ_TAB) is None:
        return False
    try:
        compact()
    except Exception as ex:
        _log(u'compact: %s' % ex)
    for p in mod.Panels:
        if p.Source is not None and p.Source.Id == PANEL_ID:
            # панель поставлена раньше, чем появились кнопки «Оформить», — переставить
            have = set(getattr(it, 'Id', None) for it in _walk(p.Source.Items))
            if u'XYZ_ctx_' + COMPACT[0][0] not in have and _has_live(COMPACT[0][0]):
                return install(uiapp) > 0
            _sync(p.Source)
            return True
    return install(uiapp) > 0


def _sync(src):
    """Подписи и подсказки копий — как у живых кнопок (после Reload заголовок мог смениться)."""
    try:
        for it in _walk(src.Items):
            cp = getattr(it, 'CommandParameter', None)
            if not cp:
                continue
            o = _find_live(u'%s' % cp)
            if o is not None and o.Text != it.Text:
                it.Text = o.Text
                it.ToolTip = o.ToolTip if o.ToolTip is not None else o.Text
                it.Image = o.Image
                it.LargeImage = o.LargeImage
    except Exception as ex:
        _log(u'sync: %s' % ex)


def _has_live(name):
    xyz_tab = _tab(title=XYZ_TAB)
    if xyz_tab is None:
        return False
    for p in _live_panels(xyz_tab):
        for it in _walk(p.Source.Items):
            if (getattr(it, 'Id', None) or u'').endswith(u'%' + name):
                return True
    return False


def remove():
    mod = _tab(TAB_ID)
    if mod is None:
        return 0
    old = [p for p in mod.Panels if p.Source is not None and p.Source.Id == PANEL_ID]
    for p in old:
        mod.Panels.Remove(p)
    return len(old)


def install(uiapp, buttons=BUTTONS):
    """Поставить (или переставить) панель. Возвращает число кнопок."""
    mod = _tab(TAB_ID)
    xyz_tab = _tab(title=XYZ_TAB)
    if mod is None or xyz_tab is None:
        return 0
    remove()
    found = {}
    names = list(buttons) + [b for g in COMPACT for b in g]
    for p in _live_panels(xyz_tab):
        for it in _walk(p.Source.Items):
            iid = getattr(it, 'Id', None) or u''
            for b in names:
                if iid.endswith(u'%' + b):
                    found[b] = it
    cmd = _Post(uiapp)
    _keep.append(cmd)
    src = aw.RibbonPanelSource()
    src.Title = XYZ_TAB
    src.Id = PANEL_ID
    n = 0
    for b in buttons:
        o = found.get(b)
        if o is None:
            continue
        nb = aw.RibbonButton()
        nb.Id = u'XYZ_ctx_' + b
        nb.Text = o.Text
        nb.Image = o.Image
        nb.LargeImage = o.LargeImage
        nb.ToolTip = o.ToolTip
        nb.Size = o.Size
        nb.Orientation = o.Orientation
        nb.ShowText = True
        nb.ShowImage = True
        nb.CommandHandler = cmd
        nb.CommandParameter = o.Id
        nb.IsEnabled = True
        if b in VIEW3D_ONLY:
            try:
                nb.IsVisible = _is3d_view(uiapp.ActiveUIDocument.ActiveView)
            except Exception:
                pass
        src.Items.Add(nb)
        n += 1
    # стопки малых кнопок «Оформить» — только значки
    for grp in COMPACT:
        rp = aw.RibbonRowPanel()
        k = 0
        for b in grp:
            o = found.get(b)
            if o is None:
                continue
            if k:
                rp.Items.Add(aw.RibbonRowBreak())
            nb = aw.RibbonButton()
            nb.Id = u'XYZ_ctx_' + b
            nb.Text = o.Text
            nb.Image = o.Image
            nb.LargeImage = o.LargeImage
            nb.ToolTip = o.ToolTip if o.ToolTip is not None else o.Text
            nb.Size = aw.RibbonItemSize.Standard
            nb.ShowText = False
            nb.ShowImage = True
            nb.CommandHandler = cmd
            nb.CommandParameter = o.Id
            nb.IsEnabled = True
            rp.Items.Add(nb)
            k += 1
            n += 1
        if k:
            src.Items.Add(rp)
    pan = aw.RibbonPanel()
    pan.Source = src
    mod.Panels.Add(pan)
    _keep.append(pan)
    if not _hooked:
        hook_view(uiapp)
        _hooked.append(1)
    return n


_hooked = []
