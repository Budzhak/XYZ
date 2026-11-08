# XYZ — pyRevit extension for MEP designers

🇷🇺 [Русская версия](README.md)

📢 **Telegram:** [@xyz_for_revit](https://t.me/xyz_for_revit) — news, tips and button demos

![XYZ](docs/img/icons_bg/XYZ.png)

MEP tools for Revit: tags, schematics, plenum families, fabrication sketches, schedules and sheet export. So that Revit routine doesn't spoil your mood, use XYZ.

> [!NOTE]
> XYZ adds its own **XYZ** tab to the Revit ribbon. Panels: **Inspect** (find and select) · **Model** · **Explode** (exploded views) · **Annotate** · **Publish** · **Exchange** (Excel, screen recording).
> Button titles and tooltips are available in English and Russian; pyRevit shows them in its own UI language. Command windows and the detailed button docs (`docs/Кнопки`) are in Russian for now.

## Installation

> [!IMPORTANT]
> Tested on **Revit 2025.4** with **pyRevit 6.1.0** and **pyRevit 7.0.0** (7.0.0.26278). Other Revit and pyRevit versions have not been tested.

**1. pyRevit 6.1.0 or 7.0.0.** Close Revit, download and run the installer (pyRevit 7 — see [pyRevit releases](https://github.com/pyrevitlabs/pyRevit/releases)):
- [pyRevit_6.1.0.26047_signed.exe](https://github.com/pyrevitlabs/pyRevit/releases/download/v6.1.0.26047%2B2255/pyRevit_6.1.0.26047_signed.exe) — regular per-user install;
- all files of this version — on the [6.1.0 release page](https://github.com/pyrevitlabs/pyRevit/releases/tag/v6.1.0.26047%2B2255).

Start Revit — the **pyRevit** tab appears on the ribbon.

**2. XYZ — from pyRevit.**
1. In Revit, on the **pyRevit** tab, click **Extensions** — the pyRevit Extensions Manager opens.
2. In the list of registered extensions, select **XYZ** and click **Install Extension**.
3. pyRevit downloads the extension and reloads itself — the **XYZ** tab appears.

> [!NOTE]
> If you installed XYZ manually before, close Revit and delete the old folder `%APPDATA%\pyRevit\Extensions\XYZ.extension` first.

**Fallback — manually:** at the top of this page **Code → Download ZIP**, unpack it into `%APPDATA%\pyRevit\Extensions\`, rename the folder `XYZ-main` to `XYZ.extension`, then pyRevit → **Reload**.

**3. Tab position.** The **XYZ** tab appears at the end of the ribbon. To place it right after **Insert**, set `"tab_after_insert": true` in `%APPDATA%\pyRevit\xyz_settings.json` and Reload.

**4. Vector PDF (optional).** PDF optimisation runs in a separate Python 3 ([python.org](https://www.python.org/downloads/windows/)) with:
```
py -m pip install --user pikepdf shapely numpy
```
Without them, sheets are exported by Revit as is, without optimisation.

**Update:** pyRevit → **Update** — pyRevit downloads new versions of installed extensions (including XYZ) and reloads itself. If you installed manually, download the ZIP again and replace the folder, then Reload.

> [!WARNING]
> The tools were written for specific projects and templates (ADSK shared parameters and our own `db_*` parameters). Before bulk changes — do a trial run and save the model.

## Buttons

| | Panel | Button | What it does |
|---|---|---|---|
| ![](docs/img/icons_bg/Распознать.png) | Inspect | Identify | lists the selection grouped by type, with previews |
| ![](docs/img/icons_bg/Идентификация%20фильтра.png) | Inspect | Which Filter | which view filters (including link filters) affect the selected element and their rules; switch a filter off from the window |
| ![](docs/img/icons_bg/Зафильтровать%20тип%20элемента.png) | Inspect | Filter by Type | a visibility filter for the type of the selected element, applied to the active view |
| ![](docs/img/icons_bg/Пометить.png) | Inspect | Mark | writes a mark into a parameter and creates a schedule filtered by it |
| ![](docs/img/icons_bg/Безымянные.png) | Inspect | Untagged Runs | pipe runs without a tag on the view; «Show» selects and zooms to the whole run |
| ![](docs/img/icons_bg/Равнение.png) | Model | MEP Align | pipes, ducts, cable trays: onto the reference axis, to its elevation, plumb risers |
| ![](docs/img/icons_bg/Пленум.png) | Model | Plenum | plenum box family with branch connections |
| ![](docs/img/icons_bg/Как%20у%20тебя.png) | Model | Replace by Sample | replaces an element with the type of a sample element |
| ![](docs/img/icons_bg/Прозрачные%20связи.png) | Model | Link Transparency | transparency slider for linked models (via view filters) |
| ![](docs/img/icons_bg/Беспорядочные%20связи.png) | Model | Link Parameters | adds IFC/RVT link parameters to the project so view filters can use them |
| ![](docs/img/icons_bg/Масштаб%203D.png) | Model | 3D Scale | writes «( 1 : N)» into 3D view titles on sheets |
| ![](docs/img/icons_bg/Количество.png) | Model | Quantities | quantities with allowances by rules (category + condition → how to count → allowance), with a before/after preview |
| ![](docs/img/icons_bg/Наименования.png) | Model | Naming | fills name, section and sort-key parameters from rule templates, with a before/after preview |
| ![](docs/img/icons_bg/Объёмы.png) | Model | Space Volumes | masses from MEP spaces, view colouring by a parameter, legends with totals |
| ![](docs/img/icons_bg/Эскиз.png) | Model | Fabrication Sketch | a fabrication sketch of a family in a legend view: views, axonometry, Revit dimensions, openings, notes |
| ![](docs/img/icons_bg/Cut3D.png) | Model | Crop 3D | top and bottom of a 3D section box by levels with offsets, like a view range |
| ![](docs/img/icons_bg/Вдребезги.png) | Explode | Exploded View | exploded view of the selection by its connections |
| ![](docs/img/icons_bg/По%20красоте.png) | Annotate | Tag Tools | tag alignment, tag columns, tag reset, elevation marks on exploded views; experimental modes ask for confirmation |
| | Annotate | 11 small buttons | Column, Center Leader, Even Spacing, Reset Tags, Reverse, Align Vertical, Align Horizontal, Measure Spacing, Merge Tags, Click Numbering, Clockwise Numbering |
| ![](docs/img/icons_bg/Прямая%20выноска.png) | Annotate | Straight Leader | click a tag, then where it should go — the leader becomes straight and slides along the pipe |
| ![](docs/img/icons_bg/Участки%20фреона.png) | Annotate | Refrigerant Runs | refrigerant liquid-line segments on a 3D scheme: number, size, elbows, height difference, length; a schedule per system |
| ![](docs/img/icons_bg/Опись%20листов.png) | Publish | Sheet Contents | sheet contents → Excel |
| ![](docs/img/icons_bg/По%20порядку.png) | Publish | Renumber Sheets | sheet numbers in order within Project Browser groups, with a preview |
| ![](docs/img/icons_bg/PdfVector.png) | Publish | Vector PDF | sheets to lightweight vector PDF |
| ![](docs/img/icons_bg/Посмотреть.png) | Exchange | Schedule to Excel | schedule → Excel |
| ![](docs/img/icons_bg/Забрать.png) | Exchange | Excel to Schedule | Excel → Revit |
| ![](docs/img/icons_bg/Под%20копирку.png) | Exchange | Copy Format | schedule formatting → other schedules with the same columns; Shift+click — column widths only |
| ![](docs/img/icons_bg/%D0%97%D0%B0%D0%BF%D0%B8%D1%81%D1%8C.png) | Exchange | Screen Recorder | launches XYZ Record (screen + voice) from Revit; downloads it from GitHub if missing; Shift+click — program folder |

## General rules
- **XYZ panel on the «Modify | …» tab:** when something is selected, Identify, Which Filter, Filter by Type, Tag Tools and MEP Align are also available on Revit's contextual tab.
- **Every command:** where (selection / view / model) → what (options) → before/after preview → Apply / Cancel → report. One command = one transaction, undo with **Ctrl+Z**.
- View graphics are changed with **view filters** only, never with per-element overrides.
- No network access, no bundled binaries. The model-change updater for elevation marks is off by default (`elev_marks_auto` in `xyz_settings.json`).

## License

[GPL-3.0](LICENSE). Some windows are based on [pyRevit](https://github.com/pyrevitlabs/pyRevit) forms (GPL-3.0).

## Feedback

Questions, bugs and ideas — in the comments under posts in the Telegram channel [@xyz_for_revit](https://t.me/xyz_for_revit) or in [Issues](https://github.com/Budzhak/XYZ/issues).

> [!TIP]
> When reporting a bug, please attach a screenshot and state your Revit (and pyRevit) version.
