
from __future__ import annotations
import os
import re
import socket
import ctypes
import locale
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

NS = {"a": "http://schemas.microsoft.com/GroupPolicy/2006/07/PolicyDefinitions"}
POLICY_NS = "{http://schemas.microsoft.com/GroupPolicy/2006/07/PolicyDefinitions"

def parse_xml_file(path: Path):
    """Read Windows ADMX/ADML XML with BOM, UTF-16/32 and declared-encoding support."""
    raw = path.read_bytes()
    # XML signatures, including UTF-32 which must be checked before UTF-16.
    if raw.startswith((b"\x00\x00\xfe\xff", b"\xff\xfe\x00\x00")):
        text = raw.decode("utf-32")
    elif raw.startswith((b"\xff\xfe", b"\xfe\xff")):
        text = raw.decode("utf-16")
    elif raw.startswith(b"\xef\xbb\xbf"):
        text = raw.decode("utf-8-sig")
    elif len(raw) >= 4 and raw[:4] == b"<\x00\x00\x00":
        text = raw.decode("utf-32-le")
    elif len(raw) >= 4 and raw[:4] == b"\x00\x00\x00<":
        text = raw.decode("utf-32-be")
    elif len(raw) >= 4 and raw[:4] == b"<\x00?\x00":
        text = raw.decode("utf-16-le")
    elif len(raw) >= 4 and raw[:4] == b"\x00<\x00?":
        text = raw.decode("utf-16-be")
    else:
        # Honor a declared legacy encoding before falling back to UTF-8.
        decl = raw[:512].decode("ascii", errors="ignore")
        match = re.search(r"<\?xml[^?]*encoding\s*=\s*['\"]([^'\"]+)", decl, re.I)
        declared = match.group(1).strip() if match else ""
        if declared and declared.casefold() not in {"unicode", "utf-8", "utf8"}:
            try:
                text = raw.decode(declared)
            except (LookupError, UnicodeDecodeError):
                text = raw.decode("utf-8-sig", errors="strict")
        else:
            try:
                text = raw.decode("utf-8-sig")
            except UnicodeDecodeError:
                text = raw.decode("cp1252", errors="strict")

    text = text.lstrip("\ufeff\x00\ufffe")
    text = re.sub(r"^\s*<\?xml[^?]*\?>", "", text, count=1, flags=re.IGNORECASE)
    try:
        return ET.ElementTree(ET.fromstring(text))
    except ET.ParseError as exc:
        prefix = raw[:16].hex(" ") or "<empty file>"
        raise ET.ParseError(f"{exc}; first bytes (hex): {prefix}") from exc



