# -*- coding: utf-8 -*-
"""Перенумеровать листы.

Окно со списком листов проекта. Порядок в списке = порядок новых номеров.
Слева колонки «Было → Станет», справа настройки нумерации; предпросмотр
обновляется сразу, как только что-то меняешь.

  · Группа — листы разложены по папкам так же, как в диспетчере проекта
    (текущая организация листов). Можно взять одну группу или «Все группы»
    (тогда каждая группа может нумероваться с начала).
  · Какие листы — вся группа или только выделенные в списке. Если перед запуском
    выделить листы в диспетчере проекта, откроется их группа и они будут выделены.
  · Порядок — кнопки «Вверх / Вниз» двигают выделенные листы; «По номеру» и
    «По названию» сортируют (выделенные — только между собой).
  · Нумерация — префикс, начальный номер, шаг, длина (ведущие нули), суффикс.
    «Оставить номер» — не нумеровать заново, а только добавить префикс/суффикс.
    «Пробел в конце» — если номер уже занят другой группой, к нему добавляется
    пробел (так в проекте и получаются одинаковые 0, 1, 2 в разных разделах).
  · Проверка — красная полоска слева: повтор номера, номер занят листом вне
    выборки или в номере запрещённый символ. Пока есть конфликты, «Перенумеровать»
    недоступна.

Перестановки (1↔2, сдвиг на один и т. п.) работают: Revit не допускает два
листа с одним номером, поэтому сначала листам даются временные номера, потом
окончательные. Всё одной транзакцией — отменяется одним Ctrl+Z.
"""
import re
import System
import clr  # pyRevit 7: WPF-сборки сами не подгружаются
clr.AddReference('PresentationCore'); clr.AddReference('PresentationFramework'); clr.AddReference('WindowsBase')
import System.Windows.Input

from pyrevit import revit, DB, script
import xyz_forms as forms   # единый стиль окон XYZ (lib/xyz_forms.py)
from System.Windows import (Thickness, CornerRadius, FontWeights, TextTrimming, VerticalAlignment,
                            HorizontalAlignment, GridLength, GridUnitType)
from System.Windows.Controls import (Grid, ColumnDefinition, TextBlock, ListBoxItem, Border)

doc = revit.doc
uidoc = revit.uidoc

# символы, которые Revit не принимает в номере листа
BAD_CHARS = u'\\:{}[]|;<>?`~'

C_RED = u'#C62828'
C_CHANGED = u'#66BB6A'
# варианты копии листа (как «Дублировать лист» в Revit), db 22.10
DUP_OPTS = [('empty', u'Пустой лист (только штамп)', 'DuplicateEmptySheet'),
            ('detail', u'Лист с оформлением, без видов', 'DuplicateSheetWithDetailing'),
            ('views', u'С видами (копии видов)', 'DuplicateSheetWithViewsOnly'),
            ('views_detail', u'С видами и оформлением', 'DuplicateSheetWithViewsAndDetailing'),
            ('dependent', u'С зависимыми видами', 'DuplicateSheetWithViewsAsDependent')]
DUP_LABEL = dict((k, t) for k, t, e in DUP_OPTS)


def dup_ok(sheet, key):
    """Можно ли так копировать лист (лист без видов — только ведомости — «с видами» нельзя)."""
    try:
        en = dict((k, e) for k, x, e in DUP_OPTS)[key]
        return sheet.CanBeDuplicated(getattr(DB.SheetDuplicateOption, en))
    except Exception:
        return False


def best_opt(sheet, key):
    """Запрошенный вариант, а если нельзя — ближайший возможный (db 22.10: «Sheet cannot be duplicated»)."""
    for k in (key, 'views_detail', 'detail', 'views', 'empty'):
        if dup_ok(sheet, k):
            return k
    return None


# ======================================================================
#  Логика (без Revit и без окна)
# ======================================================================
def nat_key(text):
    """Естественная сортировка: «А-2» перед «А-10»."""
    parts = re.split(u'(\\d+)', text or u'')
    return [(0, int(p), u'') if p.isdigit() else (1, 0, p.lower()) for p in parts if p != u'']


def to_int(text, default=None):
    try:
        return int((text or u'').strip())
    except (ValueError, TypeError):
        return default


def split_number(number):
    """«АР-101а» → («АР-», «101», «а»): префикс, последняя группа цифр, хвост."""
    number = (number or u'').rstrip()
    m = re.match(u'^(.*?)(\\d+)(\\D*)$', number)
    if not m:
        return number, u'', u''
    return m.group(1), m.group(2), m.group(3)


def to_dec(text):
    """«9,1» / «9.1» / «9» → (число, знаков после запятой, разделитель); не число → (None, 0, '.')."""
    t = (text or u'').strip()
    sep = u',' if u',' in t else u'.'
    t = t.replace(u',', u'.')
    if not re.match(u'^\\d+(\\.\\d+)?$', t):
        return None, 0, sep
    dec = len(t.split(u'.')[1]) if u'.' in t else 0
    return float(t), dec, sep


def make_number(index, prefix, start, step, length, suffix, dec=0, sep=u'.'):
    """Шаг может быть дробным (db 19.10): начать 9.1, шаг 0.1 → 9.1, 9.2, 9.3 …"""
    n = start + index * step
    if not dec:
        return u'%s%s%s' % (prefix, (u'%d' % int(round(n))).zfill(length), suffix)
    whole, frac = (u'%.*f' % (dec, n)).split(u'.')
    return u'%s%s%s%s%s' % (prefix, whole.zfill(length), sep, frac, suffix)


def bad_chars_in(number):
    return u''.join(sorted(set(c for c in number if c in BAD_CHARS)))


INVISIBLE = u'\u00a0\u00ad\u200b\u200c\u200d\u200e\u200f\u2060\u202a\u202b\u202c\u202d\u202e\ufeff'


def is_invisible(c):
    """Пробел или «невидимка» (неразрывный пробел, нулевой ширины и т. п.)."""
    return c.isspace() or c in INVISIBLE


def tail_of(text):
    """Невидимый хвост номера: у «0\u200b» это «\u200b»."""
    i = len(text)
    while i > 0 and is_invisible(text[i - 1]):
        i -= 1
    return text[i:]


def norm_number(text):
    """Номер без невидимых символов по краям — чтобы находить «0» и «0 » как один и тот же."""
    i, j = 0, len(text)
    while i < j and is_invisible(text[i]):
        i += 1
    while j > i and is_invisible(text[j - 1]):
        j -= 1
    return text[i:j]


def vis_space(text):
    """Невидимые символы по краям номера показываем точками: «1  » → «1··»."""
    core = norm_number(text)
    if core == text:
        return text
    k = text.index(core) if core else 0
    return u'\u00b7' * k + core + u'\u00b7' * (len(text) - k - len(core))


def codes(text):
    """Для подсказки: символы номера, невидимые — кодами (U+200B)."""
    return u''.join(c if not is_invisible(c) or c == u' ' else u'[U+%04X]' % ord(c) for c in text)


