"""The typed commands refuse a service of another version; the hook and `zikaron-mcp` do not.

`design/distribution.md` §3 is normative. `health()` reports the package version the service read
at its startup; `init` and every `knowledge` verb compare it with their own before sending anything
else, and refuse on any difference with both versions, the service's pid and both remedies. A
service that sends no version is older than the rule and gets the one remedy that then applies.

The service is stood in for at the transport: `connect_start_if_absent` answers with the
`health()` a test chooses, and every request sent is recorded, so "nothing else was sent" is an
observation rather than an inference.
"""

import asyncio
import time
from dataclasses import dataclass, field
from pathlib import Path

import pytest

from tests.knowledge_fixtures import config_for
from tests.service_fixtures import open_context
from tests.test_hook_connect import _FakeService
from zikaron.core.store.embedder import FakeEmbedder
from zikaron.core.store.store import Store
from zikaron.core.version import package_version
from zikaron.hook.connect import connect_once
from zikaron.knowledge import client
from zikaron.knowledge import main as knowledge_cli
from zikaron.mcp import connection as mcp_connection
from zikaron.mcp.connection import ServiceConnection
from zikaron.project import initialize
from zikaron.service.dispatch import health
from zikaron.service.lifecycle import HealthCheck

_OTHER: str = "0.0.0-another-build"
_PID: int = 4242


@dataclass
class _Service:
    """What the stand-in service answers at the handshake, and every request it was sent."""

    version: str | None
    sent: list[str] = field(default_factory=list)
    connects: int = 0


class _Socket:
    def settimeout(self, _timeout: float) -> None:
        return None

    def close(self) -> None:
        return None


@pytest.fixture
def service(monkeypatch: pytest.MonkeyPatch) -> _Service:
    standing = _Service(version=_OTHER)

    def _connect(_sock_path: Path, *, store_db_path: Path, **_options: object) -> object:
        standing.connects += 1
        answer = HealthCheck(
            ready=True,
            store_path=str(store_db_path),
            store_id="",
            version=standing.version,
            pid=_PID,
        )
        return _Socket(), answer

    def _send(_sock: object, method: str, _params: object, **_options: object) -> None:
        standing.sent.append(method)

    def _read(_sock: object) -> dict[str, object]:
        return {"jsonrpc": "2.0", "id": 1, "result": {"knowledge_bases": [], "orphans": []}}

    monkeypatch.setattr(mcp_connection, "connect_start_if_absent", _connect)
    monkeypatch.setattr(mcp_connection, "_send_request", _send)
    monkeypatch.setattr(mcp_connection, "_read_response", _read)
    return standing


@pytest.fixture
def project(tmp_path: Path) -> Path:
    config = config_for(tmp_path)
    embedder = FakeEmbedder(config.get_str("embed_model"), config.get_int("embed_dim"))

    async def _create() -> None:
        async with await Store.create(tmp_path / ".zikaron", config, embedder):
            pass

    asyncio.run(_create())
    return tmp_path


class TestATypedCommandRefuses:
    def test_a_knowledge_verb_names_both_versions_both_remedies_and_sends_nothing(
        self, project: Path, service: _Service, capsys: pytest.CaptureFixture[str]
    ) -> None:
        assert knowledge_cli.main(["--project", str(project), "list"]) == 1
        printed = capsys.readouterr().err
        assert package_version() in printed
        assert _OTHER in printed
        assert f"pid {_PID}" in printed
        assert f"kill {_PID}" in printed, "the remedy for a newer command"
        assert ".mcp.json" in printed, "the remedy for a newer service"
        assert service.sent == []

    def test_init_refuses_the_same_way(
        self, project: Path, service: _Service, capsys: pytest.CaptureFixture[str]
    ) -> None:
        assert initialize.main(["--project", str(project)]) == 1
        printed = capsys.readouterr().err
        assert _OTHER in printed
        assert package_version() in printed
        assert service.sent == []

    def test_a_service_naming_no_version_is_told_to_stop_and_nothing_else(
        self, project: Path, service: _Service, capsys: pytest.CaptureFixture[str]
    ) -> None:
        service.version = None
        assert knowledge_cli.main(["--project", str(project), "list"]) == 1
        printed = capsys.readouterr().err
        assert "names no version" in printed
        assert f"kill {_PID}" in printed
        assert ".mcp.json" not in printed, "only one remedy applies to a service older than this"
        assert service.sent == []

    def test_a_service_of_this_version_is_talked_to(
        self, project: Path, service: _Service, capsys: pytest.CaptureFixture[str]
    ) -> None:
        service.version = package_version()
        assert knowledge_cli.main(["--project", str(project), "list"]) == 0
        assert service.sent == ["knowledge_list"]
        assert "refused" not in capsys.readouterr().err

    def test_a_nameless_force_unlock_starts_no_service(
        self, project: Path, service: _Service, capsys: pytest.CaptureFixture[str]
    ) -> None:
        assert knowledge_cli.main(["--project", str(project), "refresh", "--force-unlock"]) == 1
        assert "name one" in capsys.readouterr().err
        assert service.connects == 0


