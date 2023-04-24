import asyncio
import dataclasses
from enum import IntEnum
import logging
import struct
from asyncio import StreamReader, StreamWriter
from typing import Optional
from PySide6.QtCore import QObject
from PySide6 import QtCore

from remote_dread_lua_console.window_signals import WindowSignals

# Packet Format for Dread:
# PACKET_HANDSHAKE
# Client request
# Byte 0: packet type (PACKET_HANDSHAKE)
# Byte 1: interest byte (see ClientInterest enum)
# Server answer
# Byte 0: packet type (PACKET_HANDSHAKE)
# Byte 1: request number
#
# PACKET_LOG_MESSAGE
# Server (active sending)
# Byte 0: packet type
# Byte 1-4: Size of string / log message
# Byte 5-n: Log message
#
# PACKET_REMOTE_LUA_EXEC
# Client request
# Byte 0: packet type (PACKET_REMOTE_LUA_EXEC)
# Byte 1-4 = length of content
# Byte 5-n: String to execute as lua
# Server answer
# Byte 0: packet type (PACKET_REMOTE_LUA_EXEC)
# Byte 1: request number
# Byte 2: boolean if success
# Byte 3-5: size of following answer
# Byte 6-n: answer
#
# PACKET_KEEP_ALIVE
# just a manual keep alive with only one byte from client to server
# Client request:
# Byte 0: packet type (PACKET_KEEP_ALIVE)

@dataclasses.dataclass()
class DreadSocketHolder:
    reader: StreamReader
    writer: StreamWriter
    api_version: int
    buffer_size: int
    request_number: int

class PacketType(IntEnum):
    PACKET_HANDSHAKE = b'1',
    PACKET_LOG_MESSAGE = b'2',
    PACKET_REMOTE_LUA_EXEC = b'3'
    PACKET_KEEP_ALIVE = b'4'

class ClientInterests(IntEnum):
    LOGGING = b'1',
    MULTIWORLD = b'2',


class LuaException(Exception):
    pass

