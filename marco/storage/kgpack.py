# -*- coding: utf-8 -*-
"""여러 지식 그래프를 검증 가능한 단일 .kgpack으로 묶고 다시 푼다.

.kgpack은 표준 ZIP이지만 반드시 manifest.json을 가지며, 각 파일의 SHA-256과
바이트 수를 기록한다. 런타임 지식은 pack을 수정하지 않고 별도 overlay에 쌓는다.

    python kgpack.py --pack NAI.kgpack
    python kgpack.py --list NAI.kgpack
    python kgpack.py --unpack NAI.kgpack --out unpacked
    python kgpack.py --check
"""
from __future__ import annotations
import sys as _sys
from pathlib import Path as _Path
_sys.path.insert(0, str(_Path(__file__).resolve().parents[2]))

import argparse
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import re
import tempfile
import zipfile


fmt_version = 3
frozen_hour_each = (1980, 1, 1, 0, 0, 0)


class KGPackError(RuntimeError):
    pass


def _hash(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def content_identity(data: bytes) -> dict:
    """Separate byte identity from a text-only LF-normalised comparison.

    Pack verification always uses ``sha256``.  The normalised digest is only
    diagnostic evidence that a CRLF/LF checkout difference did not alter text
    content; it must never make a changed pack verify as identical.
    """
    normal = data.replace(b"\r\n", b"\n").replace(b"\r", b"\n")
    return {"sha256": _hash(data), "lf_normalized_sha256": _hash(normal),
            "line_endings": {"crlf": data.count(b"\r\n"),
                              "lf": data.count(b"\n") - data.count(b"\r\n"),
                              "cr": data.count(b"\r") - data.count(b"\r\n")}}


def _safe_path(name: str) -> PurePosixPath:
    p = PurePosixPath(name)
    if p.is_absolute() or not p.parts or ".." in p.parts or "" in p.parts:
        raise KGPackError("안전하지 않은 pack 경로: %s" % name)
    return p


def _write(zf: zipfile.ZipFile, name: str, data: bytes) -> None:
    info = zipfile.ZipInfo(name, frozen_hour_each)
    info.compress_type = zipfile.ZIP_DEFLATED
    info.external_attr = 0o100644 << 16
    zf.writestr(info, data)


def default_file(root: str | os.PathLike = ".") -> list[Path]:
    root = Path(root).resolve()
    # `.수집.jsonl`은 승인 뒤 생긴 외부 근거와 질문 표현을 보존한다. 이것을
    # 빼면 새 팩은 같은 그래프 뼈대만 갖고 학습한 사실을 잃는다. 정의문도 UI의
    # 읽기 전용 근거이므로, 기본 팩에서 빠졌을 때 호스트 파일로 조용히 대체하지
    # 않도록 명시 자산으로 포함한다.
    definition = root / "data" / "위키" / "정의문.jsonl"
    return (sorted(root.glob("graphs/*.kg"))
            + sorted(root.glob("graphs/*.학습.jsonl"))
            + sorted(root.glob("graphs/*.수집.jsonl"))
            + ([definition] if definition.is_file() else [])
            + sorted(root.glob("models/*.json")) + model_files(root))


def model_files(root: str | os.PathLike = ".") -> list[Path]:
    """Explicit authoring inputs for a model, including its language and axioms."""
    root = Path(root).resolve()
    return sorted(root.glob("styles/*.json")) + sorted(root.glob("axioms/*.json"))


_quote = re.compile(r'"((?:\\.|[^"\\])*)"')


def _graph_meta(name: str, data: bytes, max_example=90) -> dict:
    """벡터를 만들지 않고 KG의 역할·목표·노드 예시만 읽는다."""
    text = data.decode("utf-8")
    role, goal, section, example = "", "", "", []
    for raw in text.splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("[") and line.endswith("]"):
            section = line[1:-1].strip()
            continue
        if line.startswith("역할:"):
            role = line.split(":", 1)[1].strip()
            continue
        if line.startswith("목표:"):
            goal = line.split(":", 1)[1].strip()
            continue
        if section not in ("개념", "사례") or ":" not in line:
            continue
        left, right = line.split(":", 1)
        node = left.strip().lstrip("*").split("@", 1)[0].strip()
        if node:
            example.append(node)
        for encoded in _quote.findall(right)[:2]:
            try:
                example.append(json.loads('"' + encoded + '"'))
            except json.JSONDecodeError:
                example.append(encoded.replace('\\"', '"'))
        if len(example) >= max_example:
            break
    example = list(dict.fromkeys(x for x in [goal] + example if x))[:max_example]
    return {"path": name, "role": role, "goal": goal, "examples": example}


def _manager_graph(entry, body) -> dict:
    """KG 하나를 노드 하나로 갖는, pack 내부의 상위 그래프."""
    nodes = []
    for item in sorted(entry, key=lambda x: x["path"]):
        name = item["path"]
        if item["kind"] != "graph" or "템플릿" in name:
            continue
        nodes.append(_graph_meta(name, body[name]))
    return {"format": "nai-kg-manager", "version": 1, "role": "노드 매니저",
            "goal": "그래프고르기", "nodes": nodes,
            "edges": [[n["path"], "후보", "그래프고르기"] for n in nodes]}


def write_pack(output: str | os.PathLike, files, root: str | os.PathLike = ".", *, language=None) -> dict:
    root, output = Path(root).resolve(), Path(output).resolve()
    entry, body = [], {}
    for raw in files:
        path = Path(raw).resolve()
        if not path.is_file():
            raise KGPackError("파일이 없습니다: %s" % path)
        try:
            name = path.relative_to(root).as_posix()
        except ValueError as e:
            raise KGPackError("pack 루트 밖의 파일입니다: %s" % path) from e
        _safe_path(name)
        if name in body:
            raise KGPackError("중복 경로입니다: %s" % name)
        data = path.read_bytes()
        body[name] = data
        entry.append({"path": name, "kind": "graph" if name.endswith(".kg") else "asset",
                   "bytes": len(data), **content_identity(data)})
    if not any(x["kind"] == "graph" for x in entry):
        raise KGPackError(".kg 그래프가 하나도 없습니다")
    manifest = {"format": "nai-kgpack", "version": fmt_version,
                "files": sorted(entry, key=lambda x: x["path"]),
                "manager": _manager_graph(entry, body)}
    from pack_model import PackModel, descriptor
    if language is None and os.environ.get("NAI_LANGUAGE"):
        # 짓는 쪽이 고른 언어. 고르지 않았으면 팩의 default_model_language 선언을 따른다.
        chosen = os.environ["NAI_LANGUAGE"]
        chosen = chosen if chosen.endswith(".json") else "styles/%s.json" % chosen
        # 그 언어가 이 팩에 없으면 고른 것이 아니다. 팩의 선언을 따른다.
        language = chosen if chosen in body else None
    try:
        manifest["model"] = descriptor(body, language)
        PackModel(manifest, body)
    except (ValueError, TypeError) as exc:
        raise KGPackError("잘못된 모델 선언: %s" % exc) from exc
    output.parent.mkdir(parents=True, exist_ok=True)
    tmp = output.with_name(output.name + ".tmp-%d" % os.getpid())
    try:
        with zipfile.ZipFile(tmp, "w") as zf:
            _write(zf, "manifest.json",
                (json.dumps(manifest, ensure_ascii=False, sort_keys=True,
                            separators=(",", ":")) + "\n").encode("utf-8"))
            for name in sorted(body):
                _write(zf, name, body[name])
        os.replace(tmp, output)
    finally:
        try:
            tmp.unlink()
        except FileNotFoundError:
            pass
    return manifest


def read(pack: str | os.PathLike, verify=True) -> tuple[dict, dict[str, bytes]]:
    pack = Path(pack)
    try:
        with zipfile.ZipFile(pack) as zf:
            names = zf.namelist()
            if names.count("manifest.json") != 1:
                raise KGPackError("manifest.json이 정확히 하나여야 합니다")
            if len(names) != len(set(names)):
                raise KGPackError("pack 안에 중복 경로가 있습니다")
            manifest = json.loads(zf.read("manifest.json"))
            if manifest.get("format") != "nai-kgpack" or manifest.get("version") not in (2, fmt_version):
                raise KGPackError("지원하지 않는 kgpack 형식입니다")
            entries = manifest.get("files")
            if not isinstance(entries, list):
                raise KGPackError("manifest files가 목록이 아닙니다")
            data = {}
            for item in entries:
                name = str(item.get("path", ""))
                _safe_path(name)
                if name == "manifest.json" or name not in names or name in data:
                    raise KGPackError("manifest와 archive가 다릅니다: %s" % name)
                body = zf.read(name)
                if verify and (len(body) != item.get("bytes") or _hash(body) != item.get("sha256")):
                    raise KGPackError("무결성 검증 실패: %s" % name)
                data[name] = body
            remaining = set(names) - {"manifest.json"} - set(data)
            if remaining:
                raise KGPackError("manifest에 없는 파일이 있습니다: %s" % sorted(remaining)[0])
            manager = manifest.get("manager")
            graph_paths = {x["path"] for x in entries if x.get("kind") == "graph"}
            if (not isinstance(manager, dict) or manager.get("format") != "nai-kg-manager"
                    or manager.get("version") != 1 or not isinstance(manager.get("nodes"), list)):
                raise KGPackError("pack에 유효한 노드 매니저 그래프가 없습니다")
            manager_paths = [x.get("path") for x in manager["nodes"] if isinstance(x, dict)]
            if (len(manager_paths) != len(set(manager_paths))
                    or any(x not in graph_paths for x in manager_paths)):
                raise KGPackError("노드 매니저와 pack 그래프 목록이 다릅니다")
            from pack_model import PackModel
            try:
                PackModel(manifest, data)
            except (ValueError, TypeError) as exc:
                raise KGPackError("잘못된 모델 선언: %s" % exc) from exc
            return manifest, data
    except (OSError, zipfile.BadZipFile, json.JSONDecodeError) as e:
        raise KGPackError("kgpack을 읽지 못했습니다: %s" % e) from e


def unpack(pack: str | os.PathLike, out: str | os.PathLike) -> list[Path]:
    _manifest, data = read(pack, verify=True)
    out = Path(out).resolve()
    out.mkdir(parents=True, exist_ok=True)
    written = []
    for name, body in sorted(data.items()):
        target = (out / Path(*PurePosixPath(name).parts)).resolve()
        if out != target and out not in target.parents:
            raise KGPackError("출력 경로 밖으로 나갑니다: %s" % name)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(body)
        written.append(target)
    return written


def selfcheck() -> None:
    with tempfile.TemporaryDirectory(prefix="kgpack-check-") as td:
        root = Path(td)
        (root / "graphs").mkdir()
        (root / "styles").mkdir()
        a = root / "graphs" / "가.kg"
        b = root / "graphs" / "나.kg"
        s = root / "styles" / "한국어.json"
        a.write_text("역할: 가\n목표: 가\n", encoding="utf-8")
        b.write_text("역할: 나\n목표: 나\n", encoding="utf-8")
        s.write_text('{"말투":"시험"}\n', encoding="utf-8")
        pack = root / "시험.kgpack"
        first = write_pack(pack, [a, b, s], root)
        raw1 = pack.read_bytes()
        second = write_pack(pack, [a, b, s], root)
        assert first == second and raw1 == pack.read_bytes()  # 같은 입력은 같은 pack
        manifest, data = read(pack)
        assert len(manifest["files"]) == 3 and data["graphs/가.kg"] == a.read_bytes()
        assert len(manifest["manager"]["nodes"]) == 2
        assert manifest["manager"]["goal"] == "그래프고르기"
        out = root / "out"
        unpack(pack, out)
        assert (out / "graphs" / "가.kg").read_bytes() == a.read_bytes()
        assert (out / "styles" / "한국어.json").read_bytes() == s.read_bytes()


def main(argv=None) -> int:
    p = argparse.ArgumentParser(description=__doc__)
    g = p.add_mutually_exclusive_group(required=True)
    g.add_argument("--pack", metavar="OUTPUT")
    g.add_argument("--list", metavar="PACK")
    g.add_argument("--unpack", metavar="PACK")
    g.add_argument("--check", action="store_true")
    p.add_argument("files", nargs="*")
    p.add_argument("--root", default=".")
    p.add_argument("--out")
    p.add_argument("--language", help="팩 안에서 사용할 언어 파일 경로")
    args = p.parse_args(argv)
    try:
        if args.check:
            selfcheck()
            print("kgpack 자체검사: 통과")
        elif args.pack:
            files = [Path(x) for x in args.files] or default_file(args.root)
            m = write_pack(args.pack, files, args.root, language=args.language)
            print("%s: 그래프 %d개 · 자산 %d개"
                  % (Path(args.pack).resolve(),
                     sum(x["kind"] == "graph" for x in m["files"]),
                     sum(x["kind"] != "graph" for x in m["files"])))
        elif args.list:
            m, _ = read(args.list)
            for x in m["files"]:
                print("%-5s %8d  %s  %s" % (x["kind"], x["bytes"], x["sha256"][:12], x["path"]))
        else:
            if not args.out:
                p.error("--unpack에는 --out이 필요합니다")
            written = unpack(args.unpack, args.out)
            print("%s: %d개 파일 복원" % (Path(args.out).resolve(), len(written)))
        return 0
    except KGPackError as e:
        print("kgpack 오류: %s" % e)
        return 1


_RULE_SLOT = 'axioms/learned-experience-rules.json'
_RR_EXPORT_KEYS = {'schema', 'base_binding', 'overlay_head', 'rules', 'origins', 'scope', 'sha256'}


def _rr_canon_sha(value):
    return _hash(json.dumps(value, sort_keys=True, separators=(',', ':'), ensure_ascii=False,
                            allow_nan=False).encode('utf-8'))


def _rr_hex(v):
    return isinstance(v, str) and len(v) == 64 and all(c in '0123456789abcdef' for c in v)


def write_rule_revision(base_pack, base_sha256, memory, output, *, expected_head):
    """Publish a NEW explicit pack revision from the original base plus at most one verified learned rule."""
    from marco.learning.memory import LearningMemory
    import copy
    if type(memory) is not LearningMemory:
        raise KGPackError('rule revision requires an actual LearningMemory')
    if not _rr_hex(base_sha256):
        raise KGPackError('base_sha256 must be 64 lowercase hex')
    try:
        src = os.path.abspath(os.fspath(base_pack))
        dst = os.path.abspath(os.fspath(output))
    except TypeError:
        raise KGPackError('invalid pack path') from None
    parent = os.path.dirname(dst)
    if src == dst or os.path.lexists(dst) or not os.path.isdir(parent):
        raise KGPackError('output must be a new path in an existing directory')
    for candidate_path in (src, dst):
        p = candidate_path
        while True:
            if os.path.islink(p):
                raise KGPackError('symlink path refused')
            ancestor = os.path.dirname(p)
            if ancestor == p:
                break
            p = ancestor
    if not os.path.isfile(src) or os.path.realpath(src) == os.path.realpath(dst):
        raise KGPackError('invalid input/output relation')
    head = expected_head
    export = LearningMemory.export_rule_revision(memory, expected_head=head)
    cap = 1 << 28

    def slurp():
        with open(src, 'rb') as f:
            raw = f.read(cap + 1)
        if len(raw) > cap:
            raise KGPackError('base pack too large')
        return raw
    if _hash(slurp()) != base_sha256:
        raise KGPackError('base pack sha256 mismatch')
    manifest, members = read(src)
    if _hash(slurp()) != base_sha256:
        raise KGPackError('base pack changed while reading')
    decl = manifest.get('model')
    if (_RULE_SLOT in members or not isinstance(decl, dict) or not isinstance(decl.get('axioms'), list)
            or _RULE_SLOT in decl['axioms']
            or any(isinstance(x, dict) and x.get('path') == _RULE_SLOT for x in manifest['files'])):
        raise KGPackError('base pack is not an original pack without the reserved learned slot')
    from pack_model import PackModel
    from marco.storage.graph_view import pack_rules
    try:
        fingerprint = PackModel(manifest, members).content_fingerprint
        base_rules = pack_rules(manifest, members)
    except Exception as exc:
        raise KGPackError('base pack model invalid: %s' % exc) from exc
    base_rules_sha = _rr_canon_sha(base_rules)
    if (type(export) is not dict or set(export) != _RR_EXPORT_KEYS
            or export['schema'] != 'marco-rule-experience-export-v1'
            or export['scope'] != 'finite_supervised_rule_revision_not_universal_truth'
            or export['sha256'] != _rr_canon_sha({k: v for k, v in export.items() if k != 'sha256'})):
        raise KGPackError('rule experience export is malformed')
    if (export['base_binding'] != {'graph_binding': fingerprint, 'base_rules_sha256': base_rules_sha}
            or export['overlay_head'] != head):
        raise KGPackError('export is not bound to this base pack and head')
    rules, origins = export['rules'], export['origins']
    base_ids = {r.get('id') for r in base_rules if isinstance(r, dict)}
    if (type(rules) is not list or type(origins) is not list or len(rules) > 1
            or len(origins) != len(rules) or len(base_rules) + len(rules) > 3):
        raise KGPackError('rule capacity violated')
    for r in rules:
        if (type(r) is not dict or set(r) != {'id', 'body', 'head'} or not isinstance(r['id'], str)
                or r['id'] in base_ids):
            raise KGPackError('invalid learned rule')
    doc = {'schema': 'nai-axioms-v1', 'rules': copy.deepcopy(rules),
           'rule_experience_origin': {'schema': 'marco-rule-experience-origin-v1',
                                      'export_sha256': export['sha256'], 'base_pack_sha256': base_sha256,
                                      'base_rules_sha256': base_rules_sha, 'overlay_head': copy.deepcopy(head),
                                      'origins': copy.deepcopy(origins)}}
    doc_bytes = (json.dumps(doc, ensure_ascii=False, sort_keys=True, separators=(',', ':')) + '\n').encode('utf-8')
    manifest2 = copy.deepcopy(manifest)
    manifest2['files'].append({'bytes': len(doc_bytes), 'kind': 'axiom', 'path': _RULE_SLOT,
                               'sha256': _hash(doc_bytes)})
    manifest2['model']['axioms'].append(_RULE_SLOT)
    members2 = dict(members)
    members2[_RULE_SLOT] = doc_bytes
    mbytes = (json.dumps(manifest2, ensure_ascii=False, sort_keys=True, separators=(',', ':')) + '\n').encode('utf-8')
    fd, tmp = tempfile.mkstemp(prefix='.rule-revision-', suffix='.tmp', dir=parent)
    try:
        with os.fdopen(fd, 'wb') as fh:
            with zipfile.ZipFile(fh, 'w') as zf:
                _write(zf, 'manifest.json', mbytes)
                for name in sorted(members2):
                    _write(zf, name, members2[name])
            fh.flush()
            os.fsync(fh.fileno())
        m2, d2 = read(tmp)
        if m2 != manifest2 or d2 != members2 or any(d2[k] != v for k, v in members.items()):
            raise KGPackError('built revision does not match the expected content')
        PackModel(m2, d2)
        if pack_rules(m2, d2) != base_rules + rules:
            raise KGPackError('built revision rule bank mismatch')
        if LearningMemory.export_rule_revision(memory, expected_head=head) != export:
            raise KGPackError('memory export changed before publication')
        with open(tmp, 'rb') as f:
            out = f.read()
        try:
            os.link(tmp, dst)
        except FileExistsError:
            raise KGPackError('output already exists') from None
        except OSError as exc:
            raise KGPackError('exclusive publication failed: %s' % exc) from exc
    finally:
        try:
            os.unlink(tmp)
        except FileNotFoundError:
            pass
    return {'output_path': dst, 'sha256': _hash(out), 'bytes': len(out), 'base_pack_sha256': base_sha256,
            'export_sha256': export['sha256'], 'overlay_head': copy.deepcopy(head),
            'rule_count': len(rules)}


if __name__ == "__main__":
    raise SystemExit(main())
