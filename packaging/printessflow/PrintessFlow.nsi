; PrintessFlow Installer  -  Printess Technologies
; Packages the CI-built Cura app payload (staged into .\app) together with a
; pre-seeded machine/profile configuration (.\seed) and licenses, and launches
; seeding the machine/profile config into %APPDATA%\cura\5.12 on first install.

!define APP_NAME     "PrintessFlow"
!define APP_VERSION  "1.0.4"
!define COMPANY      "Printess Technologies"
!define MAIN_EXE     "PrintessFlow.exe"
!define SRC_EXE      "UltiMaker-Cura.exe"   ; launcher name produced by PyInstaller
!define DATA_SUBPATH "data\cura\5.12"        ; seeded as 5.12; Cura 5.14 upgrades it on first run

; Per-machine install into Program Files, which needs elevation.
;
; This used to be `user` + $LOCALAPPDATA, deliberately, to avoid a UAC prompt.
; That combination is also the reason CrowdStrike terminated the app on a user's
; machine with "malicious behavior was detected": an installer that drops an
; UNSIGNED executable into a user-writable directory and then runs it is the
; canonical dropper sequence, and %LOCALAPPDATA% is where malware installs
; precisely because it needs no elevation. Running from Program Files, which is
; not user-writable, removes the strongest signal in that chain.
;
; Cost: one UAC prompt at install. Worth it for an app whose users are on
; managed institutional machines running EDR.
RequestExecutionLevel admin

VIProductVersion "1.0.4.0"
VIAddVersionKey "ProductName"     "${APP_NAME}"
VIAddVersionKey "CompanyName"     "${COMPANY}"
VIAddVersionKey "LegalCopyright"  "Copyright (c) 2026 ${COMPANY}. Based on UltiMaker Cura (LGPLv3) and CuraEngine (AGPLv3)."
VIAddVersionKey "FileDescription" "${APP_NAME} Installer"
VIAddVersionKey "FileVersion"     "${APP_VERSION}"
VIAddVersionKey "ProductVersion"  "${APP_VERSION}"

Name          "${APP_NAME}"
OutFile       "PrintessFlow-Setup.exe"
InstallDir    "$PROGRAMFILES64\${APP_NAME}"
; InstallDirRegKey is deliberately NOT used. It OVERRIDES InstallDir whenever the
; stored key exists, so every existing user - all of whom have
; "$LOCALAPPDATA\PrintessFlow" recorded from a previous install - would be sent
; straight back to the directory this change exists to move them out of. The new
; default has to win, so the old location is read only to clean it up (below).

SetCompressor /SOLID lzma

; -----------------------------------------------------------------------
!include "MUI2.nsh"

!define MUI_ICON     "PrintessFlow.ico"
!define MUI_UNICON   "PrintessFlow.ico"
!define MUI_WELCOMEFINISHPAGE_BITMAP   "installer_banner.bmp"
!define MUI_UNWELCOMEFINISHPAGE_BITMAP "installer_banner.bmp"

!define MUI_ABORTWARNING
!define MUI_WELCOMEPAGE_TITLE "Welcome to the PrintessFlow Setup Wizard"
!define MUI_WELCOMEPAGE_TEXT  "This wizard will install PrintessFlow on your computer.$\r$\n$\r$\nPrintessFlow is based on UltiMaker Cura (LGPLv3) and CuraEngine (AGPLv3). The full license texts are included in the installation.$\r$\n$\r$\nClick Next to continue."

!insertmacro MUI_PAGE_WELCOME
!insertmacro MUI_PAGE_LICENSE "licenses\cura_license.txt"
!insertmacro MUI_PAGE_DIRECTORY
!insertmacro MUI_PAGE_INSTFILES

; No MUI_FINISHPAGE_RUN. The installer no longer launches the app it just wrote.
; "Process writes an executable and immediately executes it" is a behavioral
; pattern EDRs weight heavily on its own, and it is the second half of the chain
; described at RequestExecutionLevel above. Users start PrintessFlow from the
; desktop or Start-menu shortcut instead, which is an ordinary user-initiated
; launch with no dropper adjacency.
!define MUI_FINISHPAGE_TEXT     "PrintessFlow has been installed on your computer.$\r$\n$\r$\nUse the PrintessFlow shortcut on your desktop or in the Start menu to launch it.$\r$\n$\r$\nNote: the first launch may take a few minutes while Windows scans the application files (it may sit on $\"Loading Machines$\" briefly). Subsequent launches are much faster."
!insertmacro MUI_PAGE_FINISH