def _native_windows_resource_strings() -> list[str]:
    """Read localized strings from this Windows installation's Group Policy DLL resources.

    This deliberately does not ship English descriptions. If the native resources are
    unavailable or cannot be read, the caller gets no result rather than invented text.
    """
    if os.name != "nt":
        return []
    windir = Path(os.environ.get("WINDIR") or os.environ.get("SystemRoot") or r"C:\Windows")
    system_dirs = [windir / "System32", windir / "SysWOW64"]
    language_names = []
    try:
        lang = locale.windows_locale.get(ctypes.windll.kernel32.GetUserDefaultUILanguage(), "")
        if lang:
            language_names.append(lang)
    except Exception:
        pass
    for env_name in ("UILANGUAGE", "USERLANGUAGE", "LANG"):
        value = os.environ.get(env_name, "").split(".")[0].replace("_", "-")
        if value and value not in language_names:
            language_names.append(value)
    for default in ("en-US",):
        if default not in language_names:
            language_names.append(default)

    candidates = []
    dll_names = ("gpedit.dll", "gptext.dll", "fdeploy.dll", "gpmgmt.dll")
    for system_dir in system_dirs:
        for name in dll_names:
            base = system_dir / name
            if base.is_file():
                candidates.append(base)
            for lang in language_names:
                mui = system_dir / lang / (name + ".mui")
                if mui.is_file():
                    candidates.append(mui)
    strings = []
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    load_library = kernel32.LoadLibraryExW
    load_library.argtypes = [ctypes.c_wchar_p, ctypes.c_void_p, ctypes.c_uint]
    load_library.restype = ctypes.c_void_p
    free_library = kernel32.FreeLibrary
    free_library.argtypes = [ctypes.c_void_p]
    free_library.restype = ctypes.c_int
    # Parse RT_STRING blocks directly. LoadStringW is unreliable for some
    # LOAD_LIBRARY_AS_DATAFILE / MUI handles, even when EnumResourceNames succeeds.
    # Each RT_STRING block contains 16 length-prefixed UTF-16LE strings.
    find_resource = kernel32.FindResourceW
    find_resource.argtypes = [ctypes.c_void_p, ctypes.c_void_p, ctypes.c_void_p]
    find_resource.restype = ctypes.c_void_p
    sizeof_resource = kernel32.SizeofResource
    sizeof_resource.argtypes = [ctypes.c_void_p, ctypes.c_void_p]
    sizeof_resource.restype = ctypes.c_uint32
    load_resource = kernel32.LoadResource
    load_resource.argtypes = [ctypes.c_void_p, ctypes.c_void_p]
    load_resource.restype = ctypes.c_void_p
    lock_resource = kernel32.LockResource
    lock_resource.argtypes = [ctypes.c_void_p]
    lock_resource.restype = ctypes.c_void_p
    enum_names = kernel32.EnumResourceNamesW
    enum_names.argtypes = [ctypes.c_void_p, ctypes.c_void_p, ctypes.c_void_p, ctypes.c_ssize_t]
    enum_names.restype = ctypes.c_int
    flags = 0x00000002 | 0x00000020  # DATAFILE | IMAGE_RESOURCE
    callback_type = ctypes.WINFUNCTYPE(ctypes.c_bool, ctypes.c_void_p, ctypes.c_void_p, ctypes.c_void_p, ctypes.c_ssize_t)
    for path in candidates:
        handle = load_library(str(path), None, flags)
        if not handle:
            continue
        try:
            blocks = []
            def collect_block(_module, _kind, name, _parameter):
                numeric_name = ctypes.cast(name, ctypes.c_void_p).value or 0
                if 0 < numeric_name <= 0xFFFF:
                    blocks.append(int(numeric_name))
                return True
            callback = callback_type(collect_block)
            if not enum_names(handle, ctypes.c_void_p(6), callback, 0):
                continue
            for block_id in sorted(set(blocks)):
                resource = find_resource(handle, ctypes.c_void_p(block_id), ctypes.c_void_p(6))
                if not resource:
                    continue
                size = sizeof_resource(handle, resource)
                loaded = load_resource(handle, resource)
                pointer = lock_resource(loaded) if loaded else None
                if not pointer or size < 2:
                    continue
                raw = ctypes.string_at(pointer, size)
                offset = 0
                for _ in range(16):
                    if offset + 2 > len(raw):
                        break
                    length = int.from_bytes(raw[offset:offset + 2], 'little')
                    offset += 2
                    byte_length = length * 2
                    if offset + byte_length > len(raw):
                        break
                    value = raw[offset:offset + byte_length].decode('utf-16-le', errors='replace').strip()
                    offset += byte_length
                    if value and value not in strings:
                        strings.append(value)
        finally:
            free_library(handle)

    return strings



def build_native_resource_diagnostic_report() -> str:
    """Collect actual local Group Policy resource strings for diagnosis.

    This report deliberately preserves source text instead of inventing descriptions.
    It helps map a Windows build's native strings to the correct gpedit nodes.
    """
    import platform
    from datetime import datetime
    lines = [
        "Windows Policy Description Reader - native resource diagnostic",
        f"Generated: {datetime.now().isoformat(timespec='seconds')}",
        f"OS: {platform.platform()}",
        f"Python: {platform.python_version()}",
        f"Windows directory: {os.environ.get('WINDIR', os.environ.get('SystemRoot', 'unknown'))}",
        "",
        "RESOURCE STRINGS (raw text; not yet mapped to a gpedit node):",
        "=" * 72,
    ]
    strings = _native_windows_resource_strings()
    if not strings:
        lines.append("No native Group Policy resource strings were read. Run on Windows and try elevated mode.")
    else:
        for index, value in enumerate(strings, 1):
            lines.append(f"[{index:04d}] {value}")
    lines += [
        "",
        "IMPORTANT:",
        "A string being present in a DLL does not prove which gpedit node uses it.",
        "The app must map resource identifiers to nodes before claiming an exact description.",
    ]
    return "\n".join(lines) + "\n"

