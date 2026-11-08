# -*- coding: utf-8 -*-
__title__ = u"Объёмы"
__author__ = u"db"
__doc__ = u"""Объёмы пространств и раскраска — цвет фильтрами вида.

1) Пространства: выделенные / на активном виде / все.
2) Объёмы: создать или обновить (форма + значения параметров пространства), удалить свои, удалить сторонние объёмы
   вместе с частями. Перед каждым действием — проба со списком и «Да/Нет».
3) Раскраска активного вида: параметр → значения с цветами (щелчок по цвету — сменить), прозрачность, «Покрасить».
Отмена любого действия — Ctrl+Z. Код: lib/xyz_vol.py."""

import sys
import clr
clr.AddReference('System.Windows.Forms')
clr.AddReference('System.Drawing')
import System
from System.Windows.Forms import ColorDialog, DialogResult
from pyrevit import revit, DB
import xyz_forms as forms
sys.modules.pop('xyz_vol', None)
import xyz_vol as v

import System.Windows.Input
from System.Windows import (Thickness, Visibility, HorizontalAlignment, VerticalAlignment, FontWeights, TextWrapping,
                            ResizeMode, SizeToContent)
from System.Windows.Controls import (StackPanel, WrapPanel, TextBlock, CheckBox, RadioButton, ComboBox, ComboBoxItem, TextBox,
                                     Button, Border, ScrollViewer, ScrollBarVisibility, Orientation, Slider, Grid,
                                     ColumnDefinition)
from System.Windows import GridLength, GridUnitType

doc = revit.doc
uidoc = revit.uidoc
view = doc.ActiveView
SEL = list(uidoc.Selection.GetElementIds())
B = forms._brush

try:
    import xyz_settings
    CFG = dict(xyz_settings.get('vol') or {})
except Exception:
    xyz_settings = None
    CFG = {}
COLORS = dict(CFG.get('colors') or {})
DESC = dict(CFG.get('desc') or {})   # {параметр: {значение: расшифровка}} — для легенды
DMODE = dict(CFG.get('desc_mode') or {})   # {параметр: {значение: 'add' | 'replace'}} — как текст строки идёт в подпись


def save_cfg():
    if xyz_settings is None:
        return
    CFG['colors'] = COLORS
    CFG['desc'] = DESC
    try:
        CFG['wheel_by'] = WHEEL
    except NameError:
        pass
    try:
        CFG['palette_by'] = PALBY
    except NameError:
        pass
    try:
        CFG['frames'] = [x['name'] for x, c in W['frames'] if c.IsChecked]
    except Exception:
        pass
    CFG['desc_mode'] = DMODE
    try:
        if FOOT_OF[0] is not None:
            FOOTBY[FOOT_OF[0]] = FOOT
        CFG['foot_by'] = FOOTBY
    except NameError:
        pass
    try:
        CFG['uniq_with'] = UW
    except NameError:
        pass
    try:
        BYP[PARTS_OF[0]] = [dict(x) for x in PARTS]
        CFG['label_parts_by'] = BYP
    except NameError:
        pass
    try:
        xyz_settings.set('vol', CFG)
    except Exception:
        pass


def txt(t, bold=False, muted=False, size=None, margin=None):
    tb = TextBlock()
    tb.Text = t
    tb.TextWrapping = TextWrapping.Wrap
    if bold:
        tb.FontWeight = FontWeights.SemiBold
        tb.Foreground = B(forms.GREEN)
    if muted:
        tb.Foreground = B(forms.MUTE)
    if size:
        tb.FontSize = size
    tb.Margin = margin or Thickness(0, 0, 0, 4)
    return tb


def btn(t, handler, tip=None, margin=None):
    b = Button()
    b.Content = t
    b.Padding = Thickness(10, 3, 10, 3)
    b.Margin = margin or Thickness(0, 0, 8, 0)
    if tip:
        b.ToolTip = tip
    b.Click += handler
    return b


def hpanel(m=None):
    sp = StackPanel()
    sp.Orientation = Orientation.Horizontal
    sp.Margin = m or Thickness(0, 2, 0, 6)
    return sp


def section(title):
    bd = Border()
    bd.BorderBrush = B(forms.LINE)
    bd.BorderThickness = Thickness(1)
    bd.Background = B('#FFFFFF')
    bd.Padding = Thickness(10, 8, 10, 8)
    bd.Margin = Thickness(0, 0, 0, 10)
    sp = StackPanel()
    sp.Children.Add(txt(title, bold=True))
    bd.Child = sp
    return bd, sp


dlg = forms._Dialog(u'Объёмы', width=860)
dlg.ResizeMode = ResizeMode.CanResize
dlg._s.Text = u'вид «%s» · цвет — только фильтрами вида, отмена — Ctrl+Z' % view.Name
dlg._s.Visibility = Visibility.Visible
root = StackPanel()
sv = ScrollViewer()
sv.VerticalScrollBarVisibility = ScrollBarVisibility.Auto
sv.Content = root
sv.MaxHeight = 680
dlg.body.Children.Add(sv)
W = {'vals': [], 'counts': {}}


def guarded(fn):
    """Ошибка в обработчике кнопки — окном с текстом, а не молча (db 21.10: «нажимаю — ничего»)."""
    def wrap(s, e):
        try:
            return fn(s, e)
        except Exception:
            import traceback
            forms.alert(u'Ошибка — действие не выполнено, модель не менялась:\n\n' + traceback.format_exc()[-1500:],
                        title=u'Объёмы')
    return wrap


def num_box(slider, hidden_at=None):
    """Поле ввода числа рядом с ползунком (db 21.10: «проваливаться и забивать с клавиатуры»):
    щёлкнуть, набрать 0…100, Enter / Tab / уйти из поля — ползунок встаёт; ↑/↓ — по 1, PgUp/PgDn — по 5."""
    from System.Windows.Input import Key
    box = TextBox()
    box.MinWidth = 0   # стиль XYZ даёт полям большую мин. ширину — здесь 3 цифры
    box.Width = 38
    box.MaxWidth = 38
    box.Padding = Thickness(2, 0, 2, 0)
    box.HorizontalAlignment = HorizontalAlignment.Left
    box.VerticalAlignment = VerticalAlignment.Center
    box.Margin = Thickness(6, 1, 0, 1)
    box.HorizontalContentAlignment = HorizontalAlignment.Right
    box.ToolTip = u'Наберите число 0–100 и Enter; ↑/↓ — по 1 %, PgUp/PgDn — по 5 %' + (
        u'; 100 — скрыть' if hidden_at else u'')
    unit = txt(u'%', margin=Thickness(3, 3, 0, 0))
    busy = [False]

    def show(*a):
        if busy[0]:
            return
        busy[0] = True
        box.Text = u'%d' % int(round(slider.Value))
        unit.Text = u'%  (скрыты)' if (hidden_at and slider.Value >= hidden_at) else u'%'
        busy[0] = False

    def commit(*a):
        t = (box.Text or u'').replace(u'%', u'').replace(u',', u'.').strip()
        try:
            slider.Value = max(slider.Minimum, min(slider.Maximum, round(float(t))))
        except Exception:
            pass
        show()

    def key(s_, e_):
        step = {Key.Up: 1, Key.Down: -1, Key.PageUp: 5, Key.PageDown: -5}.get(e_.Key)
        if e_.Key in (Key.Enter, Key.Return):
            commit()
            box.SelectAll()
            e_.Handled = True
        elif step:
            commit()
            slider.Value = max(slider.Minimum, min(slider.Maximum, slider.Value + step))
            box.SelectAll()
            e_.Handled = True

    box.PreviewKeyDown += key
    box.LostFocus += commit
    box.GotKeyboardFocus += lambda s_, e_: box.SelectAll()
    slider.ValueChanged += show
    show()
    sp = hpanel(Thickness(0))
    sp.VerticalAlignment = VerticalAlignment.Center
    sp.Children.Add(box)
    sp.Children.Add(unit)
    return sp


