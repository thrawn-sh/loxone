import base64
import binascii
import enum
import json
import requests
import logging
import struct
import urllib
import websockets
import hashlib
import hmac

from Crypto.Cipher import AES
from Crypto.Cipher import PKCS1_v1_5
from Crypto.PublicKey import RSA


class LoxoneServer:

    CLIENT_ID = '22629cef-e3ec-4e71-95c5-eefcae9ac1c2'
    CLIENT_NAME = 'LoxoneMonitor'

    class AuthenticationUtil:

        _UTF8 = 'utf-8'

        @staticmethod
        def create_session_key(aes_key: str, aes_iv: str, public_key: str) -> str:
            pub_key = RSA.importKey(public_key)
            encryptor = PKCS1_v1_5.new(pub_key)
            sessionkey = encryptor.encrypt(bytes(f'{aes_key}:{aes_iv}', LoxoneServer.AuthenticationUtil._UTF8))
            return base64.b64encode(sessionkey).decode()

        @staticmethod
        def _zero_pad(message: bytes) -> bytes:
            size = AES.block_size
            return message + b'\0' * (size - len(message) % size)

        @staticmethod
        def encrypt_command(aes_key: str, aes_iv: str, command: str) -> str:
            key = binascii.unhexlify(aes_key)
            iv = binascii.unhexlify(aes_iv)
            cipher = AES.new(key, AES.MODE_CBC, iv=iv)
            padded = LoxoneServer.AuthenticationUtil._zero_pad(bytes(command, LoxoneServer.AuthenticationUtil._UTF8))
            encrypted_msg = cipher.encrypt(padded)
            b64encoded = base64.b64encode(encrypted_msg)
            return urllib.parse.quote(b64encoded, safe='')

        @staticmethod
        def calculate_hash(user: str, password: str, hash_algo: str, key: str, salt: str) -> str:
            password_cipher = hashlib.new(hash_algo)
            password_cipher.update(bytes(f'{password}:{salt}', LoxoneServer.AuthenticationUtil._UTF8))
            password_hash = password_cipher.hexdigest()
            password_hash = password_hash.upper()
            message = bytes(f'{user}:{password_hash}', LoxoneServer.AuthenticationUtil._UTF8)
            binary_key = binascii.unhexlify(key)
            token_cipher = hmac.new(binary_key, message, hash_algo)
            return token_cipher.hexdigest()

    class MessageHeader:

        class Identifier(enum.Enum):
            TEXT = 0
            FILE = 1
            VALUE_STATES = 2
            TEXT_STATES = 3
            DAYTIME_STATES = 4
            OUT_OF_SERVICE = 5
            KEEPALIVE = 6
            WEATHER_STATES = 7

            @staticmethod
            def convert(value: int) -> 'LoxoneServer.MessageHeader.Identifier':
                try:
                    return LoxoneServer.MessageHeader.Identifier(value)
                except ValueError:
                    return None

        _ESTIMATION_HEADER = 0x80
        _LOGGER = logging.getLogger('loxone.LoxoneServer.MessageHeader')
        _PREFIX = 0x03
        _RESERVED = 0x0

        def __init__(self, identifier: 'LoxoneServer.MessageHeader.Identifier', size: int) -> 'LoxoneServer.MessageHeader':
            self.identifier = identifier
            self.size = size

        def __str__(self):
            return f'Identifier(identifier: {self.identifier}, size: {self.size})'

        @staticmethod
        async def parse(websocket: websockets.WebSocketClientProtocol) -> 'LoxoneServer.MessageHeader':
            LoxoneServer.MessageHeader._LOGGER.debug('waiting for header message')
            message = await websocket.recv()

            LoxoneServer.MessageHeader._LOGGER.debug(f'header: {message}')
            bin_type, identifier, info, reserved, size = struct.unpack_from('<BBBBI', message)

            assert bin_type == LoxoneServer.MessageHeader._PREFIX, 'must be binary type (0x03)'
            identifier = LoxoneServer.MessageHeader.Identifier.convert(identifier)
            assert identifier is not None, 'unknown message identifier'
            if info == LoxoneServer.MessageHeader._ESTIMATION_HEADER:
                LoxoneServer.MessageHeader._LOGGER.debug('estimation header => skipping waiting for correct header')
                return await LoxoneServer.MessageHeader.parse(websocket)
            assert reserved == LoxoneServer.MessageHeader._RESERVED, 'reserved must be empty'
            return LoxoneServer.MessageHeader(identifier, size)

    class MessageBody:

        _LOGGER = logging.getLogger('loxone.LoxoneServer.MessageBody')

        @staticmethod
        async def parseTextMessage(websocket: websockets.WebSocketClientProtocol) -> str:
            LoxoneServer.MessageBody._LOGGER.debug('waiting for text message')
            message = await websocket.recv()
            LoxoneServer.MessageBody._LOGGER.debug('text: RECEIVED')
            return message

        @staticmethod
        async def parseJsonMessage(websocket: websockets.WebSocketClientProtocol) -> dict[str, any]:
            LoxoneServer.MessageBody._LOGGER.debug('waiting for json message')
            message = await websocket.recv()
            LoxoneServer.MessageBody._LOGGER.debug('json: RECEIVED')
            return json.loads(message)

        @staticmethod
        async def parseValueStates(websocket: websockets.WebSocketClientProtocol) -> dict[str, float]:
            LoxoneServer.MessageBody._LOGGER.debug('waiting for value-state message')
            message = await websocket.recv()
            LoxoneServer.MessageBody._LOGGER.debug('value-state: RECEIVED')
            result = dict()
            for i in range(0, len(message), 24):
                uuid = struct.unpack_from('<I2H8B', message, i)
                uuid = f'{uuid[0]:08x}-{uuid[1]:04x}-{uuid[2]:04x}-{uuid[3]:02x}{uuid[4]:02x}{uuid[5]:02x}{uuid[6]:02x}{uuid[7]:02x}{uuid[8]:02x}{uuid[9]:02x}{uuid[10]:02x}'

                result[uuid] = struct.unpack_from('<d', message, i + 16)[0]

            return result

        @staticmethod
        async def sendMessage(websocket: websockets.WebSocketClientProtocol, message: str) -> None:
            LoxoneServer.MessageBody._LOGGER.debug(f'sending: {message}')
            await websocket.send(message)

        @staticmethod
        async def sendKeepAlive(websocket: websockets.WebSocketClientProtocol) -> None:
            return await LoxoneServer.MessageBody.sendMessage(websocket, 'keepalive')

    class RestClient:

        _LOGGER = logging.getLogger('loxone.LoxoneServer.RestClient')

        class MiniserverInfo:

            def __init__(self, json: dict[str, any], server: str) -> 'LoxoneServer.RestClient.MiniserverInfo':
                self.snr = json['snr']
                self.version = json['version']
                self.key = json['key']
                self.is_in_trust = json['isInTrust']
                if json.get('local', False):
                    ip = json['address'].replace('.', '-')
                    serial = json['snr'].replace(':', '')
                    hostname = f'{ip}.{serial}.dyndns.loxonecloud.com'
                else:
                    hostname = server

                protocol = 'ws'
                if json.get('httpsStatus', 0) == 1:
                    protocol = 'wss'

                self.ws_base_url = f'{protocol}://{hostname}'

            def __str__(self):
                return f'MiniserverInfo(snr: {self.snr}, version: {self.version}, key: {self.key}, isInTrust: {self.is_in_trust}, http_base_url: {self.http_base_url}, ws_base_url: {self.ws_base_url})'

        @staticmethod
        def get_info(hostname: str) -> 'LoxoneServer.RestClient.MiniserverInfo':
            response = requests.get(f'http://{hostname}/jdev/cfg/apiKey', allow_redirects=True)
            assert response.status_code == 200, 'failed to get info'
            response = response.json()
            LoxoneServer.RestClient._LOGGER.debug(f'response: {response}')
            assert response['LL']['control'] == 'dev/cfg/apiKey', 'unexpected control'
            assert response['LL']['Code'] == '200', 'unexpected code'
            value: str = response['LL']['value']
            value = value.replace("'", '"')  # make json loadable
            value = json.loads(value)
            return LoxoneServer.RestClient.MiniserverInfo(value, hostname)

        @staticmethod
        def get_public_key(server: str) -> str:
            response = requests.get(f'http://{server}/jdev/sys/getPublicKey', allow_redirects=True)
            assert response.status_code == 200, 'failed to get public key'
            response = response.json()
            LoxoneServer.RestClient._LOGGER.debug(f'response: {response}')
            assert response['LL']['control'] == 'dev/sys/getPublicKey', f'unexpected control: {response}'
            assert response['LL']['Code'] == '200', f'unexpected code: {response}'
            value: str = response['LL']['value']
            # make proper public key
            value = value.replace('-----BEGIN CERTIFICATE-----', '-----BEGIN PUBLIC KEY-----\n')
            value = value.replace('-----END CERTIFICATE-----', '\n-----END PUBLIC KEY-----')
            return value

    class Permission(enum.Enum):
        NONE = 0x00000000,
        ADMIN = 0x00000001,
        WEB = 0x00000002,
        APP = 0x00000004,
        CONFIG = 0x00000008,
        FTP = 0x00000010,
        CHANGE_PWD = 0x00000020,
        EXPERT_MODE = 0x00000040,
        OP_MODES = 0x00000080,
        SYS_WS = 0x00000100,
        AD = 0x00000200,
        ADOPT_UI = 0x00000400,
        USER_MGMT = 0x00000800,
        DEVICE_MGMT = 0x00001000,
        PLUGIN_MGMT = 0x00002000,
        TRUST_JWT_AUTH = 0x00004000,
        TRIGGER_UPDATE = 0x00008000,
        TRIGGER_BACKUP = 0x00010000
