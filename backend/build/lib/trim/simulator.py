"""Synthetic organisation generator with labelled attack scenarios.

Real enterprise agent logs are not available to a student team, so Trim ships a
simulator. It creates users and AI agents from eight archetypes, each granted
more access than it needs (as happens in practice), generates realistic daily
API activity, and injects labelled incidents. The labels let us measure the
recommender and the anomaly model with precision and recall.

Everything is deterministic for a given seed.
"""

from __future__ import annotations

import random
from dataclasses import dataclass, field
from datetime import UTC, date, datetime, timedelta

import numpy as np

from trim.connectors.base import ActivityRecord
from trim.connectors.simulated import SimulatedConnector
from trim.scopes import GOOGLE_PREFIX as G

ID = ["openid", G + "userinfo.email"]
DOMAIN = "acme-test.eu"

# method -> mean response bytes
BYTES = {
    "list": 6_000,
    "get": 25_000,
    "export": 400_000,
    "send": 2_000,
    "create": 3_000,
    "update": 2_500,
    "append": 2_000,
    "insert": 2_000,
    "patch": 1_500,
    "modify": 800,
    "delete": 400,
    "makeAdmin": 300,
    "attachments.get": 300_000,
}


def _mean_bytes(method: str) -> int:
    if method.endswith("attachments.get"):
        return BYTES["attachments.get"]
    return BYTES.get(method.rsplit(".", 1)[-1], 5_000)


@dataclass(frozen=True)
class Archetype:
    key: str
    names: tuple[str, ...]
    granted: tuple[str, ...]
    needed: tuple[str, ...]
    methods: dict[str, float]
    calls_per_user: float
    hours: tuple[int, int]  # active UTC hours [start, end)
    users: tuple[int, int]
    attack_methods: tuple[str, ...] = ()


ARCHETYPES: tuple[Archetype, ...] = (
    Archetype(
        "inbox_copilot",
        ("Inbox Copilot", "MailPilot", "Triage AI", "Reply Assist"),
        granted=(*ID, "https://mail.google.com/", G + "calendar", G + "drive"),
        needed=(*ID, G + "gmail.readonly", G + "gmail.compose"),
        methods={
            "gmail.users.messages.list": 4,
            "gmail.users.messages.get": 8,
            "gmail.users.threads.get": 3,
            "gmail.users.drafts.create": 1.5,
            "gmail.users.labels.list": 0.5,
        },
        calls_per_user=14,
        hours=(7, 19),
        users=(3, 8),
        attack_methods=(
            "gmail.users.messages.send",
            "gmail.users.messages.delete",
            "gmail.users.messages.attachments.get",
        ),
    ),
    Archetype(
        "meeting_notes",
        ("MeetingNotes AI", "Minutes Bot", "Recap"),
        granted=(*ID, G + "calendar", G + "drive", G + "gmail.readonly"),
        needed=(*ID, G + "calendar.readonly", G + "drive.file"),
        methods={"calendar.events.list": 3, "calendar.events.get": 4, "drive.files.create": 1.2},
        calls_per_user=7,
        hours=(8, 18),
        users=(4, 10),
        attack_methods=("drive.files.export", "drive.files.list", "drive.permissions.create"),
    ),
    Archetype(
        "sales_reach",
        ("SalesReach", "Outbound GPT", "LeadFlow"),
        granted=(*ID, "https://mail.google.com/", G + "contacts", G + "spreadsheets", G + "directory.readonly"),
        needed=(*ID, G + "gmail.send", G + "contacts.readonly", G + "spreadsheets.readonly"),
        methods={
            "gmail.users.messages.send": 3,
            "people.people.connections.list": 1.5,
            "sheets.spreadsheets.values.get": 2,
        },
        calls_per_user=9,
        hours=(8, 18),
        users=(2, 6),
        attack_methods=("people.people.listDirectoryPeople", "gmail.users.messages.list", "gmail.users.messages.get"),
    ),
    Archetype(
        "finance_sync",
        ("FinanceSync", "LedgerBot"),
        granted=(*ID, G + "spreadsheets", G + "drive"),
        needed=(*ID, G + "spreadsheets"),
        methods={
            "sheets.spreadsheets.values.get": 3,
            "sheets.spreadsheets.values.update": 2,
            "sheets.spreadsheets.values.append": 2,
        },
        calls_per_user=10,
        hours=(1, 4),
        users=(2, 4),  # nightly batch: off-hours is normal for it
        attack_methods=("drive.files.list", "drive.files.export", "drive.files.get"),
    ),
    Archetype(
        "recruit_screener",
        ("Recruit Screener", "TalentLens"),
        granted=(*ID, G + "gmail.readonly", G + "drive.readonly", G + "admin.directory.user.readonly"),
        needed=(*ID, G + "gmail.readonly", G + "drive.readonly"),
        methods={
            "drive.files.list": 2,
            "drive.files.get": 5,
            "gmail.users.messages.list": 2,
            "gmail.users.messages.get": 4,
        },
        calls_per_user=10,
        hours=(8, 18),
        users=(2, 4),
        attack_methods=("admin.directory.users.list", "admin.directory.users.get"),
    ),
    Archetype(
        "devops_helper",
        ("DevOps Helper", "OpsGPT"),
        granted=(*ID, G + "admin.directory.user", G + "drive", G + "gmail.send"),
        needed=(*ID, G + "admin.directory.user.readonly"),
        methods={"admin.directory.users.list": 2, "admin.directory.users.get": 4},
        calls_per_user=6,
        hours=(7, 20),
        users=(1, 3),
        attack_methods=(
            "admin.directory.users.update",
            "admin.directory.users.makeAdmin",
            "admin.directory.users.insert",
        ),
    ),
    Archetype(
        "scheduler",
        ("Calendar Scheduler", "SlotFinder"),
        granted=(*ID, G + "calendar.events"),
        needed=(*ID, G + "calendar.events"),
        methods={"calendar.events.list": 4, "calendar.events.insert": 1.5, "calendar.events.patch": 1},
        calls_per_user=8,
        hours=(7, 19),
        users=(3, 8),
        attack_methods=("calendar.events.delete",),
    ),
    Archetype(
        "dormant",
        ("Old Experiment", "Hackathon Bot"),
        granted=(*ID, G + "drive", G + "gmail.readonly"),
        needed=(),
        methods={},
        calls_per_user=0,
        hours=(9, 17),
        users=(1, 3),
    ),
)

