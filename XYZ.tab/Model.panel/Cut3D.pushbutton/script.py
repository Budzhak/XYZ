# -*- coding: utf-8 -*-
"""Подрезать 3D: рамка 3D-вида сверху и снизу — по уровням со смещением, как «Секущий диапазон» плана.

Окно: 3D-виды (активный и выбранные в диспетчере — отмечены), «Верх» и «Низ» — уровень + смещение, мм.
Границы в плане: как сейчас у рамки вида; если рамки нет или стоит галочка «по модели» — по габариту
элементов вида. Повёрнутая рамка поддерживается (поворот вокруг вертикали).
«⤓ Указать» у «Верха» и «Низа» — щёлкнуть по плоскости (грань элемента, в т. ч. в связи): рамка сразу
подрезается по этой отметке, уровень и смещение подставляются в окно — дальше можно поправить числом.
«Применить» — окно остаётся открытым; «Закрыть». Отмена изменений — Ctrl+Z в Revit.
Последние уровни и смещения запоминаются (xyz_settings, ключ cut3d).
Окно по стандарту «Объёмов»: тянется, Ctrl+колесо — масштаб, размер запоминается, ошибки — окном.
"""
import clr
from pyrevit import revit, DB
from Autodesk.Revit.UI.Selection import ObjectType
from Autodesk.Revit.Exceptions import OperationCanceledException
import xyz_forms as forms   # единый стиль окон XYZ (lib/xyz_forms.py)
from System.Windows.Controls import CheckBox
from System.Windows.Input import Keyboard, ModifierKeys, Key
from System.Windows.Media import ScaleTransform, SolidColorBrush, Color

doc = revit.doc
uidoc = revit.uidoc
MM = 1.0 / 304.8

try:
    import xyz_settings
    CFG = dict(xyz_settings.get('cut3d') or {})
except Exception:
    xyz_settings = None
    CFG = {}


def save_cfg():
    if xyz_settings is not None:
        try:
            xyz_settings.set('cut3d', CFG)
        except Exception:
            pass


def guarded(fn):
    """Ошибка в обработчике — окном с текстом, а не «нажал — ничего»."""
    def wrap(*a):
        try:
            return fn(*a)
        except Exception:
            import traceback
            forms.alert(u'Ошибка — действие не выполнено:\n\n' + traceback.format_exc()[-1500:], title=u'Подрезать 3D')
    return wrap


def fmt(x):
    return (u'%.0f' % x) if abs(x - round(x)) < 0.05 else (u'%.1f' % x)


def num(tb):
    try:
        return float(tb.Text.replace(u',', u'.').strip() or 0)
    except ValueError:
        return None


def vname(v):
    return DB.Element.Name.GetValue(v)


LEVELS = sorted(DB.FilteredElementCollector(doc).OfClass(DB.Level), key=lambda l: l.ProjectElevation)


def lvl_text(l):
    mm = l.ProjectElevation / MM
    return u'%s  (%s%s)' % (vname(l), u'+' if mm >= 0 else u'', fmt(mm))


VIEWS = sorted([v for v in DB.FilteredElementCollector(doc).OfClass(DB.View3D) if not v.IsTemplate],
               key=lambda v: vname(v))
PRESEL = set(i.IntegerValue for i in uidoc.Selection.GetElementIds())
if isinstance(doc.ActiveView, DB.View3D):
    PRESEL.add(doc.ActiveView.Id.IntegerValue)


def model_extents(view):
    """Габарит модельных элементов вида в плане (X, Y), внутренние координаты."""
    """Связи и импорт не учитываются, элементы больше 1 км — тоже; крайние 0,5 % отбрасываются
    (в моделях бывает мусор за километры от здания)."""
    big = 1000000 * MM
    x0, y0, x1, y1 = [], [], [], []
    for el in DB.FilteredElementCollector(doc, view.Id).WhereElementIsNotElementType():
        cat = el.Category
        if cat is None or cat.CategoryType != DB.CategoryType.Model:
            continue
        if isinstance(el, (DB.RevitLinkInstance, DB.ImportInstance)):
            continue
        bb = el.get_BoundingBox(None)
        if bb is None or bb.Max.X - bb.Min.X > big or bb.Max.Y - bb.Min.Y > big:
            continue
        x0.append(bb.Min.X); y0.append(bb.Min.Y); x1.append(bb.Max.X); y1.append(bb.Max.Y)
    if not x0:
        return None
    k = int(len(x0) * 0.005)

    def lo(a):
        return sorted(a)[k]

    def hi(a):
        return sorted(a)[-1 - k]
    return lo(x0), lo(y0), hi(x1), hi(y1)


