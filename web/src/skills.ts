// Adding a skill from the browser: checks, and the two text edits (inventory §6 and
// config.yml `skill_names_tr`). Pure, so it is tested against the real files' shapes.
//
// The parsing mirrors `inventory.py` (`split_terms`, the §6 table, the "never claim" line)
// and `text.py` (`fold`). If those change, change this too: a check that disagrees with
// the Python guard would let through a skill the pipeline then rejects, or the reverse.

export interface NewSkill {
  name: string;
  tr: string;
  evidence: string;
}

export interface SkillCheck {
  errors: string[];
  /** Near-duplicates: allowed, but only after the owner confirms. */
  warnings: string[];
}

/** `text.py: fold`: case-, dot- and hyphen-insensitive, with all four Turkish i's → i. */
export function fold(s: string): string {
  return s.normalize("NFC").replace(/[İIı]/g, "i").toLowerCase()
    .replace(/[‐-―\-_/]+/g, " ").replace(/\s+/g, " ").trim();
}

function cleanMd(s: string): string {
  return s.replace(/\*\(([^)]*)\)\*/g, "").replaceAll("**", "").replaceAll("`", "")
    .replace(/\s+/g, " ").trim();
}

/** `inventory.py: split_terms`: every usable name in one table cell. */
export function splitTerms(cell: string): string[] {
  const s = cleanMd(cell);
  const parts: string[] = [];
  let depth = 0;
  let cur = "";
  for (const ch of s) {
    if (ch === "(") depth++;
    else if (ch === ")") depth--;
    if (ch === "," && depth === 0) {
      parts.push(cur);
      cur = "";
    } else cur += ch;
  }
  parts.push(cur);

  const out: string[] = [];
  const add = (raw: string): void => {
    const name = raw.trim().replace(/\.+$/, "").trim();
    if (!name || name.length > 40 || name === "EN" || name === "TR") return;
    if (!out.includes(name)) out.push(name);
    const m = /^(.*\D)\s+\d+(\.\d+)?$/.exec(name);
    if (m && !out.includes(m[1]!.trim())) out.push(m[1]!.trim());
  };
  for (const p0 of parts) {
    const p = p0.trim();
    if (!p) continue;
    const m = /^(.*?)\s*\((.*)\)\s*$/.exec(p);
    const [outer, inner] = m ? [m[1]!, m[2]!] : [p, ""];
    for (const piece of outer.split(/\s+\+\s+|\s+\/\s+/)) add(piece);
    for (const piece of inner.split(/,|\s+\+\s+|\//)) add(piece);
  }
  return out;
}

function eolOf(text: string): string {
  return text.includes("\r\n") ? "\r\n" : "\n";
}

/** The `## 6.` section as [start, end) offsets into the text. */
function skillsSection(text: string): [number, number] {
  const start = text.search(/^## 6\./m);
  if (start < 0) throw new Error("career-inventory.md has no “## 6. Skills” section.");
  const rest = text.slice(start + 1);
  const next = rest.search(/^## /m);
  return [start, next < 0 ? text.length : start + 1 + next];
}

const TABLE_RULE = /^\s*\|[\s|:-]+\|\s*$/;

function tableRows(section: string): string[][] {
  const rows = section.split(/\r?\n/)
    .filter((ln) => ln.trim().startsWith("|") && !TABLE_RULE.test(ln))
    .map((ln) => ln.trim().replace(/^\|/, "").replace(/\|$/, "").split("|").map((c) => c.trim()));
  return rows.slice(1); // the header row
}

export function inventorySkills(inventory: string): string[] {
  const [a, b] = skillsSection(inventory);
  const out: string[] = [];
  for (const row of tableRows(inventory.slice(a, b))) {
    for (const t of splitTerms(row[0] ?? "")) if (!out.includes(t)) out.push(t);
  }
  return out;
}

export function neverClaim(inventory: string): string[] {
  const [a, b] = skillsSection(inventory);
  const m = /\*\*Not evidenced, never claim:\*\*([\s\S]*?)(?:\n\s*\n|$)/.exec(inventory.slice(a, b));
  if (!m) return [];
  return m[1]!.replace(/\r?\n/g, " ").split(/,|\//)
    .map((t) => t.trim().replace(/\.+$/, "").trim()).filter(Boolean);
}

/** The `skill_names_tr:` block: its key line, its entries' indent, and the keys in it. */
function trBlock(config: string): { lines: string[]; keyLine: number; last: number;
  indent: string; keys: string[] } {
  const lines = config.split(/\r?\n/);
  const keyLine = lines.findIndex((ln) => /^\s*skill_names_tr:\s*(#.*)?$/.test(ln));
  if (keyLine < 0) {
    throw new Error("config.yml has no “skill_names_tr:” block (as a list of lines). Add "
      + "it once by hand under “resume:”, then try again.");
  }
  const keyIndent = /^\s*/.exec(lines[keyLine]!)![0].length;
  let last = keyLine;
  let indent = "";
  const keys: string[] = [];
  for (let i = keyLine + 1; i < lines.length; i++) {
    const ln = lines[i]!;
    if (!ln.trim()) continue;
    const ind = /^\s*/.exec(ln)![0];
    if (ind.length <= keyIndent) break;
    last = i;
    if (ln.trim().startsWith("#")) continue;
    if (!indent) indent = ind;
    const k = /^\s*("(?:[^"\\]|\\.)*"|'[^']*'|[^:#]+?)\s*:(\s|$)/.exec(ln);
    if (k) keys.push(unquote(k[1]!));
  }
  return { lines, keyLine, last, indent: indent || " ".repeat(keyIndent + 2), keys };
}

function unquote(s: string): string {
  if (s.startsWith('"')) return JSON.parse(s) as string;
  if (s.startsWith("'")) return s.slice(1, -1).replaceAll("''", "'");
  return s;
}

const YAML_RESERVED = /^(y|yes|n|no|true|false|on|off|null|~)$/i;

/** A YAML scalar: plain when that is unambiguous, otherwise double-quoted (JSON is YAML). */
export function yamlScalar(s: string): string {
  const plain = /^[\p{L}][\p{L}\p{N} .()+'&-]*$/u.test(s) && !YAML_RESERVED.test(s)
    && !/\s$/.test(s);
  return plain ? s : JSON.stringify(s);
}

export function checkSkill(skill: NewSkill, inventory: string, config: string): SkillCheck {
  const errors: string[] = [];
  const warnings: string[] = [];
  const name = skill.name.trim();
  const tr = skill.tr.trim();
  const evidence = skill.evidence.trim();

  if (!name) errors.push("Enter the skill.");
  if (!tr) errors.push("Enter its Turkish name. It is what the Turkish resume shows.");
  if (!evidence) errors.push("Enter the evidence: where you used it (a project, a course, "
    + "a certificate). A skill without evidence is never used.");
  if (/[|\r\n]/.test(name + tr + evidence)) errors.push("Remove the “|” and line breaks.");
  if (name && (/[,()]|\s\+\s|\s\/\s/.test(name) || splitTerms(name).length !== 1
    || splitTerms(name)[0] !== name)) {
    errors.push("Add one skill at a time, without commas, brackets, “ + ” or “ / ”.");
  }
  if (name.length > 40) errors.push("Keep the skill under 40 characters; longer names are ignored.");
  if (errors.length) return { errors, warnings };

  const f = fold(name);
  for (const bad of neverClaim(inventory)) {
    const b = fold(bad);
    if (b && (` ${f} `.includes(` ${b} `) || ` ${b} `.includes(` ${f} `))) {
      errors.push(`“${name}” is on the inventory's “never claim” list (${bad}).`);
    }
  }
  const existing = inventorySkills(inventory);
  const same = existing.find((e) => fold(e) === f);
  if (same) errors.push(`“${same}” is already in the inventory.`);
  const { keys } = trBlock(config);
  const key = keys.find((k) => fold(k) === f);
  if (key && !same) errors.push(`config.yml already has a Turkish name for “${key}”.`);
  if (errors.length) return { errors, warnings };

  // Shared words are split on spaces only: "Scikit-learn" is one word, not "learn".
  const wordsOf = (s: string): string[] =>
    s.normalize("NFC").replace(/[İIı]/g, "i").toLowerCase().split(/\s+/);
  const words = new Set(wordsOf(name).filter((w) => w.length >= 4));
  for (const e of existing) {
    const g = fold(e);
    const shared = wordsOf(e).filter((w) => words.has(w));
    // Whole words only, so "Go" is not found inside "Algorithms".
    if (` ${g} `.includes(` ${f} `) || ` ${f} `.includes(` ${g} `)) {
      warnings.push(`“${name}” overlaps “${e}”, which is already listed.`);
    } else if (shared.length) {
      warnings.push(`“${name}” is close to “${e}” (both say “${shared[0]}”).`);
    }
  }
  return { errors, warnings };
}

/** Appends `| name | evidence |` after the last row of the §6 table. */
export function addSkillRow(inventory: string, skill: NewSkill): string {
  const [a, b] = skillsSection(inventory);
  const eol = eolOf(inventory);
  const section = inventory.slice(a, b);
  const lines = section.split(/\r?\n/);
  let last = -1;
  lines.forEach((ln, i) => { if (ln.trim().startsWith("|")) last = i; });
  if (last < 0) throw new Error("The Skills section of career-inventory.md has no table.");
  lines.splice(last + 1, 0, `| ${skill.name.trim()} | ${skill.evidence.trim()} |`);
  return inventory.slice(0, a) + lines.join(eol) + inventory.slice(b);
}

/** Inserts `Name: Turkish` after the last `skill_names_tr:` entry, in the block's indent. */
export function addSkillNameTr(config: string, skill: NewSkill): string {
  const { lines, last, indent } = trBlock(config);
  lines.splice(last + 1, 0,
    `${indent}${yamlScalar(skill.name.trim())}: ${yamlScalar(skill.tr.trim())}`);
  return lines.join(eolOf(config));
}
