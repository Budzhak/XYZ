# -*- coding: utf-8 -*-
__title__ = u"Количество"
__author__ = u"db"
__doc__ = u"""Количество с запасом в ADSK_Количество / ADSK_Размер_Площадь — по правилам, которые вы видите и правите.

Шаг 1 «Где»: выделенное / активный вид / вся модель; рабочие наборы; здание по областям видимости.
Шаг 2 «Правила»: категория + условие → как считать → куда писать → запас %. Сверху вниз, первое подошедшее.
Шаг 3 «Проба»: «было → станет» по позициям и по элементам, вне рамок, здание ≠ рамка, без данных.
Пока не нажато «Применить», модель не меняется. Отмена — Ctrl+Z (одна транзакция).

Правила хранятся рядом с моделью: <имя файла модели>_XYZ_Количество.json. Код: lib/xyz_qty.py."""

import os
import io
import sys
import json

import clr
clr.AddReference('System.Data')
from System.Data import DataTable
import System
from System.Collections.Generic import List

from pyrevit import revit, DB
from Microsoft.Win32 import OpenFileDialog, SaveFileDialog
import xyz_forms as forms
sys.modules.pop('xyz_qty', None)
import xyz_qty as q

from System.Windows import (Thickness, Visibility, HorizontalAlignment, VerticalAlignment, FontWeights,
                            TextWrapping, GridLength, GridUnitType, ResizeMode, SizeToContent)
from System.Windows.Controls import (StackPanel, WrapPanel, TextBlock, CheckBox, RadioButton, ComboBox,
                                     ComboBoxItem, TextBox, Button, Grid, ColumnDefinition, Border,
                                     ScrollViewer, ScrollBarVisibility, Orientation, TabControl, TabItem,
                                     DataGrid, TextSearch)

doc = revit.doc
uidoc = revit.uidoc
B = forms._brush

st, RULES_PATH, FROM_FILE = q.load_settings(doc)
FRS = q.frames(doc)
SEL = list(uidoc.Selection.GetElementIds())
VIEW = doc.ActiveView
WS = []
if doc.IsWorkshared:
    for w in DB.FilteredWorksetCollector(doc).OfKind(DB.WorksetKind.UserWorkset):
        WS.append((w.Id.IntegerValue, w.Name))
    WS.sort(key=lambda x: x[1])

S = {'items': [], 'outside': [], 'mism': [], 'bycat': {}, 'res': None, 'pcache': {}, 'vcache': {}}


def rules_sig(rules):
    return json.dumps(rules, sort_keys=True, ensure_ascii=False)


S['saved'] = rules_sig(st['rules']) if FROM_FILE else None
S['path'] = RULES_PATH


# ------------------------------------------------------------------ мелочи интерфейса
def txt(t, bold=False, muted=False, size=None, wrap=True, margin=None):
    tb = TextBlock()
    tb.Text = t
    if bold:
        tb.FontWeight = FontWeights.SemiBold
        tb.Foreground = B(forms.GREEN)
    if muted:
        tb.Foreground = B(forms.MUTE)
    if size:
        tb.FontSize = size
    if wrap:
        tb.TextWrapping = TextWrapping.Wrap
    tb.Margin = margin or Thickness(0, 0, 0, 4)
    return tb


def btn(t, handler, primary=False, margin=None):
    b = Button()
    b.Content = t
    b.MinWidth = 80
    b.Margin = margin or Thickness(8, 0, 0, 0)
    b.Padding = Thickness(10, 3, 10, 3)
    if primary:
        b.IsDefault = True
    b.Click += handler
    return b


def combo(items, current, width, editable=False, tips=None):
    cb = ComboBox()
    cb.Width = width
    cb.IsEditable = editable
    cb.Margin = Thickness(0, 0, 4, 0)
    sel = None
    for it in items:
        if isinstance(it, tuple):
            key, label = it
        else:
            key, label = it, it
        ci = ComboBoxItem()
        ci.Content = label
        ci.Tag = key
        TextSearch.SetText(ci, key)
        cb.Items.Add(ci)
        if key == current:
            sel = ci
    if sel is None and current and not editable:
        ci = ComboBoxItem()
        ci.Content = current
        ci.Tag = current
        TextSearch.SetText(ci, current)
        cb.Items.Add(ci)
        sel = ci
    if sel is not None:
        cb.SelectedItem = sel
    elif editable:
        cb.Text = current or u''
    return cb


