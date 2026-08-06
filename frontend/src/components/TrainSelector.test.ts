import { describe, it, expect, vi, afterEach } from "vitest";
import { mount, flushPromises } from "@vue/test-utils";
import TrainSelector from "@/components/TrainSelector.vue";
import type { ReleaseSchedule } from "@/trainGuidance";

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

// Render the server-side repositories field the widget reaches out to. The
// composable finds it via `document`, independent of where the widget mounts.
// Deployments only offer the repositories that require approval, so the
// checkboxes are configurable.
function renderRepositoriesField(
    repos = ["firefox-beta", "firefox-release", "firefox-esr128"],
): void {
    const checkboxes = repos
        .map(
            (repo) =>
                `<label><input type="checkbox" name="repositories" value="${repo}"> ${repo}</label>`,
        )
        .join("\n");

    document.body.innerHTML = `
    <button class="uplift-request-open">Request Uplift</button>
    <input type="hidden" id="id_target_selection_method" name="target_selection_method">
    <div data-uplift-repositories>${checkboxes}</div>
    <div id="uplift-train-messages"></div>
  `;
}

function selectionMethod(): string {
    return document.querySelector<HTMLInputElement>("#id_target_selection_method")!
        .value;
}

// The widget fetches its schedule when the "Request Uplift" button is clicked,
// so tests open the modal before asserting on the loaded state.
async function openModal(): Promise<void> {
    document.querySelector<HTMLButtonElement>(".uplift-request-open")!.click();
    await flushPromises();
}

// The widget teleports its guidance messages to this anchor, so assertions read
// from the document rather than the component wrapper.
function messagesText(): string {
    return document.querySelector("#uplift-train-messages")?.textContent ?? "";
}

function repoCheckbox(value: string): HTMLInputElement {
    return document.querySelector<HTMLInputElement>(
        `input[name="repositories"][value="${value}"]`,
    )!;
}

// Set the checkboxes to exactly the given repositories, as a user clicking them
// would, so the widget observes the resulting `change` events.
async function checkRepos(...values: string[]): Promise<void> {
    document
        .querySelectorAll<HTMLInputElement>('input[name="repositories"]')
        .forEach((checkbox) => {
            const shouldCheck = values.includes(checkbox.value);
            if (checkbox.checked !== shouldCheck) {
                checkbox.checked = shouldCheck;
                checkbox.dispatchEvent(new Event("change", { bubbles: true }));
            }
        });

    await flushPromises();
}

function repositoriesField(): HTMLElement {
    return document.querySelector<HTMLElement>("[data-uplift-repositories]")!;
}

function stubFetch(data: unknown, ok = true): void {
    vi.stubGlobal(
        "fetch",
        vi.fn().mockResolvedValue({
            ok,
            status: ok ? 200 : 500,
            json: async () => data,
        }),
    );
}

afterEach(() => {
    vi.restoreAllMocks();
    document.body.innerHTML = "";
});

