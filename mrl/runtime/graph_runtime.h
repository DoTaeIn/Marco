#ifndef MRL_GRAPH_RUNTIME_H
#define MRL_GRAPH_RUNTIME_H

/* MRL_MAX_PATHS is an output-enumeration budget, not graph storage. */
#define MRL_MAX_NODES 64
#define MRL_MAX_EDGES 256
#define MRL_MAX_PATHS 256

typedef struct { uint16_t graph; uint32_t id, generation; } MrlNode;
typedef struct { uint16_t relation, member; } MrlRelation;
typedef struct { const char *source, *text; int32_t start, end; } MrlEvidence;
typedef enum { MRL_NO_PATH, MRL_DEPTH_LIMIT, MRL_BUDGET_EXCEEDED, MRL_INVALID_NODE } MrlSearchError;
typedef enum { MRL_SEARCH_BFS, MRL_SEARCH_DFS, MRL_SEARCH_DIJKSTRA, MRL_SEARCH_ASTAR } MrlSearchMethod;
typedef struct MrlPathStorage { uint32_t refs; MrlNode *nodes; uint32_t *edges; } MrlPathStorage;
typedef struct { MrlPathStorage *storage; MrlNode *nodes; uint32_t *edges; uint32_t length; int32_t cost; } MrlPath;
typedef struct { bool ok; MrlPath path; MrlSearchError error; } MrlSearchResult;
typedef struct { MrlPath paths[MRL_MAX_PATHS]; uint16_t length; bool complete; const char *reason; } MrlPathSet;
typedef struct { bool ok; MrlPathSet *paths; MrlSearchError error; } MrlPathsResult;
typedef struct { uint8_t polarity, evidence, traverse; } MrlRelationMeta;
typedef struct { bool live; uint32_t source, target; uint16_t relation; uint32_t order, next_source, next_target; MrlEvidence evidence; } MrlEdge;
typedef struct {
    uint16_t identity, relation_identity, relation_count;
    uint32_t live_nodes, live_edges, node_capacity, edge_capacity, next_node_slot, next_edge_slot, free_nodes_len, free_edges_len, next_edge_order;
    uint32_t *generations, *free_nodes, *free_edges, *out_heads, *in_heads; bool *nodes; MrlEdge *edges; MrlRelationMeta *meta;
    int32_t *edge_costs;
    unsigned char *node_payloads, *edge_payloads;
    size_t node_payload_size, edge_payload_size;
} MrlGraph;

