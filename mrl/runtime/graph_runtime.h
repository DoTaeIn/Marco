#ifndef MRL_GRAPH_RUNTIME_H
#define MRL_GRAPH_RUNTIME_H

#define MRL_MAX_NODES 64
#define MRL_MAX_EDGES 256
#define MRL_MAX_PATHS 256

typedef struct { uint16_t graph, id; uint32_t generation; } MrlNode;
typedef struct { uint16_t relation, member; } MrlRelation;
typedef struct { const char *source, *text; int32_t start, end; } MrlEvidence;
typedef enum { MRL_NO_PATH, MRL_DEPTH_LIMIT, MRL_BUDGET_EXCEEDED, MRL_INVALID_NODE } MrlSearchError;
typedef enum { MRL_SEARCH_BFS, MRL_SEARCH_DFS, MRL_SEARCH_DIJKSTRA, MRL_SEARCH_ASTAR } MrlSearchMethod;
typedef struct { MrlNode nodes[MRL_MAX_NODES + 1]; uint16_t edges[MRL_MAX_NODES]; uint16_t length; int32_t cost; } MrlPath;
typedef struct { bool ok; MrlPath path; MrlSearchError error; } MrlSearchResult;
typedef struct { MrlPath paths[MRL_MAX_PATHS]; uint16_t length; bool complete; const char *reason; } MrlPathSet;
typedef struct { bool ok; MrlPathSet *paths; MrlSearchError error; } MrlPathsResult;
typedef struct { uint8_t polarity, evidence, traverse; } MrlRelationMeta;
typedef struct { bool live; uint16_t source, target, relation; uint32_t order; MrlEvidence evidence; } MrlEdge;
typedef struct { uint16_t identity, relation_identity, relation_count, live_nodes; uint32_t next_edge_order; uint32_t generations[MRL_MAX_NODES]; bool nodes[MRL_MAX_NODES]; MrlEdge edges[MRL_MAX_EDGES]; MrlRelationMeta meta[MRL_MAX_EDGES]; } MrlGraph;
static void mrl_pathset_copy(MrlPathSet *to, const MrlPathSet *from) { to->length = from->length; to->complete = from->complete; to->reason = from->reason; for (uint16_t i = 0; i < from->length; ++i) to->paths[i] = from->paths[i]; }

