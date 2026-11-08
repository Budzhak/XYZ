# -*- coding: utf-8 -*-
"""Новогоднее оформление вкладки XYZ (db, 07.11.2026).

Значки не трогаем — украшаем сами панели:
  * фон панелей: гирлянда по верхнему краю, снежинки, сугроб внизу (lib/ny/ny_body_A.png / _B.png,
    240×160 — выше панели, поэтому по вертикали не повторяется); ёлочки — в полосе названий (ny_title_trees.png);
  * гирлянда мигает: картинки A и B меняются раз в BLINK_S секунд (одна замена кисти на панель — Revit не тормозит);
  * раз в SANTA_EVERY_S секунд, если открыта вкладка XYZ, над лентой пролетает Дед Мороз на санях
    (прозрачное окно поверх ленты, щелчки проходят сквозь него, ~5 с).
Включается сам с 15 декабря по 15 января. xyz_settings 'newyear': 'auto' (по умолчанию) | 'on' | 'off'.
Вызывается из startup.py: xyz_newyear.start(); при Reload старые таймеры останавливаются.
"""
import os
import math
import datetime
import traceback

import clr
from System import AppDomain, TimeSpan
from System.Collections import ArrayList
from System.IO import FileStream, FileMode, FileAccess, FileShare
from System.Windows import Window, WindowStyle, Rect, Point, SizeToContent, WindowStartupLocation
from System.Windows.Controls import Image
from System.Windows.Media import ImageBrush, TileMode, BrushMappingMode, AlignmentX, AlignmentY, Brushes, Stretch
from System.Windows.Media.Imaging import BitmapImage, BitmapCacheOption
from System.Windows.Threading import DispatcherTimer
from Autodesk.Windows import ComponentManager

HERE = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'ny')
TAB_ID = u'XYZ'
KEY = 'db_newyear_timers'
BLINK_S = 1.0
SANTA_EVERY_S = 300
SANTA_FLIGHT_S = 8.0
LOG = os.path.join(os.environ.get('TEMP', ''), 'zb_newyear.log')


def _log(msg):
    try:
        import io
        with io.open(LOG, 'a', encoding='utf-8') as f:
            f.write(u'%s %s\n' % (datetime.datetime.now().strftime('%d.%m %H:%M:%S'), msg))
    except Exception:
        pass


def is_on(today=None):
    mode = 'auto'
    try:
        import xyz_settings
        mode = (xyz_settings.get('newyear') or 'auto')
    except Exception:
        pass
    if mode == 'on':
        return True
    if mode == 'off':
        return False
    d = today or datetime.date.today()
    return (d.month == 12 and d.day >= 15) or (d.month == 1 and d.day <= 15)


def _bitmap(path):
    fs = FileStream(path, FileMode.Open, FileAccess.Read, FileShare.Read)
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


def _brush(path):
    bmp = _bitmap(path)
    b = ImageBrush(bmp)
    b.TileMode = TileMode.Tile
    b.Stretch = getattr(Stretch, 'None')
    b.ViewportUnits = BrushMappingMode.Absolute
    b.Viewport = Rect(0, 0, bmp.PixelWidth, bmp.PixelHeight)
    b.AlignmentX = AlignmentX.Left
    b.AlignmentY = AlignmentY.Top
    b.Freeze()
    return b


def _panels():
    rib = ComponentManager.Ribbon
    if rib is None:
        return []
    for t in rib.Tabs:
        if t.Id == TAB_ID:
            return list(t.Panels)
    return []


def stop():
    """Остановить таймеры и вернуть обычный вид панелей."""
    old = AppDomain.CurrentDomain.GetData(KEY)
    if old is not None:
        for tm in old:
            try:
                tm.Stop()
            except Exception:
                pass
        AppDomain.CurrentDomain.SetData(KEY, None)
    for p in _panels():
        try:
            p.CustomPanelBackground = None
            p.CustomPanelTitleBarBackground = None
        except Exception:
            pass


# ---------------------------------------------------------------- Дед Мороз
_santa = {'win': None, 't0': None, 'x0': 0, 'x1': 0, 'y': 0, 'timer': None}


def _ribbon_rect():
    rib = ComponentManager.Ribbon
    if rib is None or not rib.IsVisible:
        return None
    try:
        from System.Windows import PresentationSource
        src = PresentationSource.FromVisual(rib)
        m = src.CompositionTarget.TransformToDevice
        p = rib.PointToScreen(Point(0, 0))
        return (p.X / m.M11, p.Y / m.M22, rib.ActualWidth, rib.ActualHeight)
    except Exception:
        return None


