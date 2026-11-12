# -*- coding: utf-8 -*-
__title__ = u"Наименования"
__author__ = u"db"
__doc__ = u"""ADSK_Наименование по шаблонам, которые вы видите и правите; там же — db_Раздел и ключ сортировки.

Шаг 1 «Где»: выделенное / активный вид / вся модель; рабочие наборы; здание по областям видимости.
Шаг 2 «Правила»: категория + условие → шаблон. Сверху вниз, первое подошедшее. Вкладки «Таблицы»
(толщина стали, стенка меди) и «Разделы и порядок».
Шаг 3 «Проба»: «было → станет». Пока не нажато «Применить», модель не меняется. Отмена — Ctrl+Z.

Шаблон: {Параметр}, {основа: Параметр}, {макс: A; B}, {Параметр | округл 5 | таблица …}, [необязательно].
Наименования с «!» не трогаются. Правила — файл, который вы выбираете. Код: lib/xyz_naim.py."""

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
sys.modules.pop('xyz_naim', None)
import xyz_qty as q
import xyz_naim as n

from System.Windows import (Thickness, Visibility, HorizontalAlignment, VerticalAlignment, FontWeights,
                            TextWrapping, GridLength, GridUnitType, ResizeMode, SizeToContent)
from System.Windows.Controls import (StackPanel, WrapPanel, TextBlock, CheckBox, RadioButton, ComboBox,
                                     ComboBoxItem, TextBox, Button, Grid, ColumnDefinition, Border,
                                     ScrollViewer, ScrollBarVisibility, Orientation, TabControl, TabItem,
                                     DataGrid, TextSearch, DataGridEditingUnit)
from System.Windows.Media import FontFamily

doc = revit.doc
uidoc = revit.uidoc
B = forms._brush

st, RULES_PATH, FROM_FILE = n.load_settings(doc)
FRS = q.frames(doc)
SEL = list(uidoc.Selection.GetElementIds())
VIEW = doc.ActiveView
WS = []
if doc.IsWorkshared:
    for w in DB.FilteredWorksetCollector(doc).OfKind(DB.WorksetKind.UserWorkset):
        WS.append((w.Id.IntegerValue, w.Name))
    WS.sort(key=lambda x: x[1])

S = {'items': [], 'outside': [], 'mism': [], 'bycat': {}, 'res': None, 'pcache': {}, 'vcache': {}, 'excache': {},
     'tab': 0, 'table': None}
S['saved'] = n.sig(st) if FROM_FILE else None
S['path'] = RULES_PATH
RULES = st['rules']
MONO = FontFamily(u'Consolas')


# ------------------------------------------------------------------ мелочи интерфейса
def txt(t, bold=False, muted=False, size=None, wrap=True, margin=None, color=None):
    tb = TextBlock()
    tb.Text = t
    if bold:
        tb.FontWeight = FontWeights.SemiBold
        tb.Foreground = B(forms.GREEN)
    if muted:
        tb.Foreground = B(forms.MUTE)
    if color:
        tb.Foreground = B(color)
    if size:
        tb.FontSize = size
    if wrap:
        tb.TextWrapping = TextWrapping.Wrap
    tb.Margin = margin or Thickness(0, 0, 0, 4)
    return tb


def btn(t, handler, primary=False, margin=None, tip=None):
    b = Button()
    b.Content = t
    b.MinWidth = 80
    b.Margin = margin or Thickness(8, 0, 0, 0)
    b.Padding = Thickness(10, 3, 10, 3)
    if tip:
        b.ToolTip = tip
    if primary:
        b.IsDefault = True
    b.Click += handler
    return b


def combo(items, current, width, editable=False):
    cb = ComboBox()
    cb.Width = width
    cb.IsEditable = editable
    cb.Margin = Thickness(0, 0, 4, 0)
    sel = None
    for it in items:
        key, label = it if isinstance(it, tuple) else (it, it)
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


def hpanel(margin=None):
    sp = StackPanel()
    sp.Orientation = Orientation.Horizontal
    if margin:
        sp.Margin = margin
    return sp


def scroll(el, h):
    sv = ScrollViewer()
    sv.VerticalScrollBarVisibility = ScrollBarVisibility.Auto
    sv.HorizontalScrollBarVisibility = ScrollBarVisibility.Disabled
    sv.Height = h
    sv.Content = el
    return sv


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


def rows_of(t):
    out = []
    for r in t.Rows:
        try:
            if r.RowState == System.Data.DataRowState.Deleted:
                continue
        except Exception:
            pass
        vals = []
        for c in t.Columns:
            v = r[c.ColumnName]
            vals.append(u'' if isinstance(v, System.DBNull) or v is None else (u'%s' % v).strip())
        if any(vals):
            out.append(vals)
    return out


def commit(dg):
    try:
        dg.CommitEdit(DataGridEditingUnit.Cell, True)
        dg.CommitEdit(DataGridEditingUnit.Row, True)
    except Exception:
        pass


