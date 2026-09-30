#ifndef MRL_KNOWLEDGE_INDEXED_H
#define MRL_KNOWLEDGE_INDEXED_H
/*
 * Opt-in selective knowledge storage.  The legacy checkpoint APIs are eager.
 * One SQLite database holds persistent fact and symbol indexes. Transactions
 * update those indexes directly. Windows supplies winsqlite3 at runtime.
 */
#include "knowledge_store.h"
#include <stdint.h>
#include <stdbool.h>
#include <stdlib.h>
#include <string.h>
#include <stdio.h>

#define MRL_KNOWLEDGE_INDEXED_SCHEMA 1u
#define MRL_INDEXED_ASSERTION_FINGERPRINT UINT64_C(0x4d524c5f41535331)

typedef struct { uint32_t id; const char *text; } MrlKnowledgeIndexedSymbol;
typedef struct {
    uint64_t fingerprint, generation;
    uint8_t kind;
    const void *bytes;
    uint32_t size;
} MrlKnowledgeIndexedRuleDelta;
typedef struct { uint64_t bytes_read, rows_read, symbols_read, vm_steps, fullscan_steps; } MrlKnowledgeIndexedStats;
typedef struct { bool ok; int32_t value; const char *error; } MrlIndexedResult;

#if defined(_WIN32)
#include <windows.h>
typedef struct sqlite3 MrlIxDb;
typedef struct sqlite3_stmt MrlIxStmt;
typedef long long MrlIxI64;
typedef struct {
    HMODULE dll;
    int (*open_v2)(const char*,MrlIxDb**,int,const char*);
    int (*close)(MrlIxDb*);
    int (*exec)(MrlIxDb*,const char*,int(*)(void*,int,char**,char**),void*,char**);
    int (*prepare)(MrlIxDb*,const char*,int,MrlIxStmt**,const char**);
    int (*step)(MrlIxStmt*),(*finalize)(MrlIxStmt*);
    int (*stmt_status)(MrlIxStmt*,int,int);
    void (*free_mem)(void*);
    int (*bind_text)(MrlIxStmt*,int,const char*,int,void(*)(void*));
    int (*bind_blob)(MrlIxStmt*,int,const void*,int,void(*)(void*));
    int (*bind_int)(MrlIxStmt*,int,int);
    int (*bind_int64)(MrlIxStmt*,int,MrlIxI64);
    int (*column_int)(MrlIxStmt*,int);
    MrlIxI64 (*column_int64)(MrlIxStmt*,int);
    const unsigned char *(*column_text)(MrlIxStmt*,int);
    int (*column_bytes)(MrlIxStmt*,int);
} MrlIxApi;
#define MRL_IX_OK 0
#define MRL_IX_ROW 100
#define MRL_IX_DONE 101
#define MRL_IX_RW 2
#define MRL_IX_CREATE 4
#define MRL_IX_TRANSIENT ((void(*)(void*))-1)
static MrlIxApi *mrl_ix_api(void) {
    static MrlIxApi a; static int tried;
    if (tried) return a.dll ? &a : NULL;
    tried=1; a.dll=LoadLibraryA("winsqlite3.dll"); if (!a.dll) return NULL;
#define L(x) *(FARPROC*)&a.x=GetProcAddress(a.dll,"sqlite3_" #x)
    L(open_v2);L(close);L(exec);L(step);L(finalize);
    *(FARPROC*)&a.prepare=GetProcAddress(a.dll,"sqlite3_prepare_v2");
    L(bind_text);L(bind_blob);L(bind_int);L(bind_int64);L(column_int);L(column_int64);L(stmt_status);
    *(FARPROC*)&a.free_mem=GetProcAddress(a.dll,"sqlite3_free");
    L(column_text);L(column_bytes);
#undef L
    if(!a.open_v2||!a.close||!a.exec||!a.prepare||!a.step||!a.finalize||
       !a.bind_text||!a.bind_blob||!a.bind_int||!a.bind_int64||!a.free_mem||
       !a.column_int||!a.column_int64||!a.stmt_status||!a.column_text||!a.column_bytes) {
        FreeLibrary(a.dll); a.dll=NULL; return NULL;
    }
    return &a;
}
#else
typedef struct MrlIxApi MrlIxApi;
static MrlIxApi *mrl_ix_api(void) { return NULL; }
#endif

typedef struct {
    void *db, *api;
    char *base_path, *delta_path;
    uint64_t fingerprint, version, rule_fingerprint, rule_generation;
    unsigned overlay;
    const char *error;
    MrlKnowledgeIndexedStats stats;
} MrlKnowledgeIndexed;

