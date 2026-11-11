# -*- coding: utf-8 -*-
"""Выноски к деталям (Claude по замечаниям db к узлам Глаголево, 11.11.2026).

Разнесённый 3D-вид (узел, взрыв-схема): у выделенных марок (или у всех марок вида)
- конец выноски ставится на саму деталь — на ту, что видна на виде (геометрия уже со
  смещением разноса), а не туда, где деталь стояла до разноса;
- полка выноски — строго горизонтальная или вертикальная (сторона — как стояла марка);
- марка отходит от детали на её полуширину + отступ, головы марок не налезают друг на
  друга; у края подрезки вида марка уходит в другую сторону.
Одна отмена Ctrl+Z. Марки с несколькими выносками не трогаются.
"""
import xyz_forms as forms
from Autodesk.Revit.DB import (FilteredElementCollector, IndependentTag, LeaderEndCondition,
                               Options, Solid, GeometryInstance, Transaction, View3D, XYZ)

TITLE = u'Выноски к деталям'
uidoc = __revit__.ActiveUIDocument    # noqa: F821
doc = uidoc.Document
view = doc.ActiveView

if view is None or view.IsTemplate:
    forms.alert(u'Откройте вид с марками.', title=TITLE, exitscript=True)

R, U, VD = view.RightDirection, view.UpDirection, view.ViewDirection
S = view.Scale / 304.8          # 1 мм листа в футах модели
GAP_H, GAP_V = 10.0, 9.0        # отступ марки от детали, мм листа
BOX_W, BOX_H, STEP = 9.0, 6.5, 5.0


def X(p):
    return p.DotProduct(R)


def Y(p):
    return p.DotProduct(U)


def solids(ge, out):
    if ge is None:
        return out
    for g in ge:
        if isinstance(g, Solid) and g.Volume > 1e-9:
            out.append(g)
        elif isinstance(g, GeometryInstance):
            solids(g.GetInstanceGeometry(), out)
    return out


def host_shape(el):
    """Центр видимой детали (со смещением разноса) и полуразмеры на виде."""
    opt = Options()
    opt.View = view
    ss = solids(el.get_Geometry(opt), [])
    if not ss:
        return None
    vol = 0.0
    cs = XYZ.Zero
    x0 = y0 = 1e18
    x1 = y1 = -1e18
    for s in ss:
        cs = cs + s.ComputeCentroid() * s.Volume
        vol += s.Volume
        for e in s.Edges:
            for p in e.Tessellate():
                x, y = X(p), Y(p)
                x0, x1, y0, y1 = min(x0, x), max(x1, x), min(y0, y), max(y1, y)
    c = cs / vol
    cx, cy = X(c), Y(c)
    return c, max(x1 - cx, cx - x0), max(y1 - cy, cy - y0)


def crop_xy():
    if not view.CropBoxActive:
        return None
    cb = view.CropBox
    t = cb.Transform
    xs, ys = [], []
    for p in (cb.Min, cb.Max, XYZ(cb.Min.X, cb.Max.Y, cb.Min.Z), XYZ(cb.Max.X, cb.Min.Y, cb.Min.Z)):
        w = t.OfPoint(p)
        xs.append(X(w))
        ys.append(Y(w))
    return min(xs), max(xs), min(ys), max(ys)


sel = [doc.GetElement(i) for i in uidoc.Selection.GetElementIds()]
tags = [e for e in sel if isinstance(e, IndependentTag)]
if not tags:
    tags = list(FilteredElementCollector(doc, view.Id).OfClass(IndependentTag))
if not tags:
    forms.alert(u'На виде нет марок.', title=TITLE, exitscript=True)

crop = crop_xy()
heads = []
moved = skipped = flips = 0
t = Transaction(doc, u'XYZ: ' + TITLE)
t.Start()
try:
    for tag in tags:
        refs = list(tag.GetTaggedReferences())
        if len(refs) != 1 or not tag.HasLeader:
            skipped += 1
            continue
        r = refs[0]
        host = doc.GetElement(r.ElementId)
        shp = host_shape(host) if host is not None else None
        if shp is None:
            skipped += 1
            continue
        c, hw, hh = shp
        cx, cy = X(c), Y(c)
        d = tag.TagHeadPosition - c
        dx, dy, dz = d.DotProduct(R), d.DotProduct(U), d.DotProduct(VD)
        horiz = abs(dx) >= abs(dy)
        sx = 1.0 if dx >= 0 else -1.0
        sy = 1.0 if dy >= 0 else -1.0
        ln = (hw + GAP_H * S) if horiz else (hh + GAP_V * S)
        if crop:
            if horiz and not (crop[0] < cx + sx * (ln + 6 * S) < crop[1]):
                sx = -sx
                flips += 1
            if not horiz and not (crop[2] < cy + sy * (ln + 4 * S) < crop[3]):
                sy = -sy
                flips += 1
        nx = sx * ln if horiz else 0.0
        ny = 0.0 if horiz else sy * ln
        for _ in range(20):
            hit = any(abs(hx - (cx + nx)) < BOX_W * S and abs(hy - (cy + ny)) < BOX_H * S for hx, hy in heads)
            if not hit:
                break
            if horiz:
                nx += sx * STEP * S
            else:
                ny += sy * STEP * S
        heads.append((cx + nx, cy + ny))
        end = c + (R * (sx * hw * 0.5) if horiz else U * (sy * hh * 0.5))
        tag.LeaderEndCondition = LeaderEndCondition.Free
        tag.SetLeaderEnd(r, end)
        try:
            if tag.HasLeaderElbow(r):
                tag.SetLeaderElbow(r, end)
        except Exception:
            pass
        tag.TagHeadPosition = c + R * nx + U * ny + VD * dz
        moved += 1
    t.Commit()
except Exception as ex:
    t.RollBack()
    forms.alert(u'Не получилось, изменения отменены:\n%s' % ex, title=TITLE, exitscript=True)

forms.alert(u'Выноски поставлены на детали: %d.\nПропущено (несколько выносок или деталь без геометрии): %d.'
            u'\nУ края вида марка перевёрнута на другую сторону: %d.\n\nОдна отмена — Ctrl+Z.'
            % (moved, skipped, flips), title=TITLE)