def plan(all_numbers, scope, settings, groups=None, names=None):
    """Что получится.

    all_numbers — текущие номера ВСЕХ листов по порядку списка;
    scope       — индексы листов, которые нумеруем (в порядке списка);
    settings    — dict: prefix, suffix, start, step, length, keep, restart, pad;
    groups      — группа каждого листа (для restart: в каждой группе с начала);
    names       — названия листов (для текста ошибки).

    Возвращает (new, errors): new[i] — новый номер листа i (только для scope),
    errors[i] — текст ошибки (только у конфликтных).
    """
    raw, counters = {}, {}
    for k, i in enumerate(scope):
        if settings['keep']:
            raw[i] = u'%s%s%s' % (settings['prefix'], all_numbers[i], settings['suffix'])
            if settings.get('find'):
                raw[i] = raw[i].replace(settings['find'], settings.get('repl') or u'')
            continue
        if settings.get('restart') and groups is not None:
            kk = counters.get(groups[i], 0)
            counters[groups[i]] = kk + 1
        else:
            kk = k
        raw[i] = make_number(kk, settings['prefix'], settings['start'], settings['step'],
                             settings['length'], settings['suffix'], settings.get('dec', 0),
                             settings.get('sep', u'.'))
        if settings.get('find'):
            raw[i] = raw[i].replace(settings['find'], settings.get('repl') or u'')
    scope_set = set(scope)
    outside = {}
    for i, num in enumerate(all_numbers):
        if i not in scope_set:
            outside.setdefault(num, i)
    if settings.get('pad'):
        # занятый номер → добавляем пробелы в конец, пока не станет свободным
        used = set(outside)
        new = {}
        for i in scope:
            n = raw[i] + tail_of(all_numbers[i])     # у листа свой «хвост» из пробелов — сохраняем
            while n in used:
                n += u' '
            used.add(n)
            new[i] = n
    else:
        new = raw
    errors = {}
    seen = {}
    for i in scope:
        seen.setdefault(new[i], []).append(i)
    for i in scope:
        n = new[i]
        if not n.strip():
            errors[i] = u'пустой номер'
        elif bad_chars_in(n):
            errors[i] = u'нельзя использовать: ' + u' '.join(bad_chars_in(n))
        elif len(seen[n]) > 1:
            errors[i] = u'номер «%s» повторяется' % vis_space(n)
        elif n in outside:
            errors[i] = u'номер «%s» занят другим листом' % vis_space(n)
            if names:
                errors[i] += u' — «%s»' % names[outside[n]]

    return new, errors


def group_label(group):
    return u' › '.join(group) if group else u'(вне папок)'


def temp_names(count, taken):
    """Временные номера, которых точно нет в проекте."""
    base = u'_xyz_tmp_'
    while any(t.startswith(base) for t in taken):
        base += u'_'
    return [u'%s%d' % (base, i) for i in range(count)]


# ======================================================================
#  Окно
# ======================================================================
XAML = u'''
<Window xmlns="http://schemas.microsoft.com/winfx/2006/xaml/presentation"
        xmlns:x="http://schemas.microsoft.com/winfx/2006/xaml"
        Title="Перенумеровать листы" Width="940" Height="720" MinWidth="800" MinHeight="560"
        WindowStartupLocation="CenterScreen" FontFamily="Segoe UI" FontSize="13">
  <Window.Resources>
    <ResourceDictionary>
      <ResourceDictionary.MergedDictionaries>
        <ResourceDictionary Source="XYZ_THEME_URI"/>
      </ResourceDictionary.MergedDictionaries>
      <Style x:Key="Lbl" TargetType="TextBlock"><Setter Property="Foreground" Value="#7A847C"/><Setter Property="FontSize" Value="11"/></Style>
      <Style TargetType="TextBox" BasedOn="{StaticResource {x:Type TextBox}}"><Setter Property="Margin" Value="0,2,8,6"/></Style>
      <Style TargetType="ComboBox" BasedOn="{StaticResource {x:Type ComboBox}}"><Setter Property="Margin" Value="0,2,0,8"/></Style>
      <Style TargetType="Button" BasedOn="{StaticResource {x:Type Button}}"><Setter Property="Margin" Value="0,4,6,0"/><Setter Property="Padding" Value="12,5"/></Style>
    </ResourceDictionary>
  </Window.Resources>
  <Grid x:Name="gridRoot" Margin="14,12,14,12">
    <Grid.ColumnDefinitions><ColumnDefinition Width="*" MinWidth="320"/><ColumnDefinition Width="8"/><ColumnDefinition x:Name="colSet" Width="340" MinWidth="260"/></Grid.ColumnDefinitions>
    <Grid.RowDefinitions><RowDefinition Height="*"/><RowDefinition Height="Auto"/><RowDefinition Height="Auto"/></Grid.RowDefinitions>

    <!-- список листов -->
    <DockPanel Grid.Row="0" Grid.Column="0" Margin="0,0,4,0" Grid.IsSharedSizeScope="True">
      <Grid DockPanel.Dock="Top" Margin="12,0,22,4">
        <!-- ширина «Было» / «Станет» — по самому длинному номеру (db 22.10: столбцы вплотную) -->
        <Grid.ColumnDefinitions>
          <ColumnDefinition Width="10"/><ColumnDefinition x:Name="hcOld" Width="Auto" SharedSizeGroup="cOld" MinWidth="30"/><ColumnDefinition Width="6"/>
          <ColumnDefinition Width="26"/><ColumnDefinition x:Name="hcNew" Width="Auto" SharedSizeGroup="cNew" MinWidth="30"/><ColumnDefinition Width="6"/>
          <ColumnDefinition Width="*"/>
        </Grid.ColumnDefinitions>
        <!-- столбцы можно двигать: тянуть за полоски в заголовке -->
        <Thumb x:Name="thOld" Grid.Column="2" Width="3" Background="#C9D2CB" Cursor="SizeWE"
               ToolTip="Тяните: шире или уже «Было»; двойной щелчок — по содержимому"/>
        <Thumb x:Name="thNew" Grid.Column="5" Width="3" Background="#C9D2CB" Cursor="SizeWE"
               ToolTip="Тяните: шире или уже «Станет»; двойной щелчок — по содержимому"/>
        <TextBlock Grid.Column="1" Text="БЫЛО" Style="{StaticResource Lbl}" Margin="0,0,10,0"/>
        <TextBlock Grid.Column="4" Text="СТАНЕТ" Style="{StaticResource Lbl}" Margin="0,0,14,0"/>
        <TextBlock Grid.Column="6" Text="НАЗВАНИЕ ЛИСТА" Style="{StaticResource Lbl}"/>
      </Grid>
      <Border Background="White" BorderBrush="#DDE3DE" BorderThickness="1" CornerRadius="10" Padding="3">
        <ListBox x:Name="lbSheets" SelectionMode="Extended" BorderThickness="0" Background="Transparent"
                 ScrollViewer.HorizontalScrollBarVisibility="Disabled" VirtualizingStackPanel.IsVirtualizing="False"/>
      </Border>
    </DockPanel>

    <!-- разделитель: тянуть влево/вправо — шире список или настройки (db 22.10, как в «Объёмах») -->
    <GridSplitter Grid.Row="0" Grid.Column="1" Width="6" HorizontalAlignment="Center" VerticalAlignment="Stretch"
                  Background="#DDE3DE" ResizeBehavior="PreviousAndNext" Cursor="SizeWE"
                  ToolTip="Тяните: шире список листов или настройки"/>

    <!-- настройки -->
    <ScrollViewer Grid.Row="0" Grid.Column="2" VerticalScrollBarVisibility="Auto">
      <StackPanel Margin="0,0,4,0">
        <GroupBox Header="Какие листы">
          <StackPanel>
            <TextBlock Text="КОЛЛЕКЦИЯ ЛИСТОВ" Style="{StaticResource Lbl}"/>
            <ComboBox x:Name="cbColl" Margin="0,0,0,8"/>
            <TextBlock Text="ГРУППА (КАК В ДИСПЕТЧЕРЕ ПРОЕКТА)" Style="{StaticResource Lbl}"/>
            <ComboBox x:Name="cbGroup"/>
            <CheckBox x:Name="cbOnlySel" Content="Только выделенные в списке" Margin="0,0,0,8"/>
            <TextBlock Text="НАЙТИ И ВЫДЕЛИТЬ (номер или название)" Style="{StaticResource Lbl}"/>
            <TextBox x:Name="tbFind"/>
            <WrapPanel>
              <Button x:Name="btnAll" Content="Выделить все" Margin="0,0,6,0"/>
              <Button x:Name="btnNone" Content="Снять" Margin="0,0,6,0"/>
            </WrapPanel>
          </StackPanel>
        </GroupBox>
        <GroupBox Header="Порядок">
          <WrapPanel>
            <Button x:Name="btnUp" Content="↑  Вверх" Margin="0,0,6,6"/>
            <Button x:Name="btnDown" Content="↓  Вниз" Margin="0,0,6,6"/>
            <Button x:Name="btnSortNum" Content="По номеру" Margin="0,0,6,0"
                    ToolTip="Естественная сортировка: А-2 перед А-10. Работает внутри каждой группы. Если выделено несколько листов — сортируются только они, на своих местах."/>
            <Button x:Name="btnSortName" Content="По названию" Margin="0,0,6,0"/>
          </WrapPanel>
        </GroupBox>
        <GroupBox Header="Нумерация">
          <StackPanel>
            <Grid>
              <Grid.ColumnDefinitions><ColumnDefinition/><ColumnDefinition/></Grid.ColumnDefinitions>
              <StackPanel Grid.Column="0"><TextBlock Text="ПРЕФИКС" Style="{StaticResource Lbl}"/><TextBox x:Name="tbPrefix"/></StackPanel>
              <StackPanel Grid.Column="1"><TextBlock Text="СУФФИКС" Style="{StaticResource Lbl}"/><TextBox x:Name="tbSuffix" Margin="0,2,0,6"/></StackPanel>
            </Grid>
            <Grid>
              <Grid.ColumnDefinitions><ColumnDefinition/><ColumnDefinition/><ColumnDefinition/></Grid.ColumnDefinitions>
              <StackPanel Grid.Column="0"><TextBlock Text="НАЧАТЬ С" Style="{StaticResource Lbl}"/><TextBox x:Name="tbStart" Text="1"/></StackPanel>
              <StackPanel Grid.Column="1"><TextBlock Text="ШАГ" Style="{StaticResource Lbl}"/><TextBox x:Name="tbStep" Text="1"/></StackPanel>
              <StackPanel Grid.Column="2"><TextBlock Text="ДЛИНА" Style="{StaticResource Lbl}"/><TextBox x:Name="tbLen" Text="1" Margin="0,2,0,6"
                  ToolTip="Сколько знаков в числе: при длине 3 получится 001, 002 …"/></StackPanel>
            </Grid>
            <CheckBox x:Name="cbKeep" Margin="0,2,0,8"><TextBlock TextWrapping="Wrap" MaxWidth="270" Text="Оставить номер (префикс, суффикс, замена)"/></CheckBox>
            <CheckBox x:Name="cbRestart" Margin="0,0,0,8"
                      ToolTip="Работает, когда выбрано «Все группы»: в каждой папке диспетчера номера идут заново с «Начать с».">
              <TextBlock TextWrapping="Wrap" MaxWidth="270" Text="Каждую группу — с начала"/></CheckBox>
            <CheckBox x:Name="cbPad"
                      ToolTip="Если такой номер уже есть в другой группе, к новому добавляется пробел (0 → «0 »), так одинаковые номера в разных разделах не конфликтуют. В списке пробелы в конце показаны точками.">
              <TextBlock TextWrapping="Wrap" MaxWidth="270" Text="Занятый номер — добавить пробел в конце"/></CheckBox>
          </StackPanel>
        </GroupBox>
        <GroupBox Header="Замена в номере">
          <StackPanel>
            <Grid>
              <Grid.ColumnDefinitions><ColumnDefinition/><ColumnDefinition/></Grid.ColumnDefinitions>
              <StackPanel Grid.Column="0"><TextBlock Text="НАЙТИ" Style="{StaticResource Lbl}"/><TextBox x:Name="tbRepFind"
                  ToolTip="Что убрать или заменить в номере, например « (1)» — с пробелом впереди."/></StackPanel>
              <StackPanel Grid.Column="1"><TextBlock Text="ЗАМЕНИТЬ НА" Style="{StaticResource Lbl}"/><TextBox x:Name="tbRepTo" Margin="0,2,0,6"
                  ToolTip="Пусто — просто удалить найденное."/></StackPanel>
            </Grid>
            <TextBlock TextWrapping="Wrap" Style="{StaticResource Lbl}"
                       Text="Убрать « (1)»: включите «Оставить номер», в «Найти» — пробел и (1), «Заменить на» — пусто."/>
          </StackPanel>
        </GroupBox>
      </StackPanel>
    </ScrollViewer>

    <!-- статус -->
    <TextBlock x:Name="tbStatus" Grid.Row="1" Grid.ColumnSpan="3" TextWrapping="Wrap" Margin="2,10,0,0" MinHeight="18"/>

    <!-- кнопки -->
    <StackPanel Grid.Row="2" Grid.ColumnSpan="3" Orientation="Horizontal" HorizontalAlignment="Right" Margin="0,8,0,0">
      <Button x:Name="btnCancel" Content="Отмена" IsCancel="True" MinWidth="90"/>
      <Button x:Name="btnOk" Content="Перенумеровать" IsDefault="True" MinWidth="140" Margin="0,4,0,0"/>
    </StackPanel>
  </Grid>
</Window>
'''


