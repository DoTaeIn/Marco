import json
import subprocess
import tempfile
import unittest
from pathlib import Path

from mrl.horn_bridge import emit_v7_support
from mrl.toolchain import build_c, find_compiler


@unittest.skipUnless(find_compiler()[0], "toolchain")
class StartupJsonlTests(unittest.TestCase):
 def test_chunked_unicode_jsonl_and_rejection_boundaries(self):
  plan = {"facts": [{"id": "base", "triple": ["a", "p", "b"], "polarity": True,
                     "modality": "asserted", "evidence": {}}], "rules": [], "capacity": 8,
          "memory_budget": 8_000_000}
  tight = {**plan, "memory_budget": 65_536}
  support = emit_v7_support([plan, tight])
  with tempfile.TemporaryDirectory(prefix="mrl-startup-jsonl-") as directory:
   root = Path(directory)
   def record(identifier, obj):
    return json.dumps({"id": identifier, "subject": "한", "predicate": "p", "object": obj},
                      ensure_ascii=False, separators=(",", ":")).encode("utf-8")
   long = record("long", "가" * 25_000 + "🙂")
   duplicate = record("dup", "가" * 25_000) + b"\n" + record("dup", "o")
   bad_utf8 = long + b"\n{\"id\":\"bad\",\"subject\":\"\xff\",\"predicate\":\"p\",\"object\":\"o\"}"
   (root / "long.jsonl").write_bytes(long)  # Deliberately has no trailing newline.
   (root / "duplicate.jsonl").write_bytes(duplicate)
   (root / "nul.jsonl").write_bytes(long + b"\0")
   (root / "bad-utf8.jsonl").write_bytes(bad_utf8)
   (root / "huge.jsonl").write_bytes(record("huge", "x" * (1024 * 1024)))
   source, executable = root / "jsonl.c", root / "jsonl.exe"
   source.write_text("#include <stdlib.h>\nstatic void mrl_runtime_fail(const char*message){(void)message;abort();}\n" + support + r'''
int main(void){
 MrlHornPlan *p=mrl_horn_plan_new(&mrl_horn_plan_0),*q=mrl_horn_plan_new(&mrl_horn_plan_0),*tiny=mrl_horn_plan_new(&mrl_horn_plan_1);MrlHornJsonBatch batch;MrlHornLoadResult result;size_t facts=q->store->count;uint64_t version=q->store->version;uint32_t symbols=q->store->symbols->next;
 batch=mrl_horn_jsonl_load("long.jsonl",2000000,4);if(batch.error||batch.count!=1||strlen(batch.facts[0].object)<=65536)return 1;mrl_horn_jsonl_free(&batch);
 result=mrl_horn_plan_load(&p,"long.jsonl");if(!result.ok||result.value!=1||p->store->count!=2)return 2;
 batch=mrl_horn_jsonl_load("nul.jsonl",2000000,4);if(!batch.error||batch.count)return 3;mrl_horn_jsonl_free(&batch);
 batch=mrl_horn_jsonl_load("bad-utf8.jsonl",2000000,4);if(!batch.error||batch.count)return 4;mrl_horn_jsonl_free(&batch);
 batch=mrl_horn_jsonl_load("duplicate.jsonl",2000000,4);if(!batch.error||batch.count)return 5;mrl_horn_jsonl_free(&batch);
 result=mrl_horn_plan_load(&q,"duplicate.jsonl");if(result.ok||q->store->count!=facts||q->store->version!=version||q->store->symbols->next!=symbols||mrl_knowledge_store_find_symbol(q->store,"dup"))return 6;
 result=mrl_horn_plan_load(&q,"huge.jsonl");if(result.ok||q->store->count!=facts||q->store->version!=version||q->store->symbols->next!=symbols)return 7;
 result=mrl_horn_plan_load(&tiny,"long.jsonl");if(result.ok||tiny->store->count!=1)return 8;
 mrl_horn_plan_release(p);mrl_horn_plan_release(q);mrl_horn_plan_release(tiny);return 0;
}''', encoding="utf-8")
   try:
    build_c(source, executable)
   except subprocess.CalledProcessError as error:
    self.fail(error.stderr.decode(errors="replace"))
   result = subprocess.run([str(executable)], cwd=root, capture_output=True, text=True)
   self.assertEqual(result.returncode, 0, result.stdout + result.stderr)


if __name__ == "__main__":
 unittest.main()