static void mrl_graph_init(MrlGraph *g, uint16_t identity, uint16_t relation_identity, const MrlRelationMeta *meta, uint16_t count) { if (count > MRL_MAX_EDGES) mrl_runtime_fail("MRL graph relation capacity"); *g = (MrlGraph){0}; g->identity = identity; g->relation_identity = relation_identity; g->relation_count = count; for (uint16_t i = 0; i < count; ++i) g->meta[i] = meta[i]; }
static bool mrl_node_valid(const MrlGraph *g, MrlNode n) { return n.graph == g->identity && n.id < MRL_MAX_NODES && g->nodes[n.id] && g->generations[n.id] == n.generation; }
static MrlNode mrl_graph_add_node(MrlGraph *g) { for (uint16_t i = 0; i < MRL_MAX_NODES; ++i) if (!g->nodes[i]) { if (g->generations[i] == UINT32_MAX) mrl_runtime_fail("MRL graph generation overflow"); if (!g->generations[i]) g->generations[i] = 1; g->nodes[i] = true; ++g->live_nodes; return (MrlNode){g->identity, i, g->generations[i]}; } mrl_runtime_fail("MRL graph node capacity"); return (MrlNode){0}; }
static uint16_t mrl_graph_add_edge(MrlGraph *g, MrlNode source, MrlNode target, MrlRelation relation, MrlEvidence evidence) { if (!mrl_node_valid(g, source) || !mrl_node_valid(g, target) || relation.relation != g->relation_identity || relation.member >= g->relation_count) mrl_runtime_fail("MRL invalid graph edge"); for (uint16_t i = 0; i < MRL_MAX_EDGES; ++i) if (!g->edges[i].live) { if (g->next_edge_order == UINT32_MAX) mrl_runtime_fail("MRL graph edge order overflow"); g->edges[i] = (MrlEdge){true, source.id, target.id, relation.member, ++g->next_edge_order, evidence}; return i; } mrl_runtime_fail("MRL graph edge capacity"); return 0; }
static void mrl_graph_remove(MrlGraph *g, MrlNode node) { if (!mrl_node_valid(g, node)) mrl_runtime_fail("MRL invalid graph node"); g->nodes[node.id] = false; --g->live_nodes; if (g->generations[node.id] == UINT32_MAX) mrl_runtime_fail("MRL graph generation overflow"); ++g->generations[node.id]; for (uint16_t i = 0; i < MRL_MAX_EDGES; ++i) if (g->edges[i].live && (g->edges[i].source == node.id || g->edges[i].target == node.id)) g->edges[i].live = false; }
static bool mrl_allowed(uint16_t relation, const uint16_t *allowed, uint16_t count) { for (uint16_t i = 0; i < count; ++i) if (allowed[i] == relation) return true; return false; }
static bool mrl_edge_destination(const MrlGraph *g, const MrlEdge *e, uint16_t from, bool directed, uint16_t *to) { uint8_t traverse = g->meta[e->relation].traverse; if (traverse == 3) return false; if (!directed) { if (e->source == from) { *to = e->target; return true; } if (e->target == from) { *to = e->source; return true; } return false; } if ((traverse == 0 || traverse == 2) && e->source == from) { *to = e->target; return true; } if ((traverse == 1 || traverse == 2) && e->target == from) { *to = e->source; return true; } return false; }
static int mrl_edge_compare(const MrlGraph *g, uint16_t a, uint16_t b, uint16_t destination_a, uint16_t destination_b) { const MrlEdge *left = &g->edges[a], *right = &g->edges[b]; if (left->relation != right->relation) return left->relation < right->relation ? -1 : 1; if (destination_a != destination_b) return destination_a < destination_b ? -1 : 1; if (left->order != right->order) return left->order < right->order ? -1 : 1; return a < b ? -1 : a != b; }
static bool mrl_path_contains(const MrlPath *path, uint16_t id) { for (uint16_t i = 0; i <= path->length; ++i) if (path->nodes[i].id == id) return true; return false; }
static int mrl_path_compare(const MrlGraph *g, const MrlPath *a, const MrlPath *b) { uint16_t limit = a->length < b->length ? a->length : b->length; for (uint16_t i = 0; i < limit; ++i) { int edge = mrl_edge_compare(g, a->edges[i], b->edges[i], a->nodes[i + 1].id, b->nodes[i + 1].id); if (edge) return edge; } return a->length < b->length ? -1 : a->length != b->length; }
typedef struct { MrlPath path; int64_t score; uint32_t serial; } MrlWork;
static int mrl_work_compare(const MrlGraph *g, const MrlWork *a, const MrlWork *b, MrlSearchMethod method) { if (method == MRL_SEARCH_DIJKSTRA || method == MRL_SEARCH_ASTAR) { if (a->score != b->score) return a->score < b->score ? -1 : 1; if (a->path.cost != b->path.cost) return a->path.cost < b->path.cost ? -1 : 1; } if (a->path.length != b->path.length) return a->path.length < b->path.length ? -1 : 1; int paths = mrl_path_compare(g, &a->path, &b->path); if (paths) return paths; return a->serial < b->serial ? -1 : a->serial != b->serial; }
/* ponytail: fixed graph storage; grow the temporary frontier only as candidates require to keep 256 inline paths off Windows debug stacks. */
static MrlPathsResult mrl_graph_find_all(const MrlGraph *g, bool directed, MrlNode source, MrlNode target, const uint16_t *allowed, uint16_t allowed_count, int32_t max_depth, int32_t max_expansions, int32_t max_paths, MrlSearchMethod method, const int32_t *edge_costs, int32_t (*heuristic)(MrlNode, MrlNode), MrlPathSet *out) {
    MrlPathsResult result = {0}; out->length = 0; out->complete = true; out->reason = "Complete"; result.paths = out;
    if (!mrl_node_valid(g, source) || !mrl_node_valid(g, target)) { result.error = MRL_INVALID_NODE; return result; }
    if (max_paths <= 0 || max_depth < 0 || max_expansions < 0) { result.error = MRL_BUDGET_EXCEEDED; return result; }
    if ((method == MRL_SEARCH_DIJKSTRA || method == MRL_SEARCH_ASTAR) && !edge_costs) mrl_runtime_fail("MRL weighted search requires edge cost");
    if (method == MRL_SEARCH_DIJKSTRA || method == MRL_SEARCH_ASTAR)
        for (uint16_t edge = 0; edge < MRL_MAX_EDGES; ++edge)
            if (g->edges[edge].live && mrl_allowed(g->edges[edge].relation, allowed, allowed_count) && g->meta[g->edges[edge].relation].traverse != 3 && edge_costs[edge] < 0)
                mrl_runtime_fail("MRL negative edge cost");
    uint32_t capacity = 16; MrlWork *work = calloc(capacity, sizeof(*work)); if (!work) mrl_runtime_fail("MRL search allocation");
    uint32_t head = 0, tail = 1, serial = 0; int32_t expansions = 0; bool depth_limit = false, budget_limit = false;
    work[0].path.nodes[0] = source; work[0].serial = serial++; if (method == MRL_SEARCH_ASTAR) { int32_t h = heuristic(source, target); if (h < 0) mrl_runtime_fail("MRL negative heuristic"); work[0].score = h; }
    while (head < tail) {
        uint32_t pick = head; if (method == MRL_SEARCH_DFS) pick = tail - 1; else if (method == MRL_SEARCH_DIJKSTRA || method == MRL_SEARCH_ASTAR) for (uint32_t i = head + 1; i < tail; ++i) if (mrl_work_compare(g, &work[i], &work[pick], method) < 0) pick = i;
        MrlWork current = work[pick]; if (method == MRL_SEARCH_BFS) ++head; else { work[pick] = work[--tail]; } uint16_t at = current.path.nodes[current.path.length].id;
        if (at == target.id) { out->paths[out->length++] = current.path; if (out->length == (uint16_t)max_paths) { out->complete = false; out->reason = "PathLimit"; result.ok = true; free(work); return result; } continue; }
        if (expansions >= max_expansions) { budget_limit = true; break; } ++expansions;
        uint16_t candidates[MRL_MAX_EDGES], destinations[MRL_MAX_EDGES], count = 0;
        for (uint16_t edge = 0; edge < MRL_MAX_EDGES; ++edge) { uint16_t to; if (!g->edges[edge].live || !mrl_allowed(g->edges[edge].relation, allowed, allowed_count) || !mrl_edge_destination(g, &g->edges[edge], at, directed, &to) || mrl_path_contains(&current.path, to)) continue; uint16_t place = count++; while (place && mrl_edge_compare(g, edge, candidates[place - 1], to, destinations[place - 1]) < 0) { candidates[place] = candidates[place - 1]; destinations[place] = destinations[place - 1]; --place; } candidates[place] = edge; destinations[place] = to; }
        if (count && current.path.length >= max_depth) { depth_limit = true; continue; }
        for (uint16_t step = 0; step < count; ++step) { uint16_t i = method == MRL_SEARCH_DFS ? count - step - 1 : step; if (tail == capacity) { uint32_t grown = capacity > UINT32_MAX / 2 ? UINT32_MAX : capacity * 2; MrlWork *more = realloc(work, (size_t)grown * sizeof(*work)); if (!more) { free(work); mrl_runtime_fail("MRL search allocation"); } work = more; capacity = grown; } MrlWork next = {0}; next.path = current.path; next.path.edges[next.path.length] = candidates[i]; next.path.nodes[++next.path.length] = (MrlNode){g->identity, destinations[i], g->generations[destinations[i]]}; next.serial = serial++; if (method == MRL_SEARCH_DIJKSTRA || method == MRL_SEARCH_ASTAR) { int32_t edge_cost = edge_costs[candidates[i]]; if (edge_cost < 0) mrl_runtime_fail("MRL negative edge cost"); int64_t total = (int64_t)next.path.cost + edge_cost; if (total > INT32_MAX) mrl_runtime_fail("MRL path cost overflow"); next.path.cost = (int32_t)total; if (method == MRL_SEARCH_ASTAR) { int32_t h = heuristic(next.path.nodes[next.path.length], target); if (h < 0) mrl_runtime_fail("MRL negative heuristic"); total += h; } next.score = total; } else next.path.cost = next.path.length; work[tail++] = next; }
        if (budget_limit) break;
    }
    free(work); if (out->length) { result.ok = true; if (budget_limit) { out->complete = false; out->reason = "BudgetExceeded"; } else if (depth_limit) { out->complete = false; out->reason = "DepthLimit"; } return result; } result.error = budget_limit ? MRL_BUDGET_EXCEEDED : depth_limit ? MRL_DEPTH_LIMIT : MRL_NO_PATH; return result;
}
static MrlSearchResult mrl_graph_find_method(const MrlGraph *g, bool directed, MrlNode source, MrlNode target, const uint16_t *allowed, uint16_t allowed_count, int32_t max_depth, int32_t max_expansions, MrlSearchMethod method, const int32_t *edge_costs, int32_t (*heuristic)(MrlNode, MrlNode)) { static MrlPathSet one; MrlPathsResult all = mrl_graph_find_all(g, directed, source, target, allowed, allowed_count, max_depth, max_expansions, 1, method, edge_costs, heuristic, &one); MrlSearchResult result = {0}; if (all.ok) { result.ok = true; result.path = one.paths[0]; } else result.error = all.error; return result; }
/* Kept separate: v3 BFS has frozen node-global visited and budget behavior. */
static MrlSearchResult mrl_graph_find(const MrlGraph *g, bool directed, MrlNode source, MrlNode target, const uint16_t *allowed, uint16_t allowed_count, int32_t max_depth, int32_t max_expansions) {
    MrlSearchResult result = {0};
    if (!mrl_node_valid(g, source) || !mrl_node_valid(g, target)) { result.error = MRL_INVALID_NODE; return result; }
    result.path.nodes[0] = source;
    if (source.id == target.id) { result.ok = true; return result; }
    uint16_t queue[MRL_MAX_NODES], head = 0, tail = 1, parent[MRL_MAX_NODES], parent_edge[MRL_MAX_NODES];
    int32_t depth[MRL_MAX_NODES] = {0}; bool seen[MRL_MAX_NODES] = {0}, truncated = false;
    queue[0] = source.id; seen[source.id] = true; int32_t expansions = 0;
    while (head < tail) {
        uint16_t current = queue[head++];
        if (current == target.id) { uint16_t reversed[MRL_MAX_NODES], count = 0, at = current; while (at != source.id) { reversed[count++] = at; at = parent[at]; } result.path.length = count; result.path.cost = count; for (uint16_t i = 0; i < count; ++i) { uint16_t node = reversed[count - i - 1]; result.path.nodes[i + 1] = (MrlNode){g->identity, node, g->generations[node]}; result.path.edges[i] = parent_edge[node]; } result.ok = true; return result; }
        if (expansions >= max_expansions) { result.error = MRL_BUDGET_EXCEEDED; return result; }
        ++expansions;
        for (;;) { int best = -1; uint16_t best_to = 0; for (uint16_t i = 0; i < MRL_MAX_EDGES; ++i) { uint16_t to; const MrlEdge *e = &g->edges[i]; if (!e->live || !mrl_allowed(e->relation, allowed, allowed_count) || !mrl_edge_destination(g, e, current, directed, &to) || seen[to]) continue; if (best < 0 || mrl_edge_compare(g, i, (uint16_t)best, to, best_to) < 0) { best = i; best_to = to; } } if (best < 0) break; if (depth[current] >= max_depth) { truncated = true; break; } seen[best_to] = true; parent[best_to] = current; parent_edge[best_to] = (uint16_t)best; depth[best_to] = depth[current] + 1; queue[tail++] = best_to; }
    }
    result.error = truncated ? MRL_DEPTH_LIMIT : MRL_NO_PATH; return result;
}
static const char *mrl_search_error_name(MrlSearchError error) { static const char *names[] = {"NoPath", "DepthLimit", "BudgetExceeded", "InvalidNode"}; return names[error]; }
static int32_t mrl_string_len(const char *s) { int32_t count = 0; for (const unsigned char *p = (const unsigned char *)s; *p; ++p) if ((*p & 0xc0) != 0x80) ++count; return count; }
#endif