describe("TrainSelector", () => {
    it("shows the version dropdown alongside the train checkboxes", async () => {
        renderRepositoriesField();
        stubFetch(BETA_SHIPPING);

        const wrapper = mount(TrainSelector, { props: { apiUrl: "/api/train" } });
        await openModal();

        expect(
            repositoriesField().classList.contains("is-hidden"),
            "The train checkboxes should stay visible next to the version dropdown.",
        ).toBe(false);

        const options = wrapper.findAll("option").map((option) => option.text());
        expect(
            options,
            "The version dropdown should offer the beta and release versions.",
        ).toEqual(["Choose a version…", "Firefox 152", "Firefox 151"]);
    });

    it("checks the beta repository when the beta version is selected", async () => {
        renderRepositoriesField();
        stubFetch(BETA_SHIPPING);

        const wrapper = mount(TrainSelector, { props: { apiUrl: "/api/train" } });
        await openModal();

        await wrapper.find("select").setValue(152);
        await flushPromises();

        expect(
            repoCheckbox("firefox-beta").checked,
            "Selecting Firefox 152 during beta-shipping should check beta.",
        ).toBe(true);
        expect(
            repoCheckbox("firefox-release").checked,
            "Release should not be checked for the beta version.",
        ).toBe(false);
        expect(
            messagesText(),
            "The recommendation note should describe where the patch lands.",
        ).toContain("This will land in Firefox 152.");
        expect(
            messagesText(),
            "The summary should name the selected uplift train.",
        ).toContain("Selected the Beta uplift train.");
    });

    it("checks both branches when the release version is selected", async () => {
        renderRepositoriesField();
        stubFetch(BETA_SHIPPING);

        const wrapper = mount(TrainSelector, { props: { apiUrl: "/api/train" } });
        await openModal();

        await wrapper.find("select").setValue(151);
        await flushPromises();

        expect(
            repoCheckbox("firefox-beta").checked &&
                repoCheckbox("firefox-release").checked,
            "Selecting the release version should check both beta and release.",
        ).toBe(true);
        expect(
            repoCheckbox("firefox-esr128").checked,
            "Unmanaged ESR repositories should be left untouched.",
        ).toBe(false);
        expect(
            messagesText(),
            "The summary should name both selected uplift trains.",
        ).toContain("Selected the Release and Beta uplift trains.");
        expect(
            messagesText(),
            "The version summary should use the specific dot-release wording.",
        ).toContain("the next Firefox 151 dot release");
    });

    it("combines manually selected trains into a single landing sentence", async () => {
        renderRepositoriesField();
        stubFetch(BETA_SHIPPING);

        mount(TrainSelector, { props: { apiUrl: "/api/train" } });
        await openModal();

        await checkRepos("firefox-beta", "firefox-release");

        expect(
            messagesText(),
            "Both selected trains should be described in one sentence.",
        ).toContain(
            "This will land in Firefox 152 and the next Firefox 151 dot release.",
        );
        expect(
            document.querySelectorAll("#uplift-train-messages p"),
            "Manually selected trains should render a single combined line.",
        ).toHaveLength(1);
    });

    it("records a manual selection until a version is chosen", async () => {
        renderRepositoriesField();
        stubFetch(BETA_SHIPPING);

        const wrapper = mount(TrainSelector, { props: { apiUrl: "/api/train" } });
        await openModal();

        expect(
            selectionMethod(),
            "Checking trains without using the dropdown is a manual selection.",
        ).toBe("widget_manual");

        await wrapper.find("select").setValue(152);
        await flushPromises();

        expect(
            selectionMethod(),
            "Choosing a version should record a widget-version selection.",
        ).toBe("widget_version");
    });

    it("keeps the version attribution when the recommendation is overridden", async () => {
        renderRepositoriesField();
        stubFetch(BETA_SHIPPING);

        const wrapper = mount(TrainSelector, { props: { apiUrl: "/api/train" } });
        await openModal();

        await wrapper.find("select").setValue(152);
        await flushPromises();

        await checkRepos("firefox-beta", "firefox-release");

        expect(
            selectionMethod(),
            "Adjusting the checkboxes afterwards still counts as using the dropdown.",
        ).toBe("widget_version");
        expect(
            messagesText(),
            "An overridden recommendation should drop the version summary.",
        ).not.toContain("Selected the");

        await checkRepos("firefox-beta");

        expect(
            messagesText(),
            "Restoring the recommended trains should bring the summary back.",
        ).toContain("Selected the Beta uplift train.");
    });

    it("records the version even when no train checkbox matches it", async () => {
        renderRepositoriesField(["firefox-esr128"]);
        stubFetch(BETA_SHIPPING);

        const wrapper = mount(TrainSelector, { props: { apiUrl: "/api/train" } });
        await openModal();

        await wrapper.find("select").setValue(152);
        await flushPromises();

        expect(
            selectionMethod(),
            "Attribution follows the dropdown, not which checkboxes exist.",
        ).toBe("widget_version");
    });

    it("keeps the version selection when an unmanaged repository is added", async () => {
        renderRepositoriesField();
        stubFetch(BETA_SHIPPING);

        const wrapper = mount(TrainSelector, { props: { apiUrl: "/api/train" } });
        await openModal();

        await wrapper.find("select").setValue(152);
        await flushPromises();

        await checkRepos("firefox-beta", "firefox-esr128");

        expect(
            selectionMethod(),
            "An ESR branch is not managed by the widget, so the version still applies.",
        ).toBe("widget_version");
    });

    it("records a server-rendered selection when the guidance request fails", async () => {
        renderRepositoriesField();
        vi.stubGlobal("fetch", vi.fn().mockRejectedValue(new Error("network down")));
        vi.spyOn(console, "error").mockImplementation(() => {});

        mount(TrainSelector, { props: { apiUrl: "/api/train" } });
        await openModal();

        expect(
            selectionMethod(),
            "A failed fetch should record the server-rendered fallback.",
        ).toBe("server_rendered");
    });

    it("falls back to manual mode when the guidance request fails", async () => {
        renderRepositoriesField();
        vi.stubGlobal("fetch", vi.fn().mockRejectedValue(new Error("network down")));
        vi.spyOn(console, "error").mockImplementation(() => {});

        const wrapper = mount(TrainSelector, { props: { apiUrl: "/api/train" } });
        await openModal();

        expect(
            wrapper.text(),
            "A failed fetch should explain that manual selection is needed.",
        ).toContain("Could not load release-train guidance");
    });

    it("falls back to manual mode when the response shape is invalid", async () => {
        renderRepositoriesField();
        // A 200 response whose body is missing the expected fields.
        stubFetch({ unexpected: true });
        vi.spyOn(console, "error").mockImplementation(() => {});

        const wrapper = mount(TrainSelector, { props: { apiUrl: "/api/train" } });
        await openModal();

        expect(
            wrapper.text(),
            "A malformed response should explain that manual selection is needed.",
        ).toContain("Could not load release-train guidance");
    });
});