def cval(cb):
    it = cb.SelectedItem
    if it is not None:
        return it.Tag
    return (cb.Text or u'') if cb.IsEditable else None


def grid(widths):
    g = Grid()
    for w in widths:
        cd = ColumnDefinition()
        cd.Width = GridLength(1, GridUnitType.Star) if w == '*' else GridLength(w)
        g.ColumnDefinitions.Add(cd)
    return g


def put(g, el, col):
    Grid.SetColumn(el, col)
    g.Children.Add(el)


# ------------------------------------------------------------------ окно
dlg = forms._Dialog(u'Количество', width=1180)
dlg.ResizeMode = ResizeMode.CanResize
dlg.SizeToContent = SizeToContent.Manual
dlg.Height = 760
dlg.response = None


def set_footer(buttons):
    dlg.footer.Children.Clear()
    for b in buttons:
        dlg.footer.Children.Add(b)


def set_body(el, step):
    dlg.body.Children.Clear()
    dlg.body.Children.Add(el)
    dlg._s.Text = [u'Шаг 1 из 3 — где считать', u'Шаг 2 из 3 — правила', u'Шаг 3 из 3 — проба (модель ещё не менялась)'][step]
    dlg._s.Visibility = Visibility.Visible


def scroll(el, h):
    sv = ScrollViewer()
    sv.VerticalScrollBarVisibility = ScrollBarVisibility.Auto
    sv.HorizontalScrollBarVisibility = ScrollBarVisibility.Disabled
    sv.Height = h
    sv.Content = el
    return sv


# ================================================================== ШАГ 1
W1 = {}


def step1():
    p = StackPanel()
    p.Children.Add(txt(u'Какие элементы', bold=True))
    r_sel = RadioButton()
    r_sel.GroupName = 'qty_scope'
    r_sel.Content = u'Выделенные (%d эл.)' % len(SEL)
    r_sel.IsEnabled = len(SEL) > 0
    r_view = RadioButton()
    r_view.GroupName = 'qty_scope'
    r_view.Content = u'На активном виде «%s»' % VIEW.Name
    r_mod = RadioButton()
    r_mod.GroupName = 'qty_scope'
    r_mod.Content = u'Вся модель'
    sc = st.get('scope') or ('selection' if SEL else 'model')
    (r_sel if sc == 'selection' and SEL else (r_view if sc == 'view' else r_mod)).IsChecked = True
    for r in (r_sel, r_view, r_mod):
        r.Margin = Thickness(4, 2, 0, 2)
        p.Children.Add(r)
    W1['scope'] = (r_sel, r_view, r_mod)

    if WS:
        p.Children.Add(txt(u'Рабочие наборы (снимите лишние, например теплоснабжение или отверстия)', bold=True,
                           margin=Thickness(0, 12, 0, 4)))
        wp = WrapPanel()
        off = set(st.get('ws_off') or [])
        W1['ws'] = []
        for wid, wn in WS:
            cb = CheckBox()
            cb.Content = wn
            cb.IsChecked = wn not in off
            cb.Margin = Thickness(4, 2, 14, 2)
            wp.Children.Add(cb)
            W1['ws'].append((wn, cb))
        p.Children.Add(wp)

    p.Children.Add(txt(u'Здание — по областям видимости', bold=True, margin=Thickness(0, 12, 0, 4)))
    W1['frames'] = []
    if not FRS:
        p.Children.Add(txt(u'В модели нет областей видимости — здание не учитывается, считаются все элементы.', muted=True))
    saved = st.get('frames')
    for f in FRS:
        cb = CheckBox()
        cb.Content = u'%s   →   ADSK_Номер здания = «%s»' % (f['name'], f['building'])
        cb.IsChecked = (f['name'] in saved) if saved is not None else True
        cb.Margin = Thickness(4, 2, 0, 2)
        p.Children.Add(cb)
        W1['frames'].append((f, cb))
    p.Children.Add(txt(u'Считаются только элементы, центр которых внутри отмеченных рамок. Не отмечено ни одной — '
                       u'здание не учитывается.', muted=True, size=12, margin=Thickness(22, 2, 0, 4)))
    wb = CheckBox()
    wb.Content = u'Записать ADSK_Номер здания по рамкам (список — в пробе, там же можно отказаться)'
    wb.IsChecked = bool(st.get('write_building', True))
    wb.Margin = Thickness(4, 4, 0, 2)
    p.Children.Add(wb)
    W1['wb'] = wb

    p.Children.Add(txt(u'Прочее', bold=True, margin=Thickness(0, 12, 0, 4)))
    sk = CheckBox()
    sk.Content = u'Пропускать позиции, у которых наименование начинается с «!» («!Не учитывать…»)'
    sk.IsChecked = bool(st.get('skip_excl', True))
    sk.Margin = Thickness(4, 2, 0, 2)
    p.Children.Add(sk)
    W1['skip'] = sk

    p.Children.Add(txt(u'Режим', bold=True, margin=Thickness(0, 12, 0, 4)))
    m1 = RadioButton()
    m1.GroupName = 'qty_mode'
    m1.Content = u'Посчитать и показать пробу (записать — потом, кнопкой «Применить»)'
    m2 = RadioButton()
    m2.GroupName = 'qty_mode'
    m2.Content = u'Только проверить — ничего не пишет: вне рамок, здание ≠ рамка, без данных, что изменилось бы'
    m1.IsChecked = True
    for r in (m1, m2):
        r.Margin = Thickness(4, 2, 0, 2)
        p.Children.Add(r)
    W1['mode'] = (m1, m2)

    set_body(scroll(p, 560), 0)
    set_footer([btn(u'Отмена', lambda s, e: dlg.Close()), btn(u'Дальше →', go2, primary=True)])


