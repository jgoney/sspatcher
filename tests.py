import functools
import itertools
import os
import random
import shutil
import sspatcher
import string
import unittest


# Constants for locations of test data
TEMP_DIRECTORY = 'test_tables'
READ_TEST_LOCATION = 'test_read'
REAL_TEST_IMAGE_PATH = 'shapeshifter_test.bin'


class TestReadWTData(unittest.TestCase):
    """Tests for read_wt_data."""

    def setUp(self):
        self.old_name_offset = sspatcher.WT_NAME_OFFSET
        self.old_data_offset = sspatcher.WT_DATA_OFFSET
        self.test_image = open(REAL_TEST_IMAGE_PATH, 'rb')

    def tearDown(self):
        sspatcher.WT_NAME_OFFSET = self.old_name_offset
        sspatcher.WT_DATA_OFFSET = self.old_data_offset
        self.test_image.close()

    def test_exceptions_from_known_bad_data_locations(self):
        """Correct exceptions are raised when reading audio data from locations known to cause them."""
        sspatcher.WT_DATA_OFFSET = 0x0AF6B0  # First offset in factory image with long runs of identical bytes
        with self.assertRaisesRegex(
                sspatcher.SSPatcherError,
                'Found a run of .+ characters .+; wavetable data looks invalid\.',
                msg="Read from known location where audio data doesn't exist didn't raise SSPatcherError."
        ):
            sspatcher.read_wt_data(self.test_image)

        sspatcher.WT_DATA_OFFSET = sspatcher.IMAGE_SIZE - 64
        with self.assertRaisesRegex(
                sspatcher.SSPatcherError,
                'Got less than .+ bytes when reading wavetable audio data\.',
                msg="Read from known location where insufficient audio data can be read didn't raise SSPatcherError."
        ):
            sspatcher.read_wt_data(self.test_image)

    def test_various_bad_data_locations(self):
        """SSPatcherError is raised when reading audio data from various invalid locations.

        This test is a little fuzzy since the determination of whether valid audio data was found is itself inexact.
        """
        # Since checking for invalid audio data involves looking for runs of consecutive values deemed too long
        # the locations immediately preceding the valid audio data in the image cause false positives. So, those
        # locations will be skipped in the test.
        first_false_positive_location = 0xFF800
        passed = False
        i = 0
        while i < sspatcher.IMAGE_SIZE:
            # +1 here to include the known valid audio data location in what is skipped.
            if i not in range(first_false_positive_location, self.old_data_offset + 1):
                sspatcher.WT_DATA_OFFSET = i
                try:
                    sspatcher.read_wt_data(self.test_image)
                except sspatcher.SSPatcherError as exception:
                    try:
                        run_length = exception.args[1]
                        if run_length is not None:
                            # If a run is found, we know we can skip ahead at least the length of the run. The test is
                            # very slow if this isn't done since the audio data is ~1 megabyte.
                            # -1 here because it will be added back later; avoids having a bunch of else branches to
                            # add 1.
                            i += run_length - sspatcher.RUN_LIMIT - 1
                    except IndexError:  # Exception wasn't due to a long run of identical values
                        pass
                    if exception.args[0].startswith('Got less than'):
                        # Too close to the end of the file to read enough data, which will also be true for the
                        # remaining locations, so end the test here.
                        passed = True
                        break
            i += 1
        self.assertEqual(passed, True)

    def test_good_data_location(self):
        """Something that looks like good audio data is extracted from the factory image."""
        # It might be nice to check that the extracted waves match some reference file, but we don't have that for
        # the factory waves, so just make sure we got the right number of wavetables and that they are the right size.
        wavetables = sspatcher.read_wt_data(self.test_image)
        self.assertEqual(len(wavetables), sspatcher.NUM_WT)
        for wavetable in wavetables:
            self.assertEqual(len(wavetable), sspatcher.WT_DATA_LENGTH)


