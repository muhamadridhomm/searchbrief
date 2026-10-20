const DATABASE_NAME = "searchbrief-local";
const STORE_NAME = "content";
const SOURCE_STORE = "sources";
export const LIBRARY_FORMAT = "searchbrief-library";
export const LIBRARY_VERSION = 1;

function openDatabase() {
  return new Promise((resolve, reject) => {
    if (typeof indexedDB === "undefined") {
      reject(new Error("This browser does not support local library storage."));
      return;
    }
    const request = indexedDB.open(DATABASE_NAME, 2);
    request.onupgradeneeded = () => {
      const database = request.result;
      if (!database.objectStoreNames.contains(STORE_NAME)) {
        const store = database.createObjectStore(STORE_NAME, { keyPath: "id" });
        store.createIndex("updatedAt", "updatedAt");
        store.createIndex("status", "status");
      }
      if (!database.objectStoreNames.contains(SOURCE_STORE)) {
        const store = database.createObjectStore(SOURCE_STORE, { keyPath: "id" });
        store.createIndex("savedAt", "savedAt");
      }
    };
    request.onsuccess = () => resolve(request.result);
    request.onerror = () => reject(request.error || new Error("Could not open local library."));
  });
}

async function withStore(mode, operation, storeName = STORE_NAME) {
  const database = await openDatabase();
  return new Promise((resolve, reject) => {
    const transaction = database.transaction(storeName, mode);
    const store = transaction.objectStore(storeName);
    let request;
    try {
      request = operation(store);
    } catch (error) {
      database.close();
      reject(error);
      return;
    }
    transaction.oncomplete = () => {
      database.close();
      resolve(request?.result);
    };
    transaction.onerror = () => {
      database.close();
      reject(transaction.error || request?.error || new Error("Local library operation failed."));
    };
    transaction.onabort = () => {
      database.close();
      reject(transaction.error || new Error("Local library operation was cancelled."));
    };
  });
}

export async function listContent() {
  const rows = await withStore("readonly", (store) => store.getAll());
  return rows.sort((a, b) => b.updatedAt.localeCompare(a.updatedAt));
}

export function saveContent(item) {
  return withStore("readwrite", (store) => store.put(item));
}

export function deleteContent(id) {
  return withStore("readwrite", (store) => store.delete(id));
}

export async function listSources() {
  const rows = await withStore("readonly", (store) => store.getAll(), SOURCE_STORE);
  return rows.sort((a, b) => b.savedAt.localeCompare(a.savedAt));
}

export function saveSource(source) {
  return withStore("readwrite", (store) => store.put(source), SOURCE_STORE);
}

export function deleteSource(id) {
  return withStore("readwrite", (store) => store.delete(id), SOURCE_STORE);
}

export async function mergeSources(items) {
  const database = await openDatabase();
  return new Promise((resolve, reject) => {
    const transaction = database.transaction(SOURCE_STORE, "readwrite");
    const store = transaction.objectStore(SOURCE_STORE);
    items.forEach((item) => store.put(item));
    transaction.oncomplete = () => { database.close(); resolve(); };
    transaction.onerror = () => { database.close(); reject(transaction.error || new Error("Could not import sources.")); };
    transaction.onabort = () => { database.close(); reject(transaction.error || new Error("Source import was cancelled.")); };
  });
}

export function makeSourceFile(items) {
  return { format: "searchbrief-sources", version: 1, exportedAt: new Date().toISOString(), sources: items };
}

export function parseSourceFile(value) {
  if (!value || value.format !== "searchbrief-sources" || value.version !== 1 || !Array.isArray(value.sources) || value.sources.length > 200) {
    throw new Error("This is not a supported SearchBrief Source Library file.");
  }
  const valid = value.sources.every((item) => {
    if (!item || typeof item.id !== "string" || item.id.length > 60 || typeof item.title !== "string" || item.title.length > 180 ||
        typeof item.summary !== "string" || item.summary.length > 1200 || typeof item.savedAt !== "string") return false;
    if (item.url == null || item.url === "") return true;
    try { return ["http:", "https:"].includes(new URL(item.url).protocol); } catch { return false; }
  });
  if (!valid) throw new Error("Some saved sources have invalid fields or links. Nothing was imported.");
  return value.sources;
}

export async function replaceContent(items) {
  const database = await openDatabase();
  return new Promise((resolve, reject) => {
    const transaction = database.transaction(STORE_NAME, "readwrite");
    const store = transaction.objectStore(STORE_NAME);
    store.clear();
    items.forEach((item) => store.put(item));
    transaction.oncomplete = () => {
      database.close();
      resolve();
    };
    transaction.onerror = () => {
      database.close();
      reject(transaction.error || new Error("Could not replace local library."));
    };
    transaction.onabort = () => {
      database.close();
      reject(transaction.error || new Error("Library replacement was cancelled."));
    };
  });
}

export function makeLibraryFile(items) {
  return {
    format: LIBRARY_FORMAT,
    version: LIBRARY_VERSION,
    exportedAt: new Date().toISOString(),
    contents: items,
  };
}

export function parseLibraryFile(value) {
  if (!value || value.format !== LIBRARY_FORMAT || value.version !== LIBRARY_VERSION || !Array.isArray(value.contents)) {
    throw new Error("This is not a supported SearchBrief Library file.");
  }
  const valid = value.contents.every((item) =>
    item && typeof item.id === "string" && typeof item.title === "string" &&
    ["draft", "approved", "archived"].includes(item.status) &&
    item.form && Array.isArray(item.form.evidence) && item.writing &&
    item.result && typeof item.draft === "string" &&
    typeof item.createdAt === "string" && typeof item.updatedAt === "string"
  );
  if (!valid) throw new Error("Some Library items are incomplete or have an unsupported shape. Nothing was imported.");
  return value.contents;
}
