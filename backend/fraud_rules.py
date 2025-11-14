import re

def check_invoice_integrity(extracted_docs):
    """Simple rule-based fraud detection engine."""

    rules = []

    # --- Invoice total vs item total ---
    for d in extracted_docs:
        if not d.get("items"): 
            continue

        try:
            sum_items = sum(
                float(re.sub(r"[^\d.]", "", i.get("Amount", "0"))) 
                for i in d["items"] if i.get("Amount")
            )
            inv_total = float(re.sub(r"[^\d.]", "", str(d.get("amount") or 0)))

            if abs(sum_items - inv_total) > 0.02 * inv_total:
                rules.append({
                    "rule": "Invoice total mismatch",
                    "severity": "High",
                    "doc": d["filename"],
                    "explanation": f"Sum of item totals ({sum_items}) ≠ invoice total ({inv_total})."
                })
        except Exception:
            continue

    # --- Exporter punctuation spoof ---
    exporters = [d.get("exporter") for d in extracted_docs if d.get("exporter")]
    normalized = [re.sub(r"[\W_]", "", e.lower()) for e in exporters]
    if len(set(normalized)) > 1:
        rules.append({
            "rule": "Exporter name format variation",
            "severity": "Medium",
            "explanation": f"Exporter names differ slightly: {', '.join(exporters)}"
        })

    # --- Duplicate invoice numbers ---
    invoice_numbers = [d.get("invoice_no") for d in extracted_docs if d.get("invoice_no")]
    if len(invoice_numbers) != len(set(invoice_numbers)):
        rules.append({
            "rule": "Duplicate Invoice Number",
            "severity": "High",
            "explanation": f"Repeated invoice number found: {invoice_numbers}"
        })

    return rules
