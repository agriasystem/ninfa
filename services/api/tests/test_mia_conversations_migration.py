"""Migration 0017_mia_conversations: additive, one head, numbered once, reversible.

The current global head lives here (`test_01`); the older migration files name it as a constant.
An earlier, unmerged branch of Mia created the same table under the revision number 0014; the chain
here is the real one (it sits on 0016), and `test_02` pins that no second migration claims the
number, so that clash can never come back."""

import pathlib
import uuid
from collections.abc import Iterator

import pytest
from alembic import command
from alembic.script import ScriptDirectory
from sqlalchemy import Engine, inspect, text

from tests.support import alembic_config

MIA = "0017_mia_conversations"
HEAD = "0018_cost_record_identity"  # the real global head now; Mia's own migration sits below
PREVIOUS_HEAD = "0016_remembered_scope"
TABLE = "mia_conversations"


@pytest.fixture
def at_head(db_engine: Engine, test_database_url: str) -> Iterator[None]:
    command.upgrade(alembic_config(test_database_url), "head")
    yield
    command.upgrade(alembic_config(test_database_url), "head")


def _revision(engine: Engine) -> str:
    with engine.connect() as connection:
        return str(connection.execute(text("SELECT version_num FROM alembic_version")).scalar_one())


def _tables(engine: Engine) -> set[str]:
    return set(inspect(engine).get_table_names())


def _seed(engine: Engine) -> tuple[uuid.UUID, uuid.UUID, uuid.UUID]:
    """A workspace, a property and a member user: their ids (the test purges the workspace)."""
    workspace, prop, user = (uuid.uuid4() for _ in range(3))
    suffix = uuid.uuid4().hex[:10]
    with engine.begin() as connection:
        connection.execute(
            text("INSERT INTO workspaces (id, name, slug) VALUES (:id, 'Mia', :slug)"),
            {"id": workspace, "slug": f"mia-{suffix}"},
        )
        connection.execute(
            text(
                "INSERT INTO properties (id, workspace_id, name, slug, timezone, currency)"
                " VALUES (:id, :w, 'Mia', :slug, 'Europe/Rome', 'EUR')"
            ),
            {"id": prop, "w": workspace, "slug": f"mia-{suffix}"},
        )
        connection.execute(
            text("INSERT INTO users (id, email) VALUES (:id, :email)"),
            {"id": user, "email": f"mia-{suffix}@example.com"},
        )
        connection.execute(
            text(
                "INSERT INTO workspace_memberships (id, workspace_id, user_id, role)"
                " VALUES (gen_random_uuid(), :w, :u, 'MEMBER')"
            ),
            {"w": workspace, "u": user},
        )
    return workspace, prop, user


def _purge(engine: Engine, workspace: uuid.UUID, user: uuid.UUID) -> None:
    with engine.begin() as connection:
        connection.execute(
            text("DELETE FROM mia_conversations WHERE workspace_id = :w"), {"w": workspace}
        )
        connection.execute(
            text("DELETE FROM workspace_memberships WHERE workspace_id = :w"), {"w": workspace}
        )
        connection.execute(text("DELETE FROM properties WHERE workspace_id = :w"), {"w": workspace})
        connection.execute(text("DELETE FROM workspaces WHERE id = :w"), {"w": workspace})
        connection.execute(text("DELETE FROM users WHERE id = :u"), {"u": user})


def _insert(
    engine: Engine, workspace: uuid.UUID, prop: uuid.UUID, user: uuid.UUID, messages: str = "[]"
) -> None:
    with engine.begin() as connection:
        connection.execute(
            text(
                "INSERT INTO mia_conversations"
                " (workspace_id, property_id, user_id, title, messages, last_message_at)"
                " VALUES (:w, :p, :u, 'titolo', CAST(:m AS jsonb), now())"
            ),
            {"w": workspace, "p": prop, "u": user, "m": messages},
        )


def test_01_there_is_exactly_one_head_and_it_sits_on_0016(test_database_url: str) -> None:
    scripts = ScriptDirectory.from_config(alembic_config(test_database_url))

    assert scripts.get_heads() == [HEAD]
    assert scripts.get_revision(MIA).down_revision == PREVIOUS_HEAD


def test_02_there_is_one_migration_numbered_0017_and_only_one_creates_the_table(
    test_database_url: str,
) -> None:
    scripts = ScriptDirectory.from_config(alembic_config(test_database_url))

    numbered = [rev.revision for rev in scripts.walk_revisions() if rev.revision.startswith("0017")]
    assert numbered == [MIA]
    versions = pathlib.Path(__file__).resolve().parents[1] / "alembic" / "versions"
    creators = [
        path.name
        for path in versions.glob("*.py")
        if f'"{TABLE}",' in path.read_text(encoding="utf-8")
        and "op.create_table(" in path.read_text(encoding="utf-8")
    ]
    assert creators == ["0017_mia_conversations.py"]


