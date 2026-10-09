// Settings: the data repo, the encrypted token, API keys (Actions secrets) and help.

import { busy, clear, errorText, h, notice, shortDate } from "../dom";
import { GitHub, GitHubError, type Secret } from "../github";
import {
  forget, github, keyExpiry, lock, saveSettings, sessionToken, setKeyExpiry, settings, unlock,
} from "../store";
import { addSkillNameTr, addSkillRow, checkSkill, type NewSkill } from "../skills";
import type { View } from "../types";

const REPO_RE = /^[A-Za-z0-9-]+\/[A-Za-z0-9._-]+$/;

const KEYS: { name: string; label: string; help: string }[] = [
  { name: "ANTHROPIC_API_KEY", label: "Claude API key",
    help: "From platform.claude.com → API keys (starts with sk-ant-)." },
  { name: "CLAUDE_CODE_OAUTH_TOKEN", label: "Claude Code token (optional fallback)",
    help: "Run `claude setup-token` on a computer with Claude Code and your Pro/Max plan." },
  { name: "GEMINI_API_KEY", label: "Gemini API key (optional fallback)",
    help: "From aistudio.google.com/apikey. Free tier." },
];

function input(id: string, attrs: Record<string, string | boolean> = {}): HTMLInputElement {
  return h("input", { id, autocomplete: "off", spellcheck: false, ...attrs });
}

function field(label: string, el: HTMLElement, hint?: string | HTMLElement): HTMLElement {
  return h("div", { class: "field" }, h("label", { for: el.id }, label), el,
    hint ? h("p", { class: "hint" }, hint) : null);
}

export function showSettings(view: View, flash: HTMLElement[] = []): void {
  const s = settings();
  const gh = github();
  clear(view.el,
    h("h1", null, "Settings"),
    ...flash,
    connection(s?.repo ?? "", Boolean(gh), (msg) => showSettings(view, msg)),
    gh ? keysPanel(view, gh) : null,
    gh ? skillsPanel(gh) : null,
    tokenHelp(),
    claudeHelp(),
    privacyNote());
}

function connection(repo: string, unlocked: boolean,
                    onSaved: (message: HTMLElement[]) => void): HTMLElement {
  const repoIn = input("repo", { value: repo, placeholder: "your-name/resume-data",
    autocapitalize: "off" });
  const tokenIn = input("token", { type: "password", placeholder: repo
    ? "Leave empty to keep the saved token" : "github_pat_…" });
  const pass = input("pass", { type: "password", autocomplete: "new-password" });
  const pass2 = input("pass2", { type: "password", autocomplete: "new-password" });
  const out = h("div");
  const save = h("button", { class: "primary", type: "submit" }, "Save and test");

  const form = h("form", { class: "stack card" },
    h("h2", null, "Data repository"),
    field("Private data repo (owner/name)", repoIn),
    field("Fine-grained access token", tokenIn, "See “Creating the token” below."),
    field("Passphrase", pass, "Encrypts the token on this device. You type it once per "
      + "browser session. It is never sent anywhere and cannot be recovered."),
    field("Passphrase again", pass2),
    save, out);

  form.addEventListener("submit", (ev) => {
    ev.preventDefault();
    busy(save, out, async () => {
      const r = repoIn.value.trim();
      if (!REPO_RE.test(r)) throw new Error("Enter the repo as owner/name.");
      if (pass.value.length < 8) throw new Error("Use a passphrase of at least 8 characters.");
      if (pass.value !== pass2.value) throw new Error("The passphrases do not match.");
      let token = tokenIn.value.trim();
      if (!token) {
        const current = sessionToken();
        if (!current) throw new Error("Paste the token (or unlock first to keep the saved one).");
        token = current;
      }
      const result = await testAccess(new GitHub(token, r));
      await saveSettings(r, token, pass.value);
      // Re-render: the API keys panel needs the now-unlocked token.
      onSaved([...result, h("p", null, h("a", { href: "#/" }, "Start a new application →"))]);
    })();
  });

  const extra = h("div", { class: "row" });
  if (repo && unlocked) {
    extra.append(
      h("button", { class: "secondary", onclick: () => { lock(); location.hash = "#/"; } },
        "Lock now"),
      h("button", { class: "link danger", onclick: () => {
        if (confirm("Remove the saved repo and token from this device?")) {
          forget();
          location.hash = "#/settings";
          location.reload();
        }
      } }, "Forget this device"));
  }
  return h("div", null, form, extra);
}

