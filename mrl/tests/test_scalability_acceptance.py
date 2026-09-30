"""Independent source acceptance for graph growth, dynamic rules and indexed IO."""
import json
import tempfile
import unittest
from pathlib import Path
from mrl.tests.test_language_acceptance import native


class GraphGrowthAcceptanceTests(unittest.TestCase):
    def test_long_path_and_owned_payloads_survive_growth_and_later_search(self):
        result = native("""
struct Point { name: s }
struct Road { distance: si }
relation Route { Link { polarity: positive evidence: optional traverse: forward } }
graph g { node: Point relation: Route edge: Road }
fn main() {
 knowledge = Horn(memory_budget=6000000,capacity=64,facts=Facts(),rules=Rules())
 start = g.add(Point(name="sta" + "rt"))
 last = start
 for (i in 0..300) {
  next = g.add(Point(name="no" + "de"))
  g.add(last,next,Route.Link,Road(distance=1))
  last := next
 }
 saved = g.find(start,last) { method: dijkstra cost: edge.distance max_depth: 512 max_expansions: 1000 }
 for (i in 0..600) { unused = g.add(Point(name="ex" + "tra")) }
 fresh = g.find(start,last) { method: bfs max_depth: 512 max_expansions: 1000 }
 match(saved) { Ok(path) { print(path.len) print(path.cost) } Err(error) { print(error) } }
 match(fresh) { Ok(path) { print(path.len) } Err(error) { print(error) } }
 g.remove(start)
 replacement = g.add(Point(name="re" + "used"))
 stale = g.find(start,last) { max_depth: 512 }
 match(stale) { Ok(path) { print(999) } Err(error) { print("stale") } }
 match(saved) { Ok(path) { print(path.len) } Err(error) { print(error) } }
}
""", track=True)
        self.assertEqual((result.returncode, result.stdout.splitlines()),
                         (0, ["300", "300", "300", "stale", "300"]), result.stderr)


    def test_recursive_pathsets_keep_their_results_and_release_storage(self):
        result=native("""
struct Point { value:si }
struct Road { distance:si }
relation Route { Link { polarity:positive evidence:none traverse:forward } }
graph g { node:Point relation:Route edge:Road }
fn search(depth:si)->si {
 a=g.add(Point(value=depth)) b=g.add(Point(value=depth))
 g.add(a,b,Route.Link,Road(distance=depth+1))
 saved=g.find_all(a,b) { method:dijkstra cost:edge.distance max_paths:2 }
 if(depth>0) { if(search(depth-1)!=depth) { return -1000 } }
 match(saved) { Ok(paths) { return paths[0].cost } Err(error) { return -2000 } }
}
fn main() {
 print(search(4))
 for(i in 0..100) { if(search(0)!=1) { print(-3000) return } }
 print(1)
}
""",track=True)
        self.assertEqual((result.returncode,result.stdout.splitlines()),(0,["5","1"]),result.stderr)


