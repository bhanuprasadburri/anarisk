import { apiRequest, qs, getToken } from './apiClient';
import { API_BASE_URL } from '../lib/constants';
import { ReportsOverview } from '../types';

export interface ReportParams {
  from?: string;
  to?: string;
  brand_id?: string;
  provenance?: string;
}

export type ReportKind = 'threats' | 'cases' | 'entities' | 'apps' | 'evidence';

export const reportService = {
  async getOverview(params: ReportParams = {}): Promise<ReportsOverview> {
    return apiRequest<ReportsOverview>(`/reports/overview${qs(params)}`);
  },

  /** Authenticated CSV download. */
  async exportCsv(report: ReportKind, params: ReportParams = {}): Promise<void> {
    const res = await fetch(`${API_BASE_URL}/reports/export/csv${qs({ ...params, report })}`, {
      headers: { Authorization: `Bearer ${getToken()}` },
    });
    if (!res.ok) throw new Error(`Export failed (HTTP ${res.status})`);
    const blob = await res.blob();
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = `anarisk-${report}-${new Date().toISOString().slice(0, 10)}.csv`;
    document.body.appendChild(a);
    a.click();
    a.remove();
    URL.revokeObjectURL(url);
  },

  /**
   * Client-side PDF report generation (print-optimized HTML blob download).
   * The data is the real ReportsOverview; we render a clean printable document.
   */
  async exportPdfHtml(overview: ReportsOverview, title = 'AnaRisk Report'): Promise<void> {
    const esc = (s: unknown) =>
      String(s ?? '—').replace(/[&<>"]/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' })[c]!);
    const rows = (pairs: Array<[string, string]>) =>
      pairs.map(([k, v]) => `<tr><td>${esc(k)}</td><td class="v">${esc(v)}</td></tr>`).join('');
    const html = `<!doctype html><html><head><meta charset="utf-8"><title>${esc(title)}</title>
<style>
body{font-family:Inter,Segoe UI,sans-serif;color:#10264F;margin:40px;line-height:1.5}
h1{font-size:22px;margin:0}h2{font-size:15px;margin:28px 0 8px;color:#2648B8}
.sub{color:#64748B;font-size:12px;margin-top:4px}
.banner{background:#EEF4FF;border:1px solid #BCD0FD;border-radius:8px;padding:10px 14px;font-size:12px;margin:16px 0}
table{width:100%;border-collapse:collapse;font-size:12px}
td,th{border-bottom:1px solid #DCE6F5;padding:6px 8px;text-align:left}
td.v{font-weight:600;text-align:right}
.grid{display:grid;grid-template-columns:1fr 1fr;gap:24px}
.footer{margin-top:32px;color:#94A3B8;font-size:11px}
</style></head><body>
<h1>${esc(title)}</h1>
<div class="sub">Generated ${esc(new Date(overview.generated_at).toLocaleString())} · Range ${esc(overview.date_range.from)} → ${esc(overview.date_range.to)}</div>
<div class="banner"><strong>Data honesty notice:</strong> ${overview.data_notes.map(esc).join(' · ')}</div>
<div class="grid">
<div><h2>Totals</h2><table>${rows(Object.entries(overview.totals).map(([k, v]) => [k.replace(/_/g, ' '), String(v)]))}</table></div>
<div><h2>Threat distribution</h2><table>${rows(Object.entries(overview.threat_distribution).map(([k, v]) => [k, String(v)]))}</table>
<h2>Cases by status</h2><table>${rows(Object.entries(overview.cases_by_status).map(([k, v]) => [k.replace(/_/g, ' '), String(v)]))}</table></div>
</div>
<h2>Threats by channel</h2><table>${rows(overview.threats_by_channel.map((c) => [c.channel, String(c.count)]))}</table>
<h2>Top connected entities</h2><table>${rows(overview.top_connected_entities.map((e) => [`${e.display_name} (${e.entity_type})`, `${e.relationship_count} links · risk ${e.risk_score ?? '—'}`]))}</table>
<h2>Risk trend</h2><table>${rows(overview.risk_trend.filter((d) => d.avg_risk !== null).slice(-14).map((d) => [d.date, `avg ${d.avg_risk!.toFixed(2)} · ${d.detections} detections`]))}</table>
<div class="footer">AnaRisk — Digital Threat Intelligence & Investigation Platform. Scores are heuristic and require human review.</div>
</body></html>`;
    const blob = new Blob([html], { type: 'text/html' });
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = `anarisk-report-${new Date().toISOString().slice(0, 10)}.html`;
    document.body.appendChild(a);
    a.click();
    a.remove();
    URL.revokeObjectURL(url);
  },
};