# ------------------------------------------------------------------ окно
dlg = forms._Dialog(u'Наименования', width=1240)
dlg.ResizeMode = ResizeMode.CanResize
dlg.SizeToContent = SizeToContent.Manual
dlg.Height = 820
dlg.response = None


def set_footer(buttons):
    dlg.footer.Children.Clear()
    for b in buttons:
        dlg.footer.Children.Add(b)


def set_body(el, step):
    dlg.body.Children.Clear()
    dlg.body.Children.Add(el)
    dlg._s.Text = [u'Шаг 1 из 3 — где', u'Шаг 2 из 3 — правила', u'Шаг 3 из 3 — проба (модель ещё не менялась)'][step]
    dlg._s.Visibility = Visibility.Visible


# ================================================================== ШАГ 1
W1 = {}


def step1():
    p = StackPanel()
    p.Children.Add(txt(u'Какие элементы', bold=True))
    r_sel = RadioButton()
    r_sel.GroupName = 'naim_scope'
    r_sel.Content = u'Выделенные (%d эл.)' % len(SEL)
    r_sel.IsEnabled = len(SEL) > 0
    r_view = RadioButton()
    r_view.GroupName = 'naim_scope'
    r_view.Content = u'На активном виде «%s»' % VIEW.Name
    r_mod = RadioButton()
    r_mod.GroupName = 'naim_scope'
    r_mod.Content = u'Вся модель'
    sc = st.get('scope') or ('selection' if SEL else 'model')
    (r_sel if sc == 'selection' and SEL else (r_view if sc == 'view' else r_mod)).IsChecked = True
    for r in (r_sel, r_view, r_mod):
        r.Margin = Thickness(4, 2, 0, 2)
        p.Children.Add(r)
    W1['scope'] = (r_sel, r_view, r_mod)

    if WS:
        p.Children.Add(txt(u'Рабочие наборы (снимите лишние)', bold=True, margin=Thickness(0, 12, 0, 4)))
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
        p.Children.Add(txt(u'В модели нет областей видимости — здание не учитывается.', muted=True))
    saved = st.get('frames')
    for f in FRS:
        cb = CheckBox()
        cb.Content = u'%s   →   «%s»' % (f['name'], f['building'])
        cb.IsChecked = (f['name'] in saved) if saved is not None else True
        cb.Margin = Thickness(4, 2, 0, 2)
        p.Children.Add(cb)
        W1['frames'].append((f, cb))
    p.Children.Add(txt(u'Берутся только элементы, центр которых внутри отмеченных рамок. Не отмечено ни одной — '
                       u'все. ADSK_Номер здания эта кнопка не пишет — это делает «Количество».',
                       muted=True, size=12, margin=Thickness(22, 2, 0, 4)))

    p.Children.Add(txt(u'Режим', bold=True, margin=Thickness(0, 12, 0, 4)))
    m1 = RadioButton()
    m1.GroupName = 'naim_mode'
    m1.Content = u'Посчитать и показать пробу (записать — потом, кнопкой «Применить»)'
    m2 = RadioButton()
    m2.GroupName = 'naim_mode'
    m2.Content = u'Только проверить — ничего не пишет'
    m1.IsChecked = True
    for r in (m1, m2):
        r.Margin = Thickness(4, 2, 0, 2)
        p.Children.Add(r)
    W1['mode'] = (m1, m2)
    p.Children.Add(txt(u'Наименования, которые начинаются с «!» («!Не учитывать…»), не трогаются никогда.',
                       muted=True, size=12, margin=Thickness(0, 12, 0, 4)))
    set_body(scroll(p, 600), 0)
    set_footer([btn(u'Отмена', lambda s, e: dlg.Close()), btn(u'Дальше →', go2, primary=True)])


def read1():
    r_sel, r_view, r_mod = W1['scope']
    st['scope'] = 'selection' if r_sel.IsChecked else ('view' if r_view.IsChecked else 'model')
    st['ws_off'] = [wn for wn, cb in W1.get('ws', []) if not cb.IsChecked]
    st['frames'] = [f['name'] for f, cb in W1['frames'] if cb.IsChecked]
    st['check_only'] = bool(W1['mode'][1].IsChecked)


def gather():
    els = q.collect(doc, st['scope'], VIEW.Id, SEL, [k for nm, k in n.CATS])
    off = set(st.get('ws_off') or [])
    if off and WS:
        names = dict(WS)
        els = [el for el in els if names.get(el.WorksetId.IntegerValue) not in off]
    chosen = [f['id'] for f in FRS if f['name'] in (st.get('frames') or [])]
    S['items'], S['outside'], S['mism'] = q.prepare(doc, els, FRS, chosen)
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
        names = q.param_names(doc, cat_els(cat, host))
        if u'Категория' not in names:
            names = sorted(names + [u'Категория'])
        S['pcache'][k] = names
    return S['pcache'][k]


