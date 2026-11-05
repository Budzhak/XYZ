# -*- coding: utf-8 -*-
"""Единый стиль окон XYZ.extension: чёрный — зелёный — белый.

Подключение в скрипте — одной строкой после импортов pyRevit:

    import xyz_forms as forms

Дальше все вызовы forms.* работают как раньше (те же аргументы и ответы, что у
pyrevit.forms), но окна рисуются в общем стиле:
  alert, ask_for_string, CommandSwitchWindow, SelectFromList — свои окна;
  остальное (ProgressBar, toast, pick_file, TemplateListItem, WPFWindow…) —
  без изменений из pyRevit.

Для своих WPF-окон:  forms.theme(window, u'Заголовок', u'подзаголовок')
— подключает стили (кнопки-пилюли, поля, флажки, группы-карточки, слайдер)
и добавляет тёмную шапку.  Кнопка с IsDefault=True становится зелёной.
Для окна вывода pyRevit:  forms.style_output(output)
Адаптивность окна (тянется, Ctrl+колесо — масштаб, размер запоминается):
    forms.adaptive(window, u'ключ')
"""
import os
import sys

import clr
clr.AddReference('PresentationFramework')
clr.AddReference('PresentationCore')
clr.AddReference('WindowsBase')

from pyrevit.forms import *                     # noqa: F401,F403  всё прочее — как в pyRevit
from pyrevit import forms as _pf


class WPFWindow(_pf.WPFWindow):
    """pyRevit 7: apply_contrast_foregrounds падает ('NoneType' has no attribute 'Color'),
    когда в ресурсах окна XYZ нет pyRevitWindow*Brush. Ошибку контраста глотаем — окно открывается."""
    def apply_contrast_foregrounds(self, *a, **k):
        try:
            return _pf.WPFWindow.apply_contrast_foregrounds(self, *a, **k)
        except Exception:
            return None

import System
from System.IO import File
from System.Windows import (Thickness, TextWrapping, HorizontalAlignment, VerticalAlignment,
                            FontWeights, Visibility, WindowStartupLocation, ResizeMode, SizeToContent,
                            GridLength, GridUnitType)
from System.Windows.Controls import (Border, DockPanel, StackPanel, TextBlock, Button, TextBox, CheckBox,
                                     ScrollViewer, ScrollBarVisibility, Orientation, Dock, Grid, ListBox,
                                     ColumnDefinition, RowDefinition)
from System.Windows.Markup import XamlReader
from System.Windows.Media import SolidColorBrush, Color, FontFamily
from System.Windows.Input import Key

HERE = os.path.dirname(os.path.abspath(__file__))
XAML_DIR = os.path.join(HERE, 'xyz_xaml')
_THEME_PATH = os.path.join(XAML_DIR, 'Theme.xaml')
_theme_text = None


def _brush(hexstr):
    h = hexstr.lstrip('#')
    return SolidColorBrush(Color.FromRgb(int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)))


DARK, GREEN, GREEN_SOFT, BG, LINE, INK, MUTE, RED = (
    '#1E2A22', '#2E7D32', '#A5D6A7', '#F4F6F4', '#DDE3DE', '#1B1F1C', '#7A847C', '#C62828')


def theme_dictionary():
    """Новый экземпляр словаря стилей (на каждое окно свой)."""
    global _theme_text
    if _theme_text is None:
        _theme_text = File.ReadAllText(_THEME_PATH)
    return XamlReader.Parse(_theme_text)


def _header(title, subtitle=None):
    hdr = Border()
    hdr.Background = _brush(DARK)
    hdr.Padding = Thickness(18, 12, 18, 12)
    sp = StackPanel()
    t = TextBlock()
    t.Text = title or u''
    t.Foreground = _brush('#FFFFFF')
    t.FontSize = 16
    t.FontWeight = FontWeights.SemiBold
    t.TextWrapping = TextWrapping.Wrap
    sp.Children.Add(t)
    s = TextBlock()
    s.Foreground = _brush(GREEN_SOFT)
    s.FontSize = 11
    s.Margin = Thickness(0, 2, 0, 0)
    s.TextWrapping = TextWrapping.Wrap
    s.Text = subtitle or u''
    s.Visibility = Visibility.Visible if subtitle else Visibility.Collapsed
    sp.Children.Add(s)
    hdr.Child = sp
    return hdr, t, s