def status(t, ok=True):
    W['status'].Text = t
    W['status'].Foreground = B(forms.GREEN if ok else forms.RED)
    if not ok:   # db 21.10: строка состояния бывает не видна — ошибку показываем окном
        forms.alert(t, title=u'Объёмы')


# ---------------------------------------------------------------- 1. пространства
b1, s1 = section(u'1. Пространства')
r_sel = RadioButton()
r_sel.Content = u'Выделенные (%d эл. выделено)' % len(SEL)
r_sel.IsEnabled = bool(SEL)
r_view = RadioButton()
r_view.Content = u'На активном виде'
r_all = RadioButton()
r_all.Content = u'Все в модели'
(r_sel if SEL else r_all).IsChecked = True
p1 = hpanel()
for r in (r_sel, r_view, r_all):
    r.Margin = Thickness(0, 0, 16, 0)
    p1.Children.Add(r)
s1.Children.Add(p1)
# рамки (области видимости): только пространства, центр которых внутри отмеченных (db 21.10)
import xyz_qty as _q
FRS = _q.frames(doc)
W['frames'] = []
if FRS:
    s1.Children.Add(txt(u'Здание — по областям видимости (не отмечено ни одной — все пространства):', muted=True, size=12,
                        margin=Thickness(0, 6, 0, 2)))
    fw = WrapPanel()
    saved_fr = CFG.get('frames')
    for f_ in FRS:
        cb_ = CheckBox()
        cb_.Content = f_['name']
        cb_.IsChecked = (f_['name'] in saved_fr) if saved_fr is not None else False
        cb_.Margin = Thickness(0, 2, 16, 2)
        cb_.Click += lambda s_, e_: (CFG.__setitem__('frames', [x['name'] for x, c in W['frames'] if c.IsChecked]),
                                     fill_values())
        fw.Children.Add(cb_)
        W['frames'].append((f_, cb_))
    s1.Children.Add(fw)
root.Children.Add(b1)


def in_frames(sps):
    ch = [f_ for f_, c in W['frames'] if c.IsChecked]
    if not ch:
        return sps
    return [sp for sp in sps if _q.frame_of(sp, ch) is not None]


def scope_all():
    """Все пространства модели в отмеченных рамках — для списка значений, количества и сумм."""
    return in_frames(v.spaces(doc, 'model'))


def get_spaces():
    sc = 'selection' if r_sel.IsChecked else ('view' if r_view.IsChecked else 'model')
    sps = in_frames(v.spaces(doc, sc, view, SEL))
    if sc == 'view' and not sps and view.ViewType == DB.ViewType.ThreeD:
        status(u'На 3D-виде Revit не показывает пространства, поэтому «На активном виде» их не находит. '
               u'Выберите «Все в модели» (раздел 1 вверху окна).', False)
    return sps


# ---------------------------------------------------------------- 2. объёмы
b2, s2 = section(u'2. Объёмы')
ALLSP = v.spaces(doc, 'model')
PNAMES = v.string_params(doc, ALLSP)
s2.Children.Add(txt(u'Какие параметры пространства переносить в объём (по ним потом красим). Параметр, не привязанный к '
                    u'«Обобщённым моделям», привяжется — это покажет проба.', muted=True, size=12))
wp = WrapPanel()
W['params'] = []
chosen = set(CFG.get('params') or v.DEF_PARAMS)
BND = v.bindings(doc)
for n in PNAMES:
    if n not in BND:
        continue   # встроенные (Имя, Номер …) в объём не переносятся
    cb = CheckBox()
    cb.Content = n
    cb.IsChecked = n in chosen
    cb.Margin = Thickness(0, 2, 14, 2)
    wp.Children.Add(cb)
    W['params'].append((n, cb))
pv = ScrollViewer()
pv.MaxHeight = 120
pv.VerticalScrollBarVisibility = ScrollBarVisibility.Auto
pv.Content = wp
s2.Children.Add(pv)


def sel_params():
    return [n for n, cb in W['params'] if cb.IsChecked]


def ask(text):
    return forms.alert(text, title=u'Объёмы — проба', yes=True, no=True)


@guarded
def do_build(s, e):
    sps = get_spaces()
    params = sel_params()
    if not sps:
        if not (r_view.IsChecked and view.ViewType == DB.ViewType.ThreeD):
            status(u'Нет пространств в выбранной области.', False)
        return
    new, upd, bad = v.plan(doc, sps)
    nb = [n for n in params if not v.bound_to_gm(doc, n, BND)]
    msg = (u'Пространств: %d\n• создать объёмов: %d\n• обновить (форма и значения): %d\n• без геометрии (пропуск): %d\n'
           u'Параметры в объём: %s\n' % (len(sps), len(new), len(upd), len(bad), u', '.join(params) or u'—'))
    if nb:
        msg += u'\nПРИВЯЗАТЬ к «Обобщённым моделям» (изменение привязки параметров):\n• ' + u'\n• '.join(nb) + u'\n'
    if bad:
        msg += u'\nБез геометрии: ' + u', '.join(v.space_label(x) for x in bad[:10]) + (u' …' if len(bad) > 10 else u'')
    if not ask(msg + u'\n\nВыполнить?'):
        return
    with revit.Transaction(u'XYZ: объёмы — создать/обновить'):
        done = v.bind_gm(doc, nb) if nb else []
        nc, nu, nb2, nv = v.build(doc, sps, params, v.MP_WORKSET)
    CFG['params'] = params
    save_cfg()
    refresh_params()   # привязанные сейчас параметры — сразу в список раскраски
    status(u'Создано %d, обновлено %d (сложных форм — сеткой: %d), без геометрии %d; значений %d; привязано '
           u'параметров %d. Отмена — Ctrl+Z.' % (nc, nu, v.LAST.get('mesh', 0), nb2, nv, len(done)))
    fill_values()


@guarded
def do_del_our(s, e):
    vols = v.our_volumes(doc)
    keys = set(sp.UniqueId for sp in get_spaces())
    alive = set(sp.UniqueId for sp in ALLSP)
    # «Все в модели» — ещё и объёмы, чьё пространство удалено
    ids = [ds.Id for k, ds in vols.items() if k in keys or (r_all.IsChecked and k not in alive)]
    if not ids:
        status(u'Своих объёмов для выбранных пространств нет.', False)
        return
    if not ask(u'Удалить объёмы XYZ: %d шт. (для выбранных пространств; сами пространства не трогаются).\n\nУдалить?'
               % len(ids)):
        return
    with revit.Transaction(u'XYZ: объёмы — удалить'):
        n = v.delete(doc, ids)
    status(u'Удалено объёмов: %d. Отмена — Ctrl+Z.' % n)
    fill_values()


@guarded
def do_del_outside(s, e):
    ch = [f_ for f_, c in W['frames'] if c.IsChecked]
    if not ch:
        status(u'Отметьте рамки в разделе 1 — удалятся объёмы пространств вне них.', False)
        return
    keep = set(sp.UniqueId for sp in scope_all())
    ids = [ds.Id for k, ds in v.our_volumes(doc).items() if k not in keep]
    if not ids:
        status(u'Объёмов вне отмеченных рамок нет.')
        return
    if not ask(u'Удалить объёмы XYZ вне рамок «%s»: %d шт. (пространства не трогаются).\n\nУдалить?'
               % (u', '.join(f_['name'] for f_ in ch), len(ids))):
        return
    with revit.Transaction(u'XYZ: объёмы — удалить вне рамок'):
        n = v.delete(doc, ids)
    status(u'Удалено объёмов вне рамок: %d. Отмена — Ctrl+Z.' % n)
    fill_values()


