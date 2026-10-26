"""Quick inventory of a folder of statements: type, guessed institution, layout, readability.

    python scripts/inventory_statements.py <folder>

Read-only. Prints one block per file so the right importer can be chosen/built.
"""
from __future__ import annotations

import csv
import io
import re
import subprocess
import sys
from pathlib import Path

INSTITUTIONS = {
    "Citi": r"(?<![a-z])citi(?:bank|cards?)?(?![a-z])",
    "Apple Card": r"apple card|goldman sachs",
    "American Express": r"american express|(?<![a-z])amex(?![a-z])",
    "Ally Bank": r"(?<![a-z])ally(?![a-z])",
    "PA Central FCU": r"pa central|pennsylvania central|central federal credit union|\bpacfcu\b",
    "Nelnet": r"nelnet",
    "Fidelity": r"fidelity",
}
CAR_LENDER_HINTS = r"auto loan|vehicle|vin\b|auto finance|car loan"
DATE_RX = r"\b(\d{1,2}/\d{1,2}/\d{2,4}|\d{4}-\d{2}-\d{2}|(?:jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)[a-z]* \d{1,2},? \d{4})\b"


def guess_institution(text: str, name: str) -> str:
    hay = f"{name}\n{text}".lower()
    hits = [k for k, rx in INSTITUTIONS.items() if re.search(rx, hay)]
    if not hits and re.search(CAR_LENDER_HINTS, hay):
        return "Car loan lender (unknown)"
    return ", ".join(hits) or "unknown"


def pdf_text(path: Path, max_pages: int = 3) -> tuple[str, int]:
    try:
        pages = int(re.search(r"Pages:\s+(\d+)", subprocess.run(
            ["pdfinfo", str(path)], capture_output=True, text=True).stdout).group(1))
    except Exception:
        pages = -1
    txt = subprocess.run(["pdftotext", "-layout", "-l", str(max_pages), str(path), "-"],
                         capture_output=True, text=True).stdout
    return txt, pages


def describe_csv(raw: str) -> list[str]:
    out = []
    try:
        dialect = csv.Sniffer().sniff(raw[:4096])
    except csv.Error:
        dialect = csv.excel
    rows = list(csv.reader(io.StringIO(raw), dialect))
    # header = first row with 3+ non-empty cells
    hi = next((i for i, r in enumerate(rows) if sum(bool(c.strip()) for c in r) >= 3), 0)
    out.append(f"  header (row {hi + 1}): {rows[hi] if rows else []}")
    body = [r for r in rows[hi + 1:] if any(c.strip() for c in r)]
    out.append(f"  data rows: {len(body)}")
    for r in body[:3]:
        out.append(f"  sample: {r}")
    dates = re.findall(DATE_RX, raw, flags=re.I)
    if dates:
        out.append(f"  dates seen: {dates[0]} … {dates[-1]}")
    return out


def describe(path: Path) -> list[str]:
    ext = path.suffix.lower()
    lines = [f"== {path.name}  ({path.stat().st_size:,} bytes)"]
    if ext in (".csv", ".txt"):
        raw = path.read_text(encoding="utf-8-sig", errors="replace")
        lines.append(f"  type: CSV · institution guess: {guess_institution(raw[:3000], path.name)}")
        lines += describe_csv(raw)
    elif ext in (".xlsx", ".xls"):
        import pandas as pd
        try:
            sheets = pd.read_excel(path, sheet_name=None, header=None)
        except Exception as exc:
            return lines + [f"  type: Excel · could not read: {exc}"]
        for sn, df in sheets.items():
            head = df.head(15).fillna("").astype(str).values.tolist()
            text = " ".join(" ".join(r) for r in head)
            lines.append(f"  sheet '{sn}': {df.shape[0]} rows x {df.shape[1]} cols · institution guess: "
                         f"{guess_institution(text, path.name)}")
            for r in head[:6]:
                lines.append(f"    {r}")
    elif ext == ".pdf":
        txt, pages = pdf_text(path)
        chars = len(txt.strip())
        readable = chars > 200
        lines.append(f"  type: PDF · pages: {pages} · text layer: {'yes' if readable else 'NO (scanned?) - needs review'}")
        lines.append(f"  institution guess: {guess_institution(txt, path.name)}")
        if readable:
            m = re.findall(r"(?i)(?:statement (?:period|date)|closing date|billing period|period ending)[^\n]{0,60}", txt)
            if m:
                lines.append(f"  period: {m[0]}")
            amounts = len(re.findall(r"-?\$?\d{1,3}(?:,\d{3})*\.\d{2}\b", txt))
            lines.append(f"  money values on first pages: {amounts}")
            first = [l.strip() for l in txt.splitlines() if l.strip()][:8]
            lines += [f"    | {l[:110]}" for l in first]
    elif ext in (".qfx", ".ofx", ".qbo"):
        raw = path.read_text(errors="replace")
        n = raw.upper().count("<STMTTRN>")
        lines.append(f"  type: OFX/QFX · transactions: {n} · institution guess: {guess_institution(raw[:3000], path.name)}")
    else:
        lines.append("  type: unsupported file type (send CSV, XLSX, PDF, QFX/OFX)")
    return lines


def main(folder: str) -> None:
    files = sorted(p for p in Path(folder).rglob("*") if p.is_file() and not p.name.startswith(("~$", ".")))
    if not files:
        print("No files yet.")
        return
    for p in files:
        try:
            print("\n".join(describe(p)))
        except Exception as exc:  # never stop the whole inventory on one bad file
            print(f"== {p.name}\n  could not inspect: {exc}")
        print()


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else ".")