static uint32_t mrl_ix_crc(const MrlKnowledgeFact *f,const char *s,const char *p,const char *o) {
    uint32_t h=2166136261u;const uint32_t u[12]={f->fact_id,f->id,f->subject,f->predicate,f->object,f->evidence,f->evidence_source,f->evidence_text,f->start,f->end,f->next_pred,f->prev_pred};
    for(size_t k=0;k<12;k++)for(unsigned b=0;b<4;b++)h=(h^((u[k]>>(8*b))&255u))*16777619u;
    h=(h^f->polarity)*16777619u;h=(h^f->modality)*16777619u;h=(h^f->live)*16777619u;
    const char *texts[3]={s,p,o};for(size_t k=0;k<3;k++){const unsigned char *t=(const unsigned char*)(texts[k]?texts[k]:"");while(*t)h=(h^*t++)*16777619u;h=(h^0u)*16777619u;}return h;
}
static char *mrl_ix_dup(const char *s) {
    if(!s)return NULL; size_t n=strlen(s)+1; char *p=(char*)malloc(n);
    if(p)memcpy(p,s,n); return p;
}
static const char *mrl_ix_fail(MrlKnowledgeIndexed *i,const char *e) {
    if(i)i->error=e; return e;
}
#if defined(_WIN32)
static int mrl_ix_path_exists(const char *path) {
    if(!path)return 0;int n=MultiByteToWideChar(CP_UTF8,MB_ERR_INVALID_CHARS,path,-1,NULL,0);if(n<=0)return 0;wchar_t *wide=(wchar_t*)malloc((size_t)n*sizeof(*wide));if(!wide)return 0;int ok=MultiByteToWideChar(CP_UTF8,MB_ERR_INVALID_CHARS,path,-1,wide,n)==n&&GetFileAttributesW(wide)!=INVALID_FILE_ATTRIBUTES;free(wide);return ok;
}
#endif
#if defined(_WIN32)
static int mrl_ix_exec(MrlIxApi *a,MrlIxDb *d,const char *sql) {
    char *msg=NULL; int rc=a->exec(d,sql,NULL,NULL,&msg); if(msg)a->free_mem(msg); return rc;
}
static int mrl_ix_stmt(MrlIxApi *a,MrlIxDb *d,const char *sql,MrlIxStmt **s) {
    return a->prepare(d,sql,-1,s,NULL);
}
static int mrl_ix_meta(MrlIxApi *a,MrlIxDb *d,int overlay,uint64_t fp,uint64_t version) {
    const char *t=overlay?"mrl_delta_meta":"mrl_meta"; char q[192]; MrlIxStmt *s=NULL; int ok;
    snprintf(q,sizeof(q),"INSERT OR REPLACE INTO %s(k,v) VALUES(?1,?2)",t);
    if(mrl_ix_stmt(a,d,q,&s)!=MRL_IX_OK)return 0;
    ok=a->bind_text(s,1,"fingerprint",-1,MRL_IX_TRANSIENT)==MRL_IX_OK &&
      a->bind_int64(s,2,(MrlIxI64)fp)==MRL_IX_OK && a->step(s)==MRL_IX_DONE;
    a->finalize(s); if(!ok)return 0;
    if(mrl_ix_stmt(a,d,q,&s)!=MRL_IX_OK)return 0;
    ok=a->bind_text(s,1,"version",-1,MRL_IX_TRANSIENT)==MRL_IX_OK &&
      a->bind_int64(s,2,(MrlIxI64)version)==MRL_IX_OK && a->step(s)==MRL_IX_DONE;
    a->finalize(s); return ok;
}
static const char *mrl_ix_base_schema =
"PRAGMA journal_mode=WAL;PRAGMA synchronous=FULL;"
"CREATE TABLE IF NOT EXISTS mrl_meta(k TEXT PRIMARY KEY,v INTEGER NOT NULL);"
"CREATE TABLE IF NOT EXISTS mrl_symbols(id INTEGER PRIMARY KEY,text TEXT NOT NULL UNIQUE);"
"CREATE TABLE IF NOT EXISTS mrl_facts(fact_id INTEGER PRIMARY KEY,id INTEGER,subject INTEGER,predicate INTEGER,object INTEGER,evidence INTEGER,polarity INTEGER,modality INTEGER,live INTEGER,evidence_source INTEGER,evidence_text INTEGER,start INTEGER,end INTEGER,next_pred INTEGER,prev_pred INTEGER,subject_text TEXT NOT NULL,predicate_text TEXT NOT NULL,object_text TEXT NOT NULL,row_crc INTEGER NOT NULL);"
"CREATE INDEX IF NOT EXISTS mrl_fact_lookup ON mrl_facts(subject_text,predicate_text,object_text);"
"CREATE INDEX IF NOT EXISTS mrl_fact_id_lookup ON mrl_facts(id,live,fact_id);"
"CREATE TABLE IF NOT EXISTS mrl_rules(generation INTEGER PRIMARY KEY,fingerprint INTEGER NOT NULL,kind INTEGER NOT NULL,bytes BLOB NOT NULL);";
static int mrl_ix_bind_fact(MrlIxApi *a,MrlIxStmt *s,const MrlKnowledgeFact *f,const char *x,const char *p,const char *o,int op) {
    int r=0;
#define B(x) r|=(x)
    B(a->bind_int64(s,1,(MrlIxI64)f->fact_id)); if(op>=0)B(a->bind_int(s,2,op));
    int n=op>=0?3:2; B(a->bind_int64(s,n++,(MrlIxI64)f->id));B(a->bind_int64(s,n++,(MrlIxI64)f->subject));B(a->bind_int64(s,n++,(MrlIxI64)f->predicate));B(a->bind_int64(s,n++,(MrlIxI64)f->object));B(a->bind_int64(s,n++,(MrlIxI64)f->evidence));
    B(a->bind_int(s,n++,f->polarity));B(a->bind_int(s,n++,f->modality));B(a->bind_int(s,n++,f->live));B(a->bind_int64(s,n++,(MrlIxI64)f->evidence_source));B(a->bind_int64(s,n++,(MrlIxI64)f->evidence_text));B(a->bind_int64(s,n++,(MrlIxI64)f->start));B(a->bind_int64(s,n++,(MrlIxI64)f->end));B(a->bind_int64(s,n++,(MrlIxI64)f->next_pred));B(a->bind_int64(s,n++,(MrlIxI64)f->prev_pred));
    B(a->bind_text(s,n++,x,-1,MRL_IX_TRANSIENT));B(a->bind_text(s,n++,p,-1,MRL_IX_TRANSIENT));B(a->bind_text(s,n++,o,-1,MRL_IX_TRANSIENT));B(a->bind_int64(s,n,(MrlIxI64)mrl_ix_crc(f,x,p,o)));
#undef B
    return r==0;
}
static const char *mrl_ix_insert_base =
"INSERT OR REPLACE INTO mrl_facts(fact_id,id,subject,predicate,object,evidence,polarity,modality,live,evidence_source,evidence_text,start,end,next_pred,prev_pred,subject_text,predicate_text,object_text,row_crc) VALUES(?1,?2,?3,?4,?5,?6,?7,?8,?9,?10,?11,?12,?13,?14,?15,?16,?17,?18,?19)";
#endif

