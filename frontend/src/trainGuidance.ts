// Translates whattrainisitnow.com release-train guidance into recommendations
// for Lando's uplift repository checkboxes. The data is keyed by mainline train
// (`nightly`, `beta`, `release`); see bug 2045812 for the response shape.

export type Train = "nightly" | "beta" | "release";

export type CycleStage = "beta-shipping" | "rc-shipping" | "dot-releases-only";

export type GuidanceLevel = "info" | "warning";

export interface TrainInfo {
  version: number;
  release_date: string;
}

export interface BetaTrainInfo extends TrainInfo {
  has_betas_left: boolean;
  is_rc_shipped: boolean;
}

export interface ReleaseSchedule {
  nightly: TrainInfo;
  beta: BetaTrainInfo;
  release: TrainInfo;
}

export interface VersionChoice {
  version: number;
  train: Train;
}

export interface VersionRecommendation {
  repos: string[];
  note: string;
  level: GuidanceLevel;
}

export interface RepoHint {
  message: string;
  level: GuidanceLevel;
}

// Lando repository names for each mainline train. Only `beta` and `release`
// participate in uplift recommendations; `nightly` is included for completeness
// since patches landing there go through autoland, not uplift.
const TRAIN_REPOS: Record<Train, string> = {
  nightly: "firefox-main",
  beta: "firefox-beta",
  release: "firefox-release",
};

const REPO_TRAINS: Record<string, Train> = Object.fromEntries(
  Object.entries(TRAIN_REPOS).map(([train, repo]) => [repo, train as Train]),
);

export function repoForTrain(train: string): string | null {
  return TRAIN_REPOS[train as Train] ?? null;
}

export function trainForRepo(repo: string): Train | null {
  return REPO_TRAINS[repo] ?? null;
}

// Return the current point in the release cycle, derived from the beta train.
//   `beta-shipping`     - betas are still being released for the beta version.
//   `rc-shipping`       - betas are done; the release candidate is in progress.
//   `dot-releases-only` - the release candidate shipped; only dot releases remain.
export function cycleStage(schedule: ReleaseSchedule): CycleStage {
  const beta = schedule.beta;
  if (beta.has_betas_left) {
    return "beta-shipping";
  }
  if (!beta.is_rc_shipped) {
    return "rc-shipping";
  }
  return "dot-releases-only";
}

// Return the Firefox versions a user may target for uplift, newest first.
// Nightly is excluded because those patches land via autoland, not uplift.
export function versionChoices(schedule: ReleaseSchedule): VersionChoice[] {
  return [
    { version: schedule.beta.version, train: "beta" },
    { version: schedule.release.version, train: "release" },
  ];
}

// Map a chosen target version onto the repositories to select, with a note
// explaining where the patch will land. Returns `null` for an unknown version.
export function resolveVersion(
  version: number,
  schedule: ReleaseSchedule,
): VersionRecommendation | null {
  if (version === schedule.release.version) {
    return resolveReleaseVersion(schedule);
  }
  if (version === schedule.beta.version) {
    return resolveBetaVersion(schedule);
  }
  return null;
}

// The release version is already shipped, so target both branches to cover the
// current release and the upcoming one.
function resolveReleaseVersion(
  schedule: ReleaseSchedule,
): VersionRecommendation {
  return {
    repos: [repoForTrain("release")!, repoForTrain("beta")!],
    note: `This will land in both Firefox ${schedule.release.version} and Firefox ${schedule.beta.version}.`,
    level: "info",
  };
}

function resolveBetaVersion(schedule: ReleaseSchedule): VersionRecommendation {
  const version = schedule.beta.version;
  const stage = cycleStage(schedule);

  if (stage === "beta-shipping") {
    return {
      repos: [repoForTrain("beta")!],
      note: `This will land in Firefox ${version}.`,
      level: "info",
    };
  }
  if (stage === "rc-shipping") {
    return {
      repos: [repoForTrain("release")!],
      note: `This will land in Firefox ${version}.0 (major release).`,
      level: "info",
    };
  }
  return {
    repos: [repoForTrain("release")!],
    note: `This will land in a Firefox ${version}.0.x minor release.`,
    level: "info",
  };
}

// Return guidance shown when a user manually selects a repository, or `null`
// when the repository has no train-specific hint (e.g. ESR).
export function hintForRepo(
  repo: string,
  schedule: ReleaseSchedule,
): RepoHint | null {
  const train = trainForRepo(repo);
  if (train === "beta") {
    return betaHint(schedule);
  }
  if (train === "release") {
    return releaseHint(schedule);
  }
  return null;
}

function betaHint(schedule: ReleaseSchedule): RepoHint {
  const version = schedule.beta.version;
  if (cycleStage(schedule) === "beta-shipping") {
    return { message: `This will land in Firefox ${version}.`, level: "info" };
  }
  return {
    message: `No betas remaining for Firefox ${version}; select release to land this in Firefox ${version}.`,
    level: "warning",
  };
}

function releaseHint(schedule: ReleaseSchedule): RepoHint {
  const stage = cycleStage(schedule);
  if (stage === "beta-shipping") {
    return {
      message: `This will land in the next Firefox ${schedule.release.version} dot release.`,
      level: "info",
    };
  }
  if (stage === "rc-shipping") {
    return {
      message: `This will land in Firefox ${schedule.beta.version}.0 (major release).`,
      level: "info",
    };
  }
  return {
    message: `This will land in the next Firefox ${schedule.beta.version} dot release.`,
    level: "info",
  };
}
