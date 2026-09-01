import os
import sys
import glob

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import gradio as gr
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import engine   # noqa: E402

_root_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))  # 근거/


def get_kg_files():
    """어느 폴더에서 띄우든 근거/ 의 .kg 를 전부 찾는다."""
    files = sorted(glob.glob(os.path.join(_root_dir, "*.kg"))
                   + glob.glob(os.path.join(_root_dir, "graphs", "*.kg")))
    return [os.path.relpath(path, _root_dir) for path in files] or ["cases/사건_편의점강도.kg"]

def start_new_session(case_file):
    try:
        graph = engine.load(os.path.join(_root_dir, case_file))
        session = engine.세션(graph)
        intro_msg = f"🏛️ **[{graph['역할']}]** 상대입니다.\n\n**목표:** {graph['목표']} 입증\n**사용 가능한 증거:** {', '.join(graph.get('증거', []))}\n\n입력창에 주장을 펼쳐보세요!"
        return graph, session, [{"role": "assistant", "content": intro_msg}]
    except Exception as error:
        return None, None, [{"role": "assistant", "content": f"오류 발생: {error}"}]

def chat(user_message, history, graph, session):
    if not session:
        return history, graph, session
        
    # 사용자의 말을 기록에 추가
    history.append({"role": "user", "content": user_message})
        
    if session.결과():
        history.append({"role": "assistant", "content": f"이미 재판이 끝났습니다. (결과: {session.결과()})"})
        return history, graph, session
        
    response = session.대답(user_message)
    
    if session.결과():
        response += f"\n\n**=== 재판 결과: {session.결과()} ===**"
        
    # 엔진의 대답을 기록에 추가
    history.append({"role": "assistant", "content": response})
    return history, graph, session

def get_hint_chat(history, graph, session):
    if not session:
        history.append({"role": "assistant", "content": "게임을 먼저 시작해주세요."})
        return history
    
    try:
        status = session.현황()
        hint_msg = (
            f"💡 **시스템 힌트**\n현재 상황: `{status}`\n\n"
            f"**Tip:** 상대방(AI)을 설득하려면 아직 인정받지 못한 '요건'을 증명해야 합니다. "
            f"가지고 계신 **증거({', '.join(graph.get('증거', []))})**를 아직 풀리지 않은 사실과 엮어서 말씀해 보세요!"
        )
        history.append({"role": "assistant", "content": hint_msg})
    except Exception as error:
        history.append({"role": "assistant", "content": f"힌트 로드 실패: {error}"})
        
    return history

with gr.Blocks(title="오브젝션 - AI 법정 공방", theme=gr.themes.Soft()) as demo:
    gr.Markdown("# ⚖️ 오브젝션 (Objection) 웹 플레이어")
    
    with gr.Row():
        case_dropdown = gr.Dropdown(choices=get_kg_files(), value="cases/사건_편의점강도.kg", label="사건(.kg) 선택")
        restart_btn = gr.Button("🔄 재판 시작", variant="primary")
        
    chatbot = gr.Chatbot(height=500, label="법정 공방")
    
    with gr.Row():
        # gradio 6 에서는 Enter 가 줄바꿈이라 보내기 버튼이 없으면 말을 못 건다.
        msg = gr.Textbox(placeholder="여기에 주장을 입력하고 Enter를 누르세요...",
                         show_label=False, scale=4, submit_btn=True)
        hint_btn = gr.Button("💡 힌트 받기", scale=1)
        
    g_state = gr.State()
    s_state = gr.State()
    
    msg.submit(chat, [msg, chatbot, g_state, s_state], [chatbot, g_state, s_state]).then(lambda: "", None, msg)
    restart_btn.click(start_new_session, [case_dropdown], [g_state, s_state, chatbot])
    hint_btn.click(get_hint_chat, [chatbot, g_state, s_state], chatbot)
    
    demo.load(start_new_session, [case_dropdown], [g_state, s_state, chatbot])

if __name__ == "__main__":
    # 포트는 gradio 가 알아서 고른다 (7860 이 차 있으면 7861). 그것을 직접
    # 찍으면 거짓말이 되므로 gradio 가 찍는 주소를 쓴다.
    demo.launch()
