"""
UpQuest – Bloodwork PDF parser
Uses pdfplumber for text + table extraction.
Regex patterns cover common lab report formats.
"""

import re
import io
from typing import BinaryIO, Dict, Any

try:
    import pdfplumber
except ImportError:
    pdfplumber = None  # type: ignore


# ── Key lab markers to extract ────────────────────────────────────────────

LAB_PATTERNS: Dict[str, list[str]] = {
    "triglycerides":   ["triglycerides?", "trig"],
    "LDL":             ["ldl[- ]?c(?:holesterol)?", "low[- ]density lipoprotein"],
    "HDL":             ["hdl[- ]?c(?:holesterol)?", "high[- ]density lipoprotein"],
    "total_cholesterol": ["total cholesterol", "cholesterol,? total"],
    "non_HDL":         ["non[- ]?hdl"],
    "testosterone":    ["testosterone,? total", "total testosterone", "testosterone"],
    "free_testosterone": ["free testosterone", "testosterone,? free"],
    "glucose":         ["glucose"],
    "hba1c":           ["hba1c", "hemoglobin a1c", "glycohemoglobin"],
    "TSH":             ["tsh", "thyroid stimulating hormone"],
    "vitamin_d":       ["25[- ]?oh vitamin d", "vitamin d"],
    "creatinine":      ["creatinine"],
    "eGFR":            ["egfr", "estimated gfr"],
    "ALT":             ["alt", "alanine aminotransferase"],
    "AST":             ["ast", "aspartate aminotransferase"],
    "WBC":             ["wbc", "white blood cell"],
    "RBC":             ["rbc", "red blood cell"],
    "hemoglobin":      ["hemoglobin", "hgb"],
    "hematocrit":      ["hematocrit", "hct"],
    "PSA":             ["psa", "prostate[- ]specific antigen"],
    "SHBG":            ["shbg", "sex hormone binding globulin"],
}

VALUE_PATTERN = re.compile(
    r"([d]+\.?[d]*)\s*(?:mg/dL|ng/dL|ng/mL|mIU/L|nmol/L|mmol/L|%|U/L|IU/L|cells/mcL)?",
    re.IGNORECASE,
)


def parse_bloodwork_pdf(file: BinaryIO) -> Dict[str, Any]:
    if pdfplumber is None:
        return {"raw_text": "", "values": {}, "error": "pdfplumber not installed"}

    raw_text = ""
    tables_text = ""

    with pdfplumber.open(file) as pdf:
        for page in pdf.pages:
            page_text = page.extract_text() or ""
            raw_text += page_text + "\n"
            for table in page.extract_tables():
                for row in table:
                    if row:
                        tables_text += " | ".join(str(c) for c in row if c) + "\n"

    combined = (raw_text + "\n" + tables_text).lower()
    values: Dict[str, float] = {}

    for key, patterns in LAB_PATTERNS.items():
        for pat in patterns:
            regex = re.compile(
                rf"{pat}\s*[:\|]?\s*({VALUE_PATTERN.pattern})",
                re.IGNORECASE,
            )
            match = regex.search(combined)
            if match:
                num_match = re.search(r"[\d]+\.?[\d]*", match.group(0))
                if num_match:
                    try:
                        values[key] = float(num_match.group())
                        break
                    except ValueError:
                        pass

    return {
        "raw_text": raw_text[:8000],
        "values": values,
    }
