// Copied from Coglossa (spec §2.2): apply the saved theme before the page draws, so it never
// flashes light.
// Keep in step with src/theme/theme.ts (THEME_KEY and the "system" rule).
(function () {
  var choice;
  try {
    choice = localStorage.getItem("corelata.theme") || "system";
  } catch {
    choice = "system";
  }
  if (choice !== "light" && choice !== "dark") {
    var dark =
      typeof matchMedia === "function" && matchMedia("(prefers-color-scheme: dark)").matches;
    choice = dark ? "dark" : "light";
  }
  document.documentElement.dataset.theme = choice;
})();