class Row(object):
    """Один лист в списке."""
    def __init__(self, sheet, group, src=None, opt=None):
        self.sheet = sheet          # None — новая копия (создастся по «Перенумеровать»)
        self.src = src              # лист-образец копии
        self.opt = opt              # ключ варианта копии (DUP_OPTS)
        self.deleted = False        # помечен на удаление (Delete / меню)
        self.old = sheet.SheetNumber if sheet is not None else u''
        self.name = (sheet or src).Name
        self.group = group
        self.rename = None          # новое название листа (двойной щелчок по названию, db 22.10)
        self.tb_name = None
        self.coll = group[0] if group else u''   # коллекция листов Revit 2025 — первый элемент группы
        self.item = None
        self.grid = None
        self.strip = None
        self.tb_new = None


def group_sort_key(group):
    return [nat_key(g) for g in group]


class RenumberWindow(forms.WPFWindow):
    def __init__(self, sheets, groups_map, preselected, active_id):
        forms.WPFWindow.__init__(self, XAML.replace(u'XYZ_THEME_URI', forms.theme_uri()), literal_string=True)
        forms.theme(self, u'Перенумеровать листы',
                    u'Порядок в списке = порядок новых номеров · предпросмотр сразу', merge=False)
        self.busy = True
        self.result = None
        self.renamed = []
        self.copies = []
        self.deleted = []
        self._edit = None
        self._locked = set()         # листы, открытые в Revit (удалять нельзя)
        try:
            self._locked = set(v.ViewId.Value for v in uidoc.GetOpenUIViews())
        except Exception:
            pass
        self._plan = None
        self.touched = False         # пользователь сам менял настройки — не подставлять их из выбранной группы
        rows = [Row(sh, groups_map.get(sh.Id.Value, ())) for sh in sheets]
        rows.sort(key=lambda r: (group_sort_key(r.group), nat_key(r.old.strip()), r.old))
        self.rows = rows
        self.groups = []
        self.colls = []
        for r in rows:
            if r.group not in self.groups:
                self.groups.append(r.group)
            if r.coll not in self.colls:
                self.colls.append(r.coll)
        self.cur = None              # None = все группы
        self.ccur = None             # None = все коллекции (db 22.10: фильтр по коллекции листов)
        # --- какая группа открывается
        sel_ids = set(preselected)
        picked = [r for r in rows if r.sheet.Id.Value in sel_ids]
        start_row = picked[0] if picked else next((r for r in rows if r.sheet.Id.Value == active_id), None)
        if start_row is not None and len(self.groups) > 1:
            self.cur = start_row.group
            self.ccur = start_row.coll
        # --- список коллекций и групп
        self.cbColl.Items.Add(u'Все коллекции  ·  %d' % len(rows))
        for c in self.colls:
            self.cbColl.Items.Add(u'%s  ·  %d' % (c or u'(без коллекции)', len([r for r in rows if r.coll == c])))
        self.cbColl.SelectedIndex = 0 if self.ccur is None else self.colls.index(self.ccur) + 1
        self.refill_groups()
        # --- галки по умолчанию
        self.cbOnlySel.IsChecked = bool(picked)
        self.cbRestart.IsChecked = True
        seen = {}
        dup = False
        for r in rows:
            k = norm_number(r.old)
            if k in seen and seen[k] != r.old:
                dup = True
            seen.setdefault(k, r.old)
        self.cbPad.IsChecked = dup          # в проекте уже есть «0» и «0 » (или «0» с невидимым символом) — так принято
        self.fill_list()
        for r in picked:
            r.item.IsSelected = True
        self.prefill()
        self.update_enabled()
        if picked:
            self.lbSheets.ScrollIntoView(picked[0].item)
        for tb in (self.tbPrefix, self.tbSuffix, self.tbStart, self.tbStep, self.tbLen, self.tbRepFind, self.tbRepTo):
            tb.TextChanged += self.on_edit
        self.cbKeep.Checked += self.on_flags
        self.cbKeep.Unchecked += self.on_flags
        self.cbRestart.Checked += self.on_flags
        self.cbRestart.Unchecked += self.on_flags
        self.cbPad.Checked += self.on_flags
        self.cbPad.Unchecked += self.on_flags
        self.cbOnlySel.Checked += self.on_flags
        self.cbOnlySel.Unchecked += self.on_flags
        self.cbGroup.SelectionChanged += self.on_group
        self.cbColl.SelectionChanged += self.on_coll
        self.lbSheets.SelectionChanged += self.on_select
        # перетаскивание мышью (db 22.10): взять выделенные листы и бросить на нужное место
        self._drag = None
        self.PreviewKeyDown += self.on_list_key   # окно целиком: F2 / Ctrl+C / Ctrl+V / Delete работают, где бы ни был фокус (кроме полей ввода)
        self.lbSheets.ContextMenuOpening += self.on_menu
        self.clip = []
        self.lbSheets.ContextMenu = System.Windows.Controls.ContextMenu()
        self.lbSheets.PreviewMouseLeftButtonDown += self.drag_down
        self.lbSheets.PreviewMouseMove += self.drag_move
        self.lbSheets.PreviewMouseLeftButtonUp += self.drag_up
        self.KeyDown += lambda s_, e_: self.drag_cancel() if str(e_.Key) == 'Escape' and self._drag else None
        self.tbFind.TextChanged += self.on_find
        self.btnAll.Click += lambda s, e: self.reselect(self.vis())
        self.btnNone.Click += lambda s, e: self.reselect([])
        self.btnUp.Click += lambda s, e: self.move(-1)
        self.btnDown.Click += lambda s, e: self.move(1)
        self.btnSortNum.Click += lambda s, e: self.sort_rows(lambda r: (nat_key(r.old.strip()), r.old))
        self.btnSortName.Click += lambda s, e: self.sort_rows(lambda r: (nat_key(r.name), r.old))
        self.btnOk.Click += self.on_ok
        self.btnCancel.Click += lambda s, e: self.Close()
        self.busy = False
        self.preview()
        self.setup_view()

    # ------------------------------------------------------------ окно: размер, разделитель, масштаб (db 22.10)
    def setup_view(self):
        """Как в «Объёмах»: окно тянется, разделитель между списком и настройками, Ctrl+колесо — масштаб,
        Ctrl+0 — 100 %; размер, разделитель и масштаб запоминаются (xyz_settings, ключ 'renum')."""
        try:
            import xyz_settings
            self._hs = xyz_settings
            self._cfg = dict(xyz_settings.get('renum') or {})
        except Exception:
            self._hs = None
            self._cfg = {}
        c = self._cfg
        try:
            if c.get('w') and c.get('h'):
                self.Width = max(self.MinWidth, float(c['w']))
                self.Height = max(self.MinHeight, float(c['h']))
            if c.get('set_w'):
                self.colSet.Width = GridLength(max(260.0, float(c['set_w'])))
        except Exception:
            pass
        self._zoom = max(0.6, min(1.6, float(c.get('zoom', 1.0))))
        self.apply_zoom()
        # столбцы «Было» / «Станет»: по содержимому, тянуть за полоску в заголовке (запоминается)
        for th, col, key in ((self.thOld, self.hcOld, 'w_old'), (self.thNew, self.hcNew, 'w_new')):
            th.DragDelta += (lambda col_, key_: (lambda s_, e_: self.drag_col(col_, key_, e_.HorizontalChange)))(col, key)
            th.MouseDoubleClick += (lambda col_, key_: (lambda s_, e_: self.auto_col(col_, key_)))(col, key)
        self.apply_cols()
        self.PreviewMouseWheel += self.on_zoom_wheel
        self.PreviewKeyDown += self.on_zoom_key
        self.Closing += self.save_view

    def col_width(self, key):
        """Ширина столбца: число (задана руками) или GridLength.Auto (по содержимому)."""
        w = getattr(self, '_cfg', {}).get(key)
        return GridLength(float(w)) if w else GridLength.Auto

    def apply_cols(self):
        """Ширины «Было» (колонка 1) и «Станет» (4) — в заголовке и во всех строках одинаково."""
        wo, wn = self.col_width('w_old'), self.col_width('w_new')
        self.hcOld.Width = wo
        self.hcNew.Width = wn
        for r in self.rows:
            if r.grid is not None:
                r.grid.ColumnDefinitions[1].Width = wo
                r.grid.ColumnDefinitions[4].Width = wn

    def drag_col(self, col, key, dx):
        self._cfg[key] = max(col.MinWidth, col.ActualWidth + dx)
        self.apply_cols()

    def auto_col(self, col, key):
        self._cfg.pop(key, None)
        self.apply_cols()

    def apply_zoom(self):
        from System.Windows.Media import ScaleTransform
        self.gridRoot.LayoutTransform = ScaleTransform(self._zoom, self._zoom)
        self.tbStatus.ToolTip = u'Масштаб окна %d %% · Ctrl+колесо, Ctrl+0 — 100 %%' % int(self._zoom * 100)

    def on_zoom_wheel(self, s, e):
        from System.Windows.Input import Keyboard, ModifierKeys
        if Keyboard.Modifiers & ModifierKeys.Control == ModifierKeys.Control:
            self._zoom = round(max(0.6, min(1.6, self._zoom + (0.05 if e.Delta > 0 else -0.05))), 2)
            self.apply_zoom()
            e.Handled = True

    def on_zoom_key(self, s, e):
        from System.Windows.Input import Keyboard, ModifierKeys, Key
        if Keyboard.Modifiers & ModifierKeys.Control == ModifierKeys.Control and e.Key in (Key.D0, Key.NumPad0):
            self._zoom = 1.0
            self.apply_zoom()
            e.Handled = True

    def save_view(self, s, e):
        if self._hs is None:
            return
        try:
            self._cfg.update({'w': self.ActualWidth, 'h': self.ActualHeight, 'zoom': self._zoom,
                              'set_w': self.colSet.ActualWidth})
            self._hs.set('renum', self._cfg)
        except Exception:
            pass

    # ------------------------------------------------------------ список
    def gvis(self):
        """Группы выбранной коллекции (все — если коллекция не выбрана)."""
        return [g for g in self.groups if self.ccur is None or (g[:1] or (u'',))[0] == self.ccur]

    def refill_groups(self):
        was = self.busy
        self.busy = True
        gs = self.gvis()
        if self.cur not in gs:
            self.cur = None
        rs = [r for r in self.rows if self.ccur is None or r.coll == self.ccur]
        self.cbGroup.Items.Clear()
        self.cbGroup.Items.Add(u'Все группы  ·  %d' % len(rs))
        for g in gs:
            lab = group_label(g[1:]) if self.ccur is not None else group_label(g)
            self.cbGroup.Items.Add(u'%s  ·  %d' % (lab, len([r for r in rs if r.group == g])))
        self.cbGroup.SelectedIndex = 0 if self.cur is None else gs.index(self.cur) + 1
        self.busy = was

    def vis(self):
        if self.cur is None:
            return [r for r in self.rows if self.ccur is None or r.coll == self.ccur]
        return [r for r in self.rows if r.group == self.cur]

    def make_item(self, r):
        g = Grid()
        for w in (10, 'cOld', 6, 26, 'cNew', 6):
            cd = ColumnDefinition()
            if isinstance(w, int):
                cd.Width = GridLength(w)
            else:   # общая ширина с заголовком — по самому длинному номеру
                cd.Width = GridLength.Auto
                cd.SharedSizeGroup = w
            g.ColumnDefinitions.Add(cd)
        last = ColumnDefinition()
        last.Width = GridLength(1, GridUnitType.Star)
        g.ColumnDefinitions.Add(last)

        r.strip = Border()
        r.strip.Width = 4
        r.strip.CornerRadius = CornerRadius(2)
        r.strip.Margin = Thickness(0, 1, 6, 1)
        r.strip.HorizontalAlignment = HorizontalAlignment.Left
        Grid.SetColumn(r.strip, 0)
        g.Children.Add(r.strip)

        old = TextBlock()
        old.Text = vis_space(r.old)
        if norm_number(r.old) != r.old:
            old.ToolTip = u'Номер с невидимыми символами: ' + codes(r.old)
        old.Margin = Thickness(0, 0, 10, 0)
        old.TextTrimming = TextTrimming.CharacterEllipsis
        Grid.SetColumn(old, 1)
        g.Children.Add(old)

        arrow = TextBlock()
        arrow.Text = u'→'
        arrow.Opacity = 0.5
        Grid.SetColumn(arrow, 3)
        g.Children.Add(arrow)

        r.tb_new = TextBlock()
        r.tb_new.Margin = Thickness(0, 0, 14, 0)
        r.tb_new.TextTrimming = TextTrimming.CharacterEllipsis
        Grid.SetColumn(r.tb_new, 4)
        g.Children.Add(r.tb_new)

        nm = TextBlock()
        nm.Text = r.name
        nm.TextTrimming = TextTrimming.CharacterEllipsis
        nm.ToolTip = u'%s\n%s\nДвойной щелчок — переименовать' % (r.name, group_label(r.group))
        r.tb_name = nm
        Grid.SetColumn(nm, 6)
        g.Children.Add(nm)

        if r.sheet is None:      # новая копия
            old.Text = u'копия'
            old.FontStyle = System.Windows.FontStyles.Italic
            old.Foreground = forms._brush(forms.GREEN)
            old.ToolTip = u'Новый лист — копия «%s %s»: %s. Создастся по «Перенумеровать».' % (
                r.src.SheetNumber, r.src.Name, DUP_LABEL.get(r.opt, u''))
        if getattr(self, '_cfg', None):
            g.ColumnDefinitions[1].Width = self.col_width('w_old')
            g.ColumnDefinitions[4].Width = self.col_width('w_new')
        r.grid = g
        item = ListBoxItem()
        item.Content = g
        r.item = item
        return item

    def make_header(self, group):
        tb = TextBlock()
        tb.Text = group_label(group)
        tb.FontWeight = FontWeights.SemiBold
        tb.Foreground = forms._brush(forms.GREEN)
        tb.Margin = Thickness(2, 6, 0, 2)
        item = ListBoxItem()
        item.Content = tb
        item.IsHitTestVisible = False
        item.Focusable = False
        return item

    def fill_list(self):
        was = self.busy
        self.busy = True
        self.lbSheets.Items.Clear()
        self.headers = []
        last = object()
        for r in self.vis():
            if self.cur is None and len(self.gvis()) > 1 and r.group != last:
                h = self.make_header(r.group)
                self.headers.append(h)
                self.lbSheets.Items.Add(h)
            last = r.group
            self.lbSheets.Items.Add(r.item if r.item is not None else self.make_item(r))
        self.busy = was

    def reselect(self, rows):
        was = self.busy
        self.busy = True
        self.lbSheets.UnselectAll()
        for r in rows:
            r.item.IsSelected = True
        self.busy = was
        self.preview()

    # ------------------------------------------------------------ перетаскивание мышью
    def row_at(self, pos):
        """Строка списка под точкой (координаты lbSheets) или None."""
        from System.Windows.Media import VisualTreeHelper
        el = self.lbSheets.InputHitTest(pos)
        while el is not None and not isinstance(el, ListBoxItem):
            try:
                el = VisualTreeHelper.GetParent(el)
            except Exception:
                return None
        if el is None:
            return None
        for r in self.rows:
            if r.item is el:
                return r
        return None

    def drag_down(self, s, e):
        from System.Windows.Input import Keyboard
        if getattr(self, '_edit', None) is not None:
            return                       # идёт переименование — мышь у поля ввода
        r = self.row_at(e.GetPosition(self.lbSheets))
        if r is None:
            return
        if e.ClickCount == 2 and r.tb_name is not None and e.GetPosition(r.tb_name).X >= 0:
            e.Handled = True
            self._drag = None
            self.begin_rename(r)
            return
        self._drag = {'row': r, 'pt': e.GetPosition(self.lbSheets), 'on': False, 'mark': None}
        # щелчок по уже выделенной строке без Ctrl/Shift — не сбрасывать выделение (можно тащить несколько)
        if r.item.IsSelected and int(Keyboard.Modifiers) == 0 and len(self.selected_rows()) > 1:
            e.Handled = True
            self._drag['click_only'] = True

    def drag_move(self, s, e):
        from System.Windows.Input import MouseButtonState, Mouse
        d = self._drag
        if not d or e.LeftButton != MouseButtonState.Pressed:
            return
        p = e.GetPosition(self.lbSheets)
        if not d['on']:
            if abs(p.Y - d['pt'].Y) < 5 and abs(p.X - d['pt'].X) < 5:
                return
            if not d['row'].item.IsSelected:
                self.reselect([d['row']])
            d['on'] = True
            d['rows'] = self.selected_rows()
            Mouse.Capture(self.lbSheets)
            self.lbSheets.Cursor = System.Windows.Input.Cursors.SizeNS
        # прокрутка у краёв списка
        h = self.lbSheets.ActualHeight
        vis = self.vis()
        if p.Y < 18 or p.Y > h - 18:
            t = self.row_at(System.Windows.Point(p.X, max(2.0, min(h - 2.0, p.Y))))
            if t is not None and t in vis:
                k = vis.index(t) + (-1 if p.Y < 18 else 1)
                if 0 <= k < len(vis):
                    self.lbSheets.ScrollIntoView(vis[k].item)
        t = self.row_at(System.Windows.Point(p.X, max(2.0, min(h - 2.0, p.Y))))
        self.drag_mark(t, p)

    def drag_mark(self, t, p):
        d = self._drag
        if d.get('mark') is not None:
            d['mark'].BorderThickness = Thickness(0)
            d['mark'] = None
        d['target'] = None
        if t is None or t in d['rows']:
            return
        below = p.Y > t.item.TranslatePoint(System.Windows.Point(0, t.item.ActualHeight / 2.0), self.lbSheets).Y
        d['target'] = (t, below)
        t.item.BorderBrush = forms._brush(forms.GREEN)
        t.item.BorderThickness = Thickness(0, 0, 0, 3) if below else Thickness(0, 3, 0, 0)
        d['mark'] = t.item
        ok = all(r.group == t.group for r in d['rows'])
        self.tbStatus.Text = (u'Отпустите — %d лист(ов) встанут %s «%s %s»' % (
            len(d['rows']), u'после' if below else u'перед', t.old.strip(), t.name)) if ok else \
            u'Между группами переносить нельзя — номер зависит от группы'

    def drag_up(self, s, e):
        from System.Windows.Input import Mouse
        d = self._drag
        if not d:
            return
        if not d['on']:
            if d.get('click_only'):      # был щелчок по выделенной строке — выделить только её
                self.reselect([d['row']])
            self._drag = None
            return
        tgt = d.get('target')
        rows = d['rows']
        self.drag_cancel()
        e.Handled = True
        if not tgt:
            self.preview()
            return
        t, below = tgt
        if not all(r.group == t.group for r in rows):
            self.preview()
            return
        ids = set(id(r) for r in rows)
        rest = [r for r in self.rows if id(r) not in ids]
        k = rest.index(t) + (1 if below else 0)
        self.rows[:] = rest[:k] + rows + rest[k:]
        self.touched = True
        self.fill_list()
        self.reselect(rows)
        self.focus_row(rows[0])

    def drag_cancel(self):
        from System.Windows.Input import Mouse
        d = self._drag
        self._drag = None
        if not d:
            return
        if d.get('mark') is not None:
            d['mark'].BorderThickness = Thickness(0)
        self.lbSheets.Cursor = None
        if Mouse.Captured is self.lbSheets:
            Mouse.Capture(None)

    # ------------------------------------------------------------ переименование (двойной щелчок по названию)
    def begin_rename(self, r):
        from System.Windows.Controls import TextBox
        from System.Windows.Input import Key
        tb = TextBox()
        tb.Text = r.rename if r.rename is not None else r.name
        tb.Margin = Thickness(0, -2, 6, -2)
        tb.Padding = Thickness(2, 0, 2, 0)
        tb.MinWidth = 0
        tb.ToolTip = u'Enter — сохранить, Esc — отмена. Запишется в модель по «Перенумеровать».'
        Grid.SetColumn(tb, 6)
        r.tb_name.Visibility = System.Windows.Visibility.Collapsed
        r.grid.Children.Add(tb)
        self._edit = (r, tb)

        def key(s_, e_):
            if e_.Key in (Key.Enter, Key.Return):
                self.end_rename(True, refocus=True)
                e_.Handled = True
            elif e_.Key == Key.Escape:
                self.end_rename(False, refocus=True)
                e_.Handled = True
            elif e_.Key in (Key.Up, Key.Down):      # стрелка — сохранить и перейти на соседний лист
                self.end_rename(True, refocus=True, step=-1 if e_.Key == Key.Up else 1)
                e_.Handled = True
        tb.PreviewKeyDown += key
        tb.LostKeyboardFocus += lambda s_, e_: self.end_rename(True)
        tb.Loaded += lambda s_, e_: (tb.Focus(), tb.SelectAll())
        tb.Focus()
        tb.SelectAll()

    def focus_row(self, r):
        """Фокус клавиатуры — на строку списка (после отрисовки): стрелки ходят по листам, F2 снова работает."""
        from System.Windows.Threading import DispatcherPriority

        def go():
            try:
                self.lbSheets.ScrollIntoView(r.item)
                r.item.Focus()
            except Exception:
                pass
        self.Dispatcher.BeginInvoke(DispatcherPriority.Input, System.Action(go))

    def end_rename(self, save, refocus=False, step=0):
        ed = getattr(self, '_edit', None)
        if ed is None:
            return
        self._edit = None
        r, tb = ed
        if save:
            t = (tb.Text or u'').strip()
            r.rename = t if (t and t != r.name) else None
        r.grid.Children.Remove(tb)
        r.tb_name.Visibility = System.Windows.Visibility.Visible
        if r.rename is not None:
            r.tb_name.Text = r.rename
            r.tb_name.Foreground = forms._brush(forms.GREEN)
            r.tb_name.FontWeight = FontWeights.SemiBold
            r.tb_name.ToolTip = u'Было: %s\nСтанет: %s\nДвойной щелчок — изменить; стереть всё — вернуть' % (r.name, r.rename)
        else:
            r.tb_name.Text = r.name
            r.tb_name.ClearValue(TextBlock.ForegroundProperty)
            r.tb_name.FontWeight = FontWeights.Normal
            r.tb_name.ToolTip = u'%s\n%s\nДвойной щелчок — переименовать' % (r.name, group_label(r.group))
        self.preview()
        if refocus:
            vis = self.vis()
            t = r
            if step and r in vis:
                k = vis.index(r) + step
                if 0 <= k < len(vis):
                    t = vis[k]
                    self.reselect([t])
            self.focus_row(t)

    def renames(self):
        return [(r.sheet, r.name, r.rename) for r in self.rows
                if r.rename is not None and r.sheet is not None and not r.deleted]

    # ------------------------------------------------------------ копия / удаление (Ctrl+C, Ctrl+V, Delete, меню)
    def dup_opt(self):
        return (getattr(self, '_cfg', None) or {}).get('dup_opt') or 'views_detail'

    def on_list_key(self, s, e):
        from System.Windows.Input import Keyboard, ModifierKeys, Key
        from System.Windows.Controls import TextBox, ComboBox, ComboBoxItem
        if getattr(self, '_edit', None) is not None:
            return
        fe = Keyboard.FocusedElement
        if isinstance(fe, (TextBox, ComboBox, ComboBoxItem)):
            return                       # печатают в поле справа — не мешать
        ctrl = Keyboard.Modifiers & ModifierKeys.Control == ModifierKeys.Control
        if ctrl and e.Key == Key.C:
            self.do_copy()
        elif ctrl and e.Key == Key.V:
            self.do_paste()
        elif e.Key == Key.Delete:
            self.do_delete()
        elif e.Key == Key.F2:
            cur = next((r for r in self.rows if r.item is not None and r.item is fe), None)
            sel = self.selected_rows()
            r = cur if (cur is not None and cur.item.IsSelected) else (sel[0] if sel else None)
            if r is not None:
                self.reselect([r]) if len(sel) > 1 else None
                self.begin_rename(r)
        else:
            return
        e.Handled = True

    def do_copy(self):
        self.clip = [r for r in self.selected_rows() if not r.deleted]
        self.set_status(u'Скопировано листов: %d — Ctrl+V вставит копии (%s).' % (
            len(self.clip), DUP_LABEL[self.dup_opt()].lower()), 'mute')

    def do_paste(self, rows=None, opt=None):
        """Копии листов — сразу после выделенной строки той же группы (иначе — после образца)."""
        src_rows = rows if rows is not None else self.clip
        if not src_rows:
            self.set_status(u'Сначала выделите листы и нажмите Ctrl+C (или «Дублировать» в меню).', 'mute')
            return
        opt = opt or self.dup_opt()
        sel = self.selected_rows()
        new_rows = []
        swapped = []
        for r in src_rows:
            src = r.sheet or r.src
            want = opt if r.sheet is not None else r.opt
            o = best_opt(src, want)
            if o is None:
                swapped.append(u'%s — нельзя копировать' % src.SheetNumber)
                continue
            if o != want:
                swapped.append(u'%s — %s' % (src.SheetNumber, DUP_LABEL[o].lower()))
            c = Row(None, r.group, src=src, opt=o)
            if r.rename is not None:
                c.name = r.rename
            same = [x for x in sel if x.group == r.group]
            anchor = same[-1] if same else r
            k = self.rows.index(anchor) + 1
            while k < len(self.rows) and self.rows[k] in new_rows:   # несколько копий — по порядку
                k += 1
            self.rows.insert(k, c)
            new_rows.append(c)
        if not new_rows:
            self.set_status(u'Копий нет: ' + u'; '.join(swapped), 'err')
            return
        self.touched = True
        self.fill_list()
        self.reselect(new_rows)
        self.focus_row(new_rows[-1])
        if swapped:   # лист без видов (только ведомости) «с видами» не копируется — взят ближайший вариант
            self.set_status(u'Вариант заменён (на листе нет видов): ' + u'; '.join(swapped[:6]), 'mute')

    def do_delete(self, rows=None):
        rows = rows if rows is not None else self.selected_rows()
        if not rows:
            return
        restore = all(r.deleted for r in rows if r.sheet is not None) and any(r.sheet is not None for r in rows)
        for r in rows:
            if r.sheet is None:          # копию, которой ещё нет в модели, просто убрать из списка
                self.rows.remove(r)
                continue
            if not restore and r.sheet.Id.Value in self._locked:
                self.set_status(u'Лист «%s %s» открыт в Revit — закройте его вкладку, иначе удалить нельзя.' % (
                    r.old.strip(), r.name), 'err')
                continue
            r.deleted = not restore
            self.mark_deleted(r)
        self.fill_list()
        keep = [r for r in rows if r in self.rows]
        self.reselect(keep)
        if keep:
            self.focus_row(keep[0])

    def mark_deleted(self, r):
        from System.Windows import TextDecorations
        r.tb_name.TextDecorations = TextDecorations.Strikethrough if r.deleted else None
        r.tb_name.ToolTip = (u'Будет удалён по «Перенумеровать» (виды на нём останутся в модели). '
                             u'Delete ещё раз — вернуть') if r.deleted else r.name

    def on_menu(self, s, e):
        from System.Windows.Controls import MenuItem, Separator
        m = self.lbSheets.ContextMenu
        m.Items.Clear()
        sel = self.selected_rows()

        def item(text, fn, enabled=True, gesture=None):
            mi = MenuItem()
            mi.Header = text
            if gesture:
                mi.InputGestureText = gesture
            mi.IsEnabled = enabled
            mi.Click += lambda s_, e_: fn()
            m.Items.Add(mi)
            return mi
        item(u'Копировать', self.do_copy, bool(sel), u'Ctrl+C')
        item(u'Вставить копию', lambda: self.do_paste(), bool(self.clip), u'Ctrl+V')
        dup = MenuItem()
        dup.Header = u'Дублировать как…'
        dup.IsEnabled = bool(sel)
        for k, t, en in DUP_OPTS:
            mi = MenuItem()
            mi.Header = t + (u'   ✓' if k == self.dup_opt() else u'')
            src_ = [r.sheet or r.src for r in sel]
            mi.IsEnabled = bool(src_) and any(dup_ok(x, k) for x in src_)
            if src_ and mi.IsEnabled and not all(dup_ok(x, k) for x in src_):
                mi.Header += u'  (где нельзя — ближайший)'
            
            mi.ToolTip = u'Станет вариантом для Ctrl+V'

            def go(s_, e_, k=k):
                self._cfg['dup_opt'] = k
                self.do_paste(self.selected_rows(), k)
            mi.Click += go
            dup.Items.Add(mi)
        m.Items.Add(dup)
        m.Items.Add(Separator())
        dl = [r for r in sel if r.sheet is not None]
        restore = bool(dl) and all(r.deleted for r in dl)
        item(u'Вернуть' if restore else u'Удалить', lambda: self.do_delete(), bool(sel), u'Delete')
        item(u'Переименовать', lambda: self.begin_rename(sel[0]), len(sel) == 1, u'F2 / двойной щелчок')

    def selected_rows(self):
        vis = set(id(r) for r in self.vis())
        return [r for r in self.rows if id(r) in vis and r.item.IsSelected]

    def move(self, d):
        sel = set(id(r) for r in self.selected_rows())
        if not sel:
            return
        rows = self.rows
        n = len(rows)
        rng = range(n) if d < 0 else range(n - 1, -1, -1)
        for i in rng:
            j = i + d
            if (id(rows[i]) in sel and 0 <= j < n and id(rows[j]) not in sel
                    and rows[j].group == rows[i].group):
                rows[i], rows[j] = rows[j], rows[i]
        keep = self.selected_rows()
        self.fill_list()
        self.reselect(keep)
        if keep:
            self.lbSheets.ScrollIntoView((keep[0] if d < 0 else keep[-1]).item)

    def sort_rows(self, key):
        keep = self.selected_rows()
        target = keep if len(keep) >= 2 else self.vis()
        index = dict((id(r), i) for i, r in enumerate(self.rows))
        by_group = {}
        for r in target:
            by_group.setdefault(r.group, []).append(r)
        for g, lst in by_group.items():
            slots = sorted(index[id(r)] for r in lst)
            for i, r in zip(slots, sorted(lst, key=key)):
                self.rows[i] = r
        self.fill_list()
        self.reselect(keep)

    def on_group(self, s, e):
        if self.busy:
            return
        keep = self.selected_rows()
        k = self.cbGroup.SelectedIndex
        self.cur = None if k <= 0 else self.gvis()[k - 1]
        self.fill_list()
        vis = set(id(r) for r in self.vis())
        self.reselect([r for r in keep if id(r) in vis])
        if not self.touched:
            self.prefill()
        self.update_enabled()
        self.preview()

    def on_coll(self, s, e):
        if self.busy:
            return
        k = self.cbColl.SelectedIndex
        self.ccur = None if k <= 0 else self.colls[k - 1]
        self.refill_groups()
        self.busy = False
        self.on_group(None, None)

    def on_select(self, s, e):
        if self.busy:
            return
        for h in self.headers:          # Ctrl+A мог захватить заголовки групп
            if h.IsSelected:
                h.IsSelected = False
        self.preview()

    # ------------------------------------------------------------ настройки и предпросмотр
    def prefill(self):
        """Префикс / начало / длину берём с первого листа выбранной группы."""
        vis = self.vis()
        first = vis[0] if vis else None
        if first is None:
            return
        was = self.busy
        self.busy = True
        pre, digits, suf = split_number(first.old)
        self.tbPrefix.Text = pre
        self.tbSuffix.Text = suf
        if digits:
            self.tbStart.Text = u'%d' % int(digits)
            self.tbLen.Text = u'%d' % (len(digits) if digits.startswith(u'0') and len(digits) > 1 else 1)
        self.busy = was

    def update_enabled(self):
        keep = bool(self.cbKeep.IsChecked)
        for tb in (self.tbStart, self.tbStep, self.tbLen):
            tb.IsEnabled = not keep
        self.cbRestart.IsEnabled = (self.cur is None and len(self.gvis()) > 1 and not keep)

    def settings(self):
        start, d1, sep1 = to_dec(self.tbStart.Text)
        step, d2, sep2 = to_dec(self.tbStep.Text)
        length = to_int(self.tbLen.Text)
        keep = bool(self.cbKeep.IsChecked)
        if keep:
            start, step, length, d1, d2 = 0, 1, 1, 0, 0
        problems = []
        if start is None:
            problems.append(u'«Начать с» — число от 0 (можно дробное: 9.1)')
        if step is None or step <= 0:
            problems.append(u'«Шаг» — число больше 0 (можно дробное: 0.1)')
        if length is None or length < 1 or length > 9:
            problems.append(u'«Длина» — от 1 до 9')
        sep = sep1 if d1 else sep2
        return dict(prefix=self.tbPrefix.Text or u'', suffix=self.tbSuffix.Text or u'',
                    start=start, step=step, length=length, keep=keep, dec=max(d1, d2), sep=sep,
                    find=self.tbRepFind.Text or u'', repl=self.tbRepTo.Text or u'',
                    restart=bool(self.cbRestart.IsChecked) and bool(self.cbRestart.IsEnabled),
                    pad=bool(self.cbPad.IsChecked)), problems

    def scope_rows(self):
        vis = self.vis()
        if self.cbOnlySel.IsChecked:
            return [r for r in vis if r.item.IsSelected]
        return vis

    def on_edit(self, s, e):
        if self.busy:
            return
        self.touched = True
        self.preview()

    def on_flags(self, s, e):
        if self.busy:
            return
        self.update_enabled()
        self.preview()

    def on_find(self, s, e):
        text = (self.tbFind.Text or u'').strip().lower()
        if not text:
            return
        hits = [r for r in self.vis() if text in r.old.lower() or text in r.name.lower()]
        self.reselect(hits)
        if hits:
            self.lbSheets.ScrollIntoView(hits[0].item)

    def set_status(self, text, kind):
        self.tbStatus.Text = text
        self.tbStatus.Foreground = forms._brush({'err': forms.RED, 'ok': forms.GREEN}.get(kind, forms.MUTE))

    def preview(self):
        st, problems = self.settings()
        live = [r for r in self.rows if not r.deleted]          # удаляемые номер не держат
        scope = [r for r in self.scope_rows() if not r.deleted]
        sids = set(id(r) for r in scope)
        scope += [r for r in live if r.sheet is None and id(r) not in sids]   # копии нумеруются всегда
        scope.sort(key=lambda r: live.index(r))
        idx = dict((id(r), i) for i, r in enumerate(live))
        ok = False
        new, errors = {}, {}
        if not problems:
            new, errors = plan([r.old for r in live], [idx[id(r)] for r in scope], st,
                               [r.group for r in live], [r.name for r in live])
        in_scope = set(id(r) for r in scope)
        vis = set(id(r) for r in self.vis())
        changed = 0
        for r in self.rows:
            if r.deleted and id(r) in vis:
                r.grid.Opacity = 0.55
                r.tb_new.Text = u'удалить'
                r.tb_new.FontWeight = FontWeights.SemiBold
                r.tb_new.ToolTip = None
                r.strip.Background = forms._brush(C_RED)
        for i, r in enumerate(live):
            if id(r) not in vis:
                continue
            if id(r) not in in_scope:
                r.grid.Opacity = 0.45
                r.tb_new.Text = u''
                r.strip.Background = None
                continue
            r.grid.Opacity = 1.0
            if problems:
                r.tb_new.Text = u'?'
                r.strip.Background = None
                continue
            n = new[i]
            if i in errors:
                r.tb_new.Text = u'⚠ ' + vis_space(n)
                r.tb_new.FontWeight = FontWeights.Normal
                r.tb_new.ToolTip = errors[i]
                r.strip.Background = forms._brush(C_RED)
            else:
                r.tb_new.Text = vis_space(n)
                r.tb_new.ToolTip = None
                if n != r.old:
                    r.tb_new.FontWeight = FontWeights.SemiBold
                    r.strip.Background = forms._brush(C_CHANGED)
                    changed += 1
                else:
                    r.tb_new.FontWeight = FontWeights.Normal
                    r.strip.Background = None
        if problems:
            self.set_status(u'⚠ ' + u'; '.join(problems), 'err')
        elif not scope:
            self.set_status(u'Выдели листы в списке (или сними «Только выделенные»).', 'mute')
        elif errors:
            first = sorted(errors)[0]
            hint = u'' if st['pad'] else u'\nЕсли такие номера должны повторяться в разных разделах — включи «Занятый номер — добавить пробел в конце».'
            self.set_status(u'⚠ Конфликтов: %d — например, лист %s: %s%s'
                            % (len(errors), vis_space(live[first].old) or u'(копия)', errors[first], hint), 'err')
        else:
            nr = len(self.renames())
            nc = len([r for r in live if r.sheet is None])
            nd = len([r for r in self.rows if r.deleted])
            extra = u''.join(t for t in ((u' · переименуется: %d' % nr) if nr else u'',
                                          (u' · новых копий: %d' % nc) if nc else u'',
                                          (u' · удалится: %d' % nd) if nd else u''))
            chg = changed - nc
            if chg <= 0 and not extra:
                self.set_status(u'Листов в работе: %d · номера не меняются.' % len(scope), 'mute')
            else:
                ok = True
                self.set_status(u'Листов в работе: %d · %s%s' % (
                    len(scope), (u'изменится: %d' % chg) if chg > 0 else u'номера не меняются', extra),
                    'err' if nd else 'ok')
        self.btnOk.IsEnabled = ok
        self._plan = (new, scope, idx) if ok else None

    def on_ok(self, s, e):
        if not self._plan:
            return
        new, scope, idx = self._plan
        self.end_rename(True)
        self.result = [(r.sheet, r.old, new[idx[id(r)]]) for r in scope
                       if r.sheet is not None and new[idx[id(r)]] != r.old]
        self.copies = [(r.src, r.opt, new[idx[id(r)]], r.rename if r.rename is not None else r.name)
                       for r in scope if r.sheet is None]
        self.deleted = [r.sheet for r in self.rows if r.deleted]
        self.renamed = self.renames()
        self.Close()