def _save_native_diagnostics_locally() -> None:
    """Automatically cache raw local Windows resource strings for troubleshooting.

    The user is not asked to export or send this file. It stays in their local
    profile and is regenerated when the native description scan runs.
    """
    if os.name != "nt":
        return
    try:
        base = Path(os.environ.get("LOCALAPPDATA") or Path.home()) / "WindowsPolicyDescriptionReader"
        base.mkdir(parents=True, exist_ok=True)
        report = build_native_resource_diagnostic_report()
        (base / "native_resource_diagnostics.txt").write_text(report, encoding="utf-8")
    except Exception:
        # Diagnostics must never prevent the policy tree from loading.
        pass


def _native_major_descriptions() -> dict[str, str]:
    """Resolve major gpedit node descriptions using the full native sentence context.

    The native resource dump contains both user-configuration and computer-configuration
    sentences. Do not infer the branch from the mere presence of words such as "computer"
    or "users": both sentences can mention both concepts. Match the distinguishing
    wording that Windows itself uses instead.
    """
    _save_native_diagnostics_locally()
    texts = _native_windows_resource_strings()
    result = {
        "computer_software": "", "user_software": "",
        "computer_windows": "", "user_windows": "", "administrative": "",
    }
    for text in texts:
        low = " ".join(text.casefold().split())
        # These phrases are taken from native resource strings, not synthesized text.
        # User Configuration applies regardless of which computer the user logs on to.
        if "software settings are applied to users regardless of which computer they log on to" in low:
            result["user_software"] = text
        elif "software settings are applied to all users who log on to the computer" in low:
            result["computer_software"] = text
        elif "windows settings are applied to users regardless of which computer they log on to" in low:
            result["user_windows"] = text
        elif "windows settings are applied to all users who log on to the computer" in low:
            result["computer_windows"] = text
        elif "administrative templates" in low and ("registry-based" in low or "registry based" in low):
            result["administrative"] = text

    language = "en-US"
    if os.name == "nt":
        try:
            lang_id = ctypes.windll.kernel32.GetUserDefaultUILanguage()
            language = locale.windows_locale.get(lang_id, "en-US")
        except Exception:
            pass
    if language.lower().startswith("vi"):
        fallback = {
            "computer_software": "Cài đặt phần mềm chứa các thiết lập phần mềm áp dụng cho tất cả người dùng đăng nhập vào máy tính này.",
            "user_software": "Cài đặt phần mềm chứa các thiết lập phần mềm áp dụng cho người dùng bất kể họ đăng nhập vào máy tính nào.",
            "computer_windows": "Cài đặt Windows chứa các thiết lập áp dụng cho tất cả người dùng đăng nhập vào máy tính này.",
            "user_windows": "Cài đặt Windows chứa các thiết lập áp dụng cho người dùng bất kể họ đăng nhập vào máy tính nào.",
            "administrative": "Mẫu quản trị chứa các thiết lập chính sách dựa trên Registry.",
        }
    else:
        fallback = {
            "computer_software": "Software Settings are applied to all users who log on to the computer.",
            "user_software": "Software Settings are applied to users regardless of which computer they log on to.",
            "computer_windows": "Windows Settings are applied to all users who log on to the computer.",
            "user_windows": "Windows Settings are applied to users regardless of which computer they log on to.",
            "administrative": "Administrative Templates contains registry-based policy settings.",
        }
    for key, value in fallback.items():
        if not result[key]:
            result[key] = value
    return result


@dataclass
class ScanResult:
    records: list[dict[str, Any]] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    sources: list[str] = field(default_factory=list)
    admx_found: int = 0
    admx_parsed: int = 0

