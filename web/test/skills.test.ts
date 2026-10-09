import { describe, expect, it } from "vitest";
import {
  addSkillNameTr, addSkillRow, checkSkill, fold, inventorySkills, neverClaim, splitTerms,
  yamlScalar,
} from "../src/skills";
// The fictional sample person's files: the same shape as the owner's real ones.
import INV from "../../sample-data/career-inventory.md?raw";
import CFG from "../../sample-data/config.yml?raw";

const skill = (name: string, tr = "Türkçe", evidence = "Churn Radar") =>
  ({ name, tr, evidence });

describe("parsing, as inventory.py does", () => {
  it("splits table cells like split_terms", () => {
    expect(splitTerms("Unit testing (XCTest, JUnit 5)"))
      .toEqual(["Unit testing", "XCTest", "JUnit 5", "JUnit"]);
    expect(splitTerms("Swift / SwiftUI")).toEqual(["Swift", "SwiftUI"]);
    expect(splitTerms("**.NET Framework**.")).toEqual([".NET Framework"]);
  });

  it("reads the §6 skills and the never-claim list", () => {
    const skills = inventorySkills(INV);
    expect(skills).toContain("Matplotlib");
    expect(skills).toContain("Core Location");
    expect(skills).not.toContain("Skill"); // the header row
    expect(neverClaim(INV)).toEqual(["Kubernetes", "AWS", "team leadership", "Android"]);
  });

  it("folds Turkish i's and hyphens like text.py", () => {
    expect(fold("İLETİŞİM")).toBe(fold("iletişim"));
    expect(fold("Scikit-learn")).toBe("scikit learn");
  });
});

describe("checkSkill", () => {
  it("accepts a new, distinct skill", () => {
    expect(checkSkill(skill("Documentation", "Dokümantasyon"), INV, CFG))
      .toEqual({ errors: [], warnings: [] });
  });

  it("requires the Turkish name and the evidence", () => {
    const r = checkSkill({ name: "Documentation", tr: " ", evidence: "" }, INV, CFG);
    expect(r.errors.join(" ")).toMatch(/Turkish name/);
    expect(r.errors.join(" ")).toMatch(/evidence/);
  });

  it("rejects an exact duplicate, case- and dot-insensitively", () => {
    expect(checkSkill(skill("PYTHON"), INV, CFG).errors[0]).toMatch(/already in the inventory/);
    expect(checkSkill(skill("core-location"), INV, CFG).errors[0]).toMatch(/Core Location/);
  });

  it("rejects never-claim terms, also inside a longer name", () => {
    expect(checkSkill(skill("Kubernetes"), INV, CFG).errors[0]).toMatch(/never claim/);
    expect(checkSkill(skill("Team Leadership"), INV, CFG).errors[0]).toMatch(/never claim/);
    expect(checkSkill(skill("AWS Lambda"), INV, CFG).errors[0]).toMatch(/never claim/);
  });

  it("rejects a name that already has a Turkish entry", () => {
    const cfg = CFG.replace("Unit testing: Birim testi", "Unit testing: Birim testi\n    Mentoring: Mentorluk");
    expect(checkSkill(skill("mentoring"), INV, cfg).errors[0]).toMatch(/config\.yml/);
  });

  it("takes one skill at a time", () => {
    for (const n of ["A, B", "Data (Pandas)", "Git + GitHub", "Swift / Kotlin"]) {
      expect(checkSkill(skill(n), INV, CFG).errors).toHaveLength(1);
    }
    expect(checkSkill(skill("Data | Analysis"), INV, CFG).errors.join(" ")).toMatch(/“\|”/);
  });

  it("warns about near-duplicates but allows them", () => {
    const viz = checkSkill(skill("Data Visualization"), INV.replace("| Git |",
      "| Data Analysis | Churn Radar |\n| Git |"), CFG);
    expect(viz.errors).toEqual([]);
    expect(viz.warnings[0]).toMatch(/close to “Data Analysis”.*“data”/);
    expect(checkSkill(skill("Unit"), INV, CFG).warnings[0]).toMatch(/overlaps “Unit testing”/);
  });

  it("matches whole words only", () => {
    expect(checkSkill(skill("Go"), INV, CFG).warnings).toEqual([]);
    expect(checkSkill(skill("Willingness to Learn"), INV, CFG).warnings).toEqual([]);
  });
});

describe("the edits", () => {
  it("appends the row after the last table row of §6", () => {
    const out = addSkillRow(INV, skill("Documentation", "Dokümantasyon", "Ledger API README"));
    expect(out).toContain("| Unit testing (XCTest, JUnit 5) | Parkly, Ledger API |\n"
      + "| Documentation | Ledger API README |\n\nSpoken languages");
    expect(inventorySkills(out)).toContain("Documentation");
    expect(out.length).toBe(INV.length + "| Documentation | Ledger API README |\n".length);
  });

  it("keeps CRLF files CRLF", () => {
    const crlf = INV.replace(/\n/g, "\r\n");
    const out = addSkillRow(crlf, skill("Documentation"));
    expect(out.replace(/\r\n/g, "")).not.toMatch(/\n/);
    expect(addSkillNameTr(CFG.replace(/\n/g, "\r\n"), skill("X Y")).replace(/\r\n/g, ""))
      .not.toMatch(/\n/);
  });

  it("inserts the Turkish name after the last skill_names_tr entry", () => {
    const out = addSkillNameTr(CFG, skill("Willingness to Learn", "Öğrenmeye Açıklık"));
    expect(out).toContain("    Unit testing: Birim testi\n"
      + "    Willingness to Learn: Öğrenmeye Açıklık\n  extra_skill_groups:");
  });

  it("finds the end of the block across blank lines and comments", () => {
    const cfg = CFG.replace("Unit testing: Birim testi",
      "Unit testing: Birim testi\n\n    # soft skills\n    Teamwork: Takım Çalışması");
    expect(addSkillNameTr(cfg, skill("Documentation", "Dokümantasyon")))
      .toContain("    Teamwork: Takım Çalışması\n    Documentation: Dokümantasyon\n");
  });

  it("quotes YAML scalars only when it must", () => {
    expect(yamlScalar("Veri Analizi")).toBe("Veri Analizi");
    expect(yamlScalar("C# / .NET")).toBe('"C# / .NET"');
    expect(yamlScalar("Yes")).toBe('"Yes"');
    expect(yamlScalar("A: B")).toBe('"A: B"');
  });

  it("explains a config without the block", () => {
    expect(() => addSkillNameTr("resume:\n  min_projects: 3\n", skill("X")))
      .toThrow(/skill_names_tr/);
  });
});
