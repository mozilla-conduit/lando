import { describe, it, expect, afterEach } from "vitest";
import { defineComponent } from "vue";
import { mount } from "@vue/test-utils";
import {
  useUpliftRepositories,
  type UpliftRepositories,
} from "./useUpliftRepositories";

const MANAGED = ["firefox-beta", "firefox-release"];

function renderRepositoriesField(releaseChecked = false): void {
  const releaseAttr = releaseChecked ? "checked" : "";
  document.body.innerHTML = `
    <div data-uplift-repositories>
      <label><input type="checkbox" name="repositories" value="firefox-beta"> firefox-beta</label>
      <label><input type="checkbox" name="repositories" value="firefox-release" ${releaseAttr}> firefox-release</label>
      <label><input type="checkbox" name="repositories" value="firefox-esr128"> firefox-esr128</label>
    </div>
  `;
}

// Run the composable inside a mounted component so its lifecycle hooks fire,
// returning its API for assertions.
function setupComposable(): UpliftRepositories {
  let api: UpliftRepositories | undefined;
  const Harness = defineComponent({
    setup() {
      api = useUpliftRepositories();
      return () => null;
    },
  });
  mount(Harness, { attachTo: document.body });
  return api!;
}

function repoCheckbox(value: string): HTMLInputElement {
  return document.querySelector<HTMLInputElement>(
    `input[name="repositories"][value="${value}"]`,
  )!;
}

afterEach(() => {
  document.body.innerHTML = "";
});

describe("useUpliftRepositories", () => {
  it("reads the initially checked repositories", () => {
    renderRepositoriesField(true);

    const repositories = setupComposable();

    expect(
      repositories.checkedRepos.value,
      "The initial state should reflect the pre-checked repositories.",
    ).toEqual(["firefox-release"]);
  });

  it("applies managed repositories without touching unmanaged ones", () => {
    renderRepositoriesField(true);

    const repositories = setupComposable();
    repositories.applyManaged(["firefox-beta"], MANAGED);

    expect(
      repoCheckbox("firefox-beta").checked,
      "A recommended managed repository should be checked.",
    ).toBe(true);
    expect(
      repoCheckbox("firefox-release").checked,
      "A managed repository not recommended should be unchecked.",
    ).toBe(false);
    expect(
      repositories.checkedRepos.value,
      "The reactive state should mirror the applied selection.",
    ).toEqual(["firefox-beta"]);
  });

  it("toggles the field visibility", () => {
    renderRepositoriesField();

    const repositories = setupComposable();
    repositories.setFieldVisible(false);

    const field = document.querySelector<HTMLElement>(
      "[data-uplift-repositories]",
    )!;
    expect(
      field.classList.contains("is-hidden"),
      "Hiding the field should add the `is-hidden` class.",
    ).toBe(true);

    repositories.setFieldVisible(true);
    expect(
      field.classList.contains("is-hidden"),
      "Showing the field should remove the `is-hidden` class.",
    ).toBe(false);
  });

  it("tracks manual changes to the native checkboxes", async () => {
    renderRepositoriesField();

    const repositories = setupComposable();
    const beta = repoCheckbox("firefox-beta");
    beta.checked = true;
    beta.dispatchEvent(new Event("change", { bubbles: true }));

    expect(
      repositories.checkedRepos.value,
      "A manual checkbox change should update the reactive state.",
    ).toEqual(["firefox-beta"]);
  });
});
