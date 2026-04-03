"""
Tests for utils/publish-on-aleph.py

Covers:
- raise_no_cid helper
- upload_site: normal operation, empty iterator, error cleanup
- publish_site: correct path construction and delegation
- main: output and asyncio integration
"""

import asyncio
import importlib.util
import logging
import sys
from pathlib import Path
from typing import AsyncIterator
from unittest.mock import AsyncMock, MagicMock, call, patch

import pytest

# ---------------------------------------------------------------------------
# Load the module under test from its on-disk path so we don't need to
# restructure the package layout.
# ---------------------------------------------------------------------------

_MODULE_PATH = Path(__file__).parent.parent / "publish-on-aleph.py"
_SPEC = importlib.util.spec_from_file_location("publish_on_aleph", _MODULE_PATH)
publish_on_aleph = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(publish_on_aleph)

raise_no_cid = publish_on_aleph.raise_no_cid
upload_site = publish_on_aleph.upload_site
publish_site = publish_on_aleph.publish_site
main = publish_on_aleph.main
Multiaddr = publish_on_aleph.Multiaddr
CID = publish_on_aleph.CID


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

async def _async_iter(items):
    """Yield items from a plain list as an async iterator."""
    for item in items:
        yield item


def _make_client(added_files=None, raise_on_add=None):
    """Return a mock aioipfs.AsyncIPFS client."""
    client = MagicMock()
    client.close = AsyncMock()

    if raise_on_add is not None:
        async def _raise(*args, **kwargs):
            raise raise_on_add
            # unreachable – satisfies the async-generator protocol
            yield  # noqa: unreachable

        client.add = _raise
    else:
        files = added_files or []
        client.add = MagicMock(return_value=_async_iter(files))

    return client


# ---------------------------------------------------------------------------
# raise_no_cid
# ---------------------------------------------------------------------------

class TestRaiseNoCid:
    def test_always_raises_value_error(self):
        with pytest.raises(ValueError, match="Could not obtain a CID"):
            raise_no_cid()

    def test_raises_value_error_type(self):
        with pytest.raises(ValueError):
            raise_no_cid()


# ---------------------------------------------------------------------------
# upload_site
# ---------------------------------------------------------------------------

class TestUploadSite:
    """Tests for the upload_site coroutine."""

    @pytest.mark.asyncio
    async def test_returns_last_cid(self):
        """The CID of the last uploaded file (the directory) is returned."""
        files_added = [
            {"Name": "index.html", "Hash": "QmAAA"},
            {"Name": "style.css", "Hash": "QmBBB"},
            {"Name": "site", "Hash": "QmCCC"},
        ]
        mock_client = _make_client(added_files=files_added)

        with patch.object(publish_on_aleph.aioipfs, "AsyncIPFS", return_value=mock_client):
            result = await upload_site(
                files=[Path("/tmp/site")],
                multiaddr=Multiaddr("/dns6/ipfs-2.aleph.im/tcp/443/https"),
            )

        assert result == "QmCCC"

    @pytest.mark.asyncio
    async def test_single_file_returns_its_cid(self):
        files_added = [{"Name": "site", "Hash": "QmSINGLE"}]
        mock_client = _make_client(added_files=files_added)

        with patch.object(publish_on_aleph.aioipfs, "AsyncIPFS", return_value=mock_client):
            result = await upload_site(
                files=[Path("/tmp/site")],
                multiaddr=Multiaddr("/dns6/ipfs-2.aleph.im/tcp/443/https"),
            )

        assert result == "QmSINGLE"

    @pytest.mark.asyncio
    async def test_raises_when_no_files_yielded(self):
        """If the IPFS client yields nothing, a ValueError is raised."""
        mock_client = _make_client(added_files=[])

        with patch.object(publish_on_aleph.aioipfs, "AsyncIPFS", return_value=mock_client):
            with pytest.raises(ValueError, match="Could not obtain a CID"):
                await upload_site(
                    files=[Path("/tmp/empty")],
                    multiaddr=Multiaddr("/dns6/ipfs-2.aleph.im/tcp/443/https"),
                )

    @pytest.mark.asyncio
    async def test_client_closed_after_success(self):
        """client.close() must be called even when upload succeeds."""
        files_added = [{"Name": "site", "Hash": "QmOK"}]
        mock_client = _make_client(added_files=files_added)

        with patch.object(publish_on_aleph.aioipfs, "AsyncIPFS", return_value=mock_client):
            await upload_site(
                files=[Path("/tmp/site")],
                multiaddr=Multiaddr("/dns6/ipfs-2.aleph.im/tcp/443/https"),
            )

        mock_client.close.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_client_closed_after_exception(self):
        """client.close() must be called even when the add() call raises."""
        mock_client = _make_client(raise_on_add=RuntimeError("IPFS error"))

        with patch.object(publish_on_aleph.aioipfs, "AsyncIPFS", return_value=mock_client):
            with pytest.raises(RuntimeError, match="IPFS error"):
                await upload_site(
                    files=[Path("/tmp/site")],
                    multiaddr=Multiaddr("/dns6/ipfs-2.aleph.im/tcp/443/https"),
                )

        mock_client.close.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_client_constructed_with_correct_multiaddr(self):
        """AsyncIPFS must be instantiated with the supplied multiaddr."""
        files_added = [{"Name": "site", "Hash": "QmOK"}]
        mock_client = _make_client(added_files=files_added)
        multiaddr = Multiaddr("/dns6/ipfs-2.aleph.im/tcp/443/https")

        with patch.object(
            publish_on_aleph.aioipfs, "AsyncIPFS", return_value=mock_client
        ) as mock_ipfs_cls:
            await upload_site(files=[Path("/tmp/site")], multiaddr=multiaddr)

        mock_ipfs_cls.assert_called_once_with(maddr=multiaddr)

    @pytest.mark.asyncio
    async def test_add_called_with_recursive_true(self):
        """client.add() must be called with recursive=True."""
        files_added = [{"Name": "site", "Hash": "QmOK"}]
        mock_client = _make_client(added_files=files_added)
        path = Path("/tmp/site")

        with patch.object(publish_on_aleph.aioipfs, "AsyncIPFS", return_value=mock_client):
            await upload_site(files=[path], multiaddr=Multiaddr("/addr"))

        mock_client.add.assert_called_once_with(path, recursive=True)

    @pytest.mark.asyncio
    async def test_add_called_with_multiple_files(self):
        """All supplied paths are forwarded to client.add()."""
        files_added = [{"Name": "site", "Hash": "QmMULTI"}]
        mock_client = _make_client(added_files=files_added)
        paths = [Path("/tmp/a"), Path("/tmp/b")]

        with patch.object(publish_on_aleph.aioipfs, "AsyncIPFS", return_value=mock_client):
            await upload_site(files=paths, multiaddr=Multiaddr("/addr"))

        mock_client.add.assert_called_once_with(*paths, recursive=True)

    @pytest.mark.asyncio
    async def test_debug_logging_per_file(self, caplog):
        """A debug log message is emitted for every uploaded file."""
        files_added = [
            {"Name": "index.html", "Hash": "QmAAA"},
            {"Name": "site", "Hash": "QmBBB"},
        ]
        mock_client = _make_client(added_files=files_added)

        with patch.object(publish_on_aleph.aioipfs, "AsyncIPFS", return_value=mock_client):
            with caplog.at_level(logging.DEBUG):
                await upload_site(
                    files=[Path("/tmp/site")],
                    multiaddr=Multiaddr("/addr"),
                )

        assert any("index.html" in msg for msg in caplog.messages)
        assert any("QmAAA" in msg for msg in caplog.messages)
        assert any("site" in msg for msg in caplog.messages)
        assert any("QmBBB" in msg for msg in caplog.messages)