# ======================================================================
#  Запуск
# ======================================================================
def read_groups(sheets):
    """Папки листов в диспетчере проекта (текущая организация): id листа → (папка, подпапка, …)."""
    res = {}
    try:
        org = DB.BrowserOrganization.GetCurrentBrowserOrganizationForSheets(doc)
    except Exception:
        org = None
    for sh in sheets:
        try:
            res[sh.Id.Value] = tuple(fi.Name for fi in org.GetFolderItems(sh.Id))
        except Exception:
            res[sh.Id.Value] = ()
    for sh in sheets:   # Revit 2025: коллекция листов — первым уровнем группы (db 22.10)
        try:
            c = doc.GetElement(sh.SheetCollectionId)
            cn = c.Name if c is not None else u'(без коллекции)'
        except Exception:
            cn = u''
        res[sh.Id.Value] = (cn,) + res.get(sh.Id.Value, ())
    return res


def apply_numbers(changes, renamed=(), copies=(), deleted=()):
    """changes: [(sheet, старый, новый)] → записать в одной транзакции."""
    all_numbers = [sh.SheetNumber for sh in
                   DB.FilteredElementCollector(doc).OfClass(DB.ViewSheet).ToElements()]
    tmp = temp_names(len(changes) + len(copies), all_numbers)
    made = []
    with revit.Transaction(u'Перенумеровать листы'):
        for sheet in deleted:            # удаление — первым: освобождает номера
            doc.Delete(sheet.Id)
        for (sheet, old, new), t in zip(changes, tmp):
            sheet.SheetNumber = t       # освободить номера (перестановки, сдвиги)
        for (src, opt, new, name), t in zip(copies, tmp[len(changes):]):
            opt = best_opt(src, opt) or opt
            en = dict((k, e) for k, x, e in DUP_OPTS)[opt]
            sh = doc.GetElement(src.Duplicate(getattr(DB.SheetDuplicateOption, en)))
            sh.SheetNumber = t
            made.append((sh, new, name))
        for sheet, old, new in changes:
            sheet.SheetNumber = new
        for sh, new, name in made:
            sh.SheetNumber = new
            sh.Name = name
        for sheet, old_name, new_name in renamed:   # названия (двойной щелчок по названию в окне)
            sheet.Name = new_name
    return made


