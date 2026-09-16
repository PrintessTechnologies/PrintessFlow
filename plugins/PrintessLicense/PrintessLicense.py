# Copyright (c) 2026 Printess Technologies
# Released under the terms of the LGPLv3 or higher.
#
# The activation gate. PrintessFlow is a free download, and the download count
# had come to include people building the printer themselves; this asks a new
# installation for the activation code that ships with a Printessa Series
# printer before the app can be used.
#
# It is a friction gate, and is documented as one: the plugin ships as plain
# Python, so it will not stop a determined person, and the LGPL under which
# Cura is distributed means it may not try harder than this. What it does is
# make "just download it" into "ask Printess for a code".
#
# Three rules shape everything below:
#
# 1. Existing installations are never asked. Anyone who installed PrintessFlow
#    before the gate existed keeps using it, through every update, without
#    seeing this dialog once. The plugin recognizes them by a folder only
#    PrintessFlow's installer creates (see _priorInstallation) and writes a
#    license of its own for them.
#
# 2. The gate can never take the app down. Every step is wrapped: if the
#    license file cannot be read, the config folder cannot be inspected, or the
#    dialog cannot be built, the failure is logged and the app runs unlicensed
#    rather than crashing or hanging at startup on a paying customer.
#
# 3. Nothing here touches the network, scans devices, or starts a process.
#    PrintessFlow was once terminated by CrowdStrike for launch-time behavior
#    of that kind; a license check that phoned home would reopen that. Codes
#    are verified offline against a public key (LicenseCodes.py).
#
# The license is written OUTSIDE Cura's versioned config folder
# (<config parent>/printessflow/license.json, so %APPDATA%\cura\printessflow on
# Windows) so that the folder bump of a future Cura version cannot re-prompt.

import datetime
import json
import os
import re
from typing import Optional

from PyQt6.QtCore import QObject, QUrl, pyqtProperty, pyqtSignal, pyqtSlot

from UM.Application import Application
from UM.Extension import Extension
from UM.Logger import Logger
from UM.Message import Message
from UM.Resources import Resources

from . import LicenseCodes

# Installations made BEFORE this instant are treated as existing users and
# never asked for a code (see _priorInstallation for how "made before" is
# known). It is the moment the first gated build (1.1.0) was published, in
# UTC, so it means the same thing in every timezone: anyone who installed any
# earlier build, up to the minute the gated one appeared, is an existing
# user. It never changes again.
GATE_CUTOFF = datetime.datetime(2026, 9, 16, 18, 39, 57, tzinfo=datetime.timezone.utc)

# Dev switch, stricter only: ignore the existing-installation rule so the gate
# can be exercised on a computer that has run PrintessFlow before. It cannot
# be used to skip the gate.
_IGNORE_PRIOR_INSTALL_ENV = "PRINTESSFLOW_LICENSE_IGNORE_PRIOR_INSTALL"

_VERSION_DIR_RE = re.compile(r"^\d+\.\d+$")