def theme_uri():
    """Путь к Theme.xaml для <ResourceDictionary Source="..."/> внутри своего XAML
    (нужно, если в окне свои стили с BasedOn на стили темы)."""
    return System.Uri(_THEME_PATH).AbsoluteUri


def theme(win, title=None, subtitle=None, header=True, merge=True):
    """Применить общий стиль к готовому WPF-окну (после загрузки XAML)."""
    if merge:
        win.Resources.MergedDictionaries.Add(theme_dictionary())
    win.Background = _brush(BG)
    win.Foreground = _brush(INK)
    win.FontFamily = FontFamily('Segoe UI')
    if header:
        content = win.Content
        win.Content = None
        dock = DockPanel()
        hdr, t, s = _header(title if title is not None else win.Title, subtitle)
        DockPanel.SetDock(hdr, Dock.Top)
        dock.Children.Add(hdr)
        if content is not None:
            dock.Children.Add(content)
        win.Content = dock
        win.xyz_title_tb = t
        win.xyz_sub_tb = s
    return win


def set_subtitle(win, text):
    s = getattr(win, 'xyz_sub_tb', None)
    if s is not None:
        s.Text = text or u''
        s.Visibility = Visibility.Visible if text else Visibility.Collapsed


_OUTPUT_CSS = u"""
body { font-family: 'Segoe UI', sans-serif; color: #1B1F1C; background: #F4F6F4; }
h1, h2, h3 { color: #1E2A22; border-left: 5px solid #2E7D32; padding-left: 8px; }
a { color: #2E7D32; font-weight: 600; }
table { border-collapse: collapse; background: #fff; border: 1px solid #DDE3DE; }
th { background: #1E2A22 !important; color: #fff !important; padding: 5px 8px; }
td { border-top: 1px solid #DDE3DE; padding: 4px 8px; }
tr:hover td { background: #E8F5E9; }
code, pre { background: #E8F5E9; color: #1B5E20; border-radius: 4px; }
"""


def style_output(output):
    """Окно вывода pyRevit в общем стиле (заголовки, таблицы, ссылки)."""
    try:
        output.add_style(_OUTPUT_CSS)
    except Exception:
        pass
    return output


# ------------------------------------------------------------------ адаптивное окно (стандарт «Объёмов», db 22.10.2026)
def adaptive(win, key, size=True, root=None, min_w=None, min_h=None):
    """Окно тянется, Ctrl+колесо — масштаб (60–160 %), Ctrl+0 — 100 %; размер и масштаб
    запоминаются в xyz_settings (ключ 'win_<key>'). Повторный вызов только меняет ключ/режим.
    size=False — окно по содержимому (диалоги): запоминается только масштаб.
    Ошибка внутри не ломает окно — оно просто откроется как раньше."""
    try:
        return _adaptive(win, key, size, root, min_w, min_h)
    except Exception:
        return win


