#!/usr/bin/env python3
"""Populate Router's memcached instance from its native-long query file."""

import argparse
import json
import socket
import struct
from pathlib import Path


def parse_args():
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", required=True, type=Path)
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", required=True, type=int)
    parser.add_argument("--chunk-bytes", default=1 << 20, type=int)
    return parser.parse_args()


def main():
    args = parse_args()
    record = struct.Struct("@ll")
    data = args.input.read_bytes()
    if len(data) % record.size:
        raise SystemExit(
            f"query file size {len(data)} is not a multiple of {record.size}"
        )

    sent = bytearray()
    records = 0
    unique_keys = set()
    with socket.create_connection((args.host, args.port), timeout=30) as sock:
        sock.settimeout(30)
        for key_number, value_number in record.iter_unpack(data):
            key = str(key_number).encode("ascii")
            value = str(value_number).encode("ascii")
            sent.extend(
                b"set "
                + key
                + b" 0 0 "
                + str(len(value)).encode("ascii")
                + b" noreply\r\n"
                + value
                + b"\r\n"
            )
            records += 1
            unique_keys.add(key_number)
            if len(sent) >= args.chunk_bytes:
                sock.sendall(sent)
                sent.clear()
        if sent:
            sock.sendall(sent)

        # A response to this ordered command confirms all preceding sets ran.
        sock.sendall(b"version\r\n")
        response = bytearray()
        while not response.endswith(b"\r\n"):
            response.extend(sock.recv(4096))
        if not response.startswith(b"VERSION "):
            raise SystemExit(f"unexpected memcached response: {response!r}")

    print(
        json.dumps(
            {
                "input": str(args.input.resolve()),
                "records": records,
                "unique_keys": len(unique_keys),
                "memcached_version": response.decode("ascii").strip(),
            },
            sort_keys=True,
        )
    )


if __name__ == "__main__":
    main()
