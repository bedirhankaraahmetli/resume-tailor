import { defineConfig, type Plugin } from "vite";

// GitHub Pages cannot send headers, so the CSP is a <meta> tag (docs/PLAN.md §2.7). It goes
// into the production build only: Vite's dev server injects inline styles for hot reload.
// connect-src is the guarantee behind "the token is only ever sent to api.github.com".
const CSP = [
  "default-src 'none'",
  "script-src 'self'",
  "style-src 'self'",
  "img-src 'self' data: blob:",
  "font-src 'self'",
  "connect-src https://api.github.com",
  "worker-src 'self'",
  "manifest-src 'self'",
  "base-uri 'none'",
  "form-action 'none'",
].join("; ");

function csp(): Plugin {
  return {
    name: "inject-csp",
    apply: "build",
    transformIndexHtml(html) {
      return html.replace(
        "<!--CSP-->",
        `<meta http-equiv="Content-Security-Policy" content="${CSP}">`,
      );
    },
  };
}

export default defineConfig({
  // Served from https://<user>.github.io/resume-tailor/
  base: "./",
  plugins: [csp()],
  build: {
    target: "es2022",
    // No inline data: URIs for assets: everything is a 'self' file the CSP allows.
    assetsInlineLimit: 0,
  },
});
