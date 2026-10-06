# Measures the real page number of every heading, figure caption and table caption in the built
# report, and writes build/page_numbers.json so the contents and the lists of figures and tables can
# carry true page numbers instead of estimates. Also exports the PDF used for verification.
#
#   powershell -ExecutionPolicy Bypass -File report\paginate.ps1
#
# Run it on the first-pass build, then rebuild the .docx so the numbers land in the document.
#
# The text of every paragraph is read first and the page number asked for only where the text turned
# out to be a heading. Asking Word for a page number forces a layout pass, and the appendix alone is
# seven hundred paragraphs of source code, so doing it the other way round takes tens of minutes.

$ErrorActionPreference = "Stop"
$build = Join-Path $PSScriptRoot "build"
$docx = Join-Path $build "AURA_Project_Report.docx"
$pdf = Join-Path $build "AURA_Project_Report.pdf"
$out = Join-Path $build "page_numbers.json"

if (-not (Test-Path $docx)) { throw "no build to paginate: $docx" }

function ConvertTo-Roman([int]$n) {
    $map = [ordered]@{ 1000 = "M"; 900 = "CM"; 500 = "D"; 400 = "CD"; 100 = "C"; 90 = "XC";
                       50 = "L"; 40 = "XL"; 10 = "X"; 9 = "IX"; 5 = "V"; 4 = "IV"; 1 = "I" }
    $s = ""
    foreach ($k in $map.Keys) { while ($n -ge $k) { $s += $map[$k]; $n -= $k } }
    return $s
}

$FRONT = @("ACKNOWLEDGEMENT", "ABSTRACT", "TABLE OF CONTENTS", "LIST OF FIGURES",
           "LIST OF TABLES", "LIST OF SYMBOLS", "LIST OF ABBREVIATIONS")
$TAIL = @("REFERENCES", "APPENDIX 1", "APPENDIX 2")

function Get-Key([string]$text) {
    if ($FRONT -contains $text -or $TAIL -contains $text) { return $text }
    if ($text -cmatch '^CHAPTER\s+([1-6])$') { return "CHAPTER " + $Matches[1] }
    if ($text -cmatch '^(\d+\.\d+(\.\d+)?)\s\s\S') { return $Matches[1] }
    if ($text -cmatch '^Figure\s+(\d+\.\d+)\s\s') { return "FIGURE " + $Matches[1] }
    if ($text -cmatch '^Table\s+(\d+\.\d+)\s\s') { return "TABLE " + $Matches[1] }
    return $null
}

$word = New-Object -ComObject Word.Application
$word.Visible = $false
$word.DisplayAlerts = 0
$pages = [ordered]@{}
try {
    $doc = $word.Documents.Open($docx, $false, $true)   # ReadOnly
    $doc.Repaginate()

    # 3 = wdActiveEndPageNumber: the physical page a range ends on.
    $bodyStart = $doc.Sections.Item(2).Range.Information(3)
    $frontPages = $bodyStart - 1
    $pages["__body_start__"] = $bodyStart

    # One pass to collect the text, which is cheap, and the ranges worth asking about.
    $wanted = New-Object System.Collections.ArrayList
    foreach ($p in $doc.Paragraphs) {
        $text = ($p.Range.Text -replace "[\r\a\x07]", "").Trim()
        if ($text.Length -eq 0 -or $text.Length -gt 90) { continue }
        $key = Get-Key $text
        if ($key -and -not ($wanted | Where-Object { $_.Key -eq $key })) {
            [void]$wanted.Add([pscustomobject]@{ Key = $key; Range = $p.Range })
        }
    }
    Write-Output ("headings to locate: " + $wanted.Count)

    foreach ($w in $wanted) {
        $pg = $w.Range.Information(3)
        # Front matter prints roman numerals; in the body the printed number is the physical page.
        if ($pg -le $frontPages) { $pages[$w.Key] = ConvertTo-Roman $pg } else { $pages[$w.Key] = $pg }
    }

    $doc.ExportAsFixedFormat($pdf, 17)   # 17 = wdExportFormatPDF
    $pages["__total_pages__"] = $doc.ComputeStatistics(2)   # 2 = wdStatisticPages
    $doc.Close($false)
} finally {
    $word.Quit()
    [System.Runtime.InteropServices.Marshal]::ReleaseComObject($word) | Out-Null
}

$pages | ConvertTo-Json | Out-File -FilePath $out -Encoding utf8
Write-Output ("total pages: " + $pages["__total_pages__"])
Write-Output ("front matter pages: " + ($pages["__body_start__"] - 1) +
              "   body numbering starts at: " + $pages["__body_start__"])
Write-Output ("located " + ($pages.Keys.Count - 2) + " headings and captions")
Write-Output ("pdf: " + $pdf)
