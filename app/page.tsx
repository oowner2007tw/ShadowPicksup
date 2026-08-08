"use client";

import { useMemo, useState } from "react";
import { report } from "./report-data";

type Stock = (typeof report.themes)[number]["stocks"][number];
type Tier = Stock["tier"];
const weights: Record<Tier, number> = { S: 4, A: 3, B: 2, C: 1 };
const fugleUrl = (code: string) => `https://www.fugle.tw/ai/${code}`;

export default function Home() {
  const [tier, setTier] = useState<"all" | Tier>("all");
  const [query, setQuery] = useState("");
  const visible = useMemo(() => report.themes.map((theme) => ({ ...theme, stocks: theme.stocks.filter((stock) =>
    (tier === "all" || stock.tier === tier) && `${stock.code}${stock.name}${theme.name}`.toLowerCase().includes(query.toLowerCase())
  )})).filter((theme) => theme.stocks.length), [tier, query]);
  const stockCount = visible.reduce((count, theme) => count + theme.stocks.length, 0);
  const dataDate = new Date(report.generated_at).toLocaleDateString("zh-TW");
  const dataLabel = report.freshness === "fresh" ? "資料已更新" : "沿用最近成功資料";

  return <main>
    <section className="hero"><div className="hero-top"><span className="eyebrow">FUBON MARKET SCANNER</span><span className="live"><i />{dataLabel} · {dataDate}</span></div><div className="hero-copy"><p className="kicker">TAIWAN EQUITY MOMENTUM</p><h1>把短線雜訊，<br /><em>變成可讀的趨勢。</em></h1><p className="intro">橫跨 1 至 20 日的漲幅排行，以出現頻率、平均排名與近期題材群聚篩出可追蹤的市場主線。</p></div><div className="hero-metrics"><div><strong>7</strong><span>觀測區間</span></div><div><strong>{report.themes.length}</strong><span>題材層級</span></div><div><strong>{stockCount}</strong><span>保留標的</span></div></div><div className="orb orb-one" /><div className="orb orb-two" /></section>
    <section className="toolbar" aria-label="報告篩選"><div className="window-list"><span>觀測：</span>{["1d","2d","3d","4d","5d","10d","20d"].map((window) => <b key={window}>{window}</b>)}</div><div className="controls"><div className="tier-tabs" aria-label="標的 Tier 篩選">{(["all","S","A","B","C"] as const).map((value) => <button className={tier === value ? "active" : ""} onClick={() => setTier(value)} key={value}>{value === "all" ? "全部" : `Tier ${value}`}</button>)}</div><label className="search"><span>⌕</span><input value={query} onChange={(event) => setQuery(event.target.value)} placeholder="搜尋代號、名稱或題材" /></label></div></section>
    <section className="content"><header className="report-title"><div><p className="kicker">CURATED SIGNALS</p><h2>可能性題材與標的 Tier</h2></div><p>多次高排名優先；近期群聚訊號列為 Tier C 觀察<br />S = 4 分 · A = 3 分 · B = 2 分 · C = 1 分</p></header>{report.freshness === "stale" && <p className="empty">本次抓取失敗，以下呈現最後一次成功資料。</p>}<div className="theme-list">{visible.map((theme) => <article className="theme-card" key={theme.name}><div className="theme-header"><div className="rank"><span>THEME TIER</span><strong>{String(theme.tier).padStart(2, "0")}</strong></div><div className="theme-name"><h3>{theme.name}</h3><p>{theme.stocks.length} 個保留標的 · 跨天期動能與群聚訊號</p></div><div className="score"><span>總權重</span><strong>{theme.score}<small> pts</small></strong></div></div><div className="stocks">{theme.stocks.map((stock) => <a className="stock-row" href={fugleUrl(stock.code)} target="_blank" rel="noreferrer" key={stock.code} aria-label={`在 Fugle 查看 ${stock.code} ${stock.name}`}><span className={`stock-tier tier-${stock.tier}`}>TIER {stock.tier}</span><span className="stock-id"><b>{stock.code}</b><strong>{stock.name}</strong></span><span className="windows">{stock.windows.map((window) => <i key={window}>{window}</i>)}</span><span className="go">{stock.appearances} 次 · 均排 {stock.avg_rank} · 均漲 {stock.avg_gain_pct ?? "—"}% · Fugle ↗</span></a>)}</div></article>)}</div>{!visible.length && <p className="empty">沒有符合目前篩選的標的。</p>}</section>
    <footer><span>資料來源：富邦證券台股進階數據</span><span>研究用途 · 非投資建議</span></footer>
  </main>;
}
