# backend/main.py

from fastapi import FastAPI, File, UploadFile, Form
from fastapi.responses import JSONResponse
from fastapi.middleware.cors import CORSMiddleware
from typing import List
import os, re, io
from datetime import datetime
from itertools import combinations
from pattern_detector import detect_patterns
from fraud_rules import check_invoice_integrity



# ---------- Optional imports (graceful fallbacks) ----------
# NLP (optional)
try:
    import spacy
    nlp = spacy.load("en_core_web_sm")
except Exception:
    nlp = None

# Fuzzy (optional)
try:
    from rapidfuzz import process, fuzz
except Exception:
    process = None
    fuzz = None

# OCR (optional)
try:
    import pytesseract
    from pdf2image import convert_from_path
    from PIL import Image
    OCR_AVAILABLE = True
except Exception:
    OCR_AVAILABLE = False

# DOCX (optional)
try:
    import docx2txt
    DOCX_AVAILABLE = True
except Exception:
    DOCX_AVAILABLE = False

# XLSX (optional)
try:
    import pandas as pd
    XLSX_AVAILABLE = True
except Exception:
    XLSX_AVAILABLE = False



import json, pathlib

MEMORY_FILE = pathlib.Path("memory_store.json")

def load_memory():
    if MEMORY_FILE.exists():
        try:
            with open(MEMORY_FILE, "r") as f:
                return json.load(f)
        except Exception:
            return []
    return []

def save_memory(records):
    with open(MEMORY_FILE, "w") as f:
        json.dump(records[-10:], f, indent=2)  # keep only last 10 runs

# ---------- App ----------
app = FastAPI(title="Document Intelligence v0.9 – Trade Compliance (Template-Agnostic step)")
origins = ["*"]
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
# ---------------------------------------------------------------

# ---------------------------------------------------------------


# ---------- Domain dictionaries ----------
COMPANY_SUFFIXES = ["Pvt Ltd", "Private Limited", "LLC", "Ltd", "Co.", "Limited"]
CURRENCY_SYMS = ["USD", "EUR", "INR", "GBP", "$", "€", "₹", "£"]
PORT_KEYWORDS = ["Port of Loading", "Port of Destination", "Port of Discharge", "Port"]
TRANSPORT_MODES = ["Sea", "Air", "Road", "Rail", "Courier", "Ship", "Vessel", "Flight"]

# Field synonyms (template-agnostic mapping)
FIELD_SYNONYMS = {
    "invoice_no": [r"invoice\s*no\.?", r"inv\s*#?", r"invoice\s*number", r"bill\s*no\.?", r"reference\s*no\.?"],
    "date": [r"\bdate\b", r"invoice\s*date", r"dt\."],
    "exporter": [r"\bexporter\b", r"\bseller\b", r"\bshipper\b", r"exported\s*by"],
    "consignee": [r"\bconsignee\b", r"\bbuyer\b", r"\bto\s*party\b", r"\bclient\b"],
    "currency": [r"\bcurrency\b", r"\bcur\b"],
    "port_loading": [r"port\s*of\s*loading", r"pol\b"],
    "port_dest": [r"port\s*of\s*(destination|discharge)", r"pod\b", r"final\s*destination"],
    "mode": [r"mode\s*of\s*transport", r"\btransport\b", r"\bby\s*(air|sea|road|rail)\b"],
    "gstin": [r"\bgstin\b"]
}

# ---------- Helpers ----------
def rex(pattern, text, flags=re.IGNORECASE, group=1):
    if not text:
        return None
    m = re.search(pattern, text, flags)
    return m.group(group).strip() if m else None

def fuzzy_fix(token, choices, score_cutoff=70):
    if not token or process is None:
        return token, 0.0
    best = process.extractOne(token, choices, scorer=fuzz.WRatio)
    if best and best[1] >= score_cutoff:
        return best[0], best[1] / 100.0
    return token, 0.0

def safe_int(s):
    try:
        return int(re.sub(r"[^\d]", "", str(s)))
    except Exception:
        return 0

def classify_lines(raw_text):
    if not raw_text:
        return []
    lines = [ln.strip() for ln in raw_text.splitlines() if ln.strip()]
    labeled = []
    for idx, ln in enumerate(lines):
        label = "other"
        low = ln.lower()
        if re.search(r"invoice\s*no", low):
            label = "invoice_no"
        elif re.search(r"^\s*invoice\b", low):
            label = "title"
        elif re.search(r"\bdate\b", low):
            label = "date"
        elif re.search(r"exporter|exported by", low):
            label = "exporter_header"
        elif re.search(r"consignee", low):
            label = "consignee_header"
        elif any(pk.lower() in low for pk in PORT_KEYWORDS):
            label = "port"
        elif any(tm.lower() in low for tm in TRANSPORT_MODES):
            label = "transport"
        elif re.search(r"(hs\s*code|qty|quantity|\$|\b\d{6,8}\b)", low):
            label = "possible_item"
        labeled.append({
            "index": idx,
            "line": ln,
            "label": label,
            "confidence": round(0.90 if label != "other" else 0.75, 2)
        })
    return labeled