# ---------------------------------------------------------------------------
# publish_site
# ---------------------------------------------------------------------------

class TestPublishSite:
    """Tests for the publish_site coroutine."""

    @pytest.mark.asyncio
    async def test_returns_cid_from_upload_site(self):
        expected_cid = CID("QmPUBLISHED")

        with patch.object(
            publish_on_aleph, "upload_site", new=AsyncMock(return_value=expected_cid)
        ):
            result = await publish_site(
                Multiaddr("/dns6/ipfs-2.aleph.im/tcp/443/https")
            )

        assert result == expected_cid

    @pytest.mark.asyncio
    async def test_passes_site_directory_path(self):
        """The 'site' directory at the project root must be passed to upload_site."""
        expected_path = _MODULE_PATH.parent.parent / "site"

        with patch.object(
            publish_on_aleph, "upload_site", new=AsyncMock(return_value=CID("QmX"))
        ) as mock_upload:
            await publish_site(Multiaddr("/addr"))

        _called_files = mock_upload.call_args.kwargs.get(
            "files", mock_upload.call_args.args[0] if mock_upload.call_args.args else None
        )
        assert _called_files == [expected_path]

    @pytest.mark.asyncio
    async def test_passes_multiaddr_to_upload_site(self):
        multiaddr = Multiaddr("/dns6/ipfs-2.aleph.im/tcp/443/https")

        with patch.object(
            publish_on_aleph, "upload_site", new=AsyncMock(return_value=CID("QmX"))
        ) as mock_upload:
            await publish_site(multiaddr)

        _called_multiaddr = mock_upload.call_args.kwargs.get(
            "multiaddr",
            mock_upload.call_args.args[1] if len(mock_upload.call_args.args) > 1 else None,
        )
        assert _called_multiaddr == multiaddr

    @pytest.mark.asyncio
    async def test_propagates_exception_from_upload_site(self):
        with patch.object(
            publish_on_aleph,
            "upload_site",
            new=AsyncMock(side_effect=ValueError("Could not obtain a CID")),
        ):
            with pytest.raises(ValueError, match="Could not obtain a CID"):
                await publish_site(Multiaddr("/addr"))


# ---------------------------------------------------------------------------
# main
# ---------------------------------------------------------------------------

class TestMain:
    def test_prints_cid(self, capsys):
        expected_cid = "QmMAIN"

        with patch.object(
            publish_on_aleph,
            "publish_site",
            new=AsyncMock(return_value=expected_cid),
        ):
            main()

        captured = capsys.readouterr()
        assert expected_cid in captured.out

    def test_uses_default_aleph_multiaddr(self):
        """main() must publish to the hard-coded aleph.im IPFS node."""
        with patch.object(
            publish_on_aleph,
            "publish_site",
            new=AsyncMock(return_value="QmX"),
        ) as mock_publish:
            main()

        called_multiaddr = mock_publish.call_args.args[0]
        assert "ipfs-2.aleph.im" in called_multiaddr
        assert "443" in called_multiaddr

    def test_runs_via_asyncio(self):
        """main() must drive the coroutine through asyncio.run()."""
        with patch.object(
            publish_on_aleph, "publish_site", new=AsyncMock(return_value="QmX")
        ):
            with patch("asyncio.run", wraps=asyncio.run) as mock_run:
                main()

        mock_run.assert_called_once()
