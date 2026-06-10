<script setup lang="ts">
import { ref, computed, watch, onMounted } from "vue";
import {
  versionChoices,
  resolveVersion,
  hintForRepo,
  type ReleaseSchedule,
  type GuidanceLevel,
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
      <div class="field">
        <label class="label"
          >How do you want to choose the uplift target?</label
        >
        <div class="control">
          <label class="radio">
            <input type="radio" value="version" v-model="mode" />
            Select by Firefox version
          </label>
          <label class="radio">
            <input type="radio" value="manual" v-model="mode" />
            Select repositories manually
          </label>
        </div>
      </div>
      <div v-if="mode === 'version'" class="field">
        <label class="label">Target Firefox version</label>
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
        <p
          v-if="recommendation"
          class="help"
          :class="helpClass(recommendation.level)"
        >
          {{ recommendation.note }}
        </p>
      </div>
      <div v-else-if="activeHints.length" class="field">
        <p
          v-for="hint in activeHints"
          :key="hint.repo"
          class="help"
          :class="helpClass(hint.level)"
        >
          {{ hint.message }}
        </p>
      </div>
    </template>
  </div>
</template>
