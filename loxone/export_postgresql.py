#!/usr/bin/env python3
# -*- coding: utf-8 -*-

from Crypto.Cipher import AES
from Crypto.Cipher import PKCS1_v1_5
from Crypto.PublicKey import RSA
import argparse
import asyncio
import base64
import binascii
import configparser
import datetime
import hashlib
import hmac
import json
import pathlib
import psycopg
import requests
import secrets
import struct
import tzlocal
import urllib
import websockets


UUID = '22629cef-e3ec-4e71-95c5-eefcae9ac1c2'
PERMISSION = 2
INFO = 'shadowhunt'


def get_miniserver_public_key(server: str) -> str:
    response = requests.get(f'http://{server}/jdev/sys/getPublicKey')
    key = response.json()['LL']['value']
    # make proper public key
    key = key.replace('-----BEGIN CERTIFICATE-----', '-----BEGIN PUBLIC KEY-----\n')
    key = key.replace('-----END CERTIFICATE-----', '\n-----END PUBLIC KEY-----')
    return key


def get_miniserver_info(server: str) -> dict:
    response = requests.get(f'http://{server}/jdev/cfg/apiKey')
    value = response.json()['LL']['value']
    value = value.replace("'", '"')  # make proper json
    return json.loads(value)


def calculate_real_server(info: dict, server: str) -> str:
    if info.get('httpsStatus', 0) != 1:
        return server
    if not info.get('local', False):
        return server

    ip = info['address'].replace('.', '-')
    serial = info['snr'].replace(':', '')
    return f'{ip}.{serial}.dyndns.loxonecloud.com'


def create_session_key(aes_key: str, aes_iv: str, public_key: str) -> str:
    pub_key = RSA.importKey(public_key)
    encryptor = PKCS1_v1_5.new(pub_key)
    sessionkey = encryptor.encrypt(bytes(f'{aes_key}:{aes_iv}', 'utf-8'))
    return base64.b64encode(sessionkey).decode()


def determine_secure(info: dict) -> str:
    if info.get('httpsStatus', 0) != 1:
        return ''
    return 's'


def zero_pad(message: bytes) -> bytes:
    return message + b'\0' * (AES.block_size - len(message) % AES.block_size)


def calculate_hash(secure: str, server: str, user: str, password: str) -> str:
    response = requests.get(f'http{secure}://{server}/jdev/sys/getkey2/{user}')
    value = response.json()['LL']['value']
    user_key = binascii.unhexlify(value['key'])
    hash_algo = value['hashAlg']
    user_salt = value['salt']

    password_cipher = hashlib.new(hash_algo)
    password_cipher.update(bytes(f'{password}:{user_salt}', 'utf-8'))
    password_hash = password_cipher.hexdigest()
    password_hash = password_hash.upper()
    message = bytes(f'{user}:{password_hash}', 'utf-8')

    token_cipher = hmac.new(user_key, message, hash_algo)
    return token_cipher.hexdigest()


def parseTable(eventTable: bytes) -> dict:
    result = dict()
    for i in range(0, len(eventTable), 24):
        uuid = struct.unpack_from('<I2H8B', eventTable, i)
        uuid = f'{uuid[0]:08x}-{uuid[1]:04x}-{uuid[2]:04x}-{uuid[3]:02x}{uuid[4]:02x}{uuid[5]:02x}{uuid[6]:02x}{uuid[7]:02x}{uuid[8]:02x}{uuid[9]:02x}{uuid[10]:02x}'

        result[uuid] = struct.unpack_from('<d', eventTable, i + 16)[0]

    return result


async def websocket_send(websocket, message: str) -> None:
    await websocket.send(message)
    await websocket.recv()
    await websocket.recv()


async def websocket_connect(secure: str, server: str, user: str, password: str, public_key: str) -> dict:
    # Step 4
    aes_key = secrets.token_hex(32)
    # print(f'aes_key: {aes_key}')

    # Step 5
    aes_iv = secrets.token_hex(16)
    # print(f'aes_iv: {aes_iv}')

    # Step 6
    session_key = create_session_key(aes_key, aes_iv, public_key)
    # print(f'session_key: {session_key}')

    async with websockets.connect(f'ws{secure}://{server}/ws/rfc6455') as websocket:
        # Step 7
        await websocket_send(websocket, f'jdev/sys/keyexchange/{session_key}')

        # Step 8
        salt = secrets.token_hex(2)
        # print(f'salt: {salt}')

        # Step 9.b
        user_hash = calculate_hash(secure, server, user, password)
        token_command = f'salt/{salt}/jdev/sys/getjwt/{user_hash}/{user}/{PERMISSION}/{UUID}/{INFO}'
        encrypted_command = encrypt_command(aes_key, aes_iv, token_command)
        await websocket_send(websocket, f'jdev/sys/enc/{encrypted_command}')

        # get current values
        await websocket_send(websocket, 'jdev/sps/enablebinstatusupdate')

        while True:
            response = await websocket.recv()
            bin_type, identifier, info, reserved, size = struct.unpack_from('<BBBBI', response)
            assert bin_type == 0x3, 'must be binary type (0x3)'
            assert info == 0x0, 'must be empty'
            assert reserved == 0x0, 'must be empty'

            response = await websocket.recv()
            # print(f'???: {response}')
            if identifier == 0x2:
                return parseTable(response)


