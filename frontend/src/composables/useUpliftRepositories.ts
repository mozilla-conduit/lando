import { ref, onMounted, onUnmounted, type Ref } from "vue";

// Bridges the Vue widget to the server-rendered "Uplift repositories"
// checkboxes. Those native inputs remain the source of truth for the Django
// form submission; this composable reads their state and toggles them so the
// form keeps working with JavaScript disabled or if the guidance fetch fails.
export interface UpliftRepositories {
  checkedRepos: Ref<string[]>;
  applyManaged(reposToCheck: string[], managed: string[]): void;
  setFieldVisible(visible: boolean): void;
}

export function useUpliftRepositories(
  fieldSelector = "[data-uplift-repositories]",
): UpliftRepositories {
  const fieldElement = document.querySelector<HTMLElement>(fieldSelector);
  const checkedRepos = ref<string[]>([]);

  function repoInputs(): HTMLInputElement[] {
    if (!fieldElement) {
      return [];
    }
    return Array.from(
      fieldElement.querySelectorAll<HTMLInputElement>(
        'input[name="repositories"]',
      ),
    );
  }

  function syncCheckedRepos(): void {
    checkedRepos.value = repoInputs()
      .filter((input) => input.checked)
      .map((input) => input.value);
  }

  // Tick the recommended repositories and clear any managed repositories that
  // are no longer recommended, leaving unmanaged ones (e.g. ESR) untouched.
  function applyManaged(reposToCheck: string[], managed: string[]): void {
    repoInputs().forEach((input) => {
      if (!managed.includes(input.value)) {
        return;
      }
      const shouldCheck = reposToCheck.includes(input.value);
      if (input.checked !== shouldCheck) {
        input.checked = shouldCheck;
        input.dispatchEvent(new Event("change", { bubbles: true }));
      }
    });
    syncCheckedRepos();
  }

  function setFieldVisible(visible: boolean): void {
    if (fieldElement) {
      fieldElement.style.display = visible ? "" : "none";
    }
  }

  onMounted(() => {
    repoInputs().forEach((input) => {
      input.addEventListener("change", syncCheckedRepos);
    });
    syncCheckedRepos();
  });

  onUnmounted(() => {
    repoInputs().forEach((input) => {
      input.removeEventListener("change", syncCheckedRepos);
    });
  });

  return { checkedRepos, applyManaged, setFieldVisible };
}
