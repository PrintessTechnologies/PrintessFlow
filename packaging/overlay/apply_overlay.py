#!/usr/bin/env python3
"""
Apply PrintessFlow customizations onto an extracted stock UltiMaker Cura 5.12.0 tree.

This reproduces the file-overlay operations of CuraTestInstall.bat in a
cross-platform, CI-runnable way. It copies the customized files from the
PrintessFlow repo checkout (--repo-root) onto the stock Cura app (--app-root),
discovering the app's internal layout so the same logic works for both the
Windows onedir tree and the macOS .app bundle.

NOTE: the user-config seed (machine, profiles, dispense tips) is NOT handled
here. That is planted by the NSIS installer (Windows) and the first-run
launcher (macOS) from packaging/printessflow/seed/.
"""
import argparse
import os
import shutil
import sys
from pathlib import Path

# Files to copy, as repo-relative paths. Destination is derived from the prefix:
#   cura/...       -> <cura-package>/...           (loose Python inside the app)
#   resources/...  -> <share/cura>/resources/...   (QML, themes, definitions, images, visibility)
#   plugins/...    -> <share/cura>/plugins/...
#   UM/...         -> <UM-root>/UM/...              (Uranium QML)
#   uranium/...    -> <UM-root>/...                 (patched Uranium plugins)
MANIFEST = [
    # --- core Python overrides ---
    "cura/Settings/MachineManager.py",
    "cura/UI/CuraSplashScreen.py",
    "cura/Machines/Models/SettingVisibilityPresetsModel.py",
    "cura/Machines/Models/QualityManagementModel.py",
    "cura/Machines/Models/MaterialManagementModel.py",
    "cura/Machines/Models/BaseMaterialsModel.py",
    # --- QML / resources ---
    "resources/qml/Cura.qml",
    "resources/qml/Actions.qml",
    # The object list: renamed to say it is also the print order, and its rows
    # carry a drag handle that reorders the print.
    "resources/qml/ObjectSelector.qml",
    "resources/qml/ObjectItemButton.qml",
    "resources/qml/Dialogs/AboutDialog.qml",
    "resources/qml/WelcomePages/WelcomeContent.qml",
    "resources/qml/Menus/MaterialMenu.qml",
    "resources/qml/Menus/MaterialBrandMenu.qml",
    "resources/qml/Menus/MaterialBrandSubMenu.qml",
    "resources/qml/Menus/ConfigurationMenu/CustomConfiguration.qml",
    "resources/qml/Menus/SettingVisibilityPresetsMenu.qml",
    "resources/qml/Menus/FileMenu.qml",
    "resources/qml/Menus/HelpMenu.qml",
    "resources/qml/Menus/PrinterMenu.qml",
    "resources/qml/Menus/ExtensionMenu.qml",
    "resources/qml/PrintSetupSelector/Custom/CustomPrintSetup.qml",
    "resources/qml/PrintSetupSelector/Custom/QualitiesWithIntentMenu.qml",
    "resources/qml/PrintSetupSelector/Custom/MenuButton.qml",
    "resources/qml/PrintSetupSelector/PrintSetupSelectorHeader.qml",
    "resources/qml/PrintSetupSelector/PrintSetupSelectorContents.qml",
    "resources/qml/Preferences/Materials/MaterialsTypeSection.qml",
    "resources/qml/Preferences/Materials/MaterialsPage.qml",
    "resources/qml/Preferences/Materials/MaterialsList.qml",
    "resources/qml/Preferences/Materials/MaterialsView.qml",
    "resources/qml/Preferences/ProfilesPage.qml",
    "resources/qml/Preferences/SettingVisibilityPage.qml",
    "resources/qml/Preferences/PreferencesDialog.qml",
    "resources/qml/Preferences/GeneralPage.qml",
    "resources/qml/MainWindow/MainWindowHeader.qml",
    "resources/qml/Settings/SettingItem.qml",
    "resources/qml/ActionPanel/ActionPanelWidget.qml",
    "resources/qml/ActionPanel/SliceProcessWidget.qml",
    # Routes a click on the Path Designer's toolbar icon to `requestExit` so the
    # tool can ask what to do with an unsaved drawing. Installed by
    # CuraTestInstall.bat but MISSING from this list until 2026-08-17, so every
    # release so far shipped the stock Toolbar and the exit prompt never fired:
    # leaving the tool discarded the drawing silently.
    "resources/qml/Toolbar.qml",
    "resources/themes/cura-light/theme.json",
    "resources/themes/cura-light/icons/default/WellPlate.svg",
    "resources/definitions/fdmprinter.def.json",
    "resources/definitions/custom.def.json",
    "resources/images/cura.png",
    "resources/images/printess_logo.png",
    "resources/images/cura-icon.png",
    "resources/images/cura-icon-32.png",
    "resources/setting_visibility/printess_v1.0.cfg",
    # --- plugins (Python + QML) ---
    "plugins/FirmwareUpdater/FirmwareUpdaterMachineAction.py",
    "plugins/MachineSettingsAction/MachineSettingsExtruderTab.qml",
    "plugins/MachineSettingsAction/MachineSettingsAction.py",
    "plugins/PrepareStage/PrepareMenu.qml",
    "plugins/PostProcessingPlugin/PostProcessingPlugin.py",
    "plugins/PostProcessingPlugin/PostProcessingPlugin.qml",
    "plugins/PostProcessingPlugin/PrintessScriptSelector.qml",
    "plugins/PostProcessingPlugin/scripts/PrintessLayerByLayer.py",
    "plugins/PostProcessingPlugin/scripts/PrintessOneAtATime.py",
    "plugins/CuraEngineBackend/StartSliceJob.py",
    "plugins/CuraEngineBackend/CuraEngineBackend.py",
    "plugins/PrintessAllMaterials/plugin.json",
    "plugins/PrintessAllMaterials/__init__.py",
    "plugins/PrintessAllMaterials/AllMaterialBrandsModel.py",
    "plugins/PrintessAllMaterials/PrintessProfileManager.py",
    "plugins/WellPlateArrangeTool/plugin.json",
    "plugins/WellPlateArrangeTool/__init__.py",
    "plugins/WellPlateArrangeTool/WellPlateArrangeTool.py",
    "plugins/WellPlateArrangeTool/WellPlateArrangeTool.qml",
    "plugins/WellPlateArrangeTool/WellPlateButton.qml",
    "plugins/WellPlateArrangeTool/WellPlate.svg",
    "plugins/PrintessPathDesigner/plugin.json",
    "plugins/PrintessPathDesigner/__init__.py",
    "plugins/PrintessPathDesigner/PrintessPathDesigner.py",
    "plugins/PrintessPathDesigner/PathShapes.py",
    "plugins/PrintessPathDesigner/PathNode.py",
    "plugins/PrintessPathDesigner/WellPlates.py",
    "plugins/PrintessPathDesigner/GcodeGenerator.py",
    "plugins/PrintessPathDesigner/GcodeMerge.py",
    "plugins/PrintessPathDesigner/PathDesignerPanel.qml",
    "plugins/PrintessPathDesigner/PathDesignerButton.qml",
    "plugins/PrintessPathDesigner/PathDesigner.svg",
    # Object print order. Named files rather than a whole directory (see
    # EXTRA_PLUGIN_DIRS below): the plugin is three files that are not expected
    # to multiply, and a MANIFEST entry is checked against the .bat as drift
    # rather than only reported.
    "plugins/PrintessPrintOrder/plugin.json",
    "plugins/PrintessPrintOrder/__init__.py",
    "plugins/PrintessPrintOrder/PrintessPrintOrder.py",
    # --- patched Uranium plugin ---
    # Smooth camera rotation out of the top view. Installed by
    # CuraTestInstall.bat, so it has to ship too or the released build behaves
    # differently from the one the slicer is tested on.
    "uranium/plugins/Tools/CameraTool/CameraTool.py",
    # The Move tool reports plate coordinates in the printer's frame (front-left
    # corner origin), the same frame the g-code is written in, instead of the
    # scene's centre-origin numbers.
    "uranium/plugins/Tools/TranslateTool/TranslateTool.py",
    # The six CuraDrive files that rebranded it as "Printess Backups" are gone:
    # CuraDrive itself is in REMOVED_PLUGINS, so copying them in would only mean
    # writing files into a directory deleted moments later. The customizations
    # are still in the repo under plugins/CuraDrive/ if the feature is ever
    # wanted back, at which point both this list and REMOVED_PLUGINS change.
    # --- Uranium QML ---
    "UM/Qt/qml/UM/Preferences/ManagementPage.qml",
]

