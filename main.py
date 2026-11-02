
from __future__ import annotations

import json
import os
import sys
import queue
import ctypes
import threading
import tkinter as tk
import tkinter.font as tkfont

from pathlib import Path
from tkinter import ttk, messagebox

from policy_reader import (
    PolicyScanner,
    build_tree,
    search_records,
    record_description,
)


APP_TITLE = "Windows Policy Description Reader"



class JsonDescriptionTranslator:
    """Load English -> Vietnamese descriptions from the JSON dictionary."""

    def __init__(self):
        self.translations = {}
        self.json_path = self._get_json_path()
        self.load()

    def _get_json_path(self):
        # main.py và thư mục data nằm cùng cấp.
        base_dir = Path(__file__).resolve().parent
        return base_dir / "data" / "description_translations_vi.json"

    @staticmethod
    def _normalize(text):
        """Normalize whitespace for more reliable description matching."""
        if not isinstance(text, str):
            return ""
        return " ".join(text.strip().split())

    def load(self):
        self.translations.clear()

        if not self.json_path.is_file():
            raise FileNotFoundError(
                "Không tìm thấy file từ điển dịch!\n\n"
                f"Đường dẫn chương trình đang tìm:\n{self.json_path}\n\n"
                "Hãy đặt description_translations_vi.json trong thư mục data "
                "nằm cùng cấp với main.py."
            )

        try:
            with self.json_path.open("r", encoding="utf-8-sig") as file:
                data = json.load(file)

            if not isinstance(data, dict):
                raise ValueError("Cấu trúc JSON không hợp lệ: dữ liệu gốc phải là object.")

            # QUAN TRỌNG:
            # File JSON của bạn lưu dữ liệu dịch bên trong khóa "translations".
            translation_data = data.get("translations", data)

            if not isinstance(translation_data, dict):
                raise ValueError(
                    "JSON có khóa 'translations' nhưng giá trị không phải object."
                )

            for key, item in translation_data.items():
                if not isinstance(key, str) or not isinstance(item, dict):
                    continue

                original = item.get("original", key)
                vietnamese = item.get("vi")

                if not isinstance(original, str):
                    original = key

                if not isinstance(vietnamese, str) or not vietnamese.strip():
                    continue

                translated = vietnamese.strip()

                # Tra cứu bằng cả khóa JSON và trường original.
                for source in (key, original):
                    normalized = self._normalize(source)
                    if normalized:
                        self.translations[normalized] = translated

            print(
                f"[Translation] Loaded {len(self.translations)} translation keys."
            )
            print(f"[Translation] JSON path: {self.json_path}")

        except Exception as exc:
            self.translations.clear()
            raise RuntimeError(
                "Không thể đọc từ điển dịch tiếng Việt.\n\n"
                f"File: {self.json_path}\n"
                f"Lỗi: {type(exc).__name__}: {exc}"
            ) from exc

    def get(self, original):
        if not isinstance(original, str):
            return original

        key = self._normalize(original)
        if not key:
            return original

        translated = self.translations.get(key)

        # Không có bản dịch thì giữ nguyên tiếng Anh.
        return translated if translated else original



