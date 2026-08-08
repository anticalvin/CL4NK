"""CL4NK tool registry v1.

Small, auditable tools with explicit risk classes. The runtime owns permission
checks; tool implementations never get to approve themselves.
"""
from pathlib import Path
import json, os, platform

RISK_READ = "read_only"
RISK_WRITE = "local_write"
RISK_DANGEROUS = "destructive_external"
RISK_FORBIDDEN = "forbidden"


def _workspace(root, requested="."):
    root = Path(root).resolve()
    path = (root / requested).resolve()
    try:
        path.relative_to(root)
    except ValueError:
        raise ValueError("Path escapes the configured CL4NK workspace")
    return path


def list_directory(args, ctx):
    path = _workspace(ctx["workspace"], args.get("path", "."))
    if not path.is_dir(): raise ValueError("Not a directory")
    items=[]
    for p in sorted(path.iterdir(), key=lambda x:(not x.is_dir(), x.name.lower()))[:500]:
        items.append({"name":p.name,"type":"directory" if p.is_dir() else "file","size":None if p.is_dir() else p.stat().st_size})
    return {"path":str(path),"items":items}


def read_file(args, ctx):
    path = _workspace(ctx["workspace"], args["path"])
    if not path.is_file(): raise ValueError("Not a file")
    max_bytes=min(int(args.get("max_bytes",200000)),1000000)
    raw=path.read_bytes()[:max_bytes]
    return {"path":str(path),"content":raw.decode("utf-8",errors="replace"),"truncated":path.stat().st_size>len(raw)}


def search_files(args, ctx):
    root=_workspace(ctx["workspace"],args.get("path",".")); needle=str(args["query"]).lower(); results=[]
    for p in root.rglob("*"):
        if len(results)>=100: break
        if not p.is_file() or p.stat().st_size>1000000: continue
        try: text=p.read_text(encoding="utf-8",errors="ignore")
        except OSError: continue
        for n,line in enumerate(text.splitlines(),1):
            if needle in line.lower():
                results.append({"path":str(p.relative_to(Path(ctx["workspace"]).resolve())),"line":n,"text":line[:500]})
                if len(results)>=100: break
    return {"query":needle,"results":results}


def write_file(args, ctx):
    path=_workspace(ctx["workspace"],args["path"]); path.parent.mkdir(parents=True,exist_ok=True)
    existed=path.exists(); content=str(args.get("content","")); path.write_text(content,encoding="utf-8")
    return {"path":str(path),"bytes":len(content.encode()),"replaced":existed}


def system_info(args, ctx):
    return {"platform":platform.platform(),"python":platform.python_version(),"machine":platform.machine(),"workspace":str(Path(ctx["workspace"]).resolve())}


TOOLS={
 "list_directory":{"description":"List files and directories inside the configured workspace.","risk":RISK_READ,"handler":list_directory,"schema":{"path":"string, optional"}},
 "read_file":{"description":"Read a UTF-8/text file inside the configured workspace.","risk":RISK_READ,"handler":read_file,"schema":{"path":"string","max_bytes":"integer, optional"}},
 "search_files":{"description":"Search text files inside the configured workspace.","risk":RISK_READ,"handler":search_files,"schema":{"query":"string","path":"string, optional"}},
 "write_file":{"description":"Create or replace a text file inside the configured workspace.","risk":RISK_WRITE,"handler":write_file,"schema":{"path":"string","content":"string"}},
 "system_info":{"description":"Return basic local system/runtime information.","risk":RISK_READ,"handler":system_info,"schema":{}},
 "run_command":{"description":"Command execution is reserved but disabled in v1.","risk":RISK_FORBIDDEN,"handler":None,"schema":{"command":"string"}}
}


def public_registry():
    return [{"name":name,"description":t["description"],"risk":t["risk"],"schema":t["schema"]} for name,t in TOOLS.items()]


def execute(name,args,ctx):
    tool=TOOLS.get(name)
    if not tool: raise ValueError("Unknown tool")
    if tool["risk"]==RISK_FORBIDDEN or not tool["handler"]: raise PermissionError("Tool is forbidden in this CL4NK build")
    return tool["handler"](args or {},ctx)
