<script setup lang="ts">
import { ref, computed, watch, onMounted, onUnmounted } from "vue";
import {
    versionChoices,
    resolveVersion,
    summarizeRepos,
    trainForRepo,
    releaseScheduleSchema,
    TRAIN_REPOS,
    type ReleaseSchedule,
    type RepoName,
    type Train,
} from "@/trainGuidance";
import { useUpliftRepositories } from "@/composables/useUpliftRepositories";
import {
    useTargetSelectionMethod,
    type TargetSelectionMethod,
} from "@/composables/useTargetSelectionMethod";

const props = withDefaults(
    defineProps<{ apiUrl: string; managedRepos?: RepoName[] }>(),
    { managedRepos: () => [TRAIN_REPOS.beta, TRAIN_REPOS.release] },
);

/** Current state of the API response retrieval. */
const status = ref<"loading" | "ready" | "error">("loading");

/** Stored API response. */
const schedule = ref<ReleaseSchedule | null>(null);

/** Firefox version selected in the dropdown, if any. */
const selectedVersion = ref<number | null>(null);

/**
 * The "Request Uplift" button that opens the modal. The API request is deferred
 * until it is first clicked, rather than firing on every stack page load.
 */
let openButton: Element | null = null;

/** Django-forms uplift repository selection. */
const repositories = useUpliftRepositories();

/** Hidden field recording how the uplift target was selected. */
const targetSelection = useTargetSelectionMethod();

const choices = computed(() => (schedule.value ? versionChoices(schedule.value) : []));

/**
 * The repositories a chosen version resolves to, used both to tick the
 * checkboxes and to describe where the patch will land.
 */
const selectedRepos = computed(() =>
    selectedVersion.value !== null && schedule.value
        ? resolveVersion(selectedVersion.value, schedule.value)
        : null,
);

/** Whether the widget is allowed to tick the given repository's checkbox. */
function isManaged(repo: string): boolean {
    return (props.managedRepos as readonly string[]).includes(repo);
}

/**
 * Whether the checked trains still match the ones the chosen version resolved
 * to, which decides whether the version summary still describes the selection.
 * Ticking an unmanaged repository (e.g. ESR) alongside the recommendation
 * leaves it in effect, while changing a managed checkbox overrides it.
 */
const versionSelectionApplied = computed(() => {
    const repos = selectedRepos.value;
    if (!repos) {
        return false;
    }

    const recommended = new Set(repos.filter(isManaged));
    const checked = repositories.checkedRepos.value.filter(isManaged);

    return (
        checked.length === recommended.size &&
        checked.every((repo) => recommended.has(repo))
    );
});

/**
 * Name the uplift train(s) the chosen version resolved to, so it is clear that
 * selecting a version also selects beta, release, or both.
 */
const selectionSummary = computed(() => {
    const repos = selectedRepos.value;
    if (!repos || !versionSelectionApplied.value) {
        return "";
    }

    // Turn the resolved repositories into capitalized train names (e.g.
    // `firefox-beta` becomes `Beta`), dropping any repo without a mainline train.
    const labels = repos
        .map((repo) => trainForRepo(repo))
        .filter((train): train is Train => train !== null)
        .map((train) => train.charAt(0).toUpperCase() + train.slice(1));

    if (labels.length === 0) {
        return "";
    }

    // Phrase the selected train(s) as a sentence: a single train reads "the Beta
    // uplift train", while several read "the Beta and Release uplift trains".
    if (labels.length === 1) {
        return `Selected the ${labels[0]} uplift train.`;
    }

    const last = labels[labels.length - 1];
    return `Selected the ${labels.slice(0, -1).join(", ")} and ${last} uplift trains.`;
});

/**
 * Guidance for the repositories that are currently checked, which are the
 * source of truth whether they were ticked by the version dropdown or by hand.
 */
const guidance = computed(() =>
    schedule.value
        ? summarizeRepos(repositories.checkedRepos.value, schedule.value)
        : { landing: "", warnings: [] },
);

