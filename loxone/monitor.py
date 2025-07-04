#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import argparse
import asyncio
import asyncpg
import datetime
import json
import secrets
import logging
import pathlib
import ssl
import websockets

from loxone.loxone_server import LoxoneServer
from loxone.model import Building, ChangeResponse
from loxone.configuration import decode, download_latest_config

# Create a global logger
LOGGER = logging.getLogger('loxone.monitor')

AES_KEY_LENGTH = 32
AES_IV_LENGTH = 16

DATALOCK = asyncio.Lock()
MAX_AGGREGATION_SECONDS = 30


async def keepalive(websocket: websockets.ClientConnection, sleep: int) -> None:
    while True:
        await asyncio.sleep(sleep)
        await LoxoneServer.MessageBody.sendKeepAlive(websocket)
        LOGGER.debug('keepalive sent')


async def process_updates(websocket: websockets.ClientConnection, building: Building, uri: str) -> None:
    while True:
        header = await LoxoneServer.MessageHeader.parse(websocket)
        if header.identifier == LoxoneServer.MessageHeader.Identifier.KEEPALIVE:
            LOGGER.debug('keepalive => no message body')
            continue

        if header.size == 0:
            LOGGER.debug('no message to be expected')
            continue

        if header.identifier == LoxoneServer.MessageHeader.Identifier.VALUE_STATES:
            states = await LoxoneServer.MessageBody.parseValueStates(websocket)
            async with DATALOCK:
                for id, value in states.items():
                    current = building.update(id, value)
                    if current.value > building.change.value:
                        building.change = current

            if (building.change.value > ChangeResponse.LATER.value):
                await persist_data(building, uri)
            continue

        # unsupported message
        await websocket.recv()
        LOGGER.debug(f'unsupported message of type {header.identifier}: SKIPPING')


async def scheduled_persist(building: Building, uri: str) -> None:
    while True:
        await asyncio.sleep(MAX_AGGREGATION_SECONDS)
        await persist_data(building, uri)


async def persist_data(building: Building, uri: str) -> None:
    now = datetime.datetime.now().replace(microsecond=0)
    unix = int(now.timestamp())
    async with DATALOCK:
        if building.change == ChangeResponse.NO:
            LOGGER.debug('no pending changes => skipping persistence')
            return
        if (building.change != ChangeResponse.IMMEDIATE) and (unix - building.lastPersisted) < MAX_AGGREGATION_SECONDS:
            LOGGER.debug(f'last persisted data is less than {MAX_AGGREGATION_SECONDS} seconds old => skipping persistence')
            return
        if uri == 'none':
            LOGGER.warning('no database uri provided => skipping persistence')
            building.lastPersisted = unix
            building.change = ChangeResponse.NO
            for room in building.rooms:
                values = [
                        room.temperature.getValue(),
                        room.temperatureTarget.getValue(),
                        room.humidity.getValue(),
                        room.light.getValue(),
                        room.shading.getValue(),
                        room.valve.getValue(),
                        room.ventilation.getValue(),
                        room.precence.getValue()
                    ]
                if any(v is not None for v in values):
                    LOGGER.info(f'{room.name:>20}: ' + ', '.join(f'{str(v):>5}' if v is not None else ' None' for v in values))

            return

        connection = await asyncpg.connect(uri)
        try:
            async with connection.transaction():
                LOGGER.info(f'persisting data @ {now}')
                for room in building.rooms:
                    # only persist if at least one value is defined to the room
                    values = [
                        room.temperature.getValue(),
                        room.temperatureTarget.getValue(),
                        room.humidity.getValue(),
                        room.light.getValue(),
                        room.shading.getValue(),
                        room.valve.getValue(),
                        room.ventilation.getValue(),
                        room.precence.getValue()
                    ]
                    if any(v is not None for v in values):
                        await connection.execute(
                            '''
                            INSERT INTO room (time, id, name, temperature, temperature_target, humidity, light, shading, valve, ventilation, precence)
                            VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11)
                            ON CONFLICT (time, id) DO NOTHING
                            ''',
                            now,
                            room.id,
                            room.name,
                            *values
                        )
        finally:
            await connection.close()
        building.lastPersisted = unix
        building.change = ChangeResponse.NO


