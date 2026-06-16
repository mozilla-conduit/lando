import { ref, onMounted, onUnmounted, type Ref } from "vue";

/** The reactive bridge to the server-rendered uplift repository checkboxes. */
export interface UpliftRepositories {
    /** The names of the repositories whose checkboxes are currently checked. */
    checkedRepos: Ref<string[]>;

    /**
     * Tick the recommended repositories and clear any managed repositories that
     * are no longer recommended, leaving unmanaged ones (e.g. ESR) untouched.
     *
     * @param reposToCheck - The repositories that should end up checked.
     * @param managed - The repositories the widget is allowed to change.
     */
    applyManaged(reposToCheck: string[], managed: string[]): void;

    /** Show or hide the entire native checkbox field. */
    setFieldVisible(visible: boolean): void;
}

/**
 * Bridge the Vue widget to the server-rendered "Uplift repositories" checkboxes.
 * Those native inputs remain the source of truth for the Django form
 * submission; this composable reads their state and toggles them so the form
 * keeps working with JavaScript disabled or if the guidance fetch fails.
 *
 * @param fieldSelector - Selector for the element wrapping the checkboxes.
 */
export function useUpliftRepositories(
    fieldSelector = "[data-uplift-repositories]",
): UpliftRepositories {
    const fieldElement = document.querySelector<HTMLElement>(fieldSelector);
    const checkedRepos = ref<string[]>([]);

    /**
     * Return the native repository checkboxes, or an empty array when the field
     * is absent (e.g. a page without the uplift form).
     */
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

    /**
     * Refresh `checkedRepos` from the checkboxes' current state, since those
     * native inputs remain the source of truth for the form submission.
     */
    function syncCheckedRepos(): void {
        checkedRepos.value = repoInputs()
            .filter((input) => input.checked)
            .map((input) => input.value);
    }

    /**
     * Tick the recommended repositories and clear any managed repositories that
     * are no longer recommended, leaving unmanaged ones (e.g. ESR) untouched.
     */
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

    /**
     * Show or hide the entire native checkbox field, leaving the inputs in place
     * so they still submit with the form. Uses Bulma's `is-hidden` helper rather
     * than an inline style.
     */
    function setFieldVisible(visible: boolean): void {
        if (fieldElement) {
            fieldElement.classList.toggle("is-hidden", !visible);
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