static const char *mrl_knowledge_indexed_build(const MrlKnowledgeStore *s,const char *path,uint64_t fingerprint) {
#if !defined(_WIN32)
    (void)s;(void)path;(void)fingerprint; return "indexed storage requires winsqlite3";
#else
    MrlIxApi *a=mrl_ix_api(); MrlIxDb *d=NULL; MrlIxStmt *q=NULL; const char *e=NULL;
    if(!a||!s||!path)return "indexed storage unavailable";
    if(a->open_v2(path,&d,MRL_IX_RW|MRL_IX_CREATE,NULL)!=MRL_IX_OK)return "indexed base open";
    if(mrl_ix_exec(a,d,mrl_ix_base_schema)!=MRL_IX_OK||mrl_ix_exec(a,d,"BEGIN IMMEDIATE;DELETE FROM mrl_meta;DELETE FROM mrl_symbols;DELETE FROM mrl_facts;DELETE FROM mrl_rules;")!=MRL_IX_OK){e="indexed base schema";goto done;}
    if(!mrl_ix_meta(a,d,0,fingerprint,mrl_knowledge_store_version(s))){e="indexed base metadata";goto rollback;}
    if(mrl_ix_stmt(a,d,"INSERT INTO mrl_symbols(id,text) VALUES(?1,?2)",&q)!=MRL_IX_OK){e="indexed symbol statement";goto rollback;}
    for(uint32_t id=1;id<=s->symbols->next;id++){const char *t=mrl_knowledge_store_symbol(s,id);if(!t||a->bind_int64(q,1,id)!=MRL_IX_OK||a->bind_text(q,2,t,-1,MRL_IX_TRANSIENT)!=MRL_IX_OK||a->step(q)!=MRL_IX_DONE){e="indexed symbol write";goto rollback;}a->finalize(q);q=NULL;if(id<s->symbols->next&&mrl_ix_stmt(a,d,"INSERT INTO mrl_symbols(id,text) VALUES(?1,?2)",&q)!=MRL_IX_OK){e="indexed symbol statement";goto rollback;}}
    if(q){a->finalize(q);q=NULL;}
    if(mrl_ix_stmt(a,d,mrl_ix_insert_base,&q)!=MRL_IX_OK){e="indexed fact statement";goto rollback;}
    for(uint32_t id=1;id<=s->next_id;id++){MrlKnowledgeFact f;if(!mrl_knowledge_store_get_any_fact(s,id,&f)){e="indexed fact read";goto rollback;}const char *x=mrl_knowledge_store_symbol(s,f.subject),*p=mrl_knowledge_store_symbol(s,f.predicate),*o=mrl_knowledge_store_symbol(s,f.object);if(!x)x="";if(!p)p="";if(!o)o="";if(!mrl_ix_bind_fact(a,q,&f,x,p,o,-1)||a->step(q)!=MRL_IX_DONE){e="indexed fact write";goto rollback;}a->finalize(q);q=NULL;if(id<s->next_id&&mrl_ix_stmt(a,d,mrl_ix_insert_base,&q)!=MRL_IX_OK){e="indexed fact statement";goto rollback;}}
    if(mrl_ix_exec(a,d,"COMMIT;")!=MRL_IX_OK){e="indexed base commit";goto done;}a->close(d);return NULL;
rollback:if(q)a->finalize(q);mrl_ix_exec(a,d,"ROLLBACK;");
done:if(d)a->close(d);return e;
#endif
}