@guarded
def do_del_mp(s, e):
    ds, parts = v.modplus_volumes(doc)
    if not ds and not parts:
        status(u'Сторонних объёмов (рабочий набор «%s») нет.' % v.MP_WORKSET, False)
        return
    if not ask(u'Удалить сторонние объёмы «Объём помещений»:\n• частей: %d\n• исходных объёмов (DirectShape в наборе «%s»): %d\n'
               u'\nСами пространства не трогаются. Удалить?' % (len(parts), v.MP_WORKSET, len(ds))):
        return
    with revit.Transaction(u'XYZ: сторонние объёмы — удалить'):
        n1 = v.delete(doc, parts)
        n2 = v.delete(doc, ds)
    status(u'Удалено частей %d, сторонних объёмов %d. Отмена — Ctrl+Z.' % (n1, n2))


p2 = WrapPanel()
p2.Margin = Thickness(0, 8, 0, 0)
p2.Children.Add(btn(u'Создать / обновить', do_build, u'Объём на каждое выбранное пространство; есть — обновить'))
p2.Children.Add(btn(u'Удалить объёмы XYZ', do_del_our, u'Только объёмы этой кнопки для выбранных пространств'))
p2.Children.Add(btn(u'Удалить вне рамок', do_del_outside, u'Объёмы XYZ пространств вне отмеченных рамок (другие здания)'))
mp_ds, mp_parts = v.modplus_volumes(doc)
bm = btn(u'Удалить сторонние объёмы (%d + частей %d)' % (len(mp_ds), len(mp_parts)), do_del_mp)
bm.IsEnabled = bool(mp_ds or mp_parts)
p2.Children.Add(bm)
s2.Children.Add(p2)
root.Children.Add(b2)

# ---------------------------------------------------------------- 3. раскраска
b3, s3 = section(u'3. Раскраска вида «%s» (фильтрами)' % view.Name)
p3 = WrapPanel()
p3.Margin = Thickness(0, 2, 0, 6)
p3.Children.Add(txt(u'Параметр:', margin=Thickness(0, 3, 6, 0)))
pc = ComboBox()
pc.Width = 340
p3.Children.Add(pc)
p3.Children.Add(txt(u'   Прозрачность:', margin=Thickness(0, 3, 6, 0)))
sl = Slider()
sl.Minimum = 0
sl.Maximum = 100
sl.Width = 140
sl.Value = float(CFG.get('transp', 0))
sl.IsSnapToTickEnabled = True
sl.TickFrequency = 5
p3.Children.Add(sl)
sl.IsSnapToTickEnabled = False
sl.SmallChange = 1
p3.Children.Add(num_box(sl))
# бесцветные объёмы (значение пустое): прозрачность с шагом 1 %, 100 % — скрыть
p3.Children.Add(txt(u'   Бесцветные:', margin=Thickness(0, 3, 6, 0)))
sl0 = Slider()
sl0.Minimum = 0
sl0.Maximum = 100
sl0.Width = 200
sl0.SmallChange = 1
sl0.LargeChange = 5
sl0.IsSnapToTickEnabled = True
sl0.TickFrequency = 1
sl0.Value = float(CFG.get('transp_empty', 70))
sl0.ToolTip = (u'Прозрачность объёмов без значения: 0 — непрозрачные, 99 — едва видны, 100 — скрыты. '
               u'Колесо мыши / стрелки — по 1 %')
p3.Children.Add(sl0)




def _wheel0(s_, e_):
    sl0.Value = max(0, min(100, sl0.Value + (1 if e_.Delta > 0 else -1)))
    e_.Handled = True


sl0.PreviewMouseWheel += _wheel0
p3.Children.Add(num_box(sl0, hidden_at=100))
p3c = WrapPanel()
p3c.Margin = Thickness(0, 0, 0, 6)
# с какими схемами не повторять цвета (db 21.10): список других параметров, у которых уже есть цвета
UW = dict(CFG.get('uniq_with') or {})   # {параметр: [параметры, с которыми не повторять]}


def others(par):
    return sorted(p_ for p_, d_ in COLORS.items() if p_ != par and d_)


def avoid_list(par):
    if par not in UW:
        UW[par] = others(par)   # по умолчанию — со всеми
    return [p_ for p_ in UW[par] if p_ in COLORS]


def avoid_set(par):
    return set(hx for p_ in avoid_list(par) for hx in COLORS.get(p_, {}).values())


uniq = Button()
uniq.Padding = Thickness(10, 3, 10, 3)
uniq.Margin = Thickness(0, 0, 8, 0)
uniq.ToolTip = u'Отметьте схемы (параметры), чьи цвета не должны повторяться в этой'


def uniq_text():
    par = cur_param()
    lst = avoid_list(par) if par else []
    if not lst:
        uniq.Content = u'Не повторять цвета: ни с какой схемой ▾'
    elif len(lst) == 1:
        uniq.Content = u'Не повторять цвета: %s ▾' % lst[0].replace(u'ADSK_', u'')
    else:
        uniq.Content = u'Не повторять цвета: %d схем ▾' % len(lst)


def uniq_menu(s_, e_):
    par = cur_param()
    if not par:
        return
    cm = System.Windows.Controls.ContextMenu()
    cur = set(avoid_list(par))
    oth = others(par)
    if not oth:
        mi = System.Windows.Controls.MenuItem()
        mi.Header = u'Других схем с цветами пока нет'
        mi.IsEnabled = False
        cm.Items.Add(mi)
    for p_ in oth:
        mi = System.Windows.Controls.MenuItem()
        mi.Header = u'%s  (%d цв.)' % (p_, len(COLORS.get(p_, {})))
        mi.IsCheckable = True
        mi.StaysOpenOnClick = True
        mi.IsChecked = p_ in cur

        def on_c(s2, e2, p_=p_, mi=mi):
            lst = set(avoid_list(par))
            if mi.IsChecked:
                lst.add(p_)
            else:
                lst.discard(p_)
            UW[par] = sorted(lst)
            uniq_text()
        mi.Click += on_c
        cm.Items.Add(mi)
    cm.PlacementTarget = uniq
    cm.IsOpen = True


uniq.Click += uniq_menu
p3c.Children.Add(uniq)


@guarded
def recolor(s_, e_):
    par = cur_param()
    if not par:
        return
    vals = [val for val, sw in W['vals']]
    lst = avoid_list(par)
    w_ = wheel_of(par)
    if w_:
        # цветовой круг: та же схема и тон, базовый оттенок повёрнут на случайный угол — гармония сохраняется
        import random, colorsys
        r, g, b = v.hexrgb(w_['base'])
        h, s_, vv = colorsys.rgb_to_hsv(r / 255.0, g / 255.0, b / 255.0)
        h = (h + random.uniform(0.15, 0.85)) % 1.0
        rr, gg, bb = colorsys.hsv_to_rgb(h, s_, vv)
        w_['base'] = u'#%02X%02X%02X' % (int(rr * 255), int(gg * 255), int(bb * 255))
        sync_pal()
        repaint_scheme(u'Схема повёрнута по кругу, новый базовый цвет %s.' % w_['base'])
        return
    # db 21.10: «ожидаю изменение всех цветов» — новые не совпадают с текущими этой схемы, палитра перемешана
    used = avoid_set(par) | set(COLORS.get(par, {}).values())
    COLORS[par] = dict(zip(vals, gen(used, len(vals), shuffle=True, par=par)))
    CFG['uniq_with'] = UW
    fill_values()
    status(u'Цвета «%s» подобраны заново%s. На виде — после «Покрасить вид».' % (
        par, (u' без повторов с: ' + u', '.join(lst)) if lst else u''))


