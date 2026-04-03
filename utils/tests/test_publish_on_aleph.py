"""Tests for utils/publish-on-aleph.py"""

import asyncio
import sys
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

# Ensure utils directory is importable
sys.path.insert(0, str(Path(__file__).parent.parent))

import importlib.util

spec = importlib.util.spec_from_file_location(
    "publish_on_aleph",
    Path(__file__).parent.parent / "publish-on-aleph.py",
)
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)

upload_site = module.upload_site
publish_site = module.publish_site
main = module.main
Multiaddr = module.Multiaddr
CID = module.CID

FAKE_MULTIADDR = Multiaddr("/dns4/localhost/tcp/5001/http")
FAKE_CID = "QmFakeCID1234567890abcdef"


def _make_async_iter(items):
    """Return an async iterator yielding the given items."""

    async def _gen():
        for item in items:
            yield item

    return _gen()


# ---------------------------------------------------------------------------
# upload_site
# ---------------------------------------------------------------------------


class TestUploadSite:
    @pytest.mark.asyncio
    async def test_successful_upload_returns_last_cid(self, tmp_path):
        """upload_site returns the last CID emitted by the IPFS client."""
        added_files = [
            {"Name": "file1.html", "Hash": "QmFirst"},
            {"Name": "site", "Hash": FAKE_CID},
        ]

        mock_client = MagicMock()
        mock_client.add.return_value = _make_async_iter(added_files)
        mock_client.close = AsyncMock()

        with patch("aioipfs.AsyncIPFS", return_value=mock_client):
            result = await upload_site(files=[tmp_path], multiaddr=FAKE_MULTIADDR)

        assert result == FAKE_CID
        mock_client.close.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_empty_files_list_raises_value_error(self):
        """upload_site raises ValueError when called with an empty file list."""
        with pytest.raises(ValueError, match="No files provided"):
            await upload_site(files=[], multiaddr=FAKE_MULTIADDR)

    @pytest.mark.asyncio
    async def test_nonexistent_path_raises_file_not_found(self, tmp_path):
        """upload_site raises FileNotFoundError for paths that do not exist."""
        missing = tmp_path / "does_not_exist"
        with pytest.raises(FileNotFoundError, match="does_not_exist"):
            await upload_site(files=[missing], multiaddr=FAKE_MULTIADDR)

    @pytest.mark.asyncio
    async def test_no_files_added_raises_value_error(self, tmp_path):
        """upload_site raises ValueError when the IPFS client yields nothing."""
        mock_client = MagicMock()
        mock_client.add.return_value = _make_async_iter([])
        mock_client.close = AsyncMock()

        with patch("aioipfs.AsyncIPFS", return_value=mock_client):
            with pytest.raises(ValueError, match="Could not obtain a CID"):
                await upload_site(files=[tmp_path], multiaddr=FAKE_MULTIADDR)

        mock_client.close.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_client_closed_on_exception(self, tmp_path):
        """upload_site closes the IPFS client even when an exception is raised."""
        mock_client = MagicMock()
        mock_client.add.side_effect = RuntimeError("IPFS connection refused")
        mock_client.close = AsyncMock()

        with patch("aioipfs.AsyncIPFS", return_value=mock_client):
            with pytest.raises(RuntimeError, match="IPFS connection refused"):
                await upload_site(files=[tmp_path], multiaddr=FAKE_MULTIADDR)

        mock_client.close.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_entries_without_hash_are_skipped(self, tmp_path):
        """Entries missing the 'Hash' key do not overwrite a previously seen CID."""
        added_files = [
            {"Name": "site", "Hash": FAKE_CID},
            {"Name": "partial"},          # no 'Hash' key
            {"Name": "empty_hash", "Hash": ""},  # falsy hash
        ]

        mock_client = MagicMock()
        mock_client.add.return_value = _make_async_iter(added_files)
        mock_client.close = AsyncMock()

        with patch("aioipfs.AsyncIPFS", return_value=mock_client):
            result = await upload_site(files=[tmp_path], multiaddr=FAKE_MULTIADDR)

        assert result == FAKE_CID

    @pytest.mark.asyncio
    async def test_ipfs_client_constructed_with_correct_multiaddr(self, tmp_path):
        """upload_site passes the multiaddr to the AsyncIPFS constructor."""
        added_files = [{"Name": "site", "Hash": FAKE_CID}]
        mock_client = MagicMock()
        mock_client.add.return_value = _make_async_iter(added_files)
        mock_client.close = AsyncMock()

        with patch("aioipfs.AsyncIPFS", return_value=mock_client) as mock_cls:
            await upload_site(files=[tmp_path], multiaddr=FAKE_MULTIADDR)

        mock_cls.assert_called_once_with(maddr=FAKE_MULTIADDR)

    @pytest.mark.asyncio
    async def test_multiple_files_uploaded(self, tmp_path):
        """upload_site accepts multiple file paths."""
        file_a = tmp_path / "a.html"
        file_b = tmp_path / "b.html"
        file_a.write_text("a")
        file_b.write_text("b")

        added_files = [
            {"Name": "a.html", "Hash": "QmA"},
            {"Name": "b.html", "Hash": "QmB"},
        ]

        mock_client = MagicMock()
        mock_client.add.return_value = _make_async_iter(added_files)
        mock_client.close = AsyncMock()

        with patch("aioipfs.AsyncIPFS", return_value=mock_client):
            result = await upload_site(files=[file_a, file_b], multiaddr=FAKE_MULTIADDR)

        assert result == "QmB"


