#ifndef MRL_VALUE_RUNTIME_H
#define MRL_VALUE_RUNTIME_H

#include <float.h>
#include <stdbool.h>
#include <limits.h>
#include <math.h>
#include <stdint.h>
#include <stddef.h>
#include <stdlib.h>
#include <string.h>

/* mrl_runtime_fail(const char *) is supplied by the generated translation unit. */
typedef enum { MRL_LIST_RAW, MRL_LIST_F32 } MrlListKind;
typedef void (*MrlValueCopy)(void *, const void *);
typedef void (*MrlValueDrop)(void *);
typedef struct { uint32_t refs, length, capacity; size_t item_size; MrlListKind kind; MrlValueCopy copy; MrlValueDrop drop; unsigned char *data; } MrlList;

static char *mrl_string_copy(const char *s) { size_t n = strlen(s) + 1; char *p = malloc(n); if (!p) { mrl_runtime_fail("MRL string allocation"); return NULL; } memcpy(p, s, n); return p; }
static char *mrl_string_join(const char *a, const char *b) { size_t an = strlen(a), bn = strlen(b); if (an > SIZE_MAX - bn - 1) { mrl_runtime_fail("MRL string size overflow"); return NULL; } char *p = malloc(an + bn + 1); if (!p) { mrl_runtime_fail("MRL string allocation"); return NULL; } memcpy(p, a, an); memcpy(p + an, b, bn + 1); return p; }
static void mrl_string_copy_into(void *out, const void *in) { *(char **)out = mrl_string_copy(*(char *const *)in); }
static void mrl_string_drop(void *value) { free(*(char **)value); }

static MrlList *mrl_list_new_full(size_t item_size, uint32_t capacity, MrlValueCopy copy, MrlValueDrop drop) {
    if (!item_size || capacity > SIZE_MAX / item_size) { mrl_runtime_fail("MRL list size overflow"); return NULL; }
    MrlList *list = calloc(1, sizeof(*list));
    if (!list) { mrl_runtime_fail("MRL list allocation"); return NULL; }
    list->refs = 1; list->capacity = capacity; list->item_size = item_size; list->copy = copy; list->drop = drop;
    if (capacity && !(list->data = calloc(capacity, item_size))) { free(list); mrl_runtime_fail("MRL list allocation"); return NULL; }
    return list;
}

/* Keep the original two-argument ABI for native snippets while generated
   managed lists pass their copy/release hooks. */
static MrlList *mrl_list_new_legacy(size_t item_size, uint32_t capacity) {
    return mrl_list_new_full(item_size, capacity, NULL, NULL);
}
#define MRL_LIST_NEW_SELECT(_1, _2, _3, _4, NAME, ...) NAME
#define mrl_list_new(...) MRL_LIST_NEW_SELECT(__VA_ARGS__, mrl_list_new_full, mrl_list_new_full, mrl_list_new_legacy)(__VA_ARGS__)

static MrlList *mrl_list_new_f32(uint32_t capacity) {
    MrlList *list = mrl_list_new(sizeof(float), capacity, NULL, NULL); if (list) list->kind = MRL_LIST_F32; return list;
}

static MrlList *mrl_list_retain(MrlList *list) {
    if (!list || list->refs == UINT32_MAX) { mrl_runtime_fail("MRL list reference overflow"); return NULL; }
    ++list->refs; return list;
}

static MrlList *mrl_list_copy(MrlList *list) { return mrl_list_retain(list); }

static void mrl_list_release(MrlList *list) {
    if (!list || !list->refs) { mrl_runtime_fail("MRL invalid list reference"); return; }
    if (!--list->refs) { if (list->drop) for (uint32_t i = 0; i < list->length; ++i) list->drop(list->data + (size_t)i * list->item_size); free(list->data); free(list); }
}

static int32_t mrl_list_len(const MrlList *list) {
    if (!list || list->length > INT32_MAX) { mrl_runtime_fail("MRL list length"); return 0; }
    return (int32_t)list->length;
}

