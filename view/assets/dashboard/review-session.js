(function () {
  "use strict";
  const params = new URLSearchParams(window.location.search);
  const simulated = params.get("review_actor") === "simulated_researcher_agent";

  window.reviewDecisionActor = () => simulated
    ? {
        actor_type: "simulated_researcher_agent",
        actor_label: "dashboard-playwright-reviewer",
      }
    : {};
}());
