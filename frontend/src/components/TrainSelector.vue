<script setup lang="ts">
import { ref, computed, watch, onMounted } from "vue";
import {
  versionChoices,
  resolveVersion,
  hintForRepo,
  trainForRepo,
  type ReleaseSchedule,
  type GuidanceLevel,
  type Train,
} from "../trainGuidance";
import { useUpliftRepositories } from "../composables/useUpliftRepositories";

const props = withDefaults(
  defineProps<{ apiUrl: string; managedRepos?: string[] }>(),
  { managedRepos: () => ["firefox-beta", "firefox-release"] },
);

const loading = ref(true);
const error = ref(false);
const mode = ref<"version" | "manual">("version");
const schedule = ref<ReleaseSchedule | null>(null);
const selectedVersion = ref<number | null>(null);

const repositories = useUpliftRepositories();

const choices = computed(() =>
  schedule.value ? versionChoices(schedule.value) : [],
);

const recommendation = computed(() =>
  selectedVersion.value !== null && schedule.value
    ? resolveVersion(selectedVersion.value, schedule.value)
    : null,
);

// Name the uplift train(s) the chosen version resolved to, so it is clear that
// selecting a version also selects beta, release, or both.
const selectionSummary = computed(() => {
  const current = recommendation.value;
  if (!current) {
    return "";
  }
  const labels = current.repos
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

// A single informational line for the version tab, combining which train(s)
// were selected with where the patch will land.
const versionMessage = computed(() => {
  const current = recommendation.value;
  if (!current) {
    return "";
  }
  return [selectionSummary.value, current.note].filter(Boolean).join(" ");
});

// Guidance for the manually-selected repositories, omitting any without a
// train-specific hint (e.g. ESR).
const activeHints = computed(() => {
  const currentSchedule = schedule.value;
  if (!currentSchedule) {
    return [];
  }
  return repositories.checkedRepos.value
    .map((repo) => {
      const hint = hintForRepo(repo, currentSchedule);
      return hint ? { repo, ...hint } : null;
    })
    .filter((hint) => hint !== null);
});

// The native checkbox field is shown in manual mode, and whenever the guidance
// is unavailable so the form remains usable.
const nativeFieldVisible = computed(
  () => error.value || mode.value === "manual",
);

watch(nativeFieldVisible, (visible) => repositories.setFieldVisible(visible), {
  immediate: true,
});

// Reapply the recommendation whenever it changes or the user re-enters version
// mode, so the checkboxes always reflect the chosen version.
watch([mode, recommendation], () => {
  if (mode.value === "version" && recommendation.value) {
    repositories.applyManaged(recommendation.value.repos, props.managedRepos);
  }
});

async function loadSchedule(): Promise<void> {
  try {
    const response = await fetch(props.apiUrl, {
      headers: { Accept: "application/json" },
    });
    if (!response.ok) {
      throw new Error(`Unexpected response status ${response.status}.`);
    }
    schedule.value = (await response.json()) as ReleaseSchedule;
  } catch (caught) {
    console.error("Could not load uplift train guidance.", caught);
    error.value = true;
    mode.value = "manual";
  } finally {
    loading.value = false;
  }
}

onMounted(loadSchedule);

function helpClass(level: GuidanceLevel): string {
  return level === "warning" ? "is-warning" : "is-info";
}
</script>

<template>
  <div class="block">
    <p v-if="loading" class="help is-info">Loading release schedule…</p>
    <p v-else-if="error" class="help is-warning">
      Could not load release-train guidance. Select repositories manually below.
    </p>
    <template v-else>
      <div class="tabs">
        <ul>
          <li :class="{ 'is-active': mode === 'version' }">
            <a @click="mode = 'version'">Select Firefox Version</a>
          </li>
          <li :class="{ 'is-active': mode === 'manual' }">
            <a @click="mode = 'manual'">Select Uplift Train</a>
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
    <template v-if="!loading && !error && mode === 'version'">
      <p v-if="versionMessage" class="help is-info">
        {{ versionMessage }}
      </p>
    </template>
    <template v-else-if="!loading && !error">
      <p
        v-for="hint in activeHints"
        :key="hint.repo"
        class="help"
        :class="helpClass(hint.level)"
      >
        {{ hint.message }}
      </p>
    </template>
  </Teleport>
</template>
