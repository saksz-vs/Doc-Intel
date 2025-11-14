import React, { useEffect, useState } from "react";
import axios from "axios";
import jsPDF from "jspdf";
import { saveAs } from "file-saver";
import {
  LineChart,
  Line,
  XAxis,
  YAxis,
  Tooltip,
  CartesianGrid,
  ResponsiveContainer,
} from "recharts";
import "./App.css";

/**
 * Redesigned dashboard wrapper
 *
 * Notes:
 * - All original functionality, data variables, API calls, and chart logic are kept intact.
 * - This file adds a top nav (logo, exports, theme toggle), a collapsible sidebar (tabs),
 *   and tab-based filtering so each section behaves like a real app.
 * - Dark mode auto-detect and a manual toggle are included. Styling is in App.css.
 */

/* ----------------------------- Custom tooltip ----------------------------- */
const CustomTooltip = ({ active, payload }) => {
  if (active && payload && payload.length) {
    const d = payload[0].payload;
    return (
      <div className="tooltip-card">
        <div className="tooltip-title">Score: {d.cognitive_score}/100 ({d.risk_tier})</div>
        {d.exporters?.length > 0 && <div>Exporter: <strong>{d.exporters.join(", ")}</strong></div>}
        {d.ports?.length > 0 && <div>Ports: <strong>{d.ports.join(", ")}</strong></div>}
        <div>Mismatches: {d.mismatch_count}</div>
        <div className="tooltip-time">{new Date(d.timestamp).toLocaleString()}</div>
      </div>
    );
  }
  return null;
};

