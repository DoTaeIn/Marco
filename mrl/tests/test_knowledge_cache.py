import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

from mrl.toolchain import build_c, find_compiler

ROOT = Path(__file__).parents[1]


@unittest.skipUnless(find_compiler()[0], "toolchain")
class KnowledgeCacheTests(unittest.TestCase):
    def test_cache_accepts_rederived_parent_in_later_tuple_slot(self):
        with tempfile.TemporaryDirectory(prefix="mrl-cache-cycle-") as directory:
            root = Path(directory)
            for name in ("knowledge_store.h", "knowledge_engine.h", "knowledge_persist.h", "knowledge_cache.h"):
                shutil.copyfile(ROOT / "runtime" / name, root / name)
            c, exe = root / "later.c", root / "later.exe"
            c.write_text(r'''#include "knowledge_cache.h"
int main(){int32_t body[]={-1,2,-2};MrlKnowledgeRule rules[]={{body,1,{-1,1,-2},7}};MrlKnowledgeStore*s=mrl_knowledge_store_new(1000000);MrlKnowledgeEngine e,loaded;MrlKnowledgeSymbol p,q,a,b;MrlKnowledgeFact f={0};
 if(!s||!mrl_knowledge_store_intern(s,"p",&p)||!mrl_knowledge_store_intern(s,"q",&q)||!mrl_knowledge_store_intern(s,"a",&a)||!mrl_knowledge_store_intern(s,"b",&b)||!mrl_knowledge_engine_init(&e,rules,1,10000))return 1;
 f=(MrlKnowledgeFact){.subject=a,.predicate=p,.object=b,.polarity=1};if(!mrl_knowledge_store_append(s,f,1)||!mrl_knowledge_assert(&e,1,a,p,b))return 2;f.predicate=q;if(!mrl_knowledge_store_append(s,f,1)||!mrl_knowledge_assert(&e,2,a,q,b)||!mrl_knowledge_close(&e))return 3;
 if(!mrl_knowledge_store_remove(s,1)||!mrl_knowledge_remove(&e,1)||!mrl_knowledge_close(&e)||!mrl_knowledge_has(&e,a,p,b)||e.facts[0].parents[0]!=1||mrl_knowledge_engine_cache_save(&e,s,"later.cache",9))return 4;
 if(!mrl_knowledge_engine_init(&loaded,rules,1,10000)||mrl_knowledge_engine_cache_load(&loaded,s,"later.cache",9)||!mrl_knowledge_has(&loaded,a,p,b)||!mrl_knowledge_remove(&loaded,2)||!mrl_knowledge_close(&loaded)||loaded.live_count)return 5;
 mrl_knowledge_engine_free(&loaded);mrl_knowledge_engine_free(&e);mrl_knowledge_store_release(s);return 0;}''', encoding="utf-8")
            build_c(c, exe)
            result = subprocess.run([str(exe)], cwd=root, capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_large_roundtrip_mutation_stale_and_corrupt_cache(self):
        with tempfile.TemporaryDirectory(prefix="mrl-cache-") as directory:
            root = Path(directory)
            for name in ("knowledge_store.h", "knowledge_engine.h", "knowledge_persist.h", "knowledge_cache.h"):
                shutil.copyfile(ROOT / "runtime" / name, root / name)
            c, exe = root / "cache.c", root / "cache.exe"
            c.write_text(r'''#include <stdio.h>
#include "knowledge_cache.h"
static int valid_corrupt(const char*path){FILE*f=fopen(path,"r+b");long n;unsigned char*b;uint32_t c;if(!f||fseek(f,0,SEEK_END)||(n=ftell(f))<96||fseek(f,0,SEEK_SET)||!(b=malloc((size_t)n))||fread(b,1,(size_t)n,f)!=(size_t)n){if(f)fclose(f);free(b);return 0;}b[92]=1;c=mrl_knowledge_crc32(b,(size_t)n-4);for(int i=0;i<4;i++)b[n-4+i]=(unsigned char)(c>>(8*i));if(fseek(f,0,SEEK_SET)||fwrite(b,1,(size_t)n,f)!=(size_t)n){fclose(f);free(b);return 0;}free(b);return fclose(f)==0;}
int main(){int32_t body[]={-1,1,-2};MrlKnowledgeRule rules[]={{body,1,{-1,2,-2},7}};MrlKnowledgeStore*s=mrl_knowledge_store_new(30000000),*clean;MrlKnowledgeEngine e,loaded,stale,broken;MrlKnowledgeSymbol p1,p2,subject,object;MrlKnowledgeFact f={0};FILE*file;
 if(!s||!mrl_knowledge_store_intern(s,"p1",&p1)||!mrl_knowledge_store_intern(s,"p2",&p2)||!mrl_knowledge_store_intern(s,"subject",&subject)||!mrl_knowledge_engine_init(&e,rules,1,10000000))return 1;
 for(int i=0;i<130;i++){char text[24];snprintf(text,sizeof(text),"object-%d",i);if(!mrl_knowledge_store_intern(s,text,&object))return 2;f=(MrlKnowledgeFact){.subject=subject,.predicate=p1,.object=object,.polarity=1,.modality=0};if(!mrl_knowledge_store_append(s,f,1)||!mrl_knowledge_assert(&e,(uint64_t)i+1,subject,p1,object))return 3;}
 if(!mrl_knowledge_close(&e)||e.assertion_count!=130||e.live_count!=260||mrl_knowledge_engine_cache_save(&e,s,"prepared.cache",0x77))return 4;
 if(!mrl_knowledge_engine_init(&loaded,rules,1,10000000)||mrl_knowledge_engine_cache_load(&loaded,s,"prepared.cache",0x77)||loaded.count!=e.count||loaded.live_count!=260||loaded.cap<=loaded.count||loaded.assertion_cap<=loaded.assertion_count||mrl_knowledge_query(&loaded,-1,p2,-1,NULL,NULL)!=130||(clean=mrl_knowledge_store_snapshot(s))==NULL)return 5;
 if(!mrl_knowledge_store_intern(s,"append",&object)||!mrl_knowledge_store_append(s,(MrlKnowledgeFact){.subject=subject,.predicate=p1,.object=object,.polarity=1},1)||!mrl_knowledge_assert(&loaded,131,subject,p1,object)||!mrl_knowledge_close(&loaded)||mrl_knowledge_query(&loaded,-1,p2,-1,NULL,NULL)!=131)return 6;
 if(!mrl_knowledge_remove(&loaded,131)||!mrl_knowledge_close(&loaded)||mrl_knowledge_query(&loaded,-1,p2,-1,NULL,NULL)!=130)return 10;
 if(!valid_corrupt("prepared.cache"))return 8;
 if(!mrl_knowledge_engine_init(&broken,rules,1,10000000)||!mrl_knowledge_engine_cache_load(&broken,clean,"prepared.cache",0x77)||broken.count)return 9;
 if(!mrl_knowledge_engine_init(&stale,rules,1,10000000)||!mrl_knowledge_store_append(s,(MrlKnowledgeFact){.subject=subject,.predicate=p1,.object=object,.polarity=1},1)||!mrl_knowledge_engine_cache_load(&stale,s,"prepared.cache",0x77))return 7;
 mrl_knowledge_engine_free(&broken);mrl_knowledge_engine_free(&stale);mrl_knowledge_engine_free(&loaded);mrl_knowledge_engine_free(&e);mrl_knowledge_store_release(clean);mrl_knowledge_store_release(s);return 0;}''', encoding="utf-8")
            try:
                build_c(c, exe)
            except subprocess.CalledProcessError as error:
                self.fail(error.stderr.decode(errors="replace"))
            result = subprocess.run([str(exe)], cwd=root, capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
