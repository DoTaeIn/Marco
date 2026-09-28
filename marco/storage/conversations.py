"""로컬 프로젝트/일반 대화 저장소. 외부 전송 없이 .nai에만 기록한다."""
import json
import os
import time
import uuid
from copy import deepcopy
from pathlib import Path


class ConversationStore:
    def __init__(self, path):
        self.path = Path(path); self.path.parent.mkdir(parents=True, exist_ok=True); self.data = self._load()

    def _load(self):
        try:
            value = json.loads(self.path.read_text(encoding="utf-8"))
            if isinstance(value, dict) and isinstance(value.get("chats"), list):
                value.setdefault("version", 1); value.setdefault("projects", []); return value
        except (FileNotFoundError, json.JSONDecodeError): pass
        return {"version": 1, "projects": [], "chats": []}

    def _save(self):
        temporary = self.path.with_suffix(".tmp")
        temporary.write_text(json.dumps(self.data, ensure_ascii=False, indent=2), encoding="utf-8"); os.replace(temporary, self.path)

    @staticmethod
    def _id(): return uuid.uuid4().hex
    def _chat(self, chat_id): return next((x for x in self.data["chats"] if x["id"] == chat_id), None)
    @staticmethod
    def _summary(chat): return {key: chat.get(key) for key in ("id", "title", "project_id", "created_at", "updated_at")}

    def overview(self):
        projects = []
        for project in self.data["projects"]:
            item = dict(project); item["chats"] = [self._summary(x) for x in self.data["chats"] if x.get("project_id") == project["id"]]; projects.append(item)
        return {"projects": projects, "general_chats": [self._summary(x) for x in self.data["chats"] if not x.get("project_id")]}

    def create_project(self, name):
        name = str(name or "").strip()[:80]
        if not name: raise ValueError("프로젝트 이름을 입력해 주세요")
        now = time.time(); project = {"id": self._id(), "name": name, "root": "", "created_at": now, "updated_at": now}
        self.data["projects"].append(project); self._save(); return dict(project)

    def create_chat(self, project_id=None, title="새 대화"):
        if project_id and not any(x["id"] == project_id for x in self.data["projects"]): raise ValueError("프로젝트를 찾을 수 없습니다")
        now = time.time(); chat = {"id": self._id(), "title": str(title or "새 대화")[:80], "project_id": project_id or None, "created_at": now, "updated_at": now, "turns": []}
        self.data["chats"].append(chat); self._save(); return self.get_chat(chat["id"])

    def get_chat(self, chat_id):
        chat = self._chat(str(chat_id or ""))
        if not chat: raise ValueError("대화를 찾을 수 없습니다")
        return {**self._summary(chat), "turns": list(chat.get("turns", []))}

    def reasoning_state(self, chat_id):
        chat = self._chat(chat_id)
        if not chat: raise ValueError("대화를 찾을 수 없습니다")
        return deepcopy(chat.get("reasoning_state"))

    def append_turn(self, chat_id, user, assistant, phase, reasoning_state=None):
        chat = self._chat(chat_id)
        if not chat: return None
        previous = deepcopy(chat)
        now = time.time(); turns = chat.setdefault("turns", [])
        turns.append({"id": self._id(), "at": now, "user": str(user), "assistant": str(assistant), "phase": str(phase)})
        if len(turns) == 1 and chat.get("title") == "새 대화": chat["title"] = str(user).replace("\n", " ").strip()[:34] or "새 대화"
        chat["updated_at"] = now
        if reasoning_state is not None:
            chat["reasoning_state"] = deepcopy(reasoning_state)
        try:
            self._save()
        except OSError:
            chat.clear(); chat.update(previous)
            raise
        return self.get_chat(chat_id)

    def project_root(self, chat_id):
        chat = self._chat(chat_id)
        project = next((x for x in self.data["projects"] if chat and x["id"] == chat.get("project_id")), None)
        return project.get("root") if project else None

    def set_project_root(self, chat_id, root):
        chat = self._chat(chat_id)
        project = next((x for x in self.data["projects"] if chat and x["id"] == chat.get("project_id")), None)
        if not project: return False
        project["root"] = str(root); project["updated_at"] = time.time(); self._save(); return True
