import subprocess, tempfile, unittest
from pathlib import Path
from mrl import native_graph, toolchain
ROOT=Path(__file__).parents[1]

@unittest.skipUnless(native_graph.available(),"no C compiler available")
class IncrementalTests(unittest.TestCase):
    def test_append_duplicates_rules_and_fallbacks_preserve_native_output(self):
        native=(ROOT/'runtime/native_graph.c').read_text(encoding='utf8')
        inc=(ROOT/'runtime/horn_incremental.h').read_text(encoding='utf8')
        body=r'''
static int check(GraphState*g,size_t bytes,MrlHornIncremental*c,int wanted,int expected_status){
 size_t cap=4*(5+(size_t)g->capacity*(7+128*8)),n=0;uint8_t*a=calloc(1,cap),*b=calloc(1,cap);Context x={0};x.writer=(Writer){b,cap,0,0};
 if(mrl_graph_evaluate(g,bytes,a,cap,&n)||((int32_t*)a)[0]!=expected_status)return 91;
 int handled=mrl_horn_incremental_eval(c,g,&x);
 int result=handled!=wanted||(handled&&(n!=x.writer.pos||memcmp(a,b,n)));free(a);free(b);return result;
}
static int append(GraphState*g,size_t bytes,int32_t subject,int32_t predicate){int32_t d[6]={1,subject,predicate,20,1,1};return mrl_graph_append(g,bytes,(uint8_t*)d,sizeof(d));}
int main(void){
 int32_t w[]={MAGIC,CLOSURE,2,2,256,4,8192,1,10,20,1,1,2,10,20,1,1,-1,10,-2,-1,10,-2,-1,11,-2,-1,12,-2};
 size_t bytes=mrl_graph_state_size_for(256);GraphState*g=calloc(1,bytes);MrlHornIncremental c={0};
 if(mrl_graph_prepare((uint8_t*)w,sizeof(w),g,bytes)||check(g,bytes,&c,1,OK))return 2;
 if(c.new_matches!=4||c.reused)return 3;
 for(int32_t i=3;i<40;i++){
  if(append(g,bytes,i,10)||check(g,bytes,&c,1,OK))return 4;
  if(c.new_matches!=2||c.reused!=(uint64_t)(i-1)*2)return 5;
 }
 /* Duplicate assertion changes evidence without recomputing its consequence. */
 if(append(g,bytes,1,10)||check(g,bytes,&c,1,OK)||c.new_matches)return 6;
 /* A newly asserted old conclusion precedes all derived rows in the result. */
 if(append(g,bytes,1,11)||check(g,bytes,&c,1,OK))return 7;
 g->rules[1].head[1]=11;
 if(check(g,bytes,&c,0,OK)||check(g,bytes,&c,1,OK))return 8;
 g->input_count--;
 if(check(g,bytes,&c,0,OK)||check(g,bytes,&c,1,OK))return 9;
 g->input[0].polarity=0;
 if(check(g,bytes,&c,0,OK))return 10;
 g->input[0].polarity=1;g->op=PROVENANCE;
 if(check(g,bytes,&c,0,OK))return 11;
 g->op=CLOSURE;g->rules[0].head[1]=10;
 if(check(g,bytes,&c,0,OK))return 12;
 g->rules[0].head[1]=11;g->rules[0].body[1]=-3;
 if(check(g,bytes,&c,0,OK))return 13;
 g->rules[0].body[1]=10;g->limit=1;
 if(check(g,bytes,&c,0,GRAPH_LIMIT))return 14;
 mrl_horn_incremental_free(&c);free(g);return 0;
}
'''
        with tempfile.TemporaryDirectory() as folder:
            p,e=Path(folder)/'incremental.c',Path(folder)/'incremental.exe'
            p.write_text('#define MRL_GRAPH_SHARED\n'+native+'\n'+inc+body,encoding='utf-8')
            toolchain.build_c(p,e)
            result=subprocess.run([str(e)],capture_output=True,text=True,timeout=15)
            self.assertEqual((result.returncode,result.stderr),(0,""))

if __name__=='__main__':unittest.main()