def pvalues(cat, host, param):
    k = (cat, host, param)
    if k not in S['vcache']:
        els = cat_els(cat, host)
        if param == u'Категория':
            d = {}
            for el in els:
                v = el.Category.Name if el.Category is not None else u''
                d[v] = d.get(v, 0) + 1
            S['vcache'][k] = sorted(d.items(), key=lambda kv: -kv[1])
        else:
            S['vcache'][k] = q.value_counts(doc, els, param)[:300]
    return S['vcache'][k]


def examples(cat, host):
    """{параметр: значение у первого элемента категории (или его основы)}."""
    k = (cat, host)
    if k not in S['excache']:
        els = cat_els(cat, host)
        S['excache'][k] = n.examples(doc, els[0], pnames(cat, host)) if els else {}
    return S['excache'][k]


def short(s, k=70):
    s = s or u''
    return s if len(s) <= k else s[:k - 1] + u'…'


def status_line():
    stb = W2.get('status')
    if stb is None:
        return
    if S['saved'] is None:
        stb.Text = u'Файла правил ещё нет — в окне стандартные правила. «Сохранить» создаст файл: %s' % S['path']
        stb.Foreground = B(forms.MUTE)
    elif n.sig(st) == S['saved']:
        stb.Text = u'Правила в окне совпадают с файлом: %s' % S['path']
        stb.Foreground = B(forms.GREEN)
    else:
        stb.Text = (u'Правила в окне изменены и НЕ сохранены в файл %s. Вернуть — «Вернуть из файла»; '
                    u'оставить эти — «Сохранить» или «Сохранить как…».' % S['path'])
        stb.Foreground = B(forms.RED)


def recount(*a):
    read2()
    cnt, ex = n.scan(doc, S['items'], RULES, st['tables'])
    for i, row in enumerate(W2['rows']):
        r = RULES[i]
        row['count'].Text = (u'%d' % cnt[i]) if r.get('on') else u'—'
        exb = row['ex']
        err = None if r.get('keep') else n.check(r.get('tpl') or u'', st['tables'])
        if not r.get('on'):
            exb.Text, c = u'правило выключено', forms.MUTE
        elif err:
            exb.Text, c = u'Ошибка в шаблоне: ' + err, forms.RED
        elif ex[i] is None:
            exb.Text, c = u'Не поймано ни одного элемента (или их поймало правило выше).', forms.MUTE
        else:
            el, old, new, why = ex[i]
            if r.get('keep'):
                exb.Text, c = u'не менять — пример (Id %d): «%s»' % (q._iv(el.Id), short(old, 110)), forms.MUTE
            elif new is None:
                exb.Text, c = u'Пример (Id %d): «%s» → не сработал: %s' % (q._iv(el.Id), short(old), why), forms.RED
            elif new == old:
                exb.Text, c = u'Пример (Id %d): «%s» — уже так' % (q._iv(el.Id), short(new, 110)), forms.GREEN
            else:
                exb.Text, c = u'Пример (Id %d): «%s»  →  «%s»' % (q._iv(el.Id), short(old, 60), short(new, 80)), '#E65100'
        exb.Foreground = B(c)
    status_line()


def read_rules():
    for i, row in enumerate(W2['rows']):
        r = RULES[i]
        r['on'] = bool(row['on'].IsChecked)
        r['cat'] = cval(row['cat']) or r['cat']
        r['keep'] = bool(row['keep'].IsChecked)
        r['tpl'] = row['tpl'].Text or u''
        conds = []
        for c in row['conds']:
            conds.append({'host': cval(c['src']) == 'host', 'param': cval(c['param']),
                          'op': cval(c['op']) or u'=', 'value': cval(c['val'])})
        r['conds'] = [c for c in conds if c['param']]


def read_tables():
    cur = W2.get('tbl')
    if cur is None:
        return
    name, t, dg = cur
    commit(dg)
    if name in st['tables']:
        st['tables'][name] = [[(r[0] if len(r) > 0 else u''), (r[1] if len(r) > 1 else u'')] for r in rows_of(t)]


def read_sections():
    sec = W2.get('sec')
    if sec is None:
        return
    t1, dg1, t2, dg2, eq = sec
    commit(dg1)
    commit(dg2)
    st['sections'] = [[r[0], r[1] if len(r) > 1 else u'', r[2] if len(r) > 2 else u''] for r in rows_of(t1)]
    by_name = dict((nm, k) for nm, k in n.CATS)
    cc = []
    for r in rows_of(t2):
        k = by_name.get(r[0])
        if k and len(r) > 1 and r[1]:
            cc.append([k, r[1]])
    st['cat_codes'] = cc
    st['eq_order'] = [x.strip() for x in (eq.Text or u'').replace(u';', u',').split(u',') if x.strip()]


def read2():
    read_rules()
    read_tables()
    read_sections()


def rebuild(*a):
    step2()


def insert_at_caret(tb, token):
    t = tb.Text or u''
    i = tb.CaretIndex
    if i < 0 or i > len(t):
        i = len(t)
    if token.startswith(u' |') and i > 0 and t[i - 1] == u'}':
        i -= 1
    tb.Text = t[:i] + token + t[i:]
    tb.Focus()
    tb.CaretIndex = i + len(token)