class LuaExecutor(QObject):
    _connection_lock: asyncio.Lock
    _run_code_lock: asyncio.Lock
    _port = 6969
    _socket: Optional[DreadSocketHolder] = None
    _socket_error: Optional[Exception] = None
    window_signals = WindowSignals()
    pending_messages = []

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

    def emit_new_message(self, new_message: str):
        start_timer = len(self.pending_messages) > 0
        self.pending_messages.append(new_message)
        if start_timer:
            QtCore.QTimer.singleShot(200, self.window_signals.log_for_window.emit)

    async def read_packet_type(self, timeout):
        return await asyncio.wait_for(self._socket.reader.read(1), timeout)

    async def check_header(self):
        received_number: bytes = await asyncio.wait_for(self._socket.reader.read(1), None)
        if received_number[0] != self._socket.request_number:
            raise RuntimeError(f"Expected response {self._socket.request_number}, got {received_number}")

    async def parse_packet(self, packet_type):
        response = None
        match packet_type[0]:
            case PacketType.PACKET_HANDSHAKE:
                await self.check_header()
                self._socket.request_number = (self._socket.request_number  + 1) % 256
            case PacketType.PACKET_REMOTE_LUA_EXEC:
                await self.check_header()
                self._socket.request_number = (self._socket.request_number  + 1) % 256
                response = await asyncio.wait_for(self._socket.reader.read(4), timeout=15)
                is_success = bool(response[0])

                length_data = response[1:4] + b"\x00"
                length = struct.unpack("<l", length_data)[0]

                data: bytes = await asyncio.wait_for(self._socket.reader.read(length), timeout=15)

                if is_success:
                    self.emit_new_message(f"Execute response: {str(data)}")
                    response = data
                else:
                    self.emit_new_message("Running lua code throw an error. Check your code.")
            case PacketType.PACKET_LOG_MESSAGE:
                response = await asyncio.wait_for(self._socket.reader.read(4), timeout=15)
                length_data = response[0:4]
                length = struct.unpack("<l", length_data)[0]
                response = await asyncio.wait_for(self._socket.reader.read(length), timeout=15)
                self.emit_new_message(f"Log: {response}")
        return response

    async def read_loop(self) -> bytes:
        while self.is_connected():
            await self._read_response()
    
    async def _read_response(self) -> bytes:
        packet_type: bytes = await self.read_packet_type(None)
        return await self.parse_packet(packet_type)

    def build_packet(self, type: PacketType, msg: Optional[bytes]) -> bytes:
        retBytes: bytearray = bytearray()
        retBytes.append(type.value)
        if type == PacketType.PACKET_REMOTE_LUA_EXEC:
            retBytes.extend(len(msg).to_bytes(length=4, byteorder='little'))
        if type in [PacketType.PACKET_REMOTE_LUA_EXEC, PacketType.PACKET_HANDSHAKE]:
            retBytes.extend(msg)
        return retBytes

    async def send_keep_alive(self) -> bytes:
        while self.is_connected():
            await asyncio.sleep(2)
            self._socket.writer.write(self.build_packet(PacketType.PACKET_KEEP_ALIVE, None))
            try:
                await asyncio.wait_for(self._socket.writer.drain(), timeout=30)
            except (OSError, asyncio.TimeoutError, struct.error, UnicodeError, RuntimeError) as e:
                self.logger.warning(
                    f"Unable to send keep-alive packet to {self._ip}:{self._port}: {e} ({type(e)})"
                )
                self._socket_error = LuaException(f"Unable to send keep-alive: {e} ({type(e)})")
                self.emit_new_message(f"Connection lost")
                self.disconnect()

    async def connect(self) -> bool:
        async with self._connection_lock:
            if self._socket is not None:
                return True

            try:
                ip = self._ip
                self._socket_error = None
                self.logger.info(f"Connecting to {ip}:{self._port}.")
                reader, writer = await asyncio.open_connection(ip, self._port)
                self._socket = DreadSocketHolder(reader, writer, int(1), int(4096), 0)
                self._socket.request_number = 0

                # Send interests
                self.logger.info(f"Connection open, set interests.")
                interests =  ClientInterests.LOGGING
                writer.write(self.build_packet(PacketType.PACKET_HANDSHAKE, interests.to_bytes(1, "little")))
                await asyncio.wait_for(writer.drain(), timeout=30)
                await self._read_response()

                # Send API details request
                self.logger.info(f"requesting API details.")
                writer.write(self.build_packet(PacketType.PACKET_REMOTE_LUA_EXEC, b"return string.format('%d,%d,%s', RL.Version, RL.BufferSize, tostring(RL.Bootstrap))"))
                await asyncio.wait_for(writer.drain(), timeout=30)

                self.logger.info(f"Waiting for API details response.")
                response = await self._read_response()
                api_version, buffer_size, boostrap = response.decode("ascii").split(",")

                self.logger.info(f"Remote replied with API level {api_version}, buffer {buffer_size}, "
                                 f"had bootstrap ({boostrap}).")


                loop = asyncio.get_event_loop()
                loop.create_task(self.send_keep_alive())
                loop.create_task(self.read_loop())

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
        self.window_signals.connection_changed.emit()

    def disconnect(self):
        socket = self._socket
        self._socket = None
        if socket is not None:
            socket.writer.close()
        self.window_signals.connection_changed.emit()

    def is_connected(self) -> bool:
        return self._socket is not None

    async def run_lua_code(self, code: str) -> bytes:
        async with self._run_code_lock:
            self.logger.debug("Running lua code: %s", code)

            try:
                self._socket.writer.write(self.build_packet(PacketType.PACKET_REMOTE_LUA_EXEC, code.encode("utf-8")))
                await asyncio.wait_for(self._socket.writer.drain(), timeout=30)

            except (OSError, asyncio.TimeoutError, struct.error, UnicodeError, RuntimeError) as e:
                self.logger.warning(
                    f"Unable to send {len(code)} bytes of code to {self._ip}:{self._port}: {e} ({type(e)})"
                )
                self._socket_error = LuaException(f"Unable to send lua code: {e} ({type(e)})")

                self.disconnect()
                raise self._socket_error from e