class TestReadWTNames(unittest.TestCase):
    """Tests for read_wt_names."""
    def setUp(self):
        self.old_name_offset = sspatcher.WT_NAME_OFFSET
        self.old_data_offset = sspatcher.WT_DATA_OFFSET
        self.test_image = open(REAL_TEST_IMAGE_PATH, 'rb')

    def tearDown(self):
        sspatcher.WT_NAME_OFFSET = self.old_name_offset
        sspatcher.WT_DATA_OFFSET = self.old_data_offset
        self.test_image.close()

    def test_exceptions_from_known_bad_name_locations(self):
        """Correct exceptions are raised when reading names from locations known to cause them."""
        sspatcher.WT_NAME_OFFSET = 0
        with self.assertRaisesRegex(
                sspatcher.SSPatcherError,
                'Found wavetable name .+ without valid prefix\.',
                msg="Read from known location where names don't exist didn't raise SSPatcherError."
        ):
            sspatcher.read_wt_names(self.test_image)

        sspatcher.WT_NAME_OFFSET = sspatcher.IMAGE_SIZE - 64
        with self.assertRaisesRegex(
                sspatcher.SSPatcherError,
                'Got less than .+ bytes when reading wavetable names\.',
                msg="Read from known location where insufficient name data can be read didn't raise SSPatcherError."
        ):
            sspatcher.read_wt_names(self.test_image)

    def test_all_bad_name_locations(self):
        """SSPatcherError is raised when reading from everywhere except the location of the wavetable names.

        This test is expected to take a few minutes to run since it tries to read from every possible location.
        """
        for i in range(0, sspatcher.IMAGE_SIZE):
            if i != self.old_name_offset:
                sspatcher.WT_NAME_OFFSET = i
                with self.assertRaises(
                        sspatcher.SSPatcherError,
                        msg='Read names from location {:X} did not raise an SSPatcherError.'.format(i)
                ):
                    sspatcher.read_wt_names(self.test_image)

    def test_good_name_location(self):
        """Expected wavetable names are extracted from the factory image."""
        # List of factory wavetable names. First copied from the Shapeshifter manual, then adjusted to the names
        # actually present in the factory image which use a couple different styles of padding with spaces to
        # make all names exactly 8 characters.
        factory_names = [
            b"Basic1", b"Basic2", b"BasRec", b"BiPuls", b"BitCr1", b"BitCr2", b"BitCr3", b"BitCr4",
            b"Buzzer", b"Cello1", b"Cello2", b"Chip 1", b"Chip 2", b"Chip 3", b"Chip 4", b"Chip 5",
            b"Chip 6", b"Chirp1", b"Chirp2", b"Chirp3", b"Chirp4", b"Chirp5", b"Chirp6", b"Chirp7",
            b"Chirp8", b"Chirp9", b"Chrp10", b"Chrp11", b"Chrp12", b"Chrp13", b"Chrp14", b"Chrp15",
            b"Chrp16", b"Chrp17", b"Chrp18", b"Chrp19", b"Chrp20", b"Clrnet", b" Clav1", b" Clav2",
            b"Dstrt1", b"Dstrt2", b"Dstrt3", b"eBass1", b"eBass2", b"eBass3", b"eBass4", b"ePian1",
            b"ePian2", b"ePian3", b"ePian4", b"ePian5", b"Flute1", b"GapSaw", b"Grain1", b"Grain2",
            b"Grain3", b"Gitar1", b"Gitar2", b"Gitar3", b"Gitar4", b"Harmo1", b"Harmo2", b"Harmo3",
            b"  LFO1", b"  LFO2", b"  LFO3", b"  LFO4", b"  LFO5", b"  LFO6", b"  LFO7", b"  LFO8",
            b"  LFO9", b" LFO10", b" LFO11", b" LFO12", b" LFO13", b" LFO14", b" LFO15", b" LFO16",
            b" LFO17", b" LFO18", b" LFO19", b" LFO20", b" LFO21", b" Misc1", b" Misc2", b" Misc3",
            b" Misc4", b"Noise1", b"Noise2", b"Noise3", b"Noise4", b"Noise5", b"Noise6", b" Oboes",
            b"Ovrto1", b"Ovrto2", b"Raw  1", b"Raw  2", b"Raw  3", b"ResPls", b"ResSaw", b"ResSqu",
            b"Saxoph", b"Symmtr", b"Thrmin", b"2Tone1", b"2Tone2", b"2Tone3", b"2Tone4", b"2Tone5",
            b"2Tone6", b"2Tone7", b"2Tone8", b"2Tone9", b"VidGm1", b"VidGm2", b"VidGm3", b"VidGm4",
            b"Violin", b"Vocal1", b"Vocal2", b"Vocal3", b"Vocal4", b"Vocal5", b"Vocal6", b"Vocal7"
        ]
        names = sspatcher.read_wt_names(self.test_image)
        self.assertEqual(len(names), sspatcher.NUM_WT)
        for i, name in enumerate(factory_names):
            self.assertEqual(names[i], name)