p3c.Children.Add(btn(u'Подобрать цвета заново', recolor, u'Все цвета этого параметра заменить новыми из выбранной палитры '
                                                      u'(ручные тоже); каждое нажатие — новое сочетание'))
PALBY = dict(CFG.get('palette_by') or {})
WHEEL = dict(CFG.get('wheel_by') or {})   # {параметр: {'scheme', 'tone', 'base'}} — режим «Цветовой круг»
WHEEL_TAG = u'#круг'


def pal_name(par):
    return PALBY.get(par) or v.DEFAULT_PALETTE


def wheel_of(par):
    return WHEEL.setdefault(par, {'scheme': 'triad', 'tone': 'vivid', 'base': '#2A9D8F'}) \
        if pal_name(par) == WHEEL_TAG else None


def gen(used, n, shuffle=False, par=None):
    """Цвета по выбору для параметра: готовая палитра или схема цветового круга."""
    par = par or cur_param()
    return v.free_colors(used, n, shuffle=shuffle, palette=pal_name(par), wheel=wheel_of(par))


p3c.Children.Add(txt(u'Палитра:', margin=Thickness(8, 4, 6, 0)))
palc = ComboBox()
palc.Width = 170


def pal_item(tag, label, cols):
    ci_ = ComboBoxItem()
    ci_.Tag = tag
    sp_ = hpanel(Thickness(0))
    for hx_ in cols[:6]:
        bx = Border()
        bx.Width = 10
        bx.Height = 12
        bx.Background = B(hx_)
        sp_.Children.Add(bx)
    sp_.Children.Add(txt(u'  ' + label, margin=Thickness(0)))
    ci_.Content = sp_
    palc.Items.Add(ci_)


for n_ in v.PALETTE_NAMES:
    pal_item(n_, n_, dict(v.PALETTES)[n_])
pal_item(WHEEL_TAG, u'Цветовой круг…', v.wheel_colors('#2A9D8F', 'triad', 'vivid'))
palc.ToolTip = (u'Готовые наборы в духе coolors.co или «Цветовой круг» — схема от базового цвета (триада, тетрада, '
                u'аналогия…). Выбор сразу перекрашивает значения этого параметра')
p3c.Children.Add(palc)
PALSYNC = [False]

# строка «Цветовой круг»: схема, тон, базовый цвет (как colorscheme.ru)
p3w = WrapPanel()
p3w.Margin = Thickness(0, 0, 0, 6)
p3w.Children.Add(txt(u'Схема:', margin=Thickness(0, 4, 6, 0)))
schc = ComboBox()
schc.Width = 290
for k_, n_, a_ in v.SCHEMES:
    ci_ = ComboBoxItem()
    ci_.Tag = k_
    ci_.Content = n_
    schc.Items.Add(ci_)
p3w.Children.Add(schc)
p3w.Children.Add(txt(u'  Тон:', margin=Thickness(0, 4, 6, 0)))
tonc = ComboBox()
tonc.Width = 130
for k_, n_, s_, b_ in v.TONES:
    ci_ = ComboBoxItem()
    ci_.Tag = k_
    ci_.Content = n_
    tonc.Items.Add(ci_)
p3w.Children.Add(tonc)
p3w.Children.Add(txt(u'  База:', margin=Thickness(0, 4, 6, 0)))
basesw = Border()
basesw.Width = 30
basesw.Height = 18
basesw.CornerRadius = System.Windows.CornerRadius(3)
basesw.BorderBrush = B('#202020')
basesw.BorderThickness = Thickness(1)
basesw.Cursor = System.Windows.Input.Cursors.Hand
basesw.ToolTip = u'Базовый цвет схемы — щёлкните, чтобы выбрать. От него по кругу строятся остальные'
basesw.VerticalAlignment = VerticalAlignment.Center
p3w.Children.Add(basesw)
p3w.Children.Add(txt(u'   Варианты светлоты каждого оттенка добавляются, если значений больше, чем оттенков в схеме.',
                     muted=True, size=11, margin=Thickness(8, 4, 0, 0)))


def sync_pal():
    PALSYNC[0] = True
    par = cur_param()
    for ci_ in palc.Items:
        if ci_.Tag == pal_name(par):
            palc.SelectedItem = ci_
    w_ = wheel_of(par)
    p3w.Visibility = Visibility.Visible if w_ else Visibility.Collapsed
    if w_:
        for ci_ in schc.Items:
            if ci_.Tag == w_['scheme']:
                schc.SelectedItem = ci_
        for ci_ in tonc.Items:
            if ci_.Tag == w_['tone']:
                tonc.SelectedItem = ci_
        basesw.Background = B(w_['base'])
    PALSYNC[0] = False


def repaint_scheme(note):
    par = cur_param()
    vals = [val for val, sw in W['vals']]
    COLORS[par] = dict(zip(vals, gen(avoid_set(par), len(vals), par=par)))
    CFG['palette_by'] = PALBY
    CFG['wheel_by'] = WHEEL
    fill_values()
    status(note + u' На виде — после «Покрасить вид».')


@guarded
def on_pal(s_, e_):
    if PALSYNC[0] or palc.SelectedItem is None:
        return
    par = cur_param()
    if not par:
        return
    PALBY[par] = palc.SelectedItem.Tag
    sync_pal()
    repaint_scheme(u'Палитра «%s» для «%s».' % (u'Цветовой круг' if PALBY[par] == WHEEL_TAG else PALBY[par], par))


@guarded
def on_wheel(s_, e_):
    if PALSYNC[0]:
        return
    par = cur_param()
    w_ = wheel_of(par)
    if not w_:
        return
    if schc.SelectedItem is not None:
        w_['scheme'] = schc.SelectedItem.Tag
    if tonc.SelectedItem is not None:
        w_['tone'] = tonc.SelectedItem.Tag
    repaint_scheme(u'Схема: %s, тон: %s.' % (schc.SelectedItem.Content if schc.SelectedItem else u'',
                                            tonc.SelectedItem.Content if tonc.SelectedItem else u''))


@guarded
def on_base(s_, e_):
    par = cur_param()
    w_ = wheel_of(par)
    if not w_:
        return
    d = ColorDialog()
    d.FullOpen = True
    r, g, b = v.hexrgb(w_['base'])
    d.Color = System.Drawing.Color.FromArgb(r, g, b)
    if d.ShowDialog() == DialogResult.OK:
        w_['base'] = u'#%02X%02X%02X' % (d.Color.R, d.Color.G, d.Color.B)
        basesw.Background = B(w_['base'])
        repaint_scheme(u'Базовый цвет %s.' % w_['base'])


palc.SelectionChanged += on_pal
schc.SelectionChanged += on_wheel
tonc.SelectionChanged += on_wheel
basesw.MouseLeftButtonUp += on_base
s3.Children.Add(p3)
s3.Children.Add(p3c)
s3.Children.Add(p3w)
# ---- подпись в легенде: поля с префиксом и суффиксом, как в редакторе меток Revit
NUMP = v.number_params(doc, ALLSP)
FIELDS = [('value', u'Значение параметра'), ('desc', u'Расшифровка (ввод справа)'), ('count', u'Количество пространств')] + \
    [('sum:' + n, u'Сумма: ' + n) for n in NUMP]
