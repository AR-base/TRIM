from trim import scopes as sc
from trim.scopes import GOOGLE_PREFIX as G

MAIL_FULL = "https://mail.google.com/"


def test_catalog_is_consistent():
    for s in sc.BY_SHORT.values():
        for inc in s.includes:
            assert inc in sc.BY_SHORT, f"{s.short} includes unknown {inc}"
            assert s.short not in sc.closure([inc]), f"cycle between {s.short} and {inc}"
        assert s.risk in (1, 2, 3)
        assert s.phrase and not s.phrase.endswith(".")


def test_broad_scope_includes_narrow_ones():
    assert {"gmail.modify", "gmail.readonly", "gmail.compose", "gmail.send"} <= sc.closure(["mail.full"])
    assert "drive.readonly" in sc.closure(["drive"])
    assert "drive" not in sc.closure(["drive.readonly"])


def test_minimal_cover_narrows_to_what_was_used():
    r = sc.minimal_cover(
        ["openid", MAIL_FULL, G + "calendar"], ["gmail.users.messages.list", "gmail.users.messages.send"]
    )
    assert set(r.keep) == {"openid", G + "gmail.readonly", G + "gmail.send"}
    assert set(r.remove) == {MAIL_FULL, G + "calendar"}
    assert set(r.narrowed[MAIL_FULL]) == {G + "gmail.readonly", G + "gmail.send"}
    assert r.keep[G + "gmail.send"] == ["gmail.users.messages.send"]


def test_minimal_cover_never_escalates_beyond_grant():
    # drive.files.update needs full drive; only drive.readonly was granted, so nothing broader appears.
    r = sc.minimal_cover([G + "drive.readonly"], ["drive.files.get", "drive.files.update"])
    assert set(r.keep) == {G + "drive.readonly"}
    assert G + "drive" not in r.keep
    assert r.uncovered == ["drive.files.update"]


def test_minimal_cover_keeps_unknown_and_identity_scopes():
    r = sc.minimal_cover(["openid", "https://example.com/custom", G + "drive"], [])
    assert "openid" in r.keep and "https://example.com/custom" in r.keep
    assert r.remove == [G + "drive"]


def test_unexplained_method_keeps_broadest_scope_of_family():
    r = sc.minimal_cover([MAIL_FULL], ["gmail.users.messages.list", "gmail.users.someNewMethod"])
    assert list(r.keep) == [MAIL_FULL]
    assert r.uncovered == ["gmail.users.someNewMethod"]
    assert r.remove == []


def test_redundant_picks_are_merged_into_broader_scope():
    r = sc.minimal_cover([MAIL_FULL], ["gmail.users.messages.list", "gmail.users.messages.trash"])
    assert set(r.keep) == {G + "gmail.modify"}
    assert set(r.keep[G + "gmail.modify"]) == {"gmail.users.messages.list", "gmail.users.messages.trash"}


def test_reach_sentence_describes_only_broadest_scopes():
    text = sc.reach_sentence(["openid", MAIL_FULL, G + "gmail.readonly"], 3)
    assert text == "Can read, send and permanently delete all email, for 3 people."
    assert sc.reach_sentence(["openid"]) == "Can only confirm who the user is."
    assert sc.reach_sentence([G + "calendar.readonly"], 1).endswith("for 1 person.")
    many = sc.reach_sentence([G + "drive", G + "calendar.readonly", "https://x.example/y"])
    assert many.startswith("Can read, edit, share and delete every Drive file, ") and "use https://x.example/y" in many


def test_capabilities_follow_inclusion():
    assert sc.grants_capability([MAIL_FULL], "send_email")
    assert sc.grants_capability([MAIL_FULL], "delete_email")
    assert not sc.grants_capability([G + "gmail.readonly"], "send_email")
    assert sc.grants_capability([G + "admin.directory.user"], "read_directory")


def test_write_methods_and_lookup():
    assert sc.is_write_method("gmail.users.messages.send")
    assert not sc.is_write_method("drive.files.get")
    assert sc.short_name(G + "drive") == "drive"
    assert sc.short_name("https://other/x") == "https://other/x"
    assert sc.risk("https://unknown") == 2
    assert sc.info("drive").scope == G + "drive"