def read1():
    r_sel, r_view, r_mod = W1['scope']
    st['scope'] = 'selection' if r_sel.IsChecked else ('view' if r_view.IsChecked else 'model')
    st['ws_off'] = [wn for wn, cb in W1.get('ws', []) if not cb.IsChecked]
    st['frames'] = [f['name'] for f, cb in W1['frames'] if cb.IsChecked]
    st['write_building'] = bool(W1['wb'].IsChecked)
    st['skip_excl'] = bool(W1['skip'].IsChecked)
    st['check_only'] = bool(W1['mode'][1].IsChecked)


def gather():
    els = q.collect(doc, st['scope'], VIEW.Id, SEL)
    off = set(st.get('ws_off') or [])
    if off and WS:
        names = dict(WS)
        els = [el for el in els if names.get(el.WorksetId.IntegerValue) not in off]
    chosen = [f['id'] for f in FRS if f['name'] in (st.get('frames') or [])]
    S['items'], S['outside'], S['mism'] = q.prepare(doc, els, FRS, chosen)
    S['ofix'] = q.outside_fix(doc, S['outside'], FRS) if chosen else []
    S['bycat'] = {}
    for el, f in S['items']:
        if el.Category is not None:
            S['bycat'].setdefault(q._iv(el.Category.Id), []).append(el)


def go2(s, e):
    read1()
    gather()
    step2()


# ================================================================== ШАГ 2
W2 = {'rows': []}
RULES = st['rules']


def cat_els(cat, host):
    els = S['bycat'].get(q.cat_id(cat), [])
    if host:
        hs = []
        seen = set()
        for el in els:
            h = q.host_of(doc, el)
            if h is not None and q._iv(h.Id) not in seen:
                seen.add(q._iv(h.Id))
                hs.append(h)
        return hs
    return els


def pnames(cat, host):
    k = (cat, host)
    if k not in S['pcache']:
        S['pcache'][k] = q.param_names(doc, cat_els(cat, host))
    return S['pcache'][k]


def pvalues(cat, host, param):
    k = (cat, host, param)
    if k not in S['vcache']:
        S['vcache'][k] = q.value_counts(doc, cat_els(cat, host), param)[:300]
    return S['vcache'][k]


