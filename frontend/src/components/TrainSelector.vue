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

const props = withDefaults(
    defineProps<{ apiUrl: string; managedRepos?: RepoName[] }>(),
    { managedRepos: () => [TRAIN_REPOS.beta, TRAIN_REPOS.release] },
);

/** Current state of the API response retrieval. */
const status = ref<"loading" | "ready" | "error">("loading");

/** Current mode in the component. */
const mode = ref<"version" | "manual">("version");

/** Stored API response. */
const schedule = ref<ReleaseSchedule | null>(null);

/** Selected version in "version" mode. */
const selectedVersion = ref<number | null>(null);

/**
 * The "Request Uplift" button that opens the modal. The API request is deferred
 * until it is first clicked, rather than firing on every stack page load.
 */
let openButton: Element | null = null;

/** Django-forms uplift repository selection. */
const repositories = useUpliftRepositories();

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

/**
 * Name the uplift train(s) the chosen version resolved to, so it is clear that
 * selecting a version also selects beta, release, or both.
 */
const selectionSummary = computed(() => {
    const repos = selectedRepos.value;
    if (!repos) {
        return "";
    }

    const labels = repos
        .map((repo) => trainForRepo(repo))
        .filter((train): train is Train => train !== null)
        .map((train) => train.charAt(0).toUpperCase() + train.slice(1));

    if (labels.length === 0) {
        return "";
    }

    if (labels.length === 1) {
        return `Selected the ${labels[0]} uplift train.`;
    }

    const last = labels[labels.length - 1];
    return `Selected the ${labels.slice(0, -1).join(", ")} and ${last} uplift trains.`;
});

/**
 * A single informational line for the version tab, combining which train(s)
 * were selected with where the patch will land (the same landing description
 * the train tab shows).
 */
const versionMessage = computed(() => {
    const repos = selectedRepos.value;
    if (!repos || !schedule.value) {
        return "";
    }

    const { landing } = summarizeRepos(repos, schedule.value);
    return [selectionSummary.value, landing].filter(Boolean).join(" ");
});

/** Combined guidance for the manually-selected repositories. */
const manualGuidance = computed(() =>
    schedule.value
        ? summarizeRepos(repositories.checkedRepos.value, schedule.value)
        : { landing: "", warnings: [] },
);

/**
 * The native checkbox field is shown in manual mode, and whenever the guidance
 * is unavailable so the form remains usable.
 */
const nativeFieldVisible = computed(
    () => status.value === "error" || mode.value === "manual",
);

watch(nativeFieldVisible, (visible) => repositories.setFieldVisible(visible), {
    immediate: true,
});

// Reapply the recommendation whenever it changes or the user re-enters version
// mode, so the checkboxes always reflect the chosen version.
watch([mode, selectedRepos], () => {
    if (mode.value === "version" && selectedRepos.value) {
        repositories.applyManaged(selectedRepos.value, props.managedRepos);
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
        mode.value = "manual";
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
        <p v-if="status === 'loading'" class="help is-info">
            Loading release schedule…
        </p>
        <p v-else-if="status === 'error'" class="help is-warning">
            Could not load release-train guidance. Select repositories manually below.
        </p>
        <template v-else>
            <div class="tabs">
                <ul role="tablist" aria-label="Uplift target selection">
                    <li :class="{ 'is-active': mode === 'version' }">
                        <a
                            role="tab"
                            tabindex="0"
                            :aria-selected="mode === 'version'"
                            @click="mode = 'version'"
                            @keydown.enter.prevent="mode = 'version'"
                            @keydown.space.prevent="mode = 'version'"
                            >Select Firefox Version</a
                        >
                    </li>
                    <li :class="{ 'is-active': mode === 'manual' }">
                        <a
                            role="tab"
                            tabindex="0"
                            :aria-selected="mode === 'manual'"
                            @click="mode = 'manual'"
                            @keydown.enter.prevent="mode = 'manual'"
                            @keydown.space.prevent="mode = 'manual'"
                            >Select Uplift Train</a
                        >
                    </li>
                </ul>
            </div>
            <div v-if="mode === 'version'" class="field">
                <div class="control">
                    <div class="select">
                        <select v-model.number="selectedVersion">
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
            </div>
        </template>
    </div>

    <!-- Guidance messages render below the selection widget (see the
       `uplift-train-messages` anchor in `uplift-form.html`). -->
    <Teleport to="#uplift-train-messages">
        <template v-if="status === 'ready' && mode === 'version'">
            <p v-if="versionMessage" class="help is-info">
                {{ versionMessage }}
            </p>
        </template>
        <template v-else-if="status === 'ready'">
            <p v-if="manualGuidance.landing" class="help is-info">
                {{ manualGuidance.landing }}
            </p>
            <p
                v-for="warning in manualGuidance.warnings"
                :key="warning"
                class="help is-warning"
            >
                {{ warning }}
            </p>
        </template>
    </Teleport>
</template>
