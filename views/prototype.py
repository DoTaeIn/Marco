import json
import os
from google import genai
from google.genai import types

# 1. Define a miniature knowledge graph (case: convenience-store robbery).
# A dictionary represents nodes (terms) and edges (relationships).
KNOWLEDGE_GRAPH = {
    "CCTV": ["흉기", "선제공격"],   # CCTV는 흉기 소지와 선제공격을 증명함
    "목격자": ["욕설"],             # 목격자는 강도의 욕설을 증명함
    "흉기": "생명의 위협",          # 흉기는 생명의 위협으로 이어짐
    "욕설": "위협",
    "생명의 위협": "정당방위",      # 생명의 위협을 느꼈다면 정당방위 성립 가능
    "선제공격": "과잉방위"          # 선제공격은 과잉방위로 이어짐
}

# Reference terms for LLM parsing.
VALID_EVIDENCES = ["CCTV", "목격자"]
VALID_CLAIMS = ["흉기", "선제공격", "욕설", "생명의 위협", "위협", "정당방위", "과잉방위"]

def extract_entities(user_text):
    """
    Extract evidence and claims from a user's natural-language statement with
    the small Gemini 2.5 Flash model. This is parsing, not dialogue generation.
    """
    # GEMINI_API_KEY must be set in the environment.
    client = genai.Client() 
    
    prompt = f"""
    당신은 텍스트 분석기입니다. 유저의 발언에서 '근거'와 '주장' 키워드를 정확히 추출하세요.
    
    허용된 근거(Evidence) 목록: {VALID_EVIDENCES}
    허용된 주장(Claim) 목록: {VALID_CLAIMS}
    
    유저 발언: "{user_text}"
    
    반드시 JSON 형식으로 반환하세요. 유저 발언과 매칭되는 키워드가 없다면 null로 표기하세요.
    출력 예시: {{"evidence": "CCTV", "claim": "흉기"}}
    """
    
    response = client.models.generate_content(
        model='gemini-2.5-flash',
        contents=prompt,
        config=types.GenerateContentConfig(
            response_mime_type="application/json",
            temperature=0.1, # Lower temperature for consistent output.
        ),
    )
    return json.loads(response.text)

def check_graph(evidence, claim):
    """Traverse the knowledge graph and verify whether the logic is valid."""
    if not evidence or not claim:
        return False, "말씀하신 내용에서 명확한 근거와 주장을 파악할 수 없습니다."
        
    if evidence not in KNOWLEDGE_GRAPH:
        return False, f"[{evidence}]는 현재 재판에서 인정된 증거가 아닙니다."

    # Check the first-hop relation (for example, CCTV -> weapon).
    first_level = KNOWLEDGE_GRAPH.get(evidence, [])
    if type(first_level) is str:
        first_level = [first_level]
        
    if claim in first_level:
        return True, "인정합니다."
        
    # Check the second-hop relation (for example, CCTV -> weapon -> threat to life).
    for node in first_level:
        second_level = KNOWLEDGE_GRAPH.get(node)
        if second_level == claim:
            return True, "인정합니다."
            
    return False, f"지식 그래프 논리 오류: [{evidence}]를 바탕으로 [{claim}](이)라는 결론을 도출할 수 없습니다."

def play_game():
    print("=" * 60)
    print("🏛️ [AI 법정 공방 프로토타입] 🏛️")
    print("사건: 편의점 야간 알바생 폭행 사건")
    print("당신은 알바생의 '정당방위'를 입증해야 하는 변호사입니다.")
    print("\n[사용 가능한 증거]: CCTV, 목격자")
    print("[입력 예시]: 'CCTV 영상을 보십시오. 강도가 흉기를 들고 있었으므로 생명의 위협을 느낀 것입니다.'")
    print("('종료'를 입력하면 게임이 끝납니다.)")
    print("=" * 60)
    
    while True:
        user_input = input("\n변호사(당신): ")
        if user_input.lower() in ['q', 'quit', '종료']:
            print("재판을 종료합니다.")
            break
            
        print("[시스템] 발언 분석 중 (문장 -> 그래프 데이터 추출)...")
        try:
            # 1. Decompose the statement with the LLM.
            extracted = extract_entities(user_input)
            evidence = extracted.get('evidence')
            claim = extracted.get('claim')
            
            print(f" └ 추출된 노드 데이터: [근거: {evidence}] ➔ [주장: {claim}]")
            
            # 2. Check whether it passes the knowledge-graph validation logic.
            is_valid, reason = check_graph(evidence, claim)
            
            # 3. Apply the prosecutor NPC response rule.
            if is_valid:
                print(f"⚖️ AI 검사: 큭... 확실히 [{evidence}]에 [{claim}] 사실이 있다는 것은 반박할 수 없군요.")
            else:
                print(f"⚖️ AI 검사: 이의 있습니다! {reason}")
                
        except Exception as error:
            print(f"\n[오류 발생] API 통신 중 문제가 생겼습니다.")
            print(f"1. 터미널에 'set GEMINI_API_KEY=당신의_API_키'가 설정되었는지 확인하세요.")
            print(f"2. google-genai 라이브러리가 설치되어 있는지 확인하세요. (pip install google-genai)")
            print(f"상세 에러: {error}")
            break

if __name__ == "__main__":
    play_game()
