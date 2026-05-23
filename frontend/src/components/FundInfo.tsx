"use client";

interface Metrics {
  fund_code: string;
  fund_name: string;
  start_date: string;
  end_date: string;
}

interface Props {
  metrics: Metrics;
}

export default function FundInfo({ metrics }: Props) {
  return (
    <table className="info-table">
      <tbody>
        <tr>
          <td>基金代码</td>
          <td>{metrics.fund_code}</td>
        </tr>
        <tr>
          <td>基金名称</td>
          <td>{metrics.fund_name || "未知"}</td>
        </tr>
        <tr>
          <td>数据区间</td>
          <td>
            {metrics.start_date} ~ {metrics.end_date}
          </td>
        </tr>
        <tr>
          <td>无风险利率</td>
          <td>2.50%</td>
        </tr>
      </tbody>
    </table>
  );
}
