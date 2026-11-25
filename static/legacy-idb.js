/* Membaca data Soundboard Pentas versi lama (yang menyimpan semuanya di IndexedDB browser)
   lalu mengemasnya menjadi file backup .zip dengan format yang sama seperti tombol "Backup .zip".
   Dipakai oleh static/index.html dan Pindahkan_Data_Lama.html. Butuh JSZip. */
"use strict";
window.LegacyIDB = (() => {
  const NAME = "soundboard-pentas";

  async function exists() {
    if (!window.indexedDB) return false;
    try {
      if (typeof indexedDB.databases === "function") {
        const list = await indexedDB.databases();
        return list.some((d) => d.name === NAME);
      }
    } catch (e) { /* tidak didukung: coba buka langsung */ }
    return true;
  }

  // Membuka database yang SUDAH ADA. Kalau belum ada, pembuatan dibatalkan supaya
  // tidak meninggalkan database kosong di browser.
  function openExisting() {
    return new Promise((resolve) => {
      let req;
      try { req = indexedDB.open(NAME); } catch (e) { resolve(null); return; }
      req.onupgradeneeded = () => { try { req.transaction.abort(); } catch (e) { /* ignore */ } };
      req.onsuccess = () => resolve(req.result);
      req.onerror = () => resolve(null);
      req.onblocked = () => resolve(null);
    });
  }

  function readStore(db, store) {
    return new Promise((resolve) => {
      if (!db.objectStoreNames.contains(store)) { resolve({ keys: [], values: [] }); return; }
      try {
        const t = db.transaction(store, "readonly");
        const s = t.objectStore(store);
        const out = { keys: [], values: [] };
        const rk = s.getAllKeys(), rv = s.getAll();
        rk.onsuccess = () => { out.keys = rk.result; };
        rv.onsuccess = () => { out.values = rv.result; };
        t.oncomplete = () => resolve(out);
        t.onerror = t.onabort = () => resolve({ keys: [], values: [] });
      } catch (e) { resolve({ keys: [], values: [] }); }
    });
  }

  const toMap = (r) => { const m = new Map(); r.keys.forEach((k, i) => m.set(k, r.values[i])); return m; };

  /** @returns {Promise<null|{title,master,sounds,bgs,audio:Map,images:Map,counts}>} */
  async function read() {
    if (!(await exists())) return null;
    const db = await openExisting();
    if (!db) return null;
    try {
      const [sounds, bgs, audio, images, meta] = await Promise.all(
        ["sounds", "bgs", "audio", "images", "meta"].map((s) => readStore(db, s)));
      const settings = toMap(meta).get("settings") || {};
      const data = {
        title: settings.title || "",
        master: settings.master ?? 1,
        sounds: sounds.values.filter((s) => s && s.id),
        bgs: bgs.values.filter((b) => b && b.id),
        audio: toMap(audio),
        images: toMap(images),
      };
      data.counts = {
        sounds: data.sounds.length,
        soundFiles: data.sounds.filter((s) => s.hasAudio && data.audio.get(s.id) instanceof Blob).length,
        bgs: data.bgs.length,
        bgFiles: data.bgs.filter((b) => b.hasMedia && data.images.get(b.id) instanceof Blob).length,
      };
      return data;
    } finally {
      try { db.close(); } catch (e) { /* ignore */ }
    }
  }

  function summary(d) {
    const c = d.counts;
    return `${c.sounds} suara (${c.soundFiles} dengan file audio), ${c.bgs} background (${c.bgFiles} dengan gambar/video)`;
  }

  // Format sama persis dengan backup() di soundboard lama.
  async function toZip(d) {
    const z = new JSZip();
    const meta = { app: "soundboard-pentas", version: 2, title: d.title || "Pertunjukan", master: d.master ?? 1, sounds: [], bgs: [] };
    for (const s of d.sounds) {
      const entry = { ...s };
      const blob = d.audio.get(s.id);
      if (s.hasAudio && blob instanceof Blob) {
        const ext = (String(s.fileName || "").match(/\.[a-z0-9]+$/i) || [".audio"])[0];
        entry.audioFile = `audio/${s.id}${ext}`;
        z.file(entry.audioFile, blob);
      }
      meta.sounds.push(entry);
    }
    for (const b of d.bgs) {
      const entry = { ...b };
      const blob = d.images.get(b.id);
      if (b.hasMedia && blob instanceof Blob) {
        const ext = (String(b.fileName || "").match(/\.[a-z0-9]+$/i) || [b.kind === "video" ? ".mp4" : ".jpg"])[0];
        entry.mediaFile = `bg/${b.id}${ext}`;
        z.file(entry.mediaFile, blob);
      }
      meta.bgs.push(entry);
    }
    z.file("soundboard.json", JSON.stringify(meta, null, 2));
    return await z.generateAsync({ type: "blob", compression: "STORE" });
  }

  return { read, summary, toZip };
})();