static int32_t mrl_array_index(int32_t index, uint32_t length) {
    if (index < 0 || (uint32_t)index >= length) { mrl_runtime_fail("MRL index out of bounds"); return 0; }
    return index;
}

static void *mrl_list_at(MrlList *list, int32_t index) {
    return list ? list->data + (size_t)mrl_array_index(index, list->length) * list->item_size : NULL;
}

static const void *mrl_list_at_const(const MrlList *list, int32_t index) {
    return mrl_list_at((MrlList *)list, index);
}

static void mrl_list_push(MrlList *list, const void *item) {
    if (!list || !item) { mrl_runtime_fail("MRL invalid list push"); return; }
    if (list->length == UINT32_MAX) { mrl_runtime_fail("MRL list size overflow"); return; }
    size_t offset = 0; uintptr_t start = (uintptr_t)list->data, source = (uintptr_t)item;
    bool internal = list->length && list->data && source >= start && source - start <= (size_t)list->length * list->item_size - list->item_size;
    if (internal) offset = (size_t)(source - start);
    if (list->length == list->capacity) {
        uint32_t capacity = list->capacity ? list->capacity : 4;
        if (capacity > UINT32_MAX / 2) capacity = UINT32_MAX; else capacity *= 2;
        if (capacity <= list->length || capacity > SIZE_MAX / list->item_size) { mrl_runtime_fail("MRL list size overflow"); return; }
        void *data = realloc(list->data, (size_t)capacity * list->item_size);
        if (!data) { mrl_runtime_fail("MRL list allocation"); return; }
        list->data = data; list->capacity = capacity;
    }
    if (internal) item = list->data + offset;
    void *slot = list->data + (size_t)list->length++ * list->item_size;
    if (list->copy) list->copy(slot, item); else memcpy(slot, item, list->item_size);
}

static const float *mrl_f32_items(const MrlList *list) {
    if (!list || list->kind != MRL_LIST_F32) { mrl_runtime_fail("MRL expected list<f32>"); return NULL; }
    const float *items = (const float *)list->data;
    for (uint32_t i = 0; i < list->length; ++i) if (!isfinite(items[i])) { mrl_runtime_fail("MRL non-finite f32"); return NULL; }
    return items;
}

static float mrl_f32_result(double value) {
    if (!isfinite(value) || value > FLT_MAX || value < -FLT_MAX) { mrl_runtime_fail("MRL f32 overflow"); return 0.0f; }
    return (float)value;
}

static double mrl_f32_dot_value(const float *a, const float *b, uint32_t length) {
    double total = 0.0; for (uint32_t i = 0; i < length; ++i) total += (double)a[i] * b[i];
    return total;
}

static double mrl_f32_square_sum(const float *items, uint32_t length) {
    return mrl_f32_dot_value(items, items, length);
}

static float mrl_f32_sum(const MrlList *list) {
    if (!list) { mrl_runtime_fail("MRL expected list<f32>"); return 0.0f; }
    const float *items = mrl_f32_items(list);
    double total = 0.0; for (uint32_t i = 0; i < list->length; ++i) total += items[i];
    return mrl_f32_result(total);
}

static float mrl_f32_dot(const MrlList *left, const MrlList *right) {
    if (!left || !right) { mrl_runtime_fail("MRL expected list<f32>"); return 0.0f; }
    const float *a = mrl_f32_items(left), *b = mrl_f32_items(right);
    if (left->length != right->length) { mrl_runtime_fail("MRL f32 dot length"); return 0.0f; }
    return mrl_f32_result(mrl_f32_dot_value(a, b, left->length));
}

static float mrl_f32_norm(const MrlList *list) {
    if (!list) { mrl_runtime_fail("MRL expected list<f32>"); return 0.0f; }
    const float *items = mrl_f32_items(list);
    return mrl_f32_result(sqrt(mrl_f32_square_sum(items, list->length)));
}

