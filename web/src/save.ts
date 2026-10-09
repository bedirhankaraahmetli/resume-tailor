// Getting files onto the device.
//
// Chrome and Edge: the File System Access API. The user picks `Desktop/Job Applications`
// once; the handle is kept in IndexedDB and permission is re-requested when the browser
// drops it. Safari and iPhone have no directory picker, so they get downloads and the
// share sheet (`navigator.share({ files })`, which offers "Save to Files").

export interface OutFile {
  name: string;
  data: Uint8Array;
  type: string;
}

interface DirHandle {
  name: string;
  getDirectoryHandle(name: string, o?: { create?: boolean }): Promise<DirHandle>;
  getFileHandle(name: string, o?: { create?: boolean }): Promise<{
    createWritable(): Promise<{ write(d: BufferSource | Blob): Promise<void>; close(): Promise<void> }>;
  }>;
  queryPermission(o: { mode: "readwrite" }): Promise<PermissionState>;
  requestPermission(o: { mode: "readwrite" }): Promise<PermissionState>;
}

type Picker = (o?: { id?: string; mode?: "readwrite"; startIn?: string }) => Promise<DirHandle>;

export function canSaveToFolder(): boolean {
  return typeof (window as unknown as { showDirectoryPicker?: Picker }).showDirectoryPicker
    === "function";
}

const DB = "resume-tailor";
const STORE = "handles";

function idb<T>(mode: IDBTransactionMode, fn: (s: IDBObjectStore) => IDBRequest): Promise<T> {
  return new Promise((resolve, reject) => {
    const open = indexedDB.open(DB, 1);
    open.onupgradeneeded = () => open.result.createObjectStore(STORE);
    open.onerror = () => reject(open.error);
    open.onsuccess = () => {
      const tx = open.result.transaction(STORE, mode);
      const req = fn(tx.objectStore(STORE));
      req.onsuccess = () => resolve(req.result as T);
      req.onerror = () => reject(req.error);
      tx.oncomplete = () => open.result.close();
    };
  });
}

export async function savedFolderName(): Promise<string | null> {
  try {
    return (await idb<DirHandle | undefined>("readonly", (s) => s.get("root")))?.name ?? null;
  } catch {
    return null;
  }
}

export async function chooseFolder(): Promise<DirHandle> {
  const picker = (window as unknown as { showDirectoryPicker: Picker }).showDirectoryPicker;
  const handle = await picker({ id: "job-applications", mode: "readwrite", startIn: "desktop" });
  await idb("readwrite", (s) => s.put(handle, "root"));
  return handle;
}

/** Must be called from a click: requesting permission needs a user gesture. */
async function root(): Promise<DirHandle> {
  let handle: DirHandle | undefined;
  try {
    handle = await idb<DirHandle | undefined>("readonly", (s) => s.get("root"));
  } catch {
    handle = undefined;
  }
  if (!handle) return chooseFolder();
  const mode = { mode: "readwrite" as const };
  if ((await handle.queryPermission(mode)) === "granted") return handle;
  if ((await handle.requestPermission(mode)) === "granted") return handle;
  throw new Error("Permission to write to the folder was not given.");
}

/** Writes the files into <chosen folder>/<sub...>/ and returns the path written to. */
export async function saveToFolder(sub: string[], files: OutFile[]): Promise<string> {
  let dir = await root();
  const path = [dir.name];
  for (const part of sub) {
    dir = await dir.getDirectoryHandle(part, { create: true });
    path.push(part);
  }
  for (const f of files) {
    const w = await (await dir.getFileHandle(f.name, { create: true })).createWritable();
    await w.write(f.data as BufferSource);
    await w.close();
  }
  return path.join("/");
}

export function download(file: OutFile): void {
  const url = URL.createObjectURL(new Blob([file.data as BlobPart], { type: file.type }));
  const a = document.createElement("a");
  a.href = url;
  a.download = file.name;
  document.body.append(a);
  a.click();
  a.remove();
  setTimeout(() => URL.revokeObjectURL(url), 30_000);
}

export function canShareFiles(): boolean {
  try {
    const probe = new File([""], "x.pdf", { type: "application/pdf" });
    return typeof navigator.canShare === "function" && navigator.canShare({ files: [probe] });
  } catch {
    return false;
  }
}

export async function share(files: OutFile[], title: string): Promise<void> {
  const list = files.map((f) => new File([f.data as BlobPart], f.name, { type: f.type }));
  try {
    await navigator.share({ files: list, title });
  } catch (e) {
    if (e instanceof DOMException && e.name === "AbortError") return; // user closed the sheet
    throw e;
  }
}
