param([string]$ExePath, [string]$IcoPath)

Add-Type -TypeDefinition @"
using System;
using System.Runtime.InteropServices;

public static class NativeResource {
    [DllImport("kernel32.dll", SetLastError = true, CharSet = CharSet.Unicode)]
    public static extern IntPtr BeginUpdateResource(string pFileName, bool bDeleteExistingResources);

    [DllImport("kernel32.dll", SetLastError = true)]
    public static extern bool UpdateResource(IntPtr hUpdate, IntPtr lpType, IntPtr lpName,
        ushort wLanguage, byte[] lpData, uint cbData);

    [DllImport("kernel32.dll", SetLastError = true)]
    public static extern bool EndUpdateResource(IntPtr hUpdate, bool fDiscard);
}
"@

# ---------------------------------------------------------------------------
# Step 1 — Find the PE overlay (everything after the last PE section).
# PyInstaller appends its archive as an overlay, so we save it before the
# Windows resource-update API strips it.
# ---------------------------------------------------------------------------
$exeBytes = [System.IO.File]::ReadAllBytes($ExePath)
[int]$fileLen = $exeBytes.Length

# DOS header: offset 0x3C holds the file offset of the PE signature
[int]$peOffset = [BitConverter]::ToInt32($exeBytes, 0x3C)

# PE signature = "PE\0\0" (4 bytes), then COFF header (20 bytes)
[int]$coffOffset = $peOffset + 4
[uint16]$numSections     = [BitConverter]::ToUInt16($exeBytes, $coffOffset + 2)
[uint16]$optHeaderSize   = [BitConverter]::ToUInt16($exeBytes, $coffOffset + 16)
[int]$sectionTableOffset = $coffOffset + 20 + $optHeaderSize

# Walk every section header (40 bytes each) to find the highest raw-data end
[int]$overlayStart = 0
for ($s = 0; $s -lt $numSections; $s++) {
    [int]$sh         = $sectionTableOffset + $s * 40
    [uint32]$rawSize = [BitConverter]::ToUInt32($exeBytes, $sh + 16)
    [uint32]$rawPtr  = [BitConverter]::ToUInt32($exeBytes, $sh + 20)
    [int]$sectionEnd = [int]$rawPtr + [int]$rawSize
    if ($sectionEnd -gt $overlayStart) { $overlayStart = $sectionEnd }
}

$overlay = $null
if ($overlayStart -lt $fileLen) {
    [int]$overlayLen = $fileLen - $overlayStart
    $overlay = New-Object byte[] $overlayLen
    [Array]::Copy($exeBytes, $overlayStart, $overlay, 0, $overlayLen)
    Write-Host "Overlay found at offset $overlayStart ($($overlay.Length) bytes) - will restore after icon update."
} else {
    Write-Host "No file overlay detected - archive is likely stored as a PE resource and will be preserved automatically."
}

# ---------------------------------------------------------------------------
# Step 2 — Parse the ICO file
# ---------------------------------------------------------------------------
$icoBytes = [System.IO.File]::ReadAllBytes($IcoPath)
$ms = New-Object System.IO.MemoryStream($icoBytes, $false)
$br = New-Object System.IO.BinaryReader($ms)
$br.ReadUInt16() | Out-Null   # Reserved
$br.ReadUInt16() | Out-Null   # Type
[int]$count = $br.ReadUInt16()

$entries = for ($i = 0; $i -lt $count; $i++) {
    [PSCustomObject]@{
        Width       = [int]$br.ReadByte()
        Height      = [int]$br.ReadByte()
        ColorCount  = [int]$br.ReadByte()
        Reserved    = [int]$br.ReadByte()
        Planes      = [int]$br.ReadUInt16()
        BitCount    = [int]$br.ReadUInt16()
        BytesInRes  = [uint32]$br.ReadUInt32()
        ImageOffset = [int]$br.ReadUInt32()
    }
}
$br.Close(); $ms.Close()

# ---------------------------------------------------------------------------
# Step 3 — Build RT_GROUP_ICON blob
# ---------------------------------------------------------------------------
$grpMs = New-Object System.IO.MemoryStream
$grpBw = New-Object System.IO.BinaryWriter($grpMs)
$grpBw.Write([uint16]0); $grpBw.Write([uint16]1); $grpBw.Write([uint16]$count)
for ($i = 0; $i -lt $count; $i++) {
    $e = $entries[$i]
    $grpBw.Write([byte]$e.Width);  $grpBw.Write([byte]$e.Height)
    $grpBw.Write([byte]$e.ColorCount); $grpBw.Write([byte]$e.Reserved)
    $grpBw.Write([uint16]$e.Planes); $grpBw.Write([uint16]$e.BitCount)
    $grpBw.Write([uint32]$e.BytesInRes); $grpBw.Write([uint16]($i + 1))
}
$grpBw.Flush(); $grpData = $grpMs.ToArray(); $grpBw.Close()

# ---------------------------------------------------------------------------
# Step 4 — Update icon resources (this strips the overlay)
# ---------------------------------------------------------------------------
$hUpdate = [NativeResource]::BeginUpdateResource($ExePath, $false)
if ($hUpdate -eq [IntPtr]::Zero) {
    throw "BeginUpdateResource failed (error $([Runtime.InteropServices.Marshal]::GetLastWin32Error()))"
}

for ($i = 0; $i -lt $count; $i++) {
    $e    = $entries[$i]
    $data = [byte[]]::new($e.BytesInRes)
    [Array]::Copy($icoBytes, $e.ImageOffset, $data, 0, $e.BytesInRes)
    if (-not [NativeResource]::UpdateResource($hUpdate, [IntPtr]::new(3), [IntPtr]::new($i+1), 0, $data, [uint32]$data.Length)) {
        [NativeResource]::EndUpdateResource($hUpdate, $true)
        throw "UpdateResource RT_ICON $($i+1) failed"
    }
}
if (-not [NativeResource]::UpdateResource($hUpdate, [IntPtr]::new(14), [IntPtr]::new(1), 0, $grpData, [uint32]$grpData.Length)) {
    [NativeResource]::EndUpdateResource($hUpdate, $true)
    throw "UpdateResource RT_GROUP_ICON failed"
}
if (-not [NativeResource]::EndUpdateResource($hUpdate, $false)) {
    throw "EndUpdateResource failed (error $([Runtime.InteropServices.Marshal]::GetLastWin32Error()))"
}

# ---------------------------------------------------------------------------
# Step 5 — Re-append the overlay unconditionally.
# EndUpdateResource always truncates the file at the last PE section, so the
# overlay needs to be re-appended every time.
# ---------------------------------------------------------------------------
if ($null -ne $overlay) {
    $fs = [System.IO.File]::Open($ExePath, [System.IO.FileMode]::Append, [System.IO.FileAccess]::Write)
    $fs.Write($overlay, 0, $overlay.Length)
    $fs.Close()
    Write-Host "Overlay restored."
}
Write-Host "Done: $ExePath"
