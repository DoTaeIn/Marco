import tempfile
import unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from unittest import mock

from mrl import toolchain


class ToolchainCacheIsolationTests(unittest.TestCase):
    def test_concurrent_builds_receive_private_zig_local_caches(self):
        with tempfile.TemporaryDirectory(prefix="mrl-toolchain-") as directory:
            root = Path(directory)
            sources = []
            for index in range(4):
                source = root / f"source{index}.c"
                source.write_text("int main(void){return 0;}\n", encoding="utf-8")
                sources.append((source, root / f"program{index}.exe"))
            local_caches = set()

            def fake_run(args, *, env, **kwargs):
                local_caches.add(env["ZIG_LOCAL_CACHE_DIR"])
                output = Path(args[args.index("-o") + 1])
                output.write_bytes(b"ok")
                return mock.DEFAULT

            with mock.patch.object(toolchain, "_TOOLS", root / ".tools"), \
                 mock.patch.object(toolchain, "find_compiler", return_value=(["fakecc", "cc"], False)), \
                 mock.patch.object(toolchain.subprocess, "run", side_effect=fake_run):
                with ThreadPoolExecutor(max_workers=4) as pool:
                    list(pool.map(lambda pair: toolchain.build_c(*pair), sources))
            self.assertEqual(len(local_caches), 4)
            self.assertTrue(all(Path(cache).name.startswith("zig-local-") for cache in local_caches))

    @unittest.skipUnless(toolchain.find_compiler()[0], "no C11 compiler")
    def test_actual_concurrent_builds_complete(self):
        with tempfile.TemporaryDirectory(prefix="mrl-toolchain-real-") as directory:
            root = Path(directory)
            sources = []
            for index in range(4):
                source = root / f"source{index}.c"
                source.write_text(f"int main(void){{return {index};}}\n", encoding="utf-8")
                sources.append((source, root / f"program{index}.exe"))
            with ThreadPoolExecutor(max_workers=4) as pool:
                list(pool.map(lambda pair: toolchain.build_c(*pair), sources))
            self.assertTrue(all(output.is_file() and output.stat().st_size for _, output in sources))


if __name__ == "__main__":
    unittest.main()
