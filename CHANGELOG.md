# Changelog

All notable changes to the **Android Backup & Restore Suite** are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

---

## [2.3.0] - 2026-11-11

### Added
- **Interactive Console Font Zooming**: Added `A-` and `A+` buttons to the diagnostic console header to scale the log font size dynamically between 10 pt and 24 pt.
- **Real-Time Transfer Speed Telemetry**: Added a 5th dashboard badge tracking live transfer throughput (e.g., `28.5 MB/s`), computed dynamically every 750 ms during active operations.

### Changed
- **Enlarged Console Action Buttons**: Increased button heights from `20 px` to `28 px` with rounded corners (`corner_radius=6`) and bold 11 pt typography (`📋 Copy Log`, `🧹 Clear`, `⛶ Maximize`).
- **Enlarged Default Log Font**: Upgraded diagnostic console font from `11 pt` to `13 pt Consolas` for significantly improved legibility.
- **Card-Style Telemetry Tiles**: Redesigned dashboard stat badges with high-contrast borders and backgrounds, upgrading values to `15 pt bold` and labels to `11 pt bold`.
- **Enlarged Checkboxes & Toggles**: Upgraded category selection checkboxes to `22x22 px` with `12 pt bold` labels.
- **Enlarged Primary Action Buttons**: "Start Backup", "Start Restore", and "Stop" buttons increased to `42 px height` with `14 pt bold` text.
- **Expanded Input Fields**: ADB Binary, Destination, and Restore source entry fields increased to `34 px height` with `12 pt` text.
- **Adjusted Default Window Geometry**: Default size updated to `1040x880 px` (minimum `920x720 px`) to comfortably host the larger controls and spacious log viewport.

---

## [2.2.0] - 2026-11-11

### Added
- **Smart Directory Batching Engine**:
  - Restoring and backing up files now groups items by directory into batches of up to 20 files (or 30 MB).
  - Pushes and pulls batches in a single ADB call, reducing TCP socket creation by over 95% (from ~6,500 connections to ~250).
  - Delivers a 3x–5x throughput boost over individual file transfers.
- **Seamless Batch Fallback**: If a multi-file batch encounters an I/O drop or verification mismatch, the engine automatically retries each file in that batch individually with full 3x retry protection.
- **Dedicated ADB Daemon Auto-Recovery (`_recover_adb_daemon`)**:
  - Forcefully terminates hung `adb.exe` processes (`adb kill-server` and `taskkill /F /IM adb.exe`).
  - Implements a 2.0-second cooldown allowing Windows Winsock `TIME_WAIT` states and USB controller endpoints to release.
  - Restarts the daemon and waits up to 35 seconds for the Android device to re-handshake.

### Fixed
- **Windows TCP Socket Exhaustion (`WSAETIMEDOUT 10060`)**: Solved the connection timeout error caused by thousands of rapid process spawns saturating ephemeral ports (`TIME_WAIT` backlog on `127.0.0.1:5037`).
- **Unresponsive Daemon Recovery**: Fixed issue where `adb start-server` failed to recover because a frozen daemon process was still holding port 5037.

---

## [2.1.0] - 2026-11-11

### Added
- **Console Expansion Toggle (`⛶ Maximize` / `🗕 Normal`)**: Temporarily collapses upper configuration cards, giving the live terminal over 620 px (~38 lines) of visible log height during troubleshooting.
- **`📋 Copy Log`**: One-click button to copy complete diagnostic logs to the Windows clipboard.
- **`🧹 Clear`**: Added quick log wipe button.

### Fixed
- **Restore Buttons Off-Screen**: Fixed issue where "Start Restore" and "Stop" buttons were pushed below the visible window edge by converting the Restore tab from vertically stacked cards into a responsive 2-column layout.
- **Compressed Console**: Configured dynamic grid weight on row 3 so the console expands automatically to claim all extra vertical screen real estate.

---

## [2.2.0] - 2026-11-11

### Added
- **PC → Phone Restore Subsystem**:
  - Integrated restore capability to transfer backed-up media back to the connected phone.
  - Automatic backup source inspection: scans chosen backup directory, detects all valid categories, and counts files and total bytes.
  - Path auto-resolution: automatically detects timestamped backup folders if the user selects the parent directory.
  - Selective category restore: individually toggle Camera photos, Pictures, Screenshots, Videos, Downloads, or Documents.
  - Device-side incremental verification: scans remote directories via `find ... -exec stat` to skip files that already exist on the phone with matching sizes.
  - MediaStore / Gallery Auto-Refresh: triggers Android's MediaStore scan (`content call --uri content://media --method scan_volume --arg external_primary`) so restored media appears immediately in Google Photos and Gallery apps without restarting the phone.

---

## [2.0.0] - 2026-11-11

### Added
- **CustomTkinter UI Overhaul**:
  - Complete redesign replacing plain Tkinter with modern CustomTkinter dark theme.
  - Header with custom title branding and quick `☀️ Light Mode` / `🌙 Dark Mode` toggle button.
  - Hardware connection card with real-time connection badge (🟢 connected / 🔴 disconnected) and automatic phone model detection (`getprop ro.product.model`).
  - Tabbed interface separating Backup (Phone → PC) and Restore (PC → Phone) workflows.
  - Dashboard telemetry card displaying Progress %, Files Transferred, Data Volume, and Engine Status.
  - High-contrast, color-coded diagnostic console:
    - Red (`#F87171`): Errors and transfer failures.
    - Amber (`#FBBF24`): Retries, socket cooldowns, daemon recovery notices.
    - Emerald (`#34D399`): Successful connections and completions.
    - Sky Blue (`#60A5FA`): Section headers and category progress.
- **Background Event Queue**: Decoupled worker threads from UI updates using a thread-safe `queue.Queue` to ensure a 100% stutter-free interface.

---

## [1.1.0] - 2026-11-10

### Added
- **True Incremental Backup**: Checks destination files before transfer, skipping files with matching file sizes and saving bandwidth on subsequent runs.
- **Timestamp Preservation**: Uses `adb pull -a` to ensure photo and video capture dates are preserved on the PC.
- **Dynamic File Timeouts**: Replaced static 30-second timeouts with file-size-based dynamic timeouts (`max(60, int(size / 200_000))`), preventing transfer abortions on multi-gigabyte video files.
- **3x Retry Loop with USB Recovery**: Added automatic retries with `adb wait-for-device` to withstand transient USB drops on external hubs.
- **Corrupted File Cleanup**: Deletes partial files if a transfer fails or times out, preventing corrupted assets on disk.
- **Graceful Cancellation**: Added a non-blocking `Stop` button allowing safe termination without corrupting already transferred files.

### Fixed
- **Monolithic Transfer Crashes**: Replaced brittle single-command directory pulls (`adb pull /sdcard/DCIM/Camera`) with file-by-file enumeration (`find + stat`) to prevent one failed file from aborting the entire backup.
- **Stderr Progress Parsing**: Filtered carriage-return progress percentages (`\r...%`) from stderr to stop false positive failure alerts.

---

## [1.0.0] - 2026-11-10

### Initial Release
- Basic Windows desktop backup utility for Android using ADB over USB.
- Monolithic directory `adb pull` transfers for common shared storage folders (Camera, Pictures, Movies, Download, Documents).
- Standard Tkinter graphical interface.

