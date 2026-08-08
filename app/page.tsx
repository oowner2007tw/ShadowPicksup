"use client";

import { useEffect, useMemo, useState } from "react";

type Stock = { code: string; name: string; tier: "S" | "A" | "B"; windows: string[]; theme: string };
type Theme = { name: string; score: number; tier: number; stocks: Stock[] };

const fallbackThemes: Theme[] = [
  { name: "AI 基礎建設 / 高速傳輸", tier: 1, score: 13, stocks: [
    { code: "6213", name: "聯茂", tier: "S", windows: ["1d","2d","3d","4d","5d","10d"], theme: "AI 基礎建設 / 高速傳輸" },
    { code: "2368", name: "金像電", tier: "S", windows: ["3d","4d","5d","10d","20d"], theme: "AI 基礎建設 / 高速傳輸" },
    { code: "3037", name: "欣興", tier: "A", windows: ["2d","5d","10d","20d"], theme: "AI 基礎建設 / 高速傳輸" },
    { code: "2313", name: "華通", tier: "B", windows: ["5d","20d"], theme: "AI 基礎建設 / 高速傳輸" },
  ]},
  { name: "記憶體 / IC 設計", tier: 2, score: 11, stocks: [
    { code: "6531", name: "愛普*", tier: "S", windows: ["1d","3d","4d","5d","10d"], theme: "記憶體 / IC 設計" },
    { code: "3006", name: "晶豪科", tier: "A", windows: ["2d","3d","5d","10d"], theme: "記憶體 / IC 設計" },
    { code: "2408", name: "南亞科", tier: "A", windows: ["3d","5d","10d"], theme: "記憶體 / IC 設計" },
    { code: "2344", name: "華邦電", tier: "B", windows: ["5d","20d"], theme: "記憶體 / IC 設計" },
  ]},
  { name: "機器人 / 智慧製造", tier: 3, score: 8, stocks: [
    { code: "2049", name: "上銀", tier: "S", windows: ["1d","2d","3d","5d","10d"], theme: "機器人 / 智慧製造" },
    { code: "2464", name: "盟立", tier: "A", windows: ["3d","4d","5d"], theme: "機器人 / 智慧製造" },
    { code: "4540", name: "全球傳動", tier: "B", windows: ["5d","20d"], theme: "機器人 / 智慧製造" },
  ]},
];

const weights = { S: 3, A: 2, B: 1 };
const fugleUrl = (code: string) => `https://www.fugle.tw/ai/${code}`;

export default function Home() {
  const [tier, setTier] = useState<"all" | "S" | "A" | "B">("all");
  const [query, setQuery] = useState("");
  const [themes, setThemes] = useState<Theme[]>(fallbackThemes);
  const [dataDate, setDataDate] = useState("範例資料");
  useEffect(() => { fetch("/report.json").then((response) => response.ok ? response.json() : null).then((report) => {
    if (report?.themes?.length) { setThemes(report.themes); setDataDate(new Date(report.generated_at).toLocaleDateString("zh-TW")); }
  }).catch(() => undefined); }, []);
  const visible = useMemo(() => themes.map((theme) => ({ ...theme, stocks: theme.stocks.filter((stock) =>
    (tier === "all" || stock.tier === tier) && `${stock.code}${stock.name}${theme.name}`.toLowerCase().includes(query.toLowerCase())
  )})).filter((theme) => theme.stocks.length), [tier, query]);
  const stockCount = visible.reduce((n, theme) => n + theme.stocks.length, 0);

  return <main>
    <section className="hero">
      <div className="hero-top"><span className="eyebrow">FUBON MARKET SCANNER</span><span className="live"><i />資料更新 · {dataDate}</span></div>
      <div className="hero-copy"><p className="kicker">TAIWAN EQUITY MOMENTUM</p><h1>把短線雜訊，<br /><em>變成可讀的趨勢。</em></h1><p className="intro">橫跨 1 至 20 日的漲幅排行，以出現頻率與連續性篩出可追蹤的市場主線。</p></div>
      <div className="hero-metrics"><div><strong>7</strong><span>觀測區間</span></div><div><strong>3</strong><span>題材層級</span></div><div><strong>{stockCount}</strong><span>保留標的</span></div></div>
      <div className="orb orb-one" /><div className="orb orb-two" />
    </section>

    <section className="toolbar" aria-label="報告篩選">
      <div className="window-list"><span>觀測：</span>{["1d","2d","3d","4d","5d","10d","20d"].map((w) => <b key={w}>{w}</b>)}</div>
      <div className="controls"><div className="tier-tabs" aria-label="標的 Tier 篩選">{(["all","S","A","B"] as const).map((value) => <button className={tier === value ? "active" : ""} onClick={() => setTier(value)} key={value}>{value === "all" ? "全部" : `Tier ${value}`}</button>)}</div><label className="search"><span>⌕</span><input value={query} onChange={(e) => setQuery(e.target.value)} placeholder="搜尋代號、名稱或題材" /></label></div>
    </section>

    <section className="content">
      <header className="report-title"><div><p className="kicker">CURATED SIGNALS</p><h2>可能性題材與標的 Tier</h2></div><p>僅呈現跨區間出現至少兩次的標的<br />S = 3 分 · A = 2 分 · B = 1 分</p></header>
      <div className="theme-list">{visible.map((theme) => <article className="theme-card" key={theme.name}>
        <div className="theme-header"><div className="rank"><span>THEME TIER</span><strong>{String(theme.tier).padStart(2, "0")}</strong></div><div className="theme-name"><h3>{theme.name}</h3><p>{theme.stocks.length} 個高匹配標的 · 跨天期動能同步</p></div><div className="score"><span>總權重</span><strong>{theme.stocks.reduce((total, stock) => total + weights[stock.tier], 0)}<small> pts</small></strong></div></div>
        <div className="stocks">{theme.stocks.map((stock) => <a className="stock-row" href={fugleUrl(stock.code)} target="_blank" rel="noreferrer" key={stock.code} aria-label={`在 Fugle 查看 ${stock.code} ${stock.name}`}>
          <span className={`stock-tier tier-${stock.tier}`}>TIER {stock.tier}</span><span className="stock-id"><b>{stock.code}</b><strong>{stock.name}</strong></span><span className="windows">{stock.windows.map((w) => <i key={w}>{w}</i>)}</span><span className="go">查看 Fugle ↗</span>
        </a>)}</div>
      </article>)}</div>
      {!visible.length && <p className="empty">沒有符合目前篩選的高匹配標的。</p>}
    </section>
    <footer><span>資料來源：富邦證券台股進階數據</span><span>研究用途 · 非投資建議</span></footer>
  </main>;
}