DEPARTMENTS = ("Engineering", "Sales", "Finance", "People", "Operations")
FIRST = (
    "Alex",
    "Sam",
    "Noa",
    "Leo",
    "Ines",
    "Hugo",
    "Maya",
    "Jules",
    "Emma",
    "Ravi",
    "Lina",
    "Tom",
    "Zoe",
    "Omar",
    "Chloe",
    "Ana",
    "Paul",
    "Sara",
    "Yann",
    "Mila",
    "Theo",
    "Nina",
    "Adam",
    "Lea",
)
LAST = (
    "Martin",
    "Bernard",
    "Petit",
    "Durand",
    "Leroy",
    "Moreau",
    "Simon",
    "Laurent",
    "Michel",
    "Garcia",
    "Rao",
    "Roux",
    "Fournier",
    "Girard",
    "Bonnet",
    "Dupont",
    "Lambert",
    "Fontaine",
)

ATTACK_KINDS = ("exfiltration", "goal_hijack", "off_hours", "slow_creep")


@dataclass
class AgentInstance:
    client_id: str
    name: str
    archetype: Archetype
    users: list[str]
    rate: float


@dataclass
class Incident:
    client_id: str
    kind: str
    days: list[date]


@dataclass
class Scenario:
    start: datetime
    days: int
    users: list[tuple[str, str, str]]
    agents: list[AgentInstance]
    events: list[ActivityRecord]
    incidents: list[Incident]
    benign_spikes: list[tuple[str, date]] = field(default_factory=list)

    @property
    def now(self) -> datetime:
        return self.start + timedelta(days=self.days, minutes=30)

    @property
    def anomalous_days(self) -> set[tuple[str, date]]:
        return {(i.client_id, d) for i in self.incidents for d in i.days}

    def needed_scopes(self, client_id: str) -> set[str]:
        for a in self.agents:
            if a.client_id == client_id:
                return set(a.archetype.needed)
        raise KeyError(client_id)


class _EventFactory:
    def __init__(self, rng: random.Random, nrng: np.random.Generator) -> None:
        self.rng, self.nrng, self.n = rng, nrng, 0

    def make(
        self, agent: AgentInstance, user: str | None, method: str, day: date, hour: int, bytes_scale: float = 1.0
    ) -> ActivityRecord:
        self.n += 1
        ts = datetime(
            day.year, day.month, day.day, hour % 24, self.rng.randrange(60), self.rng.randrange(60), tzinfo=UTC
        )
        nbytes = int(_mean_bytes(method) * bytes_scale * float(self.nrng.lognormal(0, 0.45)))
        return ActivityRecord(
            uid=f"sim:{self.n}",
            client_id=agent.client_id,
            app_name=agent.name,
            user_email=user,
            api_name=method.split(".", 1)[0],
            method_name=method,
            response_bytes=nbytes,
            occurred_at=ts,
        )


def _normal_day(f: _EventFactory, agent: AgentInstance, day: date, volume: float = 1.0) -> list[ActivityRecord]:
    arch = agent.archetype
    if not arch.methods:
        return []
    methods = list(arch.methods)
    weights = list(arch.methods.values())
    weekend = 0.35 if day.weekday() >= 5 else 1.0
    out = []
    for user in agent.users:
        n = int(f.nrng.poisson(agent.rate * weekend * volume))
        for m in f.rng.choices(methods, weights=weights, k=n):
            out.append(f.make(agent, user, m, day, f.rng.randrange(*arch.hours)))
    return out