static const char *mrl_knowledge_indexed_open(MrlKnowledgeIndexed *i,const char *base_path,const char *delta_path,uint64_t expected_fingerprint) {
#if !defined(_WIN32)
    (void)i;(void)base_path;(void)delta_path;(void)expected_fingerprint;return "indexed storage requires winsqlite3";
#else
    MrlIxApi *a=mrl_ix_api();MrlIxDb *d=NULL;MrlIxStmt *q=NULL;int rc;uint64_t fp=0,ver=0;int seen_fp=0,seen_ver=0;const char *e=NULL;
    if(!i||!a||!base_path)return "indexed storage unavailable";memset(i,0,sizeof(*i));i->api=a;i->base_path=mrl_ix_dup(base_path);i->delta_path=mrl_ix_dup(delta_path);
    /* The optional delta_path is retained for ABI compatibility; SQLite's
       WAL/rollback journal is the durable delta and the base stays indexed. */
    i->overlay=0;
    if(a->open_v2(base_path,&d,MRL_IX_RW,NULL)!=MRL_IX_OK){e="indexed open";goto fail;}i->db=d;
    const char *sql="SELECT k,v FROM mrl_meta WHERE k IN ('fingerprint','version')";
    if(mrl_ix_stmt(a,d,sql,&q)!=MRL_IX_OK){e="indexed metadata";goto fail;}while((rc=a->step(q))==MRL_IX_ROW){const char *k=(const char*)a->column_text(q,0);uint64_t v=(uint64_t)a->column_int64(q,1);if(k&&!strcmp(k,"fingerprint")){fp=v;seen_fp=1;}else if(k&&!strcmp(k,"version")){ver=v;seen_ver=1;}}a->finalize(q);q=NULL;if(rc!=MRL_IX_DONE||!seen_fp||!seen_ver||fp!=expected_fingerprint){e="indexed fingerprint";goto fail;}if(mrl_ix_exec(a,d,"PRAGMA journal_mode=WAL;PRAGMA synchronous=FULL;")!=MRL_IX_OK){e="indexed pragmas";goto fail;}i->fingerprint=fp;i->version=ver;
    if(mrl_ix_stmt(a,d,"SELECT fingerprint,generation FROM mrl_rules ORDER BY generation DESC LIMIT 1",&q)!=MRL_IX_OK){e="indexed rules";goto fail;}rc=a->step(q);if(rc==MRL_IX_ROW){i->rule_fingerprint=(uint64_t)a->column_int64(q,0);i->rule_generation=(uint64_t)a->column_int64(q,1);}else if(rc!=MRL_IX_DONE){e="indexed rules";goto fail;}a->finalize(q);q=NULL;
    return NULL;
fail:if(q)a->finalize(q);if(d)a->close(d);free(i->base_path);free(i->delta_path);memset(i,0,sizeof(*i));return mrl_ix_fail(i,e);
#endif
}

