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
function renderRepositoriesField(): void {
  document.body.innerHTML = `
    <button class="uplift-request-open">Request Uplift</button>
    <input type="hidden" id="id_target_selection_method" name="target_selection_method">
    <div data-uplift-repositories>
      <label><input type="checkbox" name="repositories" value="firefox-beta"> firefox-beta</label>
      <label><input type="checkbox" name="repositories" value="firefox-release"> firefox-release</label>
      <label><input type="checkbox" name="repositories" value="firefox-esr128"> firefox-esr128</label>
    </div>
    <div id="uplift-train-messages"></div>
  `;
}

function selectionMethod(): string {
  return document.querySelector<HTMLInputElement>(
    "#id_target_selection_method",
  )!.value;
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
  it("hides the manual field and offers the selectable versions after loading", async () => {
    renderRepositoriesField();
    stubFetch(BETA_SHIPPING);

    const wrapper = mount(TrainSelector, { props: { apiUrl: "/api/train" } });
    await openModal();

    expect(
      repositoriesField().classList.contains("is-hidden"),
      "Version mode should hide the server-rendered repositories field.",
    ).toBe(true);

    const options = wrapper.findAll("option").map((option) => option.text());
    expect(
      options,
      "The version dropdown should offer the beta and release versions.",
    ).toEqual(["Choose a version…", "Firefox 152", "Firefox 151"]);
  });

  it("marks the active tab with aria-selected", async () => {
    renderRepositoriesField();
    stubFetch(BETA_SHIPPING);

    const wrapper = mount(TrainSelector, { props: { apiUrl: "/api/train" } });
    await openModal();

    const tabs = wrapper.findAll('[role="tab"]');
    expect(
      tabs[0].attributes("aria-selected"),
      "The version tab starts selected.",
    ).toBe("true");
    expect(
      tabs[1].attributes("aria-selected"),
      "The train tab starts unselected.",
    ).toBe("false");

    await tabs[1].trigger("click");
    expect(
      tabs[1].attributes("aria-selected"),
      "Clicking the train tab selects it.",
    ).toBe("true");
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

    const wrapper = mount(TrainSelector, { props: { apiUrl: "/api/train" } });
    await openModal();

    // The second tab ("Select Uplift Train") switches to manual mode.
    await wrapper.findAll(".tabs li a")[1].trigger("click");
    await flushPromises();

    expect(
      repositoriesField().classList.contains("is-hidden"),
      "The train tab should reveal the server-rendered repositories field.",
    ).toBe(false);

    for (const value of ["firefox-beta", "firefox-release"]) {
      const checkbox = repoCheckbox(value);
      checkbox.checked = true;
      checkbox.dispatchEvent(new Event("change", { bubbles: true }));
    }
    await flushPromises();

    expect(
      messagesText(),
      "Both selected trains should be described in one sentence.",
    ).toContain(
      "This will land in Firefox 152 and the next Firefox 151 dot release.",
    );
    expect(
      document.querySelectorAll("#uplift-train-messages p"),
      "The train tab should render a single combined line.",
    ).toHaveLength(1);
  });

  it("records the selection method as the user moves between modes", async () => {
    renderRepositoriesField();
    stubFetch(BETA_SHIPPING);

    const wrapper = mount(TrainSelector, { props: { apiUrl: "/api/train" } });
    await openModal();

    expect(
      selectionMethod(),
      "The version tab should record a widget-version selection.",
    ).toBe("widget_version");

    await wrapper.findAll(".tabs li a")[1].trigger("click");
    await flushPromises();

    expect(
      selectionMethod(),
      "The train tab should record a widget-manual selection.",
    ).toBe("widget_manual");
  });

  it("records a server-rendered selection when the guidance request fails", async () => {
    renderRepositoriesField();
    vi.stubGlobal(
      "fetch",
      vi.fn().mockRejectedValue(new Error("network down")),
    );
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
    vi.stubGlobal(
      "fetch",
      vi.fn().mockRejectedValue(new Error("network down")),
    );
    vi.spyOn(console, "error").mockImplementation(() => {});

    const wrapper = mount(TrainSelector, { props: { apiUrl: "/api/train" } });
    await openModal();

    expect(
      repositoriesField().classList.contains("is-hidden"),
      "A failed fetch should leave the server-rendered field visible.",
    ).toBe(false);
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
      repositoriesField().classList.contains("is-hidden"),
      "A malformed response should leave the server-rendered field visible.",
    ).toBe(false);
    expect(
      wrapper.text(),
      "A malformed response should explain that manual selection is needed.",
    ).toContain("Could not load release-train guidance");
  });
});
