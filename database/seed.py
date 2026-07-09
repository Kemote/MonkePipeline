"""Populate the database with a few sample assets.

Run from the project root:  python3 -m database.seed
"""

import struct
import zlib

from database.db import init_db, get_session
from database import manager


def make_png(rgb, size=64):
    """Build a minimal solid-color PNG in memory (no external deps)."""
    def chunk(tag, payload):
        data = tag + payload
        return struct.pack(">I", len(payload)) + data + struct.pack(">I", zlib.crc32(data))

    header = struct.pack(">IIBBBBB", size, size, 8, 2, 0, 0, 0)
    row = b"\x00" + bytes(rgb) * size
    body = zlib.compress(row * size)
    return (b"\x89PNG\r\n\x1a\n"
            + chunk(b"IHDR", header)
            + chunk(b"IDAT", body)
            + chunk(b"IEND", b""))


SAMPLES = [
    {
        "data": {
            "name": "monkey_hero", "author": "tomek", "version": "v001", "status": "canceled",
            "modified_by": "tomek",
            "steps": {"model": 1, "rig": 1},
        },
        "color": (140, 90, 60),
    },
    {
        "data": {
            "name": "monkey_hero", "author": "tomek", "version": "v002", "status": "stable",
            "modified_by": "tomek",
            "steps": {
                "model": {"value": 3, "status": "stable"},
                "rig": {"value": 2, "status": "stable"},
                "lookdev": {"value": 1, "status": "wip"},
            },
        },
        "color": (90, 140, 70),
    },
    {
        "data": {
            "name": "monkey_hero", "author": "anna", "version": "v003", "status": "wip",
            "modified_by": "anna",
            "steps": {"model": {"value": 4, "status": "wip"}},
        },
        "color": (70, 110, 160),
    },
    {
        "data": {
            "name": "jungle_tree", "author": "marek", "version": "v001", "status": "stable",
            "modified_by": "marek",
            "steps": {"model": {"value": 2, "status": "stable"}, "lookdev": 1},
        },
        "color": (60, 130, 90),
    },
    {
        "data": {
            "name": "banana_prop", "author": "anna", "version": "v001", "status": "wip",
            "modified_by": "anna",
            "steps": {"model": 1},
        },
        "color": (200, 180, 60),
    },
]


def seed():
    init_db()
    with get_session() as session:
        if manager.find_assets(session):
            print("Database already contains assets, nothing seeded.")
            return
        for sample in SAMPLES:
            asset = manager.create_asset(
                session,
                sample["data"],
                image=make_png(sample["color"]),
                image_name=f"{sample['data']['name']}.png",
            )
            print(f"created {asset!r}")
    print("Done.")


if __name__ == "__main__":
    seed()
