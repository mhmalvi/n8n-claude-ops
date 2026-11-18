"""DEMO ONLY: a one-port TCP relay so the isolated demo n8n can reach one Claude gateway.

    python relay.py <listen_port> <target_host> <target_port>

The demo n8n sits on its own Docker network; this relay is the only container that also joins the
gateway's network, so n8n can reach that single host:port and nothing else.
"""
from __future__ import annotations

import asyncio
import sys


async def pipe(reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
    """Copy bytes one way until EOF, then close the writer."""
    try:
        while data := await reader.read(65536):
            writer.write(data)
            await writer.drain()
    finally:
        writer.close()


async def handle(client_r: asyncio.StreamReader, client_w: asyncio.StreamWriter, host: str, port: int) -> None:
    """Open the upstream connection and pump both directions."""
    upstream_r, upstream_w = await asyncio.open_connection(host, port)
    await asyncio.gather(pipe(client_r, upstream_w), pipe(upstream_r, client_w), return_exceptions=True)


async def main(listen: int, host: str, port: int) -> None:
    """Serve forever on ``listen``."""
    # Binds all interfaces of the relay container, which only sits on the private demo network.
    server = await asyncio.start_server(lambda r, w: handle(r, w, host, port), "0.0.0.0", listen)
    async with server:
        await server.serve_forever()


if __name__ == "__main__":
    asyncio.run(main(int(sys.argv[1]), sys.argv[2], int(sys.argv[3])))