def _adaptive(win, key, size, root, min_w, min_h):
    from System.Windows.Media import ScaleTransform
    from System.Windows.Input import Keyboard, ModifierKeys
    try:
        import xyz_settings as _hs
    except Exception:
        _hs = None
    st = getattr(win, '_xyz_ad', None)
    first = st is None
    if first:
        st = {}
        win._xyz_ad = st
    st['key'] = 'win_' + key
    st['size'] = bool(size)
    st['root'] = root or st.get('root')
    cfg = {}
    if _hs is not None:
        try:
            cfg = dict(_hs.get(st['key']) or {})
        except Exception:
            cfg = {}
    if size:
        try:
            win.ResizeMode = ResizeMode.CanResize
            if min_w:
                win.MinWidth = min_w
            if min_h:
                win.MinHeight = min_h
            if cfg.get('w') and cfg.get('h'):
                win.SizeToContent = SizeToContent.Manual
                win.Width = max(float(cfg['w']), win.MinWidth or 0)
                win.Height = max(float(cfg['h']), win.MinHeight or 0)
        except Exception:
            pass

    def target():
        r = st.get('root')
        return r if r is not None else win.Content

    def set_zoom(z):
        z = round(max(0.6, min(1.6, z)), 2)
        st['zoom'] = z
        t = target()
        if t is not None:
            try:
                t.LayoutTransform = ScaleTransform(z, z)
            except Exception:
                pass
    st['set_zoom'] = set_zoom

    def on_loaded(s, e):
        if st.get('zoom', 1.0) != 1.0:
            set_zoom(st['zoom'])

    def on_wheel(s, e):
        if Keyboard.Modifiers & ModifierKeys.Control == ModifierKeys.Control:
            st['set_zoom'](st.get('zoom', 1.0) + (0.05 if e.Delta > 0 else -0.05))
            e.Handled = True

    def on_key(s, e):
        if Keyboard.Modifiers & ModifierKeys.Control == ModifierKeys.Control and str(e.Key) in ('D0', 'NumPad0'):
            st['set_zoom'](1.0)
            e.Handled = True

    def on_closing(s, e):
        if _hs is None:
            return
        try:
            d = {'zoom': st.get('zoom', 1.0)}
            if st['size'] and win.SizeToContent == SizeToContent.Manual:
                d['w'], d['h'] = win.ActualWidth, win.ActualHeight
            elif st['size']:
                d['w'], d['h'] = win.ActualWidth, win.ActualHeight
            old = dict(_hs.get(st['key']) or {})
            if old != d:
                _hs.set(st['key'], d)
        except Exception:
            pass
    st['zoom'] = float(cfg.get('zoom', st.get('zoom', 1.0)) or 1.0)
    if first:
        win.Loaded += on_loaded
        win.PreviewMouseWheel += on_wheel
        win.PreviewKeyDown += on_key
        win.Closing += on_closing
    elif win.IsLoaded:
        set_zoom(st['zoom'])
    return win


# ------------------------------------------------------------------ базовое окно-диалог
class _Dialog(_pf.WPFWindow):
    """Пустое окно в стиле XYZ: шапка + тело + подвал с кнопками."""
    _XAML = (u'<Window xmlns="http://schemas.microsoft.com/winfx/2006/xaml/presentation" '
             u'xmlns:x="http://schemas.microsoft.com/winfx/2006/xaml" '
             u'WindowStartupLocation="CenterScreen" ShowInTaskbar="False" ResizeMode="NoResize" '
             u'SizeToContent="Height" Width="440" FontFamily="Segoe UI" FontSize="13"><Grid/></Window>')

    def __init__(self, title, width=440):
        _pf.WPFWindow.__init__(self, self._XAML, literal_string=True)
        self.Title = title or u'XYZ'
        self.Width = width
        self.response = None
        self.Resources.MergedDictionaries.Add(theme_dictionary())
        self.Background = _brush(BG)
        self.Foreground = _brush(INK)
        root = DockPanel()
        hdr, self._t, self._s = _header(self.Title)
        DockPanel.SetDock(hdr, Dock.Top)
        root.Children.Add(hdr)
        self.footer = StackPanel()
        self.footer.Orientation = Orientation.Horizontal
        self.footer.HorizontalAlignment = HorizontalAlignment.Right
        fb = Border()
        fb.Background = _brush('#FFFFFF')
        fb.BorderBrush = _brush(LINE)
        fb.BorderThickness = Thickness(0, 1, 0, 0)
        fb.Padding = Thickness(16, 10, 16, 10)
        fb.Child = self.footer
        DockPanel.SetDock(fb, Dock.Bottom)
        root.Children.Add(fb)
        self.body = StackPanel()
        self.body.Margin = Thickness(18, 14, 18, 14)
        root.Children.Add(self.body)
        self.Content = root
        self._footer_border = fb

    def add_text(self, text, muted=False, size=13, scroll=False):
        tb = TextBlock()
        tb.Text = text or u''
        tb.TextWrapping = TextWrapping.Wrap
        tb.FontSize = size
        if muted:
            tb.Foreground = _brush(MUTE)
        if scroll:
            sv = ScrollViewer()
            sv.MaxHeight = 420
            sv.VerticalScrollBarVisibility = ScrollBarVisibility.Auto
            sv.Content = tb
            self.body.Children.Add(sv)
        else:
            self.body.Children.Add(tb)
        return tb

    def add_button(self, text, value, primary=False, cancel=False):
        b = Button()
        b.Content = text
        b.Margin = Thickness(8, 0, 0, 0)
        b.MinWidth = 90
        if primary:
            b.IsDefault = True
        if cancel:
            b.IsCancel = True

        def click(s, e, v=value):
            self.response = v
            self.Close()
        b.Click += click
        self.footer.Children.Add(b)
        return b


