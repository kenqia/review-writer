(function (root, factory) {
  "use strict";
  const api = factory();
  if (typeof module === "object" && module.exports) module.exports = api;
  if (root) root.ReviewReleaseUI = api;
}(typeof window !== "undefined" ? window : null, function () {
  "use strict";

  const object = value => value && typeof value === "object" ? value : {};
  const array = value => Array.isArray(value) ? value : [];

  function artifactControl(value) {
    const row = object(value);
    const downloadUrl = typeof row.download_url === "string" && row.download_url.startsWith("/")
      ? row.download_url
      : "#";
    const downloadVisible = Boolean(row.exists && row.current && downloadUrl !== "#");
    return {
      downloadVisible,
      downloadUrl: downloadVisible ? downloadUrl : "#",
    };
  }

  function deriveReleaseControls(input) {
    const value = object(input);
    const capabilities = object(value.capabilities);
    const figures = object(value.figures);
    const artifacts = object(value.artifacts);
    const unresolved = array(figures.placeholders).filter(row => object(row).status !== "verified");
    const internalArtifact = artifactControl(artifacts.internal);
    const verifiedArtifact = artifactControl(artifacts.verified);
    const internalReady = capabilities.internal_draft_export_ready === true;
    const verifiedReady = capabilities.verified_release_ready === true && unresolved.length === 0;
    return {
      internal: {
        disabled: !internalReady,
        reason: internalReady ? "" : "INTERNAL_DRAFT_NOT_READY",
        ...internalArtifact,
      },
      verified: {
        disabled: !verifiedReady,
        reason: unresolved.length ? "FIGURE_PLACEHOLDER_PENDING" : verifiedReady ? "" : "VERIFIED_RELEASE_NOT_READY",
        ...verifiedArtifact,
      },
      unresolvedPlaceholderCount: unresolved.length,
    };
  }

  function buildExportRequest(releaseLevel) {
    if (!new Set(["SELF_REVIEWED_DRAFT", "EXPERT_REVIEWED_RELEASE"]).has(releaseLevel)) {
      throw new Error("release level is invalid");
    }
    return {release_level: releaseLevel};
  }

  return {buildExportRequest, deriveReleaseControls};
}));