def extract_items_from_lines(lines):
    items = []
    if not lines:
        return items
    text = " \n".join([l["line"] for l in lines])

    # General horizontal table pattern
    pattern = re.compile(
        r"([A-Za-z0-9 &/(),\-]+?)\s+([0-9]{6,8})\s+([0-9]{1,6})\s+\$?([0-9,]+(?:\.[0-9]{2})?)",
        re.IGNORECASE,
    )
    for m in pattern.finditer(text):
        desc, hs, qty, amt = m.groups()
        items.append({
            "Description": desc.strip(),
            "HS Code": hs.strip(),
            "Quantity": qty.strip(),
            "Amount": amt.strip(),
            "Currency": "USD" if "$" in m.group(0) or "USD" in text else None
        })

    # fallback
    if not items:
        for l in lines:
            ln = l["line"]
            hs_m = re.search(r"\b([0-9]{6,8})\b", ln)
            if hs_m:
                tokens = re.split(r"\s+", ln)
                try:
                    pos = tokens.index(hs_m.group(1))
                except ValueError:
                    pos = -1
                qty = None
                amt = None
                if pos != -1 and pos + 1 < len(tokens) and re.fullmatch(r"[0-9]{1,6}", tokens[pos + 1]):
                    qty = tokens[pos + 1]
                amt_m = re.search(r"\$?([0-9,]+(?:\.[0-9]{2})?)", ln)
                if amt_m:
                    amt = amt_m.group(1)
                items.append({
                    "Description": " ".join(tokens[:pos]) if pos > 0 else None,
                    "HS Code": hs_m.group(1),
                    "Quantity": qty,
                    "Amount": amt,
                    "Currency": "USD" if "$" in ln or "USD" in ln else None
                })
    return items

def clean_company_name(name):
    if not name:
        return None, 0.0
    if nlp:
        doc = nlp(name)
        org_tokens = [ent.text for ent in doc.ents if ent.label_ in ("ORG", "PERSON")]
        base = org_tokens[0] if org_tokens else name
    else:
        base = name
    fixed, score = fuzzy_fix(base, COMPANY_SUFFIXES, score_cutoff=60)
    if fixed in COMPANY_SUFFIXES and fixed not in base:
        base = base + " " + fixed
    return base.strip(), score

def extract_ports_and_transport(lines, raw_text):
    port_loading = rex(r"Port of Loading\s*[:\-]?\s*([A-Za-z ,]+)", raw_text)
    port_dest = rex(r"Port of (Destination|Discharge)\s*[:\-]?\s*([A-Za-z ,]+)", raw_text, group=2)
    mode = rex(r"(Mode of Transport|Transport|By)\s*[:\-]?\s*([A-Za-z ]+)", raw_text, group=2)
    if not port_loading or not port_dest or not mode:
        for l in (lines or []):
            if l["label"] == "port":
                low = l["line"].lower()
                if not port_loading and "loading" in low:
                    port_loading = re.sub(r".*loading[:\-]?", "", l["line"], flags=re.I).strip()
                if not port_dest and any(x in low for x in ["destination", "discharge"]):
                    port_dest = re.sub(r".*(destination|discharge)[:\-]?", "", l["line"], flags=re.I).strip()
            if l["label"] == "transport" and not mode:
                mode = re.sub(r".*(transport|by)[:\-]?", "", l["line"], flags=re.I).strip()
    if not mode and port_loading and port_dest:
        mode = "Sea" if "nhava" in (port_loading or "").lower() or "port" in (port_loading or "").lower() else None
    return port_loading, port_dest, mode

def build_summary(fields, items):
    inv = fields.get("Invoice No", {}).get("value")
    date = fields.get("Date", {}).get("value")
    exporter = fields.get("Exporter", {}).get("value")
    consignee = fields.get("Consignee", {}).get("value")
    total_amt = fields.get("Amount", {}).get("value")
    currency = fields.get("Currency", {}).get("value") or ("USD" if any(i.get("Currency") == "USD" for i in items) else None)
    port_loading = fields.get("Port of Loading", {}).get("value")
    port_dest = fields.get("Port of Destination", {}).get("value")
    mode = fields.get("Mode of Transport", {}).get("value")

    parts = []
    if inv: parts.append(f"Invoice {inv}")
    if date: parts.append(f"dated {date}")
    header = " ".join(parts) if parts else "Invoice"

    who = []
    if exporter: who.append(f"from {exporter}")
    if consignee: who.append(f"to {consignee}")

    line_items = f"{len(items)} item{'s' if len(items) != 1 else ''}" if items else "no line items detected"
    ship_phrase = ""
    if port_loading and port_dest:
        ship_phrase = f" Shipped from {port_loading} to {port_dest}"
        if mode: ship_phrase += f" via {mode}"
    amount_phrase = f", total {currency} {total_amt}" if total_amt else ""

    return f"{header} {' '.join(who)}, {line_items}{amount_phrase}.{ship_phrase}".strip()

