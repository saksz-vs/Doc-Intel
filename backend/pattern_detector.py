import statistics, re

def detect_patterns(extracted_docs):
    """Detects anomalies like value spikes, exporter variation, and transport inconsistencies."""

    alerts = []

    # --- Amount anomaly detection ---
    amounts = []
    for d in extracted_docs:
        try:
            amt = float(re.sub(r"[^\d.]", "", str(d.get("amount") or 0)))
            amounts.append(amt)
        except Exception:
            continue

    if len(amounts) >= 3:
        mean = statistics.mean(amounts)
        stdev = statistics.stdev(amounts) if len(amounts) > 1 else 0
        for i, a in enumerate(amounts):
            if stdev and abs(a - mean) / stdev > 2:
                alerts.append({
                    "type": "Value Spike",
                    "doc": extracted_docs[i]["filename"],
                    "value": a,
                    "mean": round(mean, 2),
                    "z_score": round(abs(a - mean) / stdev, 2),
                    "severity": "High" if abs(a - mean) / stdev > 3 else "Medium",
                    "message": f"Invoice amount deviates significantly from average (${mean})."
                })

    # --- Exporter name variation ---
    exporters = [d.get("exporter") for d in extracted_docs if d.get("exporter")]
    if len(set(exporters)) > 1:
        alerts.append({
            "type": "Exporter Name Variation",
            "values": exporters,
            "severity": "Medium",
            "message": "Exporter names vary slightly across documents — check for spoofing or formatting differences."
        })

    # --- Mode of transport / port mismatch pattern ---
    modes = [d.get("mode") for d in extracted_docs if d.get("mode")]
    if len(set(modes)) > 1:
        alerts.append({
            "type": "Transport Mode Variation",
            "values": modes,
            "severity": "Low",
            "message": "Different transport modes detected — verify shipment consistency."
        })

    return alerts