def cond_row(rule, c, i, j):
    sp = hpanel(Thickness(0, 0, 0, 3))
    src = combo([('self', u'элемент'), ('host', u'основа')], 'host' if c.get('host') else 'self', 80)
    par = combo(pnames(rule['cat'], c.get('host')), c.get('param'), 190)
    op = combo(n.OPS, c.get('op') or u'=', 100)
    vals = [(v, u'%s   (%d)' % (v or u'<пусто>', k)) for v, k in pvalues(rule['cat'], c.get('host'), c.get('param'))] \
        if c.get('param') else []
    val = combo(vals, c.get('value'), 170, editable=True)
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


def param_combo(rule, tb):
    """«+ параметр»: параметры элемента (и основы — для изоляции) с примером значения."""
    items = []
    ex = examples(rule['cat'], False)
    for nm in pnames(rule['cat'], False):
        v = ex.get(nm)
        items.append((u'{%s}' % nm, u'%s   = %s' % (nm, short(v, 40)) if v else nm))
    if rule['cat'] in ('OST_DuctInsulations', 'OST_PipeInsulations'):
        exh = examples(rule['cat'], True)
        for nm in pnames(rule['cat'], True):
            v = exh.get(nm)
            items.append((u'{основа: %s}' % nm, u'основа: %s   = %s' % (nm, short(v, 40)) if v else u'основа: ' + nm))
    cb = combo(items, None, 230)
    cb.ToolTip = u'Вставить параметр в шаблон (в место курсора). Справа — значение у первого элемента категории.'

    def on_sel(s, e):
        it = cb.SelectedItem
        if it is None:
            return
        insert_at_caret(tb, it.Tag)
        cb.SelectedIndex = -1
        recount()
    cb.SelectionChanged += on_sel
    return cb


def mod_combo(tb):
    items = [(u' | ' + m if not m.startswith(u'таблица') else None, u'%s — %s' % (m, h)) for m, h in n.MOD_HELP]
    items = [it for it in items if it[0]]
    for name in sorted(st['tables']):
        items.append((u' | таблица ' + name, u'таблица %s' % name))
    items.append((u'{макс: Ширина; Высота}', u'{макс: A; B} — большее из значений'))
    items.append((u'{мин: Ширина; Высота}', u'{мин: A; B} — меньшее из значений'))
    items.append((u'[, {Параметр}]', u'[ … ] — необязательный кусок: выпадает, если параметр пустой'))
    cb = combo(items, None, 200)
    cb.ToolTip = u'Вставить модификатор: курсор сразу после «}» — модификатор встанет внутрь скобок.'

    def on_sel(s, e):
        it = cb.SelectedItem
        if it is None:
            return
        insert_at_caret(tb, it.Tag)
        cb.SelectedIndex = -1
        recount()
    cb.SelectionChanged += on_sel
    return cb


RW = [30, 210, '*', 70, 96]


def rule_row(i, r):
    outer = StackPanel()
    g = grid(RW)
    on = CheckBox()
    on.IsChecked = bool(r.get('on'))
    on.VerticalAlignment = VerticalAlignment.Top
    on.Margin = Thickness(4, 4, 0, 0)
    on.ToolTip = u'Правило %d' % (i + 1)
    on.Click += recount
    put(g, on, 0)
    cat = combo([(k, nm) for nm, k in n.CATS], r['cat'], 202)

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
    cn = txt(u'…', wrap=False)
    cn.HorizontalAlignment = HorizontalAlignment.Right
    cn.Margin = Thickness(0, 4, 8, 0)
    put(g, cn, 3)
    tools = hpanel()
    for sym, tip, d in ((u'↑', u'Выше', -1), (u'↓', u'Ниже', 1), (u'⧉', u'Копия правила ниже', 2),
                        (u'✕', u'Удалить правило', 0)):
        b = Button()
        b.Content = sym
        b.ToolTip = tip
        b.Padding = Thickness(5, 0, 5, 0)
        b.Margin = Thickness(0, 0, 2, 0)

        def act(s, e, i=i, d=d):
            read2()
            if d == 0:
                del RULES[i]
            elif d == 2:
                RULES.insert(i + 1, json.loads(json.dumps(RULES[i], ensure_ascii=False)))
            else:
                k = i + d
                if 0 <= k < len(RULES):
                    RULES[i], RULES[k] = RULES[k], RULES[i]
            rebuild()
        b.Click += act
        tools.Children.Add(b)
    tools.VerticalAlignment = VerticalAlignment.Top
    put(g, tools, 4)
    outer.Children.Add(g)

    line = hpanel(Thickness(34, 4, 0, 0))
    line.Children.Add(txt(u'Шаблон:', wrap=False, margin=Thickness(0, 3, 6, 0)))
    tb = TextBox()
    tb.Text = r.get('tpl') or u''
    tb.Width = 600
    tb.FontFamily = MONO
    tb.LostFocus += recount
    keep = CheckBox()
    keep.Content = u'не менять'
    keep.ToolTip = u'Правило ловит элементы, но наименование не трогает (например, штанообразные тройники)'
    keep.IsChecked = bool(r.get('keep'))
    keep.Margin = Thickness(0, 3, 8, 0)

    def on_keep(s, e):
        tb.IsEnabled = not keep.IsChecked
        recount()
    keep.Click += on_keep
    tb.IsEnabled = not keep.IsChecked
    line.Children.Add(keep)
    line.Children.Add(tb)
    line.Children.Add(txt(u'  + ', wrap=False, margin=Thickness(4, 3, 2, 0)))
    line.Children.Add(param_combo(r, tb))
    line.Children.Add(mod_combo(tb))
    outer.Children.Add(line)
    exb = txt(u'', size=12, margin=Thickness(34, 3, 0, 0))
    outer.Children.Add(exb)

    row = Border()
    row.Child = outer
    row.Padding = Thickness(4, 6, 4, 6)
    row.BorderBrush = B(forms.LINE)
    row.BorderThickness = Thickness(0, 0, 0, 1)
    row.Background = B('#FFFFFF')
    return row, {'on': on, 'cat': cat, 'conds': conds, 'tpl': tb, 'keep': keep, 'count': cn, 'ex': exb}