def recount(*a):
    read2()
    cnt = q.match_counts(doc, S['items'], RULES)
    for i, row in enumerate(W2['rows']):
        row['count'].Text = u'%d' % cnt[i] if RULES[i].get('on') else u'—'
    stb = W2.get('status')
    if stb is not None:
        if S['saved'] is None:
            stb.Text = u'Файла правил ещё нет — в окне стандартные правила. «Сохранить» создаст файл: %s' % S['path']
            stb.Foreground = B(forms.MUTE)
        elif rules_sig(RULES) == S['saved']:
            stb.Text = u'Правила в окне совпадают с файлом: %s' % S['path']
            stb.Foreground = B(forms.GREEN)
        else:
            stb.Text = (u'Правила в окне изменены и НЕ сохранены в файл %s. Вернуть — «Вернуть из файла»; '
                        u'оставить эти — «Сохранить» или «Сохранить как…».' % S['path'])
            stb.Foreground = B(forms.RED)


def read2():
    for i, row in enumerate(W2['rows']):
        r = RULES[i]
        r['on'] = bool(row['on'].IsChecked)
        r['cat'] = cval(row['cat']) or r['cat']
        r['measure'] = cval(row['measure']) or r['measure']
        r['target'] = cval(row['target']) or r['target']
        try:
            r['reserve'] = float((row['res'].Text or u'0').replace(u',', u'.'))
        except Exception:
            r['reserve'] = 0.0
        conds = []
        for c in row['conds']:
            conds.append({'host': cval(c['src']) == 'host', 'param': cval(c['param']),
                          'op': cval(c['op']) or u'=', 'value': cval(c['val'])})
        r['conds'] = [c for c in conds if c['param']]


def rebuild(*a):
    step2()


def refresh(*a):
    read2()
    step2()


def cond_row(rule, c, i, j):
    sp = StackPanel()
    sp.Orientation = Orientation.Horizontal
    sp.Margin = Thickness(0, 0, 0, 3)
    src = combo([('self', u'элемент'), ('host', u'основа')], 'host' if c.get('host') else 'self', 80)
    par = combo(pnames(rule['cat'], c.get('host')), c.get('param'), 190)
    op = combo(q.OPS, c.get('op') or u'=', 100)
    vals = [(v, u'%s   (%d)' % (v or u'<пусто>', n)) for v, n in pvalues(rule['cat'], c.get('host'), c.get('param'))] \
        if c.get('param') else []
    val = combo(vals, c.get('value'), 150, editable=True)
    x = Button()
    x.Content = u'✕'
    x.ToolTip = u'Убрать условие'
    x.Padding = Thickness(6, 0, 6, 0)

    def on_param(s, e, i=i, j=j):
        read2()
        rebuild()

    def on_x(s, e, i=i, j=j):
        read2()
        del RULES[i]['conds'][j]
        rebuild()
    par.SelectionChanged += on_param
    src.SelectionChanged += on_param
    op.SelectionChanged += recount
    val.SelectionChanged += recount
    val.LostFocus += recount
    x.Click += on_x
    for w in (src, par, op, val, x):
        sp.Children.Add(w)
    return sp, {'src': src, 'param': par, 'op': op, 'val': val}


