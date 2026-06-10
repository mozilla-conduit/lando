import { describe, it, expect, vi, afterEach } from "vitest";
import { mount, flushPromises } from "@vue/test-utils";
import TrainSelector from "./TrainSelector.vue";
import type { ReleaseSchedule } from "../trainGuidance";

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
    <div data-uplift-repositories>
      <label><input type="checkbox" name="repositories" value="firefox-beta"> firefox-beta</label>
      <label><input type="checkbox" name="repositories" value="firefox-release"> firefox-release</label>
      <label><input type="checkbox" name="repositories" value="firefox-esr128"> firefox-esr128</label>
    </div>
  `;
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
    await flushPromises();

    expect(
      repositoriesField().style.display,
      "Version mode should hide the native repositories field.",
    ).toBe("none");

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
    await flushPromises();

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
      wrapper.text(),
      "The recommendation note should describe where the patch lands.",
    ).toContain("This will land in Firefox 152.");
  });

  it("checks both branches when the release version is selected", async () => {
    renderRepositoriesField();
    stubFetch(BETA_SHIPPING);

    const wrapper = mount(TrainSelector, { props: { apiUrl: "/api/train" } });
    await flushPromises();

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
  });

  it("reveals the field and hints when manually selecting a repository", async () => {
    renderRepositoriesField();
    stubFetch(BETA_SHIPPING);

    const wrapper = mount(TrainSelector, { props: { apiUrl: "/api/train" } });
    await flushPromises();

    await wrapper.find('input[value="manual"]').setValue();
    await flushPromises();

    expect(
      repositoriesField().style.display,
      "Manual mode should reveal the native repositories field.",
    ).toBe("");

    const release = repoCheckbox("firefox-release");
    release.checked = true;
    release.dispatchEvent(new Event("change", { bubbles: true }));
    await flushPromises();

    expect(
      wrapper.text(),
      "Selecting release during beta-shipping should hint the next dot release.",
    ).toContain("This will land in the next Firefox 151 dot release.");
  });

  it("falls back to manual mode when the guidance request fails", async () => {
    renderRepositoriesField();
    vi.stubGlobal(
      "fetch",
      vi.fn().mockRejectedValue(new Error("network down")),
    );
    vi.spyOn(console, "error").mockImplementation(() => {});

    const wrapper = mount(TrainSelector, { props: { apiUrl: "/api/train" } });
    await flushPromises();

    expect(
      repositoriesField().style.display,
      "A failed fetch should leave the native field visible.",
    ).toBe("");
    expect(
      wrapper.text(),
      "A failed fetch should explain that manual selection is needed.",
    ).toContain("Could not load release-train guidance");
  });
});
