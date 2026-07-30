(function (root, factory) {
  const api = factory();
  if (typeof module === "object" && module.exports) module.exports = api;
  root.ReviewDualParseUI = api;
}(typeof globalThis !== "undefined" ? globalThis : this, function () {
  "use strict";

  const studyTargetByModel = new WeakMap();
  const preflightTargetByModel = new WeakMap();
  const completionTargetByModel = new WeakMap();
  const reconciliationTargetByModel = new WeakMap();

  function object(value) {
    return value && typeof value === "object" && !Array.isArray(value) ? value : {};
  }

  function array(value) {
    return Array.isArray(value) ? value : [];
  }

  function text(value, fallback) {
    return typeof value === "string" && value.trim() ? value.trim() : fallback;
  }

  function publicText(value, fallback) {
    const candidate = text(value, "");
    if (!candidate) return fallback;
    if (/(?:^|\s)(?:\/(?:home|mnt|users|tmp)\/|[a-z]:\\)/i.test(candidate)) return fallback;
    if (/\b[a-f0-9]{64}\b/i.test(candidate)) return fallback;
    if (/(?:token|session|cookie)\s*[:=]/i.test(candidate)) return fallback;
    if (/^[\[{]/.test(candidate) || /\bV(?:2000|3000)\b|M\s+END/.test(candidate)) return fallback;
    return candidate;
  }

  function stateLabel(kind, status) {
    const labels = {
      pdf: {
        verified: "PDF 已核验",
        missing: "PDF 待补齐",
        stale: "PDF 核验已失效",
        failed: "PDF 核验失败",
        unknown: "PDF 状态未知",
      },
      generic: {
        current: "Generic Parse 当前有效",
        pending: "Generic Parse 正在处理",
        missing: "Generic Parse 待启动",
        stale: "Generic Parse 已过期",
        failed: "Generic Parse 失败",
        unknown: "Generic Parse 状态未知",
      },
      chemical: {
        current: "Chemical import 当前有效",
        imported: "Chemical import 当前有效",
        needs_import: "Chemical Paper 待确认导入",
        preflight_ready: "Chemical import 预检待确认",
        stale: "Chemical import 已过期",
        failed: "Chemical import 失败",
        unknown: "Chemical import 状态未知",
      },
      completion: {
        current: "Chemical Completion 已完成",
        complete: "Chemical Completion 已完成",
        needs_review: "Chemical Completion 待补全",
        blocked: "Chemical Completion 尚未开放",
        stale: "Chemical Completion 已过期",
        unknown: "Chemical Completion 状态未知",
      },
      reconciliation: {
        current: "Reconciliation 已闭合",
        complete: "Reconciliation 已闭合",
        needs_review: "Reconciliation 待核对",
        blocked: "Reconciliation 尚未开放",
        stale: "Reconciliation 已过期",
        unknown: "Reconciliation 状态未知",
      },
      evidence: {
        available: "Paper Evidence 可用",
        current: "Paper Evidence 可用",
        unavailable: "Paper Evidence 尚不可用",
        blocked: "Paper Evidence 尚不可用",
        stale: "Paper Evidence 已过期",
        unknown: "Paper Evidence 状态未知",
      },
    };
    return labels[kind]?.[status] || labels[kind]?.unknown || "状态未知";
  }

  function nonNegativeInteger(value) {
    return Number.isInteger(value) && value >= 0 ? value : null;
  }

  function positiveInteger(value) {
    return Number.isInteger(value) && value > 0 ? value : null;
  }

  function safePdfUrl(value) {
    const candidate = text(value, "");
    if (!candidate.startsWith("/api/project/") || candidate.startsWith("//")) return "";
    if (/(?:token|session|cookie)=/i.test(candidate)) return "";
    return candidate;
  }

  function locatorModel(row) {
    const page = positiveInteger(row.page);
    const bbox = array(row.bbox_normalized);
    return {
      locatorLabel: page
        ? `第 ${page} 页 · ${bbox.length === 4 && bbox.every(Number.isFinite) ? "页面区域已定位" : "页面区域未提供"}`
        : "PDF 定位未提供",
      pdfPageUrl: safePdfUrl(row.pdf_page_url),
      page,
    };
  }

  function studyModel(value, index) {
    const row = object(value);
    const pdfStatus = text(row.pdf_status, "unknown");
    const rawGenericStatus = text(row.generic_parse_status, "unknown");
    const genericStatus = ["current", "pending", "missing", "stale", "failed"].includes(rawGenericStatus)
      ? rawGenericStatus : "unknown";
    const rawChemicalStatus = text(object(row.chemical).status, text(row.chemical_import_status, "unknown"));
    const chemicalStatus = rawChemicalStatus === "missing" ? "needs_import" : rawChemicalStatus;
    const missingChemicalFields = [
      row.missing_name_count,
      row.missing_smiles_expanded_count,
      row.missing_smiles_unexpanded_count,
    ].some(value => Number.isInteger(value) && value > 0);
    const completionStatus = text(
      object(row.completion).status,
      missingChemicalFields ? "needs_review" : text(row.completion_status, "unknown"),
    );
    const unresolvedReconciliation = Number.isInteger(row.unresolved_reconciliation_count)
      && row.unresolved_reconciliation_count > 0;
    const reconciliationStatus = text(
      object(row.reconciliation).status,
      unresolvedReconciliation ? "needs_review" : text(row.reconciliation_status, "unknown"),
    );
    const evidenceStatus = text(row.paper_evidence_status, "unknown");
    const model = {
      displayLabel: `研究 ${index + 1}`,
      citation: publicText(row.citation, `Core study ${index + 1}`),
      tierLabel: (row.tier || row.source_tier) === "background" ? "Background" : (row.tier || row.source_tier) === "core" ? "Core" : "分层未知",
      pdfLabel: stateLabel("pdf", pdfStatus),
      genericStatus,
      genericLabel: stateLabel("generic", genericStatus),
      chemicalLabel: stateLabel("chemical", chemicalStatus),
      completionLabel: stateLabel("completion", completionStatus),
      reconciliationLabel: stateLabel("reconciliation", reconciliationStatus),
      evidenceLabel: stateLabel("evidence", evidenceStatus),
      actorLabel: publicText(row.actor_label, "决定者未提供"),
      updatedLabel: publicText(row.updated_at, "更新时间未提供"),
    };
    const studyId = text(row.study_id, "");
    if (studyId) studyTargetByModel.set(model, {studyId});
    return model;
  }

  function importPreflightModel(value) {
    const row = object(value);
    if (!Object.keys(row).length) return null;
    const pageCount = positiveInteger(row.page_count);
    const moleculeCount = nonNegativeInteger(row.molecule_count);
    const status = text(row.status, "unknown");
    const fileKindLabels = {
      layout: "版面数据",
      markdown: "Markdown",
      molecule_info: "分子信息",
    };
    const model = {
      status,
      statusLabel: ({
        ready_for_confirmation: "预检完成，等待确认导入",
        checking: "正在检查 Chemical Paper ZIP",
        failed: "Chemical Paper ZIP 预检失败",
        stale: "预检结果已过期",
      })[status] || "尚无 Chemical Paper ZIP 预检",
      confirmAvailable: status === "ready_for_confirmation",
      pageLabel: pageCount === null ? "页数未提供" : `${pageCount} 页`,
      moleculeLabel: moleculeCount === null ? "分子条目数未提供" : `${moleculeCount} 个分子条目`,
      engineLabel: [publicText(row.backend, ""), publicText(row.version, "")].filter(Boolean).join(" · ") || "解析引擎与版本未提供",
      fileKindsLabel: array(row.file_kinds).map(kind => fileKindLabels[kind]).filter(Boolean).join("、") || "文件种类未提供",
      gaps: array(row.gaps).map(value => publicText(value, "")).filter(Boolean),
      actorLabel: publicText(row.actor_label, "决定者未提供"),
      updatedLabel: publicText(row.updated_at, "更新时间未提供"),
    };
    const studyId = text(row.study_id, "");
    const preflightToken = text(row.preflight_token, "");
    if (studyId && preflightToken) preflightTargetByModel.set(model, {studyId, preflightToken});
    if (!preflightTargetByModel.has(model)) model.confirmAvailable = false;
    return model;
  }

  function completionModel(value) {
    const row = object(value);
    const fieldLabels = {
      mol_idt: "名称或论文局部标签",
      smiles_expanded: "展开 SMILES",
      smiles_unexpanded: "未展开 SMILES",
    };
    const field = fieldLabels[row.field] ? row.field : "unknown";
    const model = {
      field,
      fieldLabel: fieldLabels[field] || "未知化学字段",
      ...locatorModel(row),
      actorLabel: publicText(row.actor_label, "决定者未提供"),
      updatedLabel: publicText(row.updated_at, "更新时间未提供"),
    };
    const studyId = text(row.study_id, "");
    const moleculeIndex = nonNegativeInteger(row.molecule_index);
    const versionToken = text(row.version_token, "");
    if (studyId && moleculeIndex !== null && versionToken && field !== "unknown") {
      completionTargetByModel.set(model, {studyId, moleculeIndex, versionToken});
    }
    return model;
  }

  function reconciliationModel(value) {
    const row = object(value);
    const decision = object(row.decision);
    const selectedLane = ["generic", "chemical"].includes(decision.selected_lane)
      ? decision.selected_lane : null;
    const status = text(row.status, "unknown");
    const model = {
      kindLabel: ({
        text: "正文",
        table: "表格",
        figure: "图",
        formula: "公式",
        molecule: "分子",
      })[row.kind] || "解析对象",
      status,
      statusLabel: ({
        corroborated: "两层候选相互印证",
        complementary: "两层候选互补",
        conflict: "两层候选冲突",
        single_lane_only: "仅单层可定位",
        needs_review: "等待 PDF 核对",
        stale: "核对决定已过期",
        blocked: "当前对象已阻塞",
        pdf_resolved: "已由 PDF 仲裁",
      })[status] || "核对状态未知",
      genericCandidate: publicText(row.generic_candidate, "Generic 候选未提供"),
      chemicalCandidate: publicText(row.chemical_candidate, "Chemical 候选未提供"),
      selectedLane,
      allowedActions: ["pdf_resolved", "pdf_locator_only", "reject_both"],
      ...locatorModel(row),
      actorLabel: publicText(decision.actor_label, publicText(row.actor_label, "决定者未提供")),
      updatedLabel: publicText(decision.recorded_at, publicText(row.updated_at, "更新时间未提供")),
    };
    const studyId = text(row.study_id, "");
    const objectId = text(row.object_id, "");
    const registryDigest = text(row.registry_digest, "");
    if (studyId && objectId && registryDigest) {
      reconciliationTargetByModel.set(model, {studyId, objectId, registryDigest});
    }
    return model;
  }

  function emptyModel() {
    return {
      contractValid: false,
      status: "unknown",
      statusLabel: "双层解析安全投影尚不可用",
      failureMessage: "",
      retryable: false,
      nextAction: {
        label: "等待双层解析状态",
        description: "Evidence 保持锁定。",
      },
      studies: [],
      importPreflight: null,
      completionQueue: [],
      reconciliationItems: [],
      summary: {
        coreStudies: null,
        genericCurrent: null,
      },
    };
  }

  function projectionModel(input) {
    const value = object(input);
    if (value.schema_version !== "dual-parse-projection.v1") return emptyModel();
    const nextAction = object(value.next_action);
    const summary = object(value.summary);
    const status = ["loading", "ready", "failed", "stale", "unavailable"].includes(value.status)
      ? value.status : "unknown";
    return {
      ...emptyModel(),
      contractValid: true,
      status,
      statusLabel: ({
        loading: "正在读取双层解析任务",
        ready: "双层解析状态已读取",
        failed: "双层解析任务失败",
        stale: "双层解析状态需要刷新",
        unavailable: "双层解析尚未就绪",
      })[status] || "双层解析状态未知",
      failureMessage: publicText(value.failure_message, ""),
      retryable: value.retryable === true,
      nextAction: {
        label: publicText(nextAction.label, "等待当前阻塞项明确"),
        description: publicText(nextAction.description, "Evidence 保持锁定。"),
      },
      studies: array(value.studies).map(studyModel),
      importPreflight: importPreflightModel(value.import_preflight),
      completionQueue: array(value.completion_queue).map(completionModel),
      reconciliationItems: array(value.reconciliation_items).map(reconciliationModel),
      summary: {
        coreStudies: nonNegativeInteger(summary.core_studies),
        genericCurrent: nonNegativeInteger(summary.generic_current),
      },
    };
  }

  function availabilityModel(input) {
    const value = object(input);
    const includedStudies = nonNegativeInteger(value.includedStudies);
    const sourceRows = array(object(value.sources).sources)
      .filter(row => text(object(row).role, "").toUpperCase() === "MAIN");
    const sourceStatusByStudy = new Map();
    let sourceRowsValid = sourceRows.length > 0;
    sourceRows.forEach(value => {
      const row = object(value);
      const studyId = text(row.study_id, "");
      const status = text(row.status, "");
      if (!studyId || !["已获得", "需要上传"].includes(status)) {
        sourceRowsValid = false;
        return;
      }
      if (!sourceStatusByStudy.has(studyId)) sourceStatusByStudy.set(studyId, new Set());
      sourceStatusByStudy.get(studyId).add(status);
    });
    const sourceTotal = includedStudies !== null
      ? includedStudies : sourceStatusByStudy.size || null;
    const sourceCoverageKnown = sourceRowsValid
      && (includedStudies === null || sourceStatusByStudy.size <= includedStudies);
    const dualParse = object(value.dualParse).contractValid === true
      ? value.dualParse : projectionModel(value.dualParse);
    const coreStudies = nonNegativeInteger(object(dualParse.summary).coreStudies);
    const genericCurrent = nonNegativeInteger(object(dualParse.summary).genericCurrent);
    const projectedCoreRows = array(dualParse.studies)
      .filter(row => object(row).tierLabel === "Core");
    const projectedCoreStudies = projectedCoreRows.length;
    const projectedGenericCurrent = projectedCoreRows
      .filter(row => object(row).genericStatus === "current").length;
    const genericRowsKnown = projectedCoreRows.every(row =>
      object(row).genericStatus !== "unknown"
    );
    const coreWithinIncluded = includedStudies !== null
      && coreStudies !== null && coreStudies <= includedStudies;
    const genericKnown = dualParse.status === "ready"
      && coreStudies !== null && genericCurrent !== null
      && genericCurrent <= coreStudies
      && coreStudies === projectedCoreStudies
      && genericCurrent === projectedGenericCurrent
      && genericRowsKnown
      && coreWithinIncluded
      && (coreStudies > 0 || includedStudies === 0);
    const reviewedEvidence = nonNegativeInteger(value.reviewedEvidenceStudies);
    const reviewedEvidenceKnown = reviewedEvidence !== null
      && includedStudies !== null && reviewedEvidence <= includedStudies;
    return {
      mainFullText: {
        available: sourceCoverageKnown
          ? Array.from(sourceStatusByStudy.values()).filter(statuses => statuses.has("已获得")).length
          : null,
        total: sourceTotal,
      },
      genericSource: {
        available: genericKnown ? genericCurrent : null,
        total: genericKnown ? coreStudies : includedStudies,
      },
      reviewedEvidence: {
        available: reviewedEvidenceKnown ? reviewedEvidence : null,
        total: includedStudies,
      },
    };
  }

  function required(value, label) {
    const normalized = text(value, "");
    if (!normalized) throw new Error(`${label} required`);
    return normalized;
  }

  function actorPayload(input) {
    const actor = object(input);
    const actorType = required(actor.actorType, "actor type");
    if (!["human_researcher", "simulated_researcher_agent"].includes(actorType)) {
      throw new Error("researcher actor required");
    }
    return {
      actor_type: actorType,
      actor_label: required(actor.actorLabel, "actor label"),
    };
  }

  function importPreflightRequest(studyId, file) {
    if (!file || typeof file !== "object") throw new Error("ZIP file required");
    return {
      study_id: required(studyId, "study id"),
      file,
    };
  }

  function importConfirmRequest(studyId, preflightToken, actor) {
    return {
      study_id: required(studyId, "study id"),
      preflight_token: required(preflightToken, "preflight token"),
      ...actorPayload(actor || {actorType: "human_researcher", actorLabel: "研究者"}),
    };
  }

  function pdfLocatorPayload(input) {
    const locator = object(input);
    if (!Number.isInteger(locator.page) || locator.page < 1) throw new Error("PDF page required");
    const result = {page: locator.page};
    const figureLabel = text(locator.figureLabel, "");
    if (figureLabel) result.figure_label = figureLabel;
    return result;
  }

  function completionBatchRequest(studyId, versionToken, rows, actor) {
    const allowedFields = new Set(["mol_idt", "smiles_expanded", "smiles_unexpanded"]);
    const corrections = array(rows).map(rowValue => {
      const row = object(rowValue);
      if (!Number.isInteger(row.moleculeIndex) || row.moleculeIndex < 0) throw new Error("molecule index required");
      const field = required(row.field, "field");
      if (!allowedFields.has(field)) throw new Error("unsupported field");
      return {
        molecule_index: row.moleculeIndex,
        field,
        value: required(row.value, "value"),
        reason: required(row.reason, "reason"),
        pdf_locator: pdfLocatorPayload(row.pdfLocator),
      };
    });
    if (!corrections.length) throw new Error("corrections required");
    return {
      study_id: required(studyId, "study id"),
      version_token: required(versionToken, "version token"),
      ...actorPayload(actor),
      corrections,
    };
  }

  function reconciliationRequest(studyId, objectId, registryDigest, decision, actor) {
    const value = object(decision);
    const action = required(value.action, "action");
    if (!["pdf_resolved", "pdf_locator_only", "reject_both"].includes(action)) {
      throw new Error("unsupported reconciliation action");
    }
    const result = {
      study_id: required(studyId, "study id"),
      object_id: required(objectId, "object id"),
      registry_digest: required(registryDigest, "registry version"),
      action,
    };
    const selectedLane = text(value.selectedLane, "");
    if (selectedLane && !["generic", "chemical"].includes(selectedLane)) throw new Error("unsupported lane");
    if (action === "pdf_resolved" && !selectedLane) throw new Error("selected lane required");
    if (action !== "pdf_resolved" && selectedLane) throw new Error("selected lane not applicable");
    if (selectedLane) result.selected_lane = selectedLane;
    result.note = required(value.note, "note");
    result.pdf_locator = pdfLocatorPayload(value.pdfLocator);
    Object.assign(result, actorPayload(actor));
    return result;
  }

  function appendText(document, parent, tag, value, className) {
    const node = document.createElement(tag);
    if (className) node.className = className;
    node.textContent = value;
    parent.append(node);
    return node;
  }

  function labelledControl(document, labelText, control) {
    const label = document.createElement("label");
    label.append(document.createTextNode(labelText), control);
    return label;
  }

  function safeActor(handlers) {
    const actor = object(handlers?.actor);
    return {
      actorType: text(actor.actorType, "human_researcher"),
      actorLabel: text(actor.actorLabel, "研究者"),
    };
  }

  function openConfirmationDialog(document, returnFocus, title, description, confirmLabel, onConfirm) {
    const dialog = document.createElement("dialog");
    dialog.className = "dual-parse-dialog";
    dialog.setAttribute("aria-modal", "true");
    appendText(document, dialog, "h4", title);
    appendText(document, dialog, "p", description);
    const actions = document.createElement("div");
    actions.className = "dual-parse-dialog-actions";
    const cancel = document.createElement("button");
    cancel.type = "button";
    cancel.textContent = "返回核对";
    const confirm = document.createElement("button");
    confirm.type = "button";
    confirm.className = "dual-parse-primary";
    confirm.textContent = confirmLabel;
    actions.append(cancel, confirm);
    dialog.append(actions);
    document.body.append(dialog);

    function closeDialog() {
      if (typeof dialog.close === "function") dialog.close();
      else {
        dialog.removeAttribute("open");
        dialog.remove();
        returnFocus.focus();
      }
    }

    dialog.addEventListener("keydown", event => {
      if (event.key === "Escape") {
        event.preventDefault();
        closeDialog();
        return;
      }
      if (event.key === "Tab") {
        const focusable = Array.from(dialog.querySelectorAll("button, [href], input, select, textarea, [tabindex]:not([tabindex='-1'])"))
          .filter(node => !node.disabled && !node.hidden);
        if (!focusable.length) return;
        const first = focusable[0];
        const last = focusable[focusable.length - 1];
        if (event.shiftKey && document.activeElement === first) {
          event.preventDefault();
          last.focus();
        } else if (!event.shiftKey && document.activeElement === last) {
          event.preventDefault();
          first.focus();
        }
      }
    });
    dialog.addEventListener("close", () => {
      dialog.remove();
      returnFocus.focus();
    });
    cancel.addEventListener("click", closeDialog);
    confirm.addEventListener("click", () => {
      onConfirm?.();
      closeDialog();
    });
    if (typeof dialog.showModal === "function") dialog.showModal();
    else dialog.setAttribute("open", "");
    cancel.focus();
  }

  function renderStatus(document, parent, model, handlers) {
    parent.replaceChildren();
    const status = document.createElement("section");
    status.className = `dual-parse-live-state ${model.status}`;
    status.setAttribute("role", "status");
    status.setAttribute("aria-live", "polite");
    appendText(document, status, "strong", model.statusLabel);
    if (model.failureMessage) appendText(document, status, "p", model.failureMessage, "dual-parse-failure");
    if (model.retryable) {
      const retry = document.createElement("button");
      retry.type = "button";
      retry.textContent = "重试当前任务";
      retry.addEventListener("click", () => handlers?.onRetry?.());
      status.append(retry);
    }
    const nextAction = document.createElement("section");
    nextAction.className = "dual-parse-next-action";
    nextAction.setAttribute("aria-label", "唯一下一步");
    appendText(document, nextAction, "span", "唯一下一步");
    appendText(document, nextAction, "strong", model.nextAction.label);
    appendText(document, nextAction, "p", model.nextAction.description);
    parent.append(status, nextAction);
  }

  function appendImportControl(document, card, study, handlers) {
    const target = studyTargetByModel.get(study);
    if (!target || !study.chemicalLabel.includes("待确认")) return;
    const form = document.createElement("form");
    form.className = "dual-parse-import-form";
    const file = document.createElement("input");
    file.type = "file";
    file.accept = ".zip,application/zip";
    const submit = document.createElement("button");
    submit.type = "submit";
    submit.textContent = "预检 Chemical Paper ZIP";
    form.append(labelledControl(document, "选择完整导出 ZIP", file), submit);
    form.addEventListener("submit", async event => {
      event.preventDefault();
      try {
        const result = await handlers?.onImportPreflight?.(
          importPreflightRequest(target.studyId, file.files?.[0]),
          form,
        );
        if (result) handlers?.onPreflightResult?.(result);
      } catch (_) {
        handlers?.onValidationError?.("请选择需要预检的完整 Chemical Paper ZIP。");
      }
    });
    card.append(form);
  }

  function renderStudies(document, parent, model, handlers) {
    const list = document.createElement("div");
    list.className = "dual-study-grid";
    model.studies.forEach(study => {
      const card = document.createElement("article");
      card.className = "dual-study-card";
      const header = document.createElement("header");
      appendText(document, header, "span", study.displayLabel, "dual-study-number");
      appendText(document, header, "h4", study.citation);
      appendText(document, header, "strong", study.tierLabel);
      card.append(header);
      const states = document.createElement("ol");
      states.className = "dual-study-state-list";
      [
        study.pdfLabel,
        study.genericLabel,
        study.chemicalLabel,
        study.completionLabel,
        study.reconciliationLabel,
        study.evidenceLabel,
      ].forEach(value => appendText(document, states, "li", value));
      card.append(states);
      appendText(document, card, "p", `${study.actorLabel} · ${study.updatedLabel}`, "dual-parse-freshness");
      appendImportControl(document, card, study, handlers);
      list.append(card);
    });
    if (!model.studies.length) appendText(document, list, "p", "尚无可显示的双层解析研究状态。", "dual-parse-empty");
    parent.append(list);
  }

  function renderPreflight(document, parent, preflight, handlers) {
    parent.replaceChildren();
    appendText(document, parent, "h4", "Chemical import · 预检后确认");
    if (!preflight) {
      appendText(document, parent, "p", "选择 ZIP 只做预检；确认前不会写入权威状态。", "dual-parse-empty");
      return;
    }
    appendText(document, parent, "strong", preflight.statusLabel);
    const facts = document.createElement("ul");
    facts.className = "dual-parse-facts";
    [preflight.pageLabel, preflight.moleculeLabel, preflight.engineLabel, preflight.fileKindsLabel]
      .forEach(value => appendText(document, facts, "li", value));
    parent.append(facts);
    preflight.gaps.forEach(value => appendText(document, parent, "p", value, "dual-parse-gap"));
    appendText(document, parent, "p", `${preflight.actorLabel} · ${preflight.updatedLabel}`, "dual-parse-freshness");
    if (!preflight.confirmAvailable) return;
    const confirm = document.createElement("button");
    confirm.type = "button";
    confirm.className = "dual-parse-primary";
    confirm.textContent = "确认导入";
    confirm.addEventListener("click", () => {
      const target = preflightTargetByModel.get(preflight);
      if (!target) return;
      openConfirmationDialog(
        document,
        confirm,
        "确认 Chemical Paper 导入",
        "确认后将重新核对当前 PDF 绑定并写入权威状态。",
        "确认导入",
        () => handlers?.onImportConfirm?.(
          importConfirmRequest(target.studyId, target.preflightToken, safeActor(handlers)),
        ),
      );
    });
    parent.append(confirm);
  }

  function groupCompletionRows(rows) {
    const groups = new Map();
    rows.forEach(row => {
      const target = completionTargetByModel.get(row);
      if (!target) return;
      const key = `${target.studyId}\u0000${target.versionToken}`;
      if (!groups.has(key)) groups.set(key, {target, rows: []});
      groups.get(key).rows.push(row);
    });
    return Array.from(groups.values());
  }

  function renderCompletion(document, parent, rows, handlers) {
    parent.replaceChildren();
    appendText(document, parent, "h4", "Chemical Completion Queue");
    const groups = groupCompletionRows(rows);
    groups.forEach((group, groupIndex) => {
      const form = document.createElement("form");
      form.className = "dual-completion-form";
      appendText(document, form, "h5", `待补全批次 ${groupIndex + 1}`);
      const controls = [];
      group.rows.forEach((row, rowIndex) => {
        const fieldset = document.createElement("fieldset");
        const legend = document.createElement("legend");
        legend.textContent = `${row.fieldLabel} · ${row.locatorLabel}`;
        fieldset.append(legend);
        if (row.pdfPageUrl) {
          const link = document.createElement("a");
          link.href = row.pdfPageUrl;
          link.target = "_blank";
          link.rel = "noopener";
          link.textContent = "打开原始 PDF 页核对 ↗";
          fieldset.append(link);
        }
        const value = document.createElement("input");
        value.autocomplete = "off";
        const reason = document.createElement("textarea");
        reason.rows = 2;
        const page = document.createElement("input");
        page.type = "number";
        page.min = "1";
        page.value = row.page ? String(row.page) : "";
        const figure = document.createElement("input");
        figure.autocomplete = "off";
        fieldset.append(
          labelledControl(document, `${row.fieldLabel} 补充值`, value),
          labelledControl(document, "PDF 核对理由", reason),
          labelledControl(document, "PDF 页码", page),
          labelledControl(document, "图、Scheme 或表号（可选）", figure),
        );
        form.append(fieldset);
        controls.push({row, value, reason, page, figure, rowIndex});
      });
      const submit = document.createElement("button");
      submit.type = "submit";
      submit.className = "dual-parse-primary";
      submit.textContent = "保存本批次补全";
      form.append(submit);
      form.addEventListener("submit", event => {
        event.preventDefault();
        try {
          const corrections = controls.map(control => ({
            moleculeIndex: completionTargetByModel.get(control.row).moleculeIndex,
            field: control.row.field,
            value: control.value.value,
            reason: control.reason.value,
            pdfLocator: {page: Number(control.page.value), figureLabel: control.figure.value},
          }));
          handlers?.onCompletionSave?.(
            completionBatchRequest(group.target.studyId, group.target.versionToken, corrections, safeActor(handlers)),
            form,
          );
        } catch (_) {
          handlers?.onValidationError?.("请为本批次每一项填写补充值、PDF 页码与核对理由。");
        }
      });
      parent.append(form);
    });
    if (!groups.length) appendText(document, parent, "p", "当前没有缺失名称、局部标签或 SMILES。", "dual-parse-empty");
  }

  function renderReconciliation(document, parent, items, handlers) {
    parent.replaceChildren();
    appendText(document, parent, "h4", "Reconciliation");
    items.forEach((item, index) => {
      const card = document.createElement("article");
      card.className = "dual-reconciliation-card";
      const heading = document.createElement("header");
      appendText(document, heading, "h5", `${item.kindLabel} ${index + 1}`);
      appendText(document, heading, "strong", item.statusLabel);
      card.append(heading);
      const candidates = document.createElement("div");
      candidates.className = "dual-candidate-grid";
      [["Generic candidate", item.genericCandidate], ["Chemical candidate", item.chemicalCandidate]].forEach(([label, value]) => {
        const pane = document.createElement("section");
        appendText(document, pane, "span", label);
        appendText(document, pane, "p", value);
        candidates.append(pane);
      });
      card.append(candidates);
      appendText(document, card, "p", item.locatorLabel, "dual-parse-freshness");
      if (item.pdfPageUrl) {
        const link = document.createElement("a");
        link.href = item.pdfPageUrl;
        link.target = "_blank";
        link.rel = "noopener";
        link.textContent = "打开原始 PDF 页仲裁 ↗";
        card.append(link);
      }
      const target = reconciliationTargetByModel.get(item);
      if (target && ["conflict", "needs_review", "single_lane_only", "stale"].includes(item.status)) {
        const form = document.createElement("form");
        form.className = "dual-reconciliation-form";
        const action = document.createElement("select");
        [["", "选择 PDF 仲裁动作"], ["pdf_resolved", "按 PDF 选择候选"], ["pdf_locator_only", "仅使用 PDF 定位"], ["reject_both", "拒绝两侧候选"]]
          .forEach(([value, label]) => {
            const option = document.createElement("option");
            option.value = value;
            option.textContent = label;
            action.append(option);
          });
        const lane = document.createElement("select");
        [["", "不预选 lane"], ["generic", "Generic"], ["chemical", "Chemical"]].forEach(([value, label]) => {
          const option = document.createElement("option");
          option.value = value;
          option.textContent = label;
          lane.append(option);
        });
        lane.disabled = true;
        action.addEventListener("change", () => {
          lane.disabled = action.value !== "pdf_resolved";
          if (lane.disabled) lane.value = "";
        });
        const note = document.createElement("textarea");
        note.rows = 2;
        const page = document.createElement("input");
        page.type = "number";
        page.min = "1";
        page.value = item.page ? String(item.page) : "";
        const figure = document.createElement("input");
        figure.autocomplete = "off";
        const submit = document.createElement("button");
        submit.type = "submit";
        submit.textContent = "保存 PDF 仲裁";
        form.append(
          labelledControl(document, "仲裁动作", action),
          labelledControl(document, "采用的 lane（仅 PDF 选择候选时）", lane),
          labelledControl(document, "PDF 仲裁说明", note),
          labelledControl(document, "PDF 页码", page),
          labelledControl(document, "图、Scheme 或表号（可选）", figure),
          submit,
        );
        form.addEventListener("submit", event => {
          event.preventDefault();
          try {
            handlers?.onReconciliationSave?.(reconciliationRequest(
              target.studyId,
              target.objectId,
              target.registryDigest,
              {
                action: action.value,
                selectedLane: lane.value,
                note: note.value,
                pdfLocator: {page: Number(page.value), figureLabel: figure.value},
              },
              safeActor(handlers),
            ), form);
          } catch (_) {
            handlers?.onValidationError?.("请选择仲裁动作，并填写 PDF 页码与说明；选择候选时还需明确 lane。");
          }
        });
        card.append(form);
      }
      appendText(document, card, "p", `${item.actorLabel} · ${item.updatedLabel}`, "dual-parse-freshness");
      parent.append(card);
    });
    if (!items.length) appendText(document, parent, "p", "当前没有需要人工仲裁的双层差异。", "dual-parse-empty");
  }

  function render(document, mount, input, handlers) {
    if (!document || !mount) return;
    const model = input?.contractValid === true ? input : projectionModel(input);
    const studyRoot = mount.querySelector("#dual-study-status");
    const preflightRoot = mount.querySelector("#chemical-import-preflight");
    const completionRoot = mount.querySelector("#chemical-completion-queue");
    const reconciliationRoot = mount.querySelector("#reconciliation-list");
    if (!studyRoot || !preflightRoot || !completionRoot || !reconciliationRoot) return;
    const wiredHandlers = {
      ...(handlers || {}),
      onPreflightResult: payload => {
        renderPreflight(document, preflightRoot, importPreflightModel(payload), wiredHandlers);
      },
    };
    renderStatus(document, studyRoot, model, wiredHandlers);
    renderStudies(document, studyRoot, model, wiredHandlers);
    renderPreflight(document, preflightRoot, model.importPreflight, wiredHandlers);
    renderCompletion(document, completionRoot, model.completionQueue, wiredHandlers);
    renderReconciliation(document, reconciliationRoot, model.reconciliationItems, wiredHandlers);
  }

  async function load(projectId, request) {
    const requester = request || globalThis.fetch;
    if (typeof requester !== "function") throw new Error("request function required");
    const encoded = encodeURIComponent(required(projectId, "project id"));
    try {
      const response = await requester.call(globalThis, `/api/project/${encoded}/dual-parse`);
      if (!response.ok) {
        return projectionModel({
          schema_version: "dual-parse-projection.v1",
          status: "failed",
          failure_message: "双层解析状态读取失败；权威状态未更改。",
          retryable: true,
        });
      }
      return projectionModel(await response.json());
    } catch (_) {
      return projectionModel({
        schema_version: "dual-parse-projection.v1",
        status: "failed",
        failure_message: "网络不可用；双层解析状态未更改。",
        retryable: true,
      });
    }
  }

  return {
    availabilityModel,
    completionBatchRequest,
    importConfirmRequest,
    importPreflightRequest,
    load,
    projectionModel,
    reconciliationRequest,
    render,
  };
}));