def test_03_the_table_comes_and_goes_with_it(
    at_head: None, db_engine: Engine, test_database_url: str
) -> None:
    config = alembic_config(test_database_url)
    assert TABLE in _tables(db_engine) and _revision(db_engine) == HEAD

    command.downgrade(config, PREVIOUS_HEAD)
    assert TABLE not in _tables(db_engine)
    assert _revision(db_engine) == PREVIOUS_HEAD

    command.upgrade(config, "head")
    assert TABLE in _tables(db_engine) and _revision(db_engine) == HEAD


def test_04_it_is_additive_nothing_is_inserted_and_nothing_else_changes(
    at_head: None, db_engine: Engine
) -> None:
    with db_engine.connect() as connection:
        assert connection.execute(text(f"SELECT count(*) FROM {TABLE}")).scalar_one() == 0
    columns = {c["name"]: c for c in inspect(db_engine).get_columns(TABLE)}
    assert set(columns) == {
        "id",
        "workspace_id",
        "property_id",
        "user_id",
        "title",
        "digest",
        "messages",
        "last_message_at",
        "created_at",
        "updated_at",
    }
    for name in ("workspace_id", "property_id", "user_id", "title", "digest", "messages"):
        assert columns[name]["nullable"] is False, name


def test_05_the_owner_and_the_property_are_bound_by_composite_foreign_keys(
    at_head: None, db_engine: Engine
) -> None:
    foreign = {
        tuple(fk["constrained_columns"]): (fk["referred_table"], fk["options"].get("ondelete"))
        for fk in inspect(db_engine).get_foreign_keys(TABLE)
    }

    assert foreign == {
        ("workspace_id", "property_id"): ("properties", "RESTRICT"),
        ("workspace_id", "user_id"): ("workspace_memberships", "CASCADE"),
    }


def test_06_the_messages_are_a_bounded_array(at_head: None, db_engine: Engine) -> None:
    workspace, prop, user = _seed(db_engine)
    try:
        _insert(db_engine, workspace, prop, user, "[" + ",".join(["{}"] * 200) + "]")
        with pytest.raises(Exception, match="messages_bounded"):
            _insert(db_engine, workspace, prop, user, "[" + ",".join(["{}"] * 201) + "]")
        with pytest.raises(Exception, match="messages_is_array"):
            _insert(db_engine, workspace, prop, user, '{"not": "an array"}')
    finally:
        _purge(db_engine, workspace, user)


def test_07_a_user_who_is_not_a_member_cannot_own_a_conversation(
    at_head: None, db_engine: Engine
) -> None:
    workspace, prop, user = _seed(db_engine)
    stranger = uuid.uuid4()
    try:
        with db_engine.begin() as connection:
            connection.execute(
                text("INSERT INTO users (id, email) VALUES (:id, :e)"),
                {"id": stranger, "e": f"{stranger.hex[:8]}@example.com"},
            )
        with pytest.raises(
            Exception, match="fk_mia_conversations_workspace_id_workspace_memberships"
        ):
            _insert(db_engine, workspace, prop, stranger)
    finally:
        _purge(db_engine, workspace, user)
        with db_engine.begin() as connection:
            connection.execute(text("DELETE FROM users WHERE id = :u"), {"u": stranger})


def test_08_revoking_a_membership_deletes_its_conversations_a_property_cannot_vanish(
    at_head: None, db_engine: Engine
) -> None:
    workspace, prop, user = _seed(db_engine)
    try:
        _insert(db_engine, workspace, prop, user)
        with (
            pytest.raises(Exception, match="fk_mia_conversations_workspace_id_properties"),
            db_engine.begin() as connection,
        ):
            connection.execute(text("DELETE FROM properties WHERE id = :p"), {"p": prop})
        with db_engine.begin() as connection:
            connection.execute(
                text("DELETE FROM workspace_memberships WHERE workspace_id = :w AND user_id = :u"),
                {"w": workspace, "u": user},
            )
        with db_engine.connect() as connection:
            remaining = connection.execute(
                text(f"SELECT count(*) FROM {TABLE} WHERE workspace_id = :w"), {"w": workspace}
            ).scalar_one()
        assert remaining == 0
    finally:
        _purge(db_engine, workspace, user)


def test_09_the_owner_lookup_has_its_index(at_head: None, db_engine: Engine) -> None:
    indexes = {i["name"]: i["column_names"] for i in inspect(db_engine).get_indexes(TABLE)}

    assert indexes["ix_mia_conversations_owner_recent"] == [
        "workspace_id",
        "property_id",
        "user_id",
        "last_message_at",
    ]