async function testAccess(gh: GitHub): Promise<HTMLElement[]> {
  const repo = await gh.checkAccess();
  const lines: HTMLElement[] = [];
  if (!repo.private) lines.push(notice("warn", "This repo is public. Your resumes and "
    + "applications should be in a private repo."));
  if (!repo.push) throw new Error("The token can read the repo but not write to it. Give it "
    + "“Contents: Read and write”.");
  try {
    await gh.runsForCommit("0000000000000000000000000000000000000000");
  } catch (e) {
    if (e instanceof GitHubError && e.status === 403) {
      throw new Error("The token cannot read workflow runs. Give it “Actions: Read-only”.");
    }
    throw e;
  }
  lines.unshift(notice("ok", `Connected to ${gh.repo}. Saved, with the token encrypted.`));
  return lines;
}

function keysPanel(view: View, gh: GitHub): HTMLElement {
  const body = h("div", null, notice("info", "Checking which keys are set…"));
  const panel = h("section", { class: "card stack" },
    h("h2", null, "API keys"),
    h("p", { class: "hint" }, "Stored as encrypted Actions secrets in your data repo. A key "
      + "typed here goes from this page straight to GitHub, encrypted in your browser first. "
      + "It is never saved on this device, and nobody can read it back, not even this page."),
    body);

  gh.listSecrets().then((secrets) => {
    if (!view.alive()) return;
    clear(body, ...KEYS.map((k) => keyRow(gh, k, secrets.find((s) => s.name === k.name))));
  }).catch((e: unknown) => {
    const forbidden = e instanceof GitHubError && e.status === 403;
    clear(body, notice(forbidden ? "info" : "error", forbidden
      ? "To manage keys here, give the token the optional permission “Secrets: Read and "
        + "write”. Or set them on GitHub: "
      : errorText(e),
    forbidden ? h("a", { href: `https://github.com/${gh.repo}/settings/secrets/actions`,
      target: "_blank", rel: "noopener noreferrer" }, "repo secrets settings") : null));
  });
  return panel;
}

function keyRow(gh: GitHub, k: (typeof KEYS)[number], secret: Secret | undefined): HTMLElement {
  const value = input(`key-${k.name}`, { type: "password", placeholder: secret
    ? "Paste a new key to replace it" : "Paste the key" });
  const expiry = input(`exp-${k.name}`, { type: "date", value: keyExpiry()[k.name] ?? "" });
  const out = h("div");
  const save = h("button", { class: "secondary" }, secret ? "Replace" : "Save");
  save.addEventListener("click", busy(save, out, async () => {
    const v = value.value.trim();
    if (!v) throw new Error("Paste the key first.");
    if (/\s/.test(v)) throw new Error("The key contains spaces or line breaks.");
    await gh.putSecret(k.name, v);
    value.value = "";
    clear(out, notice("ok", `Saved ${k.name}.`));
  }));
  expiry.addEventListener("change", () => setKeyExpiry(k.name, expiry.value || null));

  const exp = keyExpiry()[k.name];
  const daysLeft = exp ? Math.ceil((Date.parse(exp) - Date.now()) / 86_400_000) : null;
  return h("div", { class: "key-row" },
    h("div", { class: "card-head" },
      h("strong", null, k.label),
      h("span", { class: `badge ${secret ? "ok" : "muted"}` }, secret
        ? `✓ Set · updated ${shortDate(secret.updated_at)}` : "– Not set")),
    daysLeft !== null && daysLeft <= 3
      ? notice("warn", daysLeft < 0 ? `This key expired on ${exp}.`
        : `This key expires in ${daysLeft} day(s), on ${exp}.`) : null,
    h("p", { class: "hint" }, k.help),
    field(`New value for ${k.name}`, value),
    field("Expires on (optional, for a reminder)", expiry),
    save, out);
}

const INVENTORY = "career-inventory.md";
const CONFIG = "config.yml";

/**
 * Adds one skill: a row in the inventory's §6 table and its Turkish name in config.yml, in
 * one commit. The checks run again on the files as they are at that commit.
 */
