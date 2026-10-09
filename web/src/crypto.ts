// The token is encrypted at rest with a passphrase (docs/PLAN.md §2.7). Every GitHub Pages
// project of a user shares one origin and so one localStorage; a plain token there would
// be readable by any of them.

import nacl from "tweetnacl";
import { blake2b } from "blakejs";
import { concat, fromBase64, fromUtf8, toBase64, utf8 } from "./bytes";

export const PBKDF2_ITERATIONS = 600_000; // OWASP 2023 figure for PBKDF2-HMAC-SHA256

export interface Sealed {
  v: 1;
  iterations: number;
  salt: string; // base64
  iv: string; // base64
  ct: string; // base64, AES-GCM ciphertext + tag
}

async function deriveKey(passphrase: string, salt: Uint8Array, iterations: number) {
  const base = await crypto.subtle.importKey("raw", utf8(passphrase) as BufferSource, "PBKDF2",
    false, ["deriveKey"]);
  return crypto.subtle.deriveKey(
    { name: "PBKDF2", hash: "SHA-256", salt: salt as BufferSource, iterations },
    base, { name: "AES-GCM", length: 256 }, false, ["encrypt", "decrypt"],
  );
}

export async function encryptText(plain: string, passphrase: string,
                                  iterations = PBKDF2_ITERATIONS): Promise<Sealed> {
  const salt = crypto.getRandomValues(new Uint8Array(16));
  const iv = crypto.getRandomValues(new Uint8Array(12));
  const key = await deriveKey(passphrase, salt, iterations);
  const ct = new Uint8Array(await crypto.subtle.encrypt({ name: "AES-GCM", iv }, key,
    utf8(plain) as BufferSource));
  return { v: 1, iterations, salt: toBase64(salt), iv: toBase64(iv), ct: toBase64(ct) };
}

export class WrongPassphrase extends Error {}

export async function decryptText(sealed: Sealed, passphrase: string): Promise<string> {
  const key = await deriveKey(passphrase, fromBase64(sealed.salt), sealed.iterations);
  try {
    const plain = await crypto.subtle.decrypt({ name: "AES-GCM",
      iv: fromBase64(sealed.iv) as BufferSource }, key, fromBase64(sealed.ct) as BufferSource);
    return fromUtf8(new Uint8Array(plain));
  } catch {
    throw new WrongPassphrase("Wrong passphrase. Try again.");
  }
}

/**
 * libsodium's crypto_box_seal, which GitHub requires for Actions secrets: an ephemeral
 * X25519 key pair, nonce = BLAKE2b-192(ephemeral_pk || recipient_pk), and the output is
 * ephemeral_pk || crypto_box(message). WebCrypto has X25519 but not XSalsa20-Poly1305, so
 * this uses tweetnacl. test/crypto.test.ts opens the result with real libsodium.
 */
export function sealedBox(message: Uint8Array, recipientPublicKey: Uint8Array): Uint8Array {
  const eph = nacl.box.keyPair();
  const nonce = blake2b(concat(eph.publicKey, recipientPublicKey), undefined, 24);
  const boxed = nacl.box(message, nonce, recipientPublicKey, eph.secretKey);
  eph.secretKey.fill(0);
  return concat(eph.publicKey, boxed);
}
