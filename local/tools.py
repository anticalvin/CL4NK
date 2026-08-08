"""CL4NK permissioned tool registry v2.

Tools are small and auditable. The runtime owns permission decisions; tool
implementations validate arguments and never approve themselves.
"""
from pathlib import Path
from urllib.parse import urlparse, urlencode
import html, ipaddress, json, os, platform, re, shlex, socket, subprocess, urllib.request

RISK_READ = "read_only"
RISK_WRITE = "local_write"
RISK_NETWORK = "external_read"
RISK_DANGEROUS = "destructive_external"
RISK_FORBIDDEN = "forbidden"

MAX_PATH = 1024
MAX_TEXT = 500_000
MAX_WEB_BYTES = 300_000
MAX_COMMAND_OUTPUT = 200_000


def _workspace(root, requested="."):
    root = Path(root).resolve()
    if not isinstance(requested, str) or not requested or len(requested) > MAX_PATH:
        raise ValueError("Invalid path")
    path = (root / requested).resolve()
    try:
        path.relative_to(root)
    except ValueError:
        raise ValueError("Path escapes the configured CL4NK workspace")
    # Existing symlinks are resolved above. For a new write, require the nearest
    # existing parent to remain inside the workspace as well.
    parent = path
    while not parent.exists() and parent != root:
        parent = parent.parent
    try:
        parent.resolve().relative_to(root)
    except ValueError:
        raise ValueError("Path escapes workspace through a symlink")
    return path


def _is_public_host(host):
    if not host:
        return False
    if host.lower() in {"localhost", "localhost.localdomain"}:
        return False
    try:
        infos = socket.getaddrinfo(host, None)
    except socket.gaierror as e:
        raise ValueError(f"Could not resolve host: {e}")
    for info in infos:
        addr = ipaddress.ip_address(info[4][0])
        if not addr.is_global:
            return False
    return True


def _validated_url(value):
    if not isinstance(value, str) or len(value) > 4096:
        raise ValueError("Invalid URL")
    parsed = urlparse(value)
    if parsed.scheme not in {"http", "https"} or not parsed.hostname:
        raise ValueError("Only public http/https URLs are allowed")
    if not _is_public_host(parsed.hostname):
        raise ValueError("Private, loopback, link-local, and non-public network targets are blocked")
    return value


class SafeRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        _validated_url(newurl)
        return super().redirect_request(req, fp, code, msg, headers, newurl)


def validate_arguments(name, args):
    tool = TOOLS.get(name)
    if not tool:
        raise ValueError("Unknown tool")
    if not isinstance(args, dict):
        raise ValueError("Tool arguments must be an object")
    schema = tool["schema"]
    unknown = set(args) - set(schema)
    if unknown:
        raise ValueError("Unknown tool arguments: " + ", ".join(sorted(unknown)))
    for key, rule in schema.items():
        required = rule.get("required", False)
        if required and key not in args:
            raise ValueError(f"Missing required argument: {key}")
        if key not in args:
            continue
        value = args[key]
        typ = rule.get("type")
        if typ == "string" and not isinstance(value, str):
            raise ValueError(f"{key} must be a string")
        if typ == "integer" and (not isinstance(value, int) or isinstance(value, bool)):
            raise ValueError(f"{key} must be an integer")
        if typ == "array" and not isinstance(value, list):
            raise ValueError(f"{key} must be an array")
        if isinstance(value, str):
            if "minLength" in rule and len(value) < rule["minLength"]: raise ValueError(f"{key} is too short")
            if "maxLength" in rule and len(value) > rule["maxLength"]: raise ValueError(f"{key} is too long")
        if isinstance(value, int):
            if "minimum" in rule and value < rule["minimum"]: raise ValueError(f"{key} is too small")
            if "maximum" in rule and value > rule["maximum"]: raise ValueError(f"{key} is too large")
        if isinstance(value, list):
            if len(value) > rule.get("maxItems", 100): raise ValueError(f"{key} has too many items")
            if rule.get("items") == "string" and any(not isinstance(x, str) for x in value): raise ValueError(f"{key} items must be strings")
    return args


def permission_scope(name, args, ctx):
    """Return the narrowest sensible persistent-permission scope for an action."""
    if name in {"list_directory", "read_file", "search_files", "write_file"}:
        requested = args.get("path", ".")
        path = _workspace(ctx["workspace"], requested)
        if name in {"read_file", "write_file"}:
            path = path.parent
        return "path:" + str(path)
    if name in {"fetch_url", "web_search"}:
        if name == "fetch_url":
            return "domain:" + urlparse(_validated_url(args["url"])).hostname.lower()
        return "domain:duckduckgo.com"
    if name == "run_command":
        argv = args.get("argv") or []
        return "exec:" + (Path(argv[0]).name.lower() if argv else "")
    return "global"


