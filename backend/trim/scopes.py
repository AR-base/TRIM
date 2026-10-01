"""Permission catalog: what each OAuth scope allows, in plain language and in API methods.

The catalog is the explainable core of Trim. Each scope lists the API methods
it unlocks and the narrower scopes it includes. From an agent's observed method
calls Trim derives the smallest set of scopes that still covers everything it
did, and keeps a reason ("kept gmail.send because it called messages.send") for
every scope it keeps.

Method ids follow Google's discovery naming as reported by the Admin SDK
OAuth token audit log (e.g. ``gmail.users.messages.send``).
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass, field

GOOGLE_PREFIX = "https://www.googleapis.com/auth/"


@dataclass(frozen=True)
class ScopeInfo:
    short: str
    scope: str
    family: str
    risk: int  # 1 low, 2 medium, 3 high
    phrase: str
    methods: tuple[str, ...] = ()
    includes: tuple[str, ...] = ()
    essential: bool = False


def _g(short: str) -> str:
    return GOOGLE_PREFIX + short


_SCOPES: list[ScopeInfo] = [
    # Identity: needed to sign the user in, never trimmed.
    ScopeInfo("openid", "openid", "identity", 1, "know who the user is", ("oauth2.userinfo.get",), essential=True),
    ScopeInfo(
        "userinfo.email",
        _g("userinfo.email"),
        "identity",
        1,
        "see the user's email address",
        ("oauth2.userinfo.get",),
        essential=True,
    ),
    ScopeInfo(
        "userinfo.profile",
        _g("userinfo.profile"),
        "identity",
        1,
        "see the user's basic profile",
        ("oauth2.userinfo.get",),
        essential=True,
    ),
    # Gmail
    ScopeInfo(
        "gmail.readonly",
        _g("gmail.readonly"),
        "gmail",
        2,
        "read all email",
        (
            "gmail.users.messages.get",
            "gmail.users.messages.list",
            "gmail.users.threads.get",
            "gmail.users.threads.list",
            "gmail.users.labels.list",
            "gmail.users.labels.get",
            "gmail.users.history.list",
            "gmail.users.getProfile",
            "gmail.users.messages.attachments.get",
        ),
    ),
    ScopeInfo(
        "gmail.send",
        _g("gmail.send"),
        "gmail",
        2,
        "send email as the user",
        ("gmail.users.messages.send", "gmail.users.drafts.send"),
    ),
    ScopeInfo(
        "gmail.compose",
        _g("gmail.compose"),
        "gmail",
        2,
        "write drafts and send email",
        ("gmail.users.drafts.create", "gmail.users.drafts.update", "gmail.users.drafts.list", "gmail.users.drafts.get"),
        includes=("gmail.send",),
    ),
    ScopeInfo(
        "gmail.modify",
        _g("gmail.modify"),
        "gmail",
        3,
        "read, label and bin all email",
        (
            "gmail.users.messages.modify",
            "gmail.users.messages.trash",
            "gmail.users.messages.untrash",
            "gmail.users.messages.batchModify",
            "gmail.users.threads.modify",
            "gmail.users.threads.trash",
            "gmail.users.labels.create",
        ),
        includes=("gmail.readonly", "gmail.compose"),
    ),
    ScopeInfo(
        "mail.full",
        "https://mail.google.com/",
        "gmail",
        3,
        "read, send and permanently delete all email",
        (
            "gmail.users.messages.delete",
            "gmail.users.messages.batchDelete",
            "gmail.users.threads.delete",
            "gmail.users.messages.import",
            "gmail.users.messages.insert",
        ),
        includes=("gmail.modify",),
    ),
    # Drive
    ScopeInfo("drive.file", _g("drive.file"), "drive", 1, "create new Drive files", ("drive.files.create",)),
    ScopeInfo(
        "drive.readonly",
        _g("drive.readonly"),
        "drive",
        2,
        "read every Drive file",
        (
            "drive.files.get",
            "drive.files.list",
            "drive.files.export",
            "drive.revisions.list",
            "drive.revisions.get",
            "drive.permissions.list",
            "drive.changes.list",
        ),
    ),
    ScopeInfo(
        "drive",
        _g("drive"),
        "drive",
        3,
        "read, edit, share and delete every Drive file",
        (
            "drive.files.update",
            "drive.files.delete",
            "drive.files.copy",
            "drive.files.emptyTrash",
            "drive.permissions.create",
            "drive.permissions.update",
            "drive.permissions.delete",
        ),
        includes=("drive.readonly", "drive.file"),
    ),
    # Calendar
    ScopeInfo(
        "calendar.readonly",
        _g("calendar.readonly"),
        "calendar",
        1,
        "see all calendars",
        (
            "calendar.events.list",
            "calendar.events.get",
            "calendar.calendarList.list",
            "calendar.freebusy.query",
            "calendar.calendars.get",
        ),
    ),
    ScopeInfo(
        "calendar.events",
        _g("calendar.events"),
        "calendar",
        2,
        "create and change calendar events",
        (
            "calendar.events.insert",
            "calendar.events.update",
            "calendar.events.patch",
            "calendar.events.delete",
            "calendar.events.quickAdd",
        ),
        includes=("calendar.readonly",),
    ),
    ScopeInfo(
        "calendar",
        _g("calendar"),
        "calendar",
        2,
        "fully manage and share all calendars",
        (
            "calendar.calendars.insert",
            "calendar.calendars.update",
            "calendar.calendars.delete",
            "calendar.acl.insert",
            "calendar.acl.update",
            "calendar.acl.delete",
        ),
        includes=("calendar.events",),
    ),
    # Sheets
    ScopeInfo(
        "spreadsheets.readonly",
        _g("spreadsheets.readonly"),
        "sheets",
        1,
        "read all spreadsheets",
        ("sheets.spreadsheets.get", "sheets.spreadsheets.values.get", "sheets.spreadsheets.values.batchGet"),
    ),
    ScopeInfo(
        "spreadsheets",
        _g("spreadsheets"),
        "sheets",
        2,
        "read and edit all spreadsheets",
        (
            "sheets.spreadsheets.create",
            "sheets.spreadsheets.batchUpdate",
            "sheets.spreadsheets.values.update",
            "sheets.spreadsheets.values.append",
            "sheets.spreadsheets.values.batchUpdate",
            "sheets.spreadsheets.values.clear",
        ),
        includes=("spreadsheets.readonly",),
    ),
    # Contacts and directory
    ScopeInfo(
        "contacts.readonly",
        _g("contacts.readonly"),
        "people",
        1,
        "see the user's contacts",
        ("people.people.connections.list", "people.people.get", "people.contactGroups.list"),
    ),
    ScopeInfo(
        "contacts",
        _g("contacts"),
        "people",
        2,
        "edit the user's contacts",
        ("people.people.createContact", "people.people.updateContact", "people.people.deleteContact"),
        includes=("contacts.readonly",),
    ),
    ScopeInfo(
        "directory.readonly",
        _g("directory.readonly"),
        "people",
        2,
        "see the whole company directory",
        ("people.people.listDirectoryPeople", "people.people.searchDirectoryPeople"),
    ),
    # Admin
    ScopeInfo(
        "admin.directory.user.readonly",
        _g("admin.directory.user.readonly"),
        "admin",
        2,
        "see every user account",
        ("admin.directory.users.list", "admin.directory.users.get"),
    ),
    ScopeInfo(
        "admin.directory.user",
        _g("admin.directory.user"),
        "admin",
        3,
        "create, change and delete user accounts",
        (
            "admin.directory.users.insert",
            "admin.directory.users.update",
            "admin.directory.users.patch",
            "admin.directory.users.delete",
            "admin.directory.users.makeAdmin",
        ),
        includes=("admin.directory.user.readonly",),
    ),
]

BY_SHORT: dict[str, ScopeInfo] = {s.short: s for s in _SCOPES}
BY_SCOPE: dict[str, ScopeInfo] = {s.scope: s for s in _SCOPES}
WRITE_VERBS = (
    "send",
    "insert",
    "update",
    "patch",
    "delete",
    "create",
    "modify",
    "trash",
    "append",
    "clear",
    "import",
    "batchUpdate",
    "batchModify",
    "batchDelete",
    "makeAdmin",
    "copy",
    "emptyTrash",
    "quickAdd",
)


def info(scope: str) -> ScopeInfo | None:
    """Look up a scope by its full URL or its short name."""
    return BY_SCOPE.get(scope) or BY_SHORT.get(scope)


def short_name(scope: str) -> str:
    i = info(scope)
    if i:
        return i.short
    return scope.removeprefix(GOOGLE_PREFIX)


def is_write_method(method: str) -> bool:
    verb = method.rsplit(".", 1)[-1]
    return verb in WRITE_VERBS


def closure(shorts: Iterable[str]) -> set[str]:
    """All catalogued scopes reachable through ``includes`` (the scopes themselves included)."""
    seen: set[str] = set()
    stack = [s for s in shorts if s in BY_SHORT]
    while stack:
        cur = stack.pop()
        if cur in seen:
            continue
        seen.add(cur)
        stack.extend(BY_SHORT[cur].includes)
    return seen


def effective_methods(short: str) -> frozenset[str]:
    methods: set[str] = set()
    for s in closure([short]):
        methods.update(BY_SHORT[s].methods)
    return frozenset(methods)


def risk(scope: str) -> int:
    i = info(scope)
    return i.risk if i else 2


# Plain-language capability questions ("which agents can send email?") -> scopes that grant it.
CAPABILITIES: dict[str, tuple[str, set[str]]] = {
    "read_email": ("read email", {"gmail.readonly"}),
    "send_email": ("send email", {"gmail.send"}),
    "delete_email": ("permanently delete email", {"mail.full"}),
    "read_files": ("read Drive files", {"drive.readonly"}),
    "edit_files": ("edit, share or delete Drive files", {"drive"}),
    "read_calendar": ("see calendars", {"calendar.readonly"}),
    "edit_calendar": ("change calendars", {"calendar.events"}),
    "read_directory": (
        "see the company directory or user accounts",
        {"directory.readonly", "admin.directory.user.readonly"},
    ),
    "manage_users": ("create, change or delete user accounts", {"admin.directory.user"}),
}


def grants_capability(scopes: Iterable[str], capability: str) -> bool:
    _, needed = CAPABILITIES[capability]
    have = closure(short_name(s) for s in scopes)
    return bool(have & needed)


@dataclass
class CoverResult:
    keep: dict[str, list[str]] = field(default_factory=dict)  # full scope -> methods that justify it
    remove: list[str] = field(default_factory=list)  # full scopes granted but not needed
    uncovered: list[str] = field(default_factory=list)  # methods no catalogued scope explains
    narrowed: dict[str, list[str]] = field(default_factory=dict)  # removed broad scope -> narrower ones kept


def minimal_cover(granted: Iterable[str], used_methods: Iterable[str]) -> CoverResult:
    """Smallest-risk set of scopes, within what was granted, that covers every used method.

    Rules, in order:
    1. Identity scopes and scopes Trim does not recognise are always kept (never guess).
    2. Each used method is assigned the lowest-risk, narrowest scope that covers it and is
       reachable from the granted scopes (so Trim never proposes *more* access).
    3. A kept scope that another kept scope already includes is dropped as redundant.
    4. If a method cannot be explained, the broadest granted scope of the same API family stays.
    """
    granted_list = list(dict.fromkeys(granted))
    used = sorted(set(used_methods))
    result = CoverResult()

    known = [g for g in granted_list if info(g)]
    for g in granted_list:
        i = info(g)
        if i is None or i.essential:
            result.keep.setdefault(g, [])

    candidates = closure(info(g).short for g in known)
    picked: dict[str, list[str]] = {}
    for method in used:
        options = [s for s in candidates if method in effective_methods(s)]
        if not options:
            result.uncovered.append(method)
            continue
        if any(BY_SHORT[s].essential for s in options):
            continue  # identity calls are justified by the identity scopes
        best = min(options, key=lambda s: (BY_SHORT[s].risk, len(effective_methods(s)), s))
        picked.setdefault(best, []).append(method)

    for method in result.uncovered:
        family = method.split(".", 1)[0]
        same_family = [g for g in known if info(g).family == family]
        if same_family:
            broadest = max(same_family, key=lambda g: (info(g).risk, len(effective_methods(info(g).short))))
            picked.setdefault(info(broadest).short, []).append(method)

    # Drop picks that another pick already includes (merge their justifying methods upward).
    for s in sorted(picked, key=lambda k: BY_SHORT[k].risk):
        broader = [o for o in picked if o != s and s in closure([o])]
        if broader:
            picked[broader[0]].extend(picked.pop(s))

    for s, methods in picked.items():
        result.keep.setdefault(BY_SHORT[s].scope, []).extend(sorted(set(methods)))

    kept_short = {info(k).short for k in result.keep if info(k)}
    for g in granted_list:
        if g in result.keep:
            continue
        result.remove.append(g)
        g_short = info(g).short
        replacements = sorted(k for k in kept_short if k != g_short and k in closure([g_short]))
        if replacements:
            result.narrowed[g] = [BY_SHORT[k].scope for k in replacements]
    return result


def reach_sentence(scopes: Iterable[str], user_count: int | None = None) -> str:
    """One plain sentence describing what a set of scopes lets an agent do."""
    scopes = list(dict.fromkeys(scopes))
    known = [info(s) for s in scopes if info(s)]
    unknown = [s for s in scopes if not info(s)]
    shorts = {k.short for k in known}
    # Only describe the broadest scopes; narrower included ones are implied.
    top = [k for k in known if not any(k.short in closure([o]) - {o} for o in shorts)]
    meaningful = [k for k in top if not k.essential]
    meaningful.sort(key=lambda k: (-k.risk, k.family, k.short))
    phrases = [k.phrase for k in meaningful] + [f"use {short_name(u)}" for u in unknown]
    if not phrases:
        base = "Can only confirm who the user is"
    elif len(phrases) == 1:
        base = f"Can {phrases[0]}"
    else:
        base = "Can " + ", ".join(phrases[:-1]) + f" and {phrases[-1]}"
    if user_count is not None and user_count > 0:
        base += f", for {user_count} {'person' if user_count == 1 else 'people'}"
    return base + "."