def rule_row(i, r):
    g = grid([30, 200, '*', 190, 190, 60, 70, 96])
    on = CheckBox()
    on.IsChecked = bool(r.get('on'))
    on.VerticalAlignment = VerticalAlignment.Top
    on.Margin = Thickness(4, 4, 0, 0)
    on.Click += recount
    put(g, on, 0)
    cat = combo([(k, n) for n, k in q.CATS], r['cat'], 192)

    def on_cat(s, e, i=i):
        read2()
        rebuild()
    cat.SelectionChanged += on_cat
    put(g, cat, 1)
    cp = StackPanel()
    conds = []
    for j, c in enumerate(r['conds']):
        sp, ctl = cond_row(r, c, i, j)
        cp.Children.Add(sp)
        conds.append(ctl)
    add = Button()
    add.Content = u'+ условие «и»' if r['conds'] else u'+ условие'
    add.HorizontalAlignment = HorizontalAlignment.Left
    add.Padding = Thickness(6, 0, 6, 0)

    def on_add(s, e, i=i):
        read2()
        RULES[i]['conds'].append({'host': False, 'param': u'', 'op': u'=', 'value': u''})
        rebuild()
    add.Click += on_add
    cp.Children.Add(add)
    put(g, cp, 2)
    me = combo(q.MEASURES, r['measure'], 182)
    me.SelectionChanged += recount
    put(g, me, 3)
    tg = combo(q.TARGETS, r['target'], 182)
    tg.SelectionChanged += recount
    put(g, tg, 4)
    rs = TextBox()
    rs.Text = (u'%g' % float(r.get('reserve') or 0))
    rs.Width = 50
    rs.VerticalAlignment = VerticalAlignment.Top
    rs.LostFocus += recount
    put(g, rs, 5)
    cn = txt(u'…', wrap=False)
    cn.HorizontalAlignment = HorizontalAlignment.Right
    cn.Margin = Thickness(0, 4, 8, 0)
    put(g, cn, 6)
    tools = StackPanel()
    tools.Orientation = Orientation.Horizontal
    for sym, tip, d in ((u'↑', u'Выше', -1), (u'↓', u'Ниже', 1), (u'✕', u'Удалить правило', 0)):
        b = Button()
        b.Content = sym
        b.ToolTip = tip
        b.Padding = Thickness(7, 0, 7, 0)
        b.Margin = Thickness(0, 0, 3, 0)

        def act(s, e, i=i, d=d):
            read2()
            if d == 0:
                del RULES[i]
            else:
                k = i + d
                if 0 <= k < len(RULES):
                    RULES[i], RULES[k] = RULES[k], RULES[i]
            rebuild()
        b.Click += act
        tools.Children.Add(b)
    tools.VerticalAlignment = VerticalAlignment.Top
    put(g, tools, 7)
    row = Border()
    row.Child = g
    row.Padding = Thickness(4, 6, 4, 6)
    row.BorderBrush = B(forms.LINE)
    row.BorderThickness = Thickness(0, 0, 0, 1)
    row.Background = B('#FFFFFF')
    return row, {'on': on, 'cat': cat, 'conds': conds, 'measure': me, 'target': tg, 'res': rs, 'count': cn}