class TestReadWavetablesFromFiles(unittest.TestCase):
    """Tests for read_wavetables_from_files."""

    def setUp(self):
        self.test_image = open(REAL_TEST_IMAGE_PATH, 'rb')
        os.mkdir(TEMP_DIRECTORY)

    def tearDown(self):
        self.test_image.close()
        shutil.rmtree(TEMP_DIRECTORY)

    def test_read(self):
        """Read of factory wavetables works and matches data extracted from factory rom image."""
        image_names = sspatcher.read_wt_names(self.test_image)
        image_tables = sspatcher.read_wt_data(self.test_image)
        wavetables = sspatcher.read_wavetables_from_files(READ_TEST_LOCATION)
        self.assertEquals(len(wavetables.keys()), len(image_names))
        self.assertEquals(len(wavetables.values()), len(image_tables))
        for name, table in wavetables.items():
            self.assertIn(name, image_names)
            self.assertIn(table, image_tables)

    def test_nonexistent_directory(self):
        """Trying to read from a nonexistent directory raises SSPatcherError."""
        with self.assertRaisesRegex(sspatcher.SSPatcherError, "doesn't exist or isn't a directory"):
            sspatcher.read_wavetables_from_files("ajsdhfkjbvkjqebnqg")

    def test_wrong_size(self):
        """If a file in the directory doesn't have the proper length of audio data, SSPatcherError is raised.

        Due to a random component in the length of the data written to each file, this test could potentially fail
        sometimes and succeed other times. But this is unlikely, and the random component helps ensure that a variety
        of bad lengths are tested even though it's impossible to test every possible bad length.
        """
        # Make some fake wavetable files containing random data.
        for i in range(sspatcher.NUM_WT):
            with open(os.path.join(TEMP_DIRECTORY, 'wt{}'.format(i)), 'wb') as f:
                f.write(os.urandom(sspatcher.WT_DATA_LENGTH))
        # Overwrite each file in turn with an incorrect length of data.
        for i in range(sspatcher.NUM_WT):
            length = sspatcher.WT_DATA_LENGTH
            with open(os.path.join(TEMP_DIRECTORY, 'wt{}'.format(i)), 'wb') as f:
                while length == sspatcher.WT_DATA_LENGTH:
                    # Twice the expected audio data size to get a roughly even distribution of too short and too long.
                    length = random.randrange(sspatcher.WT_DATA_LENGTH * 2)
                f.write(os.urandom(length))
            with self.assertRaisesRegex(
                    sspatcher.SSPatcherError,
                    'wrong size \(expected {}, got {}\)'.format(sspatcher.WT_DATA_LENGTH, length)
            ):
                sspatcher.read_wavetables_from_files(TEMP_DIRECTORY)
            # Return the file to the expected length
            with open(os.path.join(TEMP_DIRECTORY, 'wt{}'.format(i)), 'wb') as f:
                f.seek(0)
                f.write(os.urandom(sspatcher.WT_DATA_LENGTH))

    def test_wrong_number_of_tables(self):
        """If there are too many or too few wavetables, SSPatcherError is raised."""
        # Could potentially test up to the OS's limit on the number of files in the directory but for the sake of
        # getting this done in a reasonable amount of time, twice as many as expected should be more than sufficient.
        filenames = ['wt{}'.format(i) for i in range(sspatcher.NUM_WT * 2)]
        for filename in filenames:
            with open(os.path.join(TEMP_DIRECTORY, filename), 'wb') as f:
                f.write(os.urandom(sspatcher.WT_DATA_LENGTH))
        # Eliminate the fake wavetable files one at a time and make sure SSPatcherError is raised except when the
        # correct number of files are present.
        # Zip/range instead of enumerate here to make this robust to possible changes in the number of files tested.
        for filename, files_left in zip(filenames, range(len(filenames) - 1, -1, -1)):
            os.remove(os.path.join(TEMP_DIRECTORY, filename))
            if files_left != sspatcher.NUM_WT:
                with self.assertRaisesRegex(
                    sspatcher.SSPatcherError,
                    'wrong number of wavetables \(expected {}, got {}\)'.format(sspatcher.NUM_WT, files_left)
                ):
                    sspatcher.read_wavetables_from_files(TEMP_DIRECTORY)

    def test_duplicate_names(self):
        """If there are some filenames that result in duplicate wavetable names, SSPatcherError is raised."""
        for i in range(sspatcher.NUM_WT):
            with open(os.path.join(TEMP_DIRECTORY, '{}wtwtwt'.format(i)), 'wb') as f:
                f.write(os.urandom(sspatcher.WT_DATA_LENGTH))
        with self.assertRaisesRegex(sspatcher.SSPatcherError, 'Duplicate name .+wtwtwt.+ in wavetable names'):
            sspatcher.read_wavetables_from_files(TEMP_DIRECTORY)


