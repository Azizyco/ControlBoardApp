# Soundboard Pentas (versi server lokal)

Soundboard untuk pentas drama: pad musik dan SFX, urutan cue dengan GO, potong audio,
fade, layar proyektor, rekam suara, dan backup .zip. Semua data disimpan di folder
`data/` di laptop ini, bukan di browser. Tidak butuh internet saat dipakai.

## Cara menjalankan

1. Klik dua kali **`start.bat`**.
2. Jendela hitam (server) akan terbuka, lalu browser membuka `http://localhost:8765`.
3. **Jangan tutup jendela hitam itu** selama soundboard dipakai. Untuk berhenti, tutup
   jendelanya.

Pertama kali dijalankan, `start.bat` memasang Flask. Langkah ini butuh internet,
tapi cukup sekali. Kalau Python belum terpasang, `start.bat` akan memberi tahu cara
memasangnya. Saat memasang Python, centang **"Add python.exe to PATH"**.

Saran: pakai Chrome atau Edge (fitur rekam suara tab dan layar proyektor paling
lengkap di sana).

## Pertama kali dibuka: memindahkan data lama

Kalau database masih kosong, soundboard menawarkan:

- **Impor backup .zip**: pilih file backup dari soundboard lama (tombol *Backup .zip*).
  Formatnya sama, jadi backup lama bisa langsung dipakai.
- **Mulai dengan daftar cue bawaan**: mulai dari daftar cue naskah.

Soundboard lama menyimpan data di dalam browser. Kalau data itu belum pernah dibackup:

1. Jalankan `start.bat` dulu.
2. Klik dua kali **`Pindahkan_Data_Lama.html`**. Buka di browser yang sama dengan
   yang dulu dipakai untuk `Soundboard Pentas.html`.
3. Klik **Kirim ke soundboard baru**, lalu klik **Pindahkan** di tab soundboard.

Kalau cara itu gagal, buka `Soundboard Pentas.html` yang lama, klik *Backup .zip*,
lalu di soundboard baru klik *Pulihkan* dan pilih file itu.

## Memindah data ke laptop lain

Semua data ada di folder **`data/`**:

```
data/
  soundboard.db   daftar suara, background, dan pengaturan
  audio/          file audio
  images/         gambar dan video background
```

Caranya:

1. Tutup jendela server dulu supaya database tidak sedang ditulis.
2. Salin **seluruh folder soundboard** (berisi `app.py`, `start.bat`, `static/`,
   `data/`) ke flashdisk, lalu tempel di laptop lain.
3. Di laptop lain, klik dua kali `start.bat`.

Kalau di laptop lain sudah ada folder soundboard, cukup ganti folder `data/` di sana
dengan yang baru. Cara lain: buat *Backup .zip* di laptop lama, lalu *Pulihkan* di
laptop baru.

**Laptop tujuan tidak punya internet?** Di laptop yang punya internet, jalankan perintah
ini di folder soundboard:

```
python -m pip download -r requirements.txt -d wheels
```

Ikutkan folder `wheels/` saat menyalin. `start.bat` akan memasang Flask dari folder
itu tanpa internet. Python sendiri tetap harus sudah terpasang.

## Kalau port 8765 sudah dipakai

Jendela server akan menulis **"Port 8765 sudah dipakai program lain"**.

- Kalau soundboard sendiri sudah berjalan (misalnya `start.bat` diklik dua kali),
  `start.bat` langsung membuka browser ke soundboard yang sudah jalan. Tidak perlu
  apa-apa.
- Kalau port itu dipakai program lain, tutup program itu atau restart laptop.
- Kalau tetap bentrok, buka `start.bat` dengan Notepad, ubah baris
  `set "SOUNDBOARD_PORT=8765"` menjadi `set "SOUNDBOARD_PORT=8766"`, lalu simpan.
  Soundboard sekarang ada di `http://localhost:8766`. Data tidak hilang karena
  data tersimpan di folder `data/`, bukan di browser.

## Catatan

- Server hanya bisa dibuka dari laptop ini (`127.0.0.1`). HP atau laptop lain di
  jaringan yang sama tidak bisa mengaksesnya.
- `Soundboard Pentas.html` yang asli tidak diubah dan tidak dipakai lagi oleh versi
  ini. File itu sengaja disimpan untuk mengambil data lama.
- Pintasan keyboard tetap sama: **Spasi** GO, **Esc** stop semua, **↑/↓** pilih cue,
  **B** gelapkan proyektor, huruf/angka di pad = tombol pintas.