class RuntimeRuleAcceptanceTests(unittest.TestCase):
    def test_raw_rule_payload_cannot_escape_or_forge_argument_order(self):
        from copy import deepcopy
        from mrl.frontend import compile_source
        from mrl.c_backend import emit_c
        ir=compile_source('''fn main(){p=Horn(memory_budget=6000000,capacity=64,facts=Facts(),rules=Rules())
 p.add_rule(Rule(id="pq",body=Triple("?x","p","?y"),head=Triple("?x","q","?y")))}''')
        call=ir["functions"][0]["body"][1]["value"]
        escaped=deepcopy(ir)
        escaped["functions"][0]["body"].append({"kind":"expr","value":deepcopy(call["rule"])})
        with self.assertRaisesRegex(ValueError,"Rule values"):
            emit_c(escaped)
        malformed=deepcopy(ir)
        malformed["functions"][0]["body"][1]["value"]["rule"]["head"]["eval_order"]=[0,{},2]
        with self.assertRaises(ValueError):
            emit_c(malformed)

    def test_dynamic_rules_invalidate_chains_and_preserve_snapshot_proofs(self):
        result = native("""
fn rule_name()->s { return "dynamic" }
fn unsafe_variable()->s { return "?missing" }
fn main() {
 p: Horn = Horn(memory_budget=6000000,capacity=64,
  facts=Facts(Fact(id="seed",subject="a",predicate="p",object="z")),rules=Rules())
 predicate = "q"
 if(not p.add_rule(Rule(id=rule_name(),version=1,body=All(Triple("?x","p","?y")),head=Triple("?x",predicate,"?y")))) { print(901) return }
 old = p.select(predicate=predicate,proof_limit=8,search_limit=4096)
 if(not p.add_rule(Rule(id="chain",version=1,body=All(Triple("?x","q","?y")),head=Triple("?x","r","?y")))) { print(902) return }
 print(p.exists(Triple("a","r","z")))
 if(not p.replace_rule(rule_name(),Rule(id=rule_name(),version=2,body=All(Triple("?x","p","?y")),head=Triple("?x","t","?y")))) { print(903) return }
 print(p.exists(Triple("a","q","z")))
 print(p.exists(Triple("a","r","z")))
 print(p.exists(Triple("a","t","z")))
 print(old.proof_count(0)) print(old.proof_rule(0,0)) print(old.proof_rule_version(0,0)) print(old.proof_premise_id(0,0,0))
 print(p.remove_rule(rule_name()))
 print(p.exists(Triple("a","t","z")))
 print(p.remove_rule(rule_name()))
 print(p.add_rule(Rule(id="invalid",version=1,body=All(Triple("?x","p","?y")),head=Triple(unsafe_variable(),"bad","?y"))))
 print(p.count())
}
""", track="poison")
        self.assertEqual((result.returncode, result.stdout.splitlines()),
                         (0, ["true", "false", "false", "true", "1", "dynamic", "1", "seed", "true", "false", "false", "false", "1"]), result.stderr)


    def test_rule_arguments_evaluate_once_in_written_order(self):
        result = native("""
fn term(n:si,value:s)->s { print(n) return value }
fn main() {
 p = Horn(memory_budget=6000000,capacity=64,
  facts=Facts(Fact(id="seed",subject="a",predicate="p",object="b")),rules=Rules())
 print(p.add_rule(Rule(
  head=Triple(object=term(1,"?y"),subject=term(2,"?x"),predicate=term(3,"q")),
  body=Triple(predicate=term(4,"p"),object=term(5,"?y"),subject=term(6,"?x")),
  id=term(7,"pq"),version=term(8,"v1"))))
 print(p.exists(Triple("a","q","b")))
 answer=p.select(predicate="q",proof_limit=8,search_limit=4096)
 print(answer.proof_rule_version(0,0))
}
""",track="poison")
        self.assertEqual((result.returncode,result.stdout.splitlines()),
                         (0,["1","2","3","4","5","6","7","8","true","true",'"v1"']),result.stderr)

    def test_rule_edits_commit_and_restore_in_fresh_native_processes(self):
        common = """
fn initial()->Horn { return Horn(memory_budget=8000000,capacity=64,
 facts=Facts(Fact(id="first",subject="a",predicate="p",object="b"),
             Fact(id="second",subject="b",predicate="p",object="c")),rules=Rules()) }
"""
        with tempfile.TemporaryDirectory(prefix="mrl-rule-acceptance-") as directory:
            path = json.dumps(str(Path(directory)/"rules.mrlk").replace("\\", "/"))
            write = native(common + """
fn main() {
 p = initial()
 match(p.save(PATH)) { Ok(n) { print(true) } Err(e) { print(e) } }
 print(p.add_rule(Rule(id="join",version=1,body=All(Triple("?x","p","?m"),Triple("?m","p","?y")),head=Triple("?x","r","?y"))))
 old = p
 print(p.replace_rule("join",Rule(id="join",version=2,body=All(Triple("?x","p","?m"),Triple("?m","p","?y")),head=Triple("?x","t","?y"))))
 print(old.exists(Triple("a","r","c")))
 print(old.exists(Triple("a","t","c")))
 match(p.commit(PATH)) { Ok(n) { print(true) } Err(e) { print(e) } }
}
""".replace("PATH",path),track="poison")
            self.assertEqual((write.returncode,write.stdout.splitlines()),
                             (0,["true","true","true","true","false","true"]),write.stderr)
            restore = native(common + """
fn main() {
 p = initial()
 match(p.restore(PATH)) { Ok(n) { print(true) } Err(e) { print(e) } }
 print(p.exists(Triple("a","r","c")))
 print(p.exists(Triple("a","t","c")))
 answer = p.select(predicate="t",proof_limit=8,search_limit=4096)
 print(answer.proof_rule(0,0)) print(answer.proof_rule_version(0,0))
 print(answer.proof_premise_count(0,0))
 print(p.remove_rule("join"))
 match(p.commit(PATH)) { Ok(n) { print(true) } Err(e) { print(e) } }
}
""".replace("PATH",path),track="poison")
            self.assertEqual((restore.returncode,restore.stdout.splitlines()),
                             (0,["true","false","true","join","2","2","true","true"]),restore.stderr)
            removed = native(common + """
fn main() {
 p = initial()
 match(p.restore(PATH)) { Ok(n) { print(true) } Err(e) { print(e) } }
 print(p.exists(Triple("a","t","c"))) print(p.count())
}
""".replace("PATH",path),track="poison")
            self.assertEqual((removed.returncode,removed.stdout.splitlines()),
                             (0,["true","false","2"]),removed.stderr)


