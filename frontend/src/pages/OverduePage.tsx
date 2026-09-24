import { useEffect, useState } from "react";
import { api } from "../api/client";
type Released = { rail_id: number; rail_label: string; start_cm: number; end_cm: number };
type ForceOut = { order: { id: number; ticket_code: string; status: string }; released: Released[] };
type O = { id: number; ticket_code: string; garment_name: string; due_at: string; status: string; occupying: boolean };
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
  async function forceRemove(o: O) {
    setMsg(""); setErr("");
    setBusy(o.id);
    try {
      const r = await api<ForceOut>("/overdue/force-remove", {
        method: "POST",
        body: JSON.stringify({ order_id: o.id }),
      });
      const detail = r.released
        .map(s => `${s.rail_label}（#${s.rail_id}）${s.start_cm}-${s.end_cm}cm`)
        .join("；");
      setMsg(`已强制出杆 ${o.ticket_code}，释放：${detail}，工单状态 ${r.order.status}`);
      await reload();
    } catch (e) {
      setErr(e instanceof Error ? e.message : String(e));
    } finally {
      setBusy(null);
    }
  }
  return (<>
    <h2>逾期</h2>
    <div className="toolbar"><button onClick={scan}>扫描逾期</button>{msg && <span className="ok">{msg}</span>}{err && <span className="err">{err}</span>}</div>
    <table className="table"><thead><tr><th>票号</th><th>衣物</th><th>到期</th><th>状态</th><th>占杆</th><th></th></tr></thead>
    <tbody>{rows.map(o => <tr key={o.id}><td className="mono">{o.ticket_code}</td><td>{o.garment_name}</td><td className="mono">{new Date(o.due_at).toLocaleString()}</td><td>{o.status}</td><td>{o.occupying ? "是" : "否"}</td>
      <td>{o.occupying && <button className="danger" disabled={busy === o.id} onClick={() => forceRemove(o)}>强制出杆</button>}</td></tr>)}
      {!rows.length && <tr><td colSpan={6}>暂无逾期</td></tr>}
    </tbody></table>
  </>);
}
