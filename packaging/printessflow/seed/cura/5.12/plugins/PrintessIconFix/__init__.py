import ctypes
from ctypes import wintypes

from UM.Extension import Extension
from UM.Application import Application
from UM.Resources import Resources
from UM.Logger import Logger


class PrintessIconFix(Extension):
    def __init__(self):
        super().__init__()
        Application.getInstance().engineCreatedSignal.connect(self._setIcon)

    # ------------------------------------------------------------------
    # Called once the QML engine (and main window) are ready.
    # We apply the icon immediately AND schedule a second pass so we win
    # any race against Qt's own lazy WM_SETICON on window-show.
    # ------------------------------------------------------------------
    def _setIcon(self):
        try:
            ico_path = Resources.getPath(Resources.Images, "printess.ico")
            Logger.log("d", "PrintessIconFix: ico_path=%s", ico_path)
            if not ico_path:
                Logger.log("w", "PrintessIconFix: printess.ico not found")
                return

            window = Application.getInstance().getMainWindow()
            if window is None:
                Logger.log("w", "PrintessIconFix: main window is None")
                return

            # 1. Change AUMID so the taskbar stops linking us to the old Cura C icon
            ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID("Printess.PrintessFlow")
            Logger.log("d", "PrintessIconFix: AUMID set")

            # 2. Update Qt's application-level icon so any Qt-internal WM_SETICON
            #    that fires later (e.g. when the splash closes) uses our logo.
            from PyQt6.QtGui import QIcon
            from PyQt6.QtWidgets import QApplication
            qt_icon = QIcon(ico_path)
            Logger.log("d", "PrintessIconFix: qt_icon null=%s", qt_icon.isNull())
            if not qt_icon.isNull():
                QApplication.setWindowIcon(qt_icon)
                try:
                    window.setIcon(qt_icon)
                except Exception as e2:
                    Logger.log("w", "PrintessIconFix: window.setIcon: %s", str(e2))

            # 3. Apply WM_SETICON now (covers the case where window is already shown)
            self._applyWmSetIcon(ico_path, int(window.winId()))

            # 4. Apply again after 1.5 s — by then the splash has closed and Qt has
            #    done its own window-show icon update; we overwrite it.
            from PyQt6.QtCore import QTimer
            QTimer.singleShot(1500, lambda: self._applyWmSetIcon(ico_path, int(window.winId())))

        except Exception as e:
            Logger.log("e", "PrintessIconFix: _setIcon exception: %s", str(e))

    def _applyWmSetIcon(self, ico_path, hwnd):
        try:
            user32 = ctypes.windll.user32
            user32.LoadImageW.argtypes = [
                wintypes.HANDLE, ctypes.c_wchar_p, wintypes.UINT,
                ctypes.c_int, ctypes.c_int, wintypes.UINT,
            ]
            user32.LoadImageW.restype = wintypes.HANDLE
            user32.SendMessageW.argtypes = [wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM]
            user32.SendMessageW.restype = ctypes.c_long
            user32.SetClassLongPtrW.argtypes = [wintypes.HWND, ctypes.c_int, wintypes.HANDLE]
            user32.SetClassLongPtrW.restype = wintypes.HANDLE

            IMAGE_ICON      = 1
            LR_LOADFROMFILE = 0x0010
            LR_DEFAULTSIZE  = 0x0040
            WM_SETICON      = 0x0080
            ICON_SMALL      = 0
            ICON_BIG        = 1
            GCL_HICON       = -14
            GCL_HICONSM     = -34

            hBig   = user32.LoadImageW(None, ico_path, IMAGE_ICON, 0,  0,  LR_LOADFROMFILE | LR_DEFAULTSIZE)
            hSmall = user32.LoadImageW(None, ico_path, IMAGE_ICON, 16, 16, LR_LOADFROMFILE)

            if not hBig:
                Logger.log("e", "PrintessIconFix: LoadImage failed (err %d)", ctypes.GetLastError())
                return

            # Window-specific icon (drives WM_GETICON, which the taskbar queries)
            user32.SendMessageW(hwnd, WM_SETICON, ICON_BIG,   hBig)
            user32.SendMessageW(hwnd, WM_SETICON, ICON_SMALL, hSmall or hBig)

            # Window-class icon (fallback used when no window-specific icon is set)
            user32.SetClassLongPtrW(hwnd, GCL_HICON,   hBig)
            user32.SetClassLongPtrW(hwnd, GCL_HICONSM, hSmall or hBig)

            Logger.log("i", "PrintessIconFix: WM_SETICON + class icon applied (hwnd=%d)", hwnd)

        except Exception as e:
            Logger.log("e", "PrintessIconFix: _applyWmSetIcon exception: %s", str(e))


def getMetaData():
    return {}


def register(app):
    return {"extension": PrintessIconFix()}
