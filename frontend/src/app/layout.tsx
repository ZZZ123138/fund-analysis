import type { Metadata } from "next";
import "./globals.css";
import GsapBackground from "@/components/GsapBackground";

export const metadata: Metadata = {
  title: "基金分析系统",
  description: "基金净值分析、指标计算与报告生成",
};

export default function RootLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  return (
    <html lang="zh-CN">
      <body>
        <GsapBackground />
        {children}
      </body>
    </html>
  );
}
