"""로컬 프로젝트/일반 대화 저장소. 외부 전송 없이 .marco/state에만 기록한다.

A store may be *bound* (``binding``) to the base and overlay sequence it runs on. A bound
store records that binding beside each saved reasoning state (``reasoning_binding``) and
checks it on load: same base and same overlay sequence, the state as saved (its replay is
used); same base and another overlay sequence, the state without its ``replay`` so it is
re-derived; another base, the state is refused (``ConversationBaseMismatch``) while the
turns stay readable. An unbound store, or a chat saved without a binding, loads as before.
"""
import json
import time
import uuid
from copy import deepcopy
from pathlib import Path

from marco.storage.snapshot import atomic_write


class ConversationBaseMismatch(ValueError):
    """A chat's reasoning state was saved on another base; its turns stay readable."""


def binding(content_sha256, build_id=None, overlay_seq=None, overlay_change_id=None):
    """A store binding: the base identity and the overlay head (``None`` seq: no overlay)."""
    if not isinstance(content_sha256, str) or not content_sha256:
        raise ValueError("a binding needs the base content_sha256")
    overlay = None if overlay_seq is None else {"seq": int(overlay_seq), "change_id": overlay_change_id}
    return {"base": {"content_sha256": content_sha256, "build_id": build_id}, "overlay": overlay}


def _overlay_head(value):
    overlay = (value or {}).get("overlay")
    return (overlay.get("seq", 0), overlay.get("change_id")) if isinstance(overlay, dict) else (0, None)


class ConversationStore:
    def __init__(self, path, binding=None):
        self.path = Path(path); self.path.parent.mkdir(parents=True, exist_ok=True); self.data = self._load()
        if binding is not None and (not isinstance(binding, dict) or not isinstance(binding.get("base"), dict)
                                    or not binding["base"].get("content_sha256")):
            raise ValueError("binding must come from conversations.binding(...)")
        self.binding = deepcopy(binding)

    def _load(self):
        try:
            value = json.loads(self.path.read_text(encoding="utf-8"))
            if isinstance(value, dict) and isinstance(value.get("chats"), list):
                value.setdefault("version", 1); value.setdefault("projects", []); return value
        except (FileNotFoundError, json.JSONDecodeError): pass
        return {"version": 1, "projects": [], "chats": []}

    def _save(self):
        # A unique temp name per process and write, fsync, then replace: two processes never
        # share a temp file, and a crash leaves the old file or the new one.
        atomic_write(self.path, json.dumps(self.data, ensure_ascii=False, indent=2).encode("utf-8"))

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
        state = deepcopy(chat.get("reasoning_state"))
        saved = chat.get("reasoning_binding")
        if state is None or not isinstance(saved, dict) or self.binding is None:
            return state
        mine, theirs = self.binding["base"], saved.get("base") or {}
        if (theirs.get("content_sha256") != mine["content_sha256"]
                or (theirs.get("build_id") is not None and mine.get("build_id") is not None
                    and theirs["build_id"] != mine["build_id"])):
            raise ConversationBaseMismatch(
                "conversation %s: its reasoning state was saved on base %s (build %s); this store runs on "
                "base %s (build %s); the state is refused, the turns stay readable"
                % (chat_id, theirs.get("content_sha256"), theirs.get("build_id"),
                   mine["content_sha256"], mine.get("build_id")))
        if _overlay_head(saved) != _overlay_head(self.binding) and isinstance(state, dict):
            state.pop("replay", None)     # re-derived under the current overlay
        return state

    def reasoning_binding(self, chat_id):
        """The base and overlay head a chat's reasoning state was saved under, or None."""
        chat = self._chat(chat_id)
        if not chat: raise ValueError("대화를 찾을 수 없습니다")
        return deepcopy(chat.get("reasoning_binding"))

    def import_chat(self, record):
        """Add a chat from a snapshot record (``id``, ``title``, ``turns``, ``reasoning_state``).

        Refused if a chat with that id exists. The state is recorded under this store's binding:
        the caller has checked the snapshot against the current base and overlay first."""
        chat_id = str(record.get("id") or "")
        if not chat_id or self._chat(chat_id):
            raise ValueError("대화 id가 비었거나 이미 있습니다: %r" % chat_id)
        now = time.time()
        chat = {"id": chat_id, "title": str(record.get("title") or "새 대화")[:80], "project_id": None,
                "created_at": record.get("created_at") or now, "updated_at": record.get("updated_at") or now,
                "turns": deepcopy(list(record.get("turns") or []))}
        if record.get("reasoning_state") is not None:
            chat["reasoning_state"] = deepcopy(record["reasoning_state"])
            if self.binding is not None:
                chat["reasoning_binding"] = deepcopy(self.binding)
        self.data["chats"].append(chat)
        try:
            self._save()
        except OSError:
            self.data["chats"].remove(chat)
            raise
        return self.get_chat(chat_id)

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
            # The binding is beside the state it describes: a state saved by an unbound store
            # carries none, so an old binding never vouches for a newer state.
            if self.binding is not None:
                chat["reasoning_binding"] = deepcopy(self.binding)
            else:
                chat.pop("reasoning_binding", None)
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