# ------------------------------------------------------------------ alert
def alert(msg, title=None, sub_msg=None, expanded=None, footer='',
          ok=True, cancel=False, yes=False, no=False, retry=False,
          warn_icon=True, options=None, exitscript=False, **kwargs):
    """Как pyrevit.forms.alert: True — ОК/Да/Повтор, False — Нет/Отмена/закрыто,
    при options — текст выбранного варианта."""
    w = 480 if (msg and len(msg) > 160) else 440
    if options and max(len(o) for o in options) > 40:
        w = 600     # длинные пункты меню — шире окно, текст переносится (db, 18.10.2026)
    dlg = _Dialog(title or u'XYZ', width=w)
    dlg.add_text(msg, scroll=bool(msg and (msg.count(u'\n') > 14 or len(msg) > 900)))
    if sub_msg:
        t = dlg.add_text(sub_msg, muted=True, size=12)
        t.Margin = Thickness(0, 8, 0, 0)
    if expanded:
        t = dlg.add_text(expanded, muted=True, size=11, scroll=True)
        t.Margin = Thickness(0, 8, 0, 0)
    just_ok = ok and not any([cancel, yes, no, retry])
    if options:
        box = StackPanel()
        box.Margin = Thickness(0, 12, 0, 0)
        for i, opt in enumerate(options):
            b = Button()
            tb_ = TextBlock()
            tb_.Text = opt
            tb_.TextWrapping = TextWrapping.Wrap       # не обрезать длинный пункт
            b.Content = tb_
            b.HorizontalContentAlignment = HorizontalAlignment.Left
            b.Margin = Thickness(0, 0, 0, 6)
            if i == 0:
                b.IsDefault = True

            def click(s, e, v=opt):
                dlg.response = v
                dlg.Close()
            b.Click += click
            box.Children.Add(b)
        dlg.body.Children.Add(box)
        dlg._footer_border.Visibility = Visibility.Collapsed
    else:
        if no:
            dlg.add_button(u'Нет', False, cancel=not cancel)
        if cancel:
            dlg.add_button(u'Отмена', False, cancel=True)
        if retry:
            dlg.add_button(u'Повторить', True)
        if yes:
            dlg.add_button(u'Да', True, primary=True)
        elif ok:
            dlg.add_button(u'ОК', True, primary=True, cancel=just_ok)
    adaptive(dlg, 'dlg', size=False)
    dlg.ShowDialog()
    res = dlg.response
    if options:
        if res is None and exitscript:
            sys.exit()
        return res if res is not None else False
    if res:
        if just_ok and exitscript:
            sys.exit()
        return True
    if exitscript:
        sys.exit()
    return False


def alert_ifnot(condition, msg, *args, **kwargs):
    if not condition:
        return alert(msg, *args, **kwargs)


