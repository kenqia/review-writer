(function () {
  "use strict";
  const root = document.getElementById("evidence-workspace-root");
  const shell = document.getElementById("evidence-synthesis-workspace");
  const status = document.getElementById("evidence-workspace-status");
  const message = document.getElementById("evidence-workspace-message");
  const projectSelect = document.getElementById("project");
  if (!root || !shell || !projectSelect) return;

  const text = (tag, value, className) => {
    const node = document.createElement(tag);
    if (className) node.className = className;
    node.textContent = value == null || value === "" ? "—" : String(value);
    return node;
  };
  const list = value => Array.isArray(value) && value.length ? value.join("、") : "—";
  const api = (id, suffix, options) => fetch(`/api/project/${encodeURIComponent(id)}/${suffix}`, options).then(response => {
    if (!response.ok) throw new Error(response.status === 409 ? "内容已更新，请刷新后重新核对。" : "工作台暂不可用。");
    return response.json();
  });
  let busy = false;

  function render(payload) {
    root.replaceChildren();
    shell.hidden = payload.route !== "evidence-to-release.v1";
    const legacyRisk = document.getElementById("risk-stage-panel");
    if (legacyRisk && payload.route === "evidence-to-release.v1") legacyRisk.hidden = true;
    if (shell.hidden) return;
    status.textContent = payload.status === "approved" ? "已闭合" : "需要核对";
    message.textContent = payload.reason || "证据决定不会自动授权综合判断。";
    const items = payload.items || [];
    if (!items.length) { root.append(text("p", "尚未导入候选证据。", "workspace-empty")); return; }
    const listNode = document.createElement("div"); listNode.className = "evidence-card-list";
    items.forEach(item => {
      const card = document.createElement("article"); card.className = "evidence-card";
      const heading = document.createElement("header");
      heading.append(text("strong", item.statement), text("span", item.status, "workspace-status")); card.append(heading);
      card.append(text("p", `${item.study_id || "研究"} · ${item.epistemic_type || "证据"} · 第 ${item.locator?.page || "?"} 页`, "evidence-meta"));
      card.append(text("p", `条件：${list(item.reported_conditions)}；定量结果：${list(item.quantitative_results)}`));
      card.append(text("p", `机制等级：${item.mechanism_grade || "—"}；风险：${list(item.risk_classes)}`));
      if (item.locator?.exact_quote) card.append(text("blockquote", item.locator.exact_quote));
      const references = document.createElement("p"); references.className = "evidence-links";
      [[item.pdf_page_url, "打开原论文页"], [item.parsed_text_url, "打开解析正文"]].forEach(([href, label]) => { if (!href) return; const link = document.createElement("a"); link.href = href; link.target = "_blank"; link.rel = "noopener"; link.textContent = label; references.append(link); });
      card.append(references);
      const actions = document.createElement("div"); actions.className = "workspace-actions";
      ["approve", "revise_and_approve", "reject"].forEach(action => {
        const button = document.createElement("button"); button.type = "button"; button.textContent = {approve:"批准", revise_and_approve:"修改后批准", reject:"拒绝"}[action];
        button.addEventListener("click", () => decide(item, action)); actions.append(button);
      }); card.append(actions); listNode.append(card);
    }); root.append(listNode);
  }

  async function decide(item, action) {
    if (busy) return; busy = true;
    const reason = window.prompt("请记录这项决定的理由", item.decision?.reason || "研究者核对后决定");
    if (!reason) { busy = false; return; }
    try { render(await api(projectSelect.value, "paper-evidence", {method:"PUT", headers:{"Content-Type":"application/json"}, body:JSON.stringify({evidence_id:item.evidence_id, action, reason, version_token:item.version_token})})); }
    catch (error) { message.textContent = error.message; }
    finally { busy = false; }
  }

  async function refresh() {
    const id = projectSelect.value; if (!id || busy) return;
    try { render(await api(id, "paper-evidence")); } catch (error) { shell.hidden = true; }
  }
  projectSelect.addEventListener("change", refresh);
  document.addEventListener("DOMContentLoaded", refresh);
  window.setInterval(refresh, 5000);
}());
