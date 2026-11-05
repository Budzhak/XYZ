# -*- coding: utf-8 -*-
"""Как у тебя: элемент получает тип образца.
Тот же класс элементов — ChangeTypeId: поворот, основа, отметка, соединения и марки сохраняются.
Иначе — новый экземпляр в той же точке с тем же поворотом и отметкой, старый удаляется.
v2 · 05.11.2026 — сохранение поворота (раньше повёрнутый элемент вставал в стену)."""
import math
from Autodesk.Revit.DB import *
from Autodesk.Revit.UI.Selection import ObjectType
from pyrevit import revit
import xyz_forms as forms   # единый стиль окон XYZ (lib/xyz_forms.py)

doc = revit.doc
uidoc = revit.uidoc

try:
    src = doc.GetElement(uidoc.Selection.PickObject(ObjectType.Element, "Выберите эталонный элемент"))
    src_type = doc.GetElement(src.GetTypeId())
    trg = doc.GetElement(uidoc.Selection.PickObject(ObjectType.Element, "Выберите элемент для замены"))

    with revit.Transaction('Как у тебя'):
        if not src_type.IsActive:
            src_type.Activate()
            doc.Regenerate()
        done = False
        if src.Category and trg.Category and src.Category.Id == trg.Category.Id:
            try:
                if src_type.Id in trg.GetValidTypes():
                    trg.ChangeTypeId(src_type.Id)
                    done = True
            except Exception:
                done = False
        if not done:
            if not hasattr(trg.Location, 'Point'):
                forms.alert('Элемент не имеет точки вставки!', exitscript=True)
            pt = trg.Location.Point
            rot = trg.Location.Rotation if hasattr(trg.Location, 'Rotation') else 0.0
            level = doc.GetElement(trg.LevelId)
            off = trg.get_Parameter(BuiltInParameter.INSTANCE_FREE_HOST_OFFSET_PARAM)
            off_val = off.AsDouble() if off else 0.0
            new_inst = doc.Create.NewFamilyInstance(pt, src_type, level, Structure.StructuralType.NonStructural)
            if abs(rot) > 1e-9:
                axis = Line.CreateBound(pt, pt + XYZ.BasisZ)
                ElementTransformUtils.RotateElement(doc, new_inst.Id, axis, rot)
            try:
                if trg.FacingFlipped != new_inst.FacingFlipped and new_inst.CanFlipFacing:
                    new_inst.flipFacing()
                if trg.HandFlipped != new_inst.HandFlipped and new_inst.CanFlipHand:
                    new_inst.flipHand()
            except Exception:
                pass
            new_off = new_inst.get_Parameter(BuiltInParameter.INSTANCE_FREE_HOST_OFFSET_PARAM)
            if new_off and not new_off.IsReadOnly:
                new_off.Set(off_val)
            doc.Delete(trg.Id)

    forms.alert('✅ Замена выполнена успешно!', title='Готово')

except Exception as e:
    if 'Operation' in type(e).__name__ or 'cancel' in str(e).lower():
        pass
    else:
        forms.alert('❌ Ошибка: {}'.format(str(e)), title='Ошибка')