def step2():
    p = StackPanel()
    hdr = grid([30, 200, '*', 190, 190, 60, 70, 96])
    for k, t in enumerate([u'', u'Категория', u'Условие', u'Как считать', u'Куда писать',
                           u'Запас, %', u'Поймано', u'']):
        put(hdr, txt(t, bold=True, wrap=False), k)
    hb = Border()
    hb.Child = hdr
    hb.Padding = Thickness(4, 4, 4, 4)
    hb.Background = B('#F2F2F2')
    p.Children.Add(hb)
    rows = StackPanel()
    W2['rows'] = []
    for i, r in enumerate(RULES):
        row, ctl = rule_row(i, r)
        rows.Children.Add(row)
        W2['rows'].append(ctl)
    p.Children.Add(scroll(rows, 380))
    tools = StackPanel()
    tools.Orientation = Orientation.Horizontal
    tools.Margin = Thickness(0, 8, 0, 6)

    def add_rule(s, e):
        read2()
        RULES.append({'on': True, 'cat': 'OST_DuctCurves', 'conds': [], 'measure': 'length',
                      'target': u'ADSK_Количество', 'reserve': 0.0})
        rebuild()

    def defaults(s, e):
        read2()
        if forms.alert(u'Правила в окне заменятся стандартными.\n\nФайл с сохранёнными правилами не изменится — '
                       u'вернуть их можно кнопкой «Вернуть из файла».\n\nЗаменить?', yes=True, no=True):
            del RULES[:]
            RULES.extend([dict(r, conds=[dict(c) for c in r['conds']]) for r in q.DEFAULT_RULES])
            step2()

    def take(path, ask=True):
        st2, path2, ff = q.load_settings(doc, path)
        if not ff:
            forms.alert(u'Не удалось прочитать файл правил:\n%s' % path2, title=u'Количество')
            return
        if ask and S['saved'] is not None and rules_sig(RULES) != S['saved'] and not forms.alert(
                u'Правила в окне изменены и не сохранены — заменить их правилами из файла?', yes=True, no=True):
            return
        del RULES[:]
        RULES.extend(st2['rules'])
        S['path'] = path2
        S['saved'] = rules_sig(RULES)
        q.remember_path(doc, path2)
        step2()

    def load_saved(s, e):
        read2()
        take(S['path'])

    def open_file(s, e):
        read2()
        d = OpenFileDialog()
        d.Title = u'Открыть файл правил «Количество»'
        d.Filter = u'Правила «Количество» (*.json)|*.json|Все файлы|*.*'
        d.InitialDirectory = os.path.dirname(S['path'])
        if d.ShowDialog(dlg) == True:
            take(d.FileName)

    def save_to(path):
        read2()
        path = q.save_settings(doc, st, path)
        S['path'] = path
        S['saved'] = rules_sig(RULES)
        step2()
        forms.alert(u'Правила сохранены в файл (модель не менялась):\n%s' % path, title=u'Количество')

    def save(s, e):
        save_to(S['path'])

    def save_as(s, e):
        d = SaveFileDialog()
        d.Title = u'Сохранить правила «Количество» как'
        d.Filter = u'Правила «Количество» (*.json)|*.json'
        d.InitialDirectory = os.path.dirname(S['path'])
        d.FileName = os.path.basename(S['path'])
        d.OverwritePrompt = True
        if d.ShowDialog(dlg) == True:
            save_to(d.FileName)
    tools.Children.Add(btn(u'+ Правило', add_rule, margin=Thickness(0, 0, 8, 0)))
    tools.Children.Add(btn(u'Открыть…', open_file, margin=Thickness(0, 0, 8, 0)))
    lb = btn(u'Вернуть из файла', load_saved, margin=Thickness(0, 0, 8, 0))
    lb.IsEnabled = os.path.exists(S['path'])
    tools.Children.Add(lb)
    tools.Children.Add(btn(u'Стандартные', defaults, margin=Thickness(0, 0, 8, 0)))
    tools.Children.Add(btn(u'Сохранить', save, margin=Thickness(0, 0, 8, 0)))
    tools.Children.Add(btn(u'Сохранить как…', save_as, margin=Thickness(0, 0, 8, 0)))
    p.Children.Add(tools)
    p.Children.Add(txt(u'Правила проверяются сверху вниз: для каждого параметра («Куда писать») элемент берёт первое '
                       u'подошедшее правило — поэтому частное («код = 23») ставьте выше общего. Условие: параметр — из тех, '
                       u'что есть у элементов категории (или у основы — для изоляции); значение — из тех, что есть в модели, '
                       u'в скобках — сколько элементов. Количество = замер × (1 + запас/100), округление до 0,01. '
                       u'Для изоляции «… основы + её запас»: замер основы × запас основы (по её правилу выше) × свой запас — '
                       u'медь +10 % и изоляция +20 % дадут 1,10 × 1,20 = 1,32 длины трубы.',
                       muted=True, size=12))
    sttb = txt(u'', size=12)
    W2['status'] = sttb
    p.Children.Add(sttb)
    p.Children.Add(txt(u'Элементов в расчёте: %d%s. Правила — это файл, а не модель: сохранять можно и в режиме '
                       u'«Только проверить». Файл можно выбрать свой («Открыть…», «Сохранить как…») — кнопка запомнит его '
                       u'для этой модели.' % (
                           len(S['items']), u' (режим «Только проверить»)' if st.get('check_only') else u''),
                       muted=True, size=12))
    set_body(p, 1)
    set_footer([btn(u'← Назад', lambda s, e: (read2(), step1())), btn(u'Отмена', lambda s, e: dlg.Close()),
                btn(u'Посчитать →', go3, primary=True)])
    recount()


def go3(s, e):
    read2()
    S['res'] = q.compute(doc, S['items'], RULES, st.get('skip_excl', True))
    step3()


# ================================================================== ШАГ 3
W3 = {}


def table(cols, rows):
    t = DataTable()
    for name, typ in cols:
        t.Columns.Add(name, {'i': System.Int64, 'f': System.Double}.get(typ, System.String))
    for r in rows:
        dr = t.NewRow()
        for k, (name, typ) in enumerate(cols):
            v = r[k]
            if v is None:
                dr[name] = System.DBNull.Value
            elif typ == 'i':
                dr[name] = System.Int64(v)
            elif typ == 'f':
                dr[name] = System.Double(v)
            else:
                dr[name] = v
        t.Rows.Add(dr)
    return t


def sysname(el):
    p = el.get_Parameter(DB.BuiltInParameter.RBS_SYSTEM_NAME_PARAM)
    return (p.AsString() or u'') if p is not None else u''


def lvname(el):
    try:
        lv = doc.GetElement(el.LevelId)
        return lv.Name if lv is not None else u''
    except Exception:
        return u''