# ---------------------------------------------------------------
# AI EXPLANATION ENGINE (rule-based)
# ---------------------------------------------------------------
def generate_explanation(field, v1, v2):
    """
    Accepts either scalars or lists for v1/v2.
    Returns explanation dict with issue_summary, suggestion, severity.
    """
    # Normalize inputs for brief summary
    def fmt(x):
        if isinstance(x, list):
            return ", ".join([str(i) for i in x if i is not None and str(i).strip()])
        return str(x) if x is not None else ""

    f = str(field).lower()
    val1 = fmt(v1)
    val2 = fmt(v2)
    explanation = ""
    suggestion = ""
    severity = "Low"

    # numeric checks
    if f in ["qty_sum", "quantity", "amount", "value"]:
        explanation = f"{field.replace('_',' ').title()} mismatch: {val1} vs {val2}."
        suggestion = "Verify item-level totals and packing list quantities; check rounding or consolidated shipments."
        severity = "High" if f in ["amount", "value"] else "Medium"

    elif f in ["invoice_no", "invoice no", "bill_no", "reference"]:
        explanation = f"Invoice/reference mismatch: {val1} vs {val2}."
        suggestion = "Ensure all documents reference the correct invoice number and revision."
        severity = "High"

    elif f in ["exporter", "shipper"]:
        explanation = f"Exporter/shipper mismatch: {val1} vs {val2}."
        suggestion = "Confirm whether forwarding agent or ultimate exporter differs; prefer legal entity on invoice."
        severity = "Medium"

    elif f in ["consignee", "buyer"]:
        explanation = f"Consignee mismatch: {val1} vs {val2}."
        suggestion = "Ensure consignee is identical on invoice, packing list and BL to avoid customs issues."
        severity = "High"

    elif f in ["currency"]:
        explanation = f"Currency mismatch: {val1} vs {val2}."
        suggestion = "Make sure all documents use the same transaction currency or show equivalent conversions."
        severity = "Medium"

    elif f in ["port_loading", "port_dest", "port of loading", "port of destination"]:
        explanation = f"Port mismatch: {val1} vs {val2}."
        suggestion = "Confirm port abbreviations and full names; check if transshipment or alternate port used."
        severity = "Medium"

    elif f in ["mode", "mode of transport"]:
        explanation = f"Transport mode mismatch: {val1} vs {val2}."
        suggestion = "Verify mode (Sea/Air/Road) across BL, invoice, and insurance documents."
        severity = "Medium"

    else:
        explanation = f"{field} differences detected: {val1} vs {val2}."
        suggestion = "Review documents and confirm which value is authoritative."
        severity = "Low"

    return {
        "field": field,
        "issue_summary": explanation,
        "suggestion": suggestion,
        "severity": severity,
        "value1": val1,
        "value2": val2
    }

# ---------- Text extraction (with OCR + Office fallback) ----------
def extract_text_from_file(file_path: str, filename: str) -> str:
    ext = os.path.splitext(filename or "")[1].lower()

    # DOCX
    if ext in [".docx"] and DOCX_AVAILABLE:
        try:
            return (docx2txt.process(file_path) or "")
        except Exception:
            return ""

    # XLS/XLSX
    if ext in [".xls", ".xlsx"] and XLSX_AVAILABLE:
        try:
            dfs = pd.read_excel(file_path, sheet_name=None)
            parts = []
            for _, df in dfs.items():
                parts.append(df.fillna("").astype(str).to_string(index=False))
            return "\n\n".join(parts)
        except Exception:
            return ""

    # PDF
    if ext == ".pdf":
        text = ""
        try:
            import pdfplumber
            with pdfplumber.open(file_path) as pdf:
                for page in pdf.pages:
                    t = page.extract_text() or ""
                    text += ("\n" + t)
        except Exception:
            text = ""

        # OCR fallback if text is empty or too short
        if (len(text.strip()) < 50) and OCR_AVAILABLE:
            try:
                print("[INFO] Running OCR fallback for low-text PDF:", filename)
                images = convert_from_path(file_path, dpi=200)
                ocr_chunks = [pytesseract.image_to_string(img) for img in images]
                text = "\n".join(ocr_chunks)
            except Exception as e:
                print("[WARN] OCR failed:", e)
        return text or ""


    # Unknown file
    return ""

