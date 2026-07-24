import { formatDate, formatDateTime } from "../datetime";

const TIMESTAMP = "2026-07-23T14:05:09Z";

describe("formatDate", () => {
  test("writes the day first in Spanish and the month first in English", () => {
    // LR-007's whole point: "07/09" is two different days depending on who reads it, so the app's
    // locale — not the browser's — has to decide.
    expect(formatDate(TIMESTAMP, "es")).toBe("23/7/2026");
    expect(formatDate(TIMESTAMP, "en")).toBe("7/23/2026");
  });

  test("the two locales genuinely differ", () => {
    expect(formatDate(TIMESTAMP, "es")).not.toBe(formatDate(TIMESTAMP, "en"));
  });
});

describe("formatDateTime", () => {
  test("includes a time and differs by locale", () => {
    const en = formatDateTime(TIMESTAMP, "en");
    const es = formatDateTime(TIMESTAMP, "es");

    expect(en).toMatch(/\d/);
    expect(es).toMatch(/\d/);
    expect(es).not.toBe(en);
  });

  test("English uses a 12-hour clock and Spanish a 24-hour one", () => {
    expect(formatDateTime(TIMESTAMP, "en")).toMatch(/AM|PM/i);
    expect(formatDateTime(TIMESTAMP, "es")).not.toMatch(/AM|PM/i);
  });
});

describe("values that are not really dates", () => {
  // The API sends `delivery_date` as a free-form string like "19/07/26"; mangling it into
  // "Invalid Date" would be worse than showing what arrived.
  test.each([
    ["an unparseable string", "not-a-date"],
    ["an empty string", ""],
  ])("passes through %s unchanged", (_label, value) => {
    expect(formatDate(value, "es")).toBe(value);
    expect(formatDateTime(value, "es")).toBe(value);
  });

  test.each([
    ["null", null],
    ["undefined", undefined],
  ])("renders %s as an empty string", (_label, value) => {
    expect(formatDate(value, "es")).toBe("");
    expect(formatDateTime(value, "es")).toBe("");
  });
});
