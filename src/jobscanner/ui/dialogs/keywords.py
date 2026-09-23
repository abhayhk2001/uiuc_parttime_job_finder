"""Popup editor for `keywords.json`."""

from __future__ import annotations

import json
import os
from pathlib import Path
from tkinter import messagebox

import customtkinter as ctk

from jobscanner.ui import theme

_END = "end"


class KeywordEditor(ctk.CTkToplevel):
    """Popup window for editing `keywords.json`. Save also triggers a
    re-match pass against the existing DB."""

    def __init__(self, master, keywords_path: Path, on_save=None) -> None:
        super().__init__(master)
        self.title("Edit Keywords")
        self.geometry("480x620")
        self.minsize(360, 420)
        self.keywords_path = keywords_path
        self.on_save = on_save
        self.transient(master)
        self.after(50, self.grab_set)

        self.keywords: list[str] = []
        self._load_from_disk()
        self._build()

    def _load_from_disk(self) -> None:
        self.keywords = []
        if not self.keywords_path.exists():
            return
        try:
            with self.keywords_path.open("r", encoding="utf-8") as f:
                data = json.load(f)
        except Exception:
            return
        if isinstance(data, list):
            self.keywords = [str(k).strip() for k in data if str(k).strip()]

    def _persist(self) -> bool:
        clean: list[str] = []
        seen: set[str] = set()
        for k in self.keywords:
            k = k.strip()
            if not k:
                continue
            kl = k.lower()
            if kl in seen:
                continue
            seen.add(kl)
            clean.append(k)
        tmp = self.keywords_path.with_suffix(self.keywords_path.suffix + ".tmp")
        try:
            tmp.parent.mkdir(parents=True, exist_ok=True)
            with tmp.open("w", encoding="utf-8") as f:
                json.dump(clean, f, indent=2)
            os.replace(tmp, self.keywords_path)
        except Exception as exc:
            messagebox.showerror("Save failed", str(exc), parent=self)
            return False
        self.keywords = clean
        return True

    def _build(self) -> None:
        self.grid_columnconfigure(0, weight=1)
        self.grid_rowconfigure(0, weight=1)

        body = ctk.CTkFrame(self)
        body.grid(row=0, column=0, sticky="nsew",
                  padx=theme.PAD_LARGE, pady=(theme.PAD_LARGE, 6))
        body.grid_columnconfigure(0, weight=1)
        body.grid_rowconfigure(1, weight=1)

        ctk.CTkLabel(
            body, text="One keyword per line.",
            anchor="w", text_color=theme.MUTED_TEXT,
        ).grid(row=0, column=0, sticky="ew", padx=4, pady=(0, 4))

        self.textbox = ctk.CTkTextbox(body, activate_scrollbars=True,
                                      font=theme.mono_font())
        self.textbox.grid(row=1, column=0, sticky="nsew")
        self.textbox.delete("1.0", _END)
        self.textbox.insert("1.0", "\n".join(self.keywords))

        bar = ctk.CTkFrame(self)
        bar.grid(row=1, column=0, sticky="ew",
                 padx=theme.PAD_LARGE, pady=(6, theme.PAD_LARGE))
        bar.grid_columnconfigure(0, weight=1)

        ctk.CTkLabel(
            bar, text=f"Saves to {self.keywords_path.name}",
            anchor="w", text_color=theme.MUTED_TEXT,
        ).grid(row=0, column=0, sticky="ew", padx=4)
        ctk.CTkButton(bar, text="Reload", width=100,
                      command=self._reload).grid(row=0, column=1, padx=4)
        ctk.CTkButton(bar, text="Save", width=100,
                      command=self._handle_save).grid(row=0, column=2, padx=4)
        ctk.CTkButton(bar, text="Cancel", width=100,
                      command=self.destroy).grid(row=0, column=3, padx=4)

    def _reload(self) -> None:
        self._load_from_disk()
        self.textbox.delete("1.0", _END)
        self.textbox.insert("1.0", "\n".join(self.keywords))

    def _handle_save(self) -> None:
        text = self.textbox.get("1.0", _END)
        self.keywords = [line.strip() for line in text.splitlines() if line.strip()]
        if not self._persist():
            return
        cb = self.on_save
        self.destroy()
        if cb:
            cb(self.keywords)