# свой набор полей подписи у каждого параметра (db 21.10); старый общий — как основа
BYP = dict(CFG.get('label_parts_by') or {})
PARTS = [dict(x) for x in (CFG.get('label_parts') or v.DEFAULT_PARTS)]
PARTS_OF = [None]   # для какого параметра сейчас PARTS


def switch_parts(par):
    if PARTS_OF[0] is not None:
        BYP[PARTS_OF[0]] = [dict(x) for x in PARTS]
    del PARTS[:]
    PARTS.extend(dict(x) for x in (BYP.get(par) or CFG.get('label_parts') or v.DEFAULT_PARTS))
    PARTS_OF[0] = par
    build_parts()
    switch_foot(par)
SUMS = {}
lab_box = StackPanel()
lab_box.Margin = Thickness(0, 2, 0, 6)
s3.Children.Add(txt(u'Подпись в легенде — поля по порядку; пустое поле выпадает вместе со своим префиксом и суффиксом '
                    u'(как в редакторе меток). Пробелы в префиксе/суффиксе учитываются.', muted=True, size=12))
s3.Children.Add(lab_box)


def ctx_for(val):
    par = cur_param()
    c = {'value': val, 'desc': DESC.get(par, {}).get(val, u''), 'count': u'%d' % W['counts'].get(val, 0)}
    for pt in PARTS:
        f = pt.get('field') or u''
        if f.startswith('sum:'):
            ck = (par, f[4:])
            if ck not in SUMS:
                SUMS[ck] = v.sums(doc, par, f[4:], scope_all())
            c[f] = SUMS[ck].get(val, u'')
    return c


def final_label(val):
    """Подпись строки: поля + текст справа по режиму строки (дополнить / заменить)."""
    par = cur_param()
    extra = (DESC.get(par, {}).get(val, u'') or u'').strip()
    mode = DMODE.get(par, {}).get(val, 'add')
    if extra and mode == 'replace':
        return extra
    has_desc = any(p_.get('field') == 'desc' for p_ in PARTS)
    base = v.compose(PARTS, ctx_for(val))
    if extra and not has_desc:
        return (base + u' ' + extra).strip()
    return base


def preview(*a):
    for val, tb in (W.get('prev') or {}).items():
        tb.Text = final_label(val)


def parts_editor(box, parts, fields, defaults, onchg, reset_tip=None):
    """Поля с префиксом и суффиксом, как в редакторе меток Revit (подпись строк и счётчик итога)."""
    rebuild = lambda: parts_editor(box, parts, fields, defaults, onchg, reset_tip)
    box.Children.Clear()
    hdr = Grid()
    for w_ in (230, 110, 110, 90):
        cd = ColumnDefinition()
        cd.Width = GridLength(w_)
        hdr.ColumnDefinitions.Add(cd)
    for k_, t_ in enumerate((u'Поле', u'Префикс', u'Суффикс', u'')):
        h_ = txt(t_, muted=True, size=11, margin=Thickness(0))
        Grid.SetColumn(h_, k_)
        hdr.Children.Add(h_)
    box.Children.Add(hdr)
    for idx, pt in enumerate(parts):
        g = Grid()
        g.Margin = Thickness(0, 1, 0, 1)
        for w_ in (230, 110, 110, 90):
            cd = ColumnDefinition()
            cd.Width = GridLength(w_)
            g.ColumnDefinitions.Add(cd)
        cb = ComboBox()
        cb.Margin = Thickness(0, 0, 6, 0)
        for k_, n_ in fields:
            ci_ = ComboBoxItem()
            ci_.Content = n_
            ci_.Tag = k_
            cb.Items.Add(ci_)
            if k_ == pt.get('field'):
                cb.SelectedItem = ci_

        def on_f(s, e, pt=pt, cb=cb):
            if cb.SelectedItem is not None:
                pt['field'] = cb.SelectedItem.Tag
                onchg()
        cb.SelectionChanged += on_f
        Grid.SetColumn(cb, 0)
        g.Children.Add(cb)
        for col, key in ((1, 'prefix'), (2, 'suffix')):
            tb = TextBox()
            tb.Margin = Thickness(0, 0, 6, 0)
            tb.FontFamily = System.Windows.Media.FontFamily(u'Consolas')
            tb.Text = pt.get(key) or u''

            def on_t(s, e, pt=pt, key=key, tb=tb):
                pt[key] = tb.Text or u''
                onchg()
            tb.TextChanged += on_t
            Grid.SetColumn(tb, col)
            g.Children.Add(tb)
        tools = hpanel(Thickness(0))
        for sym, d_ in ((u'↑', -1), (u'↓', 1), (u'✕', 0)):
            b_ = Button()
            b_.Content = sym
            b_.Padding = Thickness(6, 0, 6, 0)
            b_.Margin = Thickness(0, 0, 2, 0)

            def act(s, e, idx=idx, d_=d_):
                if d_ == 0:
                    del parts[idx]
                else:
                    k2 = idx + d_
                    if 0 <= k2 < len(parts):
                        parts[idx], parts[k2] = parts[k2], parts[idx]
                rebuild()
                onchg()
            b_.Click += act
            tools.Children.Add(b_)
        Grid.SetColumn(tools, 3)
        g.Children.Add(tools)
        box.Children.Add(g)

    def add_part(s, e):
        parts.append({'field': fields[0][0], 'prefix': u' ', 'suffix': u''})
        rebuild()
        onchg()

    def reset_parts(s, e):
        del parts[:]
        parts.extend(dict(x) for x in defaults)
        rebuild()
        onchg()
    bar = hpanel(Thickness(0, 4, 0, 0))
    bar.Children.Add(btn(u'+ поле', add_part))
    bar.Children.Add(btn(u'Как было', reset_parts, reset_tip))
    box.Children.Add(bar)


def build_parts():
    parts_editor(lab_box, PARTS, FIELDS, v.DEFAULT_PARTS, lambda: (preview(), foot_preview()),
                 u'Значение — расшифровка (N шт.)')


build_parts()
vals_panel = StackPanel()
Grid.SetIsSharedSizeScope(vals_panel, True)
vv = ScrollViewer()
vv.MaxHeight = 300
vv.VerticalScrollBarVisibility = ScrollBarVisibility.Auto
vv.Content = vals_panel
s3.Children.Add(vv)
W['vals'] = []

# ---- итог под легендой (db 22.10): линия, счётчик с префиксом/суффиксом, примечание — каждое включается отдельно
FOOTBY = dict(CFG.get('foot_by') or {})   # {параметр: {'line','count_on','note_on','note','parts','last_note'}}
FOOT_FIELDS = list(v.FOOT_FIELDS) + [('sum:' + n, u'Итог суммы: ' + n) for n in NUMP]
FOOT_OF = [None]
FOOT = {}


def foot_default():
    d = {'line': True, 'count_on': True, 'note_on': False, 'note': u'',
         'parts': [dict(x) for x in v.DEFAULT_FOOT['parts']]}
    for pt in PARTS:   # есть сумма в строках — итог той же суммы (единица «м³/ч» уже в формате проекта)
        f = pt.get('field') or u''
        if f.startswith('sum:'):
            d['parts'].append({'field': f, 'prefix': u', ', 'suffix': u''})
            break
    return d