def wsname(el):
    names = dict(WS)
    return names.get(el.WorksetId.IntegerValue, u'')


def catname(el):
    return el.Category.Name if el.Category is not None else u''


def show_ids(ids):
    try:
        lst = List[DB.ElementId]([DB.ElementId(System.Int64(i)) for i in ids])
        uidoc.Selection.SetElementIds(lst)
        uidoc.ShowElements(lst)
    except Exception:
        pass


def grid_view(t):
    dg = DataGrid()
    dg.IsReadOnly = True
    dg.AutoGenerateColumns = True
    dg.CanUserAddRows = False
    dg.Height = 420
    dg.ItemsSource = t.DefaultView

    def dbl(s, e):
        it = dg.SelectedItem
        if it is not None and t.Columns.Contains(u'Id'):
            v = it[u'Id']
            if v is not None and not isinstance(v, System.DBNull):
                show_ids([v])
    dg.MouseDoubleClick += dbl
    return dg


def step3():
    res = S['res']
    ch_by = {}
    for ch in res['changes']:
        name, t = ch[1], ch[2]
        ch_by[(name, t)] = ch_by.get((name, t), 0) + 1
    summ = []
    for (name, t, unit), (n, a, b) in res['totals'].items():
        if (name, t) in ch_by:
            summ.append((name, t, unit, n, ch_by[(name, t)], round(a, 2), round(b, 2), round(b - a, 2)))
    summ.sort(key=lambda r: -abs(r[7]))
    tabs = []
    tabs.append((u'Итог по позициям (%d)' % len(summ), table(
        [(u'Позиция', 's'), (u'Параметр', 's'), (u'Ед', 's'), (u'Элементов', 'i'), (u'Изменится', 'i'),
         (u'Было', 'f'), (u'Станет', 'f'), (u'Δ', 'f')], summ)))
    tabs.append((u'Элементы (%d)' % len(res['changes']), table(
        [(u'Id', 'i'), (u'Категория', 's'), (u'Наименование', 's'), (u'Параметр', 's'), (u'Было', 'f'),
         (u'Станет', 'f'), (u'Правило №', 'i'), (u'Как посчитано', 's')],
        [(q._iv(el.Id), catname(el), name, t, (round(old, 3) if old is not None else None), new, i + 1, note)
         for el, name, t, old, new, i, note in res['changes']])))
    if FRS and st.get('frames'):
        tabs.append((u'Здание ≠ рамка (%d)' % len(S['mism']), table(
            [(u'Id', 'i'), (u'Категория', 's'), (u'Наименование', 's'), (u'Сейчас', 's'), (u'По рамке', 's'),
             (u'Рамка', 's'), (u'Рабочий набор', 's'), (u'Система', 's'), (u'Уровень', 's')],
            [(q._iv(el.Id), catname(el), q.pstr(doc, el, q.NAME_PARAM), cur, f['building'], f['name'], wsname(el),
              sysname(el), lvname(el)) for el, cur, f in S['mism']])))
        fx = dict((q._iv(el.Id), new) for el, cur, new in S['ofix'])
        tabs.append((u'Вне рамок (%d)' % len(S['outside']), table(
            [(u'Id', 'i'), (u'Категория', 's'), (u'Наименование', 's'), (u'Здание', 's'), (u'Станет', 's'),
             (u'Уровень', 's'), (u'Система', 's')],
            [(q._iv(el.Id), catname(el), q.pstr(doc, el, q.NAME_PARAM), q.pstr(doc, el, q.BUILDING_PARAM),
              (fx.get(q._iv(el.Id), u'—') or u'<пусто>'), lvname(el), sysname(el)) for el in S['outside']])))
    tabs.append((u'Без данных (%d)' % len(res['nodata']), table(
        [(u'Id', 'i'), (u'Категория', 's'), (u'Наименование', 's'), (u'Параметр', 's'), (u'Причина', 's')],
        [(q._iv(el.Id), catname(el), name, t, why) for el, name, t, why in res['nodata']])))
    tabs.append((u'Без правила (%d)' % len(res['norule']), table(
        [(u'Id', 'i'), (u'Категория', 's'), (u'Наименование', 's')],
        [(q._iv(el.Id), catname(el), name) for el, name in res['norule']])))

    p = StackPanel()
    tc = TabControl()
    W3['tabs'] = []
    for title, t in tabs:
        ti = TabItem()
        ti.Header = title
        ti.Content = grid_view(t)
        tc.Items.Add(ti)
        W3['tabs'].append((title, t))
    W3['tc'] = tc
    p.Children.Add(tc)
    p.Children.Add(txt(u'Без изменений (значение уже такое): %d. Двойной щелчок по строке — выделить и показать элемент '
                       u'в модели. «В Excel» — текущая вкладка.' % res['same'], muted=True, size=12,
                       margin=Thickness(0, 6, 0, 6)))
    co = st.get('check_only')
    wq = CheckBox()
    wq.Content = u'Записать количество — %d значений' % len(res['changes'])
    wq.IsChecked = (not co) and bool(res['changes'])
    wq.IsEnabled = (not co) and bool(res['changes'])
    p.Children.Add(wq)
    wbld = CheckBox()
    nb = len(S['mism']) if (st.get('write_building') and st.get('frames')) else 0
    wbld.Content = u'Записать ADSK_Номер здания по рамкам — %d эл. (вкладка «Здание ≠ рамка»)' % nb
    wbld.IsChecked = (not co) and nb > 0
    wbld.IsEnabled = (not co) and nb > 0
    p.Children.Add(wbld)
    wo = CheckBox()
    no = len(S.get('ofix') or []) if st.get('write_building') else 0
    wo.Content = (u'Убрать ADSK_Номер здания у элементов вне рамок — %d эл. (вкладка «Вне рамок», столбец «Станет»: '
                  u'здание другой рамки или пусто)' % no)
    wo.IsChecked = (not co) and no > 0
    wo.IsEnabled = (not co) and no > 0
    p.Children.Add(wo)
    if co:
        p.Children.Add(txt(u'Режим «Только проверить» — запись выключена.', muted=True, size=12))
    W3['wq'], W3['wb'], W3['wo'] = wq, wbld, wo
    set_body(p, 2)

    def to_excel(s, e):
        i = tc.SelectedIndex if tc.SelectedIndex >= 0 else 0
        title, t = W3['tabs'][i]
        path = os.path.join(os.environ.get('TEMP', u'.'), u'XYZ_Количество_%d.csv' % i)
        lines = [u';'.join(c.ColumnName for c in t.Columns)]
        for r in t.Rows:
            vals = []
            for c in t.Columns:
                v = r[c.ColumnName]
                v = u'' if isinstance(v, System.DBNull) else (u'%s' % v)
                vals.append(v.replace(u';', u',').replace(u'.', u',') if c.DataType == System.Double else v.replace(u';', u','))
            lines.append(u';'.join(vals))
        with io.open(path, 'w', encoding='utf-8-sig') as f:
            f.write(u'\r\n'.join(lines))
        try:
            os.startfile(path)
        except Exception:
            forms.alert(path, title=u'Сохранено')

    def do_apply(s, e):
        if not (wq.IsChecked or wbld.IsChecked or wo.IsChecked):
            return
        dlg.response = 'apply'
        dlg.Close()
    ap = btn(u'Применить', do_apply, primary=True)
    ap.IsEnabled = not co
    set_footer([btn(u'← Назад', lambda s, e: step2()), btn(u'В Excel', to_excel), btn(u'Отмена', lambda s, e: dlg.Close()),
                ap])


# ================================================================== запуск
step1()
forms.adaptive(dlg, 'qty')
dlg.ShowDialog()

if dlg.response == 'apply':
    res = S['res']
    ch = res['changes'] if W3['wq'].IsChecked else []
    mm = S['mism'] if W3['wb'].IsChecked else []
    fx = S['ofix'] if W3['wo'].IsChecked else []
    with revit.Transaction(u'XYZ: количество'):
        nv, nb, ne = q.apply(doc, ch, mm, fx)
    try:
        q.save_settings(doc, st, S['path'])
    except Exception:
        pass
    forms.alert(u'Записано значений количества: %d\nЗдание записано: %d эл.\nНе удалось записать: %d\n\n'
                u'Отмена — Ctrl+Z («XYZ: количество»).' % (nv, nb, ne), title=u'Количество')