async def listen(server: str, user: str, password, db_uri: str, folder: pathlib.Path) -> None:
    # Step 1
    info = LoxoneServer.RestClient.get_info(server)

    # Step 2
    public_key = LoxoneServer.RestClient.get_public_key(server)

    try:
        # Step 3
        websocket_url = f'{info.ws_base_url}/ws/rfc6455'
        LOGGER.debug(f'connecting to {websocket_url}')

        ssl_context = ssl.create_default_context()
        if not info.ws_base_url.endswith('dyndns.loxonecloud.com'):
            LOGGER.warning('disabling SSL certificate verification, because server is conected locally')
            ssl_context.check_hostname = False
            ssl_context.verify_mode = ssl.CERT_NONE

        async with websockets.connect(websocket_url, ssl=ssl_context) as websocket:
            # Step 4
            aes_key = secrets.token_hex(AES_KEY_LENGTH)
            LOGGER.debug(f'aes_key: {aes_key}')

            # Step 5
            aes_iv = secrets.token_hex(AES_IV_LENGTH)
            LOGGER.debug(f'aes_iv: {aes_iv}')

            # Step 6
            session_key = LoxoneServer.AuthenticationUtil.create_session_key(aes_key, aes_iv, public_key)
            LOGGER.debug(f'session_key: {session_key}')

            # Step 7
            await LoxoneServer.MessageBody.sendMessage(websocket, f'jdev/sys/keyexchange/{session_key}')
            header = await LoxoneServer.MessageHeader.parse(websocket)
            if header.identifier != LoxoneServer.MessageHeader.Identifier.TEXT:
                raise AssertionError('expected text (json) message')
            message = await LoxoneServer.MessageBody.parseJsonMessage(websocket)

            # Step 8
            salt = secrets.token_hex(2)
            LOGGER.debug(f'salt: {salt}')

            # Step 9.b
            await LoxoneServer.MessageBody.sendMessage(websocket, f'jdev/sys/getkey2/{user}')
            header = await LoxoneServer.MessageHeader.parse(websocket)
            if header.identifier != LoxoneServer.MessageHeader.Identifier.TEXT:
                raise AssertionError('expected text (json) message')
            message = await LoxoneServer.MessageBody.parseJsonMessage(websocket)
            if message['LL']['control'] != f'jdev/sys/getkey2/{user}':
                raise AssertionError(f'unexpected control: {message}')
            if message['LL']['code'] != '200':
                raise AssertionError(f'unexpected code: {message}')
            user_hash = LoxoneServer.AuthenticationUtil.calculate_hash(user, password, message['LL']['value']['hashAlg'], message['LL']['value']['key'], message['LL']['value']['salt'])
            if header.identifier != LoxoneServer.MessageHeader.Identifier.TEXT:
                raise AssertionError('expected text (json) message')
            if message['LL']['control'] != f'jdev/sys/getkey2/{user}':
                raise AssertionError(f'unexpected control: {message}')
            if message['LL']['code'] != '200':
                raise AssertionError(f'unexpected code: {message}')

            token_command = f'salt/{salt}/jdev/sys/getjwt/{user_hash}/{user}/{LoxoneServer.Permission.APP.value}/{LoxoneServer.CLIENT_ID}/{LoxoneServer.CLIENT_NAME}'
            encrypted_command = LoxoneServer.AuthenticationUtil.encrypt_command(aes_key, aes_iv, token_command)
            await LoxoneServer.MessageBody.sendMessage(websocket, f'jdev/sys/enc/{encrypted_command}')
            header = await LoxoneServer.MessageHeader.parse(websocket)
            if header.identifier != LoxoneServer.MessageHeader.Identifier.TEXT:
                raise AssertionError('expected text (json) message')
            message = await LoxoneServer.MessageBody.parseJsonMessage(websocket)

            # get strucuture file
            LOGGER.info('getting structure file')
            await LoxoneServer.MessageBody.sendMessage(websocket, 'data/LoxAPP3.json')
            header = await LoxoneServer.MessageHeader.parse(websocket)
            if header.identifier != LoxoneServer.MessageHeader.Identifier.FILE:
                raise AssertionError('expected text (json) file')
            message = await LoxoneServer.MessageBody.parseJsonMessage(websocket)
            if LOGGER.isEnabledFor(logging.DEBUG):
                with open("strucutredFile.json", "w", encoding="utf-8") as f:
                    json.dump(message, f, indent=2, ensure_ascii=False)
            building = Building(message)

            file = folder / f'{building.name}_{building.lastModified.strftime("%Y-%m-%dT%H-%M-%S")}.loxone'
            if not file.exists():
                LOGGER.info('pulling latest configuration from Loxone...')
                raw = download_latest_config(server, user, password)
                xml = decode(raw)
                if xml:
                    with open(file, 'wb') as output:
                        output.write(xml)
                else:
                    LOGGER.warning('no configuration file found in Loxone, skipping backup')

            # get current values
            LOGGER.info('requesting status update')
            await LoxoneServer.MessageBody.sendMessage(websocket, 'jdev/sps/enablebinstatusupdate')
            header = await LoxoneServer.MessageHeader.parse(websocket)
            if header.identifier != LoxoneServer.MessageHeader.Identifier.TEXT:
                raise AssertionError('expected text (json) message')
            message = await LoxoneServer.MessageBody.parseJsonMessage(websocket)
            if message['LL']['control'] != 'dev/sps/enablebinstatusupdate':
                raise AssertionError(f'unexpected control: {message}')
            if message['LL']['value'] != '1':
                raise AssertionError(f'unexpected value: {message}')
            if message['LL']['Code'] != '200':
                raise AssertionError(f'unexpected code: {message}')

            # start keepalive and process updates
            LOGGER.info('starting keepalive task')
            keepalive_task = asyncio.create_task(keepalive(websocket, 60))
            LOGGER.info('starting updates monitoring task')
            process_updates_task = asyncio.create_task(process_updates(websocket, building, db_uri))
            LOGGER.info('starting data persistence task')
            persist_task = asyncio.create_task(scheduled_persist(building, db_uri))

            # wait for either task to complete
            done, pending = await asyncio.wait(
                [keepalive_task, process_updates_task, persist_task],
                return_when=asyncio.FIRST_EXCEPTION
            )

            # cancel the pending task
            for task in pending:
                task.cancel()

            # raise exceptions if any
            for task in done:
                if task.exception():
                    raise task.exception()
    except websockets.ConnectionClosed as e:
        if e.code == 1000:
            LOGGER.info('connection closed cleanly')
            return
        LOGGER.error(f'connection closed with code {e.code}')
        raise e