def apply_view(view, z_bot, z_top, by_model):
    """z — отметки в координатах модели (футы). Возвращает текст о результате."""
    box = view.GetSectionBox() if view.IsSectionBoxActive else None
    if box is not None and not by_model:
        t = box.Transform
        if abs(t.BasisZ.Z - 1.0) > 1e-6:
            return u'%s: рамка наклонена — не трогаю' % vname(view)
        mn, mx = box.Min, box.Max
        nb = DB.BoundingBoxXYZ()
        nb.Transform = t
        nb.Min = DB.XYZ(mn.X, mn.Y, z_bot - t.Origin.Z)
        nb.Max = DB.XYZ(mx.X, mx.Y, z_top - t.Origin.Z)
    else:
        ext = model_extents(view)
        if ext is None:
            return u'%s: в виде нет модельных элементов' % vname(view)
        pad = 300 * MM
        nb = DB.BoundingBoxXYZ()
        nb.Min = DB.XYZ(ext[0] - pad, ext[1] - pad, z_bot)
        nb.Max = DB.XYZ(ext[2] + pad, ext[3] + pad, z_top)
    view.IsSectionBoxActive = True
    view.SetSectionBox(nb)
    return None


LAST_MSG = [None]   # (текст, ошибка?) — показать в окне после повторного открытия


def pick_z():
    """Щелчок по грани элемента; Esc — щелчок по элементу связи. Отметка точки щелчка (футы) или None."""
    sel = uidoc.Selection
    try:
        r = sel.PickObject(ObjectType.PointOnElement, u'Подрезать 3D: щёлкните по плоскости (грань элемента). Esc — выбрать элемент в связи')
        if r is not None and r.GlobalPoint is not None:
            return r.GlobalPoint.Z
    except OperationCanceledException:
        pass
    try:
        r = sel.PickObject(ObjectType.LinkedElement, u'Подрезать 3D: щёлкните по элементу связи в нужном месте. Esc — отмена')
        if r is not None and r.GlobalPoint is not None:
            return r.GlobalPoint.Z
    except OperationCanceledException:
        pass
    return None


def level_off(z):
    """Ближайший уровень не выше z и смещение от него, мм."""
    below = [l for l in LEVELS if l.ProjectElevation <= z + 1e-6]
    l = below[-1] if below else LEVELS[0]
    return l, round((z - l.ProjectElevation) / MM)


def z_cfg(k, default_idx):
    lv = [l for l in LEVELS if vname(l) == CFG.get(k + '_lvl')]
    l = lv[0] if lv else LEVELS[default_idx]
    return l.ProjectElevation + float(CFG.get(k + '_off', 0) or 0) * MM


def do_pick(side):
    """Щелчок → отметка → рамка отмеченных видов сразу подрезается, уровень и смещение — в окно."""
    z = pick_z()
    if z is None:
        LAST_MSG[0] = (u'Плоскость не выбрана — ничего не менял.', True)
        return
    # точка лежит в мировых координатах; отметки уровней — от начала проекта
    l, off = level_off(z)
    CFG[side + '_lvl'] = vname(l)
    CFG[side + '_off'] = off
    zt, zb = z_cfg('top', len(LEVELS) - 1), z_cfg('bot', 0)
    if zt - zb < 10 * MM:
        save_cfg()
        LAST_MSG[0] = (u'Указано %s: %s %s мм — но верх получается не выше низа. Поправьте второе значение и «Применить».'
                       % (u'верх' if side == 'top' else u'низ', vname(l), fmt(off)), True)
        return
    views = [v for v in VIEWS if v.Id.IntegerValue in PRESEL]
    msgs = []
    with revit.Transaction(u'Подрезать 3D по плоскости'):
        for v in views:
            m = apply_view(v, zb, zt, bool(CFG.get('by_model', False)))
            if m:
                msgs.append(m)
    save_cfg()
    try:
        uidoc.RefreshActiveView()
    except Exception:
        pass
    LAST_MSG[0] = (u'%s по плоскости: %s %s%s мм. Подрезано видов: %d. Поправьте смещение и «Применить», если нужно.'
                   % (u'Верх' if side == 'top' else u'Низ', vname(l), u'+' if off >= 0 else u'', fmt(off), len(views) - len(msgs))
                   + (u'\n' + u'\n'.join(msgs) if msgs else u''), bool(msgs))


