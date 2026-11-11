# Android Backup & Restore

A Windows desktop utility that backs up and restores common Android media and files over USB using ADB.

## Requirements

1. Windows 10 or later.
2. Python 3.10+.
3. CustomTkinter:
   ```powershell
   pip install customtkinter
   ```
4. Android Platform Tools (`adb.exe`), available from [Google](https://developer.android.com/tools/releases/platform-tools).
5. On the phone: enable **Developer options** and **USB debugging**, connect the phone, then accept the authorization prompt.

## Run

From PowerShell:

```powershell
python .\android_backup.py
```

If `adb` is not on `PATH`, use **Browse...** to select `adb.exe`.

---

## Features

### 1. Backup (Phone → PC)
- **Selectable Categories**: Back up Camera photos and videos, Screenshots, Pictures, Videos, Downloads, and Documents.
- **Smart Directory Batching**: Groups files by folder and streams them efficiently in batches, preventing Windows TCP socket exhaustion (error 10060) and accelerating transfer speeds.
- **Incremental Backup**: Automatically skips files that already exist at the destination with matching file sizes.
- **Timestamp Preservation**: Keeps original photo/video capture timestamps (`adb pull -a`).
- **Resilient Transfers**: Dynamic timeouts, automatic retries, and comprehensive ADB daemon auto-recovery.
- **Cancel / Stop Support**: Stop an active operation at any time without corrupting previously transferred files.

### 2. Restore (PC → Phone)
- **Automatic Backup Inspection**: Select a backup folder, and the app automatically scans and lists all contained categories, file counts, and sizes.
- **Selective Restore**: Choose exactly which categories to restore (e.g. only Camera photos or only Downloads).
- **High-Speed Batch Restore**: Pushes photos and documents in batches to avoid overwhelming USB controllers and Windows ephemeral ports.
- **Incremental Restore**: Checks the phone's storage and skips files that are already present with matching sizes, saving significant time and bandwidth.
- **Automatic Media Library Refresh**: Triggers Android's MediaStore scanner so newly restored photos and videos appear immediately in Google Photos and Gallery apps without needing a device reboot.

---

## Connection Tips for Maximum Stability

- **Plug directly into PC motherboard USB ports**: Avoid unpowered or multi-port USB hubs, which can reset under sustained multi-gigabyte data transfers.
- **Use a high-quality USB-C data cable**: Fast-charging-only cables or cables without proper shielding can cause I/O packet drops during bulk transfers.

## Limitations

- Backs up shared storage folders such as `DCIM/Camera`, `Pictures`, `Movies`, `Download`, and `Documents`.
- App-private data (e.g. `/data/data/...`) is not accessible on non-rooted modern Android versions without app-specific backup solutions.
- The phone must remain connected with USB debugging authorized during the transfer.