static float mrl_f32_cosine(const MrlList *left, const MrlList *right) {
    if (!left || !right) { mrl_runtime_fail("MRL expected list<f32>"); return 0.0f; }
    const float *a = mrl_f32_items(left), *b = mrl_f32_items(right);
    if (left->length != right->length) { mrl_runtime_fail("MRL f32 dot length"); return 0.0f; }
    double an = mrl_f32_square_sum(a, left->length), bn = mrl_f32_square_sum(b, right->length);
    if (an == 0.0 || bn == 0.0) { mrl_runtime_fail("MRL zero f32 norm"); return 0.0f; }
    return mrl_f32_result(mrl_f32_dot_value(a, b, left->length) / sqrt(an * bn));
}

/* Maps own copied keys and values.  String keys use strcmp; numeric keys are
   fixed-size bytes, which keeps the generic runtime independent of IR types. */
typedef struct { unsigned char *key; unsigned char *value; } MrlMapEntry;
typedef struct { uint32_t refs, length, capacity; size_t key_size, value_size; bool string_keys; MrlValueCopy copy; MrlValueDrop drop; MrlMapEntry *items; } MrlMap;
static MrlMap *mrl_map_new(size_t key_size, bool string_keys, size_t value_size, MrlValueCopy copy, MrlValueDrop drop) { if (!key_size || !value_size) { mrl_runtime_fail("MRL map type"); return NULL; } MrlMap *m=calloc(1,sizeof(*m)); if(!m){mrl_runtime_fail("MRL map allocation");return NULL;} m->refs=1;m->key_size=key_size;m->string_keys=string_keys;m->value_size=value_size;m->copy=copy;m->drop=drop;return m; }
static MrlMap *mrl_map_retain(MrlMap*m){if(!m||m->refs==UINT32_MAX){mrl_runtime_fail("MRL map reference");return NULL;}++m->refs;return m;}
static void mrl_map_release(MrlMap*m){if(!m||!m->refs){mrl_runtime_fail("MRL map reference");return;}if(--m->refs)return;for(uint32_t i=0;i<m->length;i++){free(m->items[i].key);if(m->drop)m->drop(m->items[i].value);free(m->items[i].value);}free(m->items);free(m);}
static int32_t mrl_map_find(const MrlMap*m,const void*k){if(!m||!k)return -1;for(uint32_t i=0;i<m->length;i++)if(m->string_keys? !strcmp((const char*)m->items[i].key,*(char *const*)k):!memcmp(m->items[i].key,k,m->key_size))return (int32_t)i;return -1;}
static void mrl_map_set(MrlMap*m,const void*k,const void*v){if(!m||!k||!v){mrl_runtime_fail("MRL map type");return;}int32_t i=mrl_map_find(m,k);if(i<0){if(m->length==m->capacity){uint32_t c=m->capacity?m->capacity*2:8;if(c<m->capacity){mrl_runtime_fail("MRL map size overflow");return;}MrlMapEntry*p=realloc(m->items,(size_t)c*sizeof(*p));if(!p){mrl_runtime_fail("MRL map allocation");return;}m->items=p;m->capacity=c;}i=(int32_t)m->length++;m->items[i]=(MrlMapEntry){calloc(1,m->string_keys?strlen(*(char *const*)k)+1:m->key_size),calloc(1,m->value_size)};if(!m->items[i].key||!m->items[i].value){free(m->items[i].key);free(m->items[i].value);--m->length;mrl_runtime_fail("MRL map allocation");return;}if(m->string_keys)memcpy(m->items[i].key,*(char *const*)k,strlen(*(char *const*)k)+1);else memcpy(m->items[i].key,k,m->key_size);}else if(m->drop)m->drop(m->items[i].value);if(m->copy)m->copy(m->items[i].value,v);else memcpy(m->items[i].value,v,m->value_size);}
static const void *mrl_map_get(const MrlMap*m,const void*k){int32_t i=mrl_map_find(m,k);return i<0?NULL:m->items[i].value;}
static bool mrl_map_remove(MrlMap*m,const void*k){int32_t i=mrl_map_find(m,k);if(i<0)return false;free(m->items[i].key);if(m->drop)m->drop(m->items[i].value);free(m->items[i].value);m->items[i]=m->items[--m->length];return true;}

#endif