def switch_foot(par):
    if FOOT_OF[0] is not None:
        FOOTBY[FOOT_OF[0]] = dict(FOOT)
    FOOT.clear()
    FOOT.update(FOOTBY.get(par) or foot_default())
    FOOT['parts'] = [dict(x) for x in (FOOT.get('parts') or [])]
    FOOT_OF[0] = par
    W['fbusy'] = True
    cb_line.IsChecked = bool(FOOT.get('line'))
    cb_cnt.IsChecked = bool(FOOT.get('count_on'))
    cb_note.IsChecked = bool(FOOT.get('note_on'))
    note_tb.Text = FOOT.get('note') or u''
    W['fbusy'] = False
    parts_editor(foot_box, FOOT['parts'], FOOT_FIELDS, foot_default()['parts'], foot_preview,
                 u'«Итого · N систем» + итог суммы, если она есть в строках')
    foot_vis()


def foot_ctx():
    par = cur_param()
    vals = [val for val, sw in W['vals']]
    c = {'n': u'%d' % len(vals), 'nsp': u'%d' % sum(W['counts'].get(x, 0) for x in vals)}
    for pt in FOOT.get('parts') or []:
        f = pt.get('field') or u''
        if f.startswith('sum:'):
            ck = (par, u'итог', f[4:], tuple(vals))
            if ck not in SUMS:
                SUMS[ck] = v.total(doc, par, f[4:], scope_all(), vals)
            c[f] = SUMS[ck]
    return c


def foot_text():
    return v.compose(FOOT.get('parts') or [], foot_ctx()) if FOOT.get('count_on') else u''


def foot_spec():
    return {'line': bool(FOOT.get('line')), 'count': foot_text(),
            'note': (FOOT.get('note') or u'') if FOOT.get('note_on') else u'', 'note_old': FOOT.get('last_note') or u''}


def foot_preview(*a):
    if 'fprev' not in W or not FOOT:
        return
    sp_ = foot_spec()
    lines = []
    if sp_['line']:
        lines.append(u'———— линия по длине последней строки')
    if sp_['count']:
        lines.append(sp_['count'])
    if sp_['note'].strip():
        lines.append(sp_['note'].strip())
    W['fprev'].Text = u'\n'.join(lines) or u'(итога нет)'


def foot_vis():
    foot_box.Visibility = Visibility.Visible if FOOT.get('count_on') else Visibility.Collapsed
    note_tb.Visibility = Visibility.Visible if FOOT.get('note_on') else Visibility.Collapsed
    foot_preview()


def on_foot(s_, e_):
    if W.get('fbusy'):
        return
    FOOT['line'] = bool(cb_line.IsChecked)
    FOOT['count_on'] = bool(cb_cnt.IsChecked)
    FOOT['note_on'] = bool(cb_note.IsChecked)
    FOOT['note'] = note_tb.Text or u''
    foot_vis()


s3.Children.Add(txt(u'Итог под легендой — линия длиной до конца последней строки; счётчик и примечание переносятся '
                    u'по её длине (не длиннее линии). Типы текста и стиль линии, поменянные в легенде руками, сохраняются.',
                    muted=True, size=12, margin=Thickness(0, 8, 0, 2)))
pf = hpanel(Thickness(0, 0, 0, 2))
cb_line = CheckBox()
cb_line.Content = u'Линия'
cb_cnt = CheckBox()
cb_cnt.Content = u'Счётчик'
cb_note = CheckBox()
cb_note.Content = u'Примечание'
for c_ in (cb_line, cb_cnt, cb_note):
    c_.Margin = Thickness(0, 0, 16, 0)
    c_.Click += on_foot
    pf.Children.Add(c_)
s3.Children.Add(pf)
foot_box = StackPanel()
foot_box.Margin = Thickness(0, 0, 0, 4)
s3.Children.Add(foot_box)
note_tb = TextBox()
note_tb.AcceptsReturn = True
note_tb.TextWrapping = TextWrapping.Wrap
note_tb.MinHeight = 40
note_tb.Margin = Thickness(0, 0, 0, 4)
note_tb.ToolTip = u'Текст примечания, например «*Без учета компенсационных систем на местные отсосы». Enter — новая строка'
note_tb.TextChanged += on_foot
s3.Children.Add(note_tb)
W['fprev'] = txt(u'', size=12, margin=Thickness(0, 0, 0, 4))
W['fprev'].Foreground = B(forms.GREEN)
W['fprev'].ToolTip = u'Так итог будет выглядеть в легенде'
s3.Children.Add(W['fprev'])


def legend_build(par, rows):
    """Легенда со строками и итогом; запоминает текст примечания, чтобы при перерисовке узнать его тип."""
    lg_ = v.make_legend(doc, par, rows, u'Объёмы: ' + par, foot_spec())
    FOOT['last_note'] = FOOT.get('note') or u''
    return lg_


def cur_param():
    it = pc.SelectedItem
    return it.Tag if it is not None else None


def pick_color(value, swatch):
    d = ColorDialog()
    d.FullOpen = True
    r, g, b = v.hexrgb(swatch.Tag)
    d.Color = System.Drawing.Color.FromArgb(r, g, b)
    if d.ShowDialog() == DialogResult.OK:
        hx = u'#%02X%02X%02X' % (d.Color.R, d.Color.G, d.Color.B)
        swatch.Tag = hx
        swatch.Background = B(hx)
        COLORS.setdefault(cur_param() or u'', {})[value] = hx