def _click_through(win):
    try:
        import ctypes
        from System.Windows.Interop import WindowInteropHelper
        h = WindowInteropHelper(win).Handle.ToInt64()
        GWL_EXSTYLE = -20
        u = ctypes.windll.user32
        st = u.GetWindowLongW(ctypes.c_void_p(h), GWL_EXSTYLE)
        # WS_EX_TRANSPARENT | WS_EX_LAYERED | WS_EX_TOOLWINDOW | WS_EX_NOACTIVATE
        u.SetWindowLongW(ctypes.c_void_p(h), GWL_EXSTYLE, st | 0x20 | 0x80 | 0x08000000)
    except Exception:
        _log('click_through: ' + traceback.format_exc())


def _santa_tick(*args):
    w = _santa['win']
    if w is None:
        return
    k = (datetime.datetime.now() - _santa['t0']).total_seconds() / SANTA_FLIGHT_S
    if k >= 1.0:
        try:
            _santa['timer'].Stop()
            w.Close()
        except Exception:
            pass
        _santa['win'] = None
        return
    w.Left = _santa['x0'] + (_santa['x1'] - _santa['x0']) * k
    w.Top = _santa['y'] + 3 * math.sin(k * math.pi * 4)
    if not _santa.get('logged'):
        _santa['logged'] = True
        _log('santa tick ok: %s,%s aw=%s' % (w.Left, w.Top, w.ActualWidth))


def fly_santa(*args):
    try:
        if _santa['win'] is not None:
            return
        rib = ComponentManager.Ribbon
        if rib is None or rib.ActiveTab is None or rib.ActiveTab.Id != TAB_ID:
            return
        r = _ribbon_rect()
        if r is None:
            return
        x, y, wdt, hgt = r
        img = Image()
        img.Source = _bitmap(os.path.join(HERE, 'ny_santa@2x.png'))
        img.Width = 120
        img.Height = 32
        img.IsHitTestVisible = False
        win = Window()
        win.WindowStyle = getattr(WindowStyle, 'None')
        win.AllowsTransparency = True
        win.Background = Brushes.Transparent
        win.Topmost = True
        win.ShowInTaskbar = False
        win.ShowActivated = False
        win.Focusable = False
        win.IsHitTestVisible = False
        win.SizeToContent = SizeToContent.WidthAndHeight
        win.Content = img
        _santa['x0'] = x - 130
        _santa['x1'] = x + wdt + 10
        _santa['y'] = y - 8   # над строкой вкладок, кнопки не закрывает
        win.Left = _santa['x0']
        win.Top = _santa['y']
        win.SourceInitialized += lambda s, e: _click_through(s)
        win.Show()
        _santa['win'] = win
        _santa['logged'] = False
        _santa['t0'] = datetime.datetime.now()
        tm = _santa['timer']
        if tm is None:
            tm = DispatcherTimer()
            tm.Interval = TimeSpan.FromMilliseconds(30)
            tm.Tick += _santa_tick
            _santa['timer'] = tm
        tm.Start()
    except Exception:
        _log('santa: ' + traceback.format_exc())


# ---------------------------------------------------------------- старт
def start(force=False):
    stop()
    if not (force or is_on()):
        _log('off (season/setting)')
        return False
    try:
        brushes = [_brush(os.path.join(HERE, 'ny_body_A.png')), _brush(os.path.join(HERE, 'ny_body_B.png'))]
        title = _brush(os.path.join(HERE, 'ny_title_trees.png'))
        state = {'i': 0}

        def blink(*args):
            try:
                state['i'] ^= 1
                b = brushes[state['i']]
                for p in _panels():
                    p.CustomPanelBackground = b
                    if p.CustomPanelTitleBarBackground is not title:
                        p.CustomPanelTitleBarBackground = title
            except Exception:
                _log('blink: ' + traceback.format_exc())

        t1 = DispatcherTimer()
        t1.Interval = TimeSpan.FromSeconds(BLINK_S)
        t1.Tick += blink
        t1.Start()
        t2 = DispatcherTimer()
        t2.Interval = TimeSpan.FromSeconds(SANTA_EVERY_S)
        t2.Tick += fly_santa
        t2.Start()
        lst = ArrayList()
        lst.Add(t1)
        lst.Add(t2)
        AppDomain.CurrentDomain.SetData(KEY, lst)
        blink()
        _log('started')
        return True
    except Exception:
        _log('start: ' + traceback.format_exc())
        return False
