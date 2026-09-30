import subprocess
import tempfile
import unittest
import sqlite3
from pathlib import Path

from mrl.toolchain import build_c


SOURCE = r'''#include "knowledge_indexed.h"
#include <stdio.h>
#include <string.h>
static int setup(MrlKnowledgeStore **sp, MrlKnowledgeSymbol *a, MrlKnowledgeSymbol *p, MrlKnowledgeSymbol *old, MrlKnowledgeSymbol *now) {
    MrlKnowledgeStore *s=mrl_knowledge_store_new(1u<<20); if(!s)return 0;
    if(!mrl_knowledge_store_intern(s,"alice",a)||!mrl_knowledge_store_intern(s,"likes",p)||!mrl_knowledge_store_intern(s,"tea",old)||!mrl_knowledge_store_intern(s,"coffee",now)){mrl_knowledge_store_release(s);return 0;}
    *sp=s;return 1;
}
int main(int argc,char **argv) {
    if(argc<3)return 10; const char *path=argv[1],*mode=argv[2]; MrlKnowledgeStore *s; MrlKnowledgeSymbol a,p,old,now;
    if(!setup(&s,&a,&p,&old,&now))return 11; MrlKnowledgeFact f={1,a,a,p,old,0,0,0,1,0,0,0,0,0,0};
    if(strcmp(mode,"build")==0){if(!mrl_knowledge_store_append(s,f,1)){mrl_knowledge_store_release(s);return 12;}const char *e=mrl_knowledge_indexed_build(s,path,41);mrl_knowledge_store_release(s);return e?12:0;}
    MrlKnowledgeIndexed ix={0}; const char *e=mrl_knowledge_indexed_open(&ix,path,NULL,41); if(e){mrl_knowledge_store_release(s);return 13;}
    if(strcmp(mode,"append")==0){MrlKnowledgeIndexedRuleDelta r={99,1,7,"rule",4};f.object=now;e=mrl_knowledge_indexed_append(&ix,2,NULL,0,&f,1,&r);mrl_knowledge_indexed_close(&ix);mrl_knowledge_store_release(s);return e?14:0;}
    MrlKnowledgeFact out={0}; int ok=mrl_knowledge_indexed_find(&ix,"alice","likes",strcmp(mode,"updated")==0?"coffee":"tea",&out); MrlKnowledgeIndexedStats z=mrl_knowledge_indexed_stats(&ix);
    printf("ok=%d object=%u rows=%llu bytes=%llu vm=%llu fullscan=%llu rules=%llu\n",ok,out.object,(unsigned long long)z.rows_read,(unsigned long long)z.bytes_read,(unsigned long long)z.vm_steps,(unsigned long long)z.fullscan_steps,(unsigned long long)mrl_knowledge_indexed_rule_generation(&ix));
    mrl_knowledge_indexed_close(&ix);mrl_knowledge_store_release(s);return ok?0:15;
}
'''


