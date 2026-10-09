import sodium from "libsodium-wrappers";
import { describe, expect, it } from "vitest";
import { utf8 } from "../src/bytes";
import { decryptText, encryptText, sealedBox, WrongPassphrase } from "../src/crypto";

describe("token vault", () => {
  it("round-trips and rejects a wrong passphrase", async () => {
    const sealed = await encryptText("github_pat_example", "correct horse", 1000);
    expect(JSON.stringify(sealed)).not.toContain("github_pat_example");
    expect(await decryptText(sealed, "correct horse")).toBe("github_pat_example");
    await expect(decryptText(sealed, "wrong")).rejects.toBeInstanceOf(WrongPassphrase);
  });

  it("uses a fresh salt and IV every time", async () => {
    const a = await encryptText("x", "p", 1000);
    const b = await encryptText("x", "p", 1000);
    expect(a.salt).not.toBe(b.salt);
    expect(a.ct).not.toBe(b.ct);
  });
});

describe("sealed box", () => {
  it("is opened by real libsodium (what GitHub uses)", async () => {
    await sodium.ready;
    const kp = sodium.crypto_box_keypair();
    const sealed = sealedBox(utf8("sk-ant-test-value"), kp.publicKey);
    const opened = sodium.crypto_box_seal_open(sealed, kp.publicKey, kp.privateKey);
    expect(sodium.to_string(opened)).toBe("sk-ant-test-value");
  });
});
