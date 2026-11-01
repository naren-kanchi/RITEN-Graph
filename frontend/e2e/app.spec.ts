import { expect, Page, test } from "@playwright/test";
import fs from "node:fs";
import path from "node:path";

// Reads the seed logins from the local .env; nothing secret is written into this file.
const env = Object.fromEntries(
  fs.readFileSync(path.resolve(__dirname, "../../.env"), "utf-8").split(/\r?\n/).filter((l) => l.includes("=")).map((l) => {
    const at = l.indexOf("=");
    return [l.slice(0, at), l.slice(at + 1)];
  }),
);
const shots = path.resolve(__dirname, "../../docs/screenshots");

async function login(page: Page, username: string, password: string) {
  await page.goto("/login");
  await page.getByLabel("Username").fill(username);
  await page.getByLabel("Password").fill(password);
  await page.getByRole("button", { name: "Sign in" }).click();
  await expect(page.getByRole("heading", { name: "Overview" })).toBeVisible();
}
const asAnalyst = (page: Page) => login(page, env.SEED_ANALYST_USERNAME, env.SEED_ANALYST_PASSWORD);
const asAdmin = (page: Page) => login(page, env.SEED_ADMIN_USERNAME, env.SEED_ADMIN_PASSWORD);

async function shot(page: Page, name: string) {
  await page.waitForLoadState("networkidle");
  await page.screenshot({ path: path.join(shots, `${name}.png`), fullPage: true });
}

test("signed-out visitors are sent to the login page", async ({ page }) => {
  await page.goto("/trade");
  await expect(page).toHaveURL(/\/login$/);
  await shot(page, "01-login");
});

test("a wrong password shows an error and stays signed out", async ({ page }) => {
  await page.goto("/login");
  await page.getByLabel("Username").fill(env.SEED_ANALYST_USERNAME);
  await page.getByLabel("Password").fill("definitely-wrong");
  await page.getByRole("button", { name: "Sign in" }).click();
  await expect(page.getByRole("alert").filter({ hasText: "Incorrect" })).toBeVisible();
  await expect(page).toHaveURL(/\/login$/);
});

test("no database secret reaches the browser", async ({ page }) => {
  const bodies: string[] = [];
  page.on("response", async (r) => {
    if (r.url().includes("/_next/static/") && r.url().endsWith(".js")) bodies.push(await r.text().catch(() => ""));
  });
  await asAnalyst(page);
  await page.waitForLoadState("networkidle");
  expect(bodies.length).toBeGreaterThan(0);
  const all = bodies.join("\n");
  for (const secret of [env.POSTGRES_PASSWORD, env.APP_DB_PASSWORD, env.NEO4J_PASSWORD, env.JWT_SECRET]) {
    expect(all).not.toContain(secret);
  }
  expect(all).not.toContain("18000");
});

test("overview reports the audited dataset through the whole stack", async ({ page }) => {
  await asAnalyst(page);
  await expect(page.getByText("7,281", { exact: true })).toBeVisible();
  await expect(page.getByText("28.4%")).toBeVisible();
  await expect(page.getByRole("cell", { name: "Restrictions" })).toBeVisible();
  await shot(page, "02-overview");
});

test("filtering trade changes the query result and the empty state works", async ({ page }) => {
  await asAnalyst(page);
  await page.getByRole("link", { name: "Trade flows" }).click();
  await expect(page.getByText(/of 5,656/)).toBeVisible();
  await page.getByLabel("Exporter").selectOption("TW");
  await page.getByLabel("Importer").selectOption("US");
  await page.getByLabel("Export control").selectOption("true");
  await expect(page.getByText(/of 5,656/)).toHaveCount(0);
  await page.getByLabel("Export control").selectOption("");
  await page.getByLabel("From").selectOption("2023");
  await expect(page.getByText(/ of \d+/).first()).toBeVisible();
  await shot(page, "03-trade");
  await page.getByLabel("Exporter").selectOption("PK").catch(() => undefined);
  await page.getByLabel("Importer").selectOption("FR");
  await expect(page.getByText("Nothing matches these filters.").first()).toBeVisible();
});

test("the synthetic switch removes synthetic records everywhere", async ({ page }) => {
  await asAnalyst(page);
  await page.getByRole("link", { name: "Restrictions" }).click();
  await expect(page.getByText(/of 987/)).toBeVisible();
  await page.getByLabel("Include synthetic rows").uncheck();
  await expect(page.getByText(/of 42/)).toBeVisible();
  await expect(page.getByRole("cell", { name: "Synthetic" })).toHaveCount(0);
  await page.getByLabel("Include synthetic rows").check();
  await expect(page.getByText(/of 987/)).toBeVisible();
});

test("full-text search finds restrictions by meaning of the words", async ({ page }) => {
  await asAnalyst(page);
  await page.getByRole("link", { name: "Restrictions" }).click();
  await page.getByRole("searchbox").fill("section 301");
  await page.getByRole("button", { name: "Search" }).click();
  await expect(page.getByText(/Section 301/).first()).toBeVisible();
  await shot(page, "04-restrictions");
});

test("infrastructure comparison and trend render", async ({ page }) => {
  await asAnalyst(page);
  await page.getByRole("link", { name: "AI infrastructure" }).click();
  await expect(page.getByRole("cell", { name: "United States" })).toBeVisible();
  await page.getByRole("button", { name: "India" }).click();
  await page.getByRole("button", { name: "Taiwan" }).click();
  await expect(page.locator(".legend").getByText("Taiwan")).toBeVisible();
  await shot(page, "05-infrastructure");
});

