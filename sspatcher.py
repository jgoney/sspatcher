#!/usr/bin/env python

import argparse
import collections
import itertools
import logging
import os
import string
import wave

from io import BytesIO

from intelhex import IntelHex

# Constants describing the image file and format of the wavetable data.
IMAGE_SIZE_SHORT = 0x200000
IMAGE_SIZE_LONG = 0x800000
NUM_WT = 128
WT_NAME_OFFSET = 0x0F0000
WT_NAME_LENGTH = 8
WT_NAME_PREFIX = b'  '
WT_USER_NAME_LENGTH = WT_NAME_LENGTH - len(WT_NAME_PREFIX)
ALLOWED_CHARS = string.ascii_letters + string.digits + ' '  # characters allowed in wt names
WT_DATA_OFFSET = 0x100000
WT_DATA_LENGTH = 1024 * 8  # 512 16 bit unsigned ints per wave, 8 waves per table

# Consecutive identical values permitted in the wavetable audio data. This particular value is chosen because a
# couple waves in a row with a static value are conceivably useful.
RUN_LIMIT = WT_DATA_LENGTH // 4


class SSPatcherError(Exception):
    pass


def read_wt_data(f):
    """Given an open file containing the shapeshifter rom image, extract the wavetable audio data.

    :param f: File handle for the shapeshifter rom image.
    :return: List of bytes containing the wavetable audio data.
    """
    # Retrieve the wavetable audio data.
    data_block_length = WT_DATA_LENGTH * NUM_WT
    f.seek(WT_DATA_OFFSET)
    wt_data_block = f.read(data_block_length)
    if len(wt_data_block) != data_block_length:
        raise SSPatcherError('Got less than {} bytes when reading wavetable audio data.'.format(data_block_length))

    # The WT data is effectively random ints, but the EEPROM image has many long runs of identical values in
    # unused space. Use this fact to sanity check that the data at least looks legitimate.
    for byte, run in itertools.groupby(wt_data_block):
        length = len(list(run))
        if length > RUN_LIMIT:
            # For testing convenience, throw the run length in as an extra argument to the exception.
            raise SSPatcherError(
                'Found a run of {0} characters ({1}); wavetable data looks invalid.'.format(length, byte),
                length
            )
    return [wt_data_block[i:i + WT_DATA_LENGTH] for i in range(0, data_block_length, WT_DATA_LENGTH)]


def read_wt_names(f):
    """ Given an open file containing the shapeshifter rom image, extract the wavetable names.

    :param f: File handle for the shapeshifter rom image.
    :return: List of bytes containing the wavetable names.
    """
    # Retrieve the names of the wavetables.
    name_block_length = WT_NAME_LENGTH * NUM_WT
    f.seek(WT_NAME_OFFSET)
    wt_name_block = f.read(name_block_length)
    if len(wt_name_block) != name_block_length:
        raise SSPatcherError('Got less than {} bytes when reading wavetable names.'.format(name_block_length))
    wt_names = [
        wt_name_block[i:i + WT_NAME_LENGTH]
        for i in range(0, name_block_length, WT_NAME_LENGTH)
    ]

    # Sanity check: if we got the right data, the wavetable names should have the prefix specified in the
    # Shapeshifter documentation.
    for name in wt_names:
        if not name.startswith(WT_NAME_PREFIX):
            raise SSPatcherError('Found wavetable name ({}) without valid prefix.'.format(name))

    # Strip the prefix from the names returned for easy handling. It can be added back when patching the image.
    return [name[len(WT_NAME_PREFIX):] for name in wt_names]


def _get_index_from_filename(wt):
    name = wt[0]

    try:
        i, _ = name.split('_', 1)
    except ValueError:
        raise SSPatcherError("--sortprefix flag given, but {} seems to not be formatted".format(name)) 
    
    return int(i)


def _get_name_from_filename(name):
    try:
        _, name = name.split('_', 1)
    except ValueError:
        raise SSPatcherError("--sortprefix flag given, but {} seems to not be formatted".format(name)) 
    
    return name.strip()