def calculate_boolean(values: list) -> bool:
    if not values:
        return None

    for value in values:
        if bool(value):
            return True
    return False


def calculate_average(values: list) -> bool:
    if not values:
        return None

    result = 0.0
    for value in values:
        result = result + value
    return result / len(values)


def get_database_connection(config, database: str):
    parameters = {}
    if config.has_section(database):
        for item in config.items(database):
            parameters[item[0]] = item[1]
    else:
        raise Exception(f'Section {database} not found in the {config} file')
    return psycopg.connect(**parameters)


def generate_statement(pairs: list) -> str:
    keys = []
    values = []
    for key, value in pairs:
        keys.append(key)
        if value is None:
            values.append('NULL')
        else:
            values.append(f"'{value}'")

    return f'INSERT INTO room ({", ".join(keys)}) VALUES({", ".join(values)}) ON CONFLICT (time, id) DO NOTHING;'


def main() -> None:
    parser = argparse.ArgumentParser(description='export data from Loxone to PostgreSQL', formatter_class=argparse.ArgumentDefaultsHelpFormatter)
    parser.add_argument('--server', default='miniserver', type=str, help='Loxone miniserver hostname')
    parser.add_argument('--config', default='loxone.ini', type=str, help='Loxone configuration to process')
    parser.add_argument('--user', default='loxone', type=str, help='Username to authenticate with')
    parser.add_argument('--password', default='enoxol2009', type=str, help='Password to authenticate with')
    parser.add_argument('--use-local-ddns', action=argparse.BooleanOptionalAction, help='switch server to the dyndns.loxonecloud.com name')
    parser.add_argument('--sql-file', default='loxone-cache.sql', type=str, help='file for caching sql requests')
    parser.add_argument('--database', default='postgresql', help='database config to use')
    parser.add_argument('--db-settings', default='database.ini', type=str, help='file containing postgresql connection configuration')
    arguments = parser.parse_args()

    config = configparser.ConfigParser()
    config.read(arguments.config)

    # Step 1
    info = get_miniserver_info(arguments.server)

    if arguments.use_local_ddns:
        arguments.server = calculate_real_server(info, arguments.server)

    # Step 2
    public_key = get_miniserver_public_key(arguments.server)

    secure = determine_secure(info)
    # Step 3
    data = asyncio.run(websocket_connect(secure, arguments.server, arguments.user, arguments.password, public_key))
    if False:
        with open('loxone-dump.txt', 'w', encoding='utf-8') as file:
            for key, value in data.items():
                file.write(key)
                file.write(' ')
                file.write(str(value))
                file.write('\n')

    # custom
    now = datetime.datetime.now()
    now = now.replace(second=0, microsecond=0)
    now = now.astimezone(tzlocal.get_localzone()).isoformat()
    statements = []
    for section in config.sections():
        pairs = []
        pairs.append(('id', section))
        pairs.append(('time', now))
        for key, value in config.items(section):
            if key == 'name':
                pairs.append((key, value))
                continue

            listing = value.split('|')
            values = []
            for v in listing:
                if v == '' or v is None:
                    continue
                values.append(data[v])

            if key == 'light' or key == 'ventilation':
                value = calculate_boolean(values)
            else:
                value = calculate_average(values)

            pairs.append((key, value))
        statement = generate_statement(pairs)
        statements.append(statement)

    cache_file = pathlib.Path(arguments.sql_file)
    cache_file.parent.mkdir(parents=True, exist_ok=True)
    with open(cache_file, 'a', encoding='utf-8') as file:
        for statement in statements:
            file.write(statement)
            file.write('\n')

    db_config = configparser.ConfigParser()
    db_config.read(arguments.db_settings)
    with get_database_connection(db_config, arguments.database) as database:
        cursor = database.cursor()
        for statement in statements:
            cursor.execute(statement)
        cursor.close()
        database.commit()


def encrypt_command(aes_key: str, aes_iv: str, command: str) -> str:
    key = binascii.unhexlify(aes_key)
    iv = binascii.unhexlify(aes_iv)
    cipher = AES.new(key, AES.MODE_CBC, iv=iv)
    padded = zero_pad(bytes(command, 'utf-8'))
    encrypted_msg = cipher.encrypt(padded)
    b64encoded = base64.b64encode(encrypted_msg)
    return urllib.parse.quote(b64encoded, safe='')


if __name__ == '__main__':
    main()
