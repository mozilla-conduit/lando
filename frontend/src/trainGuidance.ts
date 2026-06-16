/**
 * Translates whattrainisitnow.com release-train guidance into recommendations
 * for Lando's uplift repository checkboxes. The data is keyed by mainline train
 * (`nightly`, `beta`, `release`); see bug 2045812 for the response shape.
 */

import { z } from "zod";

export type Train = "nightly" | "beta" | "release";

/**
 * The Lando repository for each mainline train — the single source of truth for
 * the train `<->` repository mapping. Only `beta` and `release` participate in
 * uplift recommendations; `nightly` is included for completeness since patches
 * landing there go through autoland, not uplift. `as const satisfies` keeps the
 * repository names as literal types so `RepoName` can be derived from them.
 */
export const TRAIN_REPOS = {
    nightly: "firefox-main",
    beta: "firefox-beta",
    release: "firefox-release",
} as const satisfies Record<Train, string>;

/** The Lando repository names, derived from `TRAIN_REPOS`. */
export type RepoName = (typeof TRAIN_REPOS)[Train];

/** Cycle state derived from the beta train's flags. */
export type CycleStage = "beta-shipping" | "rc-shipping" | "dot-releases-only";

/** Per-train fields common to every train in the response. */
const trainInfoSchema = z.object({
    version: z.number(),
    release_date: z.string(),
});

/**
 * Schema for the whattrainisitnow.com response (see bug 2045812). This is the
 * single source of truth: the `ReleaseSchedule` type is inferred from it, and
 * the same schema validates the payload at runtime. Unknown keys are ignored,
 * so extra API fields will not fail validation.
 */
export const releaseScheduleSchema = z.object({
    nightly: trainInfoSchema,
    beta: trainInfoSchema.extend({
        has_betas_left: z.boolean(),
        is_rc_shipped: z.boolean(),
    }),
    release: trainInfoSchema,
});

/** The validated shape of the train-guidance API response. */
export type ReleaseSchedule = z.infer<typeof releaseScheduleSchema>;

/** Mapping of release train to Firefox version. */
export interface VersionChoice {
    version: number;
    train: Train;
}

/** Guidance describing where a set of selected repositories will land. */
export interface RepoGuidance {
    /**
     * A single informational sentence covering every selected train, or `""`
     * when none of the selected repositories have train-specific guidance.
     */
    landing: string;

    /**
     * Cautions for selected repositories that will not land as expected (e.g.
     * selecting beta once no betas remain).
     */
    warnings: string[];
}

/**
 * Reverse of `TRAIN_REPOS`, derived from it so the two mappings cannot drift.
 */
const TRAINS_BY_REPO: Record<string, Train> = Object.fromEntries(
    Object.entries(TRAIN_REPOS).map(([train, repo]) => [repo, train as Train]),
);

/**
 * Return the train a repository belongs to, or `null` if it is not a mainline
 * repository.
 *
 * @param repo - A Lando repository name.
 */
export function trainForRepo(repo: string): Train | null {
    return TRAINS_BY_REPO[repo] ?? null;
}

/**
 * Return the current point in the release cycle, derived from the beta train.
 *
 * @remarks
 * - `beta-shipping` — betas are still being released for the beta version.
 * - `rc-shipping` — betas are done; the release candidate is in progress.
 * - `dot-releases-only` — the release candidate shipped; only dot releases remain.
 */
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

/**
 * Return the Firefox versions a user may target for uplift, newest first.
 * Nightly is excluded because those patches land via autoland, not uplift.
 */
export function versionChoices(schedule: ReleaseSchedule): VersionChoice[] {
    return [
        { version: schedule.beta.version, train: "beta" },
        { version: schedule.release.version, train: "release" },
    ];
}

/**
 * Map a chosen target version onto the repositories to select.
 *
 * @param version - The Firefox major version the user selected.
 * @param schedule - The current release schedule.
 * @returns The repositories to tick, or `null` for a version that is not a
 *   valid uplift target.
 */
export function resolveVersion(
    version: number,
    schedule: ReleaseSchedule,
): string[] | null {
    if (version === schedule.release.version) {
        // The release version already shipped, so target both branches to cover the
        // current release and the upcoming one.
        return [TRAIN_REPOS.release, TRAIN_REPOS.beta];
    }

    if (version === schedule.beta.version) {
        // During beta-shipping the patch rides the beta train; afterwards betas are
        // closed, so it must target the release branch instead.
        return cycleStage(schedule) === "beta-shipping"
            ? [TRAIN_REPOS.beta]
            : [TRAIN_REPOS.release];
    }

    return null;
}

/**
 * Summarize where the given repositories will land, combining every train's
 * landing target into a single sentence plus any cautionary warnings.
 *
 * @param repos - The selected repository names.
 * @param schedule - The current release schedule.
 */
export function summarizeRepos(
    repos: string[],
    schedule: ReleaseSchedule,
): RepoGuidance {
    const phrases = repos
        .map((repo) => landingPhrase(repo, schedule))
        .filter((phrase): phrase is string => phrase !== null);

    const warnings = repos
        .map((repo) => landingWarning(repo, schedule))
        .filter((warning): warning is string => warning !== null);

    const landing = phrases.length ? `This will land in ${joinWithAnd(phrases)}.` : "";

    return { landing, warnings };
}

/**
 * Describe where a single repository's train will land, as a phrase that slots
 * into "This will land in …".
 *
 * @returns The landing phrase, or `null` when there is nothing to say (a
 *   non-mainline repo, or beta once betas are closed — see `landingWarning`).
 */
function landingPhrase(repo: string, schedule: ReleaseSchedule): string | null {
    const train = trainForRepo(repo);
    const stage = cycleStage(schedule);

    if (train === "beta") {
        return stage === "beta-shipping" ? `Firefox ${schedule.beta.version}` : null;
    }

    if (train === "release") {
        switch (stage) {
            case "beta-shipping":
                return `the next Firefox ${schedule.release.version} dot release`;
            case "rc-shipping":
                return `Firefox ${schedule.beta.version}.0 (major release)`;
            case "dot-releases-only":
                return `the next Firefox ${schedule.beta.version} dot release`;
            default: {
                // Exhaustiveness check: adding a `CycleStage` makes this a compile error.
                const unhandled: never = stage;
                return unhandled;
            }
        }
    }

    return null;
}

/** Warn when beta is selected after betas are closed, since it will not land. */
function landingWarning(repo: string, schedule: ReleaseSchedule): string | null {
    if (trainForRepo(repo) === "beta" && cycleStage(schedule) !== "beta-shipping") {
        const version = schedule.beta.version;
        return `No betas remaining for Firefox ${version}; select release to land this in Firefox ${version}.`;
    }
    return null;
}

/** Join phrases into a natural-language list (`a`, `a and b`, `a, b, and c`). */
function joinWithAnd(items: string[]): string {
    if (items.length <= 1) {
        return items.join("");
    }

    if (items.length === 2) {
        return `${items[0]} and ${items[1]}`;
    }

    const last = items[items.length - 1];
    return `${items.slice(0, -1).join(", ")}, and ${last}`;
}