test("actor pages cover countries and sanctions-only actors", async ({ page }) => {
  await asAnalyst(page);
  await page.goto("/actors/CN");
  await expect(page.getByRole("heading", { name: "China" })).toBeVisible();
  await expect(page.getByText("Headquartered companies")).toBeVisible();
  await shot(page, "06-actor-profile");
  await page.goto("/actors/GLOBAL");
  await expect(page.getByText(/no trade or country-year figures/)).toBeVisible();
});

test("graph explorer selects an actor and analyses a route from Neo4j", async ({ page }) => {
  await asAnalyst(page);
  await page.goto("/graph?focus=TW");
  await expect(page.getByRole("heading", { name: "Taiwan" })).toBeVisible();
  await page.getByLabel("Restrictions", { exact: true }).check();
  await expect(page.getByRole("heading", { name: "Through one intermediary" })).toBeVisible();
  await expect(page.getByText("All paths, strongest first")).toBeVisible();
  await expect(page.getByRole("cell", { name: /US → .*CN/ }).first()).toBeVisible();
  await shot(page, "07-graph");
});

test("reports run with parameters", async ({ page }) => {
  await asAnalyst(page);
  await page.getByRole("link", { name: "Reports" }).click();
  await expect(page.getByText(/% of exporter/)).toBeVisible();
  await shot(page, "08-reports");
  await page.getByRole("tab", { name: "Restriction targets" }).click();
  await page.getByLabel("At least this many measures").fill("100");
  await expect(page.getByRole("cell", { name: "Measures" })).toHaveCount(0);
  await expect(page.getByRole("link", { name: "GLOBAL" })).toHaveCount(0);
  await page.getByRole("tab", { name: "Mutual restrictions" }).click();
  await expect(page.getByText("A on B")).toBeVisible();
});

test("analysts do not get administration", async ({ page }) => {
  await asAnalyst(page);
  await expect(page.getByRole("link", { name: "Administration" })).toHaveCount(0);
  await page.goto("/admin");
  await expect(page.getByRole("alert").filter({ hasText: "Administrator role" })).toBeVisible();
});

test("an analyst proposes a link, an admin approves it, and it reaches company figures", async ({ browser }) => {
  const evidence = `E2E evidence ${Date.now()}: same manufacturer under a shorter name`;
  const analyst = await (await browser.newContext()).newPage();
  await asAnalyst(analyst);
  await analyst.getByRole("link", { name: "Curation" }).click();
  await analyst.getByLabel("Supplier label").selectOption({ label: "KLA" });
  await analyst.getByLabel("Company").selectOption({ label: "KLA Corporation" });
  await analyst.getByLabel("Evidence").fill(evidence);
  await analyst.getByRole("button", { name: "Propose link" }).click();
  await expect(analyst.getByRole("cell", { name: evidence })).toBeVisible();
  await expect(analyst.getByRole("button", { name: "Approve selected" })).toHaveCount(0);

  const admin = await (await browser.newContext()).newPage();
  await asAdmin(admin);
  await admin.getByRole("link", { name: "Curation" }).click();
  const row = admin.getByRole("row").filter({ hasText: evidence });
  await row.getByRole("checkbox").check();
  await admin.getByRole("button", { name: "Approve selected" }).click();
  await expect(row.getByText("approved")).toBeVisible();
  await expect(admin.getByRole("cell", { name: "KLA Corporation" }).first()).toBeVisible();
  await shot(admin, "09-curation");

  await admin.getByRole("link", { name: "Administration" }).click();
  await expect(admin.getByText("All counts match")).toBeVisible();
  await expect(admin.getByRole("cell", { name: "supplier_company_alias" }).first()).toBeVisible();
  await shot(admin, "10-administration");

  // Leave the demo database as it was.
  await admin.getByRole("link", { name: "Curation" }).click();
  await admin.getByRole("row").filter({ hasText: evidence }).getByRole("button", { name: "Delete" }).click();
  await expect(admin.getByRole("cell", { name: evidence })).toHaveCount(0);
});

test("notes can be added, edited and deleted on a record", async ({ page }) => {
  const note = `E2E note ${Date.now()}`;
  await asAnalyst(page);
  await page.goto("/actors/IN");
  await page.getByLabel("Add a note").fill(note);
  await page.getByRole("button", { name: "Save note" }).click();
  await expect(page.getByText(note)).toBeVisible();
  await page.getByRole("button", { name: "Edit" }).first().click();
  await page.getByLabel("Edit note").fill(`${note} edited`);
  await page.getByRole("button", { name: "Save", exact: true }).click();
  await expect(page.getByText(`${note} edited`)).toBeVisible();
  await page.getByRole("button", { name: "Delete" }).first().click();
  await expect(page.getByText(`${note} edited`)).toHaveCount(0);
});

test("companies filter and flag rows from before founding", async ({ page }) => {
  await asAnalyst(page);
  await page.getByRole("link", { name: "Companies" }).click();
  await page.getByLabel("Year").selectOption("2015");
  await page.getByLabel("Name").fill("Biren");
  await expect(page.getByText("Before founding")).toBeVisible();
  await page.getByLabel("Name").fill("");
  await page.getByLabel("Year").selectOption("2023");
  await expect(page.getByRole("link", { name: "NVIDIA" })).toBeVisible();
  await shot(page, "11-companies");
});