def fill_values(*a):
    SUMS.clear()
    vals_panel.Children.Clear()
    W['vals'] = []
    W['counts'] = {}
    W['prev'] = {}
    par = cur_param()
    if not par:
        vals_panel.Children.Add(txt(u'Сначала создайте объёмы и выберите параметр.', muted=True))
        return
    cnt, stale, novol = v.space_stats(doc, par, scope_all())
    if not cnt:
        vals_panel.Children.Add(txt(u'Пространств нет.', muted=True))
        return
    nvol = len(v.our_volumes(doc))
    warn = []
    if not nvol:
        warn.append(u'Объёмов ещё нет — «Создать / обновить», иначе красить нечего.')
    if stale:
        warn.append(u'Устарели объёмы: %d (значение «%s» в пространстве поменяли) — нажмите «Создать / обновить», '
                    u'иначе цвет на виде будет по старому значению.' % (stale, par))
    if novol and nvol:
        warn.append(u'Пространств без объёма: %d (%s) — на виде не покрашены, но в суммы и количество входят.' % (
            len(novol), u', '.join(v.space_label(x) for x in novol[:6]) + (u' …' if len(novol) > 6 else u'')))
    for w_ in warn:
        wt = txt(w_, size=12, margin=Thickness(0, 0, 0, 3))
        wt.Foreground = B(forms.RED)
        vals_panel.Children.Add(wt)
    pal = COLORS.setdefault(par, {})
    # новым значениям — цвета, которых нет у других схем (если включено) и у этой
    need = [val for val, n in cnt if val and val not in pal]
    if need:
        used = set(pal.values())
        used |= avoid_set(par)
        for val, hx in zip(need, gen(used, len(need), par=par)):
            pal[val] = hx
    i = 0
    for value, n in cnt:
        g = Grid()
        for w_ in (34, 'auto', 104, '*', '*'):
            cd = ColumnDefinition()
            cd.Width = GridLength(1, GridUnitType.Star) if w_ == '*' else (GridLength.Auto if w_ == 'auto' else GridLength(w_))
            if w_ == 'auto':
                cd.MinWidth = 130
                cd.SharedSizeGroup = 'valname'   # одна ширина колонки названий во всех строках
            g.ColumnDefinitions.Add(cd)
        g.Margin = Thickness(0, 2, 6, 2)
        if value:
            hx = pal.get(value) or v.PALETTE[i % len(v.PALETTE)]
            pal[value] = hx
            i += 1
            sw = Border()
            sw.Width = 26
            sw.Height = 16
            sw.CornerRadius = System.Windows.CornerRadius(3)
            sw.BorderBrush = B('#202020')
            sw.BorderThickness = Thickness(1)
            sw.Tag = hx
            sw.Background = B(hx)
            sw.Cursor = System.Windows.Input.Cursors.Hand
            sw.ToolTip = u'Щёлкните, чтобы выбрать цвет'
            sw.VerticalAlignment = VerticalAlignment.Center
            sw.HorizontalAlignment = HorizontalAlignment.Left
            sw.MouseLeftButtonUp += (lambda val, s_: (lambda s, e: pick_color(val, s_)))(value, sw)
            Grid.SetColumn(sw, 0)
            g.Children.Add(sw)
            W['vals'].append((value, sw))
        t = txt((value or u'<пусто> — не красится') + u'  ·  %d шт.' % n, muted=not value, margin=Thickness(0))
        t.TextWrapping = TextWrapping.NoWrap
        t.Margin = Thickness(0, 0, 8, 0)
        t.VerticalAlignment = VerticalAlignment.Center
        Grid.SetColumn(t, 1)
        g.Children.Add(t)
        if value:
            mc = ComboBox()
            mc.Margin = Thickness(4, 0, 0, 0)
            for k_, n_ in (('add', u'дополнить'), ('replace', u'заменить')):
                ci_ = ComboBoxItem()
                ci_.Content = n_
                ci_.Tag = k_
                mc.Items.Add(ci_)
                if k_ == DMODE.get(par, {}).get(value, 'add'):
                    mc.SelectedItem = ci_
            mc.ToolTip = (u'дополнить — текст справа ставится в конец подписи (или на место поля «Расшифровка», если оно '
                          u'есть в полях); заменить — вся подпись этой строки = текст справа')

            def on_mode(s, e, val=value, box=mc):
                if box.SelectedItem is not None:
                    DMODE.setdefault(cur_param() or u'', {})[val] = box.SelectedItem.Tag
                    preview()
            mc.SelectionChanged += on_mode
            Grid.SetColumn(mc, 2)
            g.Children.Add(mc)
            dt = TextBox()
            dt.Margin = Thickness(4, 0, 0, 0)
            dt.Text = DESC.setdefault(par, {}).get(value, u'')
            dt.ToolTip = u'Расшифровка для легенды, например «Приточная установка П2 — 1-й этаж»'

            def on_txt(s, e, val=value, box=dt):
                DESC.setdefault(cur_param() or u'', {})[val] = box.Text or u''
                preview()
            dt.TextChanged += on_txt
            Grid.SetColumn(dt, 3)
            g.Children.Add(dt)
            W['counts'][value] = n
            pv_ = txt(u'', margin=Thickness(10, 0, 0, 0))
            pv_.TextWrapping = TextWrapping.Wrap   # подпись видна целиком (db 21.10), длинная — в две строки
            pv_.VerticalAlignment = VerticalAlignment.Center
            pv_.Foreground = B(forms.GREEN)
            pv_.ToolTip = u'Так строка будет подписана в легенде'
            Grid.SetColumn(pv_, 4)
            g.Children.Add(pv_)
            W['prev'][value] = pv_
        vals_panel.Children.Add(g)
    preview()
    foot_preview()


def fill_params(keep=None):
    pc.Items.Clear()
    prm = [n for n in PNAMES if v.bound_to_gm(doc, n, BND)]
    want = keep or CFG.get('paint_param') or v.DEF_PARAMS[0]
    for n in prm:
        ci = ComboBoxItem()
        ci.Content = n
        ci.Tag = n
        pc.Items.Add(ci)
        if n == want:
            pc.SelectedItem = ci
    if pc.SelectedItem is None and pc.Items.Count:
        pc.SelectedIndex = 0


PC_BUSY = [False]   # список перестраивается — смену выбора не обрабатывать


def on_pc(s, e):
    if PC_BUSY[0]:
        return
    switch_parts(cur_param())
    fill_values()
    uniq_text()
    sync_pal()


pc.SelectionChanged += on_pc


def refresh_params():
    """Привязки перечитать заново: параметр, только что привязанный к «Обобщённым моделям»,
    появляется в списке сразу, без переоткрытия окна. Выбранный параметр остаётся выбранным."""
    BND.clear()
    BND.update(v.bindings(doc))
    if [it.Tag for it in pc.Items] == [n for n in PNAMES if v.bound_to_gm(doc, n, BND)]:
        return
    old = cur_param()
    PC_BUSY[0] = True
    try:
        fill_params(old)
    finally:
        PC_BUSY[0] = False
    if cur_param() != old:
        on_pc(None, None)


pc.DropDownOpened += lambda s, e: refresh_params()


@guarded
def do_paint(s, e):
    par = cur_param()
    cols = [(val, sw.Tag) for val, sw in W['vals']]
    if not par or not cols:
        status(u'Нечего красить: нет объёмов или значений.', False)
        return
    old = [doc.GetElement(f).Name for f in view.GetFilters() if doc.GetElement(f).Name.startswith(v.PREFIX)]
    empt = u'скрыты' if sl0.Value >= 100 else u'%d %%' % sl0.Value
    msg = (u'Вид «%s», параметр «%s», прозрачность %d %%, бесцветные — %s.\n• фильтров на вид: %d (по значению) + 1 для '
           u'бесцветных\n• снять прежние фильтры раскраски объёмов: %d\n\nКаждый фильтр: «%s» равно значению И «Комментарии» '
           u'содержит «%s».\n\nПокрасить?' % (view.Name, par, sl.Value, empt, len(cols), len(old), par, v.MARK))
    if view.ViewTemplateId != DB.ElementId.InvalidElementId:
        t = doc.GetElement(view.ViewTemplateId)
        if t is not None and DB.ElementId(DB.BuiltInParameter.VIS_GRAPHICS_FILTERS) in list(t.GetTemplateParameterIds()):
            status(u'Фильтрами вида управляет шаблон «%s» — снимите шаблон или красьте другой вид.' % t.Name, False)
            return
    lg = legend_of(par)
    if lg is not None:
        msg = msg.replace(u'\n\nПокрасить?', u'\n• легенда «%s» перерисуется теми же цветами и подписями\n\nПокрасить?' % lg.Name)
    if not ask(msg):
        return
    with revit.Transaction(u'XYZ: объёмы — раскраска'):
        on, cr = v.paint(doc, view, par, cols, sl.Value, empty_transp=sl0.Value)
        if lg is not None:   # db 21.10: «покрасить вид — и легенды тоже»
            legend_build(par, legend_rows())
    CFG['paint_param'] = par
    CFG['transp'] = int(sl.Value)
    CFG['transp_empty'] = int(sl0.Value)
    save_cfg()
    status(u'На виде фильтров: %d (новых %d)%s. Отмена — Ctrl+Z.' % (
        on, cr, (u'; легенда «%s» обновлена' % lg.Name) if lg is not None else u''))


def legend_of(par):
    name = v.legend_name(par)
    for x in DB.FilteredElementCollector(doc).OfClass(DB.View):
        if x.ViewType == DB.ViewType.Legend and not x.IsTemplate and x.Name == name:
            return x
    return None


def legend_rows():
    return [(final_label(val), sw.Tag) for val, sw in W['vals']]