class PolicyReaderApp:

    def __init__(self, root):
        self.root = root
        self.root.title(APP_TITLE)
        self.root.geometry("1100x760")
        self.root.minsize(760, 480)

        self.queue = queue.Queue()

        self.scanner = PolicyScanner(
            progress_callback=lambda msg: self.queue.put(("progress", msg))
        )

        self.records = []
        self.model = {}
        self.nodes = {}
        self.search_results = []

        # Load the translation dictionary once at startup.
        self.translator = JsonDescriptionTranslator()

        # English is the default language.
        self.show_vietnamese = tk.BooleanVar(value=False)

        self._build_ui()

        self.root.after(100, self._poll)
        self.root.after(150, self.start_scan)

    # ---------------------------------------------------------
    # USER INTERFACE
    # ---------------------------------------------------------

    def _build_ui(self):
        outer = ttk.Frame(self.root, padding=8)
        outer.pack(fill="both", expand=True)

        search = ttk.Frame(outer)
        search.pack(fill="x", pady=(0, 6))

        ttk.Label(
            search,
            text="Search policies:"
        ).pack(side="left")

        self.query = tk.StringVar()

        entry = ttk.Entry(
            search,
            textvariable=self.query
        )
        entry.pack(side="left", fill="x", expand=True, padx=6)
        entry.bind("<Return>", lambda _e: self.search())

        ttk.Button(
            search,
            text="Search",
            command=self.search
        ).pack(side="left")

        ttk.Button(
            search,
            text="Clear",
            command=self.clear_search
        ).pack(side="left", padx=(5, 0))

        actions = ttk.Frame(outer)
        actions.pack(fill="x", pady=(0, 5))

        ttk.Label(
            actions,
            text="Language:"
        ).pack(side="left")

        self.language_box = ttk.Combobox(
            actions,
            state="readonly",
            width=14,
            values=("English", "Tiếng Việt")
        )
        self.language_box.set("English")
        self.language_box.pack(side="left", padx=(6, 0))

        self.language_box.bind(
            "<<ComboboxSelected>>",
            self._on_language_changed
        )

        self.status = tk.StringVar(
            value="Starting automatic scan..."
        )

        status_row = ttk.Frame(outer)
        status_row.pack(fill="x", pady=(0, 5))

        ttk.Label(
            status_row,
            textvariable=self.status
        ).pack(side="left", fill="x", expand=True)

        self.progress = ttk.Progressbar(
            outer,
            mode="indeterminate"
        )
        self.progress.pack(fill="x", pady=(0, 6))

        ttk.Label(
            outer,
            text=(
                
            )
        ).pack(anchor="w", pady=(0, 3))

        frame = ttk.Frame(outer)
        frame.pack(fill="both", expand=True)

        self.tree = ttk.Treeview(
            frame,
            show="tree",
            selectmode="extended"
        )

        y = ttk.Scrollbar(
            frame,
            orient="vertical",
            command=self.tree.yview
        )

        x = ttk.Scrollbar(
            frame,
            orient="horizontal",
            command=self.tree.xview
        )

        self.tree.configure(
            yscrollcommand=y.set,
            xscrollcommand=x.set
        )

        self.tree.grid(row=0, column=0, sticky="nsew")
        y.grid(row=0, column=1, sticky="ns")
        x.grid(row=1, column=0, sticky="ew")

        frame.rowconfigure(0, weight=1)
        frame.columnconfigure(0, weight=1)

        self.tree.bind(
            "<<TreeviewOpen>>",
            self._on_open
        )

        self.tree.bind(
            "<<TreeviewSelect>>",
            self._on_select
        )

    def _on_language_changed(self, event=None):
        self.show_vietnamese.set(
            self.language_box.get() == "Tiếng Việt"
        )

        # Rebuild the visible tree so descriptions use the new language.
        self._refresh_tree()

    # ---------------------------------------------------------
    # SCANNING
    # ---------------------------------------------------------

    def start_scan(self):
        self.progress.start(10)

        self.status.set(
            "Automatically scanning this Windows computer "
            "and discoverable policy sources..."
        )

        def worker():
            try:
                result = self.scanner.scan()
                self.queue.put(("done", result))

            except Exception as exc:
                self.queue.put(
                    ("fatal", f"{type(exc).__name__}: {exc}")
                )

        threading.Thread(
            target=worker,
            daemon=True
        ).start()

    def _poll(self):
        try:
            while True:
                kind, data = self.queue.get_nowait()

                if kind == "progress":
                    self.status.set(data)

                elif kind == "done":
                    self.progress.stop()

                    self.result = data
                    self.records = data.records
                    self.model = build_tree(self.records)

                    self._populate_roots()

                    policy_count = sum(
                        record.get("kind") == "policy"
                        for record in self.records
                    )

                    summary = (
                        f"ADMX found: {data.admx_found} | "
                        f"Parsed: {data.admx_parsed} | "
                        f"Policies: {policy_count} | "
                        f"Warnings: {len(data.warnings)}"
                    )

                    self.status.set(
                        summary
                        + " | Translation dictionary loaded: "
                        + str(len(self.translator.translations))
                    )

                elif kind == "fatal":
                    self.progress.stop()
                    self.status.set("Scan failed")
                    messagebox.showerror(
                        "Scan failed",
                        data
                    )

        except queue.Empty:
            pass

        self.root.after(100, self._poll)

    def rescan(self):
        """Repeat automatic discovery on this computer."""
        self.scanner = PolicyScanner(
            progress_callback=lambda msg: self.queue.put(
                ("progress", msg)
            )
        )

        self.start_scan()

    # ---------------------------------------------------------
    # ADMINISTRATOR
    # ---------------------------------------------------------

    @staticmethod
    def _is_admin():
        if os.name != "nt":
            return False

        try:
            return bool(
                ctypes.windll.shell32.IsUserAnAdmin()
            )
        except Exception:
            return False

    def fix_missing_data(self):
        """Offer administrator restart if additional access is needed."""

        if not self._is_admin():
            answer = messagebox.askyesno(
                "Additional access may be needed",
                "The automatic scan may not be able to read every "
                "Windows policy source.\n\n"
                "Would you like to restart this app with administrator "
                "permission and scan again?\n\n"
                "You will not need to find any folders manually."
            )

            if not answer:
                return

            try:
                params = " ".join(
                    f'"{arg}"' for arg in sys.argv
                )

                result = ctypes.windll.shell32.ShellExecuteW(
                    None,
                    "runas",
                    sys.executable,
                    params,
                    None,
                    1
                )

                if result <= 32:
                    messagebox.showerror(
                        "Could not restart",
                        "Windows could not restart the app with "
                        "administrator permission. Please close it "
                        "and choose Run as administrator."
                    )
                    return

                self.root.destroy()

            except Exception as exc:
                messagebox.showerror(
                    "Could not restart",
                    str(exc)
                )

            return

        self.rescan()

        messagebox.showinfo(
            "Automatic scan restarted",
            "The app is scanning again with administrator permission.\n\n"
            "Administrator permission can improve access, but it cannot "
            "create descriptions that Windows does not expose through "
            "the sources currently supported by this version."
        )

    # ---------------------------------------------------------
    # WARNINGS
    # ---------------------------------------------------------

    def show_warnings(self):
        warnings = getattr(
            getattr(self, "result", None),
            "warnings",
            []
        )

        if not warnings:
            messagebox.showinfo(
                "Scan warnings",
                "No warnings were reported."
            )
            return

        win = tk.Toplevel(self.root)
        win.title(f"Scan warnings ({len(warnings)})")
        win.geometry("900x420")
        win.transient(self.root)

        frame = ttk.Frame(win, padding=8)
        frame.pack(fill="both", expand=True)

        box = tk.Text(
            frame,
            wrap="word",
            height=18
        )

        scroll = ttk.Scrollbar(
            frame,
            orient="vertical",
            command=box.yview
        )

        box.configure(
            yscrollcommand=scroll.set
        )

        box.pack(side="left", fill="both", expand=True)
        scroll.pack(side="right", fill="y")

        box.insert(
            "1.0",
            "\n\n".join(
                f"{i}. {item}"
                for i, item in enumerate(warnings, 1)
            )
        )

        box.configure(state="disabled")

        ttk.Button(
            win,
            text="Close",
            command=win.destroy
        ).pack(anchor="e", padx=8, pady=(0, 8))

    # ---------------------------------------------------------
    # DESCRIPTION LANGUAGE
    # ---------------------------------------------------------

    def _display_description(self, original):
        if not isinstance(original, str):
            return original

        if self.show_vietnamese.get():
            return self.translator.get(original)

        return original

    def _refresh_tree(self):
        if self.query.get().strip():
            self.search()

        elif hasattr(self, "result"):
            self._populate_roots()

    # ---------------------------------------------------------
    # TREE
    # ---------------------------------------------------------

    def _populate_roots(self):
        self.tree.delete(
            *self.tree.get_children()
        )

        self.nodes.clear()

        for name in (
            "Computer Configuration",
            "User Configuration"
        ):
            iid = self.tree.insert(
                "",
                "end",
                text=name,
                open=False,
                values=("root",)
            )

            self.nodes[iid] = {
                "kind": "branch",
                "name": name
            }

            placeholder = self.tree.insert(
                iid,
                "end",
                text="Expand to load categories",
                values=("placeholder",)
            )

            self.nodes[placeholder] = {
                "kind": "placeholder"
            }

    def _on_open(self, _event=None):
        iid = self.tree.focus()

        children = self.tree.get_children(iid)

        if not children or (
            len(children) == 1
            and self.nodes.get(children[0], {}).get("kind")
            == "placeholder"
        ):
            for child in children:
                self.tree.delete(child)
                self.nodes.pop(child, None)

            node = self.nodes.get(iid, {})

            if node.get("kind") == "branch":
                self._add_model_children(
                    iid,
                    self.model.get(node["name"], {})
                )

            elif node.get("kind") == "category":
                if node.get("description"):
                    description = self._display_description(
                        node["description"]
                    )
                else:
                    description = self._display_description("No description")

                self._insert_wrapped_detail(
                    iid,
                    "Description",
                    description
                )

                self._add_model_children(
                    iid,
                    node.get("children", {}),
                    node.get("policies", [])
                )

            elif node.get("kind") == "policy":
                self._add_description(iid, node)

    def _add_model_children(
        self,
        parent,
        children,
        policies=None
    ):
        policies = policies or []

        for name in sorted(
            children,
            key=str.casefold
        ):
            data = children[name]

            iid = self.tree.insert(
                parent,
                "end",
                text=name,
                open=False,
                values=("category",)
            )

            self.nodes[iid] = data

            self._add_placeholder_if_expandable(
                iid,
                data
            )

        for rec in sorted(
            policies,
            key=lambda r: r.get("name", "").casefold()
        ):
            iid = self.tree.insert(
                parent,
                "end",
                text=rec["name"],
                open=False,
                values=("policy",)
            )

            self.nodes[iid] = rec

            self._add_placeholder_if_expandable(
                iid,
                rec
            )

    def _add_placeholder_if_expandable(
        self,
        iid,
        node
    ):
        if (
            node.get("kind") in {"category", "policy"}
            or node.get("children")
            or node.get("policies")
        ):
            ph = self.tree.insert(
                iid,
                "end",
                text="Expand to view description/details",
                values=("placeholder",)
            )

            self.nodes[ph] = {
                "kind": "placeholder"
            }

    # ---------------------------------------------------------
    # DESCRIPTION DISPLAY
    # ---------------------------------------------------------

    def _insert_wrapped_detail(
        self,
        parent,
        label,
        value
    ):
        """Wrap detail rows to the visible Treeview width."""

        value = str(value or "")

        if not value:
            return

        # Keep paragraph separation when displaying descriptions.
        paragraphs = [
            part.strip()
            for part in value.splitlines()
            if part.strip()
        ]

        value = "  ".join(paragraphs)

        try:
            font = tkfont.nametofont("TkDefaultFont")
            available = max(
                180,
                self.tree.winfo_width() - 105
            )
        except Exception:
            font = tkfont.nametofont("TkDefaultFont")
            available = 760

        def split_to_pixels(text, max_width):
            words = text.split()

            if not words:
                return [""]

            lines = []
            current = ""

            for word in words:
                candidate = (
                    word
                    if not current
                    else current + " " + word
                )

                if font.measure(candidate) <= max_width:
                    current = candidate
                    continue

                if current:
                    lines.append(current)
                    current = ""

                piece = ""

                for char in word:
                    if (
                        piece
                        and font.measure(piece + char) > max_width
                    ):
                        lines.append(piece)
                        piece = char
                    else:
                        piece += char

                current = piece

            if current:
                lines.append(current)

            return lines or [""]

        first_prefix = f"{label}: "

        wrapped = split_to_pixels(
            value,
            max(80, available - font.measure(first_prefix))
        )

        lines = [wrapped[0]]
        lines.extend(wrapped[1:])

        for index, line in enumerate(lines):
            prefix = (
                first_prefix
                if index == 0
                else "    "
            )

            display = prefix + line

            iid = self.tree.insert(
                parent,
                "end",
                text=display,
                values=("detail",)
            )

            self.nodes[iid] = {
                "kind": "detail",
                "name": label,
                "description": value,
                "line": index
            }

    def _add_description(self, parent, rec):
        original_description = (
            rec.get("description")
            or "No description"
        )

        description = self._display_description(
            original_description
        )

        for label, value in [
            ("Type", rec.get("kind", "")),
            ("Description", description),
            ("Category", rec.get("category_path", "")),
            ("Source ADMX", rec.get("source_file", "")),
            ("Source ADML", rec.get("source_adml", "")),
        ]:
            if value:
                self._insert_wrapped_detail(
                    parent,
                    label,
                    value
                )

    def _on_select(self, _event=None):
        # Keep the single-tree interface.
        pass

    # ---------------------------------------------------------
    # SEARCH
    # ---------------------------------------------------------

    def search(self):
        q = self.query.get().strip()

        if not q:
            self.clear_search()
            return

        found = search_records(
            self.records,
            q
        )

        self.tree.delete(
            *self.tree.get_children()
        )

        self.nodes.clear()

        group = self.tree.insert(
            "",
            "end",
            text=f"Search results ({len(found)})",
            open=True
        )

        self.nodes[group] = {
            "kind": "search"
        }

        for rec in found:
            loc = (
                f'{rec.get("branch", "")} / '
                f'{rec.get("category_path", "")}'
            )

            label = (
                f'{rec["name"]}  —  {loc}  —  '
                f'{rec.get("source_file", "")}'
            )

            iid = self.tree.insert(
                group,
                "end",
                text=label,
                open=False
            )

            self.nodes[iid] = rec

            self._add_placeholder_if_expandable(
                iid,
                rec
            )

        self.status.set(
            f"Search results: {len(found)} policy/policies."
        )

        if not found:
            self.tree.insert(
                group,
                "end",
                text="No matching policies found."
            )

    def clear_search(self):
        self.query.set("")

        if hasattr(self, "result"):
            self._populate_roots()

            policy_count = sum(
                record.get("kind") == "policy"
                for record in self.records
            )

            self.status.set(
                f"ADMX found: {self.result.admx_found} | "
                f"Parsed: {self.result.admx_parsed} | "
                f"Policies: {policy_count} | "
                f"Warnings: {len(self.result.warnings)}"
            )


def main():
    root = tk.Tk()
    PolicyReaderApp(root)
    root.mainloop()


if __name__ == "__main__":
    main()
