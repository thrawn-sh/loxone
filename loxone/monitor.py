#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import argparse
import asyncio
import secrets
import logging
import websockets

from loxone.loxone_server import LoxoneServer

# Configure the logger
logging.basicConfig(level=logging.WARNING,
                    format='%(asctime)s - %(name)-12s - %(levelname)-8s - %(message)s',
                    handlers=[logging.StreamHandler()])

# Create a global logger
LOGGER = logging.getLogger('loxone.monitor')


async def keepalive(websocket: websockets.WebSocketClientProtocol, sleep: int) -> None:
    try:
        while True:
            await asyncio.sleep(sleep)
            await LoxoneServer.MessageBody.sendKeepAlive(websocket)
            LOGGER.debug('keepalive sent')
    except Exception as e:
        LOGGER.error(f'keepalive error: {e}')
        raise


async def process_updates(websocket: websockets.WebSocketClientProtocol) -> None:
    try:
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
                LOGGER.info(states)
                continue

            # unsupported message
            await websocket.recv()
            LOGGER.debug(f'unsupported message of type {header.identifier}: SKIPPING')
    except Exception as e:
        LOGGER.error(f'process_updates error: {e}')
        raise


async def listen(server: str, user: str, password) -> None:
    # Step 1
    info = LoxoneServer.RestClient.get_info(server)

    # Step 2
    public_key = LoxoneServer.RestClient.get_public_key(server)

    # Step 3
    websocket_url = f'{info.ws_base_url}/ws/rfc6455'
    LOGGER.debug(f'connecting to {websocket_url}')
    async with websockets.connect(websocket_url) as websocket:
        # Step 4
        aes_key = secrets.token_hex(32)
        LOGGER.debug(f'aes_key: {aes_key}')

        # Step 5
        aes_iv = secrets.token_hex(16)
        LOGGER.debug(f'aes_iv: {aes_iv}')

        # Step 6
        session_key = LoxoneServer.AuthenticationUtil.create_session_key(aes_key, aes_iv, public_key)
        LOGGER.debug(f'session_key: {session_key}')

        # Step 7
        await LoxoneServer.MessageBody.sendMessage(websocket, f'jdev/sys/keyexchange/{session_key}')
        header = await LoxoneServer.MessageHeader.parse(websocket)
        assert header.identifier == LoxoneServer.MessageHeader.Identifier.TEXT, 'expected text (json) message'
        message = await LoxoneServer.MessageBody.parseJsonMessage(websocket)

        # Step 8
        salt = secrets.token_hex(2)
        LOGGER.debug(f'salt: {salt}')

        # Step 9.b
        await LoxoneServer.MessageBody.sendMessage(websocket, f'jdev/sys/getkey2/{user}')
        header = await LoxoneServer.MessageHeader.parse(websocket)
        assert header.identifier == LoxoneServer.MessageHeader.Identifier.TEXT, 'expected text (json) message'
        message = await LoxoneServer.MessageBody.parseJsonMessage(websocket)
        assert message['LL']['control'] == f'jdev/sys/getkey2/{user}', f'unexpected control: {message}'
        assert message['LL']['code'] == '200', f'unexpected code: {message}'
        user_hash = LoxoneServer.AuthenticationUtil.calculate_hash(user, password, message['LL']['value']['hashAlg'], message['LL']['value']['key'], message['LL']['value']['salt'])

        # TODO maybe use APP permission for longer token lifetime
        token_command = f'salt/{salt}/jdev/sys/getjwt/{user_hash}/{user}/{LoxoneServer.Permission.WEB.value}/{LoxoneServer.CLIENT_ID}/{LoxoneServer.CLIENT_NAME}'
        encrypted_command = LoxoneServer.AuthenticationUtil.encrypt_command(aes_key, aes_iv, token_command)
        await LoxoneServer.MessageBody.sendMessage(websocket, f'jdev/sys/enc/{encrypted_command}')
        header = await LoxoneServer.MessageHeader.parse(websocket)
        assert header.identifier == LoxoneServer.MessageHeader.Identifier.TEXT, 'expected text (json) message'
        await LoxoneServer.MessageBody.parseJsonMessage(websocket)

        # get current values
        await LoxoneServer.MessageBody.sendMessage(websocket, 'jdev/sps/enablebinstatusupdate')
        header = await LoxoneServer.MessageHeader.parse(websocket)
        assert header.identifier == LoxoneServer.MessageHeader.Identifier.TEXT, 'expected text (json) message'
        await LoxoneServer.MessageBody.parseJsonMessage(websocket)

        try:
            # start keepalive and process updates
            keepalive_task = asyncio.create_task(keepalive(websocket, 60))
            process_updates_task = asyncio.create_task(process_updates(websocket))

            # wait for either task to complete
            done, pending = await asyncio.wait(
                [keepalive_task, process_updates_task],
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
            LOGGER.error(f'connection closed with code {e.code}')


def main() -> None:
    parser = argparse.ArgumentParser(description='export data from Loxone to PostgreSQL', formatter_class=argparse.ArgumentDefaultsHelpFormatter)
    parser.add_argument('--server', default='miniserver', type=str, help='Loxone miniserver hostname')
    parser.add_argument('--user', default='loxone', type=str, help='Username to authenticate with')
    parser.add_argument('--password', default='loxone', type=str, help='Password to authenticate with')
    parser.add_argument('--log-level', default='WARNING', choices=['DEBUG', 'INFO', 'WARNING', 'ERROR', 'CRITICAL'], help='Set the logging level')
    arguments = parser.parse_args()

    log_level = getattr(logging, arguments.log_level.upper())
    LOGGER.setLevel(log_level)
    logging.getLogger('loxone.loxone_server').setLevel(log_level)

    asyncio.run(listen(arguments.server, arguments.user, arguments.password))


if __name__ == '__main__':
    main()
