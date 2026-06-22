<div align="center">

<img src="resources/images/cura-icon.png" alt="PrintessFlow" width="110">

# PrintessFlow

**A precision slicer for 3D gel printing, pre-configured for the Printess Technologies Printessa Series.**

A customized build of [UltiMaker Cura](https://github.com/Ultimaker/Cura).

### [⬇ Download the latest release](https://github.com/PrintessTechnologies/PrintessFlow/releases/latest)

</div>

## Installing on Windows

Windows 10 or 11, 64-bit. No administrator rights are needed (it installs into your user folder).

1. Run the downloaded **`PrintessFlow-Setup.exe`**.
2. **SmartScreen warning:** Windows will most likely show a blue **"Windows protected your PC"** box, because the installer is not code-signed yet. This is expected, and the installer is safe. Click **More info**, then **Run anyway**.
   - Your web browser may also warn that the file "isn't commonly downloaded." Choose **Keep**.
3. Follow the setup wizard (**Next → Install → Finish**).
4. The **first launch** may pause on **"Loading Machines"** for a minute or two while Windows scans the application files. This happens only once; later launches are fast.

## Installing on macOS

Apple Silicon (M-series) Macs.

1. Open **`PrintessFlow-macOS-arm64.dmg`** and drag **PrintessFlow** into your **Applications** folder.
2. **First launch:** because the app is not notarized yet, macOS will block a normal double-click. Right-click (or Control-click) **PrintessFlow** in Applications, choose **Open**, then confirm **Open** in the dialog. You only need to do this once.
   - If macOS still says the app is "damaged" or refuses to open, run this once in Terminal, then open the app: `xattr -dr com.apple.quarantine "/Applications/PrintessFlow.app"`
3. The first launch may take a minute while macOS verifies the app; later launches are fast.

PrintessFlow opens **pre-configured** with the Printessa Series machine and the dispense-tip profiles already set up, so there is nothing to add or configure.

## Updating

Download the latest release and install it again. On Windows, run the new **`PrintessFlow-Setup.exe`**; on macOS, replace the app in **Applications**. It replaces the previous version in place.

## License & attribution

PrintessFlow is based on [UltiMaker Cura](https://github.com/Ultimaker/Cura) (LGPLv3) and [CuraEngine](https://github.com/Ultimaker/CuraEngine) (AGPLv3). The full license texts are bundled with the installation.
