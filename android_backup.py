from __future__ import annotations

import datetime as dt
import os
import queue
import subprocess
import threading
import time
from pathlib import Path
from tkinter import filedialog, messagebox

import customtkinter as ctk

# Set global appearance and default theme
ctk.set_appearance_mode("Dark")
ctk.set_default_color_theme("blue")


PHONE_FOLDERS = {
    "Camera photos and videos": "DCIM/Camera",
    "Screenshots": "Pictures/Screenshots",
    "Pictures": "Pictures",
    "Videos": "Movies",
    "Downloads": "Download",
    "Documents": "Documents",
}

CATEGORY_ICONS = {
    "Camera photos and videos": "📷",
    "Screenshots": "📸",
    "Pictures": "🖼️",
    "Videos": "🎬",
    "Downloads": "📥",
    "Documents": "📄",
}


def format_size(bytes_val: int | float) -> str:
    val = float(bytes_val)
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if val < 1024.0 or unit == "TB":
            return f"{val:.1f} {unit}" if unit != "B" else f"{int(val)} B"
        val /= 1024.0
    return f"{val:.1f} GB"


def resolve_backup_dir(path_str: str) -> Path | None:
    p = Path(path_str).expanduser()
    if not p.is_dir():
        return None
    # Check if category folders are directly in p
    if any((p / name).is_dir() for name in PHONE_FOLDERS):
        return p
    # Check if p has backup subfolders
    subdirs = [d for d in p.iterdir() if d.is_dir() and "backup" in d.name.lower()]
    if subdirs:
        subdirs.sort(key=lambda d: d.stat().st_mtime, reverse=True)
        for s in subdirs:
            if any((s / name).is_dir() for name in PHONE_FOLDERS):
                return s
    return p


class AdbError(RuntimeError):
    pass


