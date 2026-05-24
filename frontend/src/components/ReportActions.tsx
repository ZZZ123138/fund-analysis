"use client";

import { useState } from "react";

interface Props {
  fundCode: string;
}

export default function ReportActions({ fundCode }: Props) {
  const [loading, setLoading] = useState(false);

  const viewReport = () => {
    window.open(`/api/fund/${fundCode}/report`, "_blank");
  };

  const savePDF = () => {
    window.print();
  };

  return (
    <div className="report-actions">
      <button className="btn btn-primary" onClick={viewReport} disabled={loading}>
        查看 HTML 报告
      </button>
      <button className="btn btn-secondary no-print" onClick={savePDF}>
        保存为 PDF
      </button>
      <span style={{ fontSize: 12, color: "#94a3b8", alignSelf: "center" }} className="no-print">
        报告包含核心指标、净值走势和基本信息
      </span>
    </div>
  );
}