static bool mrl_graph_bytes(size_t count, size_t size, size_t *out) {
    if (size && count > SIZE_MAX / size) return false;
    *out = count * size; return true;
}
static void *mrl_graph_calloc(size_t count, size_t size) {
    size_t bytes; if (!mrl_graph_bytes(count, size, &bytes)) mrl_runtime_fail("MRL graph allocation overflow");
    void *value = calloc(1, bytes); if (!value && bytes) mrl_runtime_fail("MRL graph allocation"); return value;
}
static void mrl_graph_copy(void *to, const void *from, size_t bytes) { unsigned char *out = to; const unsigned char *in = from; while (bytes--) *out++ = *in++; }
static MrlPath mrl_path_copy(MrlPath path) { if (path.storage) { if (path.storage->refs == UINT32_MAX) mrl_runtime_fail("MRL path reference overflow"); ++path.storage->refs; } return path; }
static void mrl_path_release(MrlPath *path) { if (path->storage && !--path->storage->refs) { free(path->storage->nodes); free(path->storage->edges); free(path->storage); } *path = (MrlPath){0}; }
static void mrl_path_free(MrlPath *path) { mrl_path_release(path); }
static void mrl_pathset_release(MrlPathSet *paths) { for (uint16_t i = 0; i < paths->length; ++i) mrl_path_release(&paths->paths[i]); *paths = (MrlPathSet){0}; }
static MrlSearchResult mrl_search_result_copy(MrlSearchResult result) { if (result.ok) result.path = mrl_path_copy(result.path); return result; }
static void mrl_search_result_release(MrlSearchResult *result) { if (result->ok) mrl_path_release(&result->path); *result = (MrlSearchResult){0}; }
static void mrl_graph_destroy(MrlGraph *g) {
    free(g->generations); free(g->free_nodes); free(g->free_edges); free(g->out_heads); free(g->in_heads); free(g->nodes); free(g->edges); free(g->meta); free(g->edge_costs);
    free(g->node_payloads); free(g->edge_payloads); *g = (MrlGraph){0};
}
static void mrl_pathset_copy(MrlPathSet *to, const MrlPathSet *from) {
    if (to == from) return; mrl_pathset_release(to); to->length = from->length; to->complete = from->complete; to->reason = from->reason;
    for (uint16_t i = 0; i < from->length; ++i) to->paths[i] = mrl_path_copy(from->paths[i]);
}
static void mrl_graph_init(MrlGraph *g, uint16_t identity, uint16_t relation_identity, const MrlRelationMeta *meta, uint16_t count) {
    *g = (MrlGraph){0}; g->identity = identity; g->relation_identity = relation_identity; g->relation_count = count;
    if (count) { g->meta = mrl_graph_calloc(count, sizeof(*g->meta)); mrl_graph_copy(g->meta, meta, (size_t)count * sizeof(*meta)); }
}
static void mrl_graph_set_payload_sizes(MrlGraph *g, size_t node_size, size_t edge_size) {
    if (g->live_nodes || g->live_edges) mrl_runtime_fail("MRL graph payload configuration");
    g->node_payload_size = node_size; g->edge_payload_size = edge_size;
}
static bool mrl_node_valid(const MrlGraph *g, MrlNode n);
static bool mrl_graph_reserve_nodes(MrlGraph *g, uint32_t needed) {
    if (needed <= g->node_capacity) return true;
    uint32_t capacity = g->node_capacity ? g->node_capacity : 16;
    while (capacity < needed) { if (capacity > UINT32_MAX / 2) { capacity = UINT32_MAX; break; } capacity *= 2; }
    if (capacity < needed) return false;
    uint32_t *generations = mrl_graph_calloc(capacity, sizeof(*generations)), *free_nodes = mrl_graph_calloc(capacity, sizeof(*free_nodes)), *out_heads = mrl_graph_calloc(capacity, sizeof(*out_heads)), *in_heads = mrl_graph_calloc(capacity, sizeof(*in_heads));
    bool *nodes = mrl_graph_calloc(capacity, sizeof(*nodes));
    unsigned char *payloads = g->node_payload_size ? mrl_graph_calloc(capacity, g->node_payload_size) : NULL;
    for (uint32_t i = 0; i < capacity; ++i) out_heads[i] = in_heads[i] = UINT32_MAX;
    if (g->node_capacity) { mrl_graph_copy(generations, g->generations, (size_t)g->node_capacity * sizeof(*generations)); mrl_graph_copy(free_nodes, g->free_nodes, (size_t)g->free_nodes_len * sizeof(*free_nodes)); mrl_graph_copy(out_heads, g->out_heads, (size_t)g->node_capacity * sizeof(*out_heads)); mrl_graph_copy(in_heads, g->in_heads, (size_t)g->node_capacity * sizeof(*in_heads)); mrl_graph_copy(nodes, g->nodes, (size_t)g->node_capacity * sizeof(*nodes)); if (payloads) mrl_graph_copy(payloads, g->node_payloads, (size_t)g->node_capacity * g->node_payload_size); }
    free(g->generations); free(g->free_nodes); free(g->out_heads); free(g->in_heads); free(g->nodes); free(g->node_payloads); g->generations = generations; g->free_nodes = free_nodes; g->out_heads = out_heads; g->in_heads = in_heads; g->nodes = nodes; g->node_payloads = payloads; g->node_capacity = capacity; return true;
}
static bool mrl_graph_reserve_edges(MrlGraph *g, uint32_t needed) {
    if (needed <= g->edge_capacity) return true;
    uint32_t capacity = g->edge_capacity ? g->edge_capacity : 16;
    while (capacity < needed) { if (capacity > UINT32_MAX / 2) { capacity = UINT32_MAX; break; } capacity *= 2; }
    if (capacity < needed) return false;
    MrlEdge *edges = mrl_graph_calloc(capacity, sizeof(*edges)); uint32_t *free_edges = mrl_graph_calloc(capacity, sizeof(*free_edges)); int32_t *costs = mrl_graph_calloc(capacity, sizeof(*costs));
    unsigned char *payloads = g->edge_payload_size ? mrl_graph_calloc(capacity, g->edge_payload_size) : NULL;
    if (g->edge_capacity) { mrl_graph_copy(edges, g->edges, (size_t)g->edge_capacity * sizeof(*edges)); mrl_graph_copy(free_edges, g->free_edges, (size_t)g->free_edges_len * sizeof(*free_edges)); mrl_graph_copy(costs, g->edge_costs, (size_t)g->edge_capacity * sizeof(*costs)); if (payloads) mrl_graph_copy(payloads, g->edge_payloads, (size_t)g->edge_capacity * g->edge_payload_size); }
    free(g->edges); free(g->free_edges); free(g->edge_costs); free(g->edge_payloads); g->edges = edges; g->free_edges = free_edges; g->edge_costs = costs; g->edge_payloads = payloads; g->edge_capacity = capacity; return true;
}
static void *mrl_graph_node_payload(MrlGraph *g, MrlNode node) {
    if (!mrl_node_valid(g, node) || !g->node_payload_size) mrl_runtime_fail("MRL invalid graph node payload");
    return g->node_payloads + (size_t)node.id * g->node_payload_size;
}
static void *mrl_graph_edge_payload(MrlGraph *g, uint32_t edge) {
    if (edge >= g->edge_capacity || !g->edges[edge].live || !g->edge_payload_size) mrl_runtime_fail("MRL invalid graph edge payload");
    return g->edge_payloads + (size_t)edge * g->edge_payload_size;
}
static bool mrl_node_valid(const MrlGraph *g, MrlNode n) { return n.graph == g->identity && n.id < g->node_capacity && g->nodes[n.id] && g->generations[n.id] == n.generation; }
static MrlNode mrl_graph_add_node(MrlGraph *g) {
    uint32_t i;
    if (g->free_nodes_len) i = g->free_nodes[--g->free_nodes_len];
    else { if (g->next_node_slot == UINT32_MAX) mrl_runtime_fail("MRL graph node capacity"); if (!mrl_graph_reserve_nodes(g, g->next_node_slot + 1)) mrl_runtime_fail("MRL graph node capacity"); i = g->next_node_slot++; }
    if (g->generations[i] == UINT32_MAX) mrl_runtime_fail("MRL graph generation overflow"); if (!g->generations[i]) g->generations[i] = 1; g->nodes[i] = true; ++g->live_nodes; return (MrlNode){g->identity, i, g->generations[i]};
}
static uint32_t mrl_graph_add_edge(MrlGraph *g, MrlNode source, MrlNode target, MrlRelation relation, MrlEvidence evidence) {
    if (!mrl_node_valid(g, source) || !mrl_node_valid(g, target) || relation.relation != g->relation_identity || relation.member >= g->relation_count) mrl_runtime_fail("MRL invalid graph edge");
    uint32_t i;
    if (g->free_edges_len) i = g->free_edges[--g->free_edges_len];
    else { if (g->next_edge_slot == UINT32_MAX) mrl_runtime_fail("MRL graph edge capacity"); if (!mrl_graph_reserve_edges(g, g->next_edge_slot + 1)) mrl_runtime_fail("MRL graph edge capacity"); i = g->next_edge_slot++; }
    if (g->next_edge_order == UINT32_MAX) mrl_runtime_fail("MRL graph edge order overflow"); g->edges[i] = (MrlEdge){true, source.id, target.id, relation.member, ++g->next_edge_order, g->out_heads[source.id], g->in_heads[target.id], evidence}; g->out_heads[source.id] = g->in_heads[target.id] = i; ++g->live_edges; return i;
}
static void mrl_graph_remove(MrlGraph *g, MrlNode node) {
    if (!mrl_node_valid(g, node)) mrl_runtime_fail("MRL invalid graph node");
    g->nodes[node.id] = false; --g->live_nodes; if (g->generations[node.id] == UINT32_MAX) mrl_runtime_fail("MRL graph generation overflow"); ++g->generations[node.id];
    g->free_nodes[g->free_nodes_len++] = node.id;
    for (uint32_t i = 0; i < g->edge_capacity; ++i) if (g->edges[i].live && (g->edges[i].source == node.id || g->edges[i].target == node.id)) { g->edges[i].live = false; g->free_edges[g->free_edges_len++] = i; --g->live_edges; }
}
static bool mrl_allowed(uint16_t relation, const uint16_t *allowed, uint16_t count) { for (uint16_t i = 0; i < count; ++i) if (allowed[i] == relation) return true; return false; }
static bool mrl_edge_destination(const MrlGraph *g, const MrlEdge *e, uint32_t from, bool directed, uint32_t *to) {
    uint8_t traverse = g->meta[e->relation].traverse; if (traverse == 3) return false;
    if (!directed) { if (e->source == from) { *to = e->target; return true; } if (e->target == from) { *to = e->source; return true; } return false; }
    if ((traverse == 0 || traverse == 2) && e->source == from) { *to = e->target; return true; }
    if ((traverse == 1 || traverse == 2) && e->target == from) { *to = e->source; return true; } return false;
}
static int mrl_edge_compare(const MrlGraph *g, uint32_t a, uint32_t b, uint32_t destination_a, uint32_t destination_b) {
    const MrlEdge *left = &g->edges[a], *right = &g->edges[b]; if (left->relation != right->relation) return left->relation < right->relation ? -1 : 1;
    if (destination_a != destination_b) return destination_a < destination_b ? -1 : 1; if (left->order != right->order) return left->order < right->order ? -1 : 1; return a < b ? -1 : a != b;
}
static bool mrl_path_contains(const MrlPath *path, uint32_t id) { for (uint32_t i = 0; i <= path->length; ++i) if (path->nodes[i].id == id) return true; return false; }
static int mrl_path_compare(const MrlGraph *g, const MrlPath *a, const MrlPath *b) {
    uint32_t limit = a->length < b->length ? a->length : b->length; for (uint32_t i = 0; i < limit; ++i) { int edge = mrl_edge_compare(g, a->edges[i], b->edges[i], a->nodes[i + 1].id, b->nodes[i + 1].id); if (edge) return edge; }
    return a->length < b->length ? -1 : a->length != b->length;
}
static MrlPath mrl_path_start(MrlNode source) { MrlPath path = {0}; path.storage = mrl_graph_calloc(1, sizeof(*path.storage)); path.storage->refs = 1; path.nodes = path.storage->nodes = mrl_graph_calloc(1, sizeof(*path.nodes)); path.nodes[0] = source; return path; }
static MrlPath mrl_path_append(const MrlGraph *g, const MrlPath *path, uint32_t edge, uint32_t destination) {
    MrlPath next = {0}; if (path->length == UINT32_MAX) mrl_runtime_fail("MRL graph path length"); next.length = path->length + 1; next.cost = path->cost; next.storage = mrl_graph_calloc(1, sizeof(*next.storage)); next.storage->refs = 1;
    next.nodes = next.storage->nodes = mrl_graph_calloc((size_t)next.length + 1, sizeof(*next.nodes)); next.edges = next.storage->edges = mrl_graph_calloc(next.length, sizeof(*next.edges));
    mrl_graph_copy(next.nodes, path->nodes, ((size_t)path->length + 1) * sizeof(*next.nodes)); if (path->length) mrl_graph_copy(next.edges, path->edges, (size_t)path->length * sizeof(*next.edges));
    next.edges[path->length] = edge; next.nodes[next.length] = (MrlNode){g->identity, destination, g->generations[destination]}; return next;
}
static MrlPath mrl_path_snapshot(MrlGraph *g, const MrlPath *path) { (void)g; return mrl_path_copy(*path); }
typedef struct { MrlPath path; int64_t score; uint32_t serial; } MrlWork;
typedef struct { uint32_t edge, destination; } MrlGraphCandidate;
static int mrl_work_compare(const MrlGraph *g, const MrlWork *a, const MrlWork *b, MrlSearchMethod method) {
    if (method == MRL_SEARCH_DIJKSTRA || method == MRL_SEARCH_ASTAR) { if (a->score != b->score) return a->score < b->score ? -1 : 1; if (a->path.cost != b->path.cost) return a->path.cost < b->path.cost ? -1 : 1; }
    if (a->path.length != b->path.length) return a->path.length < b->path.length ? -1 : 1; int paths = mrl_path_compare(g, &a->path, &b->path); if (paths) return paths; return a->serial < b->serial ? -1 : a->serial != b->serial;
}
static void mrl_work_free(MrlWork *work, uint32_t first, uint32_t last) { for (uint32_t i = first; i < last; ++i) mrl_path_free(&work[i].path); free(work); }
static MrlPathsResult mrl_graph_find_all(MrlGraph *g, bool directed, MrlNode source, MrlNode target, const uint16_t *allowed, uint16_t allowed_count, int32_t max_depth, int32_t max_expansions, int32_t max_paths, MrlSearchMethod method, const int32_t *edge_costs, int32_t (*heuristic)(MrlNode, MrlNode), MrlPathSet *out) {
    MrlPathsResult result = {0}; out->length = 0; out->complete = true; out->reason = "Complete"; result.paths = out;
    if (!mrl_node_valid(g, source) || !mrl_node_valid(g, target)) { result.error = MRL_INVALID_NODE; return result; }
    if (max_paths <= 0 || max_depth < 0 || max_expansions < 0) { result.error = MRL_BUDGET_EXCEEDED; return result; }
    if (max_paths > MRL_MAX_PATHS) max_paths = MRL_MAX_PATHS;
    if ((method == MRL_SEARCH_DIJKSTRA || method == MRL_SEARCH_ASTAR) && !edge_costs) mrl_runtime_fail("MRL weighted search requires edge cost");
    if (method == MRL_SEARCH_DIJKSTRA || method == MRL_SEARCH_ASTAR) for (uint32_t edge = 0; edge < g->edge_capacity; ++edge) if (g->edges[edge].live && mrl_allowed(g->edges[edge].relation, allowed, allowed_count) && g->meta[g->edges[edge].relation].traverse != 3 && edge_costs[edge] < 0) mrl_runtime_fail("MRL negative edge cost");
    uint32_t capacity = 16; MrlWork *work = mrl_graph_calloc(capacity, sizeof(*work)); uint32_t head = 0, tail = 1, serial = 0; int32_t expansions = 0; bool depth_limit = false, budget_limit = false;
    work[0].path = mrl_path_start(source); work[0].serial = serial++; if (method == MRL_SEARCH_ASTAR) { int32_t h = heuristic(source, target); if (h < 0) mrl_runtime_fail("MRL negative heuristic"); work[0].score = h; }
    while (head < tail) {
        uint32_t pick = head; if (method == MRL_SEARCH_DFS) pick = tail - 1; else if (method == MRL_SEARCH_DIJKSTRA || method == MRL_SEARCH_ASTAR) for (uint32_t i = head + 1; i < tail; ++i) if (mrl_work_compare(g, &work[i], &work[pick], method) < 0) pick = i;
        MrlWork current;
        if (method == MRL_SEARCH_BFS) { current = work[head]; work[head].path = (MrlPath){0}; ++head; }
        else { current = work[pick]; if (--tail != pick) work[pick] = work[tail]; }
        uint32_t at = current.path.nodes[current.path.length].id;
        if (at == target.id) { out->paths[out->length++] = mrl_path_snapshot(g, &current.path); mrl_path_free(&current.path); if (out->length == (uint16_t)max_paths) { out->complete = false; out->reason = "PathLimit"; result.ok = true; mrl_work_free(work, head, tail); return result; } continue; }
        if (expansions >= max_expansions) { budget_limit = true; mrl_path_free(&current.path); break; } ++expansions;
        MrlGraphCandidate *candidates = g->live_edges ? mrl_graph_calloc(g->live_edges, sizeof(*candidates)) : NULL; uint32_t count = 0;
        for (uint32_t pass = 0; pass < 2; ++pass) for (uint32_t edge = pass ? g->in_heads[at] : g->out_heads[at]; edge != UINT32_MAX; edge = pass ? g->edges[edge].next_target : g->edges[edge].next_source) { uint32_t to; if (!g->edges[edge].live || !mrl_allowed(g->edges[edge].relation, allowed, allowed_count) || !mrl_edge_destination(g, &g->edges[edge], at, directed, &to) || mrl_path_contains(&current.path, to)) continue; uint32_t place = count++; while (place && mrl_edge_compare(g, edge, candidates[place - 1].edge, to, candidates[place - 1].destination) < 0) { candidates[place] = candidates[place - 1]; --place; } candidates[place] = (MrlGraphCandidate){edge, to}; }
        if (count && current.path.length >= (uint32_t)max_depth) { depth_limit = true; free(candidates); mrl_path_free(&current.path); continue; }
        for (uint32_t step = 0; step < count; ++step) { uint32_t i = method == MRL_SEARCH_DFS ? count - step - 1 : step; if (tail == capacity) { if (capacity == UINT32_MAX) { free(candidates); mrl_path_free(&current.path); mrl_work_free(work, head, tail); mrl_runtime_fail("MRL search allocation"); } uint32_t grown = capacity > UINT32_MAX / 2 ? UINT32_MAX : capacity * 2; MrlWork *more = realloc(work, (size_t)grown * sizeof(*work)); if (!more) { free(candidates); mrl_path_free(&current.path); mrl_work_free(work, head, tail); mrl_runtime_fail("MRL search allocation"); } work = more; capacity = grown; }
            MrlWork next = {0}; next.path = mrl_path_append(g, &current.path, candidates[i].edge, candidates[i].destination); next.serial = serial++;
            if (method == MRL_SEARCH_DIJKSTRA || method == MRL_SEARCH_ASTAR) { int32_t edge_cost = edge_costs[candidates[i].edge]; int64_t total = (int64_t)next.path.cost + edge_cost; if (edge_cost < 0) mrl_runtime_fail("MRL negative edge cost"); if (total > INT32_MAX) mrl_runtime_fail("MRL path cost overflow"); next.path.cost = (int32_t)total; if (method == MRL_SEARCH_ASTAR) { int32_t h = heuristic(next.path.nodes[next.path.length], target); if (h < 0) mrl_runtime_fail("MRL negative heuristic"); total += h; } next.score = total; } else next.path.cost = (int32_t)next.path.length; work[tail++] = next; }
        free(candidates); mrl_path_free(&current.path);
    }
    mrl_work_free(work, head, tail); if (out->length) { result.ok = true; if (budget_limit) { out->complete = false; out->reason = "BudgetExceeded"; } else if (depth_limit) { out->complete = false; out->reason = "DepthLimit"; } return result; }
    result.error = budget_limit ? MRL_BUDGET_EXCEEDED : depth_limit ? MRL_DEPTH_LIMIT : MRL_NO_PATH; return result;
}
static MrlSearchResult mrl_graph_find_method(MrlGraph *g, bool directed, MrlNode source, MrlNode target, const uint16_t *allowed, uint16_t allowed_count, int32_t max_depth, int32_t max_expansions, MrlSearchMethod method, const int32_t *edge_costs, int32_t (*heuristic)(MrlNode, MrlNode)) {
    MrlPathSet one; MrlPathsResult all = mrl_graph_find_all(g, directed, source, target, allowed, allowed_count, max_depth, max_expansions, 1, method, edge_costs, heuristic, &one); MrlSearchResult result = {0}; if (all.ok) { result.ok = true; result.path = one.paths[0]; } else result.error = all.error; return result;
}
/* Kept separate because v3 BFS has node-global visited and frozen budget behavior. */
static MrlSearchResult mrl_graph_find(MrlGraph *g, bool directed, MrlNode source, MrlNode target, const uint16_t *allowed, uint16_t allowed_count, int32_t max_depth, int32_t max_expansions) {
    MrlSearchResult result = {0};
    if (!mrl_node_valid(g, source) || !mrl_node_valid(g, target)) { result.error = MRL_INVALID_NODE; return result; }
    uint32_t capacity = g->node_capacity; uint32_t *queue = mrl_graph_calloc(capacity, sizeof(*queue)), *parent = mrl_graph_calloc(capacity, sizeof(*parent)), *parent_edge = mrl_graph_calloc(capacity, sizeof(*parent_edge));
    int32_t *depth = mrl_graph_calloc(capacity, sizeof(*depth)); bool *seen = mrl_graph_calloc(capacity, sizeof(*seen));
    uint32_t head = 0, tail = 1; int32_t expansions = 0; bool truncated = false; queue[0] = source.id; seen[source.id] = true;
    while (head < tail) {
        uint32_t current = queue[head++];
        if (current == target.id) {
            uint32_t count = 0, at = current; while (at != source.id) { ++count; at = parent[at]; }
            MrlPath path = {0}; path.length = count; path.cost = (int32_t)count; path.storage = mrl_graph_calloc(1, sizeof(*path.storage)); path.storage->refs = 1; path.nodes = path.storage->nodes = mrl_graph_calloc((size_t)count + 1, sizeof(*path.nodes)); path.edges = path.storage->edges = count ? mrl_graph_calloc(count, sizeof(*path.edges)) : NULL;
            at = current; for (uint32_t i = count; i; --i) { path.nodes[i] = (MrlNode){g->identity, at, g->generations[at]}; path.edges[i - 1] = parent_edge[at]; at = parent[at]; } path.nodes[0] = source;
            result.ok = true; result.path = path; free(queue); free(parent); free(parent_edge); free(depth); free(seen); return result;
        }
        if (expansions >= max_expansions) { result.error = MRL_BUDGET_EXCEEDED; free(queue); free(parent); free(parent_edge); free(depth); free(seen); return result; }
        ++expansions;
        for (;;) {
            int64_t best = -1; uint32_t best_to = 0;
            for (uint32_t edge = 0; edge < g->edge_capacity; ++edge) { uint32_t to; const MrlEdge *entry = &g->edges[edge]; if (!entry->live || !mrl_allowed(entry->relation, allowed, allowed_count) || !mrl_edge_destination(g, entry, current, directed, &to) || seen[to]) continue; if (best < 0 || mrl_edge_compare(g, edge, (uint32_t)best, to, best_to) < 0) { best = edge; best_to = to; } }
            if (best < 0) break; if (depth[current] >= max_depth) { truncated = true; break; }
            seen[best_to] = true; parent[best_to] = current; parent_edge[best_to] = (uint32_t)best; depth[best_to] = depth[current] + 1; queue[tail++] = best_to;
        }
    }
    result.error = truncated ? MRL_DEPTH_LIMIT : MRL_NO_PATH; free(queue); free(parent); free(parent_edge); free(depth); free(seen); return result;
}
static const char *mrl_search_error_name(MrlSearchError error) { static const char *names[] = {"NoPath", "DepthLimit", "BudgetExceeded", "InvalidNode"}; return names[error]; }
static int32_t mrl_string_len(const char *s) { int32_t count = 0; for (const unsigned char *p = (const unsigned char *)s; *p; ++p) if ((*p & 0xc0) != 0x80) ++count; return count; }
#endif
