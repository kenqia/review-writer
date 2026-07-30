(function (root, factory) {
  "use strict";
  const api = factory();
  if (typeof module === "object" && module.exports) module.exports = api;
  root.ReviewSessionUI = api;
  if (root.window === root) api.installDecisionActor(root);
}(typeof globalThis !== "undefined" ? globalThis : this, function () {
  "use strict";

  function installDecisionActor(window) {
    const params = new URLSearchParams(window.location.search);
    const simulated = params.get("review_actor") === "simulated_researcher_agent";

    window.reviewDecisionActor = () => simulated
      ? {
          actor_type: "simulated_researcher_agent",
          actor_label: "dashboard-playwright-reviewer",
        }
      : {};
  }

  function createProjectRefreshScheduler(options) {
    const refresh = options?.refresh;
    const getProjectId = options?.getProjectId;
    const setTimer = options?.setTimer;
    const clearTimer = options?.clearTimer;
    const emptyDelay = options?.emptyDelay;
    const selectedDelay = options?.selectedDelay;
    if (typeof refresh !== "function" || typeof getProjectId !== "function") {
      throw new Error("refresh and project reader required");
    }
    if (typeof setTimer !== "function" || typeof clearTimer !== "function") {
      throw new Error("timer functions required");
    }
    if (!Number.isInteger(emptyDelay) || emptyDelay < 1000) throw new Error("empty delay required");
    if (!Number.isInteger(selectedDelay) || selectedDelay < emptyDelay) throw new Error("selected delay required");

    let timer = null;
    let running = false;
    let stopped = true;

    function schedule() {
      if (stopped || timer !== null || running) return;
      timer = setTimer(tick, getProjectId() ? selectedDelay : emptyDelay);
    }

    async function tick() {
      timer = null;
      if (stopped || running) return;
      running = true;
      try {
        await refresh();
      } catch (_) {
        // Project discovery is recoverable; the next bounded tick retries once.
      } finally {
        running = false;
        schedule();
      }
    }

    return {
      start() {
        if (!stopped) return;
        stopped = false;
        schedule();
      },
      stop() {
        stopped = true;
        if (timer !== null) clearTimer(timer);
        timer = null;
      },
    };
  }

  return {createProjectRefreshScheduler, installDecisionActor};
}));
