#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import argparse
import configparser
import datetime
import dateutil.rrule
import psycopg
import requests
import time
import xml.etree.ElementTree

SECTIONS = ['temperature', 'humidity', 'shading', 'valve', 'ventilation']


def average(values: list) -> float:
    count = len(values)
    if count == 0:
        return None

    sum = 0
    for value in values:
        sum += value
    return sum / count


def atleast_one(values: list) -> bool:
    if len(values) == 0:
        return None

    for value in values:
        if bool(value):
            return True
    return False


def consolidate(values: dict) -> None:
    for value in values.values():
        for section in SECTIONS:
            value[section] = average(value[section])


def propagate(values: dict) -> None:
    sorted_keys = sorted(values)
    last = values[sorted_keys[0]] # TODO get from DB
    for key in sorted_keys:
        current = values[key]
        for section in SECTIONS:
            if current[section] is None:
                current[section] = last[section]
        last = current


def get_database_connection(config, database: str):
    parameters = {}
    if config.has_section(database):
        for item in config.items(database):
            parameters[item[0]] = item[1]
    else:
        raise Exception(f'Section {database} not found in the {config} file')
    return psycopg.connect(**parameters)


def generate_sql(sections: list) -> str:
    columns = ['time', 'id', 'name']
    values = ['%s', '%s', '%s']
    for section in sections:
        columns.append(section)
        values.append('%s')

    return f'INSERT INTO room ({", ".join(columns)}) VALUES({", ".join(values)}) ON CONFLICT (time, id) DO NOTHING;'

def main() -> None:
    now = datetime.date.today()
    parser = argparse.ArgumentParser(description='export data from Loxone to PostgreSQL', formatter_class=argparse.ArgumentDefaultsHelpFormatter)
    parser.add_argument('--server', default='http://miniserver', type=str, help='Loxone miniserver url')
    parser.add_argument('--user', default='loxone', type=str, help='Username to authenticate with')
    parser.add_argument('--password', default='enoxol2009', type=str, help='Password to authenticate with')
    parser.add_argument('--after', default='2009-01', type=str, help='only import data that was created after (YYYY-MM)')
    parser.add_argument('--before', default=now.strftime('%Y-%m'), type=str, help='only import data that was created before (YYYY-MM)')
    parser.add_argument('--database', default='postgresql', help='database config to use')
    parser.add_argument('--db-settings', default='database.ini', type=str, help='file containing postgresql connection configuration')
    parser.add_argument('--loxone-settings', default='loxone.ini', type=str, help='file containing loxone sensor configuration')

    arguments = parser.parse_args()
    before = datetime.datetime.strptime(arguments.before, '%Y-%m').date()
    after = datetime.datetime.strptime(arguments.after, '%Y-%m').date()
    loxone_config = configparser.ConfigParser()
    loxone_config.read(arguments.loxone_settings)

    inserts = []
    session = requests.Session()
    session.auth = (arguments.user, arguments.password)

    for room_id in loxone_config.sections():
        room = loxone_config[room_id]
        blubber = dict()
        for section in SECTIONS:
            for device_id in room[section].split('|'):
                if len(device_id) <= 0:
                    continue

                for date in dateutil.rrule.rrule(dateutil.rrule.MONTHLY, dtstart=after, until=before):
                    url = f'{arguments.server}/stats/{device_id}.{date:%Y%m}.xml'
                    response = session.get(url)
                    if response.status_code == 404:
                        time.sleep(1)
                        continue
                    response.raise_for_status()

                    root = xml.etree.ElementTree.fromstring(response.content)
                    for node in root.findall('.//S'):
                        attributes = node.attrib
                        timestamp = datetime.datetime.strptime(attributes['T'], '%Y-%m-%d %H:%M:%S')
                        key = f'{attributes["T"]}/{room_id}'
                        value = float(attributes['V'])
                        if key not in blubber:
                            entry = {'time': timestamp, 'id': room_id, 'name': room['name'], 'temperature': [], 'humidity': [], 'shading': [], 'valve': [], 'ventilation': []}
                            blubber[key] = entry
                        blubber[key][section].append(value)
        consolidate(blubber)
        propagate(blubber)
        for value in blubber.values():
            inserts.append(list(value.values()))
        inserts.sort(key=lambda x: f'{x[0]}|{x[1]}')

    db_config = configparser.ConfigParser()
    db_config.read(arguments.db_settings)
    sql = generate_sql(SECTIONS)
    database = None
    try:
        database = get_database_connection(db_config, arguments.database)
        cursor = database.cursor()
        cursor.executemany(sql, inserts)
        cursor.close()
        database.commit()
    finally:
       if database is not None:
           database.close()


if __name__ == '__main__':
    main()
