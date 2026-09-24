import { useEffect, useState } from "react";
import { api } from "../api/client";
type EjectResult = { order_id: number; ticket_code: string; status: string; rail_id: number; rail_label: string; start_cm: number; end_cm: number };
type O = { id: number; ticket_code: string; garment_name: string; due_at: string; status: string; rail_id: number | null; rail_label: string | null; start_cm: number | null; end_cm: number | null };
export default function OverduePage() {
  const [rows, setRows] = useState<O[]>([]);
  const [msg, setMsg] = useState("");
  const [err, setErr] = useState("");
  const [busy, setBusy] = useState<number | null>(null);
  const reload = () => api<O[]>("/overdue").then(setRows);
  useEffect(() => { reload(); }, []);
  async function scan() {
    setErr("");
    const marked = await api<O[]>("/overdue/scan", { method: "POST", body: "{}" });
    setMsg(`扫描完成，新标记 ${marked.length} 单`);
    reload();
  }
  async function eject(o: O) {
    setMsg(""); setErr(""); setBusy(o.id);
    try {
      const r = await api<EjectResult>(`/orders/${o.id}/force-eject`, { method: "POST", body: "{}" });
      // 无需取件码核验：清杆后占位图对应段随 active=0 消失，工单状态为 overdue
      setRows(rs => rs.map(x => x.id === o.id ? { ...x, status: r.status, rail_id: null, rail_label: null, start_cm: null, end_cm: null } : x));
      setMsg(`已强制出杆：${r.ticket_code} · ${r.rail_label} ${r.start_cm}-${r.end_cm}cm（杆号 ${r.rail_id}）`);
    } catch (e) { setErr(e instanceof Error ? e.message : String(e)); }
    finally { setBusy(null); }
  }
  return (<>
    <h2>逾期</h2>
    <div className="toolbar">
      <button onClick={scan}>扫描逾期</button>
      <span className="hint">仅已到期且仍占杆的工单可强制出杆（无需取件码，区别于取件入口）</span>
      {msg && <span className="ok">{msg}</span>}
      {err && <span className="err">{err}</span>}
    </div>
    <table className="table"><thead><tr><th>票号</th><th>衣物</th><th>到期</th><th>状态</th><th>占杆</th><th></th></tr></thead>
    <tbody>{rows.map(o => <tr key={o.id}>
      <td className="mono">{o.ticket_code}</td><td>{o.garment_name}</td>
      <td className="mono">{new Date(o.due_at).toLocaleString()}</td><td>{o.status}</td>
      <td>{o.rail_id ? <span className="mono">{o.rail_label} · {o.start_cm}-{o.end_cm}cm</span> : <span>已清杆</span>}</td>
      <td>{o.rail_id && <button className="btn-danger" disabled={busy === o.id} onClick={() => eject(o)}>{busy === o.id ? "出杆中…" : "强制出杆"}</button>}</td>
    </tr>)}
      {!rows.length && <tr><td colSpan={6}>暂无逾期</td></tr>}
    </tbody></table>
  </>);
}