# Files to remove from the stock app (paths are relative to <share/cura>).
DELETIONS = [
    "resources/qml/PrintSetupSelector/Custom/ExtruderTipMenu.qml",
    "resources/setting_visibility/basic.cfg",
    "resources/setting_visibility/advanced.cfg",
    "resources/setting_visibility/expert.cfg",
]

# Stock plugin directories removed from the shipped app.
#
# All of these are UltiMaker cloud/network features that PrintessFlow does not
# use, and together they are most of what the app DOES in its first seconds:
# CrowdStrike terminated PrintessFlow.exe on a user's machine with "malicious
# behavior was detected", and the profile it presented was an unsigned binary,
# with no prevalence, running from a user-writable directory, that on launch
# broadcast mDNS across the local subnet, enumerated serial devices, spawned a
# child process, and beaconed to several ultimaker.com domains. No one of those
# is malicious; the composite on an unknown binary is what gets killed.
#
# Removing them is a product simplification as much as a security one. None has
# ever worked for a Printess machine.
#
# Verified before listing: none of these is referenced as a QML TYPE anywhere
# outside its own directory, so nothing fails to construct without them.
REMOVED_PLUGINS = [
    # Starts Zeroconf/mDNS at launch (UM3OutputDevicePlugin.start ->
    # ZeroConfClient -> ServiceBrowser on _ultimaker._tcp.local.) to discover
    # UltiMaker network printers. Active LAN service discovery is the single
    # strongest behavioral signal in the list, and a Printess V1 is never on it.
    "UM3NetworkPrinting",
    # Cura acting as the printer host over serial: opens a COM port and streams
    # g-code itself. PrintessFlow does not drive the printer at all - it writes
    # a .gcode file and Pronterface hosts the connection - so this only ever
    # enumerated serial ports looking for hardware it would never talk to.
    "USBPrinting",
    # Backups to UltiMaker's cloud behind an account.ultimaker.com OAuth flow,
    # shipped rebranded as "Printess Backups". Removed at the user's request:
    # customer configuration should not be sitting in UltiMaker's cloud.
    "CuraDrive",
    # Slice telemetry to statistics.ultimaker.com. A rebranded product should
    # not be reporting its users' slices to the upstream vendor.
    "SliceInfoPlugin",
    # Checks UltiMaker firmware versions for UltiMaker printers. Already hidden
    # from the Extensions menu; this stops it loading and phoning home at all.
    "FirmwareUpdateChecker",
    # UltiMaker Digital Factory cloud storage.
    "DigitalLibrary",
]