def list_directory(args, ctx):
    path = _workspace(ctx["workspace"], args.get("path", "."))
    if not path.is_dir(): raise ValueError("Not a directory")
    items=[]
    for p in sorted(path.iterdir(), key=lambda x:(not x.is_dir(), x.name.lower()))[:500]:
        try: size=None if p.is_dir() else p.stat().st_size
        except OSError: size=None
        items.append({"name":p.name,"type":"directory" if p.is_dir() else "file","size":size})
    return {"path":str(path),"items":items,"truncated":len(items)>=500}


def read_file(args, ctx):
    path = _workspace(ctx["workspace"], args["path"])
    if not path.is_file(): raise ValueError("Not a file")
    max_bytes=min(int(args.get("max_bytes",200000)),MAX_TEXT)
    raw=path.read_bytes()[:max_bytes]
    return {"path":str(path),"content":raw.decode("utf-8",errors="replace"),"truncated":path.stat().st_size>len(raw)}


def search_files(args, ctx):
    root=_workspace(ctx["workspace"],args.get("path",".")); needle=args["query"].lower(); results=[]
    if not root.is_dir(): raise ValueError("Search path is not a directory")
    for p in root.rglob("*"):
        if len(results)>=100: break
        try:
            if not p.is_file() or p.is_symlink() or p.stat().st_size>1_000_000: continue
            p.resolve().relative_to(Path(ctx["workspace"]).resolve())
            text=p.read_text(encoding="utf-8",errors="ignore")
        except (OSError, ValueError): continue
        for n,line in enumerate(text.splitlines(),1):
            if needle in line.lower():
                results.append({"path":str(p.relative_to(Path(ctx["workspace"]).resolve())),"line":n,"text":line[:500]})
                if len(results)>=100: break
    return {"query":needle,"results":results,"truncated":len(results)>=100}


def write_file(args, ctx):
    path=_workspace(ctx["workspace"],args["path"]); path.parent.mkdir(parents=True,exist_ok=True)
    content=args.get("content","")
    if len(content.encode("utf-8")) > MAX_TEXT: raise ValueError("File content exceeds write limit")
    existed=path.exists(); path.write_text(content,encoding="utf-8")
    return {"path":str(path),"bytes":len(content.encode()),"replaced":existed}


def system_info(args, ctx):
    return {"platform":platform.platform(),"python":platform.python_version(),"machine":platform.machine(),"workspace":str(Path(ctx["workspace"]).resolve())}


def fetch_url(args, ctx):
    url=_validated_url(args["url"]); max_bytes=min(args.get("max_bytes",150000),MAX_WEB_BYTES)
    opener=urllib.request.build_opener(SafeRedirect())
    req=urllib.request.Request(url,headers={"User-Agent":"CL4NK/0.2 (+local open-source agent)"})
    with opener.open(req,timeout=15) as resp:
        final=_validated_url(resp.geturl()); content_type=resp.headers.get("Content-Type","")
        raw=resp.read(max_bytes+1); truncated=len(raw)>max_bytes; raw=raw[:max_bytes]
    text=raw.decode("utf-8",errors="replace")
    return {"url":final,"content_type":content_type,"content":text,"truncated":truncated}


def web_search(args, ctx):
    query=args["query"].strip(); limit=min(args.get("limit",8),10)
    url="https://html.duckduckgo.com/html/?"+urlencode({"q":query})
    opener=urllib.request.build_opener(SafeRedirect())
    req=urllib.request.Request(url,headers={"User-Agent":"CL4NK/0.2 (+local open-source agent)"})
    with opener.open(req,timeout=15) as resp: body=resp.read(MAX_WEB_BYTES).decode("utf-8",errors="replace")
    results=[]
    pattern=re.compile(r'class="result__a"[^>]*href="([^"]+)"[^>]*>(.*?)</a>',re.I|re.S)
    for href,title in pattern.findall(body):
        clean=re.sub(r'<[^>]+>','',title); clean=html.unescape(clean).strip()
        if clean:
            results.append({"title":clean[:300],"url":html.unescape(href)[:2000]})
        if len(results)>=limit: break
    return {"query":query,"results":results,"source":"DuckDuckGo HTML"}


