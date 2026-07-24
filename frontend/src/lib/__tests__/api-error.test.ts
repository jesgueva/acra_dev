import { errorDetailText } from "../api-error";

const FALLBACK = "Something went wrong.";

/** An axios-shaped error carrying `detail`. */
const withDetail = (detail: unknown) => ({ response: { data: { detail } } });

describe("errorDetailText", () => {
  test("returns a string detail unchanged", () => {
    expect(errorDetailText(withDetail("Insufficient stock for 'Steel Rod'."), FALLBACK)).toBe(
      "Insufficient stock for 'Steel Rod'.",
    );
  });

  test("summarises FastAPI's 422 validation array instead of returning objects", () => {
    // The regression: this array used to be assigned straight into React state and rendered,
    // crashing the component with React error #31 rather than telling the user what was wrong.
    const detail = [
      {
        type: "greater_than",
        loc: ["body", "quantity_required"],
        msg: "Input should be greater than 0",
        input: 0,
        ctx: { gt: 0 },
      },
    ];

    const text = errorDetailText(withDetail(detail), FALLBACK);

    expect(typeof text).toBe("string");
    expect(text).toBe("quantity_required: Input should be greater than 0");
  });

  test("joins multiple validation errors", () => {
    const detail = [
      { loc: ["body", "product"], msg: "Field required" },
      { loc: ["body", "target_date"], msg: "Invalid date" },
    ];

    expect(errorDetailText(withDetail(detail), FALLBACK)).toBe(
      "product: Field required; target_date: Invalid date",
    );
  });

  test("omits the field prefix when there is nothing useful to name", () => {
    expect(errorDetailText(withDetail([{ loc: ["body"], msg: "Invalid payload" }]), FALLBACK)).toBe(
      "Invalid payload",
    );
  });

  test.each([
    ["no response", {}],
    ["no detail", { response: { data: {} } }],
    ["an empty string", withDetail("   ")],
    ["an empty array", withDetail([])],
    ["an unrecognised object", withDetail({ nope: true })],
    ["a non-object error", "boom"],
    ["null", null],
  ])("falls back when the error carries %s", (_label, err) => {
    expect(errorDetailText(err, FALLBACK)).toBe(FALLBACK);
  });
});
