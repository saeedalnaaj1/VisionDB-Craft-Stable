"""VisionDB Craft setup wizard (tkinter - ships with Python, nothing to install).

One window, three pages:  choose  ->  progress  ->  done.
All real work happens in setup_app.SetupEngine; this file only shows it.

Layout rules that keep the Start button reachable on every screen:
  * the footer (buttons) of each page is packed FIRST, so it can never be pushed out of view;
  * the window is sized from the screen (never taller than 88 % of it) and centred;
  * the body of each page scrolls if the content still does not fit (large fonts / high DPI).
"""
from __future__ import annotations

import os
import queue
import subprocess
import sys
import threading
import time
import tkinter as tk
from tkinter import font as tkfont
from tkinter import messagebox, ttk
from pathlib import Path

import setup_app
from setup_app import Options, SetupEngine

ROOT = setup_app.ROOT
_EDITION, _TITLE = setup_app.read_edition(ROOT)
HAI = setup_app.is_hai(_TITLE)
if HAI:     # h.ai brand: ivory, forest and terracotta
    BG, CARD, LINE = "#F7F5F0", "#FFFFFF", "#D8D2C4"
    TEXT, MUTED = "#17211D", "#5B6B63"
    MINT, MINT_HOVER, INK = "#C75A25", "#D9692F", "#FFFFFF"          # accent / primary button
    OK, WARN, FAIL, INFO = "#2F7D5B", "#B7791F", "#C0392B", "#5B6B63"
    BTN2, BTN2_HOVER, DISABLED_FG, THIN = "#E6E0D2", "#D8D2C4", "#9AA59F", "#8BA396"
    LOGO, ICON = "hai-logo.png", "hai.ico"
else:       # original VisionDB Craft: ink and mint
    BG, CARD, LINE = "#0e1b28", "#162636", "#27405a"
    TEXT, MUTED = "#f0f6fa", "#93a9bb"
    MINT, MINT_HOVER, INK = "#2dd4bf", "#5eead4", "#0b1620"
    OK, WARN, FAIL, INFO = "#2dd4bf", "#fbbf24", "#f87171", "#93a9bb"
    BTN2, BTN2_HOVER, DISABLED_FG, THIN = LINE, "#35557a", "#5d7488", "#3f9c8f"
    LOGO, ICON = "visiondb-craft-logo.png", "visiondb-craft.ico"
GLYPH = {"ok": ("●", OK), "warn": ("▲", WARN), "fail": ("■", FAIL), "info": ("●", INFO)}
BASE_W, BASE_H = 960, 600                    # design size at 100 % scaling (16:10, landscape)


def format_time(seconds: float) -> str:
    seconds = int(seconds)
    return f"{seconds // 60:d}:{seconds % 60:02d}"


class Scroll(tk.Frame):
    """A frame whose content scrolls vertically (scrollbar appears only when needed)."""

    def __init__(self, parent: tk.Misc, bg: str) -> None:
        super().__init__(parent, bg=bg)
        self.canvas = tk.Canvas(self, bg=bg, highlightthickness=0, bd=0)
        self.bar = ttk.Scrollbar(self, orient="vertical", command=self.canvas.yview)
        self.inner = tk.Frame(self.canvas, bg=bg)
        self._win = self.canvas.create_window((0, 0), window=self.inner, anchor="nw")
        self.canvas.configure(yscrollcommand=self.bar.set)
        self.canvas.pack(side="left", fill="both", expand=True)
        self.inner.bind("<Configure>", self._sync)
        self.canvas.bind("<Configure>", self._sync)
        for widget in (self.canvas, self.inner):
            widget.bind("<Enter>", self._bind_wheel)
            widget.bind("<Leave>", self._unbind_wheel)
        self._bar_shown = False

    def _sync(self, _event: object = None) -> None:
        width = self.canvas.winfo_width()
        self.canvas.itemconfigure(self._win, width=width)
        self.canvas.configure(scrollregion=self.canvas.bbox("all"))
        need = self.inner.winfo_reqheight() > self.canvas.winfo_height() + 2
        if need and not self._bar_shown:
            self.bar.pack(side="right", fill="y")
            self._bar_shown = True
        elif not need and self._bar_shown:
            self.bar.pack_forget()
            self._bar_shown = False
            self.canvas.yview_moveto(0)

    def _bind_wheel(self, _event: object = None) -> None:
        self.canvas.bind_all("<MouseWheel>", self._wheel)
        self.canvas.bind_all("<Button-4>", lambda _e: self.canvas.yview_scroll(-2, "units"))
        self.canvas.bind_all("<Button-5>", lambda _e: self.canvas.yview_scroll(2, "units"))

    def _unbind_wheel(self, _event: object = None) -> None:
        for sequence in ("<MouseWheel>", "<Button-4>", "<Button-5>"):
            self.canvas.unbind_all(sequence)

    def _wheel(self, event: tk.Event) -> None:
        if self._bar_shown:
            self.canvas.yview_scroll(int(-event.delta / 120) * 2, "units")


