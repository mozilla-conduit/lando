import { describe, test, expect } from "vitest";
import {
  repoForTrain,
  trainForRepo,
  cycleStage,
  versionChoices,
  resolveVersion,
  hintForRepo,
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
  test("maps mainline trains to their Lando repositories", () => {
    expect(repoForTrain("beta"), "`beta` should map to `firefox-beta`.").toBe(
      "firefox-beta",
    );
    expect(
      repoForTrain("release"),
      "`release` should map to `firefox-release`.",
    ).toBe("firefox-release");
    expect(
      repoForTrain("nightly"),
      "`nightly` should map to `firefox-main`.",
    ).toBe("firefox-main");
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

  test("returns null for unknown trains and repositories", () => {
    expect(
      repoForTrain("esr"),
      "An unknown train should not resolve to a repository.",
    ).toBeNull();
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
    const result = resolveVersion(151, BETA_SHIPPING);
    expect(
      result?.repos,
      "Choosing the release version should target both release and beta.",
    ).toEqual(["firefox-release", "firefox-beta"]);
  });

  test("targets beta when betas are still shipping", () => {
    const result = resolveVersion(152, BETA_SHIPPING);
    expect(
      result?.repos,
      "During beta-shipping the beta version should target beta.",
    ).toEqual(["firefox-beta"]);
    expect(
      result?.note,
      "The note should state the patch lands in Firefox 152.",
    ).toBe("This will land in Firefox 152.");
  });

  test("targets release for a major release during rc-shipping", () => {
    const result = resolveVersion(152, RC_SHIPPING);
    expect(
      result?.repos,
      "During rc-shipping the beta version should target release.",
    ).toEqual(["firefox-release"]);
    expect(result?.note, "The note should mention the major release.").toBe(
      "This will land in Firefox 152.0 (major release).",
    );
  });

  test("targets release for a minor release once dot releases only remain", () => {
    const result = resolveVersion(152, DOT_RELEASES_ONLY);
    expect(
      result?.repos,
      "Once only dot releases remain the beta version should target release.",
    ).toEqual(["firefox-release"]);
    expect(result?.note, "The note should mention a minor release.").toBe(
      "This will land in a Firefox 152.0.x minor release.",
    );
  });

  test("returns null for a version that is not selectable", () => {
    expect(
      resolveVersion(153, BETA_SHIPPING),
      "The nightly version is not a valid uplift target.",
    ).toBeNull();
  });
});

describe("hintForRepo", () => {
  test("hints the landing version when selecting beta during beta-shipping", () => {
    expect(
      hintForRepo("firefox-beta", BETA_SHIPPING),
      "Selecting beta while betas ship should hint the landing version.",
    ).toEqual({ message: "This will land in Firefox 152.", level: "info" });
  });

  test("warns when selecting beta after betas are done", () => {
    expect(
      hintForRepo("firefox-beta", RC_SHIPPING),
      "Selecting beta with no betas left should warn and redirect to release.",
    ).toEqual({
      message:
        "No betas remaining for Firefox 152; select release to land this in Firefox 152.",
      level: "warning",
    });
    expect(
      hintForRepo("firefox-beta", DOT_RELEASES_ONLY)?.level,
      "Selecting beta during dot-releases-only should also warn.",
    ).toBe("warning");
  });

  test("hints the next dot release when selecting release during beta-shipping", () => {
    expect(
      hintForRepo("firefox-release", BETA_SHIPPING),
      "Selecting release while betas ship should hint the next 151 dot release.",
    ).toEqual({
      message: "This will land in the next Firefox 151 dot release.",
      level: "info",
    });
  });

  test("hints the major release when selecting release during rc-shipping", () => {
    expect(
      hintForRepo("firefox-release", RC_SHIPPING),
      "Selecting release during rc-shipping should hint the major release.",
    ).toEqual({
      message: "This will land in Firefox 152.0 (major release).",
      level: "info",
    });
  });

  test("hints the next dot release when selecting release during dot-releases-only", () => {
    expect(
      hintForRepo("firefox-release", DOT_RELEASES_ONLY),
      "Selecting release during dot-releases-only should hint the next 152 dot release.",
    ).toEqual({
      message: "This will land in the next Firefox 152 dot release.",
      level: "info",
    });
  });

  test("returns null for repositories without train-specific guidance", () => {
    expect(
      hintForRepo("firefox-esr128", BETA_SHIPPING),
      "ESR repositories should have no train hint.",
    ).toBeNull();
  });
});
