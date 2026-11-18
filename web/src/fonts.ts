// Spec §2.4 (R-M18-1): Noto Sans 400 and 700, the package and version Coglossa ships, so the two
// products share a typeface and the customer has already vetted it. The app works offline, so the
// font ships with it; other scripts fall back to the computer's fonts.
import "@fontsource/noto-sans/400.css";
import "@fontsource/noto-sans/700.css";

/** The CSS family names, in the order of the font stack in styles/base.css. */
export const FONT_FAMILIES: readonly string[] = ["Noto Sans"];