# ------------------------------------------------------------------ ask_for_string
def ask_for_string(default=None, prompt=None, title=None, **kwargs):
    """Как pyrevit.forms.ask_for_string: строка или None (Отмена/Esc)."""
    dlg = _Dialog(title or u'Ввод', width=420)
    if prompt:
        t = dlg.add_text(prompt)
        t.Margin = Thickness(0, 0, 0, 8)
    tb = TextBox()
    tb.Text = default or u''
    tb.MinHeight = 34          # не фиксированная высота: текст не обрезается при любом масштабе Windows
    dlg.body.Children.Add(tb)
    reserved = kwargs.get('reserved_values') or []
    warn = dlg.add_text(u'', muted=True, size=11)
    warn.Foreground = _brush(RED)
    dlg.add_button(u'Отмена', None, cancel=True)
    okb = dlg.add_button(u'ОК', '__ok__', primary=True)

    def changed(s, e):
        bad = tb.Text in [unicode(x) for x in reserved]
        okb.IsEnabled = not bad
        warn.Text = u'Такое значение уже есть' if bad else u''
    tb.TextChanged += changed

    def loaded(s, e):
        tb.Focus()
        tb.SelectAll()
    dlg.Loaded += loaded
    adaptive(dlg, 'dlg', size=False)
    dlg.ShowDialog()
    if dlg.response == '__ok__':
        return tb.Text
    return None


def ask_for_unique_string(reserved_values, default=None, prompt=None, title=None, **kwargs):
    kwargs['reserved_values'] = reserved_values
    return ask_for_string(default=default, prompt=prompt, title=title, **kwargs)


# ------------------------------------------------------------------ CommandSwitchWindow
class CommandSwitchWindow(object):
    """Как pyrevit.forms.CommandSwitchWindow.show(options, message=…, switches=…)."""

    @classmethod
    def show(cls, context, title=None, width=None, height=None, message=None,
             switches=None, config=None, recognize_access_key=False, **kwargs):
        dlg = _Dialog(title or u'Что делаем?', width=width if (width and width > 300) else 440)
        if message:
            dlg._t.Text = message
            if title:
                dlg._s.Text = title
                dlg._s.Visibility = Visibility.Visible
        sw = switches or []
        if not isinstance(sw, dict):
            sw = dict((s, False) for s in sw)
        sw_boxes = []
        for name, state in sw.items():
            cb = CheckBox()
            cb.Content = name
            cb.IsChecked = bool(state)
            cb.Margin = Thickness(0, 0, 0, 8)
            dlg.body.Children.Add(cb)
            sw_boxes.append(cb)
        box = StackPanel()
        for i, opt in enumerate(list(context)):
            b = Button()
            b.Content = (u'%d.  ' % (i + 1) if i < 9 else u'') + unicode(opt)
            b.HorizontalContentAlignment = HorizontalAlignment.Left
            b.Margin = Thickness(0, 0, 0, 6)
            b.Padding = Thickness(14, 8, 14, 8)

            def click(s, e, v=opt):
                dlg.response = v
                dlg.Close()
            b.Click += click
            box.Children.Add(b)
        dlg.body.Children.Add(box)
        hint = dlg.add_text(u'Цифра — быстрый выбор, Esc — отмена', muted=True, size=11)
        hint.Margin = Thickness(0, 4, 0, 0)
        dlg._footer_border.Visibility = Visibility.Collapsed
        opts = list(context)

        def keys(s, e):
            k = str(e.Key)
            if k.startswith('D') and len(k) == 2 and k[1].isdigit() or k.startswith('NumPad'):
                n = int(k[-1])
                if 1 <= n <= len(opts):
                    dlg.response = opts[n - 1]
                    dlg.Close()
        dlg.KeyDown += keys
        adaptive(dlg, 'dlg', size=False)
        dlg.ShowDialog()
        res = dlg.response
        if sw:
            return res, dict((cb.Content, bool(cb.IsChecked)) for cb in sw_boxes)
        return res


