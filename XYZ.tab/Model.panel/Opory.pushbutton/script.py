# -*- coding: utf-8 -*-
"""Опоры: опорные конструкции под оборудование и трассы — по техкарте производителя.

Выделить оборудование (наружные блоки, вентустановки, вентиляторы) или прямые участки трасс
(воздуховоды, трубы, лотки) → кнопка. Окно: файл техкарты (правила подбора — внешний JSON, его
правит проектировщик), проба «что станет» (таблица + показ в модели), «Применить» ставит семейства.
Пока не нажато «Применить», модель не меняется. Одна транзакция — отмена Ctrl+Z.
Логика — lib/xyz_opory.py; от производителя и семейств код не зависит, всё в техкарте.
Окно по стандарту «Объёмов»: тянется, Ctrl+колесо — масштаб, размер запоминается, ошибки — окном.
"""
import io
import os
import sys
import clr
import System
from System.Collections.Generic import List
from pyrevit import revit, DB
from Autodesk.Revit.UI.Selection import ObjectType
from Autodesk.Revit.Exceptions import OperationCanceledException
import xyz_forms as forms
sys.modules.pop('xyz_opory', None)
import xyz_opory as O
clr.AddReference('System.Data')
from System.Data import DataTable
from System.Windows.Media import SolidColorBrush, Color
from Microsoft.Win32 import OpenFileDialog, SaveFileDialog

doc = revit.doc
uidoc = revit.uidoc
TITLE = u'Опоры'


def guarded(fn):
    """Ошибка в обработчике — окном с текстом, а не «нажал — ничего»."""
    def wrap(*a):
        try:
            return fn(*a)
        except Exception:
            import traceback
            forms.alert(u'Ошибка — действие не выполнено:\n\n' + traceback.format_exc()[-1500:], title=TITLE)
    return wrap


def take_selection():
    els = [doc.GetElement(i) for i in uidoc.Selection.GetElementIds()]
    els = [e for e in els if e is not None and e.Category is not None]
    if els:
        return els
    try:
        refs = uidoc.Selection.PickObjects(
            ObjectType.Element, u'Опоры: выберите оборудование или участки трасс и нажмите «Готово»')
    except OperationCanceledException:
        return []
    return [doc.GetElement(r.ElementId) for r in refs]


COLS = [(u'Id', 'i'), (u'Объект', 's'), (u'Что', 's'), (u'Габарит, мм', 's'), (u'Масса, кг', 's'),
        (u'Комплект', 's'), (u'Типоразмер', 's'), (u'Шт', 'i'), (u'Верх опоры, мм', 's'),
        (u'До основания, мм', 's'), (u'Статус', 's'), (u'Примечание', 's')]


def table(cols, rows):
    t = DataTable()
    for name, typ in cols:
        t.Columns.Add(name, System.Int64 if typ == 'i' else System.String)
    for r in rows:
        dr = t.NewRow()
        for k, (name, typ) in enumerate(cols):
            v = r[k]
            if v is None:
                dr[name] = System.DBNull.Value
            elif typ == 'i':
                dr[name] = System.Int64(v)
            else:
                dr[name] = u'%s' % v
        t.Rows.Add(dr)
    return t


def probe_table(rows):
    data = []
    for r in rows:
        data.append([r['id'], r['obj'], r['kind'], r['size'], O.fmt(r['mass']) if r['mass'] else u'—',
                     r['kit'], r['type'] + (u'  (новый тип)' if r['new_type'] else u''), r['count'],
                     O.fmt(r['top']) if r['top'] is not None else u'',
                     O.fmt(r['base']) if r['base'] is not None else u'', r['status'], r['note']])
    return table(COLS, data)


def total_table(rows):
    data = []
    for (kit, typ, new), n in sorted(O.totals(rows).items()):
        data.append([kit, typ, u'будет создан' if new else u'есть в проекте', n])
    return table([(u'Комплект', 's'), (u'Типоразмер', 's'), (u'Тип', 's'), (u'Шт', 'i')], data)