def main():
    sheets = list(DB.FilteredElementCollector(doc).OfClass(DB.ViewSheet).ToElements())
    if not sheets:
        forms.alert(u'В проекте нет листов.', title=u'Перенумеровать листы')
        return
    pre = []
    for eid in uidoc.Selection.GetElementIds():
        if isinstance(doc.GetElement(eid), DB.ViewSheet):
            pre.append(eid.Value)
    av = uidoc.ActiveView
    active_id = av.Id.Value if isinstance(av, DB.ViewSheet) else None
    w = RenumberWindow(sheets, read_groups(sheets), pre, active_id)
    w.ShowDialog()
    if not w.result and not w.renamed and not w.copies and not w.deleted:
        return
    if w.deleted:   # удаление — только отдельным подтверждением со списком (общее правило кнопок)
        lst = u'\n'.join(u'• %s  %s' % (sh.SheetNumber, sh.Name) for sh in w.deleted[:25])
        if len(w.deleted) > 25:
            lst += u'\n… ещё %d' % (len(w.deleted) - 25)
        if not forms.alert(u'Удалить листы (%d)?\n\n%s\n\nВиды с этих листов останутся в модели. Отмена — Ctrl+Z.'
                           % (len(w.deleted), lst), title=u'Перенумеровать листы', ok=False, yes=True, no=True):
            return
    try:
        made = apply_numbers(w.result or [], w.renamed, w.copies, w.deleted)
    except Exception as ex:
        forms.alert(u'Не удалось перенумеровать — изменения отменены.\n\n%s' % ex,
                    title=u'Перенумеровать листы')
        return
    out = script.get_output()
    forms.style_output(out)
    if w.result:
        out.print_md(u'**Перенумеровано листов:** %d' % len(w.result))
        out.print_table(table_data=[[vis_space(o), vis_space(n)] for _, o, n in w.result],
                        columns=[u'Было', u'Стало'])
    if made:
        out.print_md(u'**Создано копий:** %d' % len(made))
        out.print_table(table_data=[[vis_space(n), nm] for sh, n, nm in made], columns=[u'Номер', u'Название'])
    if w.deleted:
        out.print_md(u'**Удалено листов:** %d' % len(w.deleted))
    if w.renamed:
        out.print_md(u'**Переименовано листов:** %d' % len(w.renamed))
        out.print_table(table_data=[[o, n] for _, o, n in w.renamed], columns=[u'Было', u'Стало'])


if __name__ == '__main__':
    main()