async def process(arguments) -> None:
    arguments.backup_folder.mkdir(parents=True, exist_ok=True)
    while True:
        LOGGER.info(f'connecting to Loxone... {arguments.server}')
        await listen(arguments.server, arguments.user, arguments.password, arguments.db_uri, arguments.backup_folder)
        LOGGER.info('connection closed, retrying in 20 seconds...')
        await asyncio.sleep(20)


def main() -> None:
    parser = argparse.ArgumentParser(description='export data from Loxone to PostgreSQL', formatter_class=argparse.ArgumentDefaultsHelpFormatter)
    parser.add_argument('--server', type=str, help='Loxone miniserver hostname', required=True)
    parser.add_argument('--user', type=str, help='Username to authenticate with', required=True)
    parser.add_argument('--password', type=str, help='Password to authenticate with', required=True)
    parser.add_argument('--db-uri', type=str, help='PostgreSQL connection URI postgresql://user:password@hostname/database', required=True)
    parser.add_argument('--log-level', default='INFO', choices=['DEBUG', 'INFO', 'WARNING', 'ERROR', 'CRITICAL'], help='Set the logging level')
    parser.add_argument('--backup-folder', type=pathlib.Path, help='Path to the backup folder', required=True)
    arguments = parser.parse_args()

    log_level = getattr(logging, arguments.log_level.upper())
    logging.getLogger('loxone').setLevel(log_level)

    asyncio.run(process(arguments))


if __name__ == '__main__':
    # Configure the logger
    logging.basicConfig(level=logging.WARNING,
                        format='%(asctime)s - %(name)-26s - %(levelname)-7s - %(message)s',
                        handlers=[logging.StreamHandler()])
    main()