!insertmacro MUI_UNPAGE_CONFIRM
!insertmacro MUI_UNPAGE_INSTFILES
!insertmacro MUI_UNPAGE_FINISH
!insertmacro MUI_LANGUAGE "English"

; -----------------------------------------------------------------------
Section "PrintessFlow" SEC_MAIN
    SectionIn RO

    ; --- Migrate away from the old %LOCALAPPDATA% install ---
    ;     Every user installed before this version has a copy in
    ;     $LOCALAPPDATA\PrintessFlow. Leaving it there would defeat the point:
    ;     the old unsigned binary would still be sitting in a user-writable
    ;     directory, still launchable from a stale shortcut, and still liable to
    ;     be terminated. Guarded so it can never delete the directory we are
    ;     about to install into, however the user redirects it on the Directory
    ;     page. User config lives in %APPDATA%\cura and is untouched.
    StrCmp "$INSTDIR" "$LOCALAPPDATA\${APP_NAME}" skip_migrate 0
        IfFileExists "$LOCALAPPDATA\${APP_NAME}\*.*" 0 skip_migrate
            DetailPrint "Removing the previous installation from $LOCALAPPDATA\${APP_NAME}"
            RMDir /r "$LOCALAPPDATA\${APP_NAME}"
    skip_migrate:

    ; --- Application binary (CI build payload, staged into .\app) ---
    ; Wipe any prior install first so files removed or renamed between versions
    ; don't linger and get loaded (File /r overwrites same-named files but never
    ; deletes orphans). Only the app dir is cleared -- it holds program files
    ; only; user config in %APPDATA%\cura\5.12 is separate and preserved below.
    RMDir /r "$INSTDIR"
    SetOutPath "$INSTDIR"
    File /r "app\*"

    ; Rebrand the launcher executable
    IfFileExists "$INSTDIR\${SRC_EXE}" 0 +2
        Rename "$INSTDIR\${SRC_EXE}" "$INSTDIR\${MAIN_EXE}"

    ; --- Pre-seeded user data into the real %APPDATA%\cura\5.12, but only when the
    ;     Printessa machine isn't already there. Using the real APPDATA (instead of
    ;     an install-local folder + a launch-time redirect) means the app is
    ;     configured no matter how it is started (shortcut, pinned exe, or run
    ;     directly), and a reinstall won't clobber an existing config. ---
    IfFileExists "$APPDATA\cura\5.12\machine_instances\Printess+V1+Series.global.cfg" seed_skip 0
    SetOutPath "$APPDATA\cura\5.12"
    File /r "seed\cura\5.12\*"

    ; --- Initial preferences, only on a fresh install (skips the welcome flow
    ;     and activates the Printess machine). ---
    IfFileExists "$APPDATA\cura\5.12\cura.cfg" cfg_exists cfg_missing
    cfg_missing:
        FileOpen  $0 "$APPDATA\cura\5.12\cura.cfg" w
        FileWrite $0 "[general]$\r$\n"
        FileWrite $0 "last_run_version = 5.12.0$\r$\n"
        FileWrite $0 "accepted_user_agreement = True$\r$\n"
        FileWrite $0 "version = 7$\r$\n"
        FileWrite $0 "$\r$\n"
        FileWrite $0 "[metadata]$\r$\n"
        FileWrite $0 "setting_version = 26$\r$\n"
        FileWrite $0 "$\r$\n"
        FileWrite $0 "[cura]$\r$\n"
        FileWrite $0 "active_machine = Printess V1 Series$\r$\n"
        FileWrite $0 "active_mode = 1$\r$\n"
        FileWrite $0 "active_setting_visibility_preset = printess_v1.0$\r$\n"
        FileWrite $0 "dialog_on_project_save = False$\r$\n"
        FileWrite $0 "asked_dialog_on_project_save = True$\r$\n"
        FileWrite $0 "choice_on_open_project = open_as_project$\r$\n"
        FileWrite $0 "expanded_brands = ;Printess$\r$\n"
        FileWrite $0 "$\r$\n"
        FileWrite $0 "[info]$\r$\n"
        FileWrite $0 "latest_update_version_shown = 99.99.99$\r$\n"
        FileClose $0
    cfg_exists:
    seed_skip:

    ; --- Repair pass (runs even when the seed was skipped) ---
    ;     Installs shipped before the user containers carried their stack
    ;     metadata (definition=custom + extruder=/machine=) left every
    ;     per-extruder setting (infill, speed, flow) unwritable: the field
    ;     accepted a value then reverted. The seed-skip above means a plain
    ;     reinstall would not replace those broken files, so heal them here
    ;     unconditionally. Only the user containers are overwritten; they hold
    ;     transient, unmerged edits, so dispense tips (quality_changes) and
    ;     preferences (cura.cfg) are untouched.
    SetOverwrite on
    SetOutPath "$APPDATA\cura\5.12\user"
    File /r "seed\cura\5.12\user\*"

    ;     Machine geometry is fixed hardware, not a user preference, and it is
    ;     coupled to the startup G92 datum baked into the post-processing scripts
    ;     (PLATE_CENTER_X/Y). If the two disagree, every print shifts on the plate,
    ;     so this one file is refreshed even on an upgrade where the seed was
    ;     skipped. 1.0.4 changed the plate to 124 x 86.1.
    SetOutPath "$APPDATA\cura\5.12\definition_changes"
    File "seed\cura\5.12\definition_changes\Printess+V1+Series_settings.inst.cfg"

    ; --- License files (LGPL/AGPL/Qt/third-party + attribution) ---
    SetOutPath "$INSTDIR\licenses"
    File /r "licenses\*"

    ; --- Shortcuts: launch the app directly (config lives in %APPDATA%). ---
    CreateShortcut "$DESKTOP\${APP_NAME}.lnk" "$INSTDIR\${MAIN_EXE}" "" "$INSTDIR\${MAIN_EXE}" 0
    CreateShortcut "$SMPROGRAMS\${APP_NAME}.lnk" "$INSTDIR\${MAIN_EXE}" "" "$INSTDIR\${MAIN_EXE}" 0

    ; --- Add/Remove Programs registry entries ---
    ;     HKLM, not HKCU, now that this is a per-machine install in Program
    ;     Files. An elevated installer writes HKCU into the hive of whoever
    ;     answered the UAC prompt, so on a managed machine, where that is an IT
    ;     admin rather than the person at the keyboard, the entry would land in
    ;     the wrong profile and the actual user would have an app they could not
    ;     uninstall. SetRegView 64 keeps this out of the WOW6432Node redirect.
    SetRegView 64
    DeleteRegKey HKCU "Software\Microsoft\Windows\CurrentVersion\Uninstall\${APP_NAME}"
    DeleteRegKey HKCU "Software\${APP_NAME}"
    WriteRegStr   HKLM "Software\${APP_NAME}" "InstallDir" "$INSTDIR"
    WriteRegStr   HKLM "Software\Microsoft\Windows\CurrentVersion\Uninstall\${APP_NAME}" "DisplayName"          "${APP_NAME}"
    WriteRegStr   HKLM "Software\Microsoft\Windows\CurrentVersion\Uninstall\${APP_NAME}" "UninstallString"      '"$INSTDIR\Uninstall.exe"'
    WriteRegStr   HKLM "Software\Microsoft\Windows\CurrentVersion\Uninstall\${APP_NAME}" "QuietUninstallString" '"$INSTDIR\Uninstall.exe" /S'
    WriteRegStr   HKLM "Software\Microsoft\Windows\CurrentVersion\Uninstall\${APP_NAME}" "DisplayIcon"          "$INSTDIR\${MAIN_EXE}"
    WriteRegStr   HKLM "Software\Microsoft\Windows\CurrentVersion\Uninstall\${APP_NAME}" "Publisher"            "${COMPANY}"
    WriteRegStr   HKLM "Software\Microsoft\Windows\CurrentVersion\Uninstall\${APP_NAME}" "DisplayVersion"       "${APP_VERSION}"
    WriteRegDWORD HKLM "Software\Microsoft\Windows\CurrentVersion\Uninstall\${APP_NAME}" "NoModify" 1
    WriteRegDWORD HKLM "Software\Microsoft\Windows\CurrentVersion\Uninstall\${APP_NAME}" "NoRepair" 1

    WriteUninstaller "$INSTDIR\Uninstall.exe"
SectionEnd

; LaunchApp is gone along with MUI_FINISHPAGE_RUN. Do not reintroduce it without
; re-reading the note at RequestExecutionLevel: dropping an executable and then
; running it is half of what got the app terminated.

Section "Uninstall"
    SetRegView 64
    RMDir /r "$INSTDIR"
    Delete "$DESKTOP\${APP_NAME}.lnk"
    Delete "$SMPROGRAMS\${APP_NAME}.lnk"
    DeleteRegKey HKLM "Software\Microsoft\Windows\CurrentVersion\Uninstall\${APP_NAME}"
    DeleteRegKey HKLM "Software\${APP_NAME}"
    ; Left over from installs before the move to Program Files.
    DeleteRegKey HKCU "Software\Microsoft\Windows\CurrentVersion\Uninstall\${APP_NAME}"
    DeleteRegKey HKCU "Software\${APP_NAME}"
SectionEnd