def read_wavetables_from_files(path, is_prefixed=False):
    """Read wavetable data from files and infer wavetable names from the filenames.

    :param path: String path to the directory where the files are located.
    :param is_prefixed: Boolean key for whether or not wavetable names are prefixed with sorting info.
    :return: Ordered dict where keys are bytes containing the names of length WT_USER_NAME_LENGTH and values are bytes
             of length WT_DATA_LENGTH containing audio data.
    """
    if not os.path.isdir(path):
        raise SSPatcherError("'{} doesn't exist or isn't a directory; aborting.".format(path))

    # Build the dictionary
    wavetables = {}
    for wt_file in os.listdir(path):
        if wt_file == ".DS_Store":
            continue
        
        with open(os.path.join(path, wt_file), 'rb') as f:
            name = os.path.splitext(wt_file)[0]

            data = f.read()
            if name in wavetables:
                raise SSPatcherError('Duplicate name "{}" in wavetable names.'.format(name))
            if len(data) != WT_DATA_LENGTH:
                raise SSPatcherError(
                    'Wavetable {} was the wrong size (expected {}, got {}).'.format(name, WT_DATA_LENGTH, len(data))
                )
            wavetables[name] = data

    if is_prefixed:
        wavetables = {sanitize_name(_get_name_from_filename(name)): data for name, data in sorted(wavetables.items(), key=_get_index_from_filename)}
    else:
        wavetables = {sanitize_name(name): data for name, data in sorted(wavetables.items(), key=lambda item: item[0].strip())}

    # Basic sanity checking is done while building the dict, but make sure we also got the right number of wavetables
    if len(wavetables) != NUM_WT:
        raise SSPatcherError('Found wrong number of wavetables (expected {}, got {}).'.format(NUM_WT, len(wavetables)))

    # Return a sorted dict - can be padded with spaces on the left, so strip whitespace when sorting.
    return collections.OrderedDict(wavetables.items())


def check_image_size(filename):
    """Check that the file containing the ROM image is the expected size, and raise an exception if not.

    :param filename: String path to the shapeshifter rom image.
    """
    if os.path.getsize(filename) != IMAGE_SIZE_SHORT and os.path.getsize(filename) != IMAGE_SIZE_LONG:
        raise SSPatcherError(
            'Shapeshifter ROM image ({}) had unexpected size (got {}, expected {} or {}).'.format(
                filename, os.path.getsize(filename), IMAGE_SIZE_SHORT, IMAGE_SIZE_LONG
            )
        )


def extract(source, destination):
    """Extract wavetables from a file containing the shapeshifter ROM image and write them to individual files.

    :param source: String path to the shapeshifter rom image.
    :param destination: String path to the directory to put the individual wavetable files in.
    """
    check_image_size(source)
    if os.path.exists(destination):
        raise SSPatcherError("{} already exists; aborting so existing data isn't overwritten.".format(destination))
    else:
        os.mkdir(destination)
    with open(source, 'rb') as f:
        names = read_wt_names(f)
        tables = read_wt_data(f)
    if not len(names) == len(tables) == NUM_WT:
        raise SSPatcherError('Wavetable name/data had unexpected length (names:{}, tables:{}, expected:{}).'.format(
            len(names), len(tables), NUM_WT
        ))
    for name, table in zip(names, tables):
        # write wavs for testing
        new_wav = "{}/{}.wav".format("test_wavs", name)
        with wave.open(new_wav, mode="wb") as f_out:
            f_out.setnchannels(1)
            f_out.setsampwidth(2)
            f_out.setframerate(44100)
            f_out.writeframes(table)

        with open(os.path.join(destination, name.decode() + '.raw'), 'wb') as f:
            f.write(table)


