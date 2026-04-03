#!/usr/bin/env python3

"""
This script uploads the build SPA to IPFS.
It does not ping it or do anything else yet, so the result can only be accessed
 as long as the files are not garbage collected.
Requires: 'aioipfs>=0.6.2'
"""

import asyncio
import logging
from pathlib import Path
from typing import NewType

import aioipfs

logger = logging.getLogger(__file__)

Multiaddr = NewType("Multiaddr", str)
CID = NewType("CID", str)


async def upload_site(files: list[Path], multiaddr: Multiaddr) -> CID:
    if not files:
        raise ValueError("No files provided for upload")

    for f in files:
        if not Path(f).exists():
            raise FileNotFoundError(f"Path does not exist: {f}")

    client = aioipfs.AsyncIPFS(maddr=multiaddr)

    try:
        cid = None
        async for added_file in client.add(*files, recursive=True):
            name = added_file.get("Name", "<unknown>")
            hash_value = added_file.get("Hash")
            if hash_value:
                logger.debug("Uploaded file %s with CID: %s", name, hash_value)
                cid = hash_value
        # The last CID is the CID of the directory uploaded
        if cid is None:
            raise ValueError("Could not obtain a CID: no files were added")
        return CID(cid)
    finally:
        await client.close()


async def publish_site(multiaddr: Multiaddr) -> CID:
    path = Path(__file__).parent.parent / "site"
    cid = await upload_site(files=[path], multiaddr=multiaddr)
    return cid


def main():
    print(asyncio.run(publish_site(Multiaddr("/dns6/ipfs-2.aleph.im/tcp/443/https"))))


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    main()
