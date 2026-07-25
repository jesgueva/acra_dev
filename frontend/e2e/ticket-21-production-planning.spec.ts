import { test, expect, type APIRequestContext, type Page } from "@playwright/test";
import { USERS, API, login, apiToken, authHeaders, unique, failOnPageErrors } from "./helpers/auth";

/**
 * T21 Flow 8 — UC-005, Plan and Prioritize Daily Production (FR-015, FR-017, FR-021).
 *
 * The Production Supervisor's day: look at what is ready, set the order it runs in, put each job on
 * a line, and have the operators on those lines see the result.
 *
 * Two of the six steps have no UI. Step 3 (reorder by priority) has a `PriorityReorder` component
 * and a `PATCH /work-orders/{id}/sequence` endpoint, but **no page renders the component**, so the
 * only way to reach it is the API — which is what the sequence tests below drive, deliberately, so
 * the contract is pinned for whenever the control is wired up. Step 6's line scoping is likewise
 * asserted through a purpose-made operator, because both seeded operators have a null
 * `production_line` and therefore never exercise the filter.
 */

const LINE_A = "Line 1";
const LINE_B = "Line 2";

/** A seeded product, so the required material line names something the allocator could resolve. */
const MATERIAL = "Steel Rod";

/** Create a work order straight from the API — the UI path is Flow 3's subject, not this one. */
async function createWorkOrder(
  request: APIRequestContext,
  token: string,
  product: string,
): Promise<{ id: number; wo_number: string }> {
  const res = await request.post(`${API}/api/v1/work-orders`, {
    headers: authHeaders(token),
    data: {
      product,
      quantity_required: 2,
      priority: "medium",
      target_date: "2026-12-31",
      // `materials` is min_length=1 — a work order with nothing to consume is rejected.
      materials: [{ material_type: MATERIAL, quantity_required: 1 }],
    },
  });
  expect(res.status(), "work-order creation").toBe(201);
  return await res.json();
}

async function assign(
  request: APIRequestContext,
  token: string,
  woId: number,
  line: string,
) {
  return request.patch(`${API}/api/v1/work-orders/${woId}/assign`, {
    headers: authHeaders(token),
    data: { production_line: line },
  });
}

async function setStatus(
  request: APIRequestContext,
  token: string,
  woId: number,
  status: string,
) {
  return request.patch(`${API}/api/v1/work-orders/${woId}/status`, {
    headers: authHeaders(token),
    data: { status },
  });
}

/** Open a work order's detail sheet from the list. */
async function openDetail(page: Page, woId: number) {
  await page.getByTestId(`wo-row-${woId}`).click();
  await expect(page.getByRole("dialog")).toBeVisible();
}