# Plugin directories sourced from a non-standard location, copied wholesale into
# <share/cura>/plugins/<name>. PrintessIconFix lives under the seed in the repo.
EXTRA_PLUGIN_DIRS = [
    ("packaging/printessflow/seed/cura/5.12/plugins/PrintessIconFix", "PrintessIconFix"),
    # Flow Rate Tester. Shipped as a WHOLE DIRECTORY rather than as named files
    # in MANIFEST above, deliberately: the plugin is still being worked on, and a
    # file list has to be updated by hand every time a file is added or renamed.
    # It was already in CuraTestInstall.bat and absent from this file, so the
    # feature worked locally and would have been missing from the release
    # entirely. A directory entry cannot drift that way.
    ("plugins/PrintessFlowTester", "PrintessFlowTester"),
]

# Surgical in-place edits to stock files. Used instead of overlaying whole core
# files (e.g. CuraApplication.py) that differ across Cura versions. Each patch
# injects `inject` as the first body line right after the `anchor` line.
PATCHES = [
    {
        # Never show the stock UltiMaker "What's New" / version-upgrade dialog on
        # launch (mirrors the cura/CuraApplication.py override, applied surgically).
        "rel": "cura/CuraApplication.py",
        "anchor": "def shouldShowWhatsNewDialog(self) -> bool:",
        "inject": "        return False  # PrintessFlow: never show the stock What's New / upgrade dialog",
    },
]


def apply_patches(cura_pkg):
    if cura_pkg is None:
        print("[overlay] WARNING: no cura package found; skipping patches")
        return 0
    applied = 0
    for p in PATCHES:
        f = cura_pkg.parent / p["rel"]
        if not f.is_file():
            print(f"[overlay] WARNING: patch target missing: {p['rel']}")
            continue
        lines = f.read_text(encoding="utf-8").splitlines()
        out, done = [], False
        for i, line in enumerate(lines):
            out.append(line)
            if not done and p["anchor"] in line:
                nxt = lines[i + 1] if i + 1 < len(lines) else ""
                if p["inject"].strip() not in nxt:
                    out.append(p["inject"])
                done = True
        if done:
            f.write_text("\n".join(out) + "\n", encoding="utf-8")
            applied += 1
        else:
            print(f"[overlay] WARNING: anchor not found in {p['rel']}: {p['anchor']}")
    return applied