class IndexedSourceAcceptanceTests(unittest.TestCase):
    def test_selective_queries_and_durable_edits_across_native_processes(self):
        checked = """
fn checked(r:Result<b,s>)->b {
 match(r) { Ok(value) { return value } Err(error) { print(error) return false } }
}
"""
        with tempfile.TemporaryDirectory(prefix="mrl-indexed-acceptance-") as directory:
            path=json.dumps(str(Path(directory)/"facts.db").replace("\\","/"))
            saved=native("""
fn main() {
 p=Horn(memory_budget=8000000,capacity=64,
  facts=Facts(Fact(id="seed",subject="가",predicate="p",object="🙂"),
   Fact(id="planned",subject="hidden",predicate="p",object="🙂",modality="planned")),
  rules=Rules(Rule(id="pq",body=All(Triple("?x","p","?y")),head=Triple("?x","q","?y"))))
 match(p.save_indexed(PATH)) { Ok(n) { print("saved") } Err(error) { print(error) } }
}
""".replace("PATH",path),track=True)
            self.assertEqual((saved.returncode,saved.stdout.splitlines()),(0,["saved"]),saved.stderr)
            edited=native(checked+"""
fn main() {
 print(checked(indexed_exists(PATH,Triple("가","p","🙂"))))
 print(checked(indexed_exists(PATH,Triple("가","q","🙂"))))
 print(checked(indexed_exists(PATH,Triple("hidden","p","🙂"))))
 print(checked(indexed_correct(PATH,Fact(id="seed",subject="가",predicate="r",object="🙂"))))
 print(checked(indexed_add(PATH,Fact(id="deny",subject="가",predicate="r",object="🙂",polarity=false))))
 print(checked(indexed_exists(PATH,Triple("가","r","🙂"))))
 print(checked(indexed_remove(PATH,"deny")))
 print(checked(indexed_exists(PATH,Triple("가","r","🙂"))))
 print(checked(indexed_add(PATH,Fact(id="seed",subject="wrong",predicate="r",object="🙂"))))
 print(checked(indexed_remove(PATH,"missing")))
}
""".replace("PATH",path),track=True)
            self.assertEqual((edited.returncode,edited.stdout.splitlines()),
                             (0,["true","false","false","true","true","false","true","true","false","false"]),edited.stderr)
            reopened=native(checked+"""
fn main() {
 print(checked(indexed_exists(PATH,Triple("가","r","🙂"))))
 print(checked(indexed_exists(PATH,Triple("가","p","🙂"))))
 print(checked(indexed_exists(PATH,Triple("wrong","r","🙂"))))
}
""".replace("PATH",path),track=True)
            self.assertEqual((reopened.returncode,reopened.stdout.splitlines()),(0,["true","false","false"]),reopened.stderr)


if __name__ == "__main__": unittest.main()
