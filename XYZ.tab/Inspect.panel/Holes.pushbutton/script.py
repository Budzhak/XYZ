# -*- coding: utf-8 -*-
__title__ = u"Отверстия"
__author__ = u"db"
__doc__ = u"""Задания на отверстия: где свои сети (воздуховоды, трубы, кабельные лотки) проходят сквозь стены,
перекрытия и крыши из связей (IFC и RVT).

1) Где: выделенное / активный вид / вся модель; какие сети, какие конструкции, какие связи.
2) Запасы: круглое D + 100 мм, прямоугольное + 50 мм с каждой стороны (меняются в окне), изоляция,
   объединение близких отверстий в одной конструкции.
3) «Найти» — таблица: конструкция, толщина, этаж, размер сети, размер отверстия, отметки, координаты.
   Щелчок по строке — выделить сети, двойной щелчок — показать на виде. «В Excel» — вся таблица.
В модели ничего не создаётся и не меняется. Код: lib/xyz_holes.py."""

import os
import sys
import datetime

import clr
clr.AddReference('System.Data')
from System.Data import DataTable
import System
from System.Collections.Generic import List

from pyrevit import revit, DB
from Microsoft.Win32 import SaveFileDialog
import xyz_forms as forms
import xyz_settings
sys.modules.pop('xyz_holes', None)
import xyz_holes as H

from System.Windows import (Thickness, Visibility, VerticalAlignment, FontWeights, TextWrapping, GridLength,
                            GridUnitType, ResizeMode, SizeToContent, CornerRadius)
from System.Windows.Controls import (StackPanel, WrapPanel, TextBlock, CheckBox, RadioButton, TextBox, Button, Grid,
                                     RowDefinition, Border, Orientation, DataGrid, DataGridTextColumn,
                                     DataGridSelectionMode, DataGridLength, DockPanel)
from System.Windows.Data import Binding

TITLE = u'Отверстия'
KEY = 'holes'
doc = revit.doc
uidoc = revit.uidoc
B = forms._brush

OPT = dict(H.DEFAULTS)
try:
    OPT.update(xyz_settings.get(KEY) or {})
except Exception:
    pass
if OPT.get('scope') == 'selection' and not list(uidoc.Selection.GetElementIds()):
    OPT['scope'] = 'view'
LINKS = H.links(doc)
S = {'rows': [], 'stats': None, 'by_n': {}}


def guarded(fn):
    """Ошибка в обработчике — окном, а не «нажал — ничего»."""
    def wrap(s, e):
        try:
            return fn(s, e)
        except Exception as ex:
            try:
                import traceback
                msg = traceback.format_exc()
            except Exception:
                msg = u'%s' % ex
            status(u'Ошибка: %s' % ex, bad=True)
            forms.alert(u'Не получилось:\n%s' % msg, title=TITLE)
    return wrap


# ------------------------------------------------------------------ мелочи интерфейса
def txt(t, bold=False, muted=False, size=None, margin=None):
    tb = TextBlock()
    tb.Text = t
    if bold:
        tb.FontWeight = FontWeights.SemiBold
        tb.Foreground = B(forms.GREEN)
    if muted:
        tb.Foreground = B(forms.MUTE)
    if size:
        tb.FontSize = size
    tb.TextWrapping = TextWrapping.Wrap
    tb.Margin = margin or Thickness(0, 0, 0, 4)
    return tb


def btn(t, handler, primary=False, tip=None):
    b = Button()
    b.Content = t
    b.MinWidth = 90
    b.Margin = Thickness(8, 0, 0, 0)
    b.Padding = Thickness(12, 4, 12, 4)
    if primary:
        b.IsDefault = True
    if tip:
        b.ToolTip = tip
    b.Click += handler
    return b


def check(t, on, tip=None, enabled=True):
    cb = CheckBox()
    cb.Content = t
    cb.IsChecked = bool(on)
    cb.IsEnabled = enabled
    cb.Margin = Thickness(0, 0, 0, 4)
    if tip:
        cb.ToolTip = tip
    return cb