def tab_rules():
    p = StackPanel()
    hdr = grid(RW)
    for k, t in enumerate([u'', u'Категория', u'Условие (все — «и»)', u'Поймано', u'']):
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
    p.Children.Add(scroll(rows, 400))

    def add_rule(s, e):
        read2()
        RULES.append({'on': True, 'cat': 'OST_DuctCurves', 'conds': [], 'tpl': u'', 'keep': False})
        rebuild()
    bar = hpanel(Thickness(0, 6, 0, 4))
    bar.Children.Add(btn(u'+ Правило', add_rule, margin=Thickness(0, 0, 8, 0)))
    p.Children.Add(bar)
    p.Children.Add(txt(
        u'Шаблон: {Параметр} — значение как в «Свойствах» (длины в мм, углы в градусах, без единиц); '
        u'{основа: Параметр} — у основы изоляции; {макс: A; B}, {мин: A; B}; модификаторы через «|»: '
        u'округл 5, без знака, целое, половина, первый, х, запятая, таблица <Имя>; [ … ] — кусок выпадает, если в нём '
        u'пустой параметр. Сами скобки — {{ }} [[ ]]. Пустой обязательный параметр — правило не сработает (вкладка '
        u'«Шаблон не сработал» в пробе). Если-то в шаблоне нет: другой вариант — отдельное правило с условием, выше общего.',
        muted=True, size=12))
    return p


def tab_tables():
    p = StackPanel()
    p.Children.Add(txt(u'Таблица подстановки: «таблица <Имя>» в шаблоне берёт первую строку, где значение ≤ «До» '
                       u'(если «До» — число), или где «До» равно значению (если текст).', muted=True, size=12))
    names = sorted(st['tables'])
    if S['table'] not in st['tables']:
        S['table'] = names[0] if names else None
    top = hpanel(Thickness(0, 4, 0, 6))
    top.Children.Add(txt(u'Таблица:', wrap=False, margin=Thickness(0, 3, 6, 0)))
    cb = combo(names, S['table'], 260)

    def on_sel(s, e):
        read2()
        S['table'] = cval(cb)
        S['tab'] = 1
        rebuild()
    cb.SelectionChanged += on_sel
    top.Children.Add(cb)
    nm = TextBox()
    nm.Width = 200
    nm.ToolTip = u'Имя новой таблицы'
    top.Children.Add(txt(u'   Новая:', wrap=False, margin=Thickness(0, 3, 6, 0)))
    top.Children.Add(nm)

    def new_t(s, e):
        read2()
        name = (nm.Text or u'').strip()
        if not name or u'|' in name or u'}' in name:
            forms.alert(u'Введите имя таблицы (без «|» и «}»).', title=u'Наименования')
            return
        st['tables'].setdefault(name, [])
        S['table'] = name
        S['tab'] = 1
        rebuild()

    def del_t(s, e):
        read2()
        if S['table'] and forms.alert(u'Удалить таблицу «%s» из правил?' % S['table'], yes=True, no=True):
            st['tables'].pop(S['table'], None)
            S['table'] = None
            S['tab'] = 1
            rebuild()
    top.Children.Add(btn(u'Создать', new_t))
    top.Children.Add(btn(u'Удалить таблицу', del_t, margin=Thickness(24, 0, 0, 0)))
    p.Children.Add(top)
    W2['tbl'] = None
    if S['table']:
        t = table([(u'До', 's'), (u'Значение', 's')], [[(r[0] if r else u''), (r[1] if len(r) > 1 else u'')]
                                                        for r in st['tables'][S['table']]])
        dg = DataGrid()
        dg.AutoGenerateColumns = True
        dg.CanUserAddRows = True
        dg.Height = 380
        dg.Width = 420
        dg.HorizontalAlignment = HorizontalAlignment.Left
        dg.ItemsSource = t.DefaultView
        dg.LostFocus += lambda s, e: status_line_safe()
        p.Children.Add(dg)
        W2['tbl'] = (S['table'], t, dg)
        used = [i + 1 for i, r in enumerate(RULES) if (u'таблица ' + S['table']) in (r.get('tpl') or u'')]
        p.Children.Add(txt(u'Используется в правилах: %s. Строки — по возрастанию «До»; удалить строку — выделить и Delete.'
                           % (u', '.join(u'%d' % k for k in used) or u'нигде'), muted=True, size=12,
                           margin=Thickness(0, 6, 0, 0)))
    return p


