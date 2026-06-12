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

    // Return the native repository checkboxes, or an empty array when the
    // field is absent (e.g. a page without the uplift form).
    function repoInputs(): HTMLInputElement[] {
        if (!fieldElement) {
            // If we didn't find the uplift repos div, we have no
            // inputs to manage.
            return [];
        }

        return Array.from(
            fieldElement.querySelectorAll<HTMLInputElement>(
                'input[name="repositories"]',
            ),
        );
    }

    // Refresh `checkedRepos` from the checkboxes' current state, since those
    // native inputs remain the source of truth for the form submission.
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
                // Skip changing repos the widget doesn't manage.
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

    // Show or hide the entire native checkbox field, leaving the inputs in
    // place so they still submit with the form.
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
