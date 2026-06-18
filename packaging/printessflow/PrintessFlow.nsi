; PrintessFlow Installer  -  Printess Technologies
; Packages the CI-built Cura app payload (staged into .\app) together with a
; pre-seeded machine/profile configuration (.\seed) and licenses, and launches
; with APPDATA redirected to the install-local data folder.

!define APP_NAME     "PrintessFlow"
!define APP_VERSION  "5.14.0"
!define COMPANY      "Printess Technologies"
!define MAIN_EXE     "PrintessFlow.exe"
!define SRC_EXE      "UltiMaker-Cura.exe"   ; launcher name produced by PyInstaller
!define DATA_SUBPATH "data\cura\5.12"        ; seeded as 5.12; Cura 5.14 upgrades it on first run

; No admin rights required - installs into the user's LocalAppData folder
RequestExecutionLevel user

VIProductVersion "5.14.0.0"
VIAddVersionKey "ProductName"     "${APP_NAME}"
VIAddVersionKey "CompanyName"     "${COMPANY}"
VIAddVersionKey "LegalCopyright"  "Copyright (c) 2026 ${COMPANY}. Based on UltiMaker Cura (LGPLv3) and CuraEngine (AGPLv3)."
VIAddVersionKey "FileDescription" "${APP_NAME} Installer"
VIAddVersionKey "FileVersion"     "${APP_VERSION}"
VIAddVersionKey "ProductVersion"  "${APP_VERSION}"

Name          "${APP_NAME}"
OutFile       "PrintessFlow-Setup.exe"
InstallDir    "$LOCALAPPDATA\${APP_NAME}"
InstallDirRegKey HKCU "Software\${APP_NAME}" "InstallDir"

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

!define MUI_FINISHPAGE_TEXT     "PrintessFlow has been installed on your computer.$\r$\n$\r$\nNote: the first launch may take a few minutes while Windows scans the application files (it may sit on $\"Loading Machines$\" briefly). Subsequent launches are much faster."
!define MUI_FINISHPAGE_RUN
!define MUI_FINISHPAGE_RUN_TEXT "Launch PrintessFlow now"
!define MUI_FINISHPAGE_RUN_FUNCTION "LaunchApp"
!insertmacro MUI_PAGE_FINISH

!insertmacro MUI_UNPAGE_CONFIRM
!insertmacro MUI_UNPAGE_INSTFILES
!insertmacro MUI_UNPAGE_FINISH
!insertmacro MUI_LANGUAGE "English"

; -----------------------------------------------------------------------
Section "PrintessFlow" SEC_MAIN
    SectionIn RO

    ; --- Application binary (CI build payload, staged into .\app) ---
    SetOutPath "$INSTDIR"
    File /r "app\*"

    ; Rebrand the launcher executable
    IfFileExists "$INSTDIR\${SRC_EXE}" 0 +2
        Rename "$INSTDIR\${SRC_EXE}" "$INSTDIR\${MAIN_EXE}"

    ; --- Pre-seeded user data (machine config + dispense-tip profiles) ---
    SetOutPath "$INSTDIR\data"
    File /r "seed\*"

    ; --- Initial preferences, only on a fresh install (skips the welcome flow
    ;     and activates the Printess machine). Seeded as 5.12 so Cura 5.14
    ;     migrates it through its normal version-upgrade path on first launch. ---
    IfFileExists "$INSTDIR\${DATA_SUBPATH}\cura.cfg" cfg_exists cfg_missing
    cfg_missing:
        FileOpen  $0 "$INSTDIR\${DATA_SUBPATH}\cura.cfg" w
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
        FileClose $0
    cfg_exists:

    ; --- License files (LGPL/AGPL/Qt/third-party + attribution) ---
    SetOutPath "$INSTDIR\licenses"
    File /r "licenses\*"

    ; --- Shortcuts: launch via cmd so APPDATA points at the install-local data,
    ;     keeping PrintessFlow isolated from any other Cura install. ---
    CreateShortcut "$DESKTOP\${APP_NAME}.lnk" \
        "$WINDIR\system32\cmd.exe" \
        '/c set "APPDATA=$INSTDIR\data"& start "" "$INSTDIR\${MAIN_EXE}"' \
        "$INSTDIR\${MAIN_EXE}" 0 SW_SHOWMINIMIZED

    CreateShortcut "$SMPROGRAMS\${APP_NAME}.lnk" \
        "$WINDIR\system32\cmd.exe" \
        '/c set "APPDATA=$INSTDIR\data"& start "" "$INSTDIR\${MAIN_EXE}"' \
        "$INSTDIR\${MAIN_EXE}" 0 SW_SHOWMINIMIZED

    ; --- Add/Remove Programs registry entries ---
    WriteRegStr   HKCU "Software\${APP_NAME}" "InstallDir" "$INSTDIR"
    WriteRegStr   HKCU "Software\Microsoft\Windows\CurrentVersion\Uninstall\${APP_NAME}" "DisplayName"          "${APP_NAME}"
    WriteRegStr   HKCU "Software\Microsoft\Windows\CurrentVersion\Uninstall\${APP_NAME}" "UninstallString"      '"$INSTDIR\Uninstall.exe"'
    WriteRegStr   HKCU "Software\Microsoft\Windows\CurrentVersion\Uninstall\${APP_NAME}" "QuietUninstallString" '"$INSTDIR\Uninstall.exe" /S'
    WriteRegStr   HKCU "Software\Microsoft\Windows\CurrentVersion\Uninstall\${APP_NAME}" "DisplayIcon"          "$INSTDIR\${MAIN_EXE}"
    WriteRegStr   HKCU "Software\Microsoft\Windows\CurrentVersion\Uninstall\${APP_NAME}" "Publisher"            "${COMPANY}"
    WriteRegStr   HKCU "Software\Microsoft\Windows\CurrentVersion\Uninstall\${APP_NAME}" "DisplayVersion"       "${APP_VERSION}"
    WriteRegDWORD HKCU "Software\Microsoft\Windows\CurrentVersion\Uninstall\${APP_NAME}" "NoModify" 1
    WriteRegDWORD HKCU "Software\Microsoft\Windows\CurrentVersion\Uninstall\${APP_NAME}" "NoRepair" 1

    WriteUninstaller "$INSTDIR\Uninstall.exe"
SectionEnd

Function LaunchApp
    Exec '"$WINDIR\system32\cmd.exe" /c set "APPDATA=$INSTDIR\data"& start "" "$INSTDIR\${MAIN_EXE}"'
FunctionEnd

Section "Uninstall"
    RMDir /r "$INSTDIR"
    Delete "$DESKTOP\${APP_NAME}.lnk"
    Delete "$SMPROGRAMS\${APP_NAME}.lnk"
    DeleteRegKey HKCU "Software\Microsoft\Windows\CurrentVersion\Uninstall\${APP_NAME}"
    DeleteRegKey HKCU "Software\${APP_NAME}"
SectionEnd