# ------------------------------------------------------------------ выбор положения отметки (2×2)
def pick_spot_side(title=u'Отметка на взрыв-схеме', value=u'±0.000'):
    """Окно 2×2: четыре квадратные кнопки с картинкой отметки (стрелка, выноска,
    полка, значение). Сверху — полка вверху, снизу — полка внизу; слева/справа — куда полка.
    Возвращает 'UL' | 'UR' | 'L' | 'R' (как xyz_elev_marks.SIDES) или None (Esc).
    Клавиши: 7 9 / 1 3 (цифровой блок) или Q E / Z C."""
    from System.Windows.Controls import Canvas
    from System.Windows.Shapes import Line, Polyline
    from System.Windows.Media import PointCollection
    from System.Windows import Point
    dlg = _Dialog(title, width=360)
    dlg._s.Text = u'Где полка отметки?'
    dlg._s.Visibility = Visibility.Visible
    grid = Grid()
    grid.HorizontalAlignment = HorizontalAlignment.Center
    for _ in range(2):
        grid.ColumnDefinitions.Add(ColumnDefinition())
        grid.RowDefinitions.Add(RowDefinition())
    S = 136.0
    ink = _brush(INK)
    green = _brush(GREEN)

    def ln(cv, x1, y1, x2, y2, br, w=1.6):
        l = Line()
        l.X1, l.Y1, l.X2, l.Y2 = x1, y1, x2, y2
        l.Stroke = br
        l.StrokeThickness = w
        cv.Children.Add(l)

    def picture(key):
        cv = Canvas()
        cv.Width = S - 16
        cv.Height = S - 16
        W, H = cv.Width, cv.Height
        right = key in ('R', 'UR')
        top = key in ('UL', 'UR')
        # точка на трубе: по центру по вертикали, сбоку, противоположном полке
        px = W * (0.28 if right else 0.72)
        py = H * (0.66 if top else 0.34)
        # кусок трубы (зелёный) через точку
        ln(cv, px - W * 0.26, py + H * 0.15, px + W * 0.26, py - H * 0.15, green, 4.0)
        # стрелка: засечка через острие + «галочка» в сторону выноски
        a = 7.0
        ln(cv, px - a * 1.4, py, px + a * 1.4, py, ink)
        sg = -1 if top else 1               # выноска вверх (полка вверху) или вниз
        ln(cv, px, py, px - a, py + sg * a, ink)
        ln(cv, px, py, px + a, py + sg * a, ink)
        # выноска и полка
        sy = H * (0.18 if top else 0.82)
        ln(cv, px, py, px, sy, ink)
        ex = px + (W * 0.62 if right else -W * 0.62)
        ln(cv, px, sy, ex, sy, ink)
        # значение над полкой (вверху) или под ней (внизу)
        tb = TextBlock()
        tb.Text = value
        tb.FontSize = 14
        tb.FontFamily = FontFamily('Consolas')
        tb.Foreground = ink
        tb.Measure(System.Windows.Size(1000, 1000))
        tw, th = tb.DesiredSize.Width, tb.DesiredSize.Height
        tx = (px + 4) if right else (px - 4 - tw)
        ty = (sy - th - 1) if top else (sy + 1)
        Canvas.SetLeft(tb, tx)
        Canvas.SetTop(tb, ty)
        cv.Children.Add(tb)
        return cv

    tips = {'UL': u'Полка вверху, влево', 'UR': u'Полка вверху, вправо',
            'L': u'Полка внизу, влево', 'R': u'Полка внизу, вправо'}
    for key, r, c in (('UL', 0, 0), ('UR', 0, 1), ('L', 1, 0), ('R', 1, 1)):
        b = Button()
        b.Width = S
        b.Height = S
        b.Margin = Thickness(5)
        b.Padding = Thickness(0)
        b.Content = picture(key)
        b.ToolTip = tips[key]

        def click(s, e, v=key):
            dlg.response = v
            dlg.Close()
        b.Click += click
        Grid.SetRow(b, r)
        Grid.SetColumn(b, c)
        grid.Children.Add(b)
    dlg.body.Children.Add(grid)
    hint = dlg.add_text(u'Щелчок — поставить. Клавиши 7 9 / 1 3, Esc — отмена', muted=True, size=11)
    hint.Margin = Thickness(0, 6, 0, 0)
    hint.HorizontalAlignment = HorizontalAlignment.Center
    dlg._footer_border.Visibility = Visibility.Collapsed
    km = {'NumPad7': 'UL', 'NumPad9': 'UR', 'NumPad1': 'L', 'NumPad3': 'R',
          'D7': 'UL', 'D9': 'UR', 'D1': 'L', 'D3': 'R',
          'Q': 'UL', 'E': 'UR', 'Z': 'L', 'C': 'R'}

    def keys(s, e):
        k = str(e.Key)
        if k in km:
            dlg.response = km[k]
            dlg.Close()
        elif k == 'Escape':
            dlg.Close()
    dlg.KeyDown += keys
    adaptive(dlg, 'dlg', size=False)
    dlg.ShowDialog()
    return dlg.response


