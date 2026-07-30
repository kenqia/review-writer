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
      isActive() {
        return !stopped;
      },
    };
  }

  function installProjectRefreshLifecycle(window, getController) {
    if (!window || typeof window.addEventListener !== "function" || typeof getController !== "function") {
      throw new Error("window and refresh controller reader required");
    }
    window.addEventListener("pagehide", () => getController()?.stop());
    window.addEventListener("pageshow", event => {
      const controller = getController();
      if (event?.persisted === true || controller?.isActive() === false) controller?.start();
    });
  }

  function createProjectSurfaceCoordinator(options) {
    const getProjectId = options?.getProjectId;
    const load = options?.load;
    const render = options?.render;
    if (typeof getProjectId !== "function" || typeof load !== "function" || typeof render !== "function") {
      throw new Error("project reader, loader, and renderer required");
    }

    let projectId = String(getProjectId() || "");
    let generation = 0;
    let operationEpoch = 0;
    let refreshRunning = false;
    let refreshQueued = false;
    let mutationRunning = false;

    function syncProject() {
      const nextProjectId = String(getProjectId() || "");
      if (nextProjectId !== projectId) {
        projectId = nextProjectId;
        generation += 1;
        if (refreshRunning || mutationRunning) refreshQueued = true;
        options?.onProjectChange?.({projectId, generation, operationEpoch});
      }
      return {projectId, generation, operationEpoch};
    }

    function isCurrent(context) {
      const current = syncProject();
      return current.projectId === context.projectId
        && current.generation === context.generation
        && current.operationEpoch === context.operationEpoch;
    }

    async function drainRefresh() {
      if (!refreshQueued || refreshRunning || mutationRunning) return;
      refreshQueued = false;
      await refresh();
    }

    async function refresh() {
      const context = syncProject();
      if (!context.projectId) return {status: "empty"};
      if (refreshRunning || mutationRunning) {
        refreshQueued = true;
        return {status: "queued"};
      }
      refreshRunning = true;
      try {
        const value = await load(context.projectId, context);
        if (!isCurrent(context)) return {status: "stale"};
        render(value, context);
        return {status: "rendered"};
      } catch (error) {
        if (isCurrent(context)) options?.onLoadError?.(error, context);
        return {status: "error"};
      } finally {
        refreshRunning = false;
        await drainRefresh();
      }
    }

    async function mutate(run, settings) {
      if (typeof run !== "function") throw new Error("mutation required");
      const projectContext = syncProject();
      if (!projectContext.projectId) return {status: "empty"};
      if (mutationRunning) return {status: "busy"};
      operationEpoch += 1;
      const context = {...projectContext, operationEpoch};
      mutationRunning = true;
      try {
        const value = await run(context.projectId, context);
        const current = isCurrent(context);
        if (current && typeof settings?.renderResult === "function") {
          settings.renderResult(value, context);
        }
        return {status: current ? "saved" : "stale"};
      } catch (error) {
        if (isCurrent(context)) settings?.onError?.(error, context);
        return {status: "error"};
      } finally {
        if (settings?.refreshAfterMutation === true) refreshQueued = true;
        mutationRunning = false;
        await drainRefresh();
      }
    }

    function projectChanged() {
      syncProject();
      return refresh();
    }

    return {mutate, projectChanged, refresh};
  }

  return {
    createProjectRefreshScheduler,
    createProjectSurfaceCoordinator,
    installDecisionActor,
    installProjectRefreshLifecycle,
  };
}));