def status_line_safe():
    try:
        read_tables()
        read_sections()
        status_line()
    except Exception:
        pass


def tab_sections():
    p = StackPanel()
    p.Children.Add(txt(u'Раздел ведомости (db_Раздел) и единица — по коду db_Категория. Единица пишется, только если '
                       u'db_Единица измерения пустая. Код 25 (изоляция труб) — по основе: дренаж (код основы 23/24 или '
                       u'рабочий набор db_Дренаж) → раздел кода 23, иначе — кода 21.', muted=True, size=12))
    g = grid(['*', 20, 360])
    left = StackPanel()
    t1 = table([(u'Код', 's'), (u'Раздел', 's'), (u'Единица', 's')], st.get('sections') or [])
    dg1 = DataGrid()
    dg1.AutoGenerateColumns = True
    dg1.CanUserAddRows = True
    dg1.Height = 330
    dg1.ItemsSource = t1.DefaultView
    dg1.LostFocus += lambda s, e: status_line_safe()
    left.Children.Add(dg1)
    put(g, left, 0)
    right = StackPanel()
    right.Children.Add(txt(u'Код, если db_Категория пустая', bold=True))
    t2 = table([(u'Категория', 's'), (u'Код', 's')],
               [[n.CAT_NAME.get(r[0], r[0]), r[1]] for r in (st.get('cat_codes') or [])])
    dg2 = DataGrid()
    dg2.AutoGenerateColumns = True
    dg2.CanUserAddRows = True
    dg2.Height = 170
    dg2.ItemsSource = t2.DefaultView
    dg2.LostFocus += lambda s, e: status_line_safe()
    right.Children.Add(dg2)
    right.Children.Add(txt(u'Категория — как в списке категорий правил.', muted=True, size=11))
    right.Children.Add(txt(u'Порядок наружных блоков в «1. Оборудование»', bold=True, margin=Thickness(0, 8, 0, 4)))
    eq = TextBox()
    eq.Text = u', '.join(st.get('eq_order') or [])
    eq.LostFocus += lambda s, e: status_line_safe()
    right.Children.Add(eq)
    right.Children.Add(txt(u'Через запятую, по вхождению в ADSK_Имя устройства. Порядок раздела: вентустановки по '
                           u'db_Позиция → наружные блоки LG в этом порядке → внутренние блоки и гидромодули → прочее LG → '
                           u'остальное по коду.', muted=True, size=11))
    put(g, right, 2)
    p.Children.Add(g)
    p.Children.Add(txt(u'Ключ сортировки db_Сортировка = «код|наименование|марка» (раздел 1 — по порядку выше). Ключ, '
                       u'заданный вручную (не по этой формуле), не трогается — он во вкладке пробы «Ключ вручную».',
                       muted=True, size=12, margin=Thickness(0, 8, 0, 0)))
    W2['sec'] = (t1, dg1, t2, dg2, eq)
    return p