# ---------- Field extraction via synonyms ----------
def find_field_by_synonyms(text: str, field_key: str):
    if not text:
        return None
    patterns = FIELD_SYNONYMS.get(field_key, [])
    for pat in patterns:
        m = re.search(pat + r"\s*[:\-]?\s*([^\n\r]+)", text, flags=re.I)
        if m:
            return m.group(1).strip()
        m2 = re.search(pat + r".*?\n\s*([^\n\r]{2,100})", text, flags=re.I)
        if m2:
            return m2.group(1).strip()
    return None

# ---------- Core single-file extraction ----------
def extract_core(text: str):
    lines_labeled = classify_lines(text)
    items = extract_items_from_lines(lines_labeled)
    port_loading, port_dest, mode = extract_ports_and_transport(lines_labeled, text)

    invoice_no = find_field_by_synonyms(text, "invoice_no") or rex(r"Invoice\s*No\.?\s*[:\-]?\s*([A-Za-z0-9\/\-]+)", text)
    date = find_field_by_synonyms(text, "date") or rex(r"Date\s*[:\-]?\s*([0-9]{1,2}[-/][A-Za-z]{3,}[-/][0-9]{2,4})", text)
    exporter_raw = find_field_by_synonyms(text, "exporter")
    consignee_raw = find_field_by_synonyms(text, "consignee")
    currency = find_field_by_synonyms(text, "currency") or rex(r"\b(USD|EUR|INR|GBP)\b", text) or ("USD" if "$" in text else None)
    gstin = find_field_by_synonyms(text, "gstin") or rex(r"GSTIN[:\-]?\s*([0-9A-Z]{15})", text)
    amount = rex(r"\$\s*([0-9,]+(?:\.[0-9]{2})?)", text) or rex(r"Amount\s*\(?USD\)?\s*[:\-]?\s*\$?([0-9,]+(?:\.[0-9]{2})?)", text)

    exporter_clean, exporter_score = clean_company_name(exporter_raw)
    consignee_clean, consignee_score = clean_company_name(consignee_raw)

    def conf(val): return 0.95 if val else 0.0

    key_fields = {
        "Invoice No": {"value": invoice_no, "validated": bool(invoice_no), "final_confidence": conf(invoice_no)},
        "Date": {"value": date, "validated": bool(date), "final_confidence": conf(date)},
        "Exporter": {"value": exporter_clean, "validated": bool(exporter_clean), "final_confidence": round(0.5 + (exporter_score or 0)*0.5, 2) if exporter_clean else 0.0},
        "Exporter Raw": {"value": exporter_raw, "validated": bool(exporter_raw), "final_confidence": conf(exporter_raw)},
        "Consignee": {"value": consignee_clean, "validated": bool(consignee_clean), "final_confidence": round(0.5 + (consignee_score or 0)*0.5, 2) if consignee_clean else 0.0},
        "Consignee Raw": {"value": consignee_raw, "validated": bool(consignee_raw), "final_confidence": conf(consignee_raw)},
        "GSTIN": {"value": gstin, "validated": bool(gstin), "final_confidence": conf(gstin)},
        "Amount": {"value": amount, "validated": bool(amount), "final_confidence": conf(amount)},
        "Currency": {"value": currency, "validated": bool(currency), "final_confidence": conf(currency)},
        "Port of Loading": {"value": port_loading, "validated": bool(port_loading), "final_confidence": conf(port_loading)},
        "Port of Destination": {"value": port_dest, "validated": bool(port_dest), "final_confidence": conf(port_dest)},
        "Mode of Transport": {"value": mode, "validated": bool(mode), "final_confidence": conf(mode)},
        "Items": {"value": items, "validated": bool(items), "final_confidence": 0.95 if items else 0.0},
    }

    summary = build_summary(key_fields, items)
    confidences = [v["final_confidence"] for v in key_fields.values() if isinstance(v.get("final_confidence"), (int, float))]
    overall = round(sum(confidences) / len(confidences), 2) if confidences else 0.0

    return key_fields, items, lines_labeled, summary, overall

