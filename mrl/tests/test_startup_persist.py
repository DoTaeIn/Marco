import shutil
import struct
import subprocess
import tempfile
import unittest
import zlib
from pathlib import Path

from mrl.toolchain import build_c, find_compiler

ROOT = Path(__file__).parents[1]


@unittest.skipUnless(find_compiler()[0], "toolchain")
class StartupPersistTests(unittest.TestCase):
 def test_crc_matches_zlib_for_bytes_tails_splits_and_unaligned_input(self):
  with tempfile.TemporaryDirectory(prefix="mrl-persist-crc-") as directory:
   root = Path(directory)
   for name in ("knowledge_store.h", "knowledge_persist.h"):
    shutil.copyfile(ROOT / "runtime" / name, root / name)
   source, executable = root / "crc.c", root / "crc.exe"
   source.write_text(r'''
#include <stdio.h>
#include "knowledge_persist.h"
int main(void){
 unsigned char data[72];for(unsigned i=0;i<sizeof(data);i++)data[i]=(unsigned char)(i*73u+19u);
 for(unsigned byte=0;byte<256;byte++){unsigned char x=(unsigned char)byte;printf("B %u %08x\n",byte,mrl_knowledge_crc32(&x,1));}
 for(unsigned length=0;length<=64;length++)for(unsigned split=0;split<=length;split++){
  uint32_t state=mrl_knowledge_persist_crc_step(~0u,data+1,split);state=mrl_knowledge_persist_crc_step(state,data+1+split,length-split);
  printf("S %u %u %08x %08x\n",length,split,mrl_knowledge_crc32(data+1,length),~state);
 }return 0;
}''', encoding="utf-8")
   build_c(source, executable)
   result = subprocess.run([str(executable)], cwd=root, capture_output=True, text=True, check=True)
   data = bytes((index * 73 + 19) & 0xFF for index in range(72))
   for line in result.stdout.splitlines():
    kind, *fields = line.split()
    if kind == "B":
     value, got = int(fields[0]), int(fields[1], 16)
     self.assertEqual(got, zlib.crc32(bytes([value])) & 0xFFFFFFFF)
    else:
     length, split, full, incremental = (int(fields[0]), int(fields[1]), int(fields[2], 16), int(fields[3], 16))
     expected = zlib.crc32(data[1:1 + length]) & 0xFFFFFFFF
     self.assertEqual((full, incremental), (expected, expected), (length, split))

 def test_old_checkpoint_bytes_open_and_bad_rows_are_refused(self):
  with tempfile.TemporaryDirectory(prefix="mrl-persist-schema-") as directory:
   root = Path(directory)
   for name in ("knowledge_store.h", "knowledge_persist.h"):
    shutil.copyfile(ROOT / "runtime" / name, root / name)
   source, executable = root / "checkpoint.c", root / "checkpoint.exe"
   source.write_text(r'''
#include <string.h>
#include "knowledge_persist.h"
int main(int argc,char**argv){
 const char*error=0;MrlKnowledgeStore*s=mrl_knowledge_checkpoint_open(argv[1],8000000,UINT64_C(0x123456789abcdef0),&error);MrlKnowledgeFact row;
 if(!s||s->version!=17||s->next_id!=2||s->count!=1||!mrl_knowledge_store_get_fact(s,1,&row)||row.evidence!=1||row.start!=1||row.end!=2||mrl_knowledge_store_get_fact(s,2,&row)||strcmp(mrl_knowledge_store_symbol(s,5),"\360\237\231\202")){mrl_knowledge_store_release(s);return 1;}if(mrl_knowledge_checkpoint_save(s,"roundtrip.bin",UINT64_C(0x123456789abcdef0)))return 4;mrl_knowledge_store_release(s);
 for(int i=2;i<argc;i++){s=mrl_knowledge_checkpoint_open(argv[i],8000000,UINT64_C(0x123456789abcdef0),&error);if(s||!error){mrl_knowledge_store_release(s);return i;}}return 0;
}''', encoding="utf-8")
   build_c(source, executable)
   symbols = ["fact1", "fact2", "가", "knows", "🙂", "안🙂"]
   body = bytearray(b"MRLKCP01")
   body += struct.pack("<IQQIII", 1, 0x123456789ABCDEF0, 17, len(symbols), 2, 1)
   for text in symbols:
    encoded = text.encode("utf-8")
    body += struct.pack("<I", len(encoded)) + encoded
   body += struct.pack("<10I3B", 1, 1, 3, 4, 5, 1, 6, 5, 1, 2, 1, 0, 1)
   body += struct.pack("<10I3B", 2, 2, 3, 4, 5, 0, 0, 0, 0, 0, 0, 0, 0)
   checkpoint = bytes(body) + struct.pack("<I", zlib.crc32(body) & 0xFFFFFFFF)
   valid, corrupt, truncated = (root / name for name in ("valid.bin", "corrupt.bin", "truncated.bin"))
   valid.write_bytes(checkpoint)
   damaged = bytearray(checkpoint); damaged[20] ^= 1; corrupt.write_bytes(damaged)
   truncated.write_bytes(checkpoint[:-12])
   # Recompute the CRC for semantic corruption: checks must reach past checksums.
   extras = []
   for name, payload in [("trailing", bytes(body) + struct.pack("<I", zlib.crc32(body)) + b"x"),
                         ("bad_utf8", bytes(body).replace("가".encode(), b"\xff\xff\xff", 1)),
                         ("duplicate_symbol", bytes(body).replace(b"fact2", b"fact1", 1)),
                         ("bad_live", bytes(body[:-1]) + b"\x02")]:
    path = root / (name + ".bin")
    path.write_bytes(payload if name == "trailing" else payload + struct.pack("<I", zlib.crc32(payload)))
    extras.append(str(path))
   result = subprocess.run([str(executable), str(valid), str(corrupt), str(truncated), *extras], cwd=root, capture_output=True, text=True)
   self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
   self.assertEqual((root / "roundtrip.bin").read_bytes(), checkpoint)
   # A long fact ID crosses buffer boundaries, including inside UTF-8 sequences.
   long_id = ("🙂" * 40000).encode()
   large_body = bytes(body).replace(struct.pack("<I", 5) + b"fact1", struct.pack("<I", len(long_id)) + long_id, 1)
   large = large_body + struct.pack("<I", zlib.crc32(large_body))
   valid.write_bytes(large)
   result = subprocess.run([str(executable), str(valid), str(corrupt), str(truncated), *extras], cwd=root, capture_output=True, text=True)
   self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
   self.assertEqual((root / "roundtrip.bin").read_bytes(), large)



if __name__ == "__main__":
 unittest.main()
