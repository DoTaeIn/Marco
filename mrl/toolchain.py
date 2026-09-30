"""Private C11 builds with checked modes and an immutable library cache."""
from __future__ import annotations
import hashlib, json, os, platform, shutil, subprocess, sys, sysconfig, tempfile, uuid
from pathlib import Path

_ROOT=Path(__file__).parent; _TOOLS=_ROOT/".tools"; _TIMEOUT=60

def find_compiler():
    # The provisioned local compiler avoids a repeated scan of the Windows PATH.
    if os.name=="nt" and (zig:=next(_TOOLS.glob("zig-*/zig.exe"),None)): return [str(zig),"cc","-target","x86_64-windows-gnu","-std=c11"],False
    for name in ("clang","gcc"):
        if path:=shutil.which(name): return [path,"-std=c11"],False
    vswhere=Path(r"C:\Program Files (x86)\Microsoft Visual Studio\Installer\vswhere.exe"); kits=Path(r"C:\Program Files (x86)\Windows Kits\10\Include")
    if vswhere.exists() and any(kits.glob("*/ucrt/stdio.h")):
        r=subprocess.run([str(vswhere),"-latest","-products","*","-requires","Microsoft.VisualStudio.Component.VC.Tools.x86.x64","-property","installationPath"],capture_output=True,text=True,timeout=10,check=False)
        setup=Path(r.stdout.strip())/"Common7"/"Tools"/"VsDevCmd.bat"
        if setup.exists(): return f'call "{setup}" -arch=x64 -host_arch=x64 >nul && cl /nologo /std:c11',True
    return None,False

def _mode(value):
    if not isinstance(value,str) or value not in {"release","debug"}: raise ValueError("optimization must be 'release' or 'debug'")
    return value
def _env(local_cache=None):
    env=os.environ.copy(); cache=_TOOLS/"cache"; cache.mkdir(parents=True,exist_ok=True); env["ZIG_GLOBAL_CACHE_DIR"]=str(cache/"global"); env["ZIG_LOCAL_CACHE_DIR"]=str(local_cache or cache/"local"); return env
def _build(source,output,shared,optimization):
    optimization=_mode(optimization); command,cmd=find_compiler()
    if command is None: raise RuntimeError("no complete local C11 toolchain")
    source,output=Path(source).resolve(),Path(output).resolve()
    if cmd:
        flags="/O2" if optimization=="release" else "/Od"
        if shared: flags+=" /LD /DMRL_GRAPH_SHARED"
        args=["cmd","/c",f'{command} {flags} "{source}" /Fo:"{source.with_suffix(".obj")}" /Fe:"{output}"']
    else:
        flags=["-O2" if optimization=="release" else "-O0"]+(["-DMRL_GRAPH_SHARED","-shared"] if shared else [])
        if shared and os.name!="nt": flags.append("-fPIC")
        args=command+flags+[str(source),"-o",str(output)]
    cache=_TOOLS/"cache"; cache.mkdir(parents=True,exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="zig-local-",dir=cache) as local_cache:
        subprocess.run(args,cwd=source.parent,env=_env(local_cache),timeout=_TIMEOUT,check=True,capture_output=True)
def build_c(source,output,*,optimization="release"): _build(source,output,False,optimization)
def build_shared(source,library,*,optimization="release"): _build(source,library,True,optimization)

def _extras(value, source_name=None):
    if value is None:return {}
    if not isinstance(value,dict):raise ValueError("extra_files must map simple basenames to bytes")
    if any(not isinstance(k,str) or Path(k).name!=k or any(mark in k for mark in ("/","\\",":")) or k in {"",".",".."} or k==source_name or not isinstance(v,bytes) for k,v in value.items()): raise ValueError("extra_files must map simple basenames to bytes")
    return value
def _platform_tag():
    # platform.platform() may launch cmd.exe on Windows; cache identity needs only ABI facts.
    release=str(sys.getwindowsversion()) if os.name=="nt" else os.uname().release
    return sys.platform+"-"+release

def build_identity(source,*,optimization="release",extra_files=None):
    optimization=_mode(optimization); source=Path(source); extras=_extras(extra_files,source.name); command,cmd=find_compiler()
    if command is None:raise RuntimeError("no complete local C11 toolchain")
    exe=command[0] if isinstance(command,list) else command; fp=None
    if isinstance(command,list) and Path(exe).is_file(): s=Path(exe).stat(); fp=[s.st_size,s.st_mtime_ns]
    source_hash=hashlib.sha256(source.read_bytes()).hexdigest()
    data={"schema":2,"toolchain_hash":hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),"build_config":{"release":"-O2","debug":"-O0"},"source_hash":source_hash,"optimization":optimization,"compiler":{"command":command,"uses_cmd":cmd,"executable":exe,"fingerprint":fp},"platform":_platform_tag(),"machine":sysconfig.get_platform(),"source_name":source.name,"extras":{name:hashlib.sha256(extras[name]).hexdigest() for name in sorted(extras)}}
    data["cache_key"]=hashlib.sha256(json.dumps(data,sort_keys=True,separators=(",",":")).encode()).hexdigest();return data
def cached_shared(source,*,optimization="release",extra_files=None):
    source=Path(source); extras=_extras(extra_files,source.name); identity=build_identity(source,optimization=optimization,extra_files=extras); root=_TOOLS/"native"/identity["cache_key"]; ready=root/"ready.json"
    if ready.exists():
        try:
            meta=json.loads(ready.read_text()); name=meta["library"]
            library=root/name
            if Path(name).name==name and meta.get("identity")==identity and library.is_file():return library
        except (OSError, ValueError, KeyError, TypeError):
            pass
    root.mkdir(parents=True,exist_ok=True); suffix=".dll" if os.name=="nt" else ".dylib" if platform.system()=="Darwin" else ".so"
    with tempfile.TemporaryDirectory(prefix="build-",dir=root) as temp:
        temp=Path(temp); copied=temp/Path(source).name; shutil.copyfile(source,copied)
        for name,data in extras.items():(temp/name).write_bytes(data)
        name="native-"+uuid.uuid4().hex+suffix; built=temp/name; build_shared(copied,built,optimization=optimization); library=root/name; os.replace(built,library)
    staged=root/("ready-"+uuid.uuid4().hex+".json"); staged.write_text(json.dumps({"identity":identity,"library":name},sort_keys=True))
    try: os.replace(staged,ready)
    except PermissionError:
        if ready.exists():
            staged.unlink(missing_ok=True)
            meta=json.loads(ready.read_text()); winner=root/meta["library"]
            if Path(meta["library"]).name==meta["library"] and meta.get("identity")==identity and winner.is_file(): return winner
        raise
    return library