def radio(t, group, on):
    rb = RadioButton()
    rb.Content = t
    rb.GroupName = group
    rb.IsChecked = bool(on)
    rb.Margin = Thickness(0, 0, 0, 4)
    return rb


def num(panel, before, value, after, tip=None):
    """Строка «текст [число] текст»; возвращает поле."""
    sp = StackPanel()
    sp.Orientation = Orientation.Horizontal
    sp.Margin = Thickness(0, 0, 0, 4)
    a = TextBlock()
    a.Text = before
    a.VerticalAlignment = VerticalAlignment.Center
    sp.Children.Add(a)
    tb = TextBox()
    tb.Text = (u'%g' % value).replace(u'.', u',')
    tb.Width = 54
    tb.MinHeight = 24
    tb.Margin = Thickness(6, 0, 6, 0)
    tb.VerticalContentAlignment = VerticalAlignment.Center
    sp.Children.Add(tb)
    c = TextBlock()
    c.Text = after
    c.VerticalAlignment = VerticalAlignment.Center
    c.Foreground = B(forms.MUTE)
    sp.Children.Add(c)
    if tip:
        sp.ToolTip = tip
    panel.Children.Add(sp)
    return tb


def fval(tb, default):
    try:
        v = float((tb.Text or u'').strip().replace(u',', u'.'))
        return v if v >= 0 else default
    except Exception:
        return default


def card(title):
    bd = Border()
    bd.Background = B('#FFFFFF')
    bd.BorderBrush = B(forms.LINE)
    bd.BorderThickness = Thickness(1)
    bd.CornerRadius = CornerRadius(10)
    bd.Padding = Thickness(12, 8, 12, 6)
    bd.Margin = Thickness(0, 0, 8, 8)
    sp = StackPanel()
    sp.Children.Add(txt(title, bold=True))
    bd.Child = sp
    return bd, sp


# ------------------------------------------------------------------ окно
dlg = forms._Dialog(TITLE, width=1240)
dlg.ResizeMode = ResizeMode.CanResize
dlg.SizeToContent = SizeToContent.Manual
dlg.Height = 780
dlg._s.Text = u'Сети сквозь стены, перекрытия и крыши связей. Только поиск: модель не меняется.'
dlg._s.Visibility = Visibility.Visible

W = {}
top = WrapPanel()

# --- где
bd, sp = card(u'Где искать')
n_sel = len(list(uidoc.Selection.GetElementIds()))
W['sel'] = radio(u'Выделенное (%d)' % n_sel, 'scope', OPT['scope'] == 'selection')
W['sel'].IsEnabled = n_sel > 0
W['view'] = radio(u'Активный вид', 'scope', OPT['scope'] == 'view')
W['view'].ToolTip = doc.ActiveView.Name
W['model'] = radio(u'Вся модель', 'scope', OPT['scope'] == 'model')
for k in ('sel', 'view', 'model'):
    sp.Children.Add(W[k])
top.Children.Add(bd)

# --- сети
bd, sp = card(u'Сети')
for key, _, label in H.NETS:
    W[key] = check({u'Воздуховод': u'Воздуховоды', u'Гибкий воздуховод': u'Гибкие воздуховоды', u'Труба': u'Трубы',
                    u'Кабельный лоток': u'Кабельные лотки'}[label], OPT.get(key))
    sp.Children.Add(W[key])
top.Children.Add(bd)

# --- конструкции и связи
bd, sp = card(u'Конструкции из связей')
row = StackPanel()
row.Orientation = Orientation.Horizontal
for key, label in (('walls', u'Стены'), ('floors', u'Перекрытия'), ('roofs', u'Крыши')):
    W[key] = check(label, OPT.get(key))
    W[key].Margin = Thickness(0, 0, 14, 4)
    row.Children.Add(W[key])