def sanitize_name(name):
    """Convert a filename into a 6 character name suitable for use with the shapeshifter.

    Pads out names that are too short, truncates names that are too long, and ensures that the characters in the name
    are among those supported by the shapeshifter.

    :param name: String containing a filename that wavetable data was stored in
    :return: Bytes containing a 6 character name suitable for use with the shapeshifter
    """
    log = logging.getLogger('sspatcher')
    if len(name) > WT_USER_NAME_LENGTH:
        # Use the last 6 characters since this is maybe less likely to cause collisions than the first 6.
        new_name = name.strip()[-6:]
        log.warn('Filename "{}" was too long. Renamed to "{}".'.format(name, new_name))
        name = new_name
    # It's possible the name is too short now, due to stripping whitespace.
    if len(name) < WT_USER_NAME_LENGTH:
        name = name.rjust(6)
    for ch in name:
        if ch not in ALLOWED_CHARS:
            raise SSPatcherError('Wavetable name ({}) contains invalid character ({}).'.format(name, ch))
    return name.encode()


def patch(source, destination):
    """Patch shapeshifter ROM image with the wavetables found in a source directory.

    :param source: String path to the directory where the wavetables are found.
    :param destination: String path to the shapeshifter rom image.
    """
    check_image_size(destination)
    data = read_wavetables_from_files(source)
    names = data.keys()
    wavetables = data.values()

    # Patch the ROM
    with open(destination, 'r+b') as f:
        name_data = WT_NAME_PREFIX + WT_NAME_PREFIX.join(names)
        f.seek(WT_NAME_OFFSET)
        f.write(name_data)

        wt_data = b''.join(wavetables)
        f.seek(WT_DATA_OFFSET)
        f.write(wt_data)

def derive_names(source, is_prefixed=False):

    data = read_wavetables_from_files(source, is_prefixed=is_prefixed)
    names = data.keys()
    wavetables = data.values()

    name_data = WT_NAME_PREFIX + WT_NAME_PREFIX.join(names)
    wt_data = b''.join(wavetables)

    # names
    in_f = BytesIO(name_data)

    ih = IntelHex()
    ih.loadbin(in_f, offset=WT_NAME_OFFSET)

    out_f = open(source + '_names.hex', 'w')
    ih.write_hex_file(out_f)
    out_f.close()

    # waves
    in_f = BytesIO(wt_data)

    ih = IntelHex()
    ih.loadbin(in_f, offset=WT_DATA_OFFSET)

    out_f = open(source + '_waves.hex', 'w')
    ih.write_hex_file(out_f)
    out_f.close()


if __name__ == '__main__':
    # Setup logging for error reporting.
    log = logging.getLogger('sspatcher')
    log.setLevel(logging.WARNING)
    handler = logging.StreamHandler()
    handler.setFormatter(logging.Formatter('%(levelname)s: %(message)s'))
    log.addHandler(handler)

    # Configure and run argparse.
    parser = argparse.ArgumentParser()
    parser.add_argument('--sortprefix', dest='sortprefix', action='store_true')
    parser.set_defaults(sortprefix=False)

    parser.add_argument('-i', '--image', help='Name of the Shapeshifter EEPROM image file.')
    parser.add_argument('-d',
        '--directory',
        nargs='?',
        help="Directory where extracted wavetable data will be written. If it doesn't exist, it will be created. "
             "Default: %(default)s",
        default='sstables'
    )
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument('-e', '--extract', help='Extract wavetables from the image.', action='store_true')
    group.add_argument('-p', '--patch', help='Patch the image file with new wavetables.', action='store_true')
    group.add_argument('-x', '--intelhex', help='Derive wavetables and names from directory of files, and write to IntelHex format.', action='store_true')
    args = parser.parse_args()

    # Perform the user's requested action - exceptions are caught to provide less intimidating error messaging.
    try:
        if args.extract:
            extract(args.image, args.directory)
            print("Successfully extracted wavetables from {} and put them in {}.".format(args.image, args.directory))
        elif args.patch:
            patch(args.directory, args.image)
            print("Successfully patched {} with wavetables found in {}.".format(args.image, args.directory))
        elif args.intelhex:
            derive_names(args.directory, is_prefixed=args.sortprefix)
            print("Derived names and waves from {} and wrote them to names.hex and waves.hex.".format(args.directory, ))
    except (SSPatcherError, IOError) as e:
        log.error(e)
