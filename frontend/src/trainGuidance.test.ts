import { describe, test, expect } from "vitest";
import {
  TRAIN_REPOS,
  trainForRepo,
  cycleStage,
  versionChoices,
  resolveVersion,
  summarizeRepos,
  type ReleaseSchedule,
} from "./trainGuidance";

// The example response from bug 2045812 comment 1, which represents the
// beta-shipping stage (betas still being released for Firefox 152).
const BETA_SHIPPING: ReleaseSchedule = {
  nightly: { version: 153, release_date: "2026-07-21" },
  beta: {
    version: 152,
    release_date: "2026-06-16",
    has_betas_left: true,
    is_rc_shipped: false,
  },
  release: { version: 151, release_date: "2026-05-19" },
};

// Betas are done and the release candidate is being built but has not shipped.
const RC_SHIPPING: ReleaseSchedule = {
  ...BETA_SHIPPING,
  beta: { ...BETA_SHIPPING.beta, has_betas_left: false, is_rc_shipped: false },
};

// The release candidate shipped; only Firefox 152 dot releases remain.
const DOT_RELEASES_ONLY: ReleaseSchedule = {
  ...BETA_SHIPPING,
  beta: { ...BETA_SHIPPING.beta, has_betas_left: false, is_rc_shipped: true },
};

describe("train/repo mapping", () => {
  test("maps each mainline train to its Lando repository", () => {
    expect(
      TRAIN_REPOS,
      "Each train should map to its Lando repository.",
    ).toEqual({
      nightly: "firefox-main",
      beta: "firefox-beta",
      release: "firefox-release",
    });
  });

  test("maps repositories back to their train", () => {
    expect(
      trainForRepo("firefox-beta"),
      "`firefox-beta` should map back to `beta`.",
    ).toBe("beta");
    expect(
      trainForRepo("firefox-release"),
      "`firefox-release` should map back to `release`.",
    ).toBe("release");
  });

  test("returns null for an unknown repository", () => {
    expect(
      trainForRepo("firefox-esr128"),
      "An ESR repository should have no mainline train.",
    ).toBeNull();
  });
});

describe("cycleStage", () => {
  test("identifies each stage from the beta train flags", () => {
    expect(
      cycleStage(BETA_SHIPPING),
      "`has_betas_left` should indicate the beta-shipping stage.",
    ).toBe("beta-shipping");
    expect(
      cycleStage(RC_SHIPPING),
      "No betas left and no RC shipped should indicate the rc-shipping stage.",
    ).toBe("rc-shipping");
    expect(
      cycleStage(DOT_RELEASES_ONLY),
      "A shipped RC should indicate the dot-releases-only stage.",
    ).toBe("dot-releases-only");
  });
});

describe("versionChoices", () => {
  test("offers the beta and release versions, newest first", () => {
    expect(
      versionChoices(BETA_SHIPPING),
      "Only the beta and release versions should be selectable, beta first.",
    ).toEqual([
      { version: 152, train: "beta" },
      { version: 151, train: "release" },
    ]);
  });
});

describe("resolveVersion", () => {
  test("targets both branches for the release version", () => {
    expect(
      resolveVersion(151, BETA_SHIPPING),
      "Choosing the release version should target both release and beta.",
    ).toEqual(["firefox-release", "firefox-beta"]);
  });

  test("targets beta when betas are still shipping", () => {
    expect(
      resolveVersion(152, BETA_SHIPPING),
      "During beta-shipping the beta version should target beta.",
    ).toEqual(["firefox-beta"]);
  });

  test("targets release once betas are closed", () => {
    expect(
      resolveVersion(152, RC_SHIPPING),
      "During rc-shipping the beta version should target release.",
    ).toEqual(["firefox-release"]);
    expect(
      resolveVersion(152, DOT_RELEASES_ONLY),
      "Once only dot releases remain the beta version should target release.",
    ).toEqual(["firefox-release"]);
  });

  test("returns null for a version that is not selectable", () => {
    expect(
      resolveVersion(153, BETA_SHIPPING),
      "The nightly version is not a valid uplift target.",
    ).toBeNull();
  });
});

describe("summarizeRepos", () => {
  test("combines multiple trains into a single landing sentence", () => {
    const guidance = summarizeRepos(
      ["firefox-beta", "firefox-release"],
      BETA_SHIPPING,
    );
    expect(
      guidance.landing,
      "Selecting both trains should yield one combined sentence.",
    ).toBe(
      "This will land in Firefox 152 and the next Firefox 151 dot release.",
    );
    expect(
      guidance.warnings,
      "There should be no warnings while betas are shipping.",
    ).toEqual([]);
  });

  test("describes the major release during rc-shipping", () => {
    expect(
      summarizeRepos(["firefox-release"], RC_SHIPPING).landing,
      "Release during rc-shipping should mention the major release.",
    ).toBe("This will land in Firefox 152.0 (major release).");
  });

  test("describes the next dot release during dot-releases-only", () => {
    expect(
      summarizeRepos(["firefox-release"], DOT_RELEASES_ONLY).landing,
      "Release during dot-releases-only should mention the next dot release.",
    ).toBe("This will land in the next Firefox 152 dot release.");
  });

  test("warns when beta is selected after betas are closed", () => {
    const guidance = summarizeRepos(["firefox-beta"], RC_SHIPPING);
    expect(
      guidance.landing,
      "Beta has no landing target once betas are closed.",
    ).toBe("");
    expect(
      guidance.warnings,
      "Selecting beta with no betas left should warn and redirect to release.",
    ).toEqual([
      "No betas remaining for Firefox 152; select release to land this in Firefox 152.",
    ]);
  });

  test("ignores repositories without train-specific guidance", () => {
    expect(
      summarizeRepos(["firefox-esr128"], BETA_SHIPPING),
      "ESR repositories contribute no guidance.",
    ).toEqual({ landing: "", warnings: [] });
  });
});