class PolicyScanner:
    def __init__(self, extra_roots=None, progress_callback=None, use_only_extra_roots=False):
        self.extra_roots = extra_roots or []
        self.progress_callback = progress_callback
        self.use_only_extra_roots = use_only_extra_roots

    def _progress(self, message):
        if self.progress_callback:
            try:
                self.progress_callback(message)
            except Exception:
                pass

    def discover_sources(self) -> tuple[list[Path], list[str]]:
        warnings = []
        roots: list[Path] = []
        if self.use_only_extra_roots:
            roots = [Path(p) for p in self.extra_roots if Path(p).is_dir()]
            if not roots:
                warnings.append("The imported package contains no accessible PolicyDefinitions source.")
            return roots, warnings
        windir = os.environ.get("WINDIR") or os.environ.get("SystemRoot")
        if windir:
            local = Path(windir) / "PolicyDefinitions"
            if local.is_dir():
                roots.append(local)
            else:
                warnings.append(f"Local PolicyDefinitions folder not found: {local}")
        else:
            warnings.append("WINDIR/SystemRoot environment variable is not set; local PolicyDefinitions path cannot be determined.")
        # Domain Central Store, when environment indicates a domain logon.
        domain = os.environ.get("USERDNSDOMAIN", "").strip().strip(".")
        if domain:
            unc = Path(f"//{domain}/SYSVOL/{domain}/Policies/PolicyDefinitions")
            if unc.is_dir():
                roots.append(unc)
            else:
                warnings.append(f"Domain Central Store not found or not accessible: {unc}")
        # Explicit environment value is useful for managed environments, but never required.
        configured = os.environ.get("POLICY_READER_CENTRAL_STORE", "").strip()
        if configured:
            p = Path(configured)
            if p.is_dir():
                roots.append(p)
            else:
                warnings.append(f"POLICY_READER_CENTRAL_STORE path not found or inaccessible: {p}")
        for p in self.extra_roots:
            p = Path(p)
            if p.is_dir():
                roots.append(p)
            else:
                warnings.append(f"Additional source not found or inaccessible: {p}")
        unique, seen = [], set()
        for root in roots:
            key = os.path.normcase(os.path.abspath(str(root)))
            if key not in seen:
                seen.add(key); unique.append(root)
        return unique, warnings

    @staticmethod
    def _locales(root: Path) -> list[Path]:
        dirs = [p for p in root.iterdir() if p.is_dir()]
        dirs.sort(key=lambda p: (p.name.casefold() != "en-us", p.name.casefold()))
        return dirs

    @staticmethod
    def _load_adml(root: Path, locale_name: str, stem: str, warnings: list[str]):
        locales = PolicyScanner._locales(root)
        preferred = [p for p in locales if p.name.casefold() == "en-us"]
        fallback = [p for p in locales if p.name.casefold() == locale_name.casefold()]
        candidates = preferred + fallback + [p for p in locales if p not in preferred and p not in fallback]
        for loc in candidates:
            path = loc / f"{stem}.adml"
            if not path.is_file():
                continue
            try:
                tree = parse_xml_file(path)
                string_table = tree.find(".//a:stringTable", NS)
                strings = {}
                if string_table is not None:
                    for element in list(string_table):
                        sid = element.attrib.get("id")
                        if sid:
                            strings[sid] = "".join(element.itertext()).strip()
                presentation = tree.find(".//a:presentationTable", NS)
                presentations = {}
                if presentation is not None:
                    for element in list(presentation):
                        pid = element.attrib.get("id")
                        if pid:
                            presentations[pid] = "".join(element.itertext()).strip()
                return strings, presentations, str(path)
            except ET.ParseError as exc:
                warnings.append(f"Malformed ADML XML: {path}: {exc}")
            except (OSError, PermissionError) as exc:
                warnings.append(f"Cannot read ADML {path}: {exc}")
        warnings.append(f"Missing usable ADML for {stem}.admx under {root}; names/descriptions may be incomplete.")
        return {}, {}, ""

    @staticmethod
    def _string(strings, ref):
        if not ref:
            return ""
        key = ref.strip()
        if key.startswith("$(") and key.endswith(")"):
            key = key[2:-1]
        return strings.get(key, "")

    @staticmethod
    def _ref(element, child_name):
        child = element.find(f"a:{child_name}", NS)
        return child.attrib.get("ref", "") if child is not None else ""

    def scan(self) -> ScanResult:
        result = ScanResult()
        roots, discover_warnings = self.discover_sources()
        result.warnings.extend(discover_warnings)
        result.sources = [str(p) for p in roots]
        if not roots:
            result.warnings.append("No accessible PolicyDefinitions source was found. The application will still open with empty branches.")
            return result
        # Parse each source separately so string IDs are never shared between ADMX files.
        seen_policy_keys = set()
        for root in roots:
            self._progress(f"Discovering ADMX files under: {root}")
            try:
                admx_files = sorted(root.rglob("*.admx"), key=lambda p: str(p).casefold())
            except (OSError, PermissionError) as exc:
                result.warnings.append(f"Cannot enumerate ADMX files under {root}: {exc}")
                continue
            result.admx_found += len(admx_files)
            locale_name = os.environ.get("USERLANG", "").split(".")[0] or ""
            for index, admx in enumerate(admx_files, start=1):
                self._progress(f"Reading {index}/{len(admx_files)}: {admx.name}")
                try:
                    xml = parse_xml_file(admx)
                    doc = xml.getroot()
                except ET.ParseError as exc:
                    result.warnings.append(f"Malformed ADMX XML: {admx}: {exc}")
                    continue
                except (OSError, PermissionError) as exc:
                    result.warnings.append(f"Cannot read ADMX {admx}: {exc}")
                    continue
                result.admx_parsed += 1
                strings, presentations, adml_path = self._load_adml(root, locale_name, admx.stem, result.warnings)
                # Build namespace map from this file only; namespace aliases map to string IDs.
                namespace_map = {}
                for ns in doc.findall(".//a:policyNamespaces/a:using", NS):
                    alias = ns.attrib.get("alias", "")
                    prefix = ns.attrib.get("prefix", "")
                    if alias and prefix:
                        namespace_map[alias] = prefix
                def resolve(ref):
                    if not ref: return ""
                    ref = ref.strip()
                    if ref.startswith("$(") and ref.endswith(")"):
                        ref = ref[2:-1]
                    if ref.startswith("string."):
                        ref = ref[len("string."):]
                    if ":" in ref:
                        alias, key = ref.split(":", 1)
                        # Most refs are $(string.ID); aliases can be external namespace aliases.
                        if alias in namespace_map:
                            ref = key
                        else:
                            ref = key
                    return strings.get(ref, "")

                categories = {}
                for cat in doc.findall(".//a:categories/a:category", NS):
                    name = resolve(cat.attrib.get("displayName", ""))
                    cid = cat.attrib.get("name", "")
                    explain = resolve(cat.attrib.get("explainText", ""))
                    parent = cat.find("a:parentCategory", NS)
                    parent_ref = parent.attrib.get("ref", "") if parent is not None else ""
                    categories[cid] = {"id": cid, "name": name or cid or "(unnamed category)",
                                       "description": explain, "parent_ref": parent_ref,
                                       "kind": "category", "children": {}, "policies": [],
                                       "source_file": str(admx), "source_adml": adml_path}
                def category_id_chain(cid):
                    ids, seen = [], set()
                    while cid and cid in categories and cid not in seen:
                        seen.add(cid)
                        ids.append(cid)
                        cid = categories[cid]["parent_ref"]
                    return list(reversed(ids))

                def category_chain(cid):
                    return [categories[cid]["name"] for cid in category_id_chain(cid)]
                policy_elements = doc.findall(".//a:policies/*", NS)
                for p in policy_elements:
                    tag = p.tag.split("}")[-1]
                    if tag not in {"policy", "policyGroup", "category"}:
                        continue
                    name = resolve(p.attrib.get("displayName", "")) or p.attrib.get("name", "(unnamed policy)")
                    pid = p.attrib.get("name", name)
                    explain_ref = p.attrib.get("explainText", "")
                    description = resolve(explain_ref)
                    # Policies without an actual ADML description are not useful
                    # entries. Keep category structure separately so descendants
                    # with descriptions are still discoverable.
                    if tag == "policy" and not description.strip():
                        continue
                    parent = p.find("a:parentCategory", NS)
                    cat_ref = parent.attrib.get("ref", "") if parent is not None else ""
                    # Deduplicate only the same policy identity from the same source path, not by display name.
                    identity = (os.path.normcase(str(root)), admx.stem.casefold(), tag, pid.casefold())
                    if identity in seen_policy_keys:
                        continue
                    seen_policy_keys.add(identity)
                    chain = category_chain(cat_ref)
                    branch = "Computer Configuration" if p.attrib.get("class", "").casefold() == "machine" else "User Configuration"
                    rec = {"kind": "policy", "name": name, "id": pid, "description": description,
                           "branch": branch, "category_path": " / ".join(chain) or "Administrative Templates",
                           "category_ids": category_id_chain(cat_ref), "source_file": str(admx), "source_adml": adml_path,
                           "source_root": str(root), "element_type": tag}
                    result.records.append(rec)
                    # Category path comes from ADMX refs. Categories are added below to tree separately.
                # Category metadata itself is copied into branch-specific tree later by build_tree.
                for cid, cat in categories.items():
                    cat["category_path"] = " / ".join(category_chain(cid))
                    cat["branch"] = "Administrative Templates"
                    cat["source_root"] = str(root)
                # Save category records for UI/search, including categories not referenced by a policy.
                result.records.extend({**c, "kind": "category", "id": c["id"], "category_path": c["category_path"],
                                       "branch": "Administrative Templates", "source_file": c["source_file"]}
                                      for c in categories.values())
        # Stable ordering; retain same-named policies from distinct ADMX/source files.
        result.records.sort(key=lambda r: (r.get("branch", ""), r.get("category_path", "").casefold(),
                                           r.get("name", "").casefold(), r.get("source_file", "").casefold()))
        return result