test.describe("T21 Flow 8 — plan and prioritize daily production", () => {
  test.beforeEach(({ page }) => failOnPageErrors(page));

  test("the supervisor sees the board grouped by status (step 2, FR-017)", async ({
    page,
    request,
  }) => {
    // Something in each of the groups the supervisor plans against, so the assertion is not
    // satisfied by an empty board that happens to render the headings.
    const token = await apiToken(request, USERS.supervisor);
    const wo = await createWorkOrder(request, token, unique("E2E Plan "));

    await login(page, USERS.supervisor);
    await page.goto("/en/work-orders");

    for (const label of ["Created", "Materials Allocated", "In Production", "Completed"]) {
      await expect(
        page.locator("section", { has: page.getByRole("button", { name: new RegExp(label) }) }),
        `${label} group`,
      ).toHaveCount(1);
    }

    // The new work order is genuinely on the board, under its own status.
    await expect(page.getByTestId(`wo-row-${wo.id}`)).toBeVisible();
  });

  test("the supervisor assigns a line through the UI and can reassign it (step 4, A1)", async ({
    page,
    request,
  }) => {
    const token = await apiToken(request, USERS.supervisor);
    const wo = await createWorkOrder(request, token, unique("E2E Assign "));

    const currentLine = async () => {
      const res = await request.get(`${API}/api/v1/work-orders/${wo.id}`, {
        headers: authHeaders(token),
      });
      return (await res.json()).production_line as string | null;
    };
    expect(await currentLine(), "a new work order starts unassigned").toBeNull();

    await login(page, USERS.supervisor);
    await page.goto("/en/work-orders");

    // ── step 4: put it on a line ────────────────────────────────────────────
    await openDetail(page, wo.id);
    await page.getByRole("combobox").last().click();
    await page.getByRole("option", { name: LINE_A, exact: true }).click();
    await expect.poll(currentLine, { message: "assignment must persist" }).toBe(LINE_A);

    // ── A1: the line goes down, so move the job ─────────────────────────────
    await page.reload();
    await openDetail(page, wo.id);
    await page.getByRole("combobox").last().click();
    await page.getByRole("option", { name: LINE_B, exact: true }).click();
    await expect.poll(currentLine, { message: "reassignment must persist" }).toBe(LINE_B);
  });

  test("E2 — a busy line warns before it takes another job", async ({ page, request }) => {
    const token = await apiToken(request, USERS.supervisor);
    const busyLine = `Line 3`;

    // The backend warns once a line already carries 3+ *active* work orders, so the warning needs
    // three of them parked there before the fourth assignment is made.
    for (let i = 0; i < 3; i++) {
      const filler = await createWorkOrder(request, token, unique(`E2E Busy ${i} `));
      expect((await assign(request, token, filler.id, busyLine)).status()).toBe(200);
    }

    const wo = await createWorkOrder(request, token, unique("E2E Overflow "));

    await login(page, USERS.supervisor);
    await page.goto("/en/work-orders");
    await openDetail(page, wo.id);

    await page.getByRole("combobox").last().click();
    await page.getByRole("option", { name: busyLine, exact: true }).click();

    // The supervisor is warned but not blocked — UC-005 E2 lets them confirm or pick another line.
    const warning = page.getByTestId("capacity-warning");
    await expect(warning).toBeVisible();
    await expect(warning).toContainText(busyLine);

    const res = await request.get(`${API}/api/v1/work-orders/${wo.id}`, {
      headers: authHeaders(token),
    });
    expect((await res.json()).production_line, "a warning must not undo the assignment").toBe(
      busyLine,
    );
  });

  test("step 3 — the day's running order is set by display_sequence", async ({ request }) => {
    // API-only on purpose: `PriorityReorder` exists but no page mounts it, so this pins the
    // contract the control will use rather than pretending the UI is there.
    const token = await apiToken(request, USERS.supervisor);
    const first = await createWorkOrder(request, token, unique("E2E Seq A "));
    const second = await createWorkOrder(request, token, unique("E2E Seq B "));

    for (const [wo, seq] of [
      [first, 20],
      [second, 10],
    ] as const) {
      const res = await request.patch(`${API}/api/v1/work-orders/${wo.id}/sequence`, {
        headers: authHeaders(token),
        data: { display_sequence: seq },
      });
      expect(res.status(), `sequencing ${wo.wo_number}`).toBe(200);
      expect((await res.json()).display_sequence).toBe(seq);
    }

    // The one the supervisor pulled forward now sorts ahead of the one created before it.
    const read = async (id: number) => {
      const res = await request.get(`${API}/api/v1/work-orders/${id}`, {
        headers: authHeaders(token),
      });
      return (await res.json()).display_sequence as number;
    };
    expect(await read(second.id)).toBeLessThan(await read(first.id));

    // A negative position is not a running order.
    const bad = await request.patch(`${API}/api/v1/work-orders/${first.id}/sequence`, {
      headers: authHeaders(token),
      data: { display_sequence: -1 },
    });
    expect(bad.status()).toBe(422);
  });

  test("step 6 — an operator sees their own line's work and no one else's", async ({ request }) => {
    const adminToken = await apiToken(request, USERS.admin);
    const supervisorToken = await apiToken(request, USERS.supervisor);

    // Both seeded operators have a null production_line, which makes the scoping filter a no-op.
    // This flow is about the line, so it needs an operator who is actually on one.
    const rolesRes = await request.get(`${API}/api/v1/roles`, {
      headers: authHeaders(adminToken),
    });
    expect(rolesRes.status()).toBe(200);
    const roles = (await rolesRes.json()).results as { id: number; role_name: string }[];
    const operatorRole = roles.find((r) => r.role_name === "machine_operator")!;
    expect(operatorRole, "the machine_operator role must be seeded").toBeTruthy();

    const username = unique("e2e_op_");
    const password = "temp12345";
    const createRes = await request.post(`${API}/api/v1/users`, {
      headers: authHeaders(adminToken),
      data: {
        username,
        full_name: "E2E Line Operator",
        password,
        production_line: LINE_A,
        role_ids: [operatorRole.id],
      },
    });
    expect(createRes.status(), "operator creation").toBe(201);
    const operatorId = (await createRes.json()).user_id;

    // One job on their line, one on another — both in production, so status is not what separates
    // them.
    const mine = await createWorkOrder(request, supervisorToken, unique("E2E Mine "));
    const theirs = await createWorkOrder(request, supervisorToken, unique("E2E Theirs "));
    await assign(request, supervisorToken, mine.id, LINE_A);
    await assign(request, supervisorToken, theirs.id, LINE_B);
    for (const wo of [mine, theirs]) {
      expect((await setStatus(request, supervisorToken, wo.id, "in_production")).status()).toBe(200);
    }

    const operatorToken = await apiToken(request, { username, password });
    const listRes = await request.get(`${API}/api/v1/work-orders?page_size=250`, {
      headers: authHeaders(operatorToken),
    });
    expect(listRes.status()).toBe(200);
    const visible = (await listRes.json()).results as { id: number; production_line: string }[];

    expect(visible.some((w) => w.id === mine.id), "own line is visible").toBe(true);
    expect(visible.some((w) => w.id === theirs.id), "another line must not be").toBe(false);
    expect(
      visible.every((w) => w.production_line === LINE_A),
      "every row an operator sees belongs to their line",
    ).toBe(true);

    // Reading another line's work order directly is refused, not merely hidden from the list.
    const direct = await request.get(`${API}/api/v1/work-orders/${theirs.id}`, {
      headers: authHeaders(operatorToken),
    });
    expect(direct.status()).toBe(403);

    // Leave the account disabled so repeat runs do not accumulate live logins.
    await request.patch(`${API}/api/v1/users/${operatorId}`, {
      headers: authHeaders(adminToken),
      data: { status: "inactive" },
    });
  });

  test("planning is refused to a machine operator at the API", async ({ request }) => {
    // FR-015 and FR-017 name the Supervisor and Admin. A hidden control is not enforcement.
    const operatorToken = await apiToken(request, USERS.operator);
    const supervisorToken = await apiToken(request, USERS.supervisor);
    const wo = await createWorkOrder(request, supervisorToken, unique("E2E Guard "));

    const assignRes = await assign(request, operatorToken, wo.id, LINE_A);
    expect(assignRes.status(), "work_orders.assign").toBe(403);

    const sequenceRes = await request.patch(`${API}/api/v1/work-orders/${wo.id}/sequence`, {
      headers: authHeaders(operatorToken),
      data: { display_sequence: 1 },
    });
    expect(sequenceRes.status(), "work_orders.sequence").toBe(403);
  });
});
