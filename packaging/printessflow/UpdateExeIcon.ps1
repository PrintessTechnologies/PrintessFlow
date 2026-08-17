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
#
# The overlay of a SIGNED exe contains the Authenticode blob as well as the
# PyInstaller archive, and the signature MUST NOT be carried across. Swapping
# the icon rewrites the resource section and moves every offset after it, but
# the certificate directory holds an absolute FILE OFFSET, not an RVA, and
# nothing updates it. Re-appending the old signature therefore produced a file
# whose certificate directory pointed 13824 bytes PAST its own end:
#
#   PrintessFlow.exe  certdir says 13823440, real blob at 13809616, EOF 13821480
#
# Windows reported that as NotSigned, and to a scanner it is the signature of a
# tampered signed binary, which is a genuine malware technique and is weighted
# accordingly. It is also almost certainly why signing the inner exes failed
# with 0x800700C1 (ERROR_BAD_EXE_FORMAT): signtool rejects a PE whose
# certificate directory runs past EOF, which is what led to the inner exes
# being left unsigned in the first place.
#
# A signature can never survive a modification anyway. It is stripped here and
# the build signs the finished file afterwards.
# ---------------------------------------------------------------------------
$exeBytes = [System.IO.File]::ReadAllBytes($ExePath)
[int]$fileLen = $exeBytes.Length

# DOS header: offset 0x3C holds the file offset of the PE signature
[int]$peOffset = [BitConverter]::ToInt32($exeBytes, 0x3C)

# PE signature = "PE\0\0" (4 bytes), then COFF header (20 bytes)
[int]$coffOffset = $peOffset + 4
[uint16]$numSections     = [BitConverter]::ToUInt16($exeBytes, $coffOffset + 2)
[uint16]$optHeaderSize   = [BitConverter]::ToUInt16($exeBytes, $coffOffset + 16)
[int]$optHeaderOffset    = $coffOffset + 20
[int]$sectionTableOffset = $optHeaderOffset + $optHeaderSize

# Optional header: magic 0x20B = PE32+, 0x10B = PE32. The data directories
# start after a 112-byte (PE32+) or 96-byte (PE32) fixed part; the CheckSum
# field sits at +64 in both. Certificate table = data directory index 4.
[uint16]$peMagic = [BitConverter]::ToUInt16($exeBytes, $optHeaderOffset)
[int]$checksumOffset = $optHeaderOffset + 64
if ($peMagic -eq 0x20B) { [int]$dataDirOffset = $optHeaderOffset + 112 }
else                    { [int]$dataDirOffset = $optHeaderOffset + 96  }
[int]$certDirOffset = $dataDirOffset + 4 * 8
[uint32]$certOffset = [BitConverter]::ToUInt32($exeBytes, $certDirOffset)
[uint32]$certSize   = [BitConverter]::ToUInt32($exeBytes, $certDirOffset + 4)

# Walk every section header (40 bytes each) to find the highest raw-data end
[int]$overlayStart = 0
for ($s = 0; $s -lt $numSections; $s++) {
    [int]$sh         = $sectionTableOffset + $s * 40
    [uint32]$rawSize = [BitConverter]::ToUInt32($exeBytes, $sh + 16)
    [uint32]$rawPtr  = [BitConverter]::ToUInt32($exeBytes, $sh + 20)
    [int]$sectionEnd = [int]$rawPtr + [int]$rawSize
    if ($sectionEnd -gt $overlayStart) { $overlayStart = $sectionEnd }
}

# Everything after the sections, MINUS any trailing signature.
[int]$overlayEnd = $fileLen
if ($certSize -gt 0 -and $certOffset -ge $overlayStart -and $certOffset -lt $fileLen) {
    $overlayEnd = [int]$certOffset
    Write-Host "Authenticode signature found at $certOffset ($certSize bytes) - dropping it; the build signs this file afterwards."
} elseif ($certSize -gt 0) {
    Write-Host "Certificate directory present but not inside the overlay (offset $certOffset, size $certSize) - clearing the entry only."
}

$overlay = $null
if ($overlayStart -lt $overlayEnd) {
    [int]$overlayLen = $overlayEnd - $overlayStart
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

# ---------------------------------------------------------------------------
# Step 6 — Leave a well-formed PE behind.
#
# Two header fields still describe the file as it was BEFORE the icon swap, and
# both have to be cleared or the result looks like a tampered binary:
#
#   - the certificate directory, which still points at a signature that is no
#     longer there. Zeroing both halves is what "this file is unsigned" is
#     actually spelled as; leaving a stale pointer is not the same thing.
#   - the optional-header CheckSum, which no longer matches the contents. Zero
#     is legal and common for an unsigned image, and signtool recomputes it
#     when the file is signed.
#
# EndUpdateResource rewrites the file, so these are read back from disk rather
# than patched in the in-memory copy captured at the top.
# ---------------------------------------------------------------------------
$final = [System.IO.File]::ReadAllBytes($ExePath)
[int]$finalPe   = [BitConverter]::ToInt32($final, 0x3C)
[int]$finalOpt  = $finalPe + 4 + 20
[uint16]$finalMagic = [BitConverter]::ToUInt16($final, $finalOpt)
if ($finalMagic -eq 0x20B) { [int]$finalDataDir = $finalOpt + 112 }
else                       { [int]$finalDataDir = $finalOpt + 96  }
[int]$finalCertDir = $finalDataDir + 4 * 8

$zero4 = New-Object byte[] 4
[Array]::Copy($zero4, 0, $final, $finalCertDir, 4)          # certificate RVA
[Array]::Copy($zero4, 0, $final, $finalCertDir + 4, 4)      # certificate size
[Array]::Copy($zero4, 0, $final, $finalOpt + 64, 4)         # CheckSum
[System.IO.File]::WriteAllBytes($ExePath, $final)
Write-Host "Certificate directory and header checksum cleared - PE is now a clean unsigned image."

# Fail loudly rather than shipping a malformed binary: this is the exact defect
# this script used to introduce, so it is worth asserting it is gone.
[uint32]$vCertOff  = [BitConverter]::ToUInt32($final, $finalCertDir)
[uint32]$vCertSize = [BitConverter]::ToUInt32($final, $finalCertDir + 4)
if ($vCertOff -ne 0 -or $vCertSize -ne 0) {
    throw "certificate directory was not cleared (offset $vCertOff, size $vCertSize)"
}
Write-Host "Done: $ExePath"