#if defined(_WIN32)
static char *mrl_ix_symbol(MrlIxApi *a,MrlIxDb *d,const MrlKnowledgeIndexedSymbol *v,size_t n,uint32_t id) {
    (void)v;(void)n;
    MrlIxStmt *s=NULL; if(!id||mrl_ix_stmt(a,d,"SELECT text FROM mrl_symbols WHERE id=?1",&s)!=MRL_IX_OK)return NULL;
    char *out=NULL; if(a->bind_int64(s,1,(MrlIxI64)id)==MRL_IX_OK&&a->step(s)==MRL_IX_ROW){const char *t=(const char*)a->column_text(s,0);if(t)out=mrl_ix_dup(t);}a->finalize(s);return out;
}
#endif
static const char *mrl_knowledge_indexed_append(MrlKnowledgeIndexed *i,uint64_t version,const MrlKnowledgeIndexedSymbol *symbols,size_t symbol_count,const MrlKnowledgeFact *rows,size_t row_count,const MrlKnowledgeIndexedRuleDelta *rule) {
#if !defined(_WIN32)
    (void)i;(void)version;(void)symbols;(void)symbol_count;(void)rows;(void)row_count;(void)rule;return "indexed storage requires winsqlite3";
#else
    MrlIxApi *a=i?(MrlIxApi*)i->api:NULL;MrlIxDb *d=i?(MrlIxDb*)i->db:NULL;MrlIxStmt *q=NULL;const char *e=NULL;
    if(!i||!a||!d)return mrl_ix_fail(i,"indexed append requires open index");if(version<=i->version)return mrl_ix_fail(i,"indexed version");if((symbol_count&&!symbols)||(row_count&&!rows)||(rule&&rule->size&&!rule->bytes)||symbol_count>1048576u||row_count>1048576u||(rule&&rule->size>33554432u))return mrl_ix_fail(i,"indexed append arguments");for(size_t k=0;k<symbol_count;k++)if(!symbols[k].id||!symbols[k].text||!ks_utf8(symbols[k].text))return mrl_ix_fail(i,"indexed symbol");for(size_t k=0;k<row_count;k++)if(!rows[k].fact_id||rows[k].polarity>1||rows[k].modality>2||rows[k].live>1)return mrl_ix_fail(i,"indexed fact");
    if(mrl_ix_exec(a,d,"BEGIN IMMEDIATE;")!=MRL_IX_OK)return mrl_ix_fail(i,"indexed transaction");
    { MrlIxStmt *check=NULL; uint64_t current=UINT64_MAX; int rc=mrl_ix_stmt(a,d,"SELECT v FROM mrl_meta WHERE k='version' LIMIT 1",&check);
      if(rc==MRL_IX_OK&&a->step(check)==MRL_IX_ROW)current=(uint64_t)a->column_int64(check,0);if(check)a->finalize(check);
      if(current!=i->version){mrl_ix_exec(a,d,"ROLLBACK;");return mrl_ix_fail(i,"indexed stale version");} }
    if(!mrl_ix_meta(a,d,0,i->fingerprint,version)){e="indexed metadata";goto rollback;}
    if(symbol_count){if(mrl_ix_stmt(a,d,"INSERT INTO mrl_symbols(id,text) VALUES(?1,?2)",&q)!=MRL_IX_OK){e="indexed symbol statement";goto rollback;}for(size_t k=0;k<symbol_count;k++){if(!symbols[k].id||!symbols[k].text||a->bind_int64(q,1,symbols[k].id)!=MRL_IX_OK||a->bind_text(q,2,symbols[k].text,-1,MRL_IX_TRANSIENT)!=MRL_IX_OK||a->step(q)!=MRL_IX_DONE){e="indexed symbol";goto rollback;}a->finalize(q);q=NULL;if(k+1<symbol_count&&mrl_ix_stmt(a,d,"INSERT INTO mrl_symbols(id,text) VALUES(?1,?2)",&q)!=MRL_IX_OK){e="indexed symbol statement";goto rollback;}}}
    if(row_count){if(mrl_ix_stmt(a,d,mrl_ix_insert_base,&q)!=MRL_IX_OK){e="indexed fact statement";goto rollback;}for(size_t k=0;k<row_count;k++){char *x=mrl_ix_symbol(a,d,symbols,symbol_count,rows[k].subject),*p=mrl_ix_symbol(a,d,symbols,symbol_count,rows[k].predicate),*o=mrl_ix_symbol(a,d,symbols,symbol_count,rows[k].object);if(!x||!p||!o||!mrl_ix_bind_fact(a,q,&rows[k],x,p,o,-1)||a->step(q)!=MRL_IX_DONE){free(x);free(p);free(o);e="indexed fact";goto rollback;}free(x);free(p);free(o);a->finalize(q);q=NULL;if(k+1<row_count&&mrl_ix_stmt(a,d,mrl_ix_insert_base,&q)!=MRL_IX_OK){e="indexed fact statement";goto rollback;}}}
    if(rule){if(mrl_ix_stmt(a,d,"INSERT OR REPLACE INTO mrl_rules(generation,fingerprint,kind,bytes) VALUES(?1,?2,?3,?4)",&q)!=MRL_IX_OK){e="indexed rule statement";goto rollback;}if(a->bind_int64(q,1,(MrlIxI64)rule->generation)!=MRL_IX_OK||a->bind_int64(q,2,(MrlIxI64)rule->fingerprint)!=MRL_IX_OK||a->bind_int(q,3,rule->kind)!=MRL_IX_OK||a->bind_blob(q,4,rule->bytes,(int)rule->size,MRL_IX_TRANSIENT)!=MRL_IX_OK||a->step(q)!=MRL_IX_DONE){e="indexed rule write";goto rollback;}a->finalize(q);q=NULL;}
    if(mrl_ix_exec(a,d,"COMMIT;")!=MRL_IX_OK){e="indexed commit";goto rollback;}if(rule){i->rule_fingerprint=rule->fingerprint;i->rule_generation=rule->generation;}i->version=version;return NULL;
rollback:if(q)a->finalize(q);mrl_ix_exec(a,d,"ROLLBACK;");return mrl_ix_fail(i,e);
#endif
}
#if defined(_WIN32)
static bool mrl_ix_stmt_fact(MrlIxApi *a,MrlIxStmt *q,int off,MrlKnowledgeFact *out) {
    MrlKnowledgeFact f={(uint32_t)a->column_int64(q,off+0),(uint32_t)a->column_int64(q,off+1),(uint32_t)a->column_int64(q,off+2),(uint32_t)a->column_int64(q,off+3),(uint32_t)a->column_int64(q,off+4),(uint32_t)a->column_int64(q,off+5),(uint8_t)a->column_int(q,off+6),(uint8_t)a->column_int(q,off+7),(uint8_t)a->column_int(q,off+8),(uint32_t)a->column_int64(q,off+9),(uint32_t)a->column_int64(q,off+10),(uint32_t)a->column_int64(q,off+11),(uint32_t)a->column_int64(q,off+12),(uint32_t)a->column_int64(q,off+13),(uint32_t)a->column_int64(q,off+14)};
    const char *s=(const char*)a->column_text(q,off+15),*p=(const char*)a->column_text(q,off+16),*o=(const char*)a->column_text(q,off+17);uint32_t crc=(uint32_t)a->column_int64(q,off+18);if(!s||!p||!o||f.polarity>1||f.live>1||crc!=mrl_ix_crc(&f,s,p,o))return false;if(out)*out=f;return true;
}
#endif
static bool mrl_knowledge_indexed_find(MrlKnowledgeIndexed *i,const char *subject,const char *predicate,const char *object,MrlKnowledgeFact *out) {
#if !defined(_WIN32)
    (void)i;(void)subject;(void)predicate;(void)object;(void)out;return false;
#else
    MrlIxApi *a=i?(MrlIxApi*)i->api:NULL;MrlIxDb *d=i?(MrlIxDb*)i->db:NULL;MrlIxStmt *q=NULL;int rc;
    if(!i||!a||!d||!subject||!predicate||!object)return false;
    const char *sql="SELECT fact_id,id,subject,predicate,object,evidence,polarity,modality,live,evidence_source,evidence_text,start,end,next_pred,prev_pred,subject_text,predicate_text,object_text,row_crc FROM mrl_facts WHERE live=1 AND subject_text=?1 AND predicate_text=?2 AND object_text=?3 ORDER BY fact_id DESC LIMIT 1";
    if(mrl_ix_stmt(a,d,sql,&q)!=MRL_IX_OK){i->error="indexed query";return false;}if(a->bind_text(q,1,subject,-1,MRL_IX_TRANSIENT)!=MRL_IX_OK||a->bind_text(q,2,predicate,-1,MRL_IX_TRANSIENT)!=MRL_IX_OK||a->bind_text(q,3,object,-1,MRL_IX_TRANSIENT)!=MRL_IX_OK){a->finalize(q);i->error="indexed query";return false;}
    rc=a->step(q);i->stats.vm_steps+=(uint64_t)a->stmt_status(q,4,0);i->stats.fullscan_steps+=(uint64_t)a->stmt_status(q,1,0);if(rc!=MRL_IX_ROW){a->finalize(q);if(rc!=MRL_IX_DONE)i->error="indexed query";return false;}
    MrlKnowledgeFact f; if(!mrl_ix_stmt_fact(a,q,0,&f)){a->finalize(q);i->error="indexed row corruption";return false;}a->finalize(q);i->stats.rows_read++;i->stats.bytes_read+=sizeof(f);if(out)*out=f;return true;
#endif
}
static MrlKnowledgeIndexedStats mrl_knowledge_indexed_stats(const MrlKnowledgeIndexed *i){return i?i->stats:(MrlKnowledgeIndexedStats){0,0,0};}
static void mrl_knowledge_indexed_close(MrlKnowledgeIndexed *i) {
#if defined(_WIN32)
    if(!i)return;MrlIxApi *a=(MrlIxApi*)i->api;if(a&&i->db)a->close((MrlIxDb*)i->db);free(i->base_path);free(i->delta_path);memset(i,0,sizeof(*i));
#else
    (void)i;
#endif
}
static uint64_t mrl_knowledge_indexed_rule_fingerprint(const MrlKnowledgeIndexed *i){return i?i->rule_fingerprint:0;}
static uint64_t mrl_knowledge_indexed_rule_generation(const MrlKnowledgeIndexed *i){return i?i->rule_generation:0;}