export default function App() {
  // original states preserved
  const [files, setFiles] = useState([]);
  const [data, setData] = useState(null);
  const [loading, setLoading] = useState(false);

  // new UI states
  const [sidebarOpen, setSidebarOpen] = useState(true);
  const [activeTab, setActiveTab] = useState("Overview"); // Overview = shows everything
  const [darkMode, setDarkMode] = useState(
    typeof window !== "undefined" && window.matchMedia && window.matchMedia("(prefers-color-scheme: dark)").matches
  );

  // keep it synced with body class
  useEffect(() => {
    if (darkMode) document.documentElement.classList.add("theme-dark");
    else document.documentElement.classList.remove("theme-dark");
  }, [darkMode]);

  // original handleCompare preserved
  async function handleCompare() {
    if (files.length < 2) return alert("Select at least two documents");
    setLoading(true);

    const fd = new FormData();
    files.forEach((f) => fd.append("files", f));

    try {
      const res = await axios.post("https://doc-intel-yvqm.onrender.com/compare", fd, {

        headers: { "Content-Type": "multipart/form-data" },
      });
      setData(res.data);
    } catch (e) {
      alert("Comparison failed: " + (e?.message || e));
    } finally {
      setLoading(false);
    }
  }

  // export JSON preserved
  function downloadJSON() {
    if (!data) return;
    const blob = new Blob([JSON.stringify(data, null, 2)], {
      type: "application/json",
    });
    saveAs(blob, "comparison_report.json");
  }

  // export PDF preserved (improved safety checks)
  function downloadPDF() {
    if (!data) return;
    const doc = new jsPDF({ unit: "pt", format: "a4" });
    let y = 40;
    doc.setFontSize(16);
    doc.text("Trade Document Comparison Report", 40, y);
    y += 20;

    doc.setFontSize(12);
    doc.text("Documents Processed:", 40, y);
    y += 16;
    (data.files_processed || []).forEach((f) => {
      doc.text(`• ${f}`, 60, y);
      y += 14;
    });
    y += 10;

    // Summaries
    doc.setFontSize(13);
    doc.text("Summaries:", 40, y);
    y += 16;
    doc.setFontSize(11);
    (data.extracted_data || []).forEach((d) => {
      doc.text(`${d.filename}: ${d.summary}`, 40, y);
      y += 14;
      if (y > 780) {
        doc.addPage();
        y = 40;
      }
    });

    // Mismatches
    y += 10;
    doc.setFontSize(13);
    doc.text("Critical Mismatches:", 40, y);
    y += 18;
    doc.setFontSize(11);
    if (!data.mismatch_report || !data.mismatch_report.length) {
      doc.text("No mismatches detected.", 40, y);
    } else {
      data.mismatch_report.forEach((m) => {
        const summary = m.issue_summary || m.issue || "";
        doc.text(`${m.field}: ${summary}`, 40, y);
        y += 14;
        if (m.suggestion) {
          doc.text(`→ ${m.suggestion} (${m.severity || "Medium"} severity)`, 50, y);
          y += 14;
        }
        if (y > 780) {
          doc.addPage();
          y = 40;
        }
      });
    }
    doc.save("comparison_report.pdf");
  }

  /* --------------------------- small helpers --------------------------- */
  const isTabVisible = (section) => {
    if (activeTab === "Overview") return true;
    return activeTab === section;
  };

  // quick toggle theme
  const toggleTheme = () => setDarkMode((s) => !s);

  return (
    <div className="app-root">
      {/* Top navigation */}
      <header className="topbar">
        <div className="topbar-left">
          <button
            className="burger"
            onClick={() => setSidebarOpen((s) => !s)}
            title="Toggle menu"
          >
            <svg width="20" height="20" viewBox="0 0 20 20" fill="none" aria-hidden>
              <path d="M3 5h14M3 10h14M3 15h14" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round"/>
            </svg>
          </button>

          <div className="brand">
            <img src="/logo192.png" alt="logo" className="brand-logo" />
            <div className="brand-text">
              <div className="brand-name">TradeDoc • Intelligence</div>
              <div className="brand-sub">Compliance • Comparison • Cognitive</div>
            </div>
          </div>
        </div>

        <div className="topbar-right">
          <div className="top-controls">
            <button className="btn btn-ghost" onClick={downloadJSON} title="Export JSON">
              Export JSON
            </button>
            <button className="btn btn-ghost" onClick={downloadPDF} title="Export PDF">
              Export PDF
            </button>
            <button
              className="btn btn-ghost theme-toggle"
              onClick={toggleTheme}
              title="Toggle theme"
            >
              {darkMode ? "🌙 Dark" : "☀️ Light"}
            </button>
          </div>
        </div>
      </header>

      <div className="main-content">
        {/* Sidebar */}
        <aside className={`sidebar ${sidebarOpen ? "open" : "collapsed"}`} aria-hidden={!sidebarOpen}>
          <nav>
            <ul>
              <li className={activeTab === "Overview" ? "active" : ""} onClick={() => setActiveTab("Overview")}>
                <span className="nav-icon">🏠</span> Overview
              </li>
              <li className={activeTab === "Upload" ? "active" : ""} onClick={() => setActiveTab("Upload")}>
                <span className="nav-icon">📤</span> Upload
              </li>
              <li className={activeTab === "Cognitive" ? "active" : ""} onClick={() => setActiveTab("Cognitive")}>
                <span className="nav-icon">🧠</span> Cognitive
              </li>
              <li className={activeTab === "Sanctions" ? "active" : ""} onClick={() => setActiveTab("Sanctions")}>
                <span className="nav-icon">🛑</span> Sanctions
              </li>
              <li className={activeTab === "Comparison" ? "active" : ""} onClick={() => setActiveTab("Comparison")}>
                <span className="nav-icon">🔎</span> Comparison
              </li>
              <li className={activeTab === "Analysis" ? "active" : ""} onClick={() => setActiveTab("Analysis")}>
                <span className="nav-icon">📊</span> Analysis
              </li>
            </ul>
          </nav>

          <div className="sidebar-footer">
            <div className="small">v0.9 • Prototype</div>
          </div>
        </aside>

        {/* Page area */}
        <section className="page-area">
          {/* Top summary row (kept), visible on Overview or Analysis */}
          {isTabVisible("Overview") && (
            <div className="grid-row summary-row">
              <div className="card summary-card">
                <div className="summary-title">Processed Files</div>
                <div className="summary-value">{data?.files_processed?.length ?? 0}</div>
                <div className="summary-sub">{(data?.files_processed || []).join(", ") || "No files yet"}</div>
              </div>

              <div className="card summary-card">
                <div className="summary-title">Critical Mismatches</div>
                <div className="summary-value">{data?.mismatch_report?.length ?? 0}</div>
                <div className="summary-sub">Detected across documents</div>
              </div>

              <div className="card summary-card">
                <div className="summary-title">Cognitive Score</div>
                <div className="summary-value">{data?.cognitive_score ?? "-"}</div>
                <div className="summary-sub">Aggregate confidence</div>
              </div>

              <div className="card summary-card">
                <div className="summary-title">HS Risk</div>
                <div className="summary-value">{data?.hs_analysis?.risk_level ?? "-"}</div>
                <div className="summary-sub">{data?.hs_analysis?.summary || "-"}</div>
              </div>
            </div>
          )}

          {/* Upload panel */}
          {isTabVisible("Upload") && (
            <div className="card upload-card">
              <h3 className="card-heading">Upload Documents</h3>
              <div className="upload-controls">
                <input
                  type="file"
                  multiple
                  onChange={(e) => setFiles([...e.target.files])}
                  accept=".pdf,.xls,.xlsx,.doc,.docx"
                  className="file-input"
                />
                <div className="selected-files">
                  <ul>
                    {files.map((f, i) => <li key={i} title={f.name}>{f.name}</li>)}
                  </ul>
                </div>
                <div className="action-row">
                  <button
                    onClick={handleCompare}
                    disabled={loading || files.length < 2}
                    className="btn btn-primary"
                  >
                    {loading ? "Processing..." : "Compare Documents"}
                  </button>
                </div>
              </div>
            </div>
          )}

          {/* Cognitive / Memory / Trend */}
          {isTabVisible("Cognitive") && (
            <>
              {/* Cognitive main card */}
              <div className="card">
                <h3 className="card-heading">Cognitive Confidence</h3>

                {data?.cognitive_score !== undefined && (
                  <div className="cognitive-row">
                    <div className="cog-ring">
                      <svg className="ring" viewBox="0 0 100 100">
                        <circle cx="50" cy="50" r="42" strokeWidth="8" className="ring-bg" />
                        <circle
                          cx="50"
                          cy="50"
                          r="42"
                          strokeWidth="8"
                          className={`ring-fg ${data.cognitive_score >= 90 ? "green" : data.cognitive_score >= 70 ? "yellow" : "red"}`}
                          style={{ strokeDasharray: 264, strokeDashoffset: 264 - (264 * (data.cognitive_score || 0)) / 100 }}
                        />
                      </svg>
                      <div className="ring-text">
                        <div className="big">{data.cognitive_score}%</div>
                        <div className="small">Confidence</div>
                      </div>
                    </div>

                    <div className="cog-explain">
                      <div className={`risk-pill ${data.cognitive_score >= 90 ? "low" : data.cognitive_score >= 70 ? "moderate" : "high"}`}>
                        {data.cognitive_score >= 90 ? "Low Risk" : data.cognitive_score >= 70 ? "Moderate Risk" : "High Risk"}
                      </div>
                      <p className="muted">{data.cognitive_summary || "No cognitive summary available."}</p>
                      <div className="cog-actions">
                        <button className="btn btn-outline" onClick={() => setActiveTab("Analysis")}>Open Analysis</button>
                        <button className="btn btn-ghost" onClick={downloadJSON}>Download JSON</button>
                      </div>
                    </div>
                  </div>
                )}

                {!data?.cognitive_score && <p className="muted">No cognitive data yet.</p>}
              </div>

              {/* Trend chart */}
              {data?.risk_history && (
                <div className="card">
                  <h4 className="card-subheading">Cognitive Score Trend</h4>
                  <div style={{ width: "100%", height: 240 }}>
                    <ResponsiveContainer>
                      <LineChart
                        data={(data.risk_history.trend_data || []).map((d, i) => ({ name: `Run ${i + 1}`, ...d }))}
                        margin={{ top: 6, right: 12, left: 0, bottom: 0 }}
                      >
                        <CartesianGrid strokeDasharray="3 3" />
                        <XAxis dataKey="name" tick={{ fontSize: 12 }} />
                        <YAxis domain={[0, 100]} tick={{ fontSize: 12 }} />
                        <Tooltip content={<CustomTooltip />} />
                        <Line type="monotone" dataKey="cognitive_score" stroke="#2563eb" strokeWidth={2} dot={{ r: 4 }} activeDot={{ r: 6 }} />
                      </LineChart>
                    </ResponsiveContainer>
                  </div>
                </div>
              )}
            </>
          )}

          {/* Sanctions & screening */}
          {isTabVisible("Sanctions") && (
            <div className="card">
              <h3 className="card-heading">Sanction & Origin Screening</h3>

              {data?.sanction_analysis ? (
                <>
                  <div className="muted mb-3">{data.sanction_analysis.summary}</div>
                  <div className={`risk-pill ${data.sanction_analysis.risk_level === "High" ? "high" : data.sanction_analysis.risk_level === "Medium" ? "moderate" : "low"}`}>
                    Risk: {data.sanction_analysis.risk_level}
                  </div>

                  {data.sanction_analysis.details?.length > 0 && (
                    <div className="table-wrap">
                      <table className="table">
                        <thead>
                          <tr>
                            <th>Document</th>
                            <th>Entity</th>
                            <th>Type</th>
                            <th>Reason</th>
                          </tr>
                        </thead>
                        <tbody>
                          {data.sanction_analysis.details.map((s, i) => (
                            <tr key={i}>
                              <td>{s.document}</td>
                              <td><strong>{s.entity}</strong></td>
                              <td>{s.type}</td>
                              <td className="muted">{s.reason}</td>
                            </tr>
                          ))}
                        </tbody>
                      </table>
                    </div>
                  )}
                </>
              ) : (
                <p className="muted">No sanctions data available.</p>
              )}
            </div>
          )}

          {/* Comparison / mismatch (keeps original tables and logic) */}
          {isTabVisible("Comparison") && (
            <>
              {/* Critical mismatches (AI insights) */}
              <div className="card">
                <h3 className="card-heading">Critical Mismatches (AI Insights)</h3>
                {data?.mismatch_report?.length > 0 ? (
                  <div className="table-wrap">
                    <table className="table">
                      <thead>
                        <tr>
                          <th>Field</th>
                          <th>Values</th>
                          <th>Explanation</th>
                          <th>Suggestion</th>
                          <th>Severity</th>
                        </tr>
                      </thead>
                      <tbody>
                        {data.mismatch_report.map((m, i) => (
                          <tr key={i}>
                            <td><strong>{m.field}</strong></td>
                            <td>{(m.values || []).join(" | ") || "-"}</td>
                            <td className="muted">{m.issue_summary || m.issue}</td>
                            <td className="text-accent">{m.suggestion}</td>
                            <td className={`severity ${m.severity?.toLowerCase() || "medium"}`}>{m.severity}</td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  </div>
                ) : (
                  <p className="muted">No mismatches detected.</p>
                )}
              </div>

              {/* Pairwise / master comparison grid */}
              <div className="card">
                <h3 className="card-heading">Comparison Overview (All Documents)</h3>
                {data?.comparison_report ? (
                  <div className="table-wrap">
                    <table className="table">
                      <thead>
                        <tr>
                          <th>Field</th>
                          {(data.files_processed || []).map((f, i) => <th key={i}>{f}</th>)}
                          <th>Status</th>
                        </tr>
                      </thead>
                      <tbody>
                        {data.comparison_report.map((r, i) => (
                          <tr key={i}>
                            <td><strong>{r.field}</strong></td>
                            {r.values.map((v, j) => <td key={j}>{v || "-"}</td>)}
                            <td className={`severity ${r.status.toLowerCase()}`}>{r.status}</td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  </div>
                ) : <p className="muted">No comparison available yet.</p>}
              </div>
            </>
          )}

          {/* Analysis tab (HS, Incoterms, Fraud, Pattern alerts) */}
          {isTabVisible("Analysis") && (
            <>
              {/* HS Analysis */}
              <div className="card">
                <h3 className="card-heading">HS Code Intelligence</h3>
                {data?.hs_analysis ? (
                  <>
                    <div className="muted">{data.hs_analysis.summary}</div>
                    <div className={`risk-pill ${data.hs_analysis.risk_level === "High" ? "high" : data.hs_analysis.risk_level === "Medium" ? "moderate" : "low"}`}>
                      Risk Level: {data.hs_analysis.risk_level}
                    </div>

                    {data.hs_analysis.details?.length > 0 && (
                      <div className="table-wrap">
                        <table className="table">
                          <thead>
                            <tr>
                              <th>Document</th>
                              <th>HS Code</th>
                            </tr>
                          </thead>
                          <tbody>
                            {data.hs_analysis.details.map((h, i) => (
                              <tr key={i}>
                                <td>{h.doc}</td>
                                <td>{h.hs}</td>
                              </tr>
                            ))}
                          </tbody>
                        </table>
                      </div>
                    )}
                  </>
                ) : <p className="muted">No HS analysis available.</p>}
              </div>

              {/* Incoterm intelligence */}
              <div className="card">
                <h3 className="card-heading">Incoterm Intelligence</h3>
                {data?.incoterm_analysis ? (
                  <>
                    <div className="muted">{data.incoterm_analysis.summary}</div>
                    <div className={`risk-pill ${data.incoterm_analysis.risk_level === "High" ? "high" : data.incoterm_analysis.risk_level === "Medium" ? "moderate" : "low"}`}>
                      Risk: {data.incoterm_analysis.risk_level}
                    </div>

                    {data.incoterm_analysis.details?.length > 0 && (
                      <div className="table-wrap">
                        <table className="table">
                          <thead>
                            <tr>
                              <th>Document</th>
                              <th>Detected Term</th>
                            </tr>
                          </thead>
                          <tbody>
                            {data.incoterm_analysis.details.map((t, i) => (
                              <tr key={i}>
                                <td>{t.doc}</td>
                                <td>{t.incoterm || "-"}</td>
                              </tr>
                            ))}
                          </tbody>
                        </table>
                      </div>
                    )}
                  </>
                ) : <p className="muted">No incoterm analysis available.</p>}
              </div>

              {/* Pattern alerts */}
              <div className="card">
                <h3 className="card-heading">Pattern Alerts</h3>
                {data?.pattern_alerts?.length > 0 ? (
                  <div className="table-wrap">
                    <table className="table">
                      <thead>
                        <tr>
                          <th>Type</th>
                          <th>Document</th>
                          <th>Message</th>
                          <th>Severity</th>
                        </tr>
                      </thead>
                      <tbody>
                        {data.pattern_alerts.map((a, i) => (
                          <tr key={i}>
                            <td>{a.type}</td>
                            <td>{a.doc || "-"}</td>
                            <td className="muted">{a.message}</td>
                            <td className={`severity ${a.severity?.toLowerCase()}`}>{a.severity}</td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  </div>
                ) : <p className="muted">No pattern alerts detected.</p>}
              </div>

              {/* Fraud report */}
              <div className="card">
                <h3 className="card-heading">Fraud Detection Report</h3>
                {data?.fraud_report?.length > 0 ? (
                  <div className="table-wrap">
                    <table className="table">
                      <thead>
                        <tr>
                          <th>Rule</th>
                          <th>Document</th>
                          <th>Severity</th>
                          <th>Explanation</th>
                        </tr>
                      </thead>
                      <tbody>
                        {data.fraud_report.map((r, i) => (
                          <tr key={i}>
                            <td>{r.rule}</td>
                            <td>{r.doc || "-"}</td>
                            <td className={`severity ${r.severity?.toLowerCase()}`}>{r.severity}</td>
                            <td className="muted">{r.explanation}</td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  </div>
                ) : <p className="muted">No fraud issues detected.</p>}
              </div>
            </>
          )}
        </section>
      </div>
    </div>
  );
}
