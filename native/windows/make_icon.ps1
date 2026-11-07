# Generates FiveQThoughts.ico (blue gradient tile + white lightning bolt),
# the same design as createAppIcon() in native/macos_host.swift.
# Usage:  powershell -NoProfile -ExecutionPolicy Bypass -File make_icon.ps1 [-Out path.ico]
param(
    [string]$Out = (Join-Path $PSScriptRoot "FiveQThoughts.ico")
)

Add-Type -AssemblyName System.Drawing

function New-IconPng([int]$size) {
    $bmp = New-Object System.Drawing.Bitmap($size, $size, [System.Drawing.Imaging.PixelFormat]::Format32bppArgb)
    $g = [System.Drawing.Graphics]::FromImage($bmp)
    $g.SmoothingMode = [System.Drawing.Drawing2D.SmoothingMode]::AntiAlias
    $g.PixelOffsetMode = [System.Drawing.Drawing2D.PixelOffsetMode]::HighQuality
    $g.Clear([System.Drawing.Color]::Transparent)

    # Design canvas is 256x256 (like the macOS icon); small sizes use less padding.
    $s = $size / 256.0
    $inset = if ($size -le 24) { 4 } elseif ($size -le 48) { 10 } else { 16 }
    $x = $inset * $s; $w = (256 - 2 * $inset) * $s
    $r = 52 * $s; $d = 2 * $r

    $path = New-Object System.Drawing.Drawing2D.GraphicsPath
    $path.AddArc($x, $x, $d, $d, 180, 90)
    $path.AddArc($x + $w - $d, $x, $d, $d, 270, 90)
    $path.AddArc($x + $w - $d, $x + $w - $d, $d, $d, 0, 90)
    $path.AddArc($x, $x + $w - $d, $d, $d, 90, 90)
    $path.CloseFigure()

    $rect = New-Object System.Drawing.RectangleF($x, $x, $w, $w)
    $c1 = [System.Drawing.Color]::FromArgb(255, 59, 130, 245)
    $c2 = [System.Drawing.Color]::FromArgb(255, 28, 79, 217)
    $brush = New-Object System.Drawing.Drawing2D.LinearGradientBrush($rect, $c1, $c2, 45.0)
    $g.FillPath($brush, $path)

    if ($size -ge 48) {
        $pen = New-Object System.Drawing.Pen([System.Drawing.Color]::FromArgb(56, 255, 255, 255), [single](4 * $s))
        $g.DrawPath($pen, $path)
        $pen.Dispose()
    }

    # Lightning bolt (macOS coordinates are y-up; flipped here)
    $pts = @(
        @(146, 46), @(78, 134), @(126, 134), @(110, 210), @(178, 122), @(130, 122)
    ) | ForEach-Object {
        $cx = 128 + ($_[0] - 128) * ((256 - 2 * $inset) / 224.0)
        $cy = 128 + ($_[1] - 128) * ((256 - 2 * $inset) / 224.0)
        New-Object System.Drawing.PointF([single]($cx * $s), [single]($cy * $s))
    }
    $g.FillPolygon([System.Drawing.Brushes]::White, [System.Drawing.PointF[]]$pts)

    $brush.Dispose(); $path.Dispose(); $g.Dispose()
    $ms = New-Object System.IO.MemoryStream
    $bmp.Save($ms, [System.Drawing.Imaging.ImageFormat]::Png)
    $bmp.Dispose()
    return ,$ms.ToArray()
}

$sizes = @(16, 20, 24, 32, 40, 48, 64, 128, 256)
$images = @($sizes | ForEach-Object { ,(New-IconPng $_) })

$fs = [System.IO.File]::Create($Out)
$bw = New-Object System.IO.BinaryWriter($fs)
$bw.Write([UInt16]0); $bw.Write([UInt16]1); $bw.Write([UInt16]$sizes.Count)
$offset = 6 + 16 * $sizes.Count
for ($i = 0; $i -lt $sizes.Count; $i++) {
    $sz = $sizes[$i]; $len = $images[$i].Length
    $dim = if ($sz -ge 256) { 0 } else { $sz }
    $bw.Write([byte]$dim); $bw.Write([byte]$dim)
    $bw.Write([byte]0); $bw.Write([byte]0)
    $bw.Write([UInt16]1); $bw.Write([UInt16]32)
    $bw.Write([UInt32]$len); $bw.Write([UInt32]$offset)
    $offset += $len
}
foreach ($img in $images) { $bw.Write([byte[]]$img) }
$bw.Close(); $fs.Close()
Write-Host "Icon geschrieben: $Out"