# ---------------------------------------------------------------------------
# publish_site
# ---------------------------------------------------------------------------


class TestPublishSite:
    @pytest.mark.asyncio
    async def test_publish_site_calls_upload_with_site_path(self):
        """publish_site derives the 'site' directory relative to the script."""
        expected_path = Path(module.__file__).parent.parent / "site"

        with patch.object(module, "upload_site", new=AsyncMock(return_value=FAKE_CID)) as mock_upload:
            result = await publish_site(FAKE_MULTIADDR)

        mock_upload.assert_awaited_once_with(
            files=[expected_path], multiaddr=FAKE_MULTIADDR
        )
        assert result == FAKE_CID

    @pytest.mark.asyncio
    async def test_publish_site_returns_cid(self):
        """publish_site returns the CID string produced by upload_site."""
        with patch.object(module, "upload_site", new=AsyncMock(return_value=FAKE_CID)):
            result = await publish_site(FAKE_MULTIADDR)

        assert result == FAKE_CID

    @pytest.mark.asyncio
    async def test_publish_site_propagates_upload_error(self):
        """publish_site does not swallow errors raised by upload_site."""
        with patch.object(
            module, "upload_site", new=AsyncMock(side_effect=ValueError("upload failed"))
        ):
            with pytest.raises(ValueError, match="upload failed"):
                await publish_site(FAKE_MULTIADDR)


# ---------------------------------------------------------------------------
# main
# ---------------------------------------------------------------------------


class TestMain:
    def test_main_prints_cid(self, capsys):
        """main() prints the CID returned by publish_site."""
        with patch.object(
            module,
            "publish_site",
            new=AsyncMock(return_value=FAKE_CID),
        ):
            main()

        captured = capsys.readouterr()
        assert FAKE_CID in captured.out

    def test_main_uses_aleph_multiaddr(self):
        """main() connects to the Aleph.im IPFS gateway."""
        captured_multiaddr = []

        async def _capture(multiaddr):
            captured_multiaddr.append(multiaddr)
            return FAKE_CID

        with patch.object(module, "publish_site", new=_capture):
            main()

        assert len(captured_multiaddr) == 1
        assert "aleph.im" in captured_multiaddr[0]