XAML = u'''
<Window xmlns="http://schemas.microsoft.com/winfx/2006/xaml/presentation"
        xmlns:x="http://schemas.microsoft.com/winfx/2006/xaml"
        Title="ПОДРЕЗАТЬ 3D" Width="560" Height="600" MinWidth="460" MinHeight="460"
        WindowStartupLocation="CenterScreen" FontFamily="Segoe UI" FontSize="13">
  <Window.Resources>
    <ResourceDictionary>
      <ResourceDictionary.MergedDictionaries>
        <ResourceDictionary Source="XYZ_THEME_URI"/>
      </ResourceDictionary.MergedDictionaries>
      <Style TargetType="TextBlock"><Setter Property="Foreground" Value="#7A847C"/><Setter Property="VerticalAlignment" Value="Center"/></Style>
    </ResourceDictionary>
  </Window.Resources>
  <Grid Margin="12">
    <Grid.RowDefinitions><RowDefinition Height="*"/><RowDefinition Height="Auto"/><RowDefinition Height="Auto"/><RowDefinition Height="Auto"/></Grid.RowDefinitions>
    <Grid x:Name="root" Grid.Row="0">
      <Grid.RowDefinitions><RowDefinition Height="*" MinHeight="120"/><RowDefinition Height="Auto"/></Grid.RowDefinitions>
      <GroupBox Header="3D-виды" Grid.Row="0">
        <DockPanel>
          <WrapPanel DockPanel.Dock="Top" Margin="0,0,0,6">
            <TextBox x:Name="tbFind" Width="200" ToolTip="Фильтр по имени вида"/>
            <Button x:Name="btnAll" Content="Все" Margin="6,0,0,0" Padding="10,3"/>
            <Button x:Name="btnNone" Content="Никакие" Margin="6,0,0,0" Padding="10,3"/>
          </WrapPanel>
          <ScrollViewer VerticalScrollBarVisibility="Auto"><StackPanel x:Name="spViews"/></ScrollViewer>
        </DockPanel>
      </GroupBox>
      <GroupBox Header="Секущий диапазон рамки" Grid.Row="1" Margin="0,8,0,0">
        <Grid>
          <Grid.ColumnDefinitions><ColumnDefinition Width="Auto"/><ColumnDefinition Width="*"/><ColumnDefinition Width="Auto"/><ColumnDefinition Width="90"/><ColumnDefinition Width="Auto"/></Grid.ColumnDefinitions>
          <Grid.RowDefinitions><RowDefinition/><RowDefinition/><RowDefinition/></Grid.RowDefinitions>
          <TextBlock Text="Верх:" Grid.Row="0" Margin="0,0,8,0"/>
          <ComboBox x:Name="cbTop" Grid.Row="0" Grid.Column="1" Margin="0,3"/>
          <TextBlock Text="Смещение:" Grid.Row="0" Grid.Column="2" Margin="12,0,8,0"/>
          <TextBox x:Name="tbTop" Grid.Row="0" Grid.Column="3" Margin="0,3" ToolTip="мм; ↑/↓ — ±100, PgUp/PgDn — ±500"/>
          <Button x:Name="btnPickTop" Content="⤓ Указать" Grid.Row="0" Grid.Column="4" Margin="6,3,0,3" Padding="8,2" ToolTip="Щёлкнуть по плоскости в модели — верх рамки встанет на её отметку"/>
          <TextBlock Text="Низ:" Grid.Row="1" Margin="0,0,8,0"/>
          <ComboBox x:Name="cbBot" Grid.Row="1" Grid.Column="1" Margin="0,3"/>
          <TextBlock Text="Смещение:" Grid.Row="1" Grid.Column="2" Margin="12,0,8,0"/>
          <TextBox x:Name="tbBot" Grid.Row="1" Grid.Column="3" Margin="0,3" ToolTip="мм; ↑/↓ — ±100, PgUp/PgDn — ±500"/>
          <Button x:Name="btnPickBot" Content="⤓ Указать" Grid.Row="1" Grid.Column="4" Margin="6,3,0,3" Padding="8,2" ToolTip="Щёлкнуть по плоскости в модели — низ рамки встанет на её отметку"/>
          <CheckBox x:Name="chkModel" Grid.Row="2" Grid.ColumnSpan="5" Margin="0,8,0,0"
                    Content="Границы в плане — по модели (иначе — как сейчас у рамки вида)"
                    ToolTip="Вид без рамки всегда подрезается по габариту элементов вида + 300 мм"/>
        </Grid>
      </GroupBox>
    </Grid>
    <TextBlock x:Name="tbInfo" Grid.Row="1" TextWrapping="Wrap" Margin="0,8,0,0" FontSize="11"/>
    <StackPanel Grid.Row="2" Orientation="Horizontal" HorizontalAlignment="Right" Margin="0,10,0,0">
      <Button x:Name="btnRead" Content="Считать с вида" Margin="0,0,6,0" ToolTip="Подобрать уровни и смещения по текущей рамке первого отмеченного вида"/>
      <Button x:Name="btnApply" Content="Применить" IsDefault="True" Margin="0,0,6,0"/>
      <Button x:Name="btnClose" Content="Закрыть"/>
    </StackPanel>
    <TextBlock x:Name="tbStatus" Grid.Row="3" TextWrapping="Wrap" Margin="0,8,0,0"/>
  </Grid>
</Window>
'''