/**
 * A single informational line combining which train(s) a chosen version
 * resolved to with where the patch will land.
 */
const landingMessage = computed(() =>
    [selectionSummary.value, guidance.value.landing].filter(Boolean).join(" "),
);

/** Status line shown while the guidance loads or after it fails; empty once ready. */
const statusMessage = computed(() => {
    if (status.value === "loading") {
        return "Loading release schedule…";
    }
    if (status.value === "error") {
        return "Could not load release-train guidance. Select repositories manually below.";
    }
    return "";
});

/**
 * How the target was selected, for attribution. Resolves to `server_rendered`
 * when the guidance fails (the user falls back to the raw checkboxes), and is
 * left unset while loading so the server default applies if the form is
 * submitted early. Touching the version dropdown counts as `widget_version`
 * for the rest of the submission, even if the checkboxes are adjusted after.
 */
const targetSelectionMethod = computed<TargetSelectionMethod | null>(() => {
    if (status.value === "error") {
        return "server_rendered";
    }
    if (status.value !== "ready") {
        return null;
    }
    return selectedVersion.value !== null ? "widget_version" : "widget_manual";
});

watch(
    targetSelectionMethod,
    (method) => {
        if (method) {
            targetSelection.setMethod(method);
        }
    },
    { immediate: true },
);

// Tick the recommended trains whenever the chosen version resolves to a new set
// of repositories.
watch(selectedRepos, (repos) => {
    if (repos) {
        repositories.applyManaged(repos, props.managedRepos);
    }
});

/** Fetch and validate the release-train guidance from the configured API. */
async function loadSchedule(): Promise<void> {
    try {
        const response = await fetch(props.apiUrl, {
            headers: { Accept: "application/json" },
        });

        if (!response.ok) {
            throw new Error(`Unexpected response status ${response.status}.`);
        }

        const result = releaseScheduleSchema.safeParse(await response.json());
        if (!result.success) {
            throw new Error(
                `Train guidance response had an unexpected shape: ${result.error.message}`,
            );
        }

        schedule.value = result.data;
        status.value = "ready";
    } catch (caught) {
        console.error("Could not load uplift train guidance.", caught);
        status.value = "error";
    }
}

// Fetch the schedule the first time the modal is opened, then leave it cached.
onMounted(() => {
    openButton = document.querySelector(".uplift-request-open");
    openButton?.addEventListener("click", loadSchedule, { once: true });
});

onUnmounted(() => {
    openButton?.removeEventListener("click", loadSchedule);
});
</script>

<template>
    <div class="block">
        <p
            v-if="statusMessage"
            class="help"
            :class="{
                'is-info': status === 'loading',
                'is-warning': status === 'error',
            }"
        >
            {{ statusMessage }}
        </p>
        <div v-else class="field">
            <label class="label is-small" for="uplift-version-select">
                Firefox version
            </label>
            <div class="control">
                <div class="select">
                    <select id="uplift-version-select" v-model.number="selectedVersion">
                        <option :value="null" disabled>Choose a version…</option>
                        <option
                            v-for="choice in choices"
                            :key="choice.version"
                            :value="choice.version"
                        >
                            Firefox {{ choice.version }}
                        </option>
                    </select>
                </div>
            </div>
            <p class="help">
                Choosing a version checks the matching uplift trains below. ESR branches
                are not covered by version selection and must be checked directly.
            </p>
        </div>
    </div>

    <!-- Guidance messages render below the selection widget (see the
       `uplift-train-messages` anchor in `uplift-form.html`). -->
    <Teleport to="#uplift-train-messages">
        <template v-if="status === 'ready'">
            <p v-if="landingMessage" class="help is-info">
                {{ landingMessage }}
            </p>
            <p
                v-for="warning in guidance.warnings"
                :key="warning"
                class="help is-warning"
            >
                {{ warning }}
            </p>
        </template>
    </Teleport>
</template>