class PrintessLicense(QObject, Extension):
    statusChanged = pyqtSignal()

    def __init__(self, parent=None):
        QObject.__init__(self, parent)
        Extension.__init__(self)

        self._dialog = None
        self._gating = False            # True while the app waits for a code
        self._quitting = False          # quitApplication runs once, whatever asks
        self._license = self._readLicense()

        self.setMenuName("License")
        self.addMenuItem("Activation...", self.showDialog)

        try:
            from cura.CuraApplication import CuraApplication
            CuraApplication.getInstance().initializationFinished.connect(self._onStarted)
        except Exception:
            Logger.logException("w", "PrintessLicense: could not hook startup; the app runs ungated")

    # ------------------------------------------------------------------
    # Startup
    # ------------------------------------------------------------------

    def _onStarted(self):
        try:
            if self._license is not None:
                Logger.log("i", "PrintessLicense: licensed (%s)", self._describe())
                return
            evidence = self._priorInstallation()
            if evidence:
                self._writeLicense({"source": "existing-installation",
                                    "granted": datetime.datetime.now().isoformat(timespec="seconds"),
                                    "evidence": evidence})
                Logger.log("i", "PrintessLicense: existing installation recognized (%s); no code needed", evidence)
                return
            self._gating = True
            self.statusChanged.emit()
            Logger.log("i", "PrintessLicense: no license; asking for an activation code")
            self.showDialog()
        except Exception:
            Logger.logException("w", "PrintessLicense: gate failed; the app runs ungated")
            self._gating = False

    # ------------------------------------------------------------------
    # QML-facing state
    # ------------------------------------------------------------------

    @pyqtProperty(bool, notify=statusChanged)
    def gating(self) -> bool:
        return self._gating

    @pyqtProperty(bool, notify=statusChanged)
    def licensed(self) -> bool:
        return self._license is not None

    @pyqtProperty(bool, notify=statusChanged)
    def quitting(self) -> bool:
        return self._quitting

    @pyqtProperty(str, notify=statusChanged)
    def statusText(self) -> str:
        if self._license is None:
            return ("PrintessFlow is licensed to owners of a Printessa Series printer. "
                    "Enter the activation code that came with your printer to continue.")
        number = self._license.get("number")
        if number:
            return "PrintessFlow is activated with license number %s." % number
        return ("PrintessFlow is activated on this computer as an existing installation. "
                "If you have an activation code for your printer, you can enter it here.")

    @pyqtSlot()
    def showDialog(self):
        try:
            from cura.CuraApplication import CuraApplication
            application = CuraApplication.getInstance()
            if self._dialog is None:
                qml_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "ActivationDialog.qml")
                self._dialog = application.createQmlComponent(qml_path, {"manager": self})
            if self._dialog is not None:
                self._dialog.show()
            elif self._gating:
                self._failOpen("the activation dialog could not be built")
        except Exception:
            Logger.logException("w", "PrintessLicense: could not open the activation dialog")
            if self._gating:
                self._failOpen("the activation dialog could not be opened")

    def _failOpen(self, why: str):
        """Rule 2: a dialog that cannot be shown must not leave the app blocked
        behind nothing. But silently is not acceptable either: a platform-
        specific QML fault would then mean no gate on that platform and nobody
        the wiser. So it is said on screen as well as in the log."""
        Logger.log("w", "PrintessLicense: %s; the app runs ungated", why)
        self._gating = False
        self.statusChanged.emit()
        try:
            Message("PrintessFlow could not show its activation dialog (%s) and is running "
                    "without activation. Please email contact@printesstechnologies.com "
                    "and attach cura.log." % why,
                    title="Activation unavailable", lifetime=0).show()
        except Exception:
            Logger.logException("w", "PrintessLicense: could not show the fail-open message")

    @pyqtSlot(str, result=str)
    def activate(self, code: str) -> str:
        """Try a code. Returns "" on success, or the message to show."""
        try:
            number = LicenseCodes.verify_code(code)
        except LicenseCodes.LicenseError as e:
            return str(e)
        except Exception:
            Logger.logException("w", "PrintessLicense: verification failed unexpectedly")
            return "The code could not be checked. See cura.log for details."
        record = {"source": "code",
                  "number": number,
                  "code": LicenseCodes.format_code(number, LicenseCodes.parse_code(code)[1]),
                  "activated": datetime.datetime.now().isoformat(timespec="seconds")}
        if not self._writeLicense(record):
            return "The license could not be saved. Check that %s is writable." % self._licensePath()
        Logger.log("i", "PrintessLicense: activated with license number %s", number)
        Message("PrintessFlow is activated with license number %s." % number,
                title="Activated", lifetime=10).show()
        self._gating = False
        self.statusChanged.emit()
        return ""

    @pyqtSlot(QUrl, result=str)
    def activateFromFile(self, url: QUrl) -> str:
        """A .lic file is the code as plain text; read it and try it."""
        path = url.toLocalFile() if isinstance(url, QUrl) else str(url)
        try:
            with open(path, "r", encoding="utf-8-sig") as f:
                text = f.read(4096)
        except Exception as e:
            return "The file could not be read: %s" % e
        return self.activate(text)

    @pyqtSlot()
    def quitApplication(self):
        """The hard exit the welcome flow uses for 'Decline and close'.

        Shutting down closes every window, which closes this dialog again,
        whose handler lands back here; the flag makes that second visit a
        no-op instead of a second shutdown.
        """
        if self._quitting:
            return
        self._quitting = True
        self.statusChanged.emit()
        Logger.log("i", "PrintessLicense: no code entered; closing")
        try:
            from cura.CuraApplication import CuraApplication
            CuraApplication.getInstance().closeApplication()
        except Exception:
            Logger.logException("w", "PrintessLicense: closeApplication failed; falling back to quit")
            Application.getInstance().quit()

    # ------------------------------------------------------------------
    # License file
    # ------------------------------------------------------------------

    def _licensePath(self) -> str:
        # Parent of the versioned folder: %APPDATA%\cura, not %APPDATA%\cura\5.12.
        config_dir = Resources.getConfigStoragePath()
        return os.path.join(os.path.dirname(config_dir), "printessflow", "license.json")

    def _readLicense(self) -> Optional[dict]:
        try:
            path = self._licensePath()
            if not os.path.isfile(path):
                return None
            with open(path, "r", encoding="utf-8") as f:
                record = json.load(f)
            if not isinstance(record, dict):
                return None
            source = record.get("source")
            if source == "code":
                # The stored code is checked again on every start, so the file
                # cannot be typed up by hand with a made-up number.
                record["number"] = LicenseCodes.verify_code(record.get("code", ""))
                return record
            if source == "existing-installation":
                return record
            return None
        except LicenseCodes.LicenseError as e:
            Logger.log("w", "PrintessLicense: stored code rejected: %s", e)
            return None
        except Exception:
            Logger.logException("w", "PrintessLicense: could not read the license file")
            return None

    def _writeLicense(self, record: dict) -> bool:
        try:
            path = self._licensePath()
            os.makedirs(os.path.dirname(path), exist_ok=True)
            with open(path, "w", encoding="utf-8") as f:
                json.dump(record, f, indent=2)
            self._license = record
            return True
        except Exception:
            Logger.logException("w", "PrintessLicense: could not write the license file")
            return False

    def _describe(self) -> str:
        if self._license is None:
            return "unlicensed"
        if self._license.get("number"):
            return "license number " + self._license["number"]
        return "existing installation"

    # ------------------------------------------------------------------
    # Existing installations
    # ------------------------------------------------------------------

    def _priorInstallation(self) -> str:
        """Evidence that PrintessFlow was here before the gate, or ""."""
        if os.environ.get(_IGNORE_PRIOR_INSTALL_ENV):
            Logger.log("i", "PrintessLicense: %s set; existing installations are not recognized",
                       _IGNORE_PRIOR_INSTALL_ENV)
            return ""
        # The evidence is the plugins/PrintessIconFix folder inside a config
        # folder, and its CREATION time. Every PrintessFlow installer since 1.0
        # has seeded that folder (it is in packaging/printessflow/seed), stock
        # Cura never creates one, and nothing recreates it afterwards: the
        # installer skips the seed once the Printess machine exists, its
        # repair pass touches only user/ and definition_changes/, and Cura
        # itself never rewrites a plugin directory. So its creation time is the
        # day PrintessFlow first landed on this computer, which is exactly the
        # question.
        #
        # The config folder's own creation time is deliberately NOT used: a
        # computer that ran stock Cura 5.12 has an old folder, and the
        # installer seeds the Printess machine into it, so both of those would
        # pass for someone who never had PrintessFlow.
        #
        # Creation time, not modification time, throughout: the config is
        # written to at every exit, so mtimes are always recent.
        cura_dir = os.path.dirname(Resources.getConfigStoragePath())
        try:
            names = os.listdir(cura_dir)
        except OSError:
            return ""
        for name in sorted(names):
            marker = os.path.join(cura_dir, name, "plugins", "PrintessIconFix")
            if not _VERSION_DIR_RE.match(name) or not os.path.isdir(marker):
                continue
            try:
                created = self._creationTime(marker)
            except OSError:
                continue
            if created < GATE_CUTOFF:
                return "%s created %s" % (marker, created.date().isoformat())
        return ""

    @staticmethod
    def _creationTime(path: str) -> datetime.datetime:
        st = os.stat(path)
        # st_birthtime: macOS always, Windows on Python 3.12+. On Windows
        # st_ctime is the creation time as well, so the fallback matches.
        stamp = getattr(st, "st_birthtime", None) or st.st_ctime
        return datetime.datetime.fromtimestamp(stamp, tz=datetime.timezone.utc)