def run_command(args, ctx):
    argv=args["argv"]
    if not argv or any((not isinstance(x,str) or not x or len(x)>1000) for x in argv): raise ValueError("Invalid argv")
    executable=Path(argv[0]).name.lower()
    allow={x.strip().lower() for x in ctx.get("command_allowlist",[]) if x.strip()}
    if executable not in allow: raise PermissionError(f"Executable '{executable}' is not in the command allowlist")
    cwd=_workspace(ctx["workspace"],args.get("cwd","."))
    if not cwd.is_dir(): raise ValueError("Command cwd is not a directory")
    timeout=min(args.get("timeout",15),30)
    env={"PATH":os.environ.get("PATH",""),"HOME":str(Path.home()),"LANG":os.environ.get("LANG","C.UTF-8"),"PYTHONIOENCODING":"utf-8"}
    try:
        p=subprocess.run(argv,cwd=str(cwd),env=env,capture_output=True,text=True,timeout=timeout,shell=False)
        out=(p.stdout or "")[:MAX_COMMAND_OUTPUT]; err=(p.stderr or "")[:MAX_COMMAND_OUTPUT]
        return {"argv":argv,"cwd":str(cwd),"returncode":p.returncode,"stdout":out,"stderr":err,"output_truncated":len(p.stdout or "")>MAX_COMMAND_OUTPUT or len(p.stderr or "")>MAX_COMMAND_OUTPUT}
    except subprocess.TimeoutExpired as e:
        return {"argv":argv,"cwd":str(cwd),"timed_out":True,"stdout":(e.stdout or "")[:MAX_COMMAND_OUTPUT] if isinstance(e.stdout,str) else "","stderr":(e.stderr or "")[:MAX_COMMAND_OUTPUT] if isinstance(e.stderr,str) else ""}


TOOLS={
 "list_directory":{"description":"List files and directories inside the configured workspace.","risk":RISK_READ,"handler":list_directory,"schema":{"path":{"type":"string","maxLength":MAX_PATH}}},
 "read_file":{"description":"Read a text file inside the configured workspace.","risk":RISK_READ,"handler":read_file,"schema":{"path":{"type":"string","required":True,"minLength":1,"maxLength":MAX_PATH},"max_bytes":{"type":"integer","minimum":1,"maximum":MAX_TEXT}}},
 "search_files":{"description":"Search text files inside the configured workspace.","risk":RISK_READ,"handler":search_files,"schema":{"query":{"type":"string","required":True,"minLength":1,"maxLength":500},"path":{"type":"string","maxLength":MAX_PATH}}},
 "write_file":{"description":"Create or replace a text file inside the configured workspace.","risk":RISK_WRITE,"handler":write_file,"schema":{"path":{"type":"string","required":True,"minLength":1,"maxLength":MAX_PATH},"content":{"type":"string","required":True,"maxLength":MAX_TEXT}}},
 "system_info":{"description":"Return basic local system/runtime information.","risk":RISK_READ,"handler":system_info,"schema":{}},
 "fetch_url":{"description":"Fetch a public HTTP/HTTPS URL. Private and local network targets are blocked.","risk":RISK_NETWORK,"handler":fetch_url,"schema":{"url":{"type":"string","required":True,"minLength":8,"maxLength":4096},"max_bytes":{"type":"integer","minimum":1,"maximum":MAX_WEB_BYTES}}},
 "web_search":{"description":"Search the public web using DuckDuckGo HTML results.","risk":RISK_NETWORK,"handler":web_search,"schema":{"query":{"type":"string","required":True,"minLength":1,"maxLength":500},"limit":{"type":"integer","minimum":1,"maximum":10}}},
 "run_command":{"description":"Run an argv-only command in the workspace. No shell, 30s maximum, explicit permission required, executable allowlist enforced.","risk":RISK_DANGEROUS,"handler":run_command,"schema":{"argv":{"type":"array","required":True,"items":"string","maxItems":32},"cwd":{"type":"string","maxLength":MAX_PATH},"timeout":{"type":"integer","minimum":1,"maximum":30}}}
}


def public_registry():
    return [{"name":name,"description":t["description"],"risk":t["risk"],"schema":t["schema"]} for name,t in TOOLS.items()]


def execute(name,args,ctx):
    tool=TOOLS.get(name)
    if not tool: raise ValueError("Unknown tool")
    if tool["risk"]==RISK_FORBIDDEN or not tool["handler"]: raise PermissionError("Tool is forbidden in this CL4NK build")
    validate_arguments(name,args or {})
    return tool["handler"](args or {},ctx)
