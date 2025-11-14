import React from "react";

export default function HeatmapChart({ data }) {
  if (!data || data.length === 0) return null;

  const maxRisk = Math.max(...data.map((d) => d.avg_risk || 0));
  const getColor = (risk) => {
    if (risk > 80) return "#ef4444";   // red
    if (risk > 60) return "#f59e0b";   // yellow
    return "#10b981";                  // green
  };

  return (
    <div className="overflow-x-auto">
      <table className="min-w-full text-sm border rounded-lg">
        <thead className="bg-gray-100 text-gray-600">
          <tr>
            <th className="p-2">Exporter</th>
            <th className="p-2">Port</th>
            <th className="p-2">Avg Risk (%)</th>
            <th className="p-2">Last Seen</th>
          </tr>
        </thead>
        <tbody>
          {data.map((r, i) => (
            <tr key={i} className="border-t hover:bg-gray-50">
              <td className="p-2">{r.exporter}</td>
              <td className="p-2">{r.port}</td>
              <td className="p-2 font-semibold" style={{ color: getColor(r.avg_risk) }}>
                {r.avg_risk.toFixed(1)}
              </td>
              <td className="p-2 text-gray-600 text-xs">
                {new Date(r.last_seen).toLocaleDateString()}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