def _attack(f: _EventFactory, agent: AgentInstance, kind: str, day: date, step: int = 0) -> list[ActivityRecord]:
    arch = agent.archetype
    attack_methods = list(arch.attack_methods) or list(arch.methods)
    victim_users = agent.users
    out: list[ActivityRecord] = []
    if kind == "exfiltration":
        # Bulk read and download of data through methods the agent already may use or barely uses.
        n = int(agent.rate * len(victim_users) * f.rng.uniform(6, 10))
        for _ in range(n):
            m = f.rng.choice(attack_methods + list(arch.methods))
            out.append(
                f.make(
                    agent,
                    f.rng.choice(victim_users),
                    m,
                    day,
                    f.rng.randrange(*arch.hours),
                    bytes_scale=f.rng.uniform(6, 15),
                )
            )
    elif kind == "goal_hijack":
        # Injected instructions: the agent starts calling capabilities it never used.
        n = int(agent.rate * len(victim_users) * f.rng.uniform(0.6, 1.2))
        for _ in range(n):
            out.append(
                f.make(
                    agent, f.rng.choice(victim_users), f.rng.choice(attack_methods), day, f.rng.randrange(*arch.hours)
                )
            )
    elif kind == "off_hours":
        n = int(agent.rate * len(victim_users) * f.rng.uniform(2.5, 4))
        night = [h for h in range(24) if h not in range(*arch.hours) and h not in range(6, 21)] or [3]
        for _ in range(n):
            m = f.rng.choice(list(arch.methods) or attack_methods)
            out.append(f.make(agent, f.rng.choice(victim_users), m, day, f.rng.choice(night)))
    elif kind == "slow_creep":
        # Gradual drift over several days: a few new calls, then more.
        n = int(agent.rate * len(victim_users) * (0.15 + 0.35 * step))
        for _ in range(max(n, 2)):
            out.append(
                f.make(
                    agent, f.rng.choice(victim_users), f.rng.choice(attack_methods), day, f.rng.randrange(*arch.hours)
                )
            )
    return out


def build_scenario(
    seed: int = 7,
    n_users: int = 40,
    days: int = 28,
    baseline_days: int = 14,
    start: datetime | None = None,
    incidents: int = 12,
) -> Scenario:
    rng = random.Random(seed)
    nrng = np.random.default_rng(seed)
    start = start or datetime(2026, 9, 1, tzinfo=UTC)

    users = []
    names_used: set[str] = set()
    while len(users) < n_users:
        first, last = rng.choice(FIRST), rng.choice(LAST)
        email = f"{first}.{last}@{DOMAIN}".lower()
        if email in names_used:
            continue
        names_used.add(email)
        users.append((email, f"{first} {last}", rng.choice(DEPARTMENTS)))
    emails = [u[0] for u in users]

    agents: list[AgentInstance] = []
    for arch in ARCHETYPES:
        for i, name in enumerate(arch.names):
            k = rng.randint(*arch.users)
            agents.append(
                AgentInstance(
                    client_id=f"{arch.key}-{i + 1}-{seed}.apps.test",
                    name=name,
                    archetype=arch,
                    users=rng.sample(emails, k),
                    rate=arch.calls_per_user * rng.uniform(0.7, 1.3),
                )
            )

    f = _EventFactory(rng, nrng)
    first_day = start.date()
    all_days = [first_day + timedelta(days=d) for d in range(days)]
    scoring_days = all_days[baseline_days:]

    active = [a for a in agents if a.archetype.methods]
    chosen: list[Incident] = []
    pool = rng.sample(active, min(incidents, len(active)))
    for idx, agent in enumerate(pool):
        kind = ATTACK_KINDS[idx % len(ATTACK_KINDS)]
        span = 3 if kind == "slow_creep" else 1
        d0 = rng.randrange(0, len(scoring_days) - span + 1)
        chosen.append(Incident(agent.client_id, kind, scoring_days[d0 : d0 + span]))

    # Benign, unlabelled surprises: a month-end batch and a busy all-hands week.
    spikes: list[tuple[str, date]] = []
    for agent in rng.sample(active, 3):
        spikes.append((agent.client_id, rng.choice(scoring_days)))

    events: list[ActivityRecord] = []
    incident_by = {(i.client_id, d): (i.kind, i.days.index(d)) for i in chosen for d in i.days}
    spike_set = set(spikes)
    for agent in agents:
        for day in all_days:
            volume = 1.8 if (agent.client_id, day) in spike_set else 1.0
            events.extend(_normal_day(f, agent, day, volume))
            hit = incident_by.get((agent.client_id, day))
            if hit:
                events.extend(_attack(f, agent, hit[0], day, hit[1]))

    return Scenario(
        start=start, days=days, users=users, agents=agents, events=events, incidents=chosen, benign_spikes=spikes
    )


def load_into(scenario: Scenario, connector: SimulatedConnector) -> None:
    connector.reset()
    for email, name, dept in scenario.users:
        connector.add_user(email, name, dept)
    for a in scenario.agents:
        for u in a.users:
            connector.add_grant(a.client_id, a.name, u, list(a.archetype.granted))
    connector.add_activity(scenario.events)