def discover_roots(app_root: Path):
    """Locate the share/cura dir, the cura package dir, and the UM root inside the app."""
    share_cura = cura_pkg = um_root = None
    for dirpath, dirnames, filenames in os.walk(app_root):
        base = os.path.basename(dirpath)
        parent = os.path.basename(os.path.dirname(dirpath))
        if share_cura is None and base == "cura" and parent == "share" \
                and "plugins" in dirnames and "resources" in dirnames:
            share_cura = Path(dirpath)
        if cura_pkg is None and base == "cura" and "CuraApplication.py" in filenames:
            cura_pkg = Path(dirpath)
        if um_root is None and base == "UM" and "Qt" in dirnames \
                and os.path.isdir(os.path.join(dirpath, "Qt", "qml", "UM")):
            um_root = Path(dirpath).parent
        if share_cura and cura_pkg and um_root:
            break
    return share_cura, cura_pkg, um_root


def dest_for(repo_rel: str, share_cura, cura_pkg, um_root):
    if repo_rel.startswith("cura/"):
        return (cura_pkg.parent / repo_rel) if cura_pkg else None
    if repo_rel.startswith(("resources/", "plugins/")):
        return (share_cura / repo_rel) if share_cura else None
    if repo_rel.startswith("UM/"):
        return (um_root / repo_rel) if um_root else None
    # Uranium's own plugins sit beside its UM package, so um_root is already the
    # right base and the "uranium/" prefix comes off. CuraTestInstall.bat puts
    # these in <app>/share/uranium/..., which is the same place.
    if repo_rel.startswith("uranium/"):
        return (um_root / repo_rel[len("uranium/"):]) if um_root else None
    return None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--app-root", required=True, help="extracted stock Cura tree (or .app)")
    ap.add_argument("--repo-root", required=True, help="PrintessFlow repo checkout")
    args = ap.parse_args()

    app_root = Path(args.app_root).resolve()
    repo_root = Path(args.repo_root).resolve()

    share_cura, cura_pkg, um_root = discover_roots(app_root)
    print(f"[overlay] app-root   : {app_root}")
    print(f"[overlay] share/cura : {share_cura}")
    print(f"[overlay] cura pkg   : {cura_pkg}")
    print(f"[overlay] UM root    : {um_root}")
    if share_cura is None:
        sys.exit("[overlay] FATAL: could not locate share/cura inside the app")

    copied = 0
    missing_src = []
    skipped_dest = []
    for rel in MANIFEST:
        src = repo_root / rel
        if not src.is_file():
            missing_src.append(rel)
            continue
        dest = dest_for(rel, share_cura, cura_pkg, um_root)
        if dest is None:
            skipped_dest.append(rel)
            continue
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src, dest)
        copied += 1

    # Extra plugin directories (e.g. PrintessIconFix from the seed).
    for src_rel, plugin_name in EXTRA_PLUGIN_DIRS:
        src = repo_root / src_rel
        if not src.is_dir():
            missing_src.append(src_rel + " (dir)")
            continue
        dest = share_cura / "plugins" / plugin_name
        if dest.exists():
            shutil.rmtree(dest)
        # Ignore build and VCS droppings. Without this a developer's stale
        # __pycache__ ships inside the installer, and a .pyc whose source no
        # longer matches is exactly the kind of thing that runs old code on a
        # user's machine and cannot be reproduced locally.
        shutil.copytree(src, dest, ignore = shutil.ignore_patterns(
            "__pycache__", "*.pyc", "*.pyo", ".git", ".gitignore", "*.orig", "*.rej"))
        copied += 1

    # printess.ico is generated locally by the .bat; here derive it from the
    # committed PrintessFlow.ico so the PrintessIconFix plugin can load it.
    ico_src = repo_root / "packaging/printessflow/PrintessFlow.ico"
    if ico_src.is_file():
        ico_dest = share_cura / "resources" / "images" / "printess.ico"
        ico_dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(ico_src, ico_dest)
        copied += 1

    # Deletions.
    removed = 0
    for rel in DELETIONS:
        target = share_cura / rel
        if target.exists():
            target.unlink()
            removed += 1

    # Stock plugin directories dropped from the shipped app (see REMOVED_PLUGINS).
    # Absence is reported rather than ignored: if UltiMaker renames one of these
    # in a future Cura, silently doing nothing would put mDNS discovery or the
    # serial scanner back into the product without a word.
    dropped_plugins = []
    for name in REMOVED_PLUGINS:
        target = share_cura / "plugins" / name
        if target.is_dir():
            shutil.rmtree(target)
            dropped_plugins.append(name)
        else:
            print(f"[overlay] NOTE: plugin to remove was not present: {name}")
    print(f"[overlay] plugins removed: {len(dropped_plugins)} "
          f"({', '.join(dropped_plugins) if dropped_plugins else 'none'})")

    # Surgical patches to stock core files (after copies, before bytecode purge).
    patched = apply_patches(cura_pkg)

    # Drop stale bytecode so the overlaid/patched .py files take effect.
    pyc_cleared = 0
    for root in (cura_pkg, share_cura / "plugins"):
        if root and root.exists():
            for cache in root.rglob("__pycache__"):
                shutil.rmtree(cache, ignore_errors=True)
                pyc_cleared += 1

    print(f"[overlay] copied {copied} files, removed {removed}, patched {patched}, cleared {pyc_cleared} __pycache__ dirs")
    if skipped_dest:
        print(f"[overlay] WARNING: no dest root for {len(skipped_dest)} files: {skipped_dest}")
    if missing_src:
        print(f"[overlay] FATAL: {len(missing_src)} manifest sources missing from repo:")
        for m in missing_src:
            print(f"           - {m}")
        sys.exit(1)

    # Verify key customizations actually landed in the app. Catches wrong-dir
    # discovery or silent copy failures that would otherwise ship a near-stock
    # build (the failure mode that motivated this check).
    required = [
        share_cura / "plugins" / "WellPlateArrangeTool" / "plugin.json",
        share_cura / "plugins" / "PrintessAllMaterials" / "plugin.json",
        share_cura / "plugins" / "PrintessIconFix" / "plugin.json",
        share_cura / "plugins" / "PostProcessingPlugin" / "scripts" / "PrintessOneAtATime.py",
        share_cura / "resources" / "definitions" / "custom.def.json",
        share_cura / "resources" / "setting_visibility" / "printess_v1.0.cfg",
    ]
    bad = [str(p) for p in required if not p.exists()]
    if bad or patched < 1:
        print("[overlay] FATAL: customization verification failed")
        for b in bad:
            print(f"           missing: {b}")
        if patched < 1:
            print("           CuraApplication What's-New patch did not apply")
        sys.exit(1)

    # Cura reads .cfg containers as plain utf-8, so a BOM makes configparser
    # raise MissingSectionHeaderError and the container silently never loads.
    # This shipped once: every per-extruder dispense-tip profile had a BOM, so
    # infill/speed/flow reverted the moment the auto-save cleared the user
    # container. Fail the build rather than ship it again.
    repo_root = Path(__file__).resolve().parents[2]
    bom = []
    for scan in (repo_root / "resources" / "quality_changes",
                 repo_root / "packaging" / "printessflow" / "seed"):
        if scan.is_dir():
            bom += [p for p in scan.rglob("*.cfg") if p.read_bytes()[:3] == b"\xef\xbb\xbf"]
    if bom:
        print(f"[overlay] FATAL: {len(bom)} .cfg files have a UTF-8 BOM and will not load:")
        for p in bom:
            print(f"           - {p.relative_to(repo_root)}")
        sys.exit(1)

    # An extruder USER container must (a) carry the machine definition ("custom"),
    # not the extruder definition ("custom_extruder_N"), AND (b) declare the
    # extruder it belongs to via `extruder = custom_extruder_N #2` metadata.
    # fdmextruder has no parent, so custom_extruder_N only knows the ~30
    # nozzle/machine settings; without both fields Cura can't tie the container
    # to the extruder stack and rebuilds it against the extruder definition, so
    # every per-extruder write (infill, speed, flow) is rejected with "no
    # SettingDefinition" and the field reverts. Cura itself writes definition=custom
    # + the extruder/machine metadata; the seed must match byte-for-byte.
    user_seed = repo_root / "packaging" / "printessflow" / "seed" / "cura" / "5.12" / "user"
    bad_user = []
    for p in user_seed.glob("custom_extruder_*_user.inst.cfg"):
        text = p.read_text(encoding="utf-8")
        if not any(l.strip() == "definition = custom" for l in text.splitlines()):
            bad_user.append((p.name, "definition != custom"))
        elif not any(l.startswith("extruder = custom_extruder_") for l in text.splitlines()):
            bad_user.append((p.name, "missing 'extruder =' metadata"))
    g = user_seed / "Printess+V1+Series_user.inst.cfg"
    if g.exists():
        gt = g.read_text(encoding="utf-8")
        if not any(l.startswith("machine = ") for l in gt.splitlines()):
            bad_user.append((g.name, "missing 'machine =' metadata"))
    if bad_user:
        print(f"[overlay] FATAL: {len(bad_user)} user containers are malformed "
              f"(per-extruder settings will not save):")
        for n, why in bad_user:
            print(f"           - {n}: {why}")
        sys.exit(1)

    print("[overlay] verification OK")
    print("[overlay] done")


if __name__ == "__main__":
    main()