@guarded
def do_new_view(s, e):
    par = cur_param()
    cols = [(val, sw.Tag) for val, sw in W['vals']]
    if not par or not cols:
        status(u'Нечего красить: нет объёмов или значений.', False)
        return
    short = par.replace(u'ADSK_', u'').replace(u'Наименование ', u'')
    name = v.safe(u'%s_%s' % (view.Name, short))
    ex = [x for x in DB.FilteredElementCollector(doc).OfClass(DB.View) if not x.IsTemplate and x.Name == name]
    if ex:
        status(u'Вид «%s» уже есть — откройте его и нажмите «Покрасить вид».' % name, False)
        return
    if view.ViewTemplateId != DB.ElementId.InvalidElementId:
        t = doc.GetElement(view.ViewTemplateId)
        if t is not None and DB.ElementId(DB.BuiltInParameter.VIS_GRAPHICS_FILTERS) in list(t.GetTemplateParameterIds()):
            status(u'Фильтрами вида управляет шаблон «%s» — копия унаследует его; снимите шаблон.' % t.Name, False)
            return
    if not ask(u'Копия вида «%s» → «%s» (без аннотаций), покрасить её по «%s», прозрачность %d %%: %d фильтров.\n'
               u'Текущий вид не меняется.\n\nСделать?' % (view.Name, name, par, sl.Value, len(cols))):
        return
    with revit.Transaction(u'XYZ: объёмы — вид под параметр'):
        nv = doc.GetElement(view.Duplicate(DB.ViewDuplicateOption.Duplicate))
        nv.Name = name
        on, cr = v.paint(doc, nv, par, cols, sl.Value, empty_transp=sl0.Value)
        if legend_of(par) is not None:
            legend_build(par, legend_rows())
    CFG['paint_param'] = par
    save_cfg()
    status(u'Создан вид «%s» (фильтров %d) — в Диспетчере проекта рядом с исходным. Отмена — Ctrl+Z.' % (name, on))


@guarded
def do_legend(s, e):
    par = cur_param()
    rows = [(final_label(val), sw.Tag) for val, sw in W['vals']]
    if not par or not rows:
        status(u'Нечего показывать в легенде.', False)
        return
    name = v.legend_name(par)
    ex = [x for x in DB.FilteredElementCollector(doc).OfClass(DB.View) if x.ViewType == DB.ViewType.Legend and x.Name == name]
    if not ask(u'Легенда «%s»: %s.\n• строк: %d, например «%s»\n• типы заливки «db_Объём_<цвет>»'
               u' — создадутся недостающие\n\nСделать?' % (name, u'перерисуется (её заливки и тексты удалятся и '
                                                          u'нарисуются заново)' if ex else u'создастся новая', len(rows), rows[0][0])):
        return
    with revit.Transaction(u'XYZ: объёмы — легенда'):
        lg = legend_build(par, rows)
    save_cfg()
    BYP[par] = [dict(x) for x in PARTS]
    CFG['label_parts_by'] = BYP
    save_cfg()
    status(u'Легенда «%s» готова — в Диспетчере проекта → Легенды; перетащите на лист. Отмена — Ctrl+Z.' % lg.Name)


p4 = hpanel(Thickness(0, 8, 0, 0))
p4.Children.Add(btn(u'Покрасить вид', do_paint))
p4.Children.Add(btn(u'Новый вид…', do_new_view, u'Копия активного вида, покрашенная по выбранному параметру'))
p4.Children.Add(btn(u'Легенда', do_legend, u'Легенда «db_Легенда_Объёмы_<параметр>» в «Легендах»: цвет — значение — '
                                           u'расшифровка (шт.). Есть — перерисуется'))
# разделитель: тянуть вверх/вниз — больше места списку параметров (раздел 2) или значений (раздел 3)
from System.Windows.Controls.Primitives import Thumb
SPLIT = [float(CFG.get('split', 0))]
grip = Thumb()
grip.Height = 8
grip.Margin = Thickness(40, -6, 40, 4)
grip.Cursor = System.Windows.Input.Cursors.SizeNS
grip.Background = B(forms.LINE)
grip.ToolTip = u'Тяните вверх/вниз: больше места параметрам или значениям'


def on_drag(s, e):
    SPLIT[0] += e.VerticalChange
    apply_sizes()


grip.DragDelta += on_drag
root.Children.Add(grip)
root.Children.Add(b3)

W['status'] = txt(u'', size=12, margin=Thickness(4, 4, 4, 0))
# строка состояния — отдельной строкой ПОД кнопками (db 21.10: рядом с кнопками она их выталкивала)
_fb = dlg._footer_border
_old = _fb.Child
_fb.Child = None
_fp = StackPanel()
_fp.Children.Add(_old)
_fp.Children.Add(W['status'])
_fb.Child = _fp
fill_params()
switch_parts(cur_param())
fill_values()
uniq_text()
sync_pal()
dlg.add_button(u'Закрыть', None, cancel=True)
# кнопки раскраски — внизу окна, всегда видны (db 21.10: при маленьком окне уезжали под прокрутку)
for k_, b_ in enumerate(list(p4.Children)):
    p4.Children.Remove(b_)
    dlg.footer.Children.Insert(k_, b_)

# окно тянется — растут список параметров (35 %) и список значений (65 %)
BASE = {}


def on_loaded(s, e):
    BASE['h'] = dlg.ActualHeight
    BASE['sv'] = sv.ActualHeight
    BASE['pv'] = pv.MaxHeight
    BASE['vv'] = vv.MaxHeight
    apply_sizes()


def on_size(s, e):
    if 'h' not in BASE:
        return
    d = dlg.ActualHeight - BASE['h']
    extra = max(0.0, d)
    sv.MaxHeight = max(150.0, BASE['sv'] + d)   # окно меньше — прокрутка внутри, кнопки внизу остаются
    BASE['extra'] = extra
    apply_sizes()


def apply_sizes():
    if 'h' not in BASE:
        return
    extra = BASE.get('extra', 0.0)
    a_ = BASE['pv'] + extra * 0.35
    b_ = BASE['vv'] + extra * 0.65
    # сдвиг разделителя: что прибавилось сверху — убавилось снизу (не меньше 60 px у каждого)
    sh = max(60.0 - a_, min(SPLIT[0], b_ - 60.0))
    SPLIT[0] = sh
    pv.MaxHeight = a_ + sh
    pv.Height = a_ + sh
    vv.MaxHeight = b_ - sh
    CFG['split'] = sh


# Ctrl + колесо — масштаб всей рабочей области (db 21.10), Ctrl+0 — 100 %; запоминается
from System.Windows.Media import ScaleTransform
from System.Windows.Input import Keyboard, ModifierKeys, Key
ZOOM = [max(0.6, min(1.6, float(CFG.get('zoom', 1.0))))]
root.LayoutTransform = ScaleTransform(ZOOM[0], ZOOM[0])


def set_zoom(z):
    ZOOM[0] = round(max(0.6, min(1.6, z)), 2)
    root.LayoutTransform = ScaleTransform(ZOOM[0], ZOOM[0])
    CFG['zoom'] = ZOOM[0]
    dlg._s.Text = u'вид «%s» · масштаб окна %d %% (Ctrl+колесо, Ctrl+0 — 100 %%) · цвет — только фильтрами вида' % (
        view.Name, int(ZOOM[0] * 100))


def on_zoom_wheel(s_, e_):
    if Keyboard.Modifiers & ModifierKeys.Control == ModifierKeys.Control:
        set_zoom(ZOOM[0] + (0.05 if e_.Delta > 0 else -0.05))
        e_.Handled = True


def on_zoom_key(s_, e_):
    if Keyboard.Modifiers & ModifierKeys.Control == ModifierKeys.Control and e_.Key in (Key.D0, Key.NumPad0):
        set_zoom(1.0)
        e_.Handled = True


dlg.PreviewMouseWheel += on_zoom_wheel
dlg.PreviewKeyDown += on_zoom_key
dlg.Loaded += on_loaded
dlg.SizeChanged += on_size
dlg.ShowDialog()
save_cfg()