def step2():
    W2['tbl'] = None
    W2['sec'] = None
    p = StackPanel()
    tc = TabControl()
    for title, build in ((u'Наименования', tab_rules), (u'Таблицы', tab_tables), (u'Разделы и порядок', tab_sections)):
        ti = TabItem()
        ti.Header = title
        ti.Content = build()
        tc.Items.Add(ti)
    tc.SelectedIndex = S.get('tab', 0)

    def on_tab(s, e):
        if e.OriginalSource is tc:
            S['tab'] = tc.SelectedIndex
            try:
                recount()
            except Exception:
                pass
    tc.SelectionChanged += on_tab
    p.Children.Add(tc)

    tools = hpanel(Thickness(0, 8, 0, 4))

    def defaults(s, e):
        read2()
        if forms.alert(u'Правила, таблицы и разделы в окне заменятся стандартными.\n\nФайл с сохранёнными правилами '
                       u'не изменится — вернуть их можно кнопкой «Вернуть из файла».\n\nЗаменить?', yes=True, no=True):
            d = n.default_settings()
            del RULES[:]
            RULES.extend(d['rules'])
            for k in ('tables', 'sections', 'cat_codes', 'eq_order'):
                st[k] = d[k]
            step2()

    def take(path, ask=True):
        st2, path2, ff = n.load_settings(doc, path)
        if not ff:
            forms.alert(u'Не удалось прочитать файл правил:\n%s' % path2, title=u'Наименования')
            return
        if ask and S['saved'] is not None and n.sig(st) != S['saved'] and not forms.alert(
                u'Правила в окне изменены и не сохранены — заменить их правилами из файла?', yes=True, no=True):
            return
        del RULES[:]
        RULES.extend(st2['rules'])
        for k in ('tables', 'sections', 'cat_codes', 'eq_order'):
            st[k] = st2[k]
        S['path'] = path2
        S['saved'] = n.sig(st)
        n.remember_path(doc, path2)
        step2()

    def load_saved(s, e):
        read2()
        take(S['path'])

    def open_file(s, e):
        read2()
        d = OpenFileDialog()
        d.Title = u'Открыть файл правил «Наименования»'
        d.Filter = u'Правила «Наименования» (*.json)|*.json|Все файлы|*.*'
        d.InitialDirectory = os.path.dirname(S['path'])
        if d.ShowDialog(dlg) == True:
            take(d.FileName)

    def save_to(path):
        read2()
        path = n.save_settings(doc, st, path)
        S['path'] = path
        S['saved'] = n.sig(st)
        step2()
        forms.alert(u'Правила сохранены в файл (модель не менялась):\n%s' % path, title=u'Наименования')

    def save(s, e):
        save_to(S['path'])

    def save_as(s, e):
        read2()
        d = SaveFileDialog()
        d.Title = u'Сохранить правила «Наименования» как'
        d.Filter = u'Правила «Наименования» (*.json)|*.json'
        d.InitialDirectory = os.path.dirname(S['path'])
        d.FileName = os.path.basename(S['path'])
        d.OverwritePrompt = True
        if d.ShowDialog(dlg) == True:
            save_to(d.FileName)
    tools.Children.Add(btn(u'Открыть…', open_file, margin=Thickness(0, 0, 8, 0)))
    lb = btn(u'Вернуть из файла', load_saved, margin=Thickness(0, 0, 8, 0))
    lb.IsEnabled = os.path.exists(S['path'])
    tools.Children.Add(lb)
    tools.Children.Add(btn(u'Стандартные', defaults, margin=Thickness(0, 0, 8, 0)))
    tools.Children.Add(btn(u'Сохранить', save, margin=Thickness(0, 0, 8, 0)))
    tools.Children.Add(btn(u'Сохранить как…', save_as, margin=Thickness(0, 0, 8, 0)))
    p.Children.Add(tools)
    sttb = txt(u'', size=12)
    W2['status'] = sttb
    p.Children.Add(sttb)
    p.Children.Add(txt(u'Элементов в расчёте: %d%s. В файле — все три вкладки; сохранять можно и в режиме «Только '
                       u'проверить». Файл можно выбрать свой — кнопка запомнит его для этой модели.' % (
                           len(S['items']), u' (режим «Только проверить»)' if st.get('check_only') else u''),
                       muted=True, size=12))
    set_body(p, 1)
    set_footer([btn(u'← Назад', lambda s, e: (read2(), step1())), btn(u'Отмена', lambda s, e: dlg.Close()),
                btn(u'Посчитать →', go3, primary=True)])
    recount()


def go3(s, e):
    read2()
    S['res'] = n.compute(doc, S['items'], RULES, st['tables'])
    S['sec'], S['manual'] = n.compute_sections(doc, S['items'], st, S['res']['new_name'])
    step3()