XAML = u'''
<Window xmlns="http://schemas.microsoft.com/winfx/2006/xaml/presentation"
        xmlns:x="http://schemas.microsoft.com/winfx/2006/xaml"
        Title="ОПОРЫ" Width="1100" Height="620" MinWidth="720" MinHeight="420"
        WindowStartupLocation="CenterScreen" FontFamily="Segoe UI" FontSize="13">
  <Window.Resources>
    <ResourceDictionary>
      <ResourceDictionary.MergedDictionaries>
        <ResourceDictionary Source="XYZ_THEME_URI"/>
      </ResourceDictionary.MergedDictionaries>
    </ResourceDictionary>
  </Window.Resources>
  <Grid Margin="12">
    <Grid.RowDefinitions><RowDefinition Height="*"/><RowDefinition Height="Auto"/><RowDefinition Height="Auto"/></Grid.RowDefinitions>
    <Grid x:Name="root" Grid.Row="0">
      <Grid.RowDefinitions><RowDefinition Height="Auto"/><RowDefinition Height="Auto"/><RowDefinition Height="*" MinHeight="140"/></Grid.RowDefinitions>
      <GroupBox Header="Техкарта производителя — правила подбора" Grid.Row="0">
        <StackPanel>
          <TextBlock x:Name="tbCard" TextWrapping="Wrap" FontWeight="SemiBold"/>
          <TextBlock x:Name="tbPath" TextWrapping="Wrap" FontSize="11" Foreground="#7A847C" Margin="0,2,0,6"/>
          <WrapPanel>
            <Button x:Name="btnOpen" Content="Открыть…" Padding="10,3" Margin="0,0,6,4" ToolTip="Выбрать другой файл техкарты (JSON). Выбор запоминается для этой модели"/>
            <Button x:Name="btnEdit" Content="Править в Блокноте" Padding="10,3" Margin="0,0,6,4" ToolTip="Открыть файл техкарты: правила, семейства, шаг, формулы. После правки — «Перечитать»"/>
            <Button x:Name="btnReload" Content="Перечитать" Padding="10,3" Margin="0,0,6,4" ToolTip="Прочитать файл заново и пересчитать пробу"/>
            <Button x:Name="btnSaveAs" Content="Сохранить как…" Padding="10,3" Margin="0,0,6,4" ToolTip="Копия техкарты в свой файл — под другого производителя"/>
            <Button x:Name="btnStd" Content="Стандартная" Padding="10,3" Margin="0,0,6,4" ToolTip="Техкарта, которая идёт с плагином"/>
            <Button x:Name="btnTpl" Content="Шаблон" Padding="10,3" Margin="0,0,6,4" ToolTip="Пустой шаблон техкарты с образцами записи: оборудование, воздуховод, труба"/>
          </WrapPanel>
        </StackPanel>
      </GroupBox>
      <WrapPanel Grid.Row="1" Margin="0,8,0,6">
        <TextBlock Text="Высота комплекта H, мм:" VerticalAlignment="Center" Foreground="#7A847C"/>
        <TextBox x:Name="tbH" Width="64" Margin="8,0,0,0" ToolTip="Пусто — по техкарте. Число — своя высота для всех выбранных"/>
        <TextBlock x:Name="tbScope" VerticalAlignment="Center" Margin="18,0,0,0" Foreground="#7A847C"/>
      </WrapPanel>
      <TabControl x:Name="tabs" Grid.Row="2">
        <TabItem Header="Проба: что станет">
          <DataGrid x:Name="dgProbe" IsReadOnly="True" AutoGenerateColumns="True" CanUserAddRows="False" SelectionMode="Extended"/>
        </TabItem>
        <TabItem Header="Итог">
          <DataGrid x:Name="dgTotal" IsReadOnly="True" AutoGenerateColumns="True" CanUserAddRows="False"/>
        </TabItem>
      </TabControl>
    </Grid>
    <StackPanel Grid.Row="1" Orientation="Horizontal" HorizontalAlignment="Right" Margin="0,10,0,0">
      <Button x:Name="btnShow" Content="Показать в модели" Margin="0,0,6,0" ToolTip="Выделить в Revit объекты отмеченных строк (без строк — все «поставить»). Двойной щелчок по строке — то же"/>
      <Button x:Name="btnExcel" Content="В Excel" Margin="0,0,6,0"/>
      <Button x:Name="btnApply" Content="Применить" IsDefault="True" Margin="0,0,6,0"/>
      <Button x:Name="btnClose" Content="Закрыть"/>
    </StackPanel>
    <TextBlock x:Name="tbStatus" Grid.Row="2" TextWrapping="Wrap" Margin="0,8,0,0"/>
  </Grid>
</Window>
'''


