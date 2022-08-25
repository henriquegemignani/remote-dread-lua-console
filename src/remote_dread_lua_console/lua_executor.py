import asyncio
import dataclasses
import logging
import struct
from asyncio import StreamReader, StreamWriter
from typing import Optional


@dataclasses.dataclass()
class DreadSocketHolder:
    reader: StreamReader
    writer: StreamWriter
    api_version: int
    buffer_size: int
    request_number: int


class LuaException(Exception):
    pass


async def _read_response(reader: StreamReader, expected_number: int) -> bytes:
    request_number: bytes = await asyncio.wait_for(reader.read(1), timeout=20)
    if request_number[0] != expected_number:
        raise RuntimeError(f"Expected response {expected_number}, got {request_number[0]}")

    response: bytes = await asyncio.wait_for(reader.read(4), timeout=15)
    is_success = bool(response[0])

    length_data = response[1:4] + b"\x00"
    length = struct.unpack("<l", length_data)[0]

    data: bytes = await asyncio.wait_for(reader.read(length), timeout=15)

    if is_success:
        return data
    else:
        raise RuntimeError(data.decode("utf-8"))


class LuaExecutor:
    _connection_lock: asyncio.Lock
    _run_code_lock: asyncio.Lock
    _port = 6969
    _socket: Optional[DreadSocketHolder] = None
    _socket_error: Optional[Exception] = None

    def __init__(self, ip: str):
        self.logger = logging.getLogger(type(self).__name__)
        self._ip = ip
        self._connection_lock = asyncio.Lock()
        self._run_code_lock = asyncio.Lock()

    @property
    def ip(self):
        return self._ip

    @ip.setter
    def ip(self, value):
        self.disconnect()
        self._ip = value

    async def connect(self) -> bool:
        async with self._connection_lock:
            if self._socket is not None:
                return True

            try:
                ip = self._ip
                self._socket_error = None
                self.logger.info(f"Connecting to {ip}:{self._port}.")
                reader, writer = await asyncio.open_connection(ip, self._port)

                # Send API details request
                self.logger.info(f"Connection open, requesting API details.")

                writer.write(b"return string.format('%d,%d,%s', RL.Version, RL.BufferSize, tostring(RL.Bootstrap))")
                await asyncio.wait_for(writer.drain(), timeout=30)

                self.logger.debug(f"Waiting for API details response.")
                response = await _read_response(reader, 0)
                api_version, buffer_size, boostrap = response.decode("ascii").split(",")

                self.logger.info(f"Remote replied with API level {api_version}, buffer {buffer_size}, "
                                 f"had bootstrap ({boostrap}).")
                self._socket = DreadSocketHolder(reader, writer, int(api_version), int(buffer_size), 0)

                if ip != self._ip:
                    raise RuntimeError("changed ip during connection")

                return True

            except (OSError, asyncio.TimeoutError, struct.error, UnicodeError, RuntimeError) as e:
                # UnicodeError is for some invalid ip addresses
                self._socket = None
                self.logger.warning(f"Unable to connect to {self._ip}:{self._port} - ({type(e).__name__}) {e}")
                self._socket_error = e
                return False

    async def connect_or_raise(self):
        if not await self.connect():
            raise self._socket_error

    def disconnect(self):
        socket = self._socket
        self._socket = None
        if socket is not None:
            socket.writer.close()

    def is_connected(self) -> bool:
        return self._socket is not None

    async def run_lua_code(self, code: str) -> bytes:
        async with self._run_code_lock:
            self.logger.debug("Running lua code: %s", code)

            if not await self.connect():
                raise self._socket_error

            try:
                self._socket.request_number += 1
                self._socket.writer.write(code.encode("utf-8"))
                await asyncio.wait_for(self._socket.writer.drain(), timeout=30)
                response = await _read_response(self._socket.reader, self._socket.request_number)

                self.logger.debug("Response: %s", str(response))

            except (OSError, asyncio.TimeoutError, struct.error, UnicodeError, RuntimeError) as e:
                if isinstance(e, asyncio.TimeoutError):
                    self.logger.warning(f"Timeout when reading response from {self._ip}")
                    self._socket_error = LuaException(f"Timeout during communications with API")
                else:
                    self.logger.warning(
                        f"Unable to send {len(code)} bytes of code to {self._ip}:{self._port}: {e} ({type(e)})"
                    )
                    self._socket_error = LuaException(f"Unable to send lua code: {e} ({type(e)})")

                self.disconnect()
                raise self._socket_error from e

            return response