static MrlIndexedResult mrl_ix_result(bool ok,int32_t value,const char *error){return (MrlIndexedResult){ok,value,error};}
#if defined(_WIN32)
static int mrl_ix_lookup_id(MrlIxApi *a,MrlIxDb *d,const char *text,uint32_t *id) {
    MrlIxStmt *q=NULL;int found=0,rc;if(!text||mrl_ix_stmt(a,d,"SELECT id FROM mrl_symbols WHERE text=?1 LIMIT 1",&q)!=MRL_IX_OK)return -1;
    if(a->bind_text(q,1,text,-1,MRL_IX_TRANSIENT)!=MRL_IX_OK){a->finalize(q);return -1;}rc=a->step(q);if(rc==MRL_IX_ROW){*id=(uint32_t)a->column_int64(q,0);found=1;}else if(rc!=MRL_IX_DONE)found=-1;a->finalize(q);return found;
}
static uint32_t mrl_ix_next_id(MrlIxApi *a,MrlIxDb *d,const char *table) {
    char sql[128];MrlIxStmt *q=NULL;uint32_t id=0;const char *source=!strcmp(table,"id")?"mrl_symbols":"mrl_facts";snprintf(sql,sizeof(sql),"SELECT COALESCE(MAX(%s),0)+1 FROM %s",table,source);
    if(mrl_ix_stmt(a,d,sql,&q)==MRL_IX_OK&&a->step(q)==MRL_IX_ROW)id=(uint32_t)a->column_int64(q,0);if(q)a->finalize(q);return id;
}
static int mrl_ix_fact_for_name(MrlIxApi *a,MrlIxDb *d,const char *name,uint32_t *fact_id,uint32_t *symbol_id) {
    MrlIxStmt *q=NULL;int found=0,rc;if(!name||mrl_ix_stmt(a,d,"SELECT f.fact_id,f.id FROM mrl_facts f JOIN mrl_symbols s ON s.id=f.id WHERE s.text=?1 AND f.live=1 ORDER BY f.fact_id DESC LIMIT 1",&q)!=MRL_IX_OK)return -1;
    if(a->bind_text(q,1,name,-1,MRL_IX_TRANSIENT)!=MRL_IX_OK){a->finalize(q);return -1;}rc=a->step(q);if(rc==MRL_IX_ROW){*fact_id=(uint32_t)a->column_int64(q,0);*symbol_id=(uint32_t)a->column_int64(q,1);found=1;}else if(rc!=MRL_IX_DONE)found=-1;a->finalize(q);return found;
}
static int mrl_ix_read_fact(MrlIxApi *a,MrlIxDb *d,uint32_t fact_id,MrlKnowledgeFact *out) {
    MrlIxStmt *q=NULL;int ok=0;if(mrl_ix_stmt(a,d,"SELECT fact_id,id,subject,predicate,object,evidence,polarity,modality,live,evidence_source,evidence_text,start,end,next_pred,prev_pred,subject_text,predicate_text,object_text,row_crc FROM mrl_facts WHERE fact_id=?1",&q)==MRL_IX_OK&&a->bind_int64(q,1,(MrlIxI64)fact_id)==MRL_IX_OK&&a->step(q)==MRL_IX_ROW)ok=mrl_ix_stmt_fact(a,q,0,out);if(q)a->finalize(q);return ok;
}
static int mrl_ix_ids(MrlIxApi *a,MrlIxDb *d,const char *const names[4],uint32_t ids[4],MrlKnowledgeIndexedSymbol added[4],size_t *added_count) {
    uint32_t next=mrl_ix_next_id(a,d,"id");if(!next)return 0;*added_count=0;
    for(size_t k=0;k<4;k++){if(!names[k]||!*names[k])return 0;int found=mrl_ix_lookup_id(a,d,names[k],&ids[k]);if(found<0)return 0;if(found)continue;for(size_t j=0;j<k;j++)if(!strcmp(names[j],names[k])){ids[k]=ids[j];found=1;break;}if(!found){ids[k]=next++;added[(*added_count)++]=(MrlKnowledgeIndexedSymbol){ids[k],names[k]};}}
    return 1;
}
static MrlIndexedResult mrl_ix_path_open(MrlKnowledgeIndexed *ix,const char *path) {
    if(!mrl_ix_path_exists(path))return mrl_ix_result(false,0,"indexed database missing");
    const char *e=mrl_knowledge_indexed_open(ix,path,NULL,MRL_INDEXED_ASSERTION_FINGERPRINT);return e?mrl_ix_result(false,0,e):mrl_ix_result(true,1,NULL);
}
#endif

