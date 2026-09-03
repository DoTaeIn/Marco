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

import argparse
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import re
import tempfile
import zipfile


형식버전 = 2
고정시각 = (1980, 1, 1, 0, 0, 0)


class KGPackError(RuntimeError):
    pass


def _해시(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _안전경로(name: str) -> PurePosixPath:
    p = PurePosixPath(name)
    if p.is_absolute() or not p.parts or ".." in p.parts or "" in p.parts:
        raise KGPackError("안전하지 않은 pack 경로: %s" % name)
    return p


def _쓰기(zf: zipfile.ZipFile, name: str, data: bytes) -> None:
    info = zipfile.ZipInfo(name, 고정시각)
    info.compress_type = zipfile.ZIP_DEFLATED
    info.external_attr = 0o100644 << 16
    zf.writestr(info, data)


def 기본파일(root: str | os.PathLike = ".") -> list[Path]:
    root = Path(root).resolve()
    return sorted(root.glob("graphs/*.kg")) + sorted(root.glob("styles/*.json"))


_인용문 = re.compile(r'"((?:\\.|[^"\\])*)"')


def _그래프메타(name: str, data: bytes, 최대예시=90) -> dict:
    """벡터를 만들지 않고 KG의 역할·목표·노드 예시만 읽는다."""
    text = data.decode("utf-8")
    역할, 목표, 구역, 예시 = "", "", "", []
    for raw in text.splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("[") and line.endswith("]"):
            구역 = line[1:-1].strip()
            continue
        if line.startswith("역할:"):
            역할 = line.split(":", 1)[1].strip()
            continue
        if line.startswith("목표:"):
            목표 = line.split(":", 1)[1].strip()
            continue
        if 구역 not in ("개념", "사례") or ":" not in line:
            continue
        왼쪽, 오른쪽 = line.split(":", 1)
        노드 = 왼쪽.strip().lstrip("*").split("@", 1)[0].strip()
        if 노드:
            예시.append(노드)
        for encoded in _인용문.findall(오른쪽)[:2]:
            try:
                예시.append(json.loads('"' + encoded + '"'))
            except json.JSONDecodeError:
                예시.append(encoded.replace('\\"', '"'))
        if len(예시) >= 최대예시:
            break
    예시 = list(dict.fromkeys(x for x in [목표] + 예시 if x))[:최대예시]
    return {"path": name, "role": 역할, "goal": 목표, "examples": 예시}


def _매니저그래프(항목, 본문) -> dict:
    """KG 하나를 노드 하나로 갖는, pack 내부의 상위 그래프."""
    nodes = []
    for item in sorted(항목, key=lambda x: x["path"]):
        name = item["path"]
        if item["kind"] != "graph" or "템플릿" in name:
            continue
        nodes.append(_그래프메타(name, 본문[name]))
    return {"format": "nai-kg-manager", "version": 1, "role": "노드 매니저",
            "goal": "그래프고르기", "nodes": nodes,
            "edges": [[n["path"], "후보", "그래프고르기"] for n in nodes]}


def 묶기(output: str | os.PathLike, files, root: str | os.PathLike = ".") -> dict:
    root, output = Path(root).resolve(), Path(output).resolve()
    항목, 본문 = [], {}
    for raw in files:
        path = Path(raw).resolve()
        if not path.is_file():
            raise KGPackError("파일이 없습니다: %s" % path)
        try:
            name = path.relative_to(root).as_posix()
        except ValueError as e:
            raise KGPackError("pack 루트 밖의 파일입니다: %s" % path) from e
        _안전경로(name)
        if name in 본문:
            raise KGPackError("중복 경로입니다: %s" % name)
        data = path.read_bytes()
        본문[name] = data
        항목.append({"path": name, "kind": "graph" if name.endswith(".kg") else "asset",
                   "bytes": len(data), "sha256": _해시(data)})
    if not any(x["kind"] == "graph" for x in 항목):
        raise KGPackError(".kg 그래프가 하나도 없습니다")
    manifest = {"format": "nai-kgpack", "version": 형식버전,
                "files": sorted(항목, key=lambda x: x["path"]),
                "manager": _매니저그래프(항목, 본문)}
    output.parent.mkdir(parents=True, exist_ok=True)
    임시 = output.with_name(output.name + ".tmp-%d" % os.getpid())
    try:
        with zipfile.ZipFile(임시, "w") as zf:
            _쓰기(zf, "manifest.json",
                (json.dumps(manifest, ensure_ascii=False, sort_keys=True,
                            separators=(",", ":")) + "\n").encode("utf-8"))
            for name in sorted(본문):
                _쓰기(zf, name, 본문[name])
        os.replace(임시, output)
    finally:
        try:
            임시.unlink()
        except FileNotFoundError:
            pass
    return manifest


def 읽기(pack: str | os.PathLike, 검증=True) -> tuple[dict, dict[str, bytes]]:
    pack = Path(pack)
    try:
        with zipfile.ZipFile(pack) as zf:
            names = zf.namelist()
            if names.count("manifest.json") != 1:
                raise KGPackError("manifest.json이 정확히 하나여야 합니다")
            if len(names) != len(set(names)):
                raise KGPackError("pack 안에 중복 경로가 있습니다")
            manifest = json.loads(zf.read("manifest.json"))
            if manifest.get("format") != "nai-kgpack" or manifest.get("version") != 형식버전:
                raise KGPackError("지원하지 않는 kgpack 형식입니다")
            entries = manifest.get("files")
            if not isinstance(entries, list):
                raise KGPackError("manifest files가 목록이 아닙니다")
            data = {}
            for item in entries:
                name = str(item.get("path", ""))
                _안전경로(name)
                if name == "manifest.json" or name not in names:
                    raise KGPackError("manifest와 archive가 다릅니다: %s" % name)
                body = zf.read(name)
                if 검증 and (len(body) != item.get("bytes") or _해시(body) != item.get("sha256")):
                    raise KGPackError("무결성 검증 실패: %s" % name)
                data[name] = body
            남는것 = set(names) - {"manifest.json"} - set(data)
            if 남는것:
                raise KGPackError("manifest에 없는 파일이 있습니다: %s" % sorted(남는것)[0])
            manager = manifest.get("manager")
            graph_paths = {x["path"] for x in entries if x.get("kind") == "graph"}
            if (not isinstance(manager, dict) or manager.get("format") != "nai-kg-manager"
                    or manager.get("version") != 1 or not isinstance(manager.get("nodes"), list)):
                raise KGPackError("pack에 유효한 노드 매니저 그래프가 없습니다")
            manager_paths = [x.get("path") for x in manager["nodes"] if isinstance(x, dict)]
            if (len(manager_paths) != len(set(manager_paths))
                    or any(x not in graph_paths for x in manager_paths)):
                raise KGPackError("노드 매니저와 pack 그래프 목록이 다릅니다")
            return manifest, data
    except (OSError, zipfile.BadZipFile, json.JSONDecodeError) as e:
        raise KGPackError("kgpack을 읽지 못했습니다: %s" % e) from e


def 풀기(pack: str | os.PathLike, out: str | os.PathLike) -> list[Path]:
    _manifest, data = 읽기(pack, 검증=True)
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


def 자체검사() -> None:
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
        first = 묶기(pack, [a, b, s], root)
        raw1 = pack.read_bytes()
        second = 묶기(pack, [a, b, s], root)
        assert first == second and raw1 == pack.read_bytes()  # 같은 입력은 같은 pack
        manifest, data = 읽기(pack)
        assert len(manifest["files"]) == 3 and data["graphs/가.kg"] == a.read_bytes()
        assert len(manifest["manager"]["nodes"]) == 2
        assert manifest["manager"]["goal"] == "그래프고르기"
        out = root / "out"
        풀기(pack, out)
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
    args = p.parse_args(argv)
    try:
        if args.check:
            자체검사()
            print("kgpack 자체검사: 통과")
        elif args.pack:
            files = [Path(x) for x in args.files] or 기본파일(args.root)
            m = 묶기(args.pack, files, args.root)
            print("%s: 그래프 %d개 · 자산 %d개"
                  % (Path(args.pack).resolve(),
                     sum(x["kind"] == "graph" for x in m["files"]),
                     sum(x["kind"] != "graph" for x in m["files"])))
        elif args.list:
            m, _ = 읽기(args.list)
            for x in m["files"]:
                print("%-5s %8d  %s  %s" % (x["kind"], x["bytes"], x["sha256"][:12], x["path"]))
        else:
            if not args.out:
                p.error("--unpack에는 --out이 필요합니다")
            written = 풀기(args.unpack, args.out)
            print("%s: %d개 파일 복원" % (Path(args.out).resolve(), len(written)))
        return 0
    except KGPackError as e:
        print("kgpack 오류: %s" % e)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