class IndexedStorageTests(unittest.TestCase):
    def test_build_selective_append_correction_and_reopen(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            for name in ("knowledge_store.h", "knowledge_indexed.h"):
                (root / name).write_bytes((Path(__file__).parents[1] / "runtime" / name).read_bytes())
            source = root / "indexed.c"
            source.write_text(SOURCE)
            exe = root / "indexed.exe"
            build_c(source, exe, optimization="debug")
            db = root / "knowledge.db"
            def run(mode):
                return subprocess.run([str(exe), str(db), mode], capture_output=True, text=True, check=False)
            self.assertEqual(run("build").returncode, 0)
            first = run("first")
            self.assertEqual(first.returncode, 0, first.stdout + first.stderr)
            self.assertIn("object=3", first.stdout)
            self.assertIn("rows=1", first.stdout)
            self.assertEqual(run("append").returncode, 0)
            updated = run("updated")
            self.assertEqual(updated.returncode, 0, updated.stdout + updated.stderr)
            self.assertIn("object=4", updated.stdout)
            self.assertIn("rules=1", updated.stdout)

    def test_fingerprint_rejects_wrong_base(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            for name in ("knowledge_store.h", "knowledge_indexed.h"):
                (root / name).write_bytes((Path(__file__).parents[1] / "runtime" / name).read_bytes())
            source = root / "indexed.c"
            source.write_text(SOURCE.replace('mrl_knowledge_indexed_open(&ix,path,NULL,41)', 'mrl_knowledge_indexed_open(&ix,path,NULL,99)'))
            exe = root / "indexed.exe"
            build_c(source, exe, optimization="debug")
            db = root / "knowledge.db"
            self.assertEqual(subprocess.run([str(exe), str(db), "build"], check=False).returncode, 0)
            self.assertEqual(subprocess.run([str(exe), str(db), "first"], check=False).returncode, 13)

    def test_source_wrapper_errors_are_distinct_and_atomic(self):
        wrapper = r'''#include "knowledge_indexed.h"
#include <stdio.h>
int main(int ac,char**av){const char*p=av[1];if(!strcmp(av[2],"missing")){MrlIndexedResult r=mrl_indexed_exists(p,"a","p","o");printf("%d %d %s\n",r.ok,r.value,r.error?r.error:"ok");return 0;}if(!strcmp(av[2],"rawmissing")){MrlKnowledgeIndexed ix={0};const char*e=mrl_knowledge_indexed_open(&ix,p,NULL,MRL_INDEXED_ASSERTION_FINGERPRINT);printf("%s\n",e?e:"unexpected");if(!e)mrl_knowledge_indexed_close(&ix);return 0;}MrlKnowledgeStore*s=mrl_knowledge_store_new(1<<20);MrlKnowledgeSymbol id,a,pr,o;if(!s||!mrl_knowledge_store_intern(s,"fact",&id)||!mrl_knowledge_store_intern(s,"a",&a)||!mrl_knowledge_store_intern(s,"p",&pr)||!mrl_knowledge_store_intern(s,"o",&o))return 2;MrlKnowledgeFact f={0,id,a,pr,o,0,1,0,1,0,0,0,0,0,0};if(!mrl_knowledge_store_append(s,f,1))return 3;MrlIndexedResult r;if(!strcmp(av[2],"save"))r=mrl_indexed_save(s,p);else if(!strcmp(av[2],"badadd"))r=mrl_indexed_add(p,"broken","a","p",NULL,1);else if(!strcmp(av[2],"tampered"))r=mrl_indexed_exists(p,"tampered","p","o");else r=mrl_indexed_exists(p,"a","p","o");printf("%d %d %s\n",r.ok,r.value,r.error?r.error:"ok");mrl_knowledge_store_release(s);return 0;}'''
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            for name in ("knowledge_store.h", "knowledge_indexed.h"):
                (root / name).write_bytes((Path(__file__).parents[1] / "runtime" / name).read_bytes())
            source, exe = root / "wrapper.c", root / "wrapper.exe"
            source.write_text(wrapper)
            build_c(source, exe, optimization="debug")
            db = root / "wrapper.db"
            missing = subprocess.run([str(exe), str(db), "missing"], capture_output=True, text=True, check=False)
            self.assertIn("0 0 indexed database missing", missing.stdout)
            self.assertFalse(db.exists())
            raw_missing = root / "raw-missing.db"
            raw = subprocess.run([str(exe), str(raw_missing), "rawmissing"], capture_output=True, text=True, check=False)
            self.assertIn("indexed open", raw.stdout)
            self.assertFalse(raw_missing.exists())
            self.assertEqual(subprocess.run([str(exe), str(db), "save"], check=False).returncode, 0)
            again = subprocess.run([str(exe), str(db), "save"], capture_output=True, text=True, check=False)
            self.assertIn("0 0 indexed path already exists", again.stdout)
            bad = subprocess.run([str(exe), str(db), "badadd"], capture_output=True, text=True, check=False)
            self.assertIn("0 0 indexed symbols", bad.stdout)
            unrelated = root / "unrelated.db"
            con = sqlite3.connect(unrelated)
            con.execute("CREATE TABLE unrelated(value TEXT)")
            con.commit()
            con.close()
            before = unrelated.read_bytes()
            rejected = subprocess.run([str(exe), str(unrelated), "query"], capture_output=True, text=True, check=False)
            self.assertIn("indexed metadata", rejected.stdout)
            self.assertEqual(before, unrelated.read_bytes())
            text_db = root / "text.db"
            self.assertEqual(subprocess.run([str(exe), str(text_db), "save"], check=False).returncode, 0)
            con = sqlite3.connect(text_db)
            con.execute("UPDATE mrl_facts SET subject_text='tampered'")
            con.commit()
            con.close()
            text_corrupt = subprocess.run([str(exe), str(text_db), "tampered"], capture_output=True, text=True, check=False)
            self.assertIn("0 0 indexed row corruption", text_corrupt.stdout)
            con = sqlite3.connect(db)
            con.execute("UPDATE mrl_facts SET row_crc=row_crc+1")
            con.commit()
            con.close()
            corrupt = subprocess.run([str(exe), str(db), "query"], capture_output=True, text=True, check=False)
            self.assertIn("0 0 indexed row corruption", corrupt.stdout)

    def test_utf8_database_path(self):
        wrapper = r'''#include "knowledge_indexed.h"
#include <stdio.h>
int main(int ac,char**av){char path[512];snprintf(path,sizeof(path),"%s/지식🙂.db",av[1]);MrlKnowledgeStore*s=mrl_knowledge_store_new(1<<20);MrlKnowledgeSymbol id,a,p,o;if(!s||!mrl_knowledge_store_intern(s,"fact",&id)||!mrl_knowledge_store_intern(s,"a",&a)||!mrl_knowledge_store_intern(s,"p",&p)||!mrl_knowledge_store_intern(s,"o",&o))return 2;MrlKnowledgeFact f={0,id,a,p,o,0,1,0,1,0,0,0,0,0,0};if(!mrl_knowledge_store_append(s,f,1))return 3;MrlIndexedResult r=mrl_indexed_save(s,path),q=mrl_indexed_exists(path,"a","p","o"),again=mrl_indexed_save(s,path);mrl_knowledge_store_release(s);return r.ok&&q.ok&&q.value&&!again.ok?0:4;}'''
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            for name in ("knowledge_store.h", "knowledge_indexed.h"):
                (root / name).write_bytes((Path(__file__).parents[1] / "runtime" / name).read_bytes())
            source, exe = root / "unicode.c", root / "unicode.exe"
            source.write_text(wrapper, encoding="utf-8")
            build_c(source, exe, optimization="debug")
            self.assertEqual(subprocess.run([str(exe), str(root)], check=False).returncode, 0)
            self.assertTrue((root / "지식🙂.db").exists())

    def test_stale_open_handle_cannot_overwrite_newer_commit(self):
        source_text = r'''#include "knowledge_indexed.h"
#include <stdio.h>
int main(int ac,char**av){MrlKnowledgeStore*s=mrl_knowledge_store_new(1<<20);MrlKnowledgeSymbol id,a,p,o;if(!s||!mrl_knowledge_store_intern(s,"seed",&id)||!mrl_knowledge_store_intern(s,"a",&a)||!mrl_knowledge_store_intern(s,"p",&p)||!mrl_knowledge_store_intern(s,"o",&o))return 2;MrlKnowledgeFact seed={0,id,a,p,o,0,1,0,1,0,0,0,0,0,0};if(!mrl_knowledge_store_append(s,seed,1))return 3;const char*e=mrl_knowledge_indexed_build(s,av[1],55);if(e)return 4;MrlKnowledgeIndexed x={0},y={0};if((e=mrl_knowledge_indexed_open(&x,av[1],0,55))||(e=mrl_knowledge_indexed_open(&y,av[1],0,55)))return 5;MrlKnowledgeFact first={2,id,a,p,o,0,1,0,1,0,0,0,0,0,0},second={3,id,a,p,o,0,1,0,1,0,0,0,0,0,0};if(mrl_knowledge_indexed_append(&x,2,0,0,&first,1,0))return 6;e=mrl_knowledge_indexed_append(&y,2,0,0,&second,1,0);if(!e||strcmp(e,"indexed stale version"))return 7;mrl_knowledge_indexed_close(&x);mrl_knowledge_indexed_close(&y);if((e=mrl_knowledge_indexed_open(&x,av[1],0,55)))return 8;MrlKnowledgeFact out;if(!mrl_knowledge_indexed_find(&x,"a","p","o",&out)||out.fact_id!=2)return 9;mrl_knowledge_indexed_close(&x);mrl_knowledge_store_release(s);return 0;}'''
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            for name in ("knowledge_store.h", "knowledge_indexed.h"):
                (root / name).write_bytes((Path(__file__).parents[1] / "runtime" / name).read_bytes())
            source, exe = root / "stale.c", root / "stale.exe"
            source.write_text(source_text)
            build_c(source, exe, optimization="debug")
            self.assertEqual(subprocess.run([str(exe), str(root / "stale.db")], check=False).returncode, 0)

    def test_symbol_id_conflict_rolls_back(self):
        source_text = r'''#include "knowledge_indexed.h"
int main(int ac,char**av){MrlKnowledgeStore*s=mrl_knowledge_store_new(1<<20);MrlKnowledgeSymbol id,a,p,o;if(!s||!mrl_knowledge_store_intern(s,"seed",&id)||!mrl_knowledge_store_intern(s,"a",&a)||!mrl_knowledge_store_intern(s,"p",&p)||!mrl_knowledge_store_intern(s,"o",&o))return 2;MrlKnowledgeFact seed={0,id,a,p,o,0,1,0,1,0,0,0,0,0,0};if(!mrl_knowledge_store_append(s,seed,1)||mrl_knowledge_indexed_build(s,av[1],66))return 3;MrlKnowledgeIndexed ix={0};if(mrl_knowledge_indexed_open(&ix,av[1],0,66))return 4;MrlKnowledgeIndexedSymbol bad={a,"different"};MrlKnowledgeFact row={2,id,a,p,o,0,1,0,1,0,0,0,0,0,0};if(mrl_knowledge_indexed_append(&ix,2,&bad,1,&row,1,0)){}else return 5;mrl_knowledge_indexed_close(&ix);if(mrl_knowledge_indexed_open(&ix,av[1],0,66))return 6;MrlKnowledgeFact out;if(!mrl_knowledge_indexed_find(&ix,"a","p","o",&out)||out.fact_id!=1)return 7;mrl_knowledge_indexed_close(&ix);mrl_knowledge_store_release(s);return 0;}'''
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            for name in ("knowledge_store.h", "knowledge_indexed.h"):
                (root / name).write_bytes((Path(__file__).parents[1] / "runtime" / name).read_bytes())
            source, exe = root / "conflict.c", root / "conflict.exe"
            source.write_text(source_text)
            build_c(source, exe, optimization="debug")
            self.assertEqual(subprocess.run([str(exe), str(root / "conflict.db")], check=False).returncode, 0)


if __name__ == "__main__":
    unittest.main()