class TestAReconnectMidCommand:
    async def test_a_service_replaced_during_the_command_is_refused_after_the_reconnect(
        self, project: Path, service: _Service
    ) -> None:
        """Compared through the same accessor after the request that reconnected, which for a
        `refresh --wait` is one read-only `status` poll."""
        service.version = package_version()
        async with client.connected(project) as knowledge:
            await knowledge.call("knowledge_status", {})
            service.version = _OTHER
            knowledge._connection._sock = None
            with pytest.raises(client.ServiceVersionError) as refused:
                await knowledge.call("knowledge_status", {})
        assert refused.value.theirs == _OTHER
        assert service.connects == 2

    async def test_a_restarted_service_of_this_version_is_talked_to_after_the_reconnect(
        self, project: Path, service: _Service
    ) -> None:
        service.version = package_version()
        async with client.connected(project) as knowledge:
            await knowledge.call("knowledge_status", {})
            knowledge._connection._sock = None
            await knowledge.call("knowledge_status", {})
            await knowledge.call("knowledge_status", {})
        assert service.sent == ["knowledge_status"] * 3
        assert service.connects == 2


class TestTheOtherClientsDoNotRefuse:
    async def test_an_mcp_request_proceeds_against_another_version(
        self, project: Path, service: _Service
    ) -> None:
        connection = ServiceConnection(project)
        try:
            response = await connection.request(
                "knowledge_list", {}, envelope=connection.envelope(kind="mcp")
            )
        finally:
            connection.close()
        assert "result" in response
        assert service.sent == ["knowledge_list"]

    @pytest.mark.usefixtures("generous_hook_deadlines")
    def test_the_hook_connects_to_another_version(self, socket_dir: Path, tmp_path: Path) -> None:
        sock_path = socket_dir / "version.sock"
        store_db_path = tmp_path / "memory.db"
        fake = _FakeService(
            sock_path,
            store_path=str(store_db_path),
            store_id="abc",
            also={"version": _OTHER, "pid": _PID},
        )
        try:
            connected = connect_once(
                sock_path,
                store_db_path=store_db_path,
                store_id="abc",
                server_command=["false"],
                poll_deadline=time.monotonic() + 5,
            )
            connected.sock.close()
        finally:
            fake.close()


class TestTheServiceReportsTheVersionItStartedWith:
    async def test_an_in_place_upgrade_does_not_change_what_health_reports(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        async with open_context(tmp_path) as ctx:
            started_with = health(ctx).version
            upgraded = tmp_path / "upgraded"
            metadata = upgraded / "zikaron-9.9.9.dist-info"
            metadata.mkdir(parents=True)
            (metadata / "METADATA").write_text(
                "Metadata-Version: 2.1\nName: zikaron\nVersion: 9.9.9\n", encoding="utf-8"
            )
            monkeypatch.syspath_prepend(str(upgraded))
            assert package_version() == "9.9.9", "the lookup now finds the upgrade"
            assert health(ctx).version == started_with
        assert started_with != "9.9.9"