class CutWindow(forms.WPFWindow):
    def __init__(self):
        forms.WPFWindow.__init__(self, XAML.replace(u'XYZ_THEME_URI', forms.theme_uri()), literal_string=True)
        forms.theme(self, u'Подрезать 3D', u'Рамка 3D-вида сверху и снизу — по уровням со смещением, как «Секущий диапазон»', merge=False)
        self.boxes = []
        self.pick_req = None
        for v in VIEWS:
            cb = CheckBox()
            box = u'' if v.IsSectionBoxActive else u'   · без рамки'
            cb.Content = vname(v) + box
            cb.Tag = v
            cb.IsChecked = v.Id.IntegerValue in PRESEL
            cb.Margin = forms_thick(0, 1, 0, 1)
            self.spViews.Children.Add(cb)
            self.boxes.append(cb)
        for cb in (self.cbTop, self.cbBot):
            for l in LEVELS:
                cb.Items.Add(lvl_text(l))
        self.set_level(self.cbTop, CFG.get('top_lvl'), len(LEVELS) - 1)
        self.set_level(self.cbBot, CFG.get('bot_lvl'), 0)
        self.tbTop.Text = fmt(float(CFG.get('top_off', 0)))
        self.tbBot.Text = fmt(float(CFG.get('bot_off', 0)))
        self.chkModel.IsChecked = bool(CFG.get('by_model', False))
        if 'top_lvl' not in CFG:
            self.read_view(quiet=True)
        self.tbFind.TextChanged += self.on_find
        self.btnAll.Click += lambda s, e: self.check_all(True)
        self.btnNone.Click += lambda s, e: self.check_all(False)
        self.btnRead.Click += self.on_read
        self.btnApply.Click += self.on_apply
        self.btnClose.Click += lambda s, e: self.Close()
        self.btnPickTop.Click += lambda s, e: self.request_pick('top')
        self.btnPickBot.Click += lambda s, e: self.request_pick('bot')
        for tb in (self.tbTop, self.tbBot):
            tb.PreviewKeyDown += self.on_num_key
            tb.TextChanged += self.on_change
        for cb in (self.cbTop, self.cbBot):
            cb.SelectionChanged += self.on_change
        # стандарт окон: размер и масштаб запоминаются, Ctrl+колесо — масштаб
        try:
            if CFG.get('w'):
                self.Width, self.Height = max(460.0, float(CFG['w'])), max(460.0, float(CFG['h']))
        except Exception:
            pass
        self.zoomk = 1.0
        self.set_zoomk(float(CFG.get('zoom', 1.0)))
        self.PreviewMouseWheel += self.on_zoom_wheel
        self.PreviewKeyDown += self.on_zoom_key
        self.Closing += self.on_closing
        self.on_change(None, None)
        if LAST_MSG[0]:
            self.status(LAST_MSG[0][0], LAST_MSG[0][1])
            LAST_MSG[0] = None

    # ------------------------------------------------------------ уровни
    def set_level(self, cb, name, default):
        idx = [i for i, l in enumerate(LEVELS) if vname(l) == name]
        cb.SelectedIndex = idx[0] if idx else max(0, default)

    def z_of(self, cb, tb):
        i = cb.SelectedIndex
        off = num(tb)
        if i < 0 or off is None:
            return None
        return LEVELS[i].ProjectElevation + off * MM

    def checked(self):
        return [cb.Tag for cb in self.boxes if cb.IsChecked]

    def read_view(self, quiet=False):
        views = [v for v in self.checked() if v.IsSectionBoxActive]
        if not views:
            if not quiet:
                self.status(u'У отмеченных видов нет рамки — считывать нечего.', True)
            return
        box = views[0].GetSectionBox()
        oz = box.Transform.Origin.Z
        for z, cb, tb in ((box.Min.Z + oz, self.cbBot, self.tbBot), (box.Max.Z + oz, self.cbTop, self.tbTop)):
            below = [i for i, l in enumerate(LEVELS) if l.ProjectElevation <= z + 1e-6]
            i = below[-1] if below else 0
            cb.SelectedIndex = i
            tb.Text = fmt((z - LEVELS[i].ProjectElevation) / MM)
        if not quiet:
            self.status(u'Считано с вида «%s».' % vname(views[0]))

    # ------------------------------------------------------------ события
    def on_find(self, sender, e):
        q = self.tbFind.Text.strip().lower()
        from System.Windows import Visibility
        for cb in self.boxes:
            cb.Visibility = Visibility.Visible if (not q or q in vname(cb.Tag).lower()) else Visibility.Collapsed

    def check_all(self, val):
        from System.Windows import Visibility
        for cb in self.boxes:
            if cb.Visibility == Visibility.Visible:
                cb.IsChecked = val

    def on_change(self, sender, e):
        zt, zb = self.z_of(self.cbTop, self.tbTop), self.z_of(self.cbBot, self.tbBot)
        if zt is None or zb is None:
            self.tbInfo.Text = u'Смещение — число в мм.'
            return
        self.tbInfo.Text = u'Рамка по высоте: от %s до %s (высота %s мм, отметки от начала проекта).' % (
            fmt(zb / MM), fmt(zt / MM), fmt((zt - zb) / MM))

    def on_read(self, sender, e):
        self.read_view()

    def on_apply(self, sender, e):
        views = self.checked()
        zt, zb = self.z_of(self.cbTop, self.tbTop), self.z_of(self.cbBot, self.tbBot)
        if not views:
            return self.status(u'Отметьте хотя бы один 3D-вид.', True)
        if zt is None or zb is None:
            return self.status(u'Смещение — число в мм.', True)
        if zt - zb < 10 * MM:
            return self.status(u'Верх должен быть выше низа.', True)
        by_model = bool(self.chkModel.IsChecked)
        msgs = []
        with revit.Transaction(u'Подрезать 3D: %s – %s' % (vname(LEVELS[self.cbBot.SelectedIndex]), vname(LEVELS[self.cbTop.SelectedIndex]))):
            for v in views:
                m = apply_view(v, zb, zt, by_model)
                if m:
                    msgs.append(m)
        CFG.update(top_lvl=vname(LEVELS[self.cbTop.SelectedIndex]), bot_lvl=vname(LEVELS[self.cbBot.SelectedIndex]),
                   top_off=num(self.tbTop), bot_off=num(self.tbBot), by_model=by_model)
        save_cfg()
        for cb in self.boxes:
            cb.Content = vname(cb.Tag) + (u'' if cb.Tag.IsSectionBoxActive else u'   · без рамки')
        done = len(views) - len(msgs)
        self.status(u'Подрезано видов: %d. Отмена — Ctrl+Z в Revit.' % done + (u'\n' + u'\n'.join(msgs) if msgs else u''), bool(msgs))
        try:
            uidoc.RefreshActiveView()
        except Exception:
            pass

    def request_pick(self, side):
        """Запомнить состояние окна и закрыть его: щелчок в модели — в main()."""
        PRESEL.clear()
        PRESEL.update(cb.Tag.Id.IntegerValue for cb in self.boxes if cb.IsChecked)
        if not PRESEL:
            return self.status(u'Отметьте хотя бы один 3D-вид.', True)
        for cb, tb, k in ((self.cbTop, self.tbTop, 'top'), (self.cbBot, self.tbBot, 'bot')):
            if cb.SelectedIndex >= 0:
                CFG[k + '_lvl'] = vname(LEVELS[cb.SelectedIndex])
            if num(tb) is not None:
                CFG[k + '_off'] = num(tb)
        CFG['by_model'] = bool(self.chkModel.IsChecked)
        self.pick_req = side
        self.Close()

    def status(self, text, bad=False):
        self.tbStatus.Foreground = SolidColorBrush(Color.FromRgb(198, 40, 40) if bad else Color.FromRgb(46, 125, 50))
        self.tbStatus.Text = text

    def on_num_key(self, sender, e):
        step = {Key.Up: 100, Key.Down: -100, Key.PageUp: 500, Key.Next: -500}.get(e.Key)
        if step is None or int(Keyboard.Modifiers) != 0:
            return
        val = num(sender)
        if val is None:
            return
        sender.Text = fmt(val + step)
        sender.CaretIndex = len(sender.Text)
        e.Handled = True

    def set_zoomk(self, z):
        self.zoomk = round(max(0.6, min(1.6, z)), 2)
        self.root.LayoutTransform = ScaleTransform(self.zoomk, self.zoomk)
        CFG['zoom'] = self.zoomk

    def on_zoom_wheel(self, sender, e):
        if Keyboard.Modifiers & ModifierKeys.Control == ModifierKeys.Control:
            self.set_zoomk(self.zoomk + (0.05 if e.Delta > 0 else -0.05))
            e.Handled = True

    def on_zoom_key(self, sender, e):
        if Keyboard.Modifiers & ModifierKeys.Control == ModifierKeys.Control and e.Key in (Key.D0, Key.NumPad0):
            self.set_zoomk(1.0)
            e.Handled = True

    def on_closing(self, sender, e):
        try:
            CFG['w'], CFG['h'] = self.ActualWidth, self.ActualHeight
        except Exception:
            pass
        save_cfg()


def forms_thick(l, t, r, b):
    from System.Windows import Thickness
    return Thickness(l, t, r, b)


for _n in ('on_find', 'on_change', 'on_read', 'on_apply', 'on_num_key', 'check_all', 'request_pick'):
    setattr(CutWindow, _n, guarded(getattr(CutWindow, _n)))


def main():
    if not LEVELS:
        forms.alert(u'В проекте нет уровней.', exitscript=True)
    if not VIEWS:
        forms.alert(u'В проекте нет 3D-видов.', exitscript=True)
    while True:
        w = CutWindow()
        w.ShowDialog()
        if not w.pick_req:
            break
        try:
            do_pick(w.pick_req)
        except Exception:
            import traceback
            LAST_MSG[0] = (u'Ошибка при выборе плоскости:\n' + traceback.format_exc()[-800:], True)


main()