sp.Children.Add(row)
W['links'] = []
want = OPT.get('links')
off = []
for l in LINKS:
    total = sum(l['counts'].values()) if l['loaded'] else 0
    if not l['loaded']:
        off.append(l['name'])
        continue
    if not total:
        continue
    cb = check(u'%s — стен %d, перекрытий %d, крыш %d' % (l['name'], l['counts'].get('walls', 0),
               l['counts'].get('floors', 0), l['counts'].get('roofs', 0)), want is None or l['id'] in want)
    cb.Tag = l['id']
    W['links'].append(cb)
    sp.Children.Add(cb)
if not W['links']:
    sp.Children.Add(txt(u'Загруженных связей со стенами и перекрытиями нет.', muted=True, size=12))
if off:
    t = txt(u'Не загружены (не проверяются): %d' % len(off), muted=True, size=11)
    t.ToolTip = u'\n'.join(off)
    sp.Children.Add(t)
top.Children.Add(bd)

# --- запасы
bd, sp = card(u'Размер отверстия')
W['round_add'] = num(sp, u'Круглое: D +', OPT['round_add'], u'мм')
W['rect_add'] = num(sp, u'Прямоугольное: +', OPT['rect_add'], u'мм с каждой стороны')
W['round_to'] = num(sp, u'Округлять вверх до', OPT['round_to'], u'мм (0 — нет)')
W['insulation'] = check(u'Размер сети — с изоляцией', OPT.get('insulation'))
sp.Children.Add(W['insulation'])
top.Children.Add(bd)

bd, sp = card(u'Объединение и отсев')
W['merge'] = num(sp, u'Объединять ближе', OPT['merge'], u'мм (0 — нет)',
                 u'Отверстия в одной конструкции с просветом меньше этого сливаются в одно прямоугольное. '
                 u'Так же склеиваются слои одной стены.')
W['max_len'] = num(sp, u'Вдоль: в теле больше', OPT['max_len'], u'мм',
                   u'Сеть, ось которой идёт внутри конструкции дольше этого (труба в стяжке, стояк в стене), — не отверстие.')
W['min_size'] = num(sp, u'Сети мельче', OPT['min_size'], u'мм не показывать')
W['skip_along'] = check(u'Не показывать сети вдоль конструкций', OPT.get('skip_along'),
                        u'Снять — такие строки появятся в таблице с пометкой в «Примечании».')
sp.Children.Add(W['skip_along'])
top.Children.Add(bd)

# --- таблица
dg = DataGrid()
dg.IsReadOnly = True
dg.AutoGenerateColumns = False
dg.CanUserAddRows = False
dg.SelectionMode = DataGridSelectionMode.Extended
dg.MinHeight = 160
dg.HeadersVisibility = System.Windows.Controls.DataGridHeadersVisibility.Column
for key, title, typ in H.COLUMNS:
    c = DataGridTextColumn()
    c.Header = title
    c.Binding = Binding(key)
    if key in ('sname', 'smat', 'system', 'note', 'ids', 'sid'):
        c.MaxWidth = 260
    dg.Columns.Add(c)

st_tb = TextBlock()
st_tb.TextWrapping = TextWrapping.Wrap
st_tb.Margin = Thickness(0, 6, 0, 0)
st_tb.FontSize = 12
st_tb.Foreground = B(forms.MUTE)
st_tb.Text = (u'Задайте, где искать, и нажмите «Найти». Щелчок по строке — выделить сети, двойной щелчок — показать '
              u'на виде. Заголовок столбца — сортировка. Ctrl+колесо — масштаб окна.')


def status(t, bad=False, good=False):
    st_tb.Text = t
    st_tb.Foreground = B(forms.RED if bad else (forms.GREEN if good else forms.MUTE))


g = Grid()
g.Margin = Thickness(18, 12, 18, 10)
for h in (GridLength.Auto, GridLength(1, GridUnitType.Star), GridLength.Auto):
    rd = RowDefinition()
    rd.Height = h
    g.RowDefinitions.Add(rd)
for i, el in enumerate((top, dg, st_tb)):
    Grid.SetRow(el, i)
    g.Children.Add(el)
root = dlg.Content
root.Children.Remove(dlg.body)
root.Children.Add(g)          # последний ребёнок DockPanel занимает всё оставшееся место