# ------------------------------------------------------------------ SelectFromList
class SelectFromList(_pf.SelectFromList):
    """pyRevit SelectFromList (вся логика: поиск, группы, флажки) в оформлении XYZ."""
    xaml_source = os.path.join(XAML_DIR, 'SelectFromList.xaml')

    def _setup(self, **kwargs):
        try:
            self.Resources.MergedDictionaries.Add(theme_dictionary())
        except Exception:
            pass
        _pf.SelectFromList._setup(self, **kwargs)
        try:
            adaptive(self, 'sfl')
        except Exception:
            pass
        try:
            self.xyz_title.Text = self.Title
            if kwargs.get('multiselect'):
                self.xyz_sub.Text = u'Отметь нужное флажками · поиск — просто начни печатать'
        except Exception:
            pass


# ------------------------------------------------------------------ список с порядком
def reorder_list(items, title=u'Порядок', prompt=None):
    """Окно «Вверх/Вниз» для задания порядка; возвращает новый список (или исходный при отмене)."""
    items = list(items)
    if len(items) < 2:
        return items
    dlg = _Dialog(title, width=520)
    if prompt:
        t = dlg.add_text(prompt, muted=True, size=12)
        t.Margin = Thickness(0, 0, 0, 8)
    g = Grid()
    c0 = ColumnDefinition()
    c0.Width = GridLength(1, GridUnitType.Star)
    c1 = ColumnDefinition()
    c1.Width = GridLength.Auto
    g.ColumnDefinitions.Add(c0)
    g.ColumnDefinitions.Add(c1)
    lb = ListBox()
    lb.Height = 380
    for it in items:
        lb.Items.Add(it)
    lb.SelectedIndex = 0
    g.Children.Add(lb)
    side = StackPanel()
    side.Margin = Thickness(10, 0, 0, 0)
    Grid.SetColumn(side, 1)

    def move(d):
        i = lb.SelectedIndex
        j = i + d
        if i < 0 or j < 0 or j >= lb.Items.Count:
            return
        it = lb.Items[i]
        lb.Items.RemoveAt(i)
        lb.Items.Insert(j, it)
        lb.SelectedIndex = j
        lb.ScrollIntoView(it)
    for txt, d in ((u'↑  Вверх', -1), (u'↓  Вниз', 1)):
        b = Button()
        b.Content = txt
        b.Margin = Thickness(0, 0, 0, 6)
        b.Click += (lambda dd: (lambda s, e: move(dd)))(d)
        side.Children.Add(b)
    g.Children.Add(side)
    dlg.body.Children.Add(g)
    dlg.add_button(u'Отмена', None, cancel=True)
    dlg.add_button(u'Готово', '__ok__', primary=True)
    adaptive(dlg, 'reorder')
    dlg.ShowDialog()
    if dlg.response == '__ok__':
        return [x for x in lb.Items]
    return items