# ---------------------------------------------------------------
#  SINGLE FILE EXTRACTION
# ---------------------------------------------------------------
@app.post("/extract")
async def extract_text(file: UploadFile = File(...), review_mode: bool = Form(False)):
    file_location = f"temp_{file.filename}"
    with open(file_location, "wb") as f:
        f.write(await file.read())

    try:
        text = extract_text_from_file(file_location, file.filename)
        key_fields, items, lines_labeled, summary, overall = extract_core(text)

        line_meta = []
        for idx, ln in enumerate((text or "").splitlines()):
            if ln.strip():
                line_meta.append({"page": 1, "index": idx, "text": ln.strip()})

        output = {
            "filename": file.filename,
            "overall_confidence": overall,
            "summary": summary,
            "key_fields": key_fields,
            "items": items,
            "debug_lines": lines_labeled[:50],
            "meta": {
                "pages": 1,
                "lines": len(line_meta),
                "review_mode": review_mode
            }
        }
        if review_mode:
            output["visual_map"] = line_meta

        return JSONResponse(output)
    finally:
        if os.path.exists(file_location):
            os.remove(file_location)

# ---------------------------------------------------------------
#  MULTI-DOC UPLOAD + COMPARISON
# ---------------------------------------------------------------
@app.post("/compare")
async def compare_docs(files: List[UploadFile] = File(...)):

    extracted_docs = []

    # Extract each
    for file in files:
        file_location = f"temp_{file.filename}"
        with open(file_location, "wb") as f:
            f.write(await file.read())
        try:
            text = extract_text_from_file(file_location, file.filename)
            print("\n----- Extracted Text Preview -----\n", text[:1000], "\n----------------------------------\n")

            key_fields, items, _, summary, _ = extract_core(text)
            doc_info = {
                "filename": file.filename,
                "summary": summary,
                "invoice_no": key_fields["Invoice No"]["value"],
                "date": key_fields["Date"]["value"],
                "amount": key_fields["Amount"]["value"],
                "currency": key_fields["Currency"]["value"],
                "exporter": key_fields["Exporter"]["value"] or key_fields["Exporter Raw"]["value"],
                "consignee": key_fields["Consignee"]["value"] or key_fields["Consignee Raw"]["value"],
                "port_loading": key_fields["Port of Loading"]["value"],
                "port_dest": key_fields["Port of Destination"]["value"],
                "mode": key_fields["Mode of Transport"]["value"],
                "qty_sum": sum(safe_int(i.get("Quantity")) for i in items),
                "items": items
            }
            extracted_docs.append(doc_info)
        finally:
            if os.path.exists(file_location):
                os.remove(file_location)

    fields = ["invoice_no", "date", "exporter", "consignee", "port_loading", "port_dest", "mode", "currency", "qty_sum"]

    comparison_table = []
    mismatch_report = []

    # Master row comparison (all docs side-by-side)
    for field in fields:
        values = [doc.get(field) for doc in extracted_docs]
        # normalize string forms for uniqueness check
        normalized = set([str(v).strip() for v in values if v not in (None, "", [])])
        status = "Match" if len(normalized) == 1 else "Mismatch"
        if all(v is None or v == "" or v == [] for v in values):
            status = "Missing"

        comparison_table.append({
            "field": field,
            "values": values,
            "status": status
        })

        if status == "Mismatch":
            # create explanation for master mismatch (list of values)
            explanation = generate_explanation(field, values, None)
            mismatch_report.append({
                "field": field,
                "values": values,
                "issue": explanation["issue_summary"],
                "suggestion": explanation["suggestion"],
                "severity": explanation["severity"]
            })

    # Pairwise metadata (all combinations)
    pairwise = []
    for a, b in combinations(extracted_docs, 2):
        for f in fields:
            v1, v2 = a.get(f), b.get(f)
            stat = "Match" if str(v1).strip() == str(v2).strip() else "Mismatch"
            if (not v1) and (not v2):
                stat = "Missing"
            expl = None
            if stat != "Match":
                expl = generate_explanation(f, v1, v2)
            pairwise.append({
                "field": f,
                "doc1": a["filename"],
                "doc2": b["filename"],
                "value1": v1,
                "value2": v2,
                "status": stat,
                "explanation": expl
            })

    # ---------------------------------------
    # HS CODE INTELLIGENCE (Phase 2 Start)
    # ---------------------------------------
    hs_map = []
    for d in extracted_docs:
        for it in d.get("items", []) or []:
            hs = it.get("HS Code")
            if hs:
                hs_map.append({"doc": d["filename"], "hs": hs.strip()})

    hs_summary = ""
    hs_risk = "Low"
    if not hs_map:
        hs_summary = "No HS codes found in any document."
        hs_risk = "High"
    else:
        unique_codes = list({h["hs"] for h in hs_map})
        chapters = [h["hs"][:2] for h in hs_map if len(h["hs"]) >= 2]
        unique_chapters = list(set(chapters))

        if len(unique_codes) == 1:
            hs_summary = f"All documents share the same HS Code: {unique_codes[0]}"
            hs_risk = "Low"
        elif len(unique_chapters) == 1:
            hs_summary = f"Different HS Codes, but same chapter ({unique_chapters[0]}). Moderate consistency."
            hs_risk = "Medium"
        else:
            hs_summary = f"HS Code inconsistency detected. Chapters differ across documents: {', '.join(unique_chapters)}"
            hs_risk = "High"

        # ---------------------------------------
    # HS CODE INTELLIGENCE
    # ---------------------------------------
    hs_analysis = {
        "summary": hs_summary,
        "risk_level": hs_risk,
        "details": hs_map
    }


    

    # ---------------------------------------------------------------
    # INCOTERM INTELLIGENCE (Phase 2.3)
    # ---------------------------------------------------------------
        # ---------------------------------------------------------------
    # STRONGER INCOTERM DETECTION
    # ---------------------------------------------------------------
        # ---------------------------------------------------------------
    # FINAL ROBUST INCOTERM DETECTION (no false positives)
    # ---------------------------------------------------------------
    # INCOTERMS_LIST = [
    #     "EXW", "FCA", "FAS", "FOB", "CFR", "CIF",
    #     "CPT", "CIP", "DAP", "DPU", "DDP"
    # ]

    # def normalize_text(t: str):
    #     if not t:
    #         return ""
    #     # Normalize spaces and punctuation, uppercase for consistency
    #     t = re.sub(r"[\n\r]+", " ", t)
    #     t = re.sub(r"[^A-Z0-9 ]", " ", t.upper())
    #     t = re.sub(r"\s{2,}", " ", t)
    #     return t.strip()

    # def find_incoterms(text: str):
    #     found = []
    #     text_norm = normalize_text(text)
    #     for term in INCOTERMS_LIST:
    #         # Match variations like 'CIF', 'C I F', 'CIFNOVOROSSIYSK', 'CIF 2020'
    #         pattern = rf"\b{term}\b|{' '.join(term)}|{term}[A-Z ]{{0,15}}2020"
    #         if re.search(pattern, text_norm, flags=re.I):
    #             found.append(term)
    #     return list(set(found))

    # incoterm_hits = []
    # for d in extracted_docs:
    #     text_block = " ".join([
    #         str(d.get("summary") or ""),
    #         str(d.get("port_loading") or ""),
    #         str(d.get("port_dest") or ""),
    #         str(d.get("invoice_no") or ""),
    #     ])
    #     found_terms = find_incoterms(text_block)
    #     if found_terms:
    #         incoterm_hits.append({
    #             "document": d["filename"],
    #             "term": ", ".join(found_terms)
    #         })

    # if not incoterm_hits:
    #     incoterm_analysis = {
    #         "summary": "No Incoterms detected in the provided documents.",
    #         "risk_level": "High",
    #         "details": []
    #     }
    # else:
    #     unique_terms = list({t for h in incoterm_hits for t in h["term"].split(", ")})
    #     incoterm_risk = "Low" if len(unique_terms) == 1 else "Medium"
    #     incoterm_analysis = {
    #         "summary": f"Detected Incoterm(s): {', '.join(unique_terms)}",
    #         "risk_level": incoterm_risk,
    #         "details": incoterm_hits
    #     }


    # ---------------------------------------------------------------
    # SANCTION & ORIGIN SCREENING (Phase 2.4 Fixed)
    # ---------------------------------------------------------------
    SANCTIONED_COUNTRIES = {
        "IRAN": "High-risk — comprehensive sanctions (OFAC, EU, UN)",
        "SYRIA": "High-risk — export & financial restrictions",
        "NORTH KOREA": "High-risk — complete embargo",
        "CRIMEA": "High-risk — annexed territory, EU/US trade ban",
        "CUBA": "Restricted — subject to export-license requirements",
        "RUSSIA": "Medium-High — sectoral sanctions & port restrictions",
        "BELARUS": "Medium-High — aligned with Russian sanctions",
        "SUDAN": "Medium — certain financial restrictions"
    }

    RESTRICTED_PORTS = [
        "SEVASTOPOL", "NOVOROSSIYSK", "BANDAR ABBAS",
        "LATTAKIA", "HAVANA", "PYONGYANG"
    ]

    sanction_hits = []
    sanction_risk = "Low"

    def detect_sanctions(text_block: str):
        matches = []
        upper = text_block.upper()
        for country, desc in SANCTIONED_COUNTRIES.items():
            if re.search(rf"\b{country}\b", upper):
                matches.append({"entity": country, "type": "Country", "reason": desc})
        for port in RESTRICTED_PORTS:
            if re.search(rf"\b{port}\b", upper):
                matches.append({"entity": port, "type": "Port", "reason": "Restricted port / embargoed route"})
        return matches

    for d in extracted_docs:
        block = " ".join([
            str(v) for v in [
                d.get("exporter"), d.get("consignee"),
                d.get("port_loading"), d.get("port_dest"),
                d.get("summary")
            ] if v
        ])
        found = detect_sanctions(block)
        for f in found:
            f["document"] = d["filename"]
        sanction_hits.extend(found)

    if sanction_hits:
        sanction_risk = "High" if any(h["type"] == "Country" for h in sanction_hits) else "Medium"

    sanction_analysis = {
        "summary": f"{len(sanction_hits)} potential sanction-related entities detected."
        if sanction_hits else "No sanction-related entities detected.",
        "risk_level": sanction_risk,
        "details": sanction_hits
    }




    # ---------------------------------------
    # PHASE 2.5 – AI Trade Risk Insights
    # ---------------------------------------
    risk_score = 0
    reasons = []

    # HS Risk
    hs_risk = hs_analysis.get("risk_level", "Low")
    if hs_risk == "Medium":
        risk_score += 25
        reasons.append("Moderate HS code inconsistency across documents")
    elif hs_risk == "High":
        risk_score += 45
        reasons.append("Significant HS code inconsistency (different chapters)")

    # Sanction / Origin risk
    sanction_flag = any(
        kw.lower() in str(d.get("port_dest", "")).lower() + str(d.get("exporter", "")).lower()
        for kw in ["russia", "iran", "syria", "belarus", "crimea", "north korea"]
    )
    if sanction_flag:
        risk_score += 35
        reasons.append("Involvement of sanctioned or high-risk region")

    # Critical mismatches
    if len(mismatch_report) > 0:
        add = min(20 + 5 * len(mismatch_report), 40)
        risk_score += add
        reasons.append(f"{len(mismatch_report)} critical field mismatches detected")

    # Normalize and classify
    risk_score = min(risk_score, 100)
    if risk_score < 30:
        level = "Low"
    elif risk_score < 60:
        level = "Medium"
    else:
        level = "High"

    risk_explanation = {
        "score": risk_score,
        "level": level,
        "reasons": reasons or ["No major issues detected"]
    }

    pattern_alerts = detect_patterns(extracted_docs)
    fraud_report = check_invoice_integrity(extracted_docs)

       # ---------------------------------------------------------------
    # 🧠 Phase 4.1 — Cognitive Score & Summary
    # ---------------------------------------------------------------
    def score_from_level(level):
        if not level:
            return 100
        return {"Low": 95, "Medium": 75, "High": 45}.get(level, 80)

    # base score from detected issues
    mismatch_penalty = len(mismatch_report) * 4
    fraud_penalty = len([f for f in locals().get("fraud_report", []) if f.get("severity") == "High"]) * 8
    pattern_penalty = len([p for p in locals().get("pattern_alerts", []) if p.get("severity") == "High"]) * 5

    hs_score = score_from_level(hs_analysis.get("risk_level"))
    sanc_score = score_from_level(locals().get("sanction_analysis", {}).get("risk_level", "Low"))
    inco_score = score_from_level(locals().get("incoterm_analysis", {}).get("risk_level", "Low"))
    base = 100 - mismatch_penalty - fraud_penalty - pattern_penalty
    weighted = (base * 0.4) + (hs_score * 0.2) + (sanc_score * 0.2) + (inco_score * 0.2)
    cognitive_score = int(max(0, min(100, weighted)))

    if cognitive_score >= 90:
        risk_tier = "Low"
    elif cognitive_score >= 70:
        risk_tier = "Medium"
    else:
        risk_tier = "High"
        
        
        

    cognitive_summary = (
        f"Across {len(extracted_docs)} documents, "
        f"{len(mismatch_report)} field mismatches"
        f"{' and ' if fraud_penalty or pattern_penalty else ''}"
        f"{'fraud/pattern anomalies detected. ' if (fraud_penalty or pattern_penalty) else '. '}"
        f"Overall trade confidence is {risk_tier} ({cognitive_score}%)."
    )

    cognitive_breakdown = {
        "HS Code": {"risk": hs_analysis.get("risk_level"), "score": hs_score},
        "Sanctions": {"risk": sanc_score and locals().get("sanction_analysis", {}).get("risk_level", "Low"), "score": sanc_score},
        "Incoterm": {"risk": inco_score and locals().get("incoterm_analysis", {}).get("risk_level", "Low"), "score": inco_score},
        "Mismatches": {"risk": "High" if mismatch_penalty > 8 else ("Medium" if mismatch_penalty > 3 else "Low"), "score": max(0, 100 - mismatch_penalty * 4)},
    }


    # -------------------------------------------------
    # 🧠 PHASE 4.4 — COGNITIVE MEMORY & ANOMALY TRACKER
    # -------------------------------------------------
    history = load_memory()
    current_record = {
        "timestamp": datetime.utcnow().isoformat(),
        "exporters": [d.get("exporter") for d in extracted_docs],
        "consignees": [d.get("consignee") for d in extracted_docs],
        "ports": [d.get("port_dest") for d in extracted_docs if d.get("port_dest")],
        "cognitive_score": cognitive_score,
        "risk_tier": risk_tier,
        "hs_risk": hs_analysis.get("risk_level"),
        "mismatch_count": len(mismatch_report),
    }
    history.append(current_record)
    save_memory(history)

    # --- Historical anomaly check ---
    recurring_exporters = set()
    recurring_ports = set()
    for prev in history[:-1]:
        for e in prev.get("exporters", []):
            if e and e in current_record["exporters"]:
                recurring_exporters.add(e)
        for p in prev.get("ports", []):
            if p and p in current_record["ports"]:
                recurring_ports.add(p)

    anomaly_note = None
    if recurring_exporters or recurring_ports:
        penalty = 5 * (len(recurring_exporters) + len(recurring_ports))
        cognitive_score = max(0, cognitive_score - penalty)
        anomaly_note = (
            f"Historical pattern detected: "
            f"{len(recurring_exporters)} recurrent exporter(s), "
            f"{len(recurring_ports)} recurrent port(s). "
            f"Cognitive score adjusted (−{penalty})."
        )

    risk_history = {
        "total_records": len(history),
        "recurring_exporters": list(recurring_exporters),
        "recurring_ports": list(recurring_ports),
        "note": anomaly_note,
    }

    # Attach full trend for graph visualization
        # Attach full trend for graph visualization + context
    trend_data = []
    for h in history:
        trend_data.append({
            "timestamp": h["timestamp"],
            "cognitive_score": h.get("cognitive_score", 0),
            "risk_tier": h.get("risk_tier", "Unknown"),
            "exporters": h.get("exporters", []),
            "ports": h.get("ports", []),
            "mismatch_count": h.get("mismatch_count", 0),
        })
    risk_history["trend_data"] = trend_data

        # ---------------------------------------------------------------
    # 🌍 Cognitive Heatmap: Exporter × Port Risk Aggregation
    # ---------------------------------------------------------------
    heatmap_data = []
    exporter_port_map = {}

    # Build mapping based on extracted_docs
    for d in extracted_docs:
        exporter = (d.get("exporter") or "").strip() or "Unknown Exporter"
        port = (d.get("port_dest") or "").strip() or "Unknown Port"
        risk_score = 0

        # Basic risk heuristic (you can refine later)
        if not exporter or not port:
            risk_score = 90
        elif "Limited" in exporter or "LLC" in exporter:
            risk_score = 55
        elif "Russia" in (port or exporter):
            risk_score = 95
        else:
            risk_score = 60 + (hash(exporter + port) % 30)

        key = (exporter, port)
        if key not in exporter_port_map:
            exporter_port_map[key] = {"scores": [], "last_seen": datetime.utcnow()}
        exporter_port_map[key]["scores"].append(risk_score)

    # Aggregate results
    for (exp, port), val in exporter_port_map.items():
        avg_risk = sum(val["scores"]) / len(val["scores"])
        heatmap_data.append({
            "exporter": exp,
            "port": port,
            "avg_risk": round(avg_risk, 1),
            "last_seen": val["last_seen"].isoformat()
        })

    # Sort by highest risk first for easier viewing
    heatmap_data.sort(key=lambda x: x["avg_risk"], reverse=True)

    # ---------------------------------------------------------------
    # Final Response
    # ---------------------------------------------------------------
    return JSONResponse({
        "files_processed": [d["filename"] for d in extracted_docs],
        "extracted_data": extracted_docs,
        "mismatch_report": mismatch_report,
        "comparison_report": comparison_table,
        "pairwise_comparison": pairwise,
        "hs_analysis": hs_analysis,
        "cognitive_score": cognitive_score,
        "cognitive_summary": cognitive_summary,
        "cognitive_breakdown": cognitive_breakdown,
        "risk_history": risk_history,
        # "heatmap_data": heatmap_data   # 👈 Added field
         
    })


    

# ---------------------------------------------------------------
# Health check (handy)
# ---------------------------------------------------------------
@app.get("/health")
def health():
    return {
        "status": "ok",
        "ocr_available": OCR_AVAILABLE,
        "docx_available": DOCX_AVAILABLE,
        "xlsx_available": XLSX_AVAILABLE,
        "spacy": bool(nlp is not None),
        "rapidfuzz": bool(process is not None)
    }