class BackupApp(ctk.CTk):
    def __init__(self) -> None:
        super().__init__()
        self.title("Android Transfer Suite • Backup & Restore")
        self.geometry("1040x880")
        self.minsize(920, 720)

        self.events: queue.Queue[tuple[str, object]] = queue.Queue()
        self.adb_path = ctk.StringVar(value="adb")

        # Telemetry & Font Sizing
        self.last_speed_time = 0.0
        self.last_speed_bytes = 0
        self.current_speed_str = "0.0 B/s"
        self.log_font_size = 13

        # Default paths
        default_dir = Path.home() / "Android Backups"
        local_override = Path("D:/Wondershare/New folder")
        if local_override.exists():
            default_dir = local_override

        self.destination = ctk.StringVar(value=str(default_dir))
        self.restore_source = ctk.StringVar(value=str(default_dir))

        self.status = ctk.StringVar(value="Connecting...")
        self.device_name = "No device detected"
        self.running = False
        self.stop_requested = threading.Event()
        self.current_process: subprocess.Popen[str] | None = None
        self.console_maximized = False

        # Backup options
        self.incremental_var = ctk.BooleanVar(value=True)
        self.timestamp_var = ctk.BooleanVar(value=True)
        self.folder_vars = {
            label: ctk.BooleanVar(
                value=label in ("Camera photos and videos", "Screenshots", "Pictures", "Videos", "Downloads", "Documents")
            )
            for label in PHONE_FOLDERS
        }

        # Restore options & detected data
        self.restore_incremental_var = ctk.BooleanVar(value=True)
        self.restore_scan_media_var = ctk.BooleanVar(value=True)
        self.restore_folder_vars: dict[str, ctk.BooleanVar] = {}
        self.restore_folder_widgets: dict[str, ctk.CTkCheckBox] = {}
        self.detected_restore_files: dict[str, list[Path]] = {}

        self._build_ui()
        self.after(100, self._process_events)
        self.after(300, self.detect_device)
        self.after(600, self.scan_restore_source)

    def _build_ui(self) -> None:
        # Main layout container
        self.grid_columnconfigure(0, weight=1)
        self.grid_rowconfigure(0, weight=0)
        self.grid_rowconfigure(1, weight=0)
        self.grid_rowconfigure(2, weight=0)  # Tabview takes its natural required height (~220px)
        self.grid_rowconfigure(3, weight=1)  # Activity & Console card takes ALL remaining vertical space!

        # 1. Header Bar
        self.header = ctk.CTkFrame(self, fg_color="transparent")
        self.header.grid(row=0, column=0, sticky="ew", padx=16, pady=(10, 4))
        self.header.grid_columnconfigure(0, weight=1)

        title_box = ctk.CTkFrame(self.header, fg_color="transparent")
        title_box.grid(row=0, column=0, sticky="w")
        ctk.CTkLabel(
            title_box,
            text="⚡ Android Transfer Suite",
            font=ctk.CTkFont(family="Segoe UI", size=22, weight="bold"),
        ).pack(anchor="w")
        ctk.CTkLabel(
            title_box,
            text="Fast, resilient backup & restore for photos, videos, and files over ADB USB",
            font=ctk.CTkFont(family="Segoe UI", size=12),
            text_color=("gray45", "gray70"),
        ).pack(anchor="w", pady=(1, 0))

        # Appearance mode toggle button
        self.theme_btn = ctk.CTkButton(
            self.header,
            text="☀️ Light Mode",
            command=self.toggle_theme,
            width=110,
            height=32,
            fg_color=("gray85", "gray25"),
            text_color=("gray10", "gray90"),
            hover_color=("gray75", "gray35"),
            font=ctk.CTkFont(size=12, weight="bold"),
        )
        self.theme_btn.grid(row=0, column=1, sticky="e")

        # 2. Connection Card (Compact)
        self.conn_card = ctk.CTkFrame(self, corner_radius=10)
        self.conn_card.grid(row=1, column=0, sticky="ew", padx=16, pady=(0, 6))
        self.conn_card.grid_columnconfigure(1, weight=1)

        # Row 0: ADB Path
        ctk.CTkLabel(
            self.conn_card, text="ADB Binary:", font=ctk.CTkFont(family="Segoe UI", size=12, weight="bold")
        ).grid(row=0, column=0, sticky="w", padx=(14, 6), pady=(8, 4))

        adb_entry = ctk.CTkEntry(self.conn_card, textvariable=self.adb_path, height=32, font=ctk.CTkFont(size=12))
        adb_entry.grid(row=0, column=1, sticky="ew", padx=4, pady=(8, 4))

        ctk.CTkButton(
            self.conn_card,
            text="Browse...",
            command=self.choose_adb,
            width=85,
            height=32,
            font=ctk.CTkFont(size=12, weight="bold"),
        ).grid(row=0, column=2, padx=(4, 14), pady=(8, 4))

        # Row 1: Device Status Pill + Detect Button + Stability Tip in one clean row
        status_row = ctk.CTkFrame(self.conn_card, fg_color="transparent")
        status_row.grid(row=1, column=0, columnspan=3, sticky="ew", padx=14, pady=(2, 8))
        status_row.grid_columnconfigure(3, weight=1)

        ctk.CTkLabel(
            status_row, text="Phone Device:", font=ctk.CTkFont(family="Segoe UI", size=12, weight="bold")
        ).grid(row=0, column=0, sticky="w", padx=(0, 6))

        self.device_badge = ctk.CTkLabel(
            status_row,
            text="🔴 Checking...",
            font=ctk.CTkFont(family="Segoe UI", size=12, weight="bold"),
            corner_radius=6,
            fg_color=("gray85", "gray20"),
            padx=12,
            pady=3,
        )
        self.device_badge.grid(row=0, column=1, sticky="w", padx=(0, 8))

        ctk.CTkButton(
            status_row,
            text="🔄 Detect",
            command=self.detect_device,
            width=80,
            height=28,
            font=ctk.CTkFont(size=12, weight="bold"),
        ).grid(row=0, column=2, sticky="w", padx=(0, 10))

        ctk.CTkLabel(
            status_row,
            text="💡 Tip: Connect directly to PC motherboard USB ports (avoid external USB hubs).",
            font=ctk.CTkFont(family="Segoe UI", size=11),
            text_color=("gray40", "gray70"),
        ).grid(row=0, column=3, sticky="e")

        # 3. Main Workspace Notebook / Tabview (Compact height)
        self.tabview = ctk.CTkTabview(
            self,
            corner_radius=10,
            segmented_button_font=ctk.CTkFont(family="Segoe UI", size=12, weight="bold"),
        )
        self.tabview.grid(row=2, column=0, sticky="ew", padx=16, pady=(0, 6))

        backup_tab = self.tabview.add("  📥  Backup (Phone → PC)  ")
        restore_tab = self.tabview.add("  📤  Restore (PC → Phone)  ")

        self._build_backup_tab(backup_tab)
        self._build_restore_tab(restore_tab)

        # 4. Activity & Progress Card (Expands to fill all remaining window space!)
        self.act_card = ctk.CTkFrame(self, corner_radius=10)
        self.act_card.grid(row=3, column=0, sticky="nsew", padx=16, pady=(0, 10))
        self.act_card.grid_columnconfigure(0, weight=1)

        # Stat Badges in a Row (5 Badges: Progress %, Files, Speed, Volume, State)
        stats_row = ctk.CTkFrame(self.act_card, fg_color="transparent")
        stats_row.pack(fill="x", padx=12, pady=(8, 4))
        stats_row.grid_columnconfigure((0, 1, 2, 3, 4), weight=1)

        self.metric_pct = self._make_stat_badge(stats_row, 0, "Progress", "0.0%")
        self.metric_files = self._make_stat_badge(stats_row, 1, "Files Transferred", "0 / 0")
        self.metric_speed = self._make_stat_badge(stats_row, 2, "Transfer Speed", "0.0 B/s")
        self.metric_volume = self._make_stat_badge(stats_row, 3, "Data Volume", "0 B / 0 B")
        self.metric_state = self._make_stat_badge(stats_row, 4, "Engine Status", "Idle")

        # Smooth Progress Bar
        self.progress_bar = ctk.CTkProgressBar(self.act_card, height=10, corner_radius=5)
        self.progress_bar.pack(fill="x", padx=12, pady=(4, 3))
        self.progress_bar.set(0)

        # Active File Info
        self.file_label = ctk.CTkLabel(
            self.act_card,
            text="Ready to transfer.",
            font=ctk.CTkFont(family="Segoe UI", size=12, weight="bold"),
            text_color=("gray30", "gray85"),
        )
        self.file_label.pack(anchor="w", padx=14, pady=(0, 4))

        # Terminal / Log Box Header Bar
        log_header = ctk.CTkFrame(self.act_card, fg_color="transparent")
        log_header.pack(fill="x", padx=12, pady=(4, 4))
        ctk.CTkLabel(
            log_header,
            text="Live Activity & Diagnostics Console",
            font=ctk.CTkFont(family="Segoe UI", size=13, weight="bold"),
            text_color=("gray30", "gray85"),
        ).pack(side="left")

        # Interactive Right buttons on log header: A- / A+ Zoom, Copy, Clear, Maximize
        btn_box = ctk.CTkFrame(log_header, fg_color="transparent")
        btn_box.pack(side="right")

        self.zoom_out_btn = ctk.CTkButton(
            btn_box,
            text="A-",
            command=self.zoom_log_out,
            width=36,
            height=28,
            font=ctk.CTkFont(size=12, weight="bold"),
            fg_color=("gray85", "gray25"),
            text_color=("gray10", "gray90"),
            hover_color=("gray75", "gray35"),
        )
        self.zoom_out_btn.pack(side="left", padx=2)

        self.zoom_in_btn = ctk.CTkButton(
            btn_box,
            text="A+",
            command=self.zoom_log_in,
            width=36,
            height=28,
            font=ctk.CTkFont(size=12, weight="bold"),
            fg_color=("gray85", "gray25"),
            text_color=("gray10", "gray90"),
            hover_color=("gray75", "gray35"),
        )
        self.zoom_in_btn.pack(side="left", padx=2)

        self.copy_btn = ctk.CTkButton(
            btn_box,
            text="📋 Copy Log",
            command=self.copy_log,
            width=95,
            height=28,
            font=ctk.CTkFont(size=11, weight="bold"),
            fg_color=("gray85", "gray25"),
            text_color=("gray10", "gray90"),
            hover_color=("gray75", "gray35"),
        )
        self.copy_btn.pack(side="left", padx=3)

        ctk.CTkButton(
            btn_box,
            text="🧹 Clear",
            command=self.clear_log,
            width=70,
            height=28,
            font=ctk.CTkFont(size=11, weight="bold"),
            fg_color=("gray85", "gray25"),
            text_color=("gray10", "gray90"),
            hover_color=("gray75", "gray35"),
        ).pack(side="left", padx=3)

        self.expand_btn = ctk.CTkButton(
            btn_box,
            text="⛶ Maximize",
            command=self.toggle_console_size,
            width=95,
            height=28,
            font=ctk.CTkFont(size=11, weight="bold"),
            fg_color=("gray85", "gray25"),
            text_color=("gray10", "gray90"),
            hover_color=("gray75", "gray35"),
        )
        self.expand_btn.pack(side="left", padx=(3, 0))

        # Big, expanding console textbox with enlarged default font
        self.log_font = ctk.CTkFont(family="Consolas", size=self.log_font_size)
        self.log = ctk.CTkTextbox(
            self.act_card,
            corner_radius=8,
            font=self.log_font,
            fg_color=("#1E293B", "#0F172A"),
            text_color="#F8FAFC",
            wrap="word",
        )
        self.log.pack(fill="both", expand=True, padx=12, pady=(0, 8))

        # Color tags for readable diagnostics
        self.log.tag_config("err", foreground="#F87171")
        self.log.tag_config("warn", foreground="#FBBF24")
        self.log.tag_config("ok", foreground="#34D399")
        self.log.tag_config("info", foreground="#60A5FA")
        self.log.tag_config("dim", foreground="#94A3B8")

    def _make_stat_badge(self, parent: ctk.CTkFrame, col: int, label: str, init_val: str) -> ctk.CTkLabel:
        box = ctk.CTkFrame(parent, corner_radius=8, fg_color=("gray92", "gray17"), border_width=1, border_color=("gray82", "gray25"))
        box.grid(row=0, column=col, sticky="ew", padx=3, pady=1)
        ctk.CTkLabel(
            box,
            text=label,
            font=ctk.CTkFont(family="Segoe UI", size=11, weight="bold"),
            text_color=("gray45", "gray65"),
        ).pack(anchor="center", pady=(5, 1))
        val_lbl = ctk.CTkLabel(
            box,
            text=init_val,
            font=ctk.CTkFont(family="Segoe UI", size=15, weight="bold"),
        )
        val_lbl.pack(anchor="center", pady=(0, 5))
        return val_lbl

    def _build_backup_tab(self, parent: ctk.CTkFrame) -> None:
        parent.grid_columnconfigure(0, weight=1)
        parent.grid_columnconfigure(1, weight=1)
        parent.grid_rowconfigure(0, weight=1)

        # Left Column: Folders to back up
        left_card = ctk.CTkFrame(parent, corner_radius=8)
        left_card.grid(row=0, column=0, sticky="nsew", padx=(0, 6), pady=4)
        left_card.grid_columnconfigure(0, weight=1)

        left_hdr = ctk.CTkFrame(left_card, fg_color="transparent")
        left_hdr.pack(fill="x", padx=12, pady=(8, 4))
        ctk.CTkLabel(
            left_hdr,
            text="Phone Folders to Back Up",
            font=ctk.CTkFont(family="Segoe UI", size=13, weight="bold"),
        ).pack(side="left")

        quick_box = ctk.CTkFrame(left_hdr, fg_color="transparent")
        quick_box.pack(side="right")
        ctk.CTkButton(
            quick_box,
            text="All",
            command=self.select_all_backup,
            width=48,
            height=24,
            font=ctk.CTkFont(size=11, weight="bold"),
            fg_color=("gray80", "gray25"),
            text_color=("gray10", "gray90"),
            hover_color=("gray70", "gray35"),
        ).pack(side="left", padx=2)
        ctk.CTkButton(
            quick_box,
            text="None",
            command=self.select_none_backup,
            width=48,
            height=24,
            font=ctk.CTkFont(size=11, weight="bold"),
            fg_color=("gray80", "gray25"),
            text_color=("gray10", "gray90"),
            hover_color=("gray70", "gray35"),
        ).pack(side="left")

        # Checkboxes list with larger font and larger checkbox
        for label, path in PHONE_FOLDERS.items():
            icon = CATEGORY_ICONS.get(label, "📁")
            chk = ctk.CTkCheckBox(
                left_card,
                text=f"{icon}  {label}",
                variable=self.folder_vars[label],
                font=ctk.CTkFont(family="Segoe UI", size=12, weight="bold"),
                corner_radius=5,
                checkbox_width=22,
                checkbox_height=22,
            )
            chk.pack(anchor="w", padx=14, pady=4)

        # Right Column: Destination & Options
        right_card = ctk.CTkFrame(parent, corner_radius=8)
        right_card.grid(row=0, column=1, sticky="nsew", padx=(6, 0), pady=4)
        right_card.grid_columnconfigure(0, weight=1)

        ctk.CTkLabel(
            right_card,
            text="Backup Destination & Settings",
            font=ctk.CTkFont(family="Segoe UI", size=13, weight="bold"),
        ).pack(anchor="w", padx=12, pady=(8, 6))

        # Destination input
        dest_box = ctk.CTkFrame(right_card, fg_color="transparent")
        dest_box.pack(fill="x", padx=12, pady=(0, 6))
        dest_box.grid_columnconfigure(0, weight=1)

        dest_entry = ctk.CTkEntry(dest_box, textvariable=self.destination, height=34, font=ctk.CTkFont(size=12))
        dest_entry.grid(row=0, column=0, sticky="ew", padx=(0, 6))

        ctk.CTkButton(
            dest_box,
            text="Choose...",
            command=self.choose_destination,
            width=85,
            height=34,
            font=ctk.CTkFont(size=12, weight="bold"),
        ).grid(row=0, column=1)

        # Toggles
        ctk.CTkSwitch(
            right_card,
            text="Incremental backup (skip identical files)",
            variable=self.incremental_var,
            font=ctk.CTkFont(family="Segoe UI", size=12),
            switch_width=44,
            switch_height=22,
        ).pack(anchor="w", padx=14, pady=5)

        ctk.CTkSwitch(
            right_card,
            text="Create timestamped subfolder (e.g. 2026-...)",
            variable=self.timestamp_var,
            font=ctk.CTkFont(family="Segoe UI", size=12),
            switch_width=44,
            switch_height=22,
        ).pack(anchor="w", padx=14, pady=5)

        # Action Buttons
        btn_box = ctk.CTkFrame(right_card, fg_color="transparent")
        btn_box.pack(fill="x", padx=12, pady=(16, 8))
        btn_box.grid_columnconfigure(0, weight=3)
        btn_box.grid_columnconfigure(1, weight=1)

        self.backup_start_btn = ctk.CTkButton(
            btn_box,
            text="▶  Start Backup",
            command=self.start_backup,
            font=ctk.CTkFont(family="Segoe UI", size=14, weight="bold"),
            height=42,
            fg_color="#2563EB",
            hover_color="#1D4ED8",
        )
        self.backup_start_btn.grid(row=0, column=0, sticky="ew", padx=(0, 6))

        self.backup_stop_btn = ctk.CTkButton(
            btn_box,
            text="⏹  Stop",
            command=self.stop_operation,
            font=ctk.CTkFont(family="Segoe UI", size=14, weight="bold"),
            height=42,
            fg_color="#EF4444",
            hover_color="#DC2626",
            state="disabled",
        )
        self.backup_stop_btn.grid(row=0, column=1, sticky="ew")

    def _build_restore_tab(self, parent: ctk.CTkFrame) -> None:
        parent.grid_columnconfigure(0, weight=1)
        parent.grid_columnconfigure(1, weight=1)
        parent.grid_rowconfigure(1, weight=1)

        # Top: Backup source picker in a single clean row
        top_card = ctk.CTkFrame(parent, corner_radius=8)
        top_card.grid(row=0, column=0, columnspan=2, sticky="ew", padx=2, pady=(2, 6))
        top_card.grid_columnconfigure(1, weight=1)

        ctk.CTkLabel(
            top_card,
            text="Backup Folder:",
            font=ctk.CTkFont(family="Segoe UI", size=12, weight="bold"),
        ).grid(row=0, column=0, sticky="w", padx=(14, 6), pady=6)

        ctk.CTkEntry(top_card, textvariable=self.restore_source, height=34, font=ctk.CTkFont(size=12)).grid(
            row=0, column=1, sticky="ew", padx=(0, 6), pady=6
        )
        ctk.CTkButton(
            top_card,
            text="Browse...",
            command=self.choose_restore_source,
            width=85,
            height=34,
            font=ctk.CTkFont(size=12, weight="bold"),
        ).grid(row=0, column=2, padx=(0, 6), pady=6)
        ctk.CTkButton(
            top_card,
            text="🔍 Scan",
            command=self.scan_restore_source,
            width=85,
            height=34,
            font=ctk.CTkFont(size=12, weight="bold"),
        ).grid(row=0, column=3, padx=(0, 12), pady=6)

        # Left Column: Detected Contents
        left_card = ctk.CTkFrame(parent, corner_radius=8)
        left_card.grid(row=1, column=0, sticky="nsew", padx=(2, 5), pady=(0, 2))
        left_card.grid_columnconfigure(0, weight=1)

        mid_hdr = ctk.CTkFrame(left_card, fg_color="transparent")
        mid_hdr.pack(fill="x", padx=12, pady=(8, 4))
        ctk.CTkLabel(
            mid_hdr,
            text="Detected Backup Contents",
            font=ctk.CTkFont(family="Segoe UI", size=13, weight="bold"),
        ).pack(side="left")

        quick_box = ctk.CTkFrame(mid_hdr, fg_color="transparent")
        quick_box.pack(side="right")
        ctk.CTkButton(
            quick_box,
            text="All",
            command=self.select_all_restore,
            width=48,
            height=24,
            font=ctk.CTkFont(size=11, weight="bold"),
            fg_color=("gray80", "gray25"),
            text_color=("gray10", "gray90"),
            hover_color=("gray70", "gray35"),
        ).pack(side="left", padx=2)
        ctk.CTkButton(
            quick_box,
            text="None",
            command=self.select_none_restore,
            width=48,
            height=24,
            font=ctk.CTkFont(size=11, weight="bold"),
            fg_color=("gray80", "gray25"),
            text_color=("gray10", "gray90"),
            hover_color=("gray70", "gray35"),
        ).pack(side="left")

        # Category checkboxes list with larger font and larger checkbox
        for label, path in PHONE_FOLDERS.items():
            icon = CATEGORY_ICONS.get(label, "📁")
            var = ctk.BooleanVar(value=False)
            self.restore_folder_vars[label] = var
            chk = ctk.CTkCheckBox(
                left_card,
                text=f"{icon}  {label} — (Scanning...)",
                variable=var,
                font=ctk.CTkFont(family="Segoe UI", size=12, weight="bold"),
                corner_radius=5,
                checkbox_width=22,
                checkbox_height=22,
                state="disabled",
            )
            chk.pack(anchor="w", padx=14, pady=3)
            self.restore_folder_widgets[label] = chk

        # Right Column: Settings & Action Buttons
        right_card = ctk.CTkFrame(parent, corner_radius=8)
        right_card.grid(row=1, column=1, sticky="nsew", padx=(5, 2), pady=(0, 2))
        right_card.grid_columnconfigure(0, weight=1)

        ctk.CTkLabel(
            right_card,
            text="Restore Settings & Actions",
            font=ctk.CTkFont(family="Segoe UI", size=13, weight="bold"),
        ).pack(anchor="w", padx=12, pady=(8, 6))

        ctk.CTkSwitch(
            right_card,
            text="Incremental restore (skip identical files)",
            variable=self.restore_incremental_var,
            font=ctk.CTkFont(family="Segoe UI", size=12),
            switch_width=44,
            switch_height=22,
        ).pack(anchor="w", padx=14, pady=5)

        ctk.CTkSwitch(
            right_card,
            text="Refresh Android Gallery / MediaStore",
            variable=self.restore_scan_media_var,
            font=ctk.CTkFont(family="Segoe UI", size=12),
            switch_width=44,
            switch_height=22,
        ).pack(anchor="w", padx=14, pady=5)

        # Action Buttons prominently placed in Right Card
        restore_btn_box = ctk.CTkFrame(right_card, fg_color="transparent")
        restore_btn_box.pack(fill="x", padx=12, pady=(16, 8))
        restore_btn_box.grid_columnconfigure(0, weight=3)
        restore_btn_box.grid_columnconfigure(1, weight=1)

        self.restore_start_btn = ctk.CTkButton(
            restore_btn_box,
            text="🚀  Start Restore",
            command=self.start_restore,
            font=ctk.CTkFont(family="Segoe UI", size=14, weight="bold"),
            height=42,
            fg_color="#059669",
            hover_color="#047857",
        )
        self.restore_start_btn.grid(row=0, column=0, sticky="ew", padx=(0, 6))

        self.restore_stop_btn = ctk.CTkButton(
            restore_btn_box,
            text="⏹  Stop",
            command=self.stop_operation,
            font=ctk.CTkFont(family="Segoe UI", size=14, weight="bold"),
            height=42,
            fg_color="#EF4444",
            hover_color="#DC2626",
            state="disabled",
        )
        self.restore_stop_btn.grid(row=0, column=1, sticky="ew")

    def toggle_theme(self) -> None:
        current = ctk.get_appearance_mode()
        if current.lower() == "dark":
            ctk.set_appearance_mode("Light")
            self.theme_btn.configure(text="🌙 Dark Mode")
        else:
            ctk.set_appearance_mode("Dark")
            self.theme_btn.configure(text="☀️ Light Mode")

    def toggle_console_size(self) -> None:
        if self.console_maximized:
            # Restore normal view
            self.tabview.grid()
            self.conn_card.grid()
            self.expand_btn.configure(text="⛶ Maximize")
            self.console_maximized = False
        else:
            # Maximize console view
            self.tabview.grid_remove()
            self.conn_card.grid_remove()
            self.expand_btn.configure(text="🗕 Restore")
            self.console_maximized = True

    def choose_adb(self) -> None:
        path = filedialog.askopenfilename(
            title="Select adb.exe", filetypes=[("ADB executable", "adb.exe"), ("All files", "*.*")]
        )
        if path:
            self.adb_path.set(path)
            self.detect_device()

    def choose_destination(self) -> None:
        path = filedialog.askdirectory(title="Choose backup destination")
        if path:
            self.destination.set(path)

    def choose_restore_source(self) -> None:
        path = filedialog.askdirectory(title="Choose backup folder to restore")
        if path:
            self.restore_source.set(path)
            self.scan_restore_source()

    def select_all_backup(self) -> None:
        for var in self.folder_vars.values():
            var.set(True)

    def select_none_backup(self) -> None:
        for var in self.folder_vars.values():
            var.set(False)

    def select_all_restore(self) -> None:
        for label, var in self.restore_folder_vars.items():
            if label in self.detected_restore_files and self.detected_restore_files[label]:
                var.set(True)

    def select_none_restore(self) -> None:
        for var in self.restore_folder_vars.values():
            var.set(False)

    def zoom_log_in(self) -> None:
        if self.log_font_size < 24:
            self.log_font_size += 1
            self.log_font.configure(size=self.log_font_size)

    def zoom_log_out(self) -> None:
        if self.log_font_size > 10:
            self.log_font_size -= 1
            self.log_font.configure(size=self.log_font_size)

    def clear_log(self) -> None:
        self.log.configure(state="normal")
        self.log.delete("1.0", "end")
        self.log.configure(state="disabled")

    def copy_log(self) -> None:
        text = self.log.get("1.0", "end-1c")
        self.clipboard_clear()
        self.clipboard_append(text)
        self.copy_btn.configure(text="✓ Copied!")
        self.after(1500, lambda: self.copy_btn.configure(text="📋 Copy Log"))

    def scan_restore_source(self) -> None:
        resolved = resolve_backup_dir(self.restore_source.get())
        if resolved is None or not resolved.is_dir():
            for label, chk in self.restore_folder_widgets.items():
                icon = CATEGORY_ICONS.get(label, "📁")
                chk.configure(text=f"{icon}  {label} — (Folder not found)", state="disabled")
                self.restore_folder_vars[label].set(False)
            return

        if resolved != Path(self.restore_source.get()):
            self.restore_source.set(str(resolved))

        self.detected_restore_files.clear()
        for label, phone_path in PHONE_FOLDERS.items():
            icon = CATEGORY_ICONS.get(label, "📁")
            cat_dir = resolved / label
            chk = self.restore_folder_widgets[label]
            var = self.restore_folder_vars[label]
            if cat_dir.is_dir():
                files = [p for p in cat_dir.rglob("*") if p.is_file()]
                if files:
                    total_bytes = sum(p.stat().st_size for p in files)
                    chk.configure(
                        text=f"{icon}  {label} — {len(files):,} files ({format_size(total_bytes)})",
                        state="normal",
                    )
                    var.set(True)
                    self.detected_restore_files[label] = files
                    continue

            chk.configure(text=f"{icon}  {label} — (Not in backup)", state="disabled")
            var.set(False)

    def _run_adb(self, *args: str, timeout: int = 30, check: bool = True) -> subprocess.CompletedProcess[str]:
        try:
            result = subprocess.run(
                [self.adb_path.get(), *args],
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=timeout,
                check=False,
            )
        except (OSError, subprocess.SubprocessError) as exc:
            raise AdbError(f"Could not run ADB: {exc}") from exc
        if check and result.returncode != 0:
            lines = [
                l.strip()
                for l in (result.stderr or result.stdout).splitlines()
                if l.strip() and not l.strip().endswith("%")
            ]
            detail = lines[-1] if lines else f"ADB exited with code {result.returncode}."
            raise AdbError(detail)
        return result

    def detect_device(self) -> None:
        try:
            result = self._run_adb("get-state", timeout=10)
            if result.stdout.strip() != "device":
                raise AdbError("No authorized Android device found.")
            model = self._run_adb("shell", "getprop", "ro.product.model", timeout=10).stdout.strip()
            self.device_name = model or "Android Device"
            self.device_badge.configure(
                text=f"🟢 {self.device_name} (Connected)",
                fg_color=("#DCFCE7", "#14532D"),
                text_color=("#166534", "#4ADE80"),
            )
            self.status.set("Ready.")
            self._write_log(f"[Connected] Phone: {self.device_name}")
        except AdbError as exc:
            self.device_name = "No device detected"
            self.device_badge.configure(
                text="🔴 Disconnected",
                fg_color=("#FEE2E2", "#7F1D1D"),
                text_color=("#991B1B", "#FCA5A5"),
            )
            self.status.set(str(exc))

    def _list_remote_files(self, rel_path: str) -> list[tuple[str, str, int | None]]:
        phone_root = f"/sdcard/{rel_path.strip('/')}"
        cmd = f'find "{phone_root}" -type f -exec stat -c "%s %n" {{}} + 2>/dev/null'
        res = self._run_adb("shell", cmd, timeout=90, check=False)
        items: list[tuple[str, str, int | None]] = []
        prefix = phone_root.rstrip("/") + "/"

        if res.returncode == 0 and res.stdout.strip():
            for line in res.stdout.splitlines():
                line = line.strip()
                if not line:
                    continue
                parts = line.split(maxsplit=1)
                if len(parts) == 2 and parts[0].isdigit():
                    size = int(parts[0])
                    full_p = parts[1]
                    rel_p = full_p[len(prefix):] if full_p.startswith(prefix) else os.path.basename(full_p)
                    items.append((full_p, rel_p, size))

        if not items:
            fallback_cmd = f'find "{phone_root}" -type f 2>/dev/null'
            res = self._run_adb("shell", fallback_cmd, timeout=90, check=False)
            if res.returncode == 0 and res.stdout.strip():
                for line in res.stdout.splitlines():
                    full_p = line.strip()
                    if not full_p:
                        continue
                    rel_p = full_p[len(prefix):] if full_p.startswith(prefix) else os.path.basename(full_p)
                    items.append((full_p, rel_p, None))

        return items

    def _get_remote_file_map(self, rel_path: str) -> dict[str, int]:
        phone_root = f"/sdcard/{rel_path.strip('/')}"
        cmd = f'find "{phone_root}" -type f -exec stat -c "%s %n" {{}} + 2>/dev/null'
        res = self._run_adb("shell", cmd, timeout=90, check=False)
        mapping: dict[str, int] = {}
        prefix = phone_root.rstrip("/") + "/"

        if res.returncode == 0 and res.stdout.strip():
            for line in res.stdout.splitlines():
                line = line.strip()
                if not line:
                    continue
                parts = line.split(maxsplit=1)
                if len(parts) == 2 and parts[0].isdigit():
                    size = int(parts[0])
                    full_p = parts[1]
                    rel_p = full_p[len(prefix):] if full_p.startswith(prefix) else os.path.basename(full_p)
                    mapping[rel_p] = size
        return mapping

    def _recover_adb_daemon(self) -> bool:
        self.events.put(("log", "  [Daemon Recovery] Resetting ADB server to clear sockets and re-establish USB link..."))
        adb_bin = self.adb_path.get()
        try:
            subprocess.run([adb_bin, "kill-server"], timeout=5, check=False)
        except Exception:
            pass
        try:
            subprocess.run(["taskkill", "/F", "/IM", "adb.exe"], capture_output=True, timeout=5, check=False)
        except Exception:
            pass
        time.sleep(2.0)
        try:
            subprocess.run([adb_bin, "start-server"], timeout=10, check=False)
        except Exception:
            pass
        time.sleep(1.0)
        try:
            res = subprocess.run([adb_bin, "wait-for-device"], timeout=35, check=False)
            if res.returncode == 0:
                self.events.put(("log", "  [Daemon Recovery] Reconnected successfully to device."))
                return True
        except Exception:
            pass
        self.events.put(("log", "  [Daemon Recovery] Device still initializing, waiting 3s..."))
        time.sleep(3.0)
        return False

    def _pull_file_with_retry(
        self,
        full_path: str,
        target_path: Path,
        remote_size: int | None,
        max_attempts: int = 3,
    ) -> tuple[bool, str]:
        target_path.parent.mkdir(parents=True, exist_ok=True)
        timeout = max(60, int((remote_size or 0) / 200_000))

        last_err = ""
        for attempt in range(1, max_attempts + 1):
            if self.stop_requested.is_set():
                return False, "Cancelled by user"

            try:
                proc = subprocess.Popen(
                    [self.adb_path.get(), "pull", "-a", full_path, str(target_path)],
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    text=True,
                    encoding="utf-8",
                    errors="replace",
                )
                self.current_process = proc
                try:
                    stdout, stderr = proc.communicate(timeout=timeout)
                except subprocess.TimeoutExpired:
                    proc.kill()
                    last_err = f"Transfer timed out after {timeout}s"
                    continue
                finally:
                    self.current_process = None

                if proc.returncode == 0 and target_path.is_file():
                    if remote_size is None or target_path.stat().st_size == remote_size:
                        return True, ""
                    else:
                        last_err = f"Size mismatch: expected {remote_size}B, got {target_path.stat().st_size}B"
                else:
                    err_lines = [
                        l.strip()
                        for l in (stderr or stdout).splitlines()
                        if l.strip() and not l.strip().endswith("%")
                    ]
                    last_err = err_lines[-1] if err_lines else f"ADB pull failed (code {proc.returncode})"

            except Exception as exc:
                last_err = str(exc)

            if target_path.exists():
                try:
                    target_path.unlink()
                except Exception:
                    pass

            if self.stop_requested.is_set():
                return False, "Cancelled by user"

            # Check for socket exhaustion / daemon disconnect errors
            is_conn_error = any(
                x in last_err.lower()
                for x in (
                    "cannot connect",
                    "10060",
                    "device offline",
                    "device not found",
                    "write terminated",
                    "connection reset",
                    "closed",
                )
            )
            if is_conn_error:
                self.events.put(
                    ("log", f"  [Connection Issue] {target_path.name}: {last_err}. Recovering ADB connection...")
                )
                self._recover_adb_daemon()
            else:
                self.events.put(
                    ("log", f"  [Retry {attempt}/{max_attempts}] {target_path.name}: {last_err}. Waiting for device...")
                )
                try:
                    subprocess.run([self.adb_path.get(), "wait-for-device"], timeout=35, check=False)
                except Exception:
                    pass
                time.sleep(1.0)

        return False, last_err

    def _push_file_with_retry(
        self,
        local_path: Path,
        remote_path: str,
        local_size: int,
        max_attempts: int = 3,
    ) -> tuple[bool, str]:
        timeout = max(60, int(local_size / 200_000))
        last_err = ""
        for attempt in range(1, max_attempts + 1):
            if self.stop_requested.is_set():
                return False, "Cancelled by user"

            try:
                proc = subprocess.Popen(
                    [self.adb_path.get(), "push", str(local_path), remote_path],
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    text=True,
                    encoding="utf-8",
                    errors="replace",
                )
                self.current_process = proc
                try:
                    stdout, stderr = proc.communicate(timeout=timeout)
                except subprocess.TimeoutExpired:
                    proc.kill()
                    last_err = f"Transfer timed out after {timeout}s"
                    continue
                finally:
                    self.current_process = None

                if proc.returncode == 0:
                    return True, ""
                else:
                    err_lines = [
                        l.strip()
                        for l in (stderr or stdout).splitlines()
                        if l.strip() and not l.strip().endswith("%")
                    ]
                    last_err = err_lines[-1] if err_lines else f"ADB push failed (code {proc.returncode})"

            except Exception as exc:
                last_err = str(exc)

            if self.stop_requested.is_set():
                return False, "Cancelled by user"

            # Check for socket exhaustion / daemon disconnect errors
            is_conn_error = any(
                x in last_err.lower()
                for x in (
                    "cannot connect",
                    "10060",
                    "device offline",
                    "device not found",
                    "write terminated",
                    "connection reset",
                    "closed",
                )
            )
            if is_conn_error:
                self.events.put(
                    ("log", f"  [Connection Issue] {local_path.name}: {last_err}. Recovering ADB connection...")
                )
                self._recover_adb_daemon()
            else:
                self.events.put(
                    ("log", f"  [Retry {attempt}/{max_attempts}] {local_path.name}: {last_err}. Waiting for device...")
                )
                try:
                    subprocess.run([self.adb_path.get(), "wait-for-device"], timeout=35, check=False)
                except Exception:
                    pass
                time.sleep(1.0)

        return False, last_err

    def start_backup(self) -> None:
        if self.running:
            return
        selected = [
            (label, path) for label, path in PHONE_FOLDERS.items() if self.folder_vars[label].get()
        ]
        selected = [
            (label, path)
            for label, path in selected
            if not any(
                other_path != path and path.startswith(other_path + "/")
                for _, other_path in selected
            )
        ]
        if not selected:
            messagebox.showwarning("Nothing selected", "Select at least one phone folder.")
            return
        target = Path(self.destination.get()).expanduser()
        if not str(target).strip():
            messagebox.showwarning("Destination required", "Choose a backup destination.")
            return

        self._set_running_state(is_running=True, is_backup=True)
        self.status.set("Starting backup...")
        self.progress_bar.set(0)
        self.metric_pct.configure(text="0.0%")
        self.metric_state.configure(text="Scanning")
        self.file_label.configure(text="Scanning phone folders...")

        use_timestamp = self.timestamp_var.get()
        incremental = self.incremental_var.get()

        threading.Thread(
            target=self._backup_worker,
            args=(selected, target, use_timestamp, incremental),
            daemon=True,
        ).start()

    def start_restore(self) -> None:
        if self.running:
            return
        resolved = resolve_backup_dir(self.restore_source.get())
        if resolved is None or not resolved.is_dir():
            messagebox.showerror("Invalid backup folder", "Select a valid backup folder.")
            return

        selected_categories: list[tuple[str, str, list[Path]]] = []
        for label, phone_path in PHONE_FOLDERS.items():
            if self.restore_folder_vars[label].get():
                files = self.detected_restore_files.get(label, [])
                if files:
                    selected_categories.append((label, phone_path, files))

        if not selected_categories:
            messagebox.showwarning("Nothing selected", "Select at least one category to restore.")
            return

        total_files = sum(len(f) for _, _, f in selected_categories)
        total_bytes = sum(sum(p.stat().st_size for p in f) for _, _, f in selected_categories)

        confirmed = messagebox.askyesno(
            "Confirm Restore",
            f"Restore {total_files:,} files ({format_size(total_bytes)}) from:\n{resolved}\n\nto your connected {self.device_name}?",
            default=messagebox.YES,
        )
        if not confirmed:
            return

        self._set_running_state(is_running=True, is_backup=False)
        self.status.set("Starting restore...")
        self.progress_bar.set(0)
        self.metric_pct.configure(text="0.0%")
        self.metric_state.configure(text="Preparing")
        self.file_label.configure(text="Preparing restore...")

        incremental = self.restore_incremental_var.get()
        scan_media = self.restore_scan_media_var.get()

        threading.Thread(
            target=self._restore_worker,
            args=(resolved, selected_categories, incremental, scan_media),
            daemon=True,
        ).start()

    def stop_operation(self) -> None:
        if not self.running:
            return
        self.stop_requested.set()
        self.status.set("Stopping operation, please wait...")
        self.metric_state.configure(text="Stopping")
        self.backup_stop_btn.configure(state="disabled")
        self.restore_stop_btn.configure(state="disabled")
        if self.current_process:
            try:
                self.current_process.terminate()
            except Exception:
                pass

    def _backup_worker(
        self,
        selected: list[tuple[str, str]],
        target_root: Path,
        use_timestamp: bool,
        incremental: bool,
    ) -> None:
        if use_timestamp:
            backup_dir = target_root / dt.datetime.now().strftime("Android Backup %Y-%m-%d %H-%M-%S")
        else:
            backup_dir = target_root / "Android Backup"

        try:
            backup_dir.mkdir(parents=True, exist_ok=False) if not backup_dir.exists() else None
            self.events.put(("log", f"=== Starting Backup ==="))
            self.events.put(("log", f"Destination: {backup_dir}"))
            self.events.put(("log", "Scanning phone folders..."))

            folders_files: list[tuple[str, str, list[tuple[str, str, int | None]]]] = []
            total_file_count = 0
            total_bytes = 0

            for label, phone_path in selected:
                if self.stop_requested.is_set():
                    break
                self.events.put(("status", f"Scanning {label}..."))
                files = self._list_remote_files(phone_path)
                folder_bytes = sum(sz for _, _, sz in files if sz is not None)
                total_file_count += len(files)
                total_bytes += folder_bytes
                folders_files.append((label, phone_path, files))
                self.events.put(("log", f"  Found {len(files):,} files in {label} ({format_size(folder_bytes)})"))

            if self.stop_requested.is_set():
                self.events.put(("stopped", "Backup cancelled by user during scan."))
                return

            self.events.put(("log", f"Total: {total_file_count:,} files ({format_size(total_bytes)}) to process.\n"))

            copied_count = 0
            copied_bytes = 0
            skipped_count = 0
            skipped_bytes = 0
            failed_count = 0
            failed_files: list[str] = []

            processed_count = 0
            processed_bytes = 0

            for label, phone_path, files in folders_files:
                if self.stop_requested.is_set():
                    break
                self.events.put(("log", f"--- Backing up {label} ({len(files):,} files) ---"))
                folder_dest = backup_dir / label
                folder_dest.mkdir(parents=True, exist_ok=True)

                files_to_transfer: list[tuple[str, str, int]] = []

                for full_path, rel_path, remote_size in files:
                    if self.stop_requested.is_set():
                        break

                    file_size = remote_size or 0
                    target_file = folder_dest / rel_path

                    if incremental and target_file.is_file():
                        if remote_size is None or target_file.stat().st_size == remote_size:
                            skipped_count += 1
                            skipped_bytes += file_size
                            processed_count += 1
                            processed_bytes += file_size
                            self.events.put(
                                (
                                    "progress",
                                    (processed_count, total_file_count, processed_bytes, total_bytes, rel_path, "Backing up"),
                                )
                            )
                            continue

                    files_to_transfer.append((full_path, rel_path, file_size))

                if self.stop_requested.is_set():
                    break

                # Group files by local target directory
                dir_groups: dict[Path, list[tuple[str, str, int]]] = {}
                for full_path, rel_path, file_size in files_to_transfer:
                    local_target_dir = (folder_dest / rel_path).parent
                    dir_groups.setdefault(local_target_dir, []).append((full_path, rel_path, file_size))

                for local_target_dir, group_items in dir_groups.items():
                    if self.stop_requested.is_set():
                        break

                    local_target_dir.mkdir(parents=True, exist_ok=True)

                    batches: list[list[tuple[str, str, int]]] = []
                    current_batch: list[tuple[str, str, int]] = []
                    current_batch_bytes = 0

                    for item in group_items:
                        f_sz = item[2]
                        if f_sz >= 20 * 1024 * 1024:
                            if current_batch:
                                batches.append(current_batch)
                                current_batch = []
                                current_batch_bytes = 0
                            batches.append([item])
                        else:
                            if len(current_batch) >= 20 or (current_batch_bytes + f_sz > 30 * 1024 * 1024 and current_batch):
                                batches.append(current_batch)
                                current_batch = []
                                current_batch_bytes = 0
                            current_batch.append(item)
                            current_batch_bytes += f_sz
                    if current_batch:
                        batches.append(current_batch)

                    for batch in batches:
                        if self.stop_requested.is_set():
                            break

                        if len(batch) == 1:
                            full_path, rel_path, file_size = batch[0]
                            target_file = folder_dest / rel_path
                            self.events.put(
                                (
                                    "progress",
                                    (processed_count, total_file_count, processed_bytes, total_bytes, rel_path, "Backing up"),
                                )
                            )
                            success, err_msg = self._pull_file_with_retry(full_path, target_file, file_size)
                            if success:
                                copied_count += 1
                                copied_bytes += file_size
                            else:
                                if self.stop_requested.is_set():
                                    break
                                failed_count += 1
                                failed_files.append(f"{label}/{rel_path}: {err_msg}")
                                self.events.put(("log", f"  [Failed] {label}/{rel_path} - {err_msg}"))

                            processed_count += 1
                            processed_bytes += file_size
                            self.events.put(
                                (
                                    "progress",
                                    (processed_count, total_file_count, processed_bytes, total_bytes, rel_path, "Backing up"),
                                )
                            )
                            time.sleep(0.04)

                        else:
                            # Batch pull: adb pull -a remote1 remote2 ... local_target_dir
                            remote_paths = [item[0] for item in batch]
                            batch_bytes = sum(item[2] for item in batch)
                            timeout = max(60, int(batch_bytes / 200_000))
                            first_name = Path(batch[0][1]).name
                            self.events.put(
                                (
                                    "progress",
                                    (processed_count, total_file_count, processed_bytes, total_bytes, f"Batch ({len(batch)} files): {first_name} ...", "Backing up"),
                                )
                            )

                            batch_success = False
                            batch_err = ""
                            try:
                                proc = subprocess.Popen(
                                    [self.adb_path.get(), "pull", "-a"] + remote_paths + [str(local_target_dir)],
                                    stdout=subprocess.PIPE,
                                    stderr=subprocess.PIPE,
                                    text=True,
                                    encoding="utf-8",
                                    errors="replace",
                                )
                                self.current_process = proc
                                try:
                                    stdout, stderr = proc.communicate(timeout=timeout)
                                except subprocess.TimeoutExpired:
                                    proc.kill()
                                    batch_err = f"Batch pull timed out after {timeout}s"
                                finally:
                                    self.current_process = None

                                if proc.returncode == 0:
                                    all_ok = True
                                    for full_path, rel_path, file_size in batch:
                                        t_file = folder_dest / rel_path
                                        if not t_file.is_file() or (file_size > 0 and t_file.stat().st_size != file_size):
                                            all_ok = False
                                            break
                                    if all_ok:
                                        batch_success = True
                                    else:
                                        batch_err = "One or more files had size mismatch or missing after pull"
                                else:
                                    err_lines = [
                                        l.strip()
                                        for l in (stderr or stdout).splitlines()
                                        if l.strip() and not l.strip().endswith("%")
                                    ]
                                    batch_err = err_lines[-1] if err_lines else f"ADB batch pull failed (code {proc.returncode})"
                            except Exception as exc:
                                batch_err = str(exc)

                            if batch_success:
                                for full_path, rel_path, file_size in batch:
                                    copied_count += 1
                                    copied_bytes += file_size
                                    processed_count += 1
                                    processed_bytes += file_size
                                    self.events.put(
                                        (
                                            "progress",
                                            (processed_count, total_file_count, processed_bytes, total_bytes, rel_path, "Backing up"),
                                        )
                                    )
                                time.sleep(0.06)

                            else:
                                if self.stop_requested.is_set():
                                    break
                                self.events.put(
                                    ("log", f"  [Notice] Batch pull ({len(batch)} files) had an issue: {batch_err}. Retrying individually...")
                                )
                                if any(x in batch_err.lower() for x in ("cannot connect", "10060", "device offline", "device not found")):
                                    self._recover_adb_daemon()

                                for full_path, rel_path, file_size in batch:
                                    if self.stop_requested.is_set():
                                        break
                                    target_file = folder_dest / rel_path
                                    self.events.put(
                                        (
                                            "progress",
                                            (processed_count, total_file_count, processed_bytes, total_bytes, rel_path, "Backing up"),
                                        )
                                    )
                                    success, err_msg = self._pull_file_with_retry(full_path, target_file, file_size)
                                    if success:
                                        copied_count += 1
                                        copied_bytes += file_size
                                    else:
                                        if self.stop_requested.is_set():
                                            break
                                        failed_count += 1
                                        failed_files.append(f"{label}/{rel_path}: {err_msg}")
                                        self.events.put(("log", f"  [Failed] {label}/{rel_path} - {err_msg}"))

                                    processed_count += 1
                                    processed_bytes += file_size
                                    self.events.put(
                                        (
                                            "progress",
                                            (processed_count, total_file_count, processed_bytes, total_bytes, rel_path, "Backing up"),
                                        )
                                    )
                                    time.sleep(0.04)

            if self.stop_requested.is_set():
                summary = (
                    f"Backup stopped by user.\n"
                    f"Copied: {copied_count:,} files ({format_size(copied_bytes)})\n"
                    f"Skipped: {skipped_count:,} files ({format_size(skipped_bytes)})\n"
                    f"Failed: {failed_count:,} files"
                )
                self.events.put(("stopped", summary))
                return

            summary = (
                f"Backup completed successfully!\n\n"
                f"Folder: {backup_dir}\n"
                f"Copied: {copied_count:,} files ({format_size(copied_bytes)})\n"
                f"Skipped (already backed up): {skipped_count:,} files ({format_size(skipped_bytes)})\n"
                f"Failed: {failed_count:,} files"
            )
            if failed_files:
                summary += "\n\nFailed items:\n" + "\n".join(failed_files[:5])
                if len(failed_files) > 5:
                    summary += f"\n...and {len(failed_files) - 5} more."

            self.events.put(("done", summary))

        except Exception as exc:
            self.events.put(("error", f"Backup failed: {exc}"))

    def _restore_worker(
        self,
        backup_dir: Path,
        selected_categories: list[tuple[str, str, list[Path]]],
        incremental: bool,
        scan_media: bool,
    ) -> None:
        try:
            self.events.put(("log", f"=== Starting Restore ==="))
            self.events.put(("log", f"Source folder: {backup_dir}"))
            self.events.put(("status", "Preparing restore..."))

            total_file_count = sum(len(files) for _, _, files in selected_categories)
            total_bytes = sum(sum(p.stat().st_size for p in files) for _, _, files in selected_categories)

            self.events.put(("log", f"Total files to restore: {total_file_count:,} ({format_size(total_bytes)})\n"))

            restored_count = 0
            restored_bytes = 0
            skipped_count = 0
            skipped_bytes = 0
            failed_count = 0
            failed_files: list[str] = []

            processed_count = 0
            processed_bytes = 0

            for label, phone_path, local_files in selected_categories:
                if self.stop_requested.is_set():
                    break

                self.events.put(("log", f"--- Restoring {label} ({len(local_files):,} files) ---"))
                self.events.put(("status", f"Checking phone destination: /sdcard/{phone_path}..."))

                existing_remote: dict[str, int] = {}
                if incremental:
                    existing_remote = self._get_remote_file_map(phone_path)

                cat_dir = backup_dir / label
                files_to_transfer: list[tuple[Path, str, int]] = []

                for local_file in local_files:
                    if self.stop_requested.is_set():
                        break

                    file_size = local_file.stat().st_size
                    rel_path = local_file.relative_to(cat_dir).as_posix()

                    if incremental and rel_path in existing_remote:
                        if existing_remote[rel_path] == file_size:
                            skipped_count += 1
                            skipped_bytes += file_size
                            processed_count += 1
                            processed_bytes += file_size
                            self.events.put(
                                (
                                    "progress",
                                    (processed_count, total_file_count, processed_bytes, total_bytes, rel_path, "Restoring"),
                                )
                            )
                            continue

                    files_to_transfer.append((local_file, rel_path, file_size))

                if self.stop_requested.is_set():
                    break

                # Group files by their destination directory on phone
                dir_groups: dict[str, list[tuple[Path, str, int]]] = {}
                for f_local, rel_path, f_size in files_to_transfer:
                    rel_parent = Path(rel_path).parent.as_posix()
                    if rel_parent == ".":
                        remote_target_dir = f"/sdcard/{phone_path}"
                    else:
                        remote_target_dir = f"/sdcard/{phone_path}/{rel_parent}"
                    dir_groups.setdefault(remote_target_dir, []).append((f_local, rel_path, f_size))

                for remote_dir, group_items in dir_groups.items():
                    if self.stop_requested.is_set():
                        break

                    # Ensure target directory exists on phone
                    try:
                        self._run_adb("shell", "mkdir", "-p", f'"{remote_dir}"', timeout=20, check=False)
                    except Exception:
                        pass

                    # Chunk into batches of up to 20 files or up to 30 MB (files >= 20 MB are sent alone)
                    batches: list[list[tuple[Path, str, int]]] = []
                    current_batch: list[tuple[Path, str, int]] = []
                    current_batch_bytes = 0

                    for item in group_items:
                        f_sz = item[2]
                        if f_sz >= 20 * 1024 * 1024:
                            if current_batch:
                                batches.append(current_batch)
                                current_batch = []
                                current_batch_bytes = 0
                            batches.append([item])
                        else:
                            if len(current_batch) >= 20 or (current_batch_bytes + f_sz > 30 * 1024 * 1024 and current_batch):
                                batches.append(current_batch)
                                current_batch = []
                                current_batch_bytes = 0
                            current_batch.append(item)
                            current_batch_bytes += f_sz
                    if current_batch:
                        batches.append(current_batch)

                    # Transfer each batch
                    for batch in batches:
                        if self.stop_requested.is_set():
                            break

                        if len(batch) == 1:
                            f_local, rel_path, f_size = batch[0]
                            remote_file_path = f"{remote_dir}/{Path(rel_path).name}"
                            self.events.put(
                                (
                                    "progress",
                                    (processed_count, total_file_count, processed_bytes, total_bytes, rel_path, "Restoring"),
                                )
                            )
                            success, err_msg = self._push_file_with_retry(f_local, remote_file_path, f_size)
                            if success:
                                restored_count += 1
                                restored_bytes += f_size
                            else:
                                if self.stop_requested.is_set():
                                    break
                                failed_count += 1
                                failed_files.append(f"{label}/{rel_path}: {err_msg}")
                                self.events.put(("log", f"  [Failed] {label}/{rel_path} - {err_msg}"))

                            processed_count += 1
                            processed_bytes += f_size
                            self.events.put(
                                (
                                    "progress",
                                    (processed_count, total_file_count, processed_bytes, total_bytes, rel_path, "Restoring"),
                                )
                            )
                            time.sleep(0.04)

                        else:
                            # Multi-file batch push
                            batch_paths = [str(item[0]) for item in batch]
                            batch_bytes = sum(item[2] for item in batch)
                            timeout = max(60, int(batch_bytes / 200_000))

                            first_rel = batch[0][1]
                            self.events.put(
                                (
                                    "progress",
                                    (processed_count, total_file_count, processed_bytes, total_bytes, f"Batch ({len(batch)} files): {first_rel} ...", "Restoring"),
                                )
                            )

                            batch_success = False
                            batch_err = ""
                            try:
                                proc = subprocess.Popen(
                                    [self.adb_path.get(), "push"] + batch_paths + [f"{remote_dir}/"],
                                    stdout=subprocess.PIPE,
                                    stderr=subprocess.PIPE,
                                    text=True,
                                    encoding="utf-8",
                                    errors="replace",
                                )
                                self.current_process = proc
                                try:
                                    stdout, stderr = proc.communicate(timeout=timeout)
                                except subprocess.TimeoutExpired:
                                    proc.kill()
                                    batch_err = f"Batch push timed out after {timeout}s"
                                finally:
                                    self.current_process = None

                                if proc.returncode == 0:
                                    batch_success = True
                                else:
                                    err_lines = [
                                        l.strip()
                                        for l in (stderr or stdout).splitlines()
                                        if l.strip() and not l.strip().endswith("%")
                                    ]
                                    batch_err = err_lines[-1] if err_lines else f"ADB batch push failed (code {proc.returncode})"
                            except Exception as exc:
                                batch_err = str(exc)

                            if batch_success:
                                for f_local, rel_path, f_size in batch:
                                    restored_count += 1
                                    restored_bytes += f_size
                                    processed_count += 1
                                    processed_bytes += f_size
                                    self.events.put(
                                        (
                                            "progress",
                                            (processed_count, total_file_count, processed_bytes, total_bytes, rel_path, "Restoring"),
                                        )
                                    )
                                # Brief breathing pause between batches to protect USB hub buffers
                                time.sleep(0.06)

                            else:
                                if self.stop_requested.is_set():
                                    break
                                self.events.put(
                                    ("log", f"  [Notice] Batch push ({len(batch)} files) had an issue: {batch_err}. Retrying individually...")
                                )
                                if any(x in batch_err.lower() for x in ("cannot connect", "10060", "device offline", "device not found")):
                                    self._recover_adb_daemon()

                                for f_local, rel_path, f_size in batch:
                                    if self.stop_requested.is_set():
                                        break
                                    remote_file_path = f"{remote_dir}/{Path(rel_path).name}"
                                    self.events.put(
                                        (
                                            "progress",
                                            (processed_count, total_file_count, processed_bytes, total_bytes, rel_path, "Restoring"),
                                        )
                                    )
                                    success, err_msg = self._push_file_with_retry(f_local, remote_file_path, f_size)
                                    if success:
                                        restored_count += 1
                                        restored_bytes += f_size
                                    else:
                                        if self.stop_requested.is_set():
                                            break
                                        failed_count += 1
                                        failed_files.append(f"{label}/{rel_path}: {err_msg}")
                                        self.events.put(("log", f"  [Failed] {label}/{rel_path} - {err_msg}"))

                                    processed_count += 1
                                    processed_bytes += f_size
                                    self.events.put(
                                        (
                                            "progress",
                                            (processed_count, total_file_count, processed_bytes, total_bytes, rel_path, "Restoring"),
                                        )
                                    )
                                    time.sleep(0.04)

            if self.stop_requested.is_set():
                summary = (
                    f"Restore stopped by user.\n"
                    f"Restored: {restored_count:,} files ({format_size(restored_bytes)})\n"
                    f"Skipped: {skipped_count:,} files ({format_size(skipped_bytes)})\n"
                    f"Failed: {failed_count:,} files"
                )
                self.events.put(("stopped", summary))
                return

            if scan_media and restored_count > 0:
                self.events.put(("log", "\nRefreshing Android MediaStore / Gallery database..."))
                self.events.put(("status", "Refreshing Android Gallery..."))
                try:
                    self._run_adb(
                        "shell",
                        "content",
                        "call",
                        "--uri",
                        "content://media",
                        "--method",
                        "scan_volume",
                        "--arg",
                        "external_primary",
                        timeout=30,
                        check=False,
                    )
                    self.events.put(("log", "Media library refreshed. Photos and videos will appear in your Gallery/Photos app."))
                except Exception as exc:
                    self.events.put(("log", f"Notice: Could not trigger media scan: {exc}"))

            summary = (
                f"Restore completed successfully!\n\n"
                f"Source: {backup_dir}\n"
                f"Restored to phone: {restored_count:,} files ({format_size(restored_bytes)})\n"
                f"Skipped (already on phone): {skipped_count:,} files ({format_size(skipped_bytes)})\n"
                f"Failed: {failed_count:,} files"
            )
            if failed_files:
                summary += "\n\nFailed items:\n" + "\n".join(failed_files[:5])
                if len(failed_files) > 5:
                    summary += f"\n...and {len(failed_files) - 5} more."

            self.events.put(("done", summary))

        except Exception as exc:
            self.events.put(("error", f"Restore failed: {exc}"))

    def _set_running_state(self, is_running: bool, is_backup: bool = True) -> None:
        self.running = is_running
        self.stop_requested.clear()
        if is_running:
            if is_backup:
                self.backup_start_btn.configure(state="disabled")
                self.backup_stop_btn.configure(state="normal")
                self.restore_start_btn.configure(state="disabled")
                self.restore_stop_btn.configure(state="disabled")
            else:
                self.backup_start_btn.configure(state="disabled")
                self.backup_stop_btn.configure(state="disabled")
                self.restore_start_btn.configure(state="disabled")
                self.restore_stop_btn.configure(state="normal")
        else:
            self.backup_start_btn.configure(state="normal")
            self.backup_stop_btn.configure(state="disabled")
            self.restore_start_btn.configure(state="normal")
            self.restore_stop_btn.configure(state="disabled")

    def _process_events(self) -> None:
        try:
            while True:
                event, value = self.events.get_nowait()
                if event == "log":
                    self._write_log(str(value))
                elif event == "status":
                    self.status.set(str(value))
                elif event == "progress":
                    cur_idx, total_cnt, cur_bytes, total_b, cur_file, action = value  # type: ignore
                    pct = (cur_bytes / total_b * 100) if total_b > 0 else (cur_idx / total_cnt * 100 if total_cnt > 0 else 0)
                    self.progress_bar.set(min(1.0, max(0.0, pct / 100.0)))
                    self.metric_pct.configure(text=f"{pct:.1f}%")
                    self.metric_files.configure(text=f"{cur_idx:,} / {total_cnt:,}")
                    self.metric_volume.configure(text=f"{format_size(cur_bytes)} / {format_size(total_b)}")
                    self.metric_state.configure(text=action)
                    self.file_label.configure(text=f"📄 {cur_file}")

                    # Real-time transfer speed calculation
                    now = time.time()
                    if self.last_speed_time == 0.0:
                        self.last_speed_time = now
                        self.last_speed_bytes = cur_bytes
                    elif now - self.last_speed_time >= 0.75:
                        elapsed = now - self.last_speed_time
                        byte_delta = max(0, cur_bytes - self.last_speed_bytes)
                        speed = byte_delta / elapsed
                        self.current_speed_str = f"{format_size(speed)}/s"
                        self.metric_speed.configure(text=self.current_speed_str)
                        self.last_speed_time = now
                        self.last_speed_bytes = cur_bytes

                elif event == "done":
                    self.last_speed_time = 0.0
                    self.last_speed_bytes = 0
                    self.metric_speed.configure(text="0.0 B/s")
                    self.status.set("Operation completed successfully.")
                    self.metric_state.configure(text="Completed")
                    self.file_label.configure(text="Finished.")
                    self._write_log(f"\n{value}\n")
                    messagebox.showinfo("Operation complete", str(value))
                    self._set_running_state(is_running=False)
                elif event == "error":
                    self.last_speed_time = 0.0
                    self.last_speed_bytes = 0
                    self.metric_speed.configure(text="0.0 B/s")
                    self.status.set("Operation failed.")
                    self.metric_state.configure(text="Failed")
                    self._write_log(f"\n[ERROR] {value}\n")
                    messagebox.showerror("Error", str(value))
                    self._set_running_state(is_running=False)
                elif event == "stopped":
                    self.last_speed_time = 0.0
                    self.last_speed_bytes = 0
                    self.metric_speed.configure(text="0.0 B/s")
                    self.status.set("Operation stopped.")
                    self.metric_state.configure(text="Stopped")
                    self.file_label.configure(text="Stopped by user.")
                    self._write_log(f"\n[STOPPED] {value}\n")
                    messagebox.showwarning("Stopped", str(value))
                    self._set_running_state(is_running=False)
        except queue.Empty:
            pass
        self.after(100, self._process_events)

    def _write_log(self, text: str) -> None:
        self.log.configure(state="normal")
        # Apply color-coded styling tags based on message prefix
        line = text + "\n"
        if text.startswith("[Failed]") or text.startswith("[ERROR]"):
            self.log.insert("end", line, "err")
        elif (
            text.startswith("  [Retry")
            or text.startswith("  [TCP")
            or text.startswith("  [Connection Issue]")
            or text.startswith("  [Daemon Recovery]")
            or text.startswith("  [Notice]")
            or text.startswith("[Warning]")
        ):
            self.log.insert("end", line, "warn")
        elif text.startswith("[Connected]") or "completed successfully" in text or text.startswith("Finished"):
            self.log.insert("end", line, "ok")
        elif text.startswith("===") or text.startswith("---") or "[Recovery]" in text:
            self.log.insert("end", line, "info")
        else:
            self.log.insert("end", line)

        self.log.see("end")
        self.log.configure(state="disabled")


if __name__ == "__main__":
    BackupApp().mainloop()
