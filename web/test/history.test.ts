import { describe, expect, it } from "vitest";
import { appendRecord, parseRecords, setField } from "../src/csv";

const CSV = "date,company,position,status,request_id\r\n"
  + "2026-10-01,Acme,Data Analyst,applied,a1\r\n"
  + "2026-10-02,\"Beta, Inc\",\"iOS \"\"Dev\"\"\",applied,\r\n"
  + "2026-10-03,Gamma,Backend,applied,g1\r\n";

describe("setField", () => {
  const rows = parseRecords(CSV);

  it("changes one field and leaves every other byte alone", () => {
    const out = setField(CSV, 1, rows[1]!, "status", "interview");
    expect(out).toBe(CSV.replace("Dev\"\"\",applied,", "Dev\"\"\",interview,"));
    expect(parseRecords(out)[1]).toEqual({ ...rows[1], status: "interview" });
  });

  it("finds the row by content when a row was inserted before it", () => {
    const moved = CSV.replace("date,company,position,status,request_id\r\n",
      "date,company,position,status,request_id\r\n2026-09-30,Zeta,QA,applied,z\r\n");
    const out = setField(moved, 0, rows[0]!, "status", "offer");
    expect(parseRecords(out)[1]).toEqual({ ...rows[0], status: "offer" });
    expect(parseRecords(out)[0]!.status).toBe("applied");
  });

  it("still works after the workflow appends a row", () => {
    const appended = appendRecord(CSV, { date: "2026-10-04", company: "Delta" });
    const out = setField(appended, 2, rows[2]!, "status", "rejected");
    expect(parseRecords(out).map((r) => r.status))
      .toEqual(["applied", "applied", "rejected", ""]);
  });

  it("refuses when the row is gone or changed", () => {
    expect(() => setField(CSV, 0, { ...rows[0]!, status: "offer" }, "status", "rejected"))
      .toThrow(/changed/);
  });

  it("keeps a BOM and LF line endings", () => {
    const lf = "﻿" + CSV.replace(/\r\n/g, "\n");
    const out = setField(lf, 2, rows[2]!, "status", "offer");
    expect(out.startsWith("﻿")).toBe(true);
    expect(out).not.toContain("\r");
    expect(out).toContain("Gamma,Backend,offer,g1\n");
  });

  it("names a missing column", () => {
    expect(() => setField(CSV, 0, rows[0]!, "nope", "x")).toThrow(/nope/);
  });
});
