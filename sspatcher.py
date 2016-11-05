import argparse
import itertools
import logging
import os
import string


# Constants describing the image file and format of the wavetable data.
IMAGE_SIZE = 0x1FFFFF
NUM_WT = 128
WT_NAME_OFFSET = 0x0F0000
WT_NAME_LENGTH = 8
WT_NAME_PREFIX = b'  '
WT_USER_NAME_LENGTH = WT_NAME_LENGTH - len(WT_NAME_PREFIX)
ALLOWED_CHARS = string.ascii_letters + string.digits + ' '  # characters allowed in wt names
WT_DATA_OFFSET = 0x100000
WT_DATA_LENGTH = 1024*8  # 512 16 bit unsigned ints per wave, 8 waves per table

# Consecutive identical values permitted in the wavetable audio data. This particular value is chosen because a
# couple waves in a row with a static value are conceivably useful.
RUN_LIMIT = WT_DATA_LENGTH // 4


class SSPatcherError(Exception):

    def __init__(self, *args, run_length=None):
        # For testing convenience, allow for a run length to be attached when a excessive run of consecutive values is
        # found in the audio data.
        self.run_length = run_length
        super().__init__(self, *args)


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
            raise SSPatcherError(
                'Found a run of {0} characters ({1}); wavetable data looks invalid.'.format(length, byte),
                run_length=length
            )
    return [wt_data_block[i:i + WT_DATA_LENGTH] for i in range(0, data_block_length, WT_DATA_LENGTH)]


def write_wavetables_to_files(names, wavetables, path):
    """Write wavetable audio data to raw audio files.

    :param names: List of bytes containing names to use, as extracted from the shapeshifter rom image.
    :param wavetables: List of bytes containing the wavetable audio data, as extracted from the shapeshifter rom image.
    :param path: String path to the directory where the files will be placed.
    """
    if len(names) != len(wavetables):
        raise SSPatcherError(
            'When writing wavetable files, length of names and wavetables did not match (names:{}, tables:{}).'.format(
                len(names), len(wavetables)
            )
        )
    for name, table in zip(names, wavetables):
        with open("{}/{}.raw".format(path, name.decode()), 'wb') as f:
            f.write(table)


def write_wavetables_to_image():
    pass


def write_names_to_image():
    pass


def extract(filename, destination):
    """Extract wavetables from a file containing the shapeshifter ROM image and write them to individual files.

    :param filename: String path to the shapeshifter rom image.
    :param destination: String path to the directory to put the individual wavetable files in.
    """
    if os.path.exists(destination):
        raise SSPatcherError("{} already exists; aborting so existing data isn't overwritten.".format(destination))
    else:
        os.mkdir(destination)
    with open(filename, 'rb') as f:
        names = read_wt_names(f)
        tables = read_wt_data(f)
        write_wavetables_to_files(names, tables, destination)


if __name__ == '__main__':
    # Setup logging for error reporting.
    log = logging.getLogger('sspatcher')
    log.setLevel(logging.WARNING)
    handler = logging.StreamHandler()
    handler.setFormatter(logging.Formatter('%(levelname)s: %(message)s'))
    log.addHandler(handler)

    # Configure and run argparse.
    parser = argparse.ArgumentParser()
    parser.add_argument('image', help='Name of the Shapeshifter EEPROM image file.')
    parser.add_argument(
        'directory',
        help="Directory where extracted wavetable data will be written. If it doesn't exist, it will be created. "
             "Default: %(default)s",
        default='sstables'
    )
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument('-e', '--extract', help='Extract wavetables from the image.', action='store_true')
    group.add_argument('-p', '--patch', help='Patch the image file with new wavetables.', action='store_true')
    args = parser.parse_args()
    
    # Perform the user's requested action.
    if args.extract:
            extract(args.image, args.directory)
    elif args.patch:
        pass
