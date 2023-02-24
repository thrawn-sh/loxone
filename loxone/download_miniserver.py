#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import argparse
import ftplib
import io
import struct
import zipfile
import zlib


def download_latest_config(server: str, user: str, password: str) -> io.BytesIO:
    ftp = ftplib.FTP(server)
    ftp.login(user, password)
    ftp.cwd('prog')

    # Ignore all the special cases, because the Miniserver does load in this order:
    # 1. /prog/Emergency.LoxCC (only if several reboots within 10 minutes happen!)
    # 2. /prog/sps_new.zip
    # 3. /prog/sps_new.LoxCC
    # 4. all `/prog/sps_vers_yyyymmddhhmmss.zip`
    #    or `/prog/sps_vers_yyyymmddhhmmss.LoxCC` files with `vers` less
    #    or equal the max. version allowed for the Miniserver
    #    (148 = 09030326; 162 = 10020326)
    # 5. /prog/sps.zip
    # 6. /prog/sps_old.zip
    # 7. /prog/sps.LoxPLAN (a very old fileformat)
    # 8. /prog/Default.Loxone or /prog/DefaultGo.Loxone, depending on the type of the Miniserver
    filelist = []
    for line in ftp.nlst():
        if line.startswith('sps_') and (line.endswith('.zip') or line.endswith('.LoxCC')):
            filelist.append(line)
    filename = sorted(filelist)[-1]

    buffer = io.BytesIO()
    ftp.retrbinary(f'RETR /prog/{filename}', buffer.write)
    ftp.quit()
    buffer.seek(0)

    return buffer


def uncompress(download_file: io.BytesIO) -> bytearray:
    with zipfile.ZipFile(download_file) as zip_file:
        with zip_file.open('sps0.LoxCC') as file:
            header = struct.unpack('<L', file.read(4))[0]
            if header != 0xaabbccee:  # magic word to detect a compressed file
                print('wrong header')
                return None

            compressedSize, uncompressedSize, checksum = struct.unpack('<LLL', file.read(12))
            data = file.read(compressedSize)
            index = 0
            result = bytearray()
            while index < len(data):
                # the first byte contains the number of bytes to copy in the upper
                # nibble. If this nibble is 15, then another byte follows with
                # the remainder of bytes to copy. (Comment: it might be possible that
                # it follows the same scheme as below, which means: if more than
                # 255+15 bytes need to be copied, another 0xff byte follows and so on)
                byte = struct.unpack('<B', data[index:index + 1])[0]
                index += 1
                copyBytes = byte >> 4
                byte &= 0xf
                if copyBytes == 15:
                    while True:
                        addByte = data[index]
                        copyBytes += addByte
                        index += 1
                        if addByte != 0xff:
                            break
                if copyBytes > 0:
                    result += data[index:index + copyBytes]
                    index += copyBytes
                if index >= len(data):
                    break
                # Reference to data which already was copied into the result.
                # bytesBack is the offset from the end of the string
                bytesBack = struct.unpack('<H', data[index:index + 2])[0]
                index += 2
                # the number of bytes to be transferred is at least 4 plus the lower
                # nibble of the package header.
                bytesBackCopied = 4 + byte
                if byte == 15:
                    # if the header was 15, then more than 19 bytes need to be copied.
                    while True:
                        val = struct.unpack('<B', data[index:index + 1])[0]
                        bytesBackCopied += val
                        index += 1
                        if val != 0xff:
                            break
                # Duplicating the last byte in the buffer multiple times is possible,
                # so we need to account for that.
                while bytesBackCopied > 0:
                    if -bytesBack + 1 == 0:
                        result += result[-bytesBack:]
                    else:
                        result += result[-bytesBack:-bytesBack + 1]
                    bytesBackCopied -= 1
            if checksum != zlib.crc32(result):
                print('Invalid checksum')
                return None

            if len(result) != uncompressedSize:
                print(f'Uncompressed filesize is wrong {len(result)} != {uncompressedSize}')
                return None

            return result


def main() -> None:
    parser = argparse.ArgumentParser(description='download configuration from miniserver', formatter_class=argparse.ArgumentDefaultsHelpFormatter)
    parser.add_argument('--server', default='http://miniserver', type=str, help='Loxone miniserver url')
    parser.add_argument('--user', default='loxone', type=str, help='Username to authenticate with')
    parser.add_argument('--password', default='enoxol2009', type=str, help='Password to authenticate with')
    parser.add_argument('--output', default='Project.Loxone', type=str, help='Output file to save configuration to')

    arguments = parser.parse_args()
    raw = download_latest_config(arguments.server, arguments.user, arguments.password)
    uncompressed = uncompress(raw)
    if uncompressed:
        with open(arguments.output, 'wb') as output:
            output.write(uncompressed)


if __name__ == '__main__':
    main()