# ------------------------------------------------------------------ действия
def read_opt():
    o = dict(OPT)
    o['scope'] = 'selection' if W['sel'].IsChecked else ('model' if W['model'].IsChecked else 'view')
    for k in ('ducts', 'flex', 'pipes', 'trays', 'walls', 'floors', 'roofs', 'insulation', 'skip_along'):
        o[k] = bool(W[k].IsChecked)
    for k in ('round_add', 'rect_add', 'round_to', 'merge', 'max_len', 'min_size'):
        o[k] = fval(W[k], H.DEFAULTS[k])
    o['links'] = [cb.Tag for cb in W['links'] if cb.IsChecked]
    return o


def fill(rows):
    t = DataTable()
    for key, title, typ in H.COLUMNS:
        t.Columns.Add(key, System.Int64 if typ == 'i' else System.String)
    for r in rows:
        dr = t.NewRow()
        for key, title, typ in H.COLUMNS:
            v = r.get(key)
            if v is None:
                dr[key] = System.DBNull.Value
            elif typ == 'i':
                dr[key] = System.Int64(v)
            else:
                dr[key] = v
        t.Rows.Add(dr)
    dg.ItemsSource = t.DefaultView


def do_find(s, e):
    o = read_opt()
    if not o['links']:
        status(u'Не отмечена ни одна связь с конструкциями.', bad=True)
        return
    rows, st = H.find(doc, uidoc, o)
    S['rows'], S['stats'] = rows, st
    S['by_n'] = dict((r['n'], r) for r in rows)
    fill(rows)
    status(H.summary(st), good=bool(rows))
    try:
        xyz_settings.set(KEY, o)
    except Exception:
        pass


def picked_ids(all_if_none=False):
    ids = []
    items = list(dg.SelectedItems)
    if not items and all_if_none:
        items = list(dg.Items)
    for it in items:
        try:
            r = S['by_n'].get(int(it['n']))
        except Exception:
            r = None
        if r:
            for i in r['elids']:
                if i not in ids:
                    ids.append(i)
    return ids


def select(ids, show=False):
    lst = List[DB.ElementId]([DB.ElementId(System.Int64(i)) for i in ids])
    uidoc.Selection.SetElementIds(lst)
    if show and ids:
        uidoc.ShowElements(lst)


def on_sel(s, e):
    ids = picked_ids()
    if ids:
        select(ids)


def on_dbl(s, e):
    ids = picked_ids()
    if ids:
        select(ids, show=True)


def to_excel(s, e):
    if not S['rows']:
        status(u'Сначала «Найти» — таблица пустая.', bad=True)
        return
    d = SaveFileDialog()
    d.Title = u'Отверстия — сохранить таблицу'
    d.Filter = u'Таблица CSV для Excel (*.csv)|*.csv'
    d.FileName = u'%s_Отверстия_%s.csv' % (doc.Title, datetime.datetime.now().strftime('%Y-%m-%d'))
    if d.ShowDialog(dlg) != True:
        return
    H.to_csv(S['rows'], d.FileName)
    status(u'Сохранено: %s' % d.FileName, good=True)
    try:
        os.startfile(d.FileName)
    except Exception:
        pass


def do_select(s, e):
    ids = picked_ids(all_if_none=True)
    if not ids:
        status(u'Нечего выделять: сначала «Найти».', bad=True)
        return
    select(ids)
    dlg.Close()


dg.SelectionChanged += guarded(on_sel)
dg.MouseDoubleClick += guarded(on_dbl)
dlg.footer.Children.Clear()
for b in (btn(u'В Excel', guarded(to_excel), tip=u'Вся таблица — в файл CSV, откроется в Excel'),
          btn(u'Выделить на виде', guarded(do_select),
              tip=u'Выделить сети отмеченных строк (если ничего не отмечено — всех) и закрыть окно'),
          btn(u'Закрыть', lambda s, e: dlg.Close()),
          btn(u'Найти', guarded(do_find), primary=True)):
    dlg.footer.Children.Add(b)

forms.adaptive(dlg, KEY, min_w=900, min_h=520)
dlg.ShowDialog()