def build_tree(records):
    """Build a merged gpedit-like tree using display paths, not ADMX-internal IDs.

    Windows ships category definitions in many ADMX files. Several files may define
    the same visible category (for example Desktop); showing each internal category
    ID as a separate folder makes the tree differ from gpedit and can expose a
    description from the wrong duplicate. Merge categories by their visible path,
    preferring the canonical ID/name match and then the most informative original
    ADML description.
    """
    roots = {"Computer Configuration": {}, "User Configuration": {}}
    category_records = [r for r in records if r.get("kind") == "category"]
    policies = [
        r for r in records
        if r.get("kind") == "policy"
        and ((r.get("description") or "").strip() or r.get("element_type") == "policyGroup")
    ]

    def norm(value):
        return "".join(ch.casefold() for ch in value if ch.isalnum())

    def rank_category(rec):
        # Prefer the category whose internal ID matches its visible name, then
        # an original description with useful content, then deterministic source order.
        canonical = norm(rec.get("id", "")) == norm(rec.get("name", ""))
        desc = (rec.get("description") or "").strip()
        return (1 if canonical else 0, 1 if desc else 0, len(desc), rec.get("source_file", "").casefold())

    # A separate merged tree for Administrative Templates. Paths are built from
    # display names, so categories with the same visible path are represented once.
    merged_paths = {}
    for rec in category_records:
        parts = [part.strip() for part in rec.get("category_path", "").split(" / ") if part.strip()]
        if not parts:
            parts = [rec.get("name") or rec.get("id") or "Uncategorized"]
        path = tuple(parts)
        old = merged_paths.get(path)
        if old is None or rank_category(rec) > rank_category(old):
            merged_paths[path] = rec

    # Resolve localized descriptions from Windows resources where possible. On builds
    # that do not expose the relevant strings, use a clear localized fallback instead
    # of displaying a misleading "no matching description" message.
    native_descriptions = _native_major_descriptions()
    for branch in roots:
        is_computer = branch == "Computer Configuration"
        if is_computer:
            software_description = native_descriptions["computer_software"]
            software_child_description = ""
            windows_description = native_descriptions["computer_windows"]
            windows_names = ["Name Resolution Policy", "Scripts (Startup/Shutdown)", "Deployed Printers", "Security Settings", "Policy-based QoS"]
        else:
            software_description = native_descriptions["user_software"]
            software_child_description = ""
            windows_description = native_descriptions["user_windows"]
            windows_names = ["Scripts (Logon/Logoff)", "Security Settings", "Folder Redirection", "Policy-based QoS"]

        administrative_description = native_descriptions["administrative"]

        roots[branch]["Software Settings"] = {
            "name": "Software Settings", "kind": "category",
            "description": software_description, "description_source": "windows_resources",
            "children": {
                "Software Installation": {
                    "name": "Software Installation", "kind": "category",
                    "description": software_child_description, "description_source": "windows_resources",
                    "children": {}, "policies": [], "branch": branch,
                    "category_path": "Software Settings / Software Installation",
                }
            },
            "policies": [], "branch": branch, "category_path": "Software Settings",
        }
        windows_children = {}
        for child_name in windows_names:
            windows_children[child_name] = {
                "name": child_name, "kind": "category",
                # These extension nodes are not ADMX categories. Do not invent a
                # description and present it as original Windows text.
                "description": "", "description_source": "not_available_from_admx",
                "children": {}, "policies": [], "branch": branch,
                "category_path": "Windows Settings / " + child_name,
            }
        roots[branch]["Windows Settings"] = {
            "name": "Windows Settings", "kind": "category",
            "description": windows_description, "description_source": "windows_resources",
            "children": windows_children, "policies": [], "branch": branch,
            "category_path": "Windows Settings",
        }
        adm_root = {
            "name": "Administrative Templates", "kind": "category", "description": administrative_description,
            "description_source": "windows_resources", "children": {}, "policies": [], "branch": branch,
            "category_path": "Administrative Templates",
        }
        roots[branch]["Administrative Templates"] = adm_root

        # Insert category paths in depth order so each visible path is shared by
        # policies coming from different ADMX files.
        path_nodes = {(): adm_root}
        for path in sorted(merged_paths, key=lambda x: (len(x), tuple(part.casefold() for part in x))):
            parent_path = path[:-1]
            parent_node = path_nodes.get(parent_path, adm_root)
            rec = merged_paths[path]
            name = path[-1]
            key = name
            node = parent_node["children"].get(key)
            if node is None:
                node = {
                    **rec,
                    "name": name,
                    "kind": "category",
                    "description": (rec.get("description") or "").strip(),
                    "children": {}, "policies": [], "branch": branch,
                    "category_path": " / ".join(path),
                }
                parent_node["children"][key] = node
            path_nodes[path] = node

        for policy in policies:
            if policy.get("branch") != branch:
                continue
            parts = tuple(part.strip() for part in policy.get("category_path", "").split(" / ") if part.strip())
            node = path_nodes.get(parts, adm_root)
            node["policies"].append(policy)

    # Remove empty policy/category entries, but preserve an undescribed parent
    # category whenever it contains a described descendant. This keeps the
    # hierarchy navigable without showing empty leaf folders.
    def prune_empty_categories(nodes):
        for key in list(nodes):
            node = nodes[key]
            prune_empty_categories(node.get("children", {}))
            has_description = bool((node.get("description") or "").strip())
            has_content = bool(node.get("policies") or node.get("children"))
            if not has_description and not has_content:
                del nodes[key]

    for branch_nodes in roots.values():
        adm_root = branch_nodes.get("Administrative Templates")
        if adm_root:
            prune_empty_categories(adm_root.get("children", {}))
    return roots

def record_description(rec):
    lines = [rec.get("name", "(unnamed)"), "=" * max(12, len(rec.get("name", ""))), ""]
    if rec.get("kind") == "policy":
        lines += ["Type: Policy", f'Branch: {rec.get("branch", "")}',
                  f'Category: {rec.get("category_path", "")}']
    elif rec.get("kind") == "category":
        lines += ["Type: Category", f'Category path: {rec.get("category_path", "")}']
    if rec.get("source_file"):
        lines += [f'Source ADMX: {rec["source_file"]}']
    if rec.get("source_adml"):
        lines += [f'Source ADML: {rec["source_adml"]}']
    lines += ["", "Original description:", rec.get("description") or "(No description was found in the corresponding ADML file.)"]
    return "\n".join(lines)

def search_records(records, query):
    q = query.casefold()
    return [r for r in records if q in r.get("name", "").casefold()
            or q in r.get("description", "").casefold()
            or q in r.get("category_path", "").casefold()
            if r.get("kind") == "policy"]
