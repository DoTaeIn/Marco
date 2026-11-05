"""PUBLIC actual selected-model dialogue demo, private state only; partial candidate limits retained."""
import json
import tempfile
from pathlib import Path
import sys
r=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(r),str(r/"tests")]
from test_marco2_coherent_hook import selected_model, triples
from marco.runtime.learning_dialogue import DialogueSession
rows=[]
for color,reverse,transitive in [("amber",False,True),("cobalt",True,False)]:
    model,rel=selected_model(color,reverse=reverse,transitive=transitive)
    state=Path(tempfile.mkdtemp(prefix="public-coherent-demo-",dir="/private/tmp"))
    with DialogueSession(state/"memory.sqlite",state/"session.json",model=model) as chat:
        turns=[]
        for source in ["Compared with Elian, Mira outranks.","who outranks, Mira or Elian?",
                       "Elian outranks Sola.","who outranks, Mira or Sola?"]:
            result=chat.respond(source)
            turns.append({"source":source,"result":result})
        rows.append({"selected_graph":color,"selected_model_content_fingerprint":model.content_fingerprint,
            "reverse_selected_roles":reverse,"selected_transitive_rule":transitive,"turns":turns,
            "actual_replay_facts":chat.snapshot()["context"]["replay"]["facts"]})
print(json.dumps({"status":"PUBLIC_REAL_DIALOGUE_ON_REVIEWED_MAIN",
    "ordinary_asset_activation":False,"limits":["selected assets only; no general language completeness claim",
    "selected fixture activation only; ordinary packs unchanged"],"models":rows},ensure_ascii=False,indent=2))
