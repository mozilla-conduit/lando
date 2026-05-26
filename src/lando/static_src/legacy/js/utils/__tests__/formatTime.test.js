"use strict";

require("../formatTime");

describe("$.fn.formatTime", () => {
  beforeEach(() => {
    // Pin "now" to midnight UTC on January 1, 2026 so relative-time output
    // is deterministic. The `TZ=UTC` env var (set in the `test` npm script)
    // makes `toLocaleString` output deterministic across environments.
    jest.useFakeTimers().setSystemTime(new Date("2026-01-01T00:00:00Z"));
  });

  afterEach(() => {
    jest.useRealTimers();
  });

  test("renders 'yesterday' for a timestamp from the prior day", () => {
    document.body.innerHTML =
      '<time data-timestamp="2025-12-31 00:00:00.000000+00:00"></time>';

    $("time[data-timestamp]").formatTime();

    expect($("time[data-timestamp]").text()).toBe(
      "Wed, December 31, 2025 at 12:00 AM UTC (yesterday)",
    );
  });

  test("renders 'N years ago' for a timestamp years in the past", () => {
    document.body.innerHTML =
      '<time data-timestamp="2020-01-01 00:00:00.000000+00:00"></time>';

    $("time[data-timestamp]").formatTime();

    expect($("time[data-timestamp]").text()).toBe(
      "Wed, January 1, 2020 at 12:00 AM UTC (6 years ago)",
    );
  });

  test("processes every matched element", () => {
    document.body.innerHTML = `
      <time data-timestamp="2025-12-31 00:00:00.000000+00:00"></time>
      <time data-timestamp="2020-01-01 00:00:00.000000+00:00"></time>
    `;

    $("time[data-timestamp]").formatTime();

    const renderedTexts = $("time[data-timestamp]")
      .map((_, element) => $(element).text())
      .get();
    expect(renderedTexts).toEqual([
      "Wed, December 31, 2025 at 12:00 AM UTC (yesterday)",
      "Wed, January 1, 2020 at 12:00 AM UTC (6 years ago)",
    ]);
  });
});
