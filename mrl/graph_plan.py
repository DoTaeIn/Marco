"""Checked one-premise Horn plans compiled to native matcher hooks."""
from __future__ import annotations
from functools import lru_cache
import struct,tempfile
from pathlib import Path
from mrl import native_graph,toolchain
_SOURCE=Path(__file__).with_name("runtime")/"native_graph.c"
_WRAPPER=b'#define MRL_GRAPH_PLAN_HEADER "graph_plan.h"\n#include "native_graph.c"\n'
def _term(x):
    if type(x)is not int or not -(2**31)<=x<=2**31-1:raise ValueError("invalid graph-plan term")
    return x
def _rows(ir):
    if not isinstance(ir,dict) or set(ir)!={"version","kind","rules"} or type(ir["version"]) is not int or ir["version"]!=1 or ir["kind"]!="horn_graph_plan" or not isinstance(ir["rules"],list) or len(ir["rules"])>32:raise ValueError("malformed graph-plan IR")
    out=[]
    for rule in ir["rules"]:
        if not isinstance(rule,dict) or set(rule)!={"body","head"} or not all(isinstance(rule[k],list) and len(rule[k])==3 for k in ("body","head")):raise ValueError("malformed graph-plan rule")
        body,head=[_term(x) for x in rule["body"]],[_term(x) for x in rule["head"]]
        if any(x<-3 for x in body+head) or any(x<0 and x not in body for x in head):raise ValueError("unsafe graph-plan rule")
        out.append((body,head))
    return out
def make_plan(case):
    packet,*_=native_graph._prepare(case); values=struct.unpack("<%di"%(len(packet)//4),packet); n,nr=values[2:4]; start=7+n*5; rules=[{"body":list(values[start+i*3:start+i*3+3]),"head":list(values[start+nr*3+i*3:start+nr*3+i*3+3])} for i in range(nr)];ir={"version":1,"kind":"horn_graph_plan","rules":rules};_rows(ir);return ir
def emit_plan(ir):
    rows=_rows(ir); fields=("s","p","o"); lines=["#ifndef MRL_GRAPH_PLAN_H","#define MRL_GRAPH_PLAN_H","static int mrl_graph_plan_accepts(const Rule *rules,int32_t count) {"," if (count != %d) return 0;"%len(rows)]
    for i,(body,head) in enumerate(rows):
        for part,terms in (("body",body),("head",head)):
            for j,x in enumerate(terms):lines.append(" if (rules[%d].%s[%d] != %d) return 0;"%(i,part,j,x))
    lines += [" return 1;}","static int mrl_graph_plan_match(int32_t index,const Rule *rule,const Fact *fact,int32_t *slots) {(void)rule;switch(index) {"]
    for i,(body,_) in enumerate(rows):
        lines.append("case %d:"%i);seen={}
        for j,x in enumerate(body):
            field=fields[j]
            if x>=0:lines.append(" if (fact->%s != %d) return 0;"%(field,x))
            elif x in seen:lines.append(" if (fact->%s != fact->%s) return 0;"%(field,seen[x]))
            else:seen[x]=field;lines.append(" slots[%d] = fact->%s;"%(-x-1,field))
        lines.append(" return 1;")
    lines += ["default:return 0;}}","#define MRL_GRAPH_PLAN_ACCEPTS(rules,count) mrl_graph_plan_accepts((rules),(count))","#define MRL_GRAPH_MATCH(index,rule,fact,slots) mrl_graph_plan_match((index),(rule),(fact),(slots))","#endif",""]
    return "\n".join(lines)
@lru_cache(maxsize=32)
def _compiled_plan(header,source,optimization):
    with tempfile.TemporaryDirectory(prefix="mrl-plan-") as temp:
        wrapper=Path(temp)/"graph_plan.c";wrapper.write_bytes(_WRAPPER);return toolchain.cached_shared(wrapper,optimization=optimization,extra_files={"native_graph.c":source,"graph_plan.h":header})
def compile_plan(case,*,optimization="release"):
    optimization=toolchain._mode(optimization)
    header=emit_plan(make_plan(case)).encode()
    return _compiled_plan(header,_SOURCE.read_bytes(),optimization)