class OporyWindow(forms.WPFWindow):
    def __init__(self, elements):
        forms.WPFWindow.__init__(self, XAML.replace(u'XYZ_THEME_URI', forms.theme_uri()), literal_string=True)
        forms.theme(self, TITLE, u'Опорные конструкции под оборудование и трассы — по техкарте производителя. '
                                 u'Проба → «Применить»', merge=False)
        self.elements = elements
        self.view3d = O.find_3d(doc)
        self.path = O.current_path(doc)
        self.card = None
        self.rows = []
        self.made = []
        self.btnOpen.Click += self.on_open
        self.btnEdit.Click += self.on_edit
        self.btnReload.Click += self.on_reload
        self.btnSaveAs.Click += self.on_save_as
        self.btnStd.Click += self.on_std
        self.btnTpl.Click += self.on_tpl
        self.btnShow.Click += self.on_show
        self.btnExcel.Click += self.on_excel
        self.btnApply.Click += self.on_apply
        self.btnClose.Click += lambda s, e: self.Close()
        self.dgProbe.MouseDoubleClick += self.on_show
        self.tbH.LostFocus += self.on_reload
        self.tbH.KeyDown += self.on_h_key
        self.load(self.path)

    # ------------------------------------------------------------ техкарта и проба
    def status(self, text, bad=False):
        self.tbStatus.Foreground = SolidColorBrush(Color.FromRgb(198, 40, 40) if bad else Color.FromRgb(46, 125, 50))
        self.tbStatus.Text = text

    def load(self, path):
        try:
            card, problems = O.load_card(path)
        except Exception as ex:
            self.card = None
            self.tbCard.Text = u'Техкарта не читается'
            self.tbPath.Text = path
            self.fill([])
            return self.status(u'Файл техкарты не читается: %s' % ex, True)
        self.path, self.card = path, card
        self.tbCard.Text = card.get(u'название', u'(без названия)')
        self.tbPath.Text = u'%s\n%s' % (path, card.get(u'источник', u''))
        self.recount(problems)

    def overrides(self):
        s = self.tbH.Text.replace(u',', u'.').strip()
        if not s:
            return {}
        try:
            return {u'H': float(s)}
        except ValueError:
            return None

    def recount(self, problems=None):
        ov = self.overrides()
        if ov is None:
            return self.status(u'Высота — число в мм или пусто.', True)
        rows = O.probe(doc, self.elements, self.card, self.view3d, ov)
        self.fill(rows)
        n_ok = len([r for r in rows if r['status'] == O.STATUS_OK])
        pcs = sum(r['count'] for r in rows if r['status'] == O.STATUS_OK)
        n_has = len([r for r in rows if r['status'] == O.STATUS_HAS])
        rest = len(rows) - n_ok - n_has
        self.tbScope.Text = u'Выбрано объектов: %d' % len(rows)
        self.btnApply.IsEnabled = n_ok > 0
        txt = u'Проба: поставить под %d объект(ов) — %d шт.; уже стоит — %d; без правила или не выходит — %d. ' \
              u'Модель не менялась.' % (n_ok, pcs, n_has, rest)
        if problems:
            txt += u'\nЗамечания к техкарте: ' + u'; '.join(problems)
        self.status(txt, bool(problems) or (n_ok == 0))

    def fill(self, rows):
        self.rows = rows
        self.t_probe = probe_table(rows)
        self.t_total = total_table(rows)
        self.dgProbe.ItemsSource = self.t_probe.DefaultView
        self.dgTotal.ItemsSource = self.t_total.DefaultView

    # ------------------------------------------------------------ кнопки техкарты
    def on_open(self, s, e):
        d = OpenFileDialog()
        d.Filter = u'Техкарта (*.json)|*.json'
        d.InitialDirectory = os.path.dirname(self.path)
        if d.ShowDialog(self) == True:      # noqa: E712
            self.load(d.FileName)
            if self.card is not None:
                O.remember_path(doc, self.path)

    def on_edit(self, s, e):
        if self.path.startswith(O.CARDS_DIR):
            self.status(u'Это техкарта из поставки плагина — при обновлении плагина она заменится. '
                        u'Для своих правил: «Сохранить как…» и правьте копию.', True)
        System.Diagnostics.Process.Start('notepad.exe', u'"%s"' % self.path)

    def on_reload(self, s, e):
        if self.card is None:
            return self.load(self.path)
        self.load(self.path)

    def on_h_key(self, s, e):
        if str(e.Key) in ('Return', 'Enter'):
            self.on_reload(s, e)
            e.Handled = True

    def on_save_as(self, s, e):
        if self.card is None:
            return
        d = SaveFileDialog()
        d.Filter = u'Техкарта (*.json)|*.json'
        d.FileName = u'Опоры_техкарта_%s.json' % doc.Title
        if d.ShowDialog(self) == True:      # noqa: E712
            O.save_card(self.card, d.FileName)
            self.load(d.FileName)
            O.remember_path(doc, self.path)
            self.status(u'Техкарта сохранена и выбрана для этой модели: %s' % d.FileName)

    def on_std(self, s, e):
        self.load(O.DEFAULT_CARD)
        O.remember_path(doc, self.path)

    def on_tpl(self, s, e):
        d = SaveFileDialog()
        d.Filter = u'Техкарта (*.json)|*.json'
        d.FileName = u'Опоры_техкарта_новая.json'
        if d.ShowDialog(self) == True:      # noqa: E712
            card, _ = O.load_card(O.TEMPLATE_CARD)
            O.save_card(card, d.FileName)
            System.Diagnostics.Process.Start('notepad.exe', u'"%s"' % d.FileName)
            self.status(u'Шаблон сохранён: %s. Заполните по каталогу производителя и выберите через «Открыть…».' % d.FileName)

    # ------------------------------------------------------------ показ, Excel, применение
    def picked_ids(self):
        ids = []
        for it in self.dgProbe.SelectedItems:
            try:
                ids.append(int(it[u'Id']))
            except Exception:
                pass
        if not ids:
            ids = [r['id'] for r in self.rows if r['status'] == O.STATUS_OK] or [r['id'] for r in self.rows]
        return ids

    def on_show(self, s, e):
        ids = self.picked_ids() + list(self.made)
        lst = List[DB.ElementId]([DB.ElementId(System.Int64(i)) for i in ids])
        uidoc.Selection.SetElementIds(lst)
        try:
            uidoc.ShowElements(lst)
        except Exception:
            pass
        self.status(u'В модели выделено объектов: %d.' % len(ids))

    def on_excel(self, s, e):
        t = self.t_total if self.tabs.SelectedIndex == 1 else self.t_probe
        path = os.path.join(os.environ.get('TEMP', u'.'), u'XYZ_Опоры_%d.csv' % self.tabs.SelectedIndex)
        lines = [u';'.join(c.ColumnName for c in t.Columns)]
        for r in t.Rows:
            vals = []
            for c in t.Columns:
                v = r[c.ColumnName]
                vals.append((u'' if isinstance(v, System.DBNull) else (u'%s' % v)).replace(u';', u','))
            lines.append(u';'.join(vals))
        with io.open(path, 'w', encoding='utf-8-sig') as f:
            f.write(u'\r\n'.join(lines))
        try:
            os.startfile(path)
        except Exception:
            forms.alert(path, title=u'Сохранено')

    def on_apply(self, s, e):
        todo = [r for r in self.rows if r['status'] == O.STATUS_OK]
        if not todo:
            return self.status(u'Ставить нечего.', True)
        with revit.Transaction(u'Опоры: поставить по техкарте'):
            made, log = O.apply(doc, todo, self.card)
        self.made = made
        self.recount()
        self.status(u'Поставлено: %d шт. под %d объект(ов). Отмена — Ctrl+Z в Revit.' % (len(made), len(todo))
                    + (u'\n' + u'\n'.join(log) if log else u''), not made)
        if made:
            lst = List[DB.ElementId]([DB.ElementId(System.Int64(i)) for i in made])
            uidoc.Selection.SetElementIds(lst)
            try:
                uidoc.RefreshActiveView()
            except Exception:
                pass


for _n in ('on_open', 'on_edit', 'on_reload', 'on_save_as', 'on_std', 'on_tpl', 'on_show', 'on_excel', 'on_apply',
           'on_h_key'):
    setattr(OporyWindow, _n, guarded(getattr(OporyWindow, _n)))


def main():
    els = take_selection()
    if not els:
        forms.alert(u'Выделите оборудование (наружные блоки, вентустановки) или прямые участки трасс '
                    u'и нажмите кнопку ещё раз.', title=TITLE)
        return
    w = OporyWindow(els)
    forms.adaptive(w, 'opory', root=w.root, min_w=720, min_h=420)
    w.ShowDialog()


main()
