(function () {
  "use strict";
  const root = document.getElementById("synthesis-workspace-root");
  const projectSelect = document.getElementById("project");
  if (!root || !projectSelect) return;
  const text = (tag, value, className) => { const node = document.createElement(tag); if (className) node.className = className; node.textContent = value == null || value === "" ? "—" : String(value); return node; };
  const api = (id, suffix, options) => fetch(`/api/project/${encodeURIComponent(id)}/${suffix}`, options).then(response => { if (!response.ok) throw new Error(response.status === 409 ? "内容已更新，请刷新后重新核对。" : "综合判断暂不可用。"); return response.json(); });
  let busy = false;
  function section(title) { const node = document.createElement("section"); node.className = "synthesis-panel"; node.append(text("h4", title)); return node; }
  function render(protocol, synthesis, contracts, figures) {
    root.replaceChildren();
    if (protocol.route !== "evidence-to-release.v1") return;
    const protocolPanel = section("Comparison Protocol");
    const p = protocol.protocol || {};
    protocolPanel.append(text("p", `比较对象：${(p.comparison_objects || []).join("、") || "—"}`));
    protocolPanel.append(text("p", `比较轴：${(p.axes || []).join("、") || "—"}`));
    protocolPanel.append(text("p", `结论强度：${p.claim_strength || "—"}`));
    if (p.decision) protocolPanel.append(text("p", `决定：${p.decision.action} · ${p.decision.reason || ""}`, "decision-line"));
    if (!p.decision) {
      const protocolButton = document.createElement("button"); protocolButton.type = "button"; protocolButton.textContent = "批准比较协议";
      protocolButton.addEventListener("click", () => decide("comparison-protocol", {version_token: p.version_token})); protocolPanel.append(protocolButton);
    }
    const claimPanel = section("Synthesis Claims");
    (synthesis.items || []).forEach(item => {
      const card = document.createElement("article"); card.className = "synthesis-card";
      card.append(text("strong", item.proposition), text("p", `比较轴：${item.comparison_axis}；边界：${item.applicability_boundary}`));
      card.append(text("p", `支持证据：${(item.supporting_evidence_ids || []).join("、") || "—"}；反证：${(item.counter_evidence_ids || []).join("、") || "—"}`));
      card.append(text("p", `不确定性：${item.uncertainty}；风险：${item.risk_class}`, "evidence-meta"));
      const button = document.createElement("button"); button.type = "button"; button.textContent = "记录决定"; button.addEventListener("click", () => decide("synthesis", item)); card.append(button); claimPanel.append(card);
    });
    const contractPanel = section("Section Contracts");
    (contracts.items || []).forEach(item => { const card = document.createElement("article"); card.className = "synthesis-card"; card.append(text("strong", item.section_id), text("p", item.research_question), text("p", `预期综合判断：${item.expected_synthesis}`), text("p", `图计划：${JSON.stringify(item.figure_plan || [])}`)); const button = document.createElement("button"); button.type = "button"; button.textContent = "记录决定"; button.addEventListener("click", () => decide("section-contracts", item)); card.append(button); contractPanel.append(card); });
    const figurePanel = section("原论文图片");
    (figures.source_figures || []).forEach(item => {
      const row = document.createElement("div"); row.className = "figure-source-row";
      row.append(text("span", `${item.study_id} · ${item.figure_label} · 第 ${item.page} 页：${item.caption}`));
      const button = document.createElement("button"); button.type = "button"; button.textContent = item.selection_status === "selected" ? "取消选择" : "选择原图";
      button.addEventListener("click", () => decide("review-figures", {...item, selection_status: item.selection_status === "selected" ? "available" : "selected"})); row.append(button); figurePanel.append(row);
    });
    figurePanel.append(text("h4", "综合图制图任务", "placeholder-heading"));
    (figures.placeholders || []).forEach(item => figurePanel.append(text("p", `${item.placeholder_id}：${item.reader_takeaway}（${item.status}）`, "figure-placeholder-row")));
    root.append(protocolPanel, claimPanel, contractPanel, figurePanel);
  }
  async function decide(kind, item) {
    if (busy) return; busy = true; const reason = window.prompt("请记录这项决定的理由", item.decision?.reason || "研究者核对后决定");
    if (!reason) { busy = false; return; }
    const body = kind === "comparison-protocol"
      ? {action:"approve", reason, version_token:item.version_token}
      : kind === "review-figures"
        ? {figure_id:item.figure_id, selection_status:item.selection_status, version_token:item.version_token}
        : {[kind === "synthesis" ? "synthesis_id" : "section_id"]: item[kind === "synthesis" ? "synthesis_id" : "section_id"], action:"approve", reason, version_token:item.version_token};
    try { await api(projectSelect.value, kind, {method:"PUT", headers:{"Content-Type":"application/json"}, body:JSON.stringify(body)}); await refresh(); } catch (error) { root.prepend(text("p", error.message, "workspace-error")); } finally { busy = false; }
  }
  async function refresh() { const id = projectSelect.value; if (!id || busy) return; try { const values = await Promise.all([api(id,"comparison-protocol"), api(id,"synthesis"), api(id,"section-contracts"), api(id,"review-figures")]); render(...values); } catch (_) {} }
  projectSelect.addEventListener("change", refresh); document.addEventListener("DOMContentLoaded", refresh); window.setInterval(refresh, 5000);
}());
