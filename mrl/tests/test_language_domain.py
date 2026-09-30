import subprocess
import tempfile
import unittest
from pathlib import Path

from mrl.toolchain import build_c
from mrl.frontend import compile_source
from mrl.c_backend import emit_c

ROOT = Path(__file__).resolve().parents[1]


def source_run(source):
    with tempfile.TemporaryDirectory(prefix="mrl-domain-source-") as directory:
        c_path, exe = Path(directory) / "source.c", Path(directory) / "source.exe"
        c_path.write_text(emit_c(compile_source(source)), encoding="utf-8")
        build_c(c_path, exe)
        return subprocess.run([str(exe)], capture_output=True, text=True, timeout=10)


def header(name):
    return f'#include "{(ROOT / "runtime" / name).as_posix()}"\n'


class LanguageDomainRuntimeTests(unittest.TestCase):
    def test_candidate_constraints_and_budgets(self):
        source = '''#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <stdint.h>
static void mrl_runtime_fail(const char *s){fprintf(stderr,"%s",s);exit(90);}
''' + "".join(header(name) for name in (
            "knowledge_store.h", "knowledge_engine.h", "horn_jsonl.h",
            "knowledge_persist.h", "knowledge_cache.h", "knowledge_journal.h",
            "horn_runtime_v7.h")) + r'''
int main(void){
 MrlHornPlanFact left_facts[]={{"left","a","p","x","asserted",1,{0}}};
 MrlHornPlanFact right_facts[]={{"right","b","p","x","asserted",1,{0}}};
 MrlHornPlanFact conflict_facts[]={{"yes","z","q","x","asserted",1,{0}},{"no","z","q","x","asserted",0,{0}}};
 MrlHornPlanFact derived_facts[]={{"premise","a","p","x","asserted",1,{0}},{"deny","a","q","x","asserted",0,{0}}};
 MrlHornPlanRule derived_rules[]={{"pq",NULL,1,{{"?s","p","?o"}},{"?s","q","?o"}}};
 MrlHornPlanTemplate left_t={left_facts,1,NULL,0,16,3000000},right_t={right_facts,1,NULL,0,16,3000000},conflict_t={conflict_facts,2,NULL,0,16,3000000},derived_t={derived_facts,2,derived_rules,1,16,3000000};
 MrlHornPlan *left=mrl_horn_plan_new(&left_t),*right=mrl_horn_plan_new(&right_t),*conflict=mrl_horn_plan_new(&conflict_t),*derived=mrl_horn_plan_new(&derived_t);
 MrlHornSnapshot *ls=mrl_horn_plan_select(left,NULL,NULL,NULL),*rs=mrl_horn_plan_select(right,NULL,NULL,NULL),*cs=mrl_horn_plan_select(conflict,NULL,NULL,NULL),*ds=mrl_horn_plan_select(derived,NULL,NULL,NULL);
 MrlCandidate *a=mrl_candidate_new("a",ls),*b=mrl_candidate_new("b",rs),*bad=mrl_candidate_new("bad",cs),*derived_bad=mrl_candidate_new("derived_bad",ds);
 MrlCandidate *two[]={a,b},*one[]={a},*contradicted[]={bad},*derived_contradicted[]={derived_bad};MrlCandidates *both=mrl_candidates_new(two,2),*single=mrl_candidates_new(one,1),*negative=mrl_candidates_new(contradicted,1),*derived_negative=mrl_candidates_new(derived_contradicted,1);
 MrlConstraint *required=mrl_constraint_new(1,(const char*[]){"a","p","x"},0,NULL,true),*consistent=mrl_constraint_new(0,NULL,0,NULL,true);
 MrlConstraint *required_only[]={required},*consistent_only[]={consistent};MrlConstraints *req=mrl_constraints_new(required_only,1),*check=mrl_constraints_new(consistent_only,1),*empty=mrl_constraints_new(NULL,0);
 MrlInterpretation *i=mrl_horn_interpret(single,req,32),*amb=mrl_horn_interpret(both,empty,32),*contra=mrl_horn_interpret(negative,check,32),*derived_contra=mrl_horn_interpret(derived_negative,check,64),*unknown=mrl_horn_interpret(single,check,1);
 if(i->status!=MRL_INTERPRETATION_SELECTED||!mrl_interpretation_candidate_id_some(i)||strcmp(mrl_interpretation_candidate_id(i),"a"))return 1;
 if(amb->status!=MRL_INTERPRETATION_AMBIGUOUS||mrl_interpretation_candidate_id_some(amb))return 2;
 if(contra->status!=MRL_INTERPRETATION_CONTRADICTED)return 3;
 if(derived_contra->status!=MRL_INTERPRETATION_CONTRADICTED)return 5;
 if(unknown->status!=MRL_INTERPRETATION_INCOMPLETE||unknown->complete)return 4;
 mrl_interpretation_release(i);mrl_interpretation_release(amb);mrl_interpretation_release(contra);mrl_interpretation_release(derived_contra);mrl_interpretation_release(unknown);
 mrl_constraints_release(empty);mrl_constraints_release(check);mrl_constraints_release(req);mrl_constraint_release(required);mrl_constraint_release(consistent);
 mrl_candidates_release(both);mrl_candidates_release(single);mrl_candidates_release(negative);mrl_candidates_release(derived_negative);mrl_candidate_release(a);mrl_candidate_release(b);mrl_candidate_release(bad);mrl_candidate_release(derived_bad);
 mrl_horn_snapshot_release(ls);mrl_horn_snapshot_release(rs);mrl_horn_snapshot_release(cs);mrl_horn_snapshot_release(ds);mrl_horn_plan_release(left);mrl_horn_plan_release(right);mrl_horn_plan_release(conflict);mrl_horn_plan_release(derived);return 0;
}'''
        with tempfile.TemporaryDirectory(prefix="mrl-domain-") as directory:
            c_path, exe = Path(directory) / "domain.c", Path(directory) / "domain.exe"
            c_path.write_text(source, encoding="utf-8")
            build_c(c_path, exe)
            subprocess.run([str(exe)], check=True, capture_output=True, text=True)


    def test_domain_apis_from_mrl_source(self):
        run = source_run(r"""
fn tick_subject() -> s { print("subject") return "a" }
fn main() -> si {
  p: Horn = Horn(memory_budget=4000000, capacity=16,
    facts=Facts(
      Fact(id="premise", subject="a", predicate="p", object="x"),
      Fact(id="denial", subject="a", predicate="q", object="x", polarity=false)),
    rules=Rules(Rule(id="pq", version=1,
      body=All(Triple("?s", "p", "?o")), head=Triple("?s", "q", "?o"))))
  limited = p.select(subject=tick_subject(), predicate="q", limit=1, proof_limit=2, search_limit=256)
  if (limited.fact_count != 0) { return 1 }
  if (p.status(Triple("a", "q", "x")) != EpistemicState.contradicted) { return 2 }
  if (p.status(Triple("a", "p", "x")) != EpistemicState.known) { return 3 }
  if (p.status(Triple("missing", "p", "x")) != EpistemicState.unknown) { return 4 }
  bad = Candidate(id="bad", meaning=p.select(subject="a", predicate="p"))
  bad_set = Candidates(bad)
  inconsistent = Constraints(Constraint(consistent=true))
  if (interpret(bad_set, inconsistent, budget=128).status != InterpretationStatus.contradicted) { return 5 }
  required = Constraints(Constraint(required=Triple("a", "p", "x"), consistent=false))
  selected = interpret(bad_set, required, budget=128)
  if (selected.status != InterpretationStatus.selected) { return 6 }
  match (selected.candidate_id) { Some(id) { if (id != "bad") { return 7 } } none { return 8 } }
  if (interpret(bad_set, required, budget=1).status != InterpretationStatus.incomplete) { return 9 }
  if (interpret(Candidates(), Constraints(), budget=128).status != InterpretationStatus.unknown) { return 10 }
  ambiguous = interpret(Candidates(bad, Candidate(id="other", meaning=p.select(subject="a", predicate="p"))), Constraints(), budget=128)
  if (ambiguous.status != InterpretationStatus.ambiguous) { return 11 }
  match (ambiguous.candidate_id) { Some(id) { return 15 } none { } }
  derived: Horn = Horn(memory_budget=4000000, capacity=16,
    facts=Facts(Fact(id="seed", subject="a", predicate="p", object="x")),
    rules=Rules(Rule(id="pq", version=1,
      body=All(Triple("?s", "p", "?o")), head=Triple("?s", "q", "?o"))))
  proof = derived.select(predicate="q", proof_limit=4, search_limit=256)
  if (proof.fact_count != 1 or proof.proof_count(0) != 1) { return 12 }
  if (proof.proof_premise_count(0, 0) != 1 or proof.proof_binding_count(0, 0) != 2) { return 13 }
  if (proof.proof_binding_name(0, 0, 0) != "?s" or proof.proof_binding_value(0, 0, 0) != "a") { return 14 }
  return 0
}
""")
        self.assertEqual((run.returncode, run.stdout.splitlines()), (0, ["subject", "0"]), run.stderr)



    def test_alternate_proofs_are_stable_after_plan_edit(self):
        source = '''#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <stdint.h>
static void mrl_runtime_fail(const char *s){fprintf(stderr,"%s",s);exit(90);}
''' + "".join(header(name) for name in (
            "knowledge_store.h", "knowledge_engine.h", "horn_jsonl.h",
            "knowledge_persist.h", "knowledge_cache.h", "knowledge_journal.h",
            "horn_runtime_v7.h")) + r'''
int main(void){
 MrlHornPlanFact facts[]={
  {"direct","a","q","x","asserted",1,{0}},
  {"left","a","p","x","asserted",1,{0}},
  {"right","a","r","x","asserted",1,{0}}};
 MrlHornPlanRule rules[]={
  {"from_p","1",1,{{"?s","p","?o"}},{"?s","q","?o"}},
  {"from_r","2",1,{{"?s","r","?o"}},{"?s","q","?o"}}};
 MrlHornPlanTemplate t={facts,3,rules,2,16,3000000};MrlHornPlan*p=mrl_horn_plan_new(&t);
 MrlHornSnapshot*old=mrl_horn_plan_select(p,"a","q","x");
 if(old->count!=1||mrl_horn_snapshot_proof_count_at(old,0)!=3)return 1;
 if(strcmp(mrl_horn_snapshot_proof_id(old,0,0),"direct")||strcmp(mrl_horn_snapshot_proof_kind(old,0,0),"asserted"))return 2;
 if(strcmp(mrl_horn_snapshot_proof_rule(old,0,1),"from_p")||strcmp(mrl_horn_snapshot_proof_rule_version(old,0,1),"1"))return 3;
 if(strcmp(mrl_horn_snapshot_proof_premise_id(old,0,1,0),"left"))return 4;
 if(strcmp(mrl_horn_snapshot_proof_rule(old,0,2),"from_r")||strcmp(mrl_horn_snapshot_proof_rule_version(old,0,2),"2"))return 5;
 if(strcmp(mrl_horn_snapshot_proof_premise_id(old,0,2,0),"right"))return 6;
 if(mrl_horn_snapshot_proof_binding_count(old,0,1)!=2||strcmp(mrl_horn_snapshot_proof_binding_name(old,0,1,0),"?s")||strcmp(mrl_horn_snapshot_proof_binding_value(old,0,1,0),"a")||strcmp(mrl_horn_snapshot_proof_binding_name(old,0,1,1),"?o")||strcmp(mrl_horn_snapshot_proof_binding_value(old,0,1,1),"x"))return 7;
 if(!mrl_horn_plan_remove(&p,"left"))return 8;
 MrlHornSnapshot*fresh=mrl_horn_plan_select(p,"a","q","x");
 if(mrl_horn_snapshot_proof_count_at(fresh,0)!=2)return 9;
 if(mrl_horn_snapshot_proof_count_at(old,0)!=3||strcmp(mrl_horn_snapshot_proof_rule(old,0,1),"from_p")||strcmp(mrl_horn_snapshot_proof_premise_id(old,0,1,0),"left"))return 10;
 mrl_horn_snapshot_release(fresh);mrl_horn_snapshot_release(old);mrl_horn_plan_release(p);return 0;
}'''
        with tempfile.TemporaryDirectory(prefix="mrl-domain-proof-") as directory:
            c_path, exe = Path(directory) / "proof.c", Path(directory) / "proof.exe"
            c_path.write_text(source, encoding="utf-8")
            build_c(c_path, exe)
            subprocess.run([str(exe)], check=True, capture_output=True, text=True, timeout=10)

    def test_history_keeps_negative_facts_and_rejects_reused_ids_atomically(self):
        source = '''#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <stdint.h>
static void mrl_runtime_fail(const char *s){fprintf(stderr,"%s",s);exit(90);}
''' + "".join(header(name) for name in (
            "knowledge_store.h", "knowledge_engine.h", "horn_jsonl.h",
            "knowledge_persist.h", "knowledge_cache.h", "knowledge_journal.h",
            "horn_runtime_v7.h")) + r'''
int main(void){
 MrlHornPlanFact fact={"old","a","p","x","asserted",0,{0}};
 MrlHornPlanTemplate small={&fact,1,NULL,0,1,3000000},wide={&fact,1,NULL,0,8,3000000};
 MrlHornPlan*p=mrl_horn_plan_new(&small);uint64_t version=p->store->version;uint32_t symbols=p->store->symbols->next;size_t count=p->store->count;
 if(mrl_horn_plan_replace(&p,"old","fresh","new","p","x",true,"asserted",(MrlHornEvidence){0}))return 1;
 if(p->store->version!=version||p->store->symbols->next!=symbols||p->store->count!=count||!mrl_knowledge_store_find_id(p->store,mrl_knowledge_store_find_symbol(p->store,"old")))return 2;
 mrl_horn_plan_release(p);
 p=mrl_horn_plan_new(&wide);
 if(!mrl_horn_plan_supersede(&p,"old","new","a","p","y",true,"asserted",(MrlHornEvidence){0}))return 3;
 MrlHornSnapshot*history=mrl_horn_plan_history_fact(p,"old");
 if(history->count!=1||mrl_horn_snapshot_polarity(history,0)||strcmp(mrl_horn_snapshot_term(history,0,2),"x"))return 4;
 version=p->store->version;symbols=p->store->symbols->next;count=p->store->count;
 if(mrl_horn_plan_replace(&p,"new","old","a","p","z",true,"asserted",(MrlHornEvidence){0}))return 5;
 if(p->store->version!=version||p->store->symbols->next!=symbols||p->store->count!=count)return 6;
 if(strcmp(mrl_horn_plan_superseded_by(p,"old","mrl:supersededBy"),"new"))return 7;
 mrl_horn_snapshot_release(history);mrl_horn_plan_release(p);return 0;
}'''
        with tempfile.TemporaryDirectory(prefix="mrl-domain-history-") as directory:
            c_path, exe = Path(directory) / "history.c", Path(directory) / "history.exe"
            c_path.write_text(source, encoding="utf-8")
            build_c(c_path, exe)
            subprocess.run([str(exe)], check=True, capture_output=True, text=True, timeout=10)



if __name__ == "__main__":
    unittest.main()