class TestCheckImageSize(unittest.TestCase):
    """Tests for check_image_size."""

    FAKE_IMAGE_PATH = "checkimage.bin"

    def test_valid_image(self):
        sspatcher.check_image_size(REAL_TEST_IMAGE_PATH)

    def test_invalid_images(self):
        fake_sizes = [sspatcher.IMAGE_SIZE + 1, sspatcher.IMAGE_SIZE - 1, 0, 1, 0x200000, 0x400000]
        self.addCleanup(functools.partial(os.remove, self.FAKE_IMAGE_PATH))
        for size in fake_sizes:
            with open(self.FAKE_IMAGE_PATH, 'wb') as f:
                f.write(os.urandom(size))
            self.assertRaisesRegex(
                sspatcher.SSPatcherError,
                'had unexpected size \(got {}, expected {}\).'.format(size, sspatcher.IMAGE_SIZE)
            )


class TestExtract(unittest.TestCase):
    """Tests for extract."""

    def setUp(self):
        self.test_image = open(REAL_TEST_IMAGE_PATH, 'rb')

    def tearDown(self):
        self.test_image.close()

    def test_extract(self):
        """Full extraction process works - names and data are read and files are written successfully.

        This is expected to fail if the names or wavetable data aren't successfully read from the image.
        """
        self.addCleanup(functools.partial(shutil.rmtree, TEMP_DIRECTORY))
        names = sspatcher.read_wt_names(self.test_image)
        tables = sspatcher.read_wt_data(self.test_image)
        sspatcher.extract(REAL_TEST_IMAGE_PATH, TEMP_DIRECTORY)
        filenames = os.listdir(TEMP_DIRECTORY)
        self.assertEquals(len(names), len(filenames))
        self.assertEquals(len(tables), len(filenames))
        for filename in filenames:
            name = filename[:sspatcher.WT_USER_NAME_LENGTH]
            self.assertIn(name.encode(), names)
            with open('{}/{}'.format(TEMP_DIRECTORY, filename), 'rb') as f:
                self.assertIn(f.read(), tables)

    def test_extract_doesnt_overwrite(self):
        """Full extraction fails if the destination directory already exists."""
        self.addCleanup(functools.partial(shutil.rmtree, TEMP_DIRECTORY))
        os.mkdir(TEMP_DIRECTORY)
        with self.assertRaisesRegex(sspatcher.SSPatcherError, 'already exists'):
            sspatcher.extract(REAL_TEST_IMAGE_PATH, TEMP_DIRECTORY)


