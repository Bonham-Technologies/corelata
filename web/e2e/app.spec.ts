import { expect, test } from "@playwright/test";

test("an unknown address shows the app's not-found page", async ({ page }) => {
  await page.goto("/no/such/page");
  await expect(page.getByRole("heading", { name: "Page not found" })).toBeVisible();
  await page.getByRole("link", { name: "Start a new report" }).click();
  await expect(page).toHaveURL(/\/new$/);
});

test("unknown API paths answer JSON 404, not the app", async ({ request }) => {
  const response = await request.get("/api/nope");
  expect(response.status()).toBe(404);
  expect(await response.json()).toEqual({ detail: "Not Found" });
});

// The version sits in the sidebar's foot (M18 spec §3.3), outside the navigation landmark.
test("the sidebar's foot shows the version from the API", async ({ page, request }) => {
  const health = await (await request.get("/api/health")).json();
  await page.goto("/new");
  await expect(page.getByText(`Corelata ${health.version}`)).toBeVisible();
});