function skillsPanel(gh: GitHub): HTMLElement {
  const name = input("skill-name", { placeholder: "Data Analysis", autocapitalize: "words" });
  const tr = input("skill-tr", { placeholder: "Veri Analizi", autocapitalize: "words" });
  const evidence = input("skill-evidence", { placeholder: "Pandas in FireGuard, MuviNight" });
  const out = h("div");
  const add = h("button", { class: "primary", type: "submit" }, "Add skill");

  const form = h("form", { class: "card stack" },
    h("h2", null, "Skills"),
    h("p", { class: "hint" }, "Adds a skill to your career inventory, so tailored resumes "
      + "may use it when a posting asks for it. Only add what you can back up in an interview."),
    field("Skill (English, Title Case)", name),
    field("Turkish name", tr, "Shown on the Turkish resume."),
    field("Evidence", evidence, "Where you used it: a project, a course, a certificate."),
    add, out);

  form.addEventListener("submit", (ev) => {
    ev.preventDefault();
    busy(add, out, async () => {
      const skill: NewSkill = { name: name.value.trim(), tr: tr.value.trim(),
        evidence: evidence.value.trim() };
      let confirmed = false;
      const commit = await gh.commitFiles([INVENTORY, CONFIG], `skills: add ${skill.name}`,
        (files) => {
          const inv = files.get(INVENTORY)!;
          const cfg = files.get(CONFIG)!;
          const { errors, warnings } = checkSkill(skill, inv, cfg);
          if (errors.length) throw new Error(errors.join(" "));
          if (warnings.length && !confirmed) {
            if (!confirm(`${warnings.join("\n")}\n\nAdd “${skill.name}” anyway?`)) {
              throw new Error("Not added.");
            }
            confirmed = true;
          }
          return new Map([[INVENTORY, addSkillRow(inv, skill)],
            [CONFIG, addSkillNameTr(cfg, skill)]]);
        });
      name.value = tr.value = evidence.value = "";
      clear(out, notice("ok", `Added ${skill.name} (${skill.tr}). `,
        h("a", { href: `https://github.com/${gh.repo}/commit/${commit}`, target: "_blank",
          rel: "noopener noreferrer" }, "See the commit")),
      notice("info", "New tailored resumes can use it from now on. The presets are now "
        + "outdated: rebuild them in Quick apply when you want them to include it. The base "
        + "resumes do not change."));
    })();
  });
  return form;
}

function tokenHelp(): HTMLElement {
  return h("details", { class: "card" }, h("summary", null, "Creating the token"),
    h("ol", null,
      h("li", null, "On GitHub: Settings → Developer settings → Personal access tokens → "
        + "Fine-grained tokens → Generate new token."),
      h("li", null, "Expiration: 90 days or less. Repository access: Only select "
        + "repositories → your private data repo, nothing else."),
      h("li", null, "Repository permissions: Contents — Read and write; Actions — Read-only. "
        + "(Metadata — Read-only is added automatically.)"),
      h("li", null, "Optional, for the API keys panel: Secrets — Read and write."),
      h("li", null, "Generate, copy it, paste it above, and choose a passphrase.")),
    h("p", { class: "hint" }, "The token can only touch that one repo. If a device is lost, "
      + "revoke the token on GitHub; the encrypted copy is useless without the passphrase."));
}

function claudeHelp(): HTMLElement {
  return h("details", { class: "card" }, h("summary", null, "Setting up the Claude API"),
    h("ol", null,
      h("li", null, "Create a Claude Console account at platform.claude.com."),
      h("li", null, "Settings → Billing → Buy credits (for example $10). Leave auto-reload "
        + "off, so the prepaid balance is a hard spending cap. Credits expire one year after "
        + "purchase and are non-refundable."),
      h("li", null, "Create an API key in a workspace named resume-tailor."),
      h("li", null, "Save it under API keys above (or as the Actions secret "
        + "ANTHROPIC_API_KEY in your data repo).")),
    h("p", { class: "hint" }, "The Claude API is billed separately from a Claude Pro "
      + "subscription. A run costs about $0.05–0.10, and a monthly budget in config.yml "
      + "switches to a fallback provider before it is exceeded."));
}

function privacyNote(): HTMLElement {
  return h("details", { class: "card" }, h("summary", null, "What this page stores"),
    h("ul", null,
      h("li", null, "On this device: the repo name, the token encrypted with your "
        + "passphrase, the ids of requests started here, and optional key-expiry dates."),
      h("li", null, "For this browser tab only: the decrypted token, until you close it or "
        + "lock."),
      h("li", null, "It talks only to api.github.com. No analytics, no other servers.")));
}

export function showUnlock(view: View, onUnlocked: () => void): void {
  const s = settings();
  const pass = input("unlock-pass", { type: "password", autocomplete: "current-password" });
  const go = h("button", { class: "primary", type: "submit" }, "Unlock");
  const out = h("div");
  const form = h("form", { class: "stack card" },
    h("p", null, `Connected to ${s?.repo ?? "–"}. Enter your passphrase to decrypt the token `
      + "for this session."),
    field("Passphrase", pass), go, out,
    h("a", { href: "#/settings" }, "Settings"));
  form.addEventListener("submit", (ev) => {
    ev.preventDefault();
    busy(go, out, async () => {
      await unlock(pass.value);
      onUnlocked();
    })();
  });
  clear(view.el, h("h1", null, "Unlock"), form);
  pass.focus();
}
