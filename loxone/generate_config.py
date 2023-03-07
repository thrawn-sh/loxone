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
        rooms[attributes['U']] = {'id': attributes['U'], 'name': attributes['Title'], 'temperature': [], 'temperature_target': [], 'humidity': [], 'light': [], 'shading': [], 'valve': [], 'ventilation': []}

    for node in root.findall('.//C'):
        room = None
        for ioData in node.findall('./IoData/[@Pr]'):
            room = rooms[ioData.attrib['Pr']]

        attributes = node.attrib
        id = attributes['U']
        if attributes['Type'] == 'HeatIRoomController2':
            for target in node.findall('./Co/[@K="AQt"]'):
                room['temperature_target'].append(target.attrib['U'])
            for target in node.findall('./Co/[@K="Temp"]'):
                room['temperature'].append(target.attrib['U'])
            continue

        if attributes['Type'] == 'LightController2':
            for target in node.findall('./Co'):
                if target.attrib['K'].startswith('AQ'):
                    uuid = target.attrib['U']
                    if root.findall(f'.//C[@Type="OutputRef"]/Co/In[@Input="{uuid}"]'):
                        room['light'].append(uuid)
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
        if len(room['temperature']) + len(room['temperature_target']) + len(room['humidity']) + len(room['light']) + len(room['shading']) + len(room['valve']) + len(room['ventilation']) <= 0:
            # skip rooms without sensors or actors
            continue

        config[room['id']] = {
            'name': room['name'],
            'temperature': '|'.join(room['temperature']),
            'temperature_target': '|'.join(room['temperature_target']),
            'humidity': '|'.join(room['humidity']),
            'light': '|'.join(room['light']),
            'shading': '|'.join(room['shading']),
            'valve': '|'.join(room['valve']),
            'ventilation': '|'.join(room['ventilation']),
        }

    with open(arguments.output, 'w') as configfile:
        config.write(configfile)


if __name__ == '__main__':
    main()
