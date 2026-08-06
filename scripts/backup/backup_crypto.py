#!/usr/bin/env python3
"""Stream-encrypt backup artifacts with AES-256-GCM."""

from __future__ import annotations

import argparse
import hashlib
import os
import struct
from pathlib import Path

from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes

MAGIC = b"VAVBACKUP1"
CHUNK_SIZE = 1024 * 1024


def _key(path: Path) -> bytes:
    material = path.read_bytes().strip()
    if len(material) < 32:
        raise ValueError("backup encryption key must contain at least 32 bytes")
    return hashlib.sha256(b"vav-backup-v1\0" + material).digest()


def encrypt(source: Path, destination: Path, key_file: Path) -> None:
    nonce = os.urandom(12)
    encryptor = Cipher(algorithms.AES(_key(key_file)), modes.GCM(nonce)).encryptor()
    with source.open("rb") as incoming, destination.open("wb") as outgoing:
        outgoing.write(MAGIC + nonce)
        while chunk := incoming.read(CHUNK_SIZE):
            outgoing.write(encryptor.update(chunk))
        outgoing.write(encryptor.finalize())
        outgoing.write(struct.pack("!H", len(encryptor.tag)))
        outgoing.write(encryptor.tag)


def decrypt(source: Path, destination: Path, key_file: Path) -> None:
    size = source.stat().st_size
    if size < len(MAGIC) + 12 + 2 + 16:
        raise ValueError("encrypted backup is truncated")
    with source.open("rb") as incoming:
        header = incoming.read(len(MAGIC))
        if header != MAGIC:
            raise ValueError("encrypted backup has an invalid header")
        nonce = incoming.read(12)
        incoming.seek(-18, os.SEEK_END)
        tag_size = struct.unpack("!H", incoming.read(2))[0]
        if tag_size != 16:
            raise ValueError("encrypted backup has an invalid authentication tag")
        tag = incoming.read(tag_size)
        ciphertext_size = size - len(MAGIC) - len(nonce) - 2 - tag_size
        incoming.seek(len(MAGIC) + len(nonce))
        decryptor = Cipher(
            algorithms.AES(_key(key_file)), modes.GCM(nonce, tag)
        ).decryptor()
        remaining = ciphertext_size
        with destination.open("wb") as outgoing:
            while remaining:
                chunk = incoming.read(min(CHUNK_SIZE, remaining))
                if not chunk:
                    raise ValueError(
                        "encrypted backup ended before its authenticated tag"
                    )
                remaining -= len(chunk)
                outgoing.write(decryptor.update(chunk))
            outgoing.write(decryptor.finalize())


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("operation", choices=["encrypt", "decrypt"])
    parser.add_argument("source", type=Path)
    parser.add_argument("destination", type=Path)
    parser.add_argument("--key-file", required=True, type=Path)
    args = parser.parse_args()
    if args.operation == "encrypt":
        encrypt(args.source, args.destination, args.key_file)
    else:
        decrypt(args.source, args.destination, args.key_file)


if __name__ == "__main__":
    main()
