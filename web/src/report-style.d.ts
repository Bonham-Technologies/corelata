declare module "virtual:report-style" {
  /** The CSP source of the engine's report stylesheet, `sha256-<base64>`, computed from
   * engine/corelata/render/templates/report.css when the app is built (vite.config.ts). */
  export const REPORT_STYLE_HASH: string;
}
