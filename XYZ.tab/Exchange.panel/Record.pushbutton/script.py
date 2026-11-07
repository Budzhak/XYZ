# -*- coding: utf-8 -*-
"""Запись — запуск XYZ Записи (запись экрана со звуком) прямо из Revit.

Ищет программу: <XYZ.extension>\\bin\\XYZ Запись, %LOCALAPPDATA%\\XYZ\\Record.
Нет — скачивает портативный архив с GitHub (Budzhak/XYZ-Record) в %LOCALAPPDATA%\\XYZ\\Record
и запускает. Shift+щелчок — открыть папку программы.
"""
import os
import clr
clr.AddReference('System')
clr.AddReference('System.IO.Compression')
clr.AddReference('System.IO.Compression.FileSystem')
from System.Diagnostics import Process, ProcessStartInfo
from System.Net import WebClient, ServicePointManager, SecurityProtocolType
from System.IO.Compression import ZipFile

__title__ = 'Запись'
EXE = u'XYZ Запись.exe'
ZIP_URL = u'https://github.com/Budzhak/XYZ-Record/raw/main/XYZ-Record_portable_v19.10.zip'
REPO_URL = u'https://github.com/Budzhak/XYZ-Record'

HERE = os.path.dirname(os.path.abspath(__file__))
EXT = os.path.abspath(os.path.join(HERE, u'..', u'..', u'..'))
LOCAL = os.path.join(os.environ.get('LOCALAPPDATA', os.path.expanduser('~')), u'XYZ', u'Record')


def find_exe():
    for root in (os.path.join(EXT, u'bin', u'XYZ Запись'), LOCAL):
        if not os.path.isdir(root):
            continue
        for d, _subs, files in os.walk(root):
            if EXE in files:
                return os.path.join(d, EXE)
    return None


def download():
    import xyz_forms as forms
    if not forms.alert(u'XYZ Запись не найдена на этом компьютере.\n\nСкачать портативную версию с GitHub '
                       u'(около 30 МБ) в\n%s ?' % LOCAL, title=__title__, yes=True, no=True):
        return None
    if not os.path.isdir(LOCAL):
        os.makedirs(LOCAL)
    zp = os.path.join(LOCAL, u'XYZ-Record_portable.zip')
    try:
        ServicePointManager.SecurityProtocol = SecurityProtocolType.Tls12
        WebClient().DownloadFile(ZIP_URL, zp)
        ZipFile.ExtractToDirectory(zp, LOCAL)
    except Exception as e:
        forms.alert(u'Скачать не вышло: %s\n\nСкачайте архив вручную: %s' % (e, REPO_URL), title=__title__)
        return None
    finally:
        try:
            os.remove(zp)
        except Exception:
            pass
    return find_exe()


def main():
    from pyrevit import EXEC_PARAMS
    exe = find_exe()
    if EXEC_PARAMS.config_mode:          # Shift+щелчок — открыть папку программы
        folder = os.path.dirname(exe) if exe else LOCAL
        if not os.path.isdir(folder):
            os.makedirs(folder)
        Process.Start(u'explorer.exe', u'"%s"' % folder)
        return
    if not exe:
        exe = download()
    if not exe:
        return
    psi = ProcessStartInfo(exe)
    psi.WorkingDirectory = os.path.dirname(exe)
    psi.UseShellExecute = True
    Process.Start(psi)        # программа однокопийная: повторный запуск покажет уже открытый прибор


main()
