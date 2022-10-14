#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import argparse
import configparser
import xml.etree.ElementTree


def main() -> None:
    parser = argparse.ArgumentParser(description='extract sensor information from Loxone Configuration', formatter_class=argparse.ArgumentDefaultsHelpFormatter)
    parser.add_argument('--configuration', default='Default.Loxone', type=str, help='Loxone configuration file')
    parser.add_argument('--output', default='loxone.ini', type=str, help='sensor information output')

    arguments = parser.parse_args()

    tree = xml.etree.ElementTree.parse(arguments.configuration)
    root = tree.getroot()

    rooms = dict()
    for node in root.findall('.//C[@Type="PlaceCaption"]/C[@Type="Place"]'):
        attributes = node.attrib
        rooms[attributes['U']] = {'id': attributes['U'], 'name': attributes['Title'], 'temperature': [], 'humidity': [], 'shading': [], 'valve': [], 'ventilation': []}

    for node in root.findall('.//*[@StatsType]'):
        room = None
        for ioData in node.findall('./IoData'):
            room = rooms[ioData.attrib['Pr']]

        attributes = node.attrib
        id = attributes['U']
        if attributes['Type'] == 'HeatIRoomController2':
            room['temperature'].append(id)
            continue

        if attributes['Type'] == 'LoxAIRAactor':
            room['valve'].append(id)
            continue

        if attributes['Type'] == 'TreeAactor':
            room['valve'].append(id)
            continue

        if attributes['Type'] == 'TreeAsensor':
            if attributes['Title'] == 'Luftfeuchte':
                room['humidity'].append(id)
                continue

    config = configparser.ConfigParser()
    for room in sorted(rooms.values(), key=lambda item: item['name']):
        if len(room['temperature']) + len(room['humidity']) + len(room['shading']) + len(room['valve']) + len(room['ventilation']) <= 0:
            # skip rooms without sensors or actors
            continue

        config[room['id']] = {
            'name': room['name'],
            'temperature': '|'.join(room['temperature']),
            'humidity': '|'.join(room['humidity']),
            'shading': '|'.join(room['shading']),
            'valve': '|'.join(room['valve']),
            'ventilation': '|'.join(room['ventilation']),
        }

    with open(arguments.output, 'w') as configfile:
        config.write(configfile)


if __name__ == '__main__':
    main()
