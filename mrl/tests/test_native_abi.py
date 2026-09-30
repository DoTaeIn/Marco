"""In-process ABI checks for the native Horn-runtime wire v2."""

import ctypes
import shutil
import struct
import subprocess
import tempfile
import unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from mrl import toolchain


MAGIC = 0x4D524C32
MALFORMED = 5
MAX_OUTPUT = 4 * (5 + 64 * (7 + 128 * 8))
SOURCE = Path(__file__).parents[1] / "runtime" / "native_graph.c"


def packet(subject=0):
    """A small closure input that derives one fact from one asserted fact."""
    words = [MAGIC, 1, 1, 1, 16, 8, 128]
    words += [subject, 1, 2, 1, 1]
    words += [-1, 1, -2]
    words += [-1, 3, -2]
    return struct.pack("<%di" % len(words), *words)


@unittest.skipUnless(toolchain.find_compiler()[0] is not None, "no C compiler available")
class NativeAbiTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        # Windows keeps a loaded DLL locked. Keep it below ignored mrl/.tools.
        native_root = Path(__file__).parents[1] / ".tools" / "native"
        native_root.mkdir(parents=True, exist_ok=True)
        root = Path(tempfile.mkdtemp(prefix="abi-", dir=native_root))
        source, cls.library = root / "native_graph.c", root / "native_graph.dll"
        shutil.copyfile(SOURCE, source)
        # A discoverable compiler that cannot build must fail this class.
        toolchain.build_shared(source, cls.library)
        cls.cli_directory = tempfile.TemporaryDirectory()
        cli_root = Path(cls.cli_directory.name)
        cli_source, cls.executable = cli_root / "native_graph.c", cli_root / "native_graph.exe"
        shutil.copyfile(SOURCE, cli_source)
        toolchain.build_c(cli_source, cls.executable)
        cls.abi_run = ctypes.CDLL(str(cls.library)).mrl_native_graph_run
        cls.abi_run.argtypes = [ctypes.POINTER(ctypes.c_uint8), ctypes.c_size_t,
                                ctypes.POINTER(ctypes.c_uint8), ctypes.c_size_t,
                                ctypes.POINTER(ctypes.c_size_t)]
        cls.abi_run.restype = ctypes.c_int

    @classmethod
    def tearDownClass(cls):
        cls.cli_directory.cleanup()

    @classmethod
    def invoke(cls, payload, capacity=MAX_OUTPUT):
        source = ((ctypes.c_uint8 * len(payload)).from_buffer_copy(payload)
                  if payload else None)
        output = (ctypes.c_uint8 * max(1, capacity))()
        written = ctypes.c_size_t(999)
        result = cls.abi_run(source, len(payload), output, capacity, ctypes.byref(written))
        return result, written.value, bytes(output[:written.value]) if result == 0 else b""

    def test_abi_matches_cli_for_success_and_malformed_wire(self):
        oversized = struct.pack("<7i", MAGIC, 1, 65, 0, 65, 1, 1) + b"\0" * 3000
        for payload in (packet(), b"\x00", oversized):
            with self.subTest(length=len(payload)):
                code, written, output = self.invoke(payload)
                self.assertEqual(code, 0)
                self.assertEqual(written, len(output))
                cli = subprocess.run([str(self.executable)], input=payload,
                                     capture_output=True, timeout=3, check=False)
                self.assertEqual(cli.returncode, 0)
                self.assertEqual(output, cli.stdout)
        self.assertEqual(struct.unpack("<i", self.invoke(b"\x00")[2])[0], MALFORMED)
        self.assertEqual(struct.unpack("<i", self.invoke(oversized)[2])[0], MALFORMED)

    def test_capacity_and_null_pointer_rules(self):
        code, written, _ = self.invoke(packet(), capacity=1)
        self.assertEqual((code, written), (1, 0))

        output = (ctypes.c_uint8 * MAX_OUTPUT)()
        written_value = ctypes.c_size_t(999)
        self.assertEqual(self.abi_run(None, 0, output, MAX_OUTPUT, ctypes.byref(written_value)), 0)
        self.assertEqual((written_value.value, struct.unpack("<i", bytes(output[:4]))[0]), (4, MALFORMED))

        source = (ctypes.c_uint8 * 1)(0)
        for args in ((None, 1, output, MAX_OUTPUT, ctypes.byref(written_value)),
                     (source, 1, None, MAX_OUTPUT, ctypes.byref(written_value)),
                     (source, 1, output, MAX_OUTPUT, None)):
            written_value.value = 999
            self.assertEqual(self.abi_run(*args), 2)
            if args[-1] is not None:
                self.assertEqual(written_value.value, 0)

    def test_output_capacity_never_overwrites_guard_bytes(self):
        _, needed, _ = self.invoke(packet())
        source = (ctypes.c_uint8 * len(packet())).from_buffer_copy(packet())
        for capacity in (0, 1, needed - 1, needed):
            with self.subTest(capacity=capacity):
                guarded = (ctypes.c_uint8 * (capacity + 2))()
                guarded[0], guarded[-1] = 0xA5, 0x5A
                written = ctypes.c_size_t(999)
                output = ctypes.cast(ctypes.byref(guarded, 1), ctypes.POINTER(ctypes.c_uint8))
                result = self.abi_run(source, len(packet()), output, capacity, ctypes.byref(written))
                self.assertEqual((guarded[0], guarded[-1]), (0xA5, 0x5A))
                if capacity < needed:
                    self.assertEqual((result, written.value), (1, 0))
                else:
                    self.assertEqual((result, written.value), (0, needed))

    def test_repeated_and_concurrent_calls_are_independent(self):
        expected = self.invoke(packet())
        self.assertEqual(expected[0], 0)
        for _ in range(8):
            self.assertEqual(self.invoke(packet()), expected)
        with ThreadPoolExecutor(max_workers=4) as pool:
            concurrent = list(pool.map(lambda subject: self.invoke(packet(subject)), range(16)))
        sequential = [self.invoke(packet(subject)) for subject in range(16)]
        self.assertEqual(concurrent, sequential)


if __name__ == "__main__":
    unittest.main()