class Wizard(tk.Tk):
    def __init__(self, dry_run: bool = False, preset: Options | None = None, dpi: float | None = None) -> None:
        super().__init__()
        if dpi:                                        # testing hook: emulate a display scaling
            self.tk.call("tk", "scaling", dpi / 72.0)
        self.dry_run = dry_run
        self.edition, self.title_text = setup_app.read_edition(ROOT)
        self.title(f"{self.title_text} - Setup")
        self.configure(bg=BG)
        self.scale = max(1.0, self.winfo_fpixels("1i") / 96.0)
        self._place_window()
        try:
            self.iconbitmap(str(ROOT / "imagecraft/ui/assets" / ICON))
        except tk.TclError:
            pass
        self._fonts()
        self._styles()
        self.info: dict = {}
        self.engine: SetupEngine | None = None
        self.events: queue.Queue = queue.Queue()
        self.worker: threading.Thread | None = None
        self.started = 0.0
        self.step_rows: list[tuple[str, tk.Label]] = []
        self.step_index = 0
        self.total_steps = 1
        self.warnings: list[str] = []
        self.result: dict = {}
        self.closing = False
        self.extras_open = False

        preset = preset or Options(dry_run=dry_run)
        self.v = {name: tk.BooleanVar(value=getattr(preset, name)) for name in
                  ("install_deps", "launcher", "desktop_shortcut", "start_menu_shortcut", "standalone", "installer", "reinstall")}
        self.holder = tk.Frame(self, bg=BG)
        self.holder.pack(fill="both", expand=True)
        self.pages = {"options": self._build_options(), "progress": self._build_progress(), "done": self._build_done()}
        self.show("options")
        self.protocol("WM_DELETE_WINDOW", self.on_close)
        self.bind("<Return>", lambda _e: self.start() if self.current == "options" and str(self.btn_install["state"]) == "normal" else None)
        self.after(100, self._load_checks)
        self.after(100, self._poll)

    # ------------------------------------------------------------ window / look
    def _place_window(self) -> None:
        """Landscape 16:10 window, capped to the screen and centred, whatever the DPI."""
        screen_w, screen_h = self.winfo_screenwidth(), self.winfo_screenheight()
        width = min(int(BASE_W * self.scale), int(screen_w * 0.92))
        height = min(int(BASE_H * self.scale), int(screen_h * 0.88))
        x, y = max(0, (screen_w - width) // 2), max(0, (screen_h - height) // 3)
        self.geometry(f"{width}x{height}+{x}+{y}")
        self.minsize(min(int(760 * self.scale), width), min(int(480 * self.scale), height))
        self.win_w = width

    def _fonts(self) -> None:
        family = "Segoe UI" if sys.platform == "win32" else "DejaVu Sans"
        self.f_title = tkfont.Font(family=family, size=17, weight="bold")
        self.f_head = tkfont.Font(family=family, size=11, weight="bold")
        self.f_body = tkfont.Font(family=family, size=10)
        self.f_small = tkfont.Font(family=family, size=9)
        self.f_mono = tkfont.Font(family="Consolas" if sys.platform == "win32" else "DejaVu Sans Mono", size=9)
        self.f_big = tkfont.Font(family=family, size=28)

    def _styles(self) -> None:
        style = ttk.Style(self)
        style.theme_use("clam")
        style.configure("Mint.Horizontal.TProgressbar", troughcolor=LINE, background=MINT, bordercolor=LINE,
                        lightcolor=MINT, darkcolor=MINT, thickness=int(10 * self.scale))
        style.configure("Thin.Horizontal.TProgressbar", troughcolor=LINE, background=THIN, bordercolor=LINE,
                        lightcolor=THIN, darkcolor=THIN, thickness=int(5 * self.scale))
        style.configure("Vertical.TScrollbar", troughcolor=CARD, background=LINE, bordercolor=CARD, arrowcolor=MUTED)

    def px(self, value: float) -> int:
        return int(value * self.scale)

    def label(self, parent, text="", font=None, fg=TEXT, bg=None, **kw) -> tk.Label:
        return tk.Label(parent, text=text, font=font or self.f_body, fg=fg, bg=bg or parent["bg"], anchor="w",
                        justify="left", **kw)

    def wrap(self, label: tk.Label, container: tk.Misc, pad: int = 0) -> tk.Label:
        """Re-wrap a label whenever its container changes width."""
        container.bind("<Configure>", lambda e: label.configure(wraplength=max(120, e.width - pad)), add="+")
        return label

    def button(self, parent, text, command, primary=False) -> tk.Button:
        bg, fg, hover = (MINT, INK, MINT_HOVER) if primary else (BTN2, TEXT, BTN2_HOVER)
        b = tk.Button(parent, text=text, command=command, font=self.f_head if primary else self.f_body, bg=bg, fg=fg,
                      activebackground=hover, activeforeground=fg, relief="flat", bd=0, cursor="hand2",
                      padx=self.px(26 if primary else 20), pady=self.px(10 if primary else 8), disabledforeground=DISABLED_FG)
        b._base = bg                                     # type: ignore[attr-defined]
        b.bind("<Enter>", lambda _e: b.configure(bg=hover) if str(b["state"]) == "normal" else None)
        b.bind("<Leave>", lambda _e: b.configure(bg=b._base))   # type: ignore[attr-defined]
        return b

    def card(self, parent) -> tk.Frame:
        return tk.Frame(parent, bg=CARD, highlightbackground=LINE, highlightthickness=1)

    def check(self, parent, text, var, sub="", indent=0):
        row = tk.Frame(parent, bg=CARD)
        row.pack(fill="x", padx=(self.px(12) + indent, self.px(12)), pady=(self.px(5), 0))
        box = tk.Checkbutton(row, text=text, variable=var, font=self.f_body, fg=TEXT, bg=CARD, selectcolor=BG,
                             activebackground=CARD, activeforeground=TEXT, highlightthickness=0, bd=0, anchor="w",
                             disabledforeground=DISABLED_FG, command=self.refresh, cursor="hand2")
        box.pack(fill="x")
        subtitle = self.label(row, sub, self.f_small, MUTED)
        self.wrap(subtitle, row, self.px(30))
        if sub:
            subtitle.pack(fill="x", padx=(self.px(24), 0))
        return box, subtitle

    def page_frame(self) -> tuple[tk.Frame, tk.Frame, tk.Frame]:
        """(page, footer, body): footer is packed first so the buttons are always on screen."""
        page = tk.Frame(self.holder, bg=BG)
        footer = tk.Frame(page, bg=BG)
        footer.pack(side="bottom", fill="x", padx=self.px(24), pady=(self.px(8), self.px(16)))
        tk.Frame(page, bg=LINE, height=1).pack(side="bottom", fill="x")
        scroll = Scroll(page, BG)
        scroll.pack(side="top", fill="both", expand=True, padx=self.px(24), pady=(self.px(14), 0))
        return page, footer, scroll.inner

    def show(self, name: str) -> None:
        for page in self.pages.values():
            page.pack_forget()
        self.pages[name].pack(fill="both", expand=True)
        self.current = name

    # ------------------------------------------------------------ page 1: choose
    def _build_options(self) -> tk.Frame:
        page, footer, body = self.page_frame()
        head = tk.Frame(body, bg=BG)
        head.pack(fill="x")
        try:
            logo = tk.PhotoImage(file=str(ROOT / "imagecraft/ui/assets" / LOGO))
            target = 84 * self.scale if HAI else 62 * self.scale          # picture height in pixels
            self._logo = logo.subsample(max(1, round(logo.height() / target)))
            tk.Label(head, image=self._logo, bg=BG).pack(side="left")
        except tk.TclError:
            self.label(head, self.title_text, self.f_title, MINT).pack(side="left")
        titles = tk.Frame(head, bg=BG)
        titles.pack(side="left", padx=(self.px(20), 0), fill="x", expand=True)
        self.label(titles, f"Set up {self.title_text}", self.f_title).pack(fill="x")
        intro = self.label(titles, "One click installs everything the app needs. The first time takes a while, "
                           "mostly downloading - you can leave it running.", self.f_body, MUTED)
        self.wrap(intro, titles, 0)
        intro.pack(fill="x")

        columns = tk.Frame(body, bg=BG)
        columns.pack(fill="both", expand=True, pady=(self.px(14), 0))
        columns.grid_columnconfigure(0, weight=5, uniform="c")
        columns.grid_columnconfigure(1, weight=6, uniform="c")
        left = tk.Frame(columns, bg=BG)
        right = tk.Frame(columns, bg=BG)
        left.grid(row=0, column=0, sticky="nsew", padx=(0, self.px(8)))
        right.grid(row=0, column=1, sticky="nsew", padx=(self.px(8), 0))

        self.label(left, "YOUR PC", self.f_small, MUTED).pack(anchor="w")
        self.checks_card = self.card(left)
        self.checks_card.pack(fill="x", pady=(2, 0))
        self.checks_body = tk.Frame(self.checks_card, bg=CARD)
        self.checks_body.pack(fill="x", padx=self.px(12), pady=self.px(8))
        self.label(self.checks_body, "Checking your PC...", self.f_body, MUTED).pack(anchor="w")

        self.label(right, "WHAT SHOULD SETUP DO?", self.f_small, MUTED).pack(anchor="w")
        card = self.card(right)
        card.pack(fill="x", pady=(2, 0))
        plus = self.edition == "Plus"
        self.cb_install, self.sub_install = self.check(
            card, "Install the app" + (" and its AI / GPU libraries" if plus else ""), self.v["install_deps"],
            "Creates a private Python environment inside this folder. Nothing else on your PC is touched.")
        self.cb_launcher, _ = self.check(
            card, "Create a quick-launch EXE   (recommended)", self.v["launcher"],
            f"A tiny '{self.title_text}.exe' that simply opens the app. Takes under a minute.")
        self.cb_desktop, _ = self.check(card, "Desktop shortcut", self.v["desktop_shortcut"], indent=self.px(24))
        self.cb_start, _ = self.check(card, "Start Menu shortcut", self.v["start_menu_shortcut"], indent=self.px(24))

        self.extras_toggle = tk.Label(card, text="", font=self.f_body, fg=MINT, bg=CARD, cursor="hand2", anchor="w")
        self.extras_toggle.pack(fill="x", padx=self.px(12), pady=(self.px(10), self.px(2)))
        self.extras_toggle.bind("<Button-1>", lambda _e: self.toggle_extras())
        self.extras = tk.Frame(card, bg=CARD)
        self.cb_standalone, self.sub_standalone = self.check(
            self.extras, "Build the standalone EXE with everything inside", self.v["standalone"],
            "A portable folder with Python and every library bundled: copy it to any Windows PC and it just runs. "
            "Large and slow to build - most people do not need it.")
        self.cb_installer, self.sub_installer = self.check(
            self.extras, "Also make a Windows installer for it", self.v["installer"], "", indent=self.px(24))
        self.cb_reinstall, _ = self.check(
            self.extras, "Clean reinstall (repairs a broken install)", self.v["reinstall"],
            "Deletes the .venv folder and installs everything again.")
        tk.Frame(card, bg=CARD, height=self.px(8)).pack()
        if self.v["standalone"].get() or self.v["reinstall"].get():
            self.toggle_extras()
        else:
            self._set_extras_text()

        self.need_label = self.label(footer, "", self.f_small, MUTED)
        self.need_label.pack(side="left")
        self.btn_install = self.button(footer, "Start setup  ▶", self.start, primary=True)
        self.btn_install.pack(side="right")
        self.button(footer, "Exit", self.on_close).pack(side="right", padx=(0, self.px(10)))
        return page

    def _set_extras_text(self) -> None:
        arrow = "▾" if self.extras_open else "▸"
        self.extras_toggle.configure(text=f"{arrow}  Optional extras: standalone EXE, installer, repair")

    def toggle_extras(self) -> None:
        self.extras_open = not self.extras_open
        if self.extras_open:
            self.extras.pack(fill="x", after=self.extras_toggle)
        else:
            self.extras.pack_forget()
        self._set_extras_text()

    def _load_checks(self) -> None:
        def work() -> None:
            self.events.put(("checks", setup_app.preflight(ROOT, self.dry_run)))
        threading.Thread(target=work, daemon=True).start()

    def _show_checks(self, info: dict) -> None:
        self.info = info
        for child in self.checks_body.winfo_children():
            child.destroy()
        for item in info["checks"]:
            glyph, colour = GLYPH.get(item["status"], GLYPH["info"])
            row = tk.Frame(self.checks_body, bg=CARD)
            row.pack(fill="x", pady=self.px(3))
            tk.Label(row, text=glyph, fg=colour, bg=CARD, font=self.f_small, width=2).pack(side="left", anchor="n")
            text = tk.Frame(row, bg=CARD)
            text.pack(side="left", fill="x", expand=True)
            self.label(text, item["label"], self.f_body, TEXT).pack(fill="x")
            detail = self.label(text, item["detail"], self.f_small, MUTED if item["status"] in ("ok", "info") else colour)
            self.wrap(detail, text, 0)
            detail.pack(fill="x")
        state = info["state"]
        if state == "current":
            self.sub_install.configure(text="Already installed and up to date - Setup will only verify it, which is quick.")
        elif self.edition == "Plus":
            self.sub_install.configure(text="Creates a private Python environment inside this folder. The first run "
                                       "downloads about 7 GB (NVIDIA CUDA PyTorch): expect 15-40 minutes.")
        else:
            self.sub_install.configure(text="Creates a private Python environment inside this folder. A small download "
                                       "(a few minutes).")
        self.sub_installer.configure(text="Inno Setup 6 found. Packs the standalone build into a normal Setup wizard."
                                     if info.get("inno") else "Needs Inno Setup 6 (free, jrsoftware.org) - not found on this PC.")
        self.sub_installer.pack(fill="x", padx=(self.px(24), 0))
        if state == "missing":
            self.v["install_deps"].set(True)
        self.refresh()

    def refresh(self) -> None:
        v = {k: var.get() for k, var in self.v.items()}
        launcher_on = v["launcher"]
        self.cb_desktop.configure(state="normal" if launcher_on else "disabled")
        self.cb_start.configure(state="normal" if launcher_on else "disabled")
        installer_ok = bool(self.info.get("inno")) and v["standalone"]
        self.cb_installer.configure(state="normal" if installer_ok else "disabled")
        if not installer_ok:
            self.v["installer"].set(False)
        state = self.info.get("state", "missing")
        needs_install = not v["install_deps"] and state == "missing" and (v["launcher"] or v["standalone"])
        need = setup_app.estimate_gb(self.options(), state, self.edition)
        free = self.info.get("free_gb", 0.0)
        enough = free >= need or self.dry_run
        if not self.info:
            message, ready = "Checking your PC...", False
        elif self.info.get("blocking"):
            message, ready = "Fix the red item on the left, then start Setup again.", False
        elif needs_install:
            message, ready = "Tick 'Install the app' first - nothing is installed yet.", False
        elif not enough:
            message, ready = f"Needs about {need:.0f} GB, only {free:.0f} GB free on this drive.", False
        elif not any([v["install_deps"], v["launcher"], v["standalone"]]):
            message, ready = "Nothing selected.", False
        else:
            message, ready = (f"Needs about {need:.0f} GB free  -  {free:.0f} GB available" if need else "Quick - no big downloads"), True
        self.need_label.configure(text=message, fg=MUTED if ready else WARN)
        self.btn_install.configure(state="normal" if ready else "disabled", bg=MINT if ready else BTN2)
        self.btn_install._base = MINT if ready else BTN2     # type: ignore[attr-defined]

    def options(self) -> Options:
        v = {k: var.get() for k, var in self.v.items()}
        return Options(install_deps=v["install_deps"], reinstall=v["reinstall"], launcher=v["launcher"],
                       desktop_shortcut=v["launcher"] and v["desktop_shortcut"],
                       start_menu_shortcut=v["launcher"] and v["start_menu_shortcut"],
                       standalone=v["standalone"], installer=v["standalone"] and v["installer"], dry_run=self.dry_run)

    # ------------------------------------------------------------ page 2: progress
    def _build_progress(self) -> tk.Frame:
        page, footer, body = self.page_frame()
        self.label(body, "Setting things up", self.f_title).pack(anchor="w")
        self.label(body, "You can leave this window open and do something else. Please don't shut the PC down.",
                   self.f_body, MUTED).pack(anchor="w", pady=(2, self.px(10)))
        steps = self.card(body)
        steps.pack(fill="x")
        self.steps_body = tk.Frame(steps, bg=CARD)
        self.steps_body.pack(fill="x", padx=self.px(14), pady=self.px(8))
        self.status_label = self.label(body, "", self.f_body, TEXT)
        self.wrap(self.status_label, body, 0)
        self.status_label.pack(fill="x", pady=(self.px(10), 4))
        self.bar = ttk.Progressbar(body, style="Mint.Horizontal.TProgressbar", mode="determinate", maximum=1.0)
        self.bar.pack(fill="x", pady=(0, 3))
        self.sub_bar = ttk.Progressbar(body, style="Thin.Horizontal.TProgressbar", mode="determinate", maximum=1.0)
        self.sub_bar.pack(fill="x", pady=(0, 4))
        self.time_label = self.label(body, "", self.f_small, MUTED)
        self.time_label.pack(fill="x")
        self.log_toggle = tk.Label(body, text="▸ Show details", font=self.f_small, fg=MINT, bg=BG, cursor="hand2", anchor="w")
        self.log_toggle.pack(fill="x", pady=(self.px(8), 2))
        self.log_toggle.bind("<Button-1>", lambda _e: self.toggle_log())
        self.log_frame = tk.Frame(body, bg=CARD, highlightbackground=LINE, highlightthickness=1)
        self.log = tk.Text(self.log_frame, height=9, bg=CARD, fg=MUTED, font=self.f_mono, bd=0, wrap="none",
                           highlightthickness=0, state="disabled", padx=8, pady=6)
        scroll = ttk.Scrollbar(self.log_frame, command=self.log.yview)
        self.log.configure(yscrollcommand=scroll.set)
        scroll.pack(side="right", fill="y")
        self.log.pack(side="left", fill="both", expand=True)
        self.log_visible = False
        self.btn_cancel = self.button(footer, "Cancel", self.cancel)
        self.btn_cancel.pack(side="right")
        return page

    def toggle_log(self) -> None:
        self.log_visible = not self.log_visible
        if self.log_visible:
            self.log_frame.pack(fill="both", expand=True)
            self.log_toggle.configure(text="▾ Hide details")
            self.log.see("end")
        else:
            self.log_frame.pack_forget()
            self.log_toggle.configure(text="▸ Show details")

    def start(self) -> None:
        opts = self.options()
        if opts.reinstall and not messagebox.askyesno(
                "Clean reinstall", "This deletes the .venv folder and downloads everything again. Continue?"):
            return
        self.engine = SetupEngine(opts, lambda kind, **data: self.events.put((kind, data)))
        self.warnings = []
        self.started = time.monotonic()
        self.bar["value"] = 0
        self.sub_bar["value"] = 0
        self.log.configure(state="normal")
        self.log.delete("1.0", "end")
        self.log.configure(state="disabled")
        self.btn_cancel.configure(state="normal", text="Cancel")
        self.show("progress")
        self.worker = threading.Thread(target=self.engine.run, daemon=True)
        self.worker.start()

    def cancel(self) -> None:
        if self.engine and messagebox.askyesno("Cancel setup", "Stop now? Anything already downloaded is kept, "
                                               "so running Setup again continues quickly."):
            self.btn_cancel.configure(state="disabled", text="Stopping...")
            self.engine.cancel()

    def _plan(self, steps) -> None:
        for child in self.steps_body.winfo_children():
            child.destroy()
        self.step_rows = []
        for _key, text in steps:
            row = self.label(self.steps_body, f"○  {text}", self.f_body, MUTED)
            row.pack(fill="x", pady=1)
            self.step_rows.append((text, row))
        self.total_steps = len(steps)

    def _mark_step(self, index: int) -> None:
        for i, (text, row) in enumerate(self.step_rows):
            if i < index:
                row.configure(text=f"✓  {text}", fg=OK, font=self.f_body)
            elif i == index:
                row.configure(text=f"▶  {text}", fg=TEXT, font=self.f_head)
            else:
                row.configure(text=f"○  {text}", fg=MUTED, font=self.f_body)
        self.step_index = index

    def _append_log(self, text: str) -> None:
        self.log.configure(state="normal")
        self.log.insert("end", text + "\n")
        if int(self.log.index("end-1c").split(".")[0]) > 2500:
            self.log.delete("1.0", "500.0")
        self.log.configure(state="disabled")
        if self.log_visible:
            self.log.see("end")

    # ------------------------------------------------------------ page 3: done
    def _build_done(self) -> tk.Frame:
        page, footer, body = self.page_frame()
        head = tk.Frame(body, bg=BG)
        head.pack(fill="x")
        self.done_icon = tk.Label(head, text="", font=self.f_big, bg=BG)
        self.done_icon.pack(side="left", padx=(0, self.px(14)))
        titles = tk.Frame(head, bg=BG)
        titles.pack(side="left", fill="x", expand=True)
        self.done_title = self.label(titles, "", self.f_title)
        self.done_title.pack(fill="x")
        self.done_text = self.label(titles, "", self.f_body, MUTED)
        self.wrap(self.done_text, titles, 0)
        self.done_text.pack(fill="x")
        self.done_card = self.card(body)
        self.done_card.pack(fill="x", pady=(self.px(14), 0))
        self.done_body = tk.Frame(self.done_card, bg=CARD)
        self.done_body.pack(fill="x", padx=self.px(14), pady=self.px(10))
        self.done_notes = self.label(body, "", self.f_small, WARN)
        self.wrap(self.done_notes, body, 0)
        self.done_notes.pack(fill="x", pady=(self.px(10), 0))
        self.done_buttons = footer
        return page

    def _finish(self, ok: bool, cancelled: bool, summary: dict, error: str, hint: str) -> None:
        self.result = summary
        for child in self.done_body.winfo_children():
            child.destroy()
        for child in self.done_buttons.winfo_children():
            child.destroy()
        launcher = summary.get("launcher")
        standalone = summary.get("standalone")
        rows: list[tuple[str, str]] = []
        if ok:
            self.done_icon.configure(text="✔", fg=OK)
            self.done_title.configure(text=f"{self.title_text} is ready")
            self.done_text.configure(text="Everything you selected was set up. Open it from the shortcut, the launcher, or the button below.")
            if launcher:
                rows.append(("Quick launcher", launcher))
            for path in summary.get("shortcuts", []):
                rows.append(("Shortcut", path))
            if standalone:
                rows.append(("Standalone EXE", standalone))
            if summary.get("installer"):
                rows.append(("Installer", summary["installer"]))
            gpu = summary.get("gpu")
            if gpu:
                rows.append(("GPU check", ("Passed - " + gpu.get("name", "")) if gpu["ok"] else "Not passed (see note below)"))
            rows.append(("Models", f"Downloaded later inside the app, into {ROOT / 'models'}") if self.edition == "Plus"
                        else ("App folder", str(ROOT)))
        elif cancelled:
            self.done_icon.configure(text="■", fg=WARN)
            self.done_title.configure(text="Setup was stopped")
            self.done_text.configure(text="Nothing is broken. Run Setup again - it continues where it left off.")
        else:
            self.done_icon.configure(text="✖", fg=FAIL)
            self.done_title.configure(text="Setup hit a problem")
            self.done_text.configure(text=error)
            rows.append(("What to do", hint or "Press Try again. If it repeats, open the log and send it to support."))
        for name, value in rows:
            row = tk.Frame(self.done_body, bg=CARD)
            row.pack(fill="x", pady=2)
            self.label(row, name, self.f_small, MUTED, width=15).pack(side="left", anchor="n")
            text = self.label(row, value, self.f_body, TEXT)
            self.wrap(text, row, self.px(130))
            text.pack(side="left", fill="x", expand=True)
        self.done_card.pack_forget()
        if rows:
            self.done_card.pack(fill="x", pady=(self.px(14), 0), before=self.done_notes)
        notes = summary.get("warnings", [])
        self.done_notes.configure(text=("▲ " + "\n▲ ".join(notes)) if notes else "")
        pad = self.px(10)
        self.button(self.done_buttons, "Close", self.destroy).pack(side="right")
        if ok and standalone:
            self.button(self.done_buttons, "Show standalone folder",
                        lambda: self.open_path(Path(standalone).parent)).pack(side="right", padx=(0, pad))
        if ROOT.joinpath("setup.log").is_file():
            self.button(self.done_buttons, "Open log", lambda: self.open_path(ROOT / "setup.log")).pack(side="right", padx=(0, pad))
        if ok and (launcher or standalone):
            self.button(self.done_buttons, f"Open {self.title_text}", self.launch_app, primary=True).pack(side="left")
        if not ok:
            self.button(self.done_buttons, "Try again", lambda: self.show("options"), primary=True).pack(side="left")
        self.show("done")

    def open_path(self, path: Path) -> None:
        try:
            os.startfile(str(path))                     # type: ignore[attr-defined]
        except (AttributeError, OSError):
            pass

    def launch_app(self) -> None:
        launcher = self.result.get("launcher")
        try:
            if launcher and Path(launcher).is_file():
                os.startfile(launcher)                  # type: ignore[attr-defined]
            else:
                python = setup_app.venv_python(ROOT).with_name("pythonw.exe")
                subprocess.Popen([str(python), str(ROOT / "launch.py")], cwd=str(ROOT), creationflags=0x00000008,
                                 stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        except (AttributeError, OSError) as exc:
            messagebox.showerror("Could not open the app", str(exc))
            return
        self.destroy()

    # ------------------------------------------------------------ events
    def _poll(self) -> None:
        try:
            while True:
                kind, data = self.events.get_nowait()
                self._handle(kind, data)
        except queue.Empty:
            pass
        if self.worker and self.worker.is_alive():
            self.time_label.configure(text=f"Step {min(self.step_index + 1, self.total_steps)} of {self.total_steps}"
                                           f"   -   {format_time(time.monotonic() - self.started)} elapsed")
        elif self.closing:
            self.destroy()
            return
        self.after(100, self._poll)

    def _handle(self, kind: str, data: dict) -> None:
        if kind == "checks":
            self._show_checks(data)
        elif kind == "plan":
            self._plan(data["steps"])
        elif kind == "step":
            self._mark_step(data["index"])
        elif kind == "status":
            self.status_label.configure(text=data["text"])
        elif kind == "progress":
            if data["value"] is None:
                self.sub_bar.configure(mode="indeterminate")
                self.sub_bar.start(12)
            else:
                self.sub_bar.stop()
                self.sub_bar.configure(mode="determinate", value=data["value"])
        elif kind == "overall":
            self.bar["value"] = data["value"]
        elif kind == "log":
            self._append_log(data["text"])
        elif kind == "warn":
            self.warnings.append(data["text"])
            self._append_log("WARNING: " + data["text"])
        elif kind == "done":
            self.sub_bar.stop()
            self.sub_bar.configure(mode="determinate", value=0)
            self._mark_step(len(self.step_rows) if data["ok"] else self.step_index)
            self._finish(data["ok"], data["cancelled"], data["summary"], data["error"], data["hint"])

    def on_close(self) -> None:
        if self.worker and self.worker.is_alive():
            if messagebox.askyesno("Setup is running", "Stop setup and close this window?"):
                self.closing = True
                if self.engine:
                    self.engine.cancel()
            return
        self.destroy()


def main(argv: list[str] | None = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    if sys.platform == "win32":
        try:
            import ctypes
            ctypes.windll.shcore.SetProcessDpiAwareness(1)       # crisp text on high-DPI screens
        except (AttributeError, OSError):
            pass
    try:
        app = Wizard(dry_run="--dry-run" in argv)
        app.mainloop()
        return 0
    except Exception:
        import traceback
        text = traceback.format_exc()
        try:
            (ROOT / "setup-gui-error.log").write_text(text, encoding="utf-8")
        except OSError:
            pass
        if sys.platform == "win32":
            import ctypes
            ctypes.windll.user32.MessageBoxW(None, "The setup window could not start.\n\nRun Setup.cmd --console instead.\n\n"
                                             + text[-900:], "VisionDB Craft Setup", 0x10)
        else:
            print(text, file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