class TestSanitizeName(unittest.TestCase):
    """Tests for sanitize_name."""

    def test_formatting(self):
        """Formatting of names that are too long or too short works as expected."""
        # Dictionary with input as keys and expected result as values
        test_data = {
            '1': b'     1',
            '22': b'    22',
            '333': b'   333',
            '4444': b'  4444',
            '55555': b' 55555',
            '666666': b'666666',
            'test 1': b'test 1',
            '': b'      ',
            ' ': b'      ',
            'verylongname': b'ngname'
        }
        for name, expected in test_data.items():
            self.assertEquals(sspatcher.sanitize_name(name), expected)

    def test_valid_chars(self):
        """All valid characters are accepted."""
        # This builds the list of valid characters to check the same way the constant does, so this should really
        # never fail unless something is horribly wrong or the constant changes.
        chars_to_check = string.ascii_letters + string.digits + ' '

        # Helper function to get chunks of characters from the string containing the allowed ones.
        def group(s, n):
            for item in itertools.zip_longest(*[iter(s)] * n, fillvalue=' '):
                yield ''.join(item)

        for name in group(chars_to_check, sspatcher.WT_USER_NAME_LENGTH):
            self.assertEquals(sspatcher.sanitize_name(name), name.encode())

    def test_invalid_chars(self):
        """All invalid characters are rejected."""
        max_unicode_char = 0x10FFFF
        for ch in (chr(i) for i in range(max_unicode_char + 1)):
            if ch not in sspatcher.ALLOWED_CHARS:
                with self.assertRaisesRegex(sspatcher.SSPatcherError, 'invalid character'):
                    sspatcher.sanitize_name(ch)


class TestPatch(unittest.TestCase):

    PATCHED_IMAGE_PATH = "patchedimage.bin"

    def test_success(self):
        """Verify that a copy of the rom image is patched using test data."""
        self.addCleanup(functools.partial(os.remove, self.PATCHED_IMAGE_PATH))
        self.addCleanup(functools.partial(shutil.rmtree, TEMP_DIRECTORY))
        os.mkdir(TEMP_DIRECTORY)
        # Generate some fake wavetables using random data
        for i in range(sspatcher.NUM_WT):
            with open(os.path.join(TEMP_DIRECTORY, 'wt{}.raw'.format(i)), 'wb') as f:
                f.write(os.urandom(sspatcher.WT_DATA_LENGTH))

        # Make a copy of the test imgae and patch it
        shutil.copyfile(REAL_TEST_IMAGE_PATH, self.PATCHED_IMAGE_PATH)
        sspatcher.patch(TEMP_DIRECTORY, self.PATCHED_IMAGE_PATH)

        # Verify that what we read from the ROM image is the same as what's in the test data.
        with open(self.PATCHED_IMAGE_PATH, 'rb') as f:
            names = sspatcher.read_wt_names(f)
            tables = sspatcher.read_wt_data(f)
        filenames = {os.path.splitext(name)[0].rjust(6).encode(): name for name in os.listdir(TEMP_DIRECTORY)}
        for name, table in zip(names, tables):
            self.assertIn(name, filenames.keys())
            with open(os.path.join(TEMP_DIRECTORY, filenames[name]), 'rb') as f:
                self.assertEqual(table, f.read())


if __name__ == '__main__':
    unittest.main()