static MrlIndexedResult mrl_indexed_save(const MrlKnowledgeStore *store,const char *path) {
#if !defined(_WIN32)
    (void)store;(void)path;return mrl_ix_result(false,0,"indexed storage requires winsqlite3");
#else
    if(!store||!path||!*path)return mrl_ix_result(false,0,"indexed save arguments");
    if(mrl_ix_path_exists(path))return mrl_ix_result(false,0,"indexed path already exists");
    const char *e=mrl_knowledge_indexed_build(store,path,MRL_INDEXED_ASSERTION_FINGERPRINT);return e?mrl_ix_result(false,0,e):mrl_ix_result(true,1,NULL);
#endif
}
static MrlIndexedResult mrl_indexed_exists(const char *path,const char *subject,const char *predicate,const char *object) {
#if !defined(_WIN32)
    (void)path;(void)subject;(void)predicate;(void)object;return mrl_ix_result(false,0,"indexed storage requires winsqlite3");
#else
    MrlKnowledgeIndexed ix={0};MrlIndexedResult r=mrl_ix_path_open(&ix,path);if(!r.ok)return r;MrlIxApi *a=(MrlIxApi*)ix.api;MrlIxDb *d=(MrlIxDb*)ix.db;MrlIxStmt *q=NULL;int positive=0,negative=0,rc;
    const char *sql="SELECT fact_id,id,subject,predicate,object,evidence,polarity,modality,live,evidence_source,evidence_text,start,end,next_pred,prev_pred,subject_text,predicate_text,object_text,row_crc FROM mrl_facts WHERE live=1 AND modality=0 AND subject_text=?1 AND predicate_text=?2 AND object_text=?3";
    if(!subject||!predicate||!object||mrl_ix_stmt(a,d,sql,&q)!=MRL_IX_OK||a->bind_text(q,1,subject,-1,MRL_IX_TRANSIENT)!=MRL_IX_OK||a->bind_text(q,2,predicate,-1,MRL_IX_TRANSIENT)!=MRL_IX_OK||a->bind_text(q,3,object,-1,MRL_IX_TRANSIENT)!=MRL_IX_OK){if(q)a->finalize(q);mrl_knowledge_indexed_close(&ix);return mrl_ix_result(false,0,"indexed query");}
    while((rc=a->step(q))==MRL_IX_ROW){MrlKnowledgeFact f;if(!mrl_ix_stmt_fact(a,q,0,&f)){a->finalize(q);mrl_knowledge_indexed_close(&ix);return mrl_ix_result(false,0,"indexed row corruption");}if(f.polarity)positive=1;else negative=1;ix.stats.rows_read++;ix.stats.bytes_read+=sizeof(f);}a->finalize(q);mrl_knowledge_indexed_close(&ix);if(rc!=MRL_IX_DONE)return mrl_ix_result(false,0,"indexed query");return mrl_ix_result(true,(positive&&!negative)?1:0,NULL);
#endif
}
static MrlIndexedResult mrl_indexed_add(const char *path,const char *id,const char *subject,const char *predicate,const char *object,bool polarity) {
#if !defined(_WIN32)
    (void)path;(void)id;(void)subject;(void)predicate;(void)object;(void)polarity;return mrl_ix_result(false,0,"indexed storage requires winsqlite3");
#else
    MrlKnowledgeIndexed ix={0};MrlIndexedResult r=mrl_ix_path_open(&ix,path);if(!r.ok)return r;MrlIxApi *a=(MrlIxApi*)ix.api;MrlIxDb *d=(MrlIxDb*)ix.db;uint32_t duplicate,unused;int prior=mrl_ix_fact_for_name(a,d,id,&duplicate,&unused);if(prior<0){mrl_knowledge_indexed_close(&ix);return mrl_ix_result(false,0,"indexed fact query");}if(prior==1){MrlKnowledgeFact old;if(!mrl_ix_read_fact(a,d,duplicate,&old)){mrl_knowledge_indexed_close(&ix);return mrl_ix_result(false,0,"indexed row corruption");}mrl_knowledge_indexed_close(&ix);return mrl_ix_result(true,0,NULL);}const char *names[4]={id,subject,predicate,object};uint32_t ids[4];MrlKnowledgeIndexedSymbol added[4];size_t n=0;if(!mrl_ix_ids(a,d,names,ids,added,&n)){mrl_knowledge_indexed_close(&ix);return mrl_ix_result(false,0,"indexed symbols");}MrlKnowledgeFact f={mrl_ix_next_id(a,d,"fact_id"),ids[0],ids[1],ids[2],ids[3],0,(uint8_t)(polarity?1:0),0,1,0,0,0,0,0,0};const char *e=mrl_knowledge_indexed_append(&ix,ix.version+1,added,n,&f,1,NULL);mrl_knowledge_indexed_close(&ix);return e?mrl_ix_result(false,0,e):mrl_ix_result(true,1,NULL);
#endif
}
static MrlIndexedResult mrl_indexed_correct(const char *path,const char *id,const char *subject,const char *predicate,const char *object,bool polarity) {
#if !defined(_WIN32)
    (void)path;(void)id;(void)subject;(void)predicate;(void)object;(void)polarity;return mrl_ix_result(false,0,"indexed storage requires winsqlite3");
#else
    MrlKnowledgeIndexed ix={0};MrlIndexedResult r=mrl_ix_path_open(&ix,path);if(!r.ok)return r;MrlIxApi *a=(MrlIxApi*)ix.api;MrlIxDb *d=(MrlIxDb*)ix.db;uint32_t fid,oldid;int prior=mrl_ix_fact_for_name(a,d,id,&fid,&oldid);if(prior<0){mrl_knowledge_indexed_close(&ix);return mrl_ix_result(false,0,"indexed fact query");}if(prior==0){mrl_knowledge_indexed_close(&ix);return mrl_ix_result(false,0,"indexed fact id");}MrlKnowledgeFact old;if(!mrl_ix_read_fact(a,d,fid,&old)){mrl_knowledge_indexed_close(&ix);return mrl_ix_result(false,0,"indexed row corruption");}const char *names[4]={id,subject,predicate,object};uint32_t ids[4];MrlKnowledgeIndexedSymbol added[4];size_t n=0;if(!mrl_ix_ids(a,d,names,ids,added,&n)){mrl_knowledge_indexed_close(&ix);return mrl_ix_result(false,0,"indexed symbols");}MrlKnowledgeFact f={fid,oldid,ids[1],ids[2],ids[3],0,(uint8_t)(polarity?1:0),0,1,0,0,0,0,0,0};const char *e=mrl_knowledge_indexed_append(&ix,ix.version+1,added,n,&f,1,NULL);mrl_knowledge_indexed_close(&ix);return e?mrl_ix_result(false,0,e):mrl_ix_result(true,1,NULL);
#endif
}
static MrlIndexedResult mrl_indexed_remove(const char *path,const char *id) {
#if !defined(_WIN32)
    (void)path;(void)id;return mrl_ix_result(false,0,"indexed storage requires winsqlite3");
#else
    MrlKnowledgeIndexed ix={0};MrlIndexedResult r=mrl_ix_path_open(&ix,path);if(!r.ok)return r;MrlIxApi *a=(MrlIxApi*)ix.api;MrlIxDb *d=(MrlIxDb*)ix.db;uint32_t fid,symbol_id;int prior=mrl_ix_fact_for_name(a,d,id,&fid,&symbol_id);if(prior<0){mrl_knowledge_indexed_close(&ix);return mrl_ix_result(false,0,"indexed fact query");}if(prior==0){mrl_knowledge_indexed_close(&ix);return mrl_ix_result(true,0,NULL);}MrlKnowledgeFact f;if(!mrl_ix_read_fact(a,d,fid,&f)){mrl_knowledge_indexed_close(&ix);return mrl_ix_result(false,0,"indexed row corruption");}f.live=0;const char *e=mrl_knowledge_indexed_append(&ix,ix.version+1,NULL,0,&f,1,NULL);mrl_knowledge_indexed_close(&ix);return e?mrl_ix_result(false,0,e):mrl_ix_result(true,1,NULL);
#endif
}

#endif