# ================================================================== ШАГ 3
W3 = {}


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
    dg.Height = 470
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
    grp = {}
    for el, old, new, i in res['changes']:
        k = (old, new, i)
        grp[k] = grp.get(k, 0) + 1
    summ = sorted([(old, new, c, i + 1) for (old, new, i), c in grp.items()], key=lambda r: (-r[2], r[0]))
    tabs = []
    tabs.append((u'Итог: было → станет (%d)' % len(summ), table(
        [(u'Было', 's'), (u'Станет', 's'), (u'Элементов', 'i'), (u'Правило №', 'i')], summ)))
    tabs.append((u'Элементы (%d)' % len(res['changes']), table(
        [(u'Id', 'i'), (u'Категория', 's'), (u'Было', 's'), (u'Станет', 's'), (u'Правило №', 'i')],
        [(q._iv(el.Id), catname(el), old, new, i + 1) for el, old, new, i in res['changes']])))
    tabs.append((u'Шаблон не сработал (%d)' % len(res['fail']), table(
        [(u'Id', 'i'), (u'Категория', 's'), (u'Наименование', 's'), (u'Правило №', 'i'), (u'Причина', 's')],
        [(q._iv(el.Id), catname(el), old, i + 1, why) for el, old, i, why in res['fail']])))
    tabs.append((u'Без правила (%d)' % len(res['norule']), table(
        [(u'Id', 'i'), (u'Категория', 's'), (u'Наименование', 's'), (u'Семейство', 's'), (u'Тип', 's')],
        [(q._iv(el.Id), catname(el), old, q.pstr(doc, el, u'Семейство'), q.pstr(doc, el, u'Тип'))
         for el, old in res['norule']])))
    tabs.append((u'Разделы и сортировка (%d)' % len(S['sec']), table(
        [(u'Id', 'i'), (u'Категория', 's'), (u'Наименование', 's'), (u'Параметр', 's'), (u'Было', 's'), (u'Станет', 's')],
        [(q._iv(el.Id), catname(el), nm, par, old, new) for el, nm, par, old, new in S['sec']])))
    tabs.append((u'Ключ вручную (%d)' % len(S['manual']), table(
        [(u'Id', 'i'), (u'Категория', 's'), (u'Наименование', 's'), (u'Ключ сейчас', 's'), (u'По формуле', 's')],
        [(q._iv(el.Id), catname(el), nm, cur, key) for el, nm, cur, key in S['manual']])))
    if FRS and st.get('frames'):
        tabs.append((u'Вне рамок (%d)' % len(S['outside']), table(
            [(u'Id', 'i'), (u'Категория', 's'), (u'Наименование', 's'), (u'Здание', 's')],
            [(q._iv(el.Id), catname(el), q.pstr(doc, el, n.NAME_PARAM), q.pstr(doc, el, q.BUILDING_PARAM))
             for el in S['outside']])))

    p = StackPanel()
    tc = TabControl()
    W3['tabs'] = []
    for title, t in tabs:
        ti = TabItem()
        ti.Header = title
        ti.Content = grid_view(t)
        tc.Items.Add(ti)
        W3['tabs'].append((title, t))
    p.Children.Add(tc)
    p.Children.Add(txt(u'Уже так: %d. «Не менять»: %d. С «!»: %d. Двойной щелчок по строке — показать элемент. '
                       u'«В Excel» — текущая вкладка.' % (res['same'], res['kept'], res['excl']),
                       muted=True, size=12, margin=Thickness(0, 6, 0, 6)))
    co = st.get('check_only')
    wn = CheckBox()
    wn.Content = u'Записать наименования — %d эл.' % len(res['changes'])
    wn.IsChecked = (not co) and bool(res['changes'])
    wn.IsEnabled = (not co) and bool(res['changes'])
    p.Children.Add(wn)
    ws = CheckBox()
    ws.Content = u'Записать разделы, единицы, коды и ключи сортировки — %d значений' % len(S['sec'])
    ws.IsChecked = (not co) and bool(S['sec'])
    ws.IsEnabled = (not co) and bool(S['sec'])
    p.Children.Add(ws)
    if co:
        p.Children.Add(txt(u'Режим «Только проверить» — запись выключена.', muted=True, size=12))
    W3['wn'], W3['ws'] = wn, ws
    set_body(p, 2)

    def to_excel(s, e):
        i = tc.SelectedIndex if tc.SelectedIndex >= 0 else 0
        title, t = W3['tabs'][i]
        path = os.path.join(os.environ.get('TEMP', u'.'), u'XYZ_Наименования_%d.csv' % i)
        lines = [u';'.join(c.ColumnName for c in t.Columns)]
        for r in t.Rows:
            vals = []
            for c in t.Columns:
                v = r[c.ColumnName]
                v = u'' if isinstance(v, System.DBNull) else (u'%s' % v)
                vals.append(v.replace(u';', u','))
            lines.append(u';'.join(vals))
        with io.open(path, 'w', encoding='utf-8-sig') as f:
            f.write(u'\r\n'.join(lines))
        try:
            os.startfile(path)
        except Exception:
            forms.alert(path, title=u'Сохранено')

    def do_apply(s, e):
        if not (wn.IsChecked or ws.IsChecked):
            return
        dlg.response = 'apply'
        dlg.Close()
    ap = btn(u'Применить', do_apply, primary=True)
    ap.IsEnabled = not co
    set_footer([btn(u'← Назад', lambda s, e: step2()), btn(u'В Excel', to_excel), btn(u'Отмена', lambda s, e: dlg.Close()),
                ap])


# ================================================================== запуск
step1()
forms.adaptive(dlg, 'naim')
dlg.ShowDialog()

if dlg.response == 'apply':
    res = S['res']
    ch = res['changes'] if W3['wn'].IsChecked else []
    sec = []
    if W3['ws'].IsChecked:
        # ключи сортировки — по тем наименованиям, которые реально будут в модели
        sec = S['sec'] if ch else n.compute_sections(doc, S['items'], st, {})[0]
    with revit.Transaction(u'XYZ: наименования'):
        nn, ns, ne = n.apply(doc, ch, sec)
    try:
        n.save_settings(doc, st, S['path'])
    except Exception:
        pass
    forms.alert(u'Записано наименований: %d\nРазделов, кодов, единиц, ключей: %d\nНе удалось записать: %d\n\n'
                u'Отмена — Ctrl+Z («XYZ: наименования»).' % (nn, ns, ne), title=u'Наименования')
