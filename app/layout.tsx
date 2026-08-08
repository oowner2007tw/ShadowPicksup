import type { Metadata } from "next";
import "./globals.css";

export const metadata: Metadata = {
  title: "台股動能 Tier 雷達",
  description: "跨週期台股漲幅排行的題材與標的 Tier 分析報告。",
  openGraph: { title: "台股動能 Tier 雷達", description: "跨週期台股漲幅排行的題材與標的 Tier 分析報告。", images: ["/og.png"] },
};

export default function RootLayout({ children }: Readonly<{ children: React.ReactNode }>) {
  return <html lang="zh-Hant"><body>{children}</body></html>;
}
