import type { Metadata } from "next";
import "./globals.css";

export const metadata: Metadata = {
  title: "台股題材地圖｜Theme Atlas",
  description: "以多週期漲幅排行辨識核心強勢與新興題材群聚的台股研究雷達。",
  openGraph: {
    title: "台股題材地圖｜Theme Atlas",
    description: "從多週期排行讀出資金正在聚集的方向。",
    images: ["/og.png"],
  },
};

export default function RootLayout({ children }: Readonly<{ children: React.ReactNode }>) {
  return <html lang="zh-Hant"><body>{children}</body></html>;
}
