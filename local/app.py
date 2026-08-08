#!/usr/bin/env python3
import json, os, re, sqlite3, urllib.request, urllib.error
from http.server import ThreadingHTTPServer, SimpleHTTPRequestHandler
from pathlib import Path
from datetime import datetime, timezone
from tools import TOOLS, public_registry, execute, validate_arguments, permission_scope, RISK_READ, RISK_WRITE, RISK_NETWORK, RISK_DANGEROUS, RISK_FORBIDDEN

ROOT=Path(__file__).resolve().parent; REPO=ROOT.parent; DB_PATH=ROOT/"cl4nk.db"; PERSONALITY_PATH=REPO/"personality.md"; UI_PATH=ROOT/"index.html"
HOST=os.getenv("CL4NK_HOST","127.0.0.1"); PORT=int(os.getenv("CL4NK_PORT","4242")); DEFAULT_BASE_URL=os.getenv("CL4NK_BASE_URL","http://127.0.0.1:11434/v1"); DEFAULT_MODEL=os.getenv("CL4NK_MODEL","llama3.2")
STOPWORDS={"about","after","again","also","and","are","because","been","before","being","but","can","could","did","does","doing","for","from","had","has","have","here","how","into","its","just","like","more","not","now","only","our","out","really","should","some","than","that","the","their","them","then","there","these","they","this","those","too","was","were","what","when","where","which","who","why","will","with","would","you","your"}

def now(): return datetime.now(timezone.utc).isoformat()
def db():
 c=sqlite3.connect(DB_PATH); c.row_factory=sqlite3.Row
 c.executescript("""CREATE TABLE IF NOT EXISTS settings(key TEXT PRIMARY KEY,value TEXT NOT NULL); CREATE TABLE IF NOT EXISTS messages(id INTEGER PRIMARY KEY AUTOINCREMENT,role TEXT NOT NULL,content TEXT NOT NULL,created_at TEXT NOT NULL); CREATE TABLE IF NOT EXISTS memories(id INTEGER PRIMARY KEY AUTOINCREMENT,content TEXT NOT NULL,importance INTEGER NOT NULL DEFAULT 5,created_at TEXT NOT NULL,updated_at TEXT NOT NULL); CREATE TABLE IF NOT EXISTS permissions(id INTEGER PRIMARY KEY AUTOINCREMENT,tool TEXT NOT NULL,scope TEXT NOT NULL,decision TEXT NOT NULL,updated_at TEXT NOT NULL,UNIQUE(tool,scope)); CREATE TABLE IF NOT EXISTS actions(id INTEGER PRIMARY KEY AUTOINCREMENT,tool TEXT NOT NULL,args TEXT NOT NULL,risk TEXT NOT NULL,scope TEXT,status TEXT NOT NULL,result TEXT,error TEXT,created_at TEXT NOT NULL,completed_at TEXT); CREATE TABLE IF NOT EXISTS pending_actions(id INTEGER PRIMARY KEY AUTOINCREMENT,tool TEXT NOT NULL,args TEXT NOT NULL,risk TEXT NOT NULL,scope TEXT,status TEXT NOT NULL DEFAULT 'pending',created_at TEXT NOT NULL); CREATE TABLE IF NOT EXISTS memory_events(id INTEGER PRIMARY KEY AUTOINCREMENT,source TEXT NOT NULL,candidate TEXT NOT NULL,importance INTEGER NOT NULL,status TEXT NOT NULL,reason TEXT,created_at TEXT NOT NULL);""")
 cols={r['name'] for r in c.execute('PRAGMA table_info(memories)').fetchall()}
 if 'access_count' not in cols:c.execute('ALTER TABLE memories ADD COLUMN access_count INTEGER NOT NULL DEFAULT 0')
 if 'last_accessed_at' not in cols:c.execute('ALTER TABLE memories ADD COLUMN last_accessed_at TEXT')
 # v1 permissions had tool as a primary key. Preserve grants while migrating.
 pcols={r['name'] for r in c.execute('PRAGMA table_info(permissions)').fetchall()}
 if pcols and 'scope' not in pcols:
  old=[dict(r) for r in c.execute('SELECT tool,decision,updated_at FROM permissions').fetchall()]
  c.execute('ALTER TABLE permissions RENAME TO permissions_v1')
  c.execute('CREATE TABLE permissions(id INTEGER PRIMARY KEY AUTOINCREMENT,tool TEXT NOT NULL,scope TEXT NOT NULL,decision TEXT NOT NULL,updated_at TEXT NOT NULL,UNIQUE(tool,scope))')
  for r in old:c.execute('INSERT OR IGNORE INTO permissions(tool,scope,decision,updated_at) VALUES(?,?,?,?)',(r['tool'],'global',r['decision'],r['updated_at']))
  c.execute('DROP TABLE permissions_v1')
 for table in ('actions','pending_actions'):
  cols={r['name'] for r in c.execute(f'PRAGMA table_info({table})').fetchall()}
  if 'scope' not in cols:c.execute(f'ALTER TABLE {table} ADD COLUMN scope TEXT')
 return c

def setting(c,k,f=""):
 r=c.execute('SELECT value FROM settings WHERE key=?',(k,)).fetchone(); return r['value'] if r else f
def set_setting(c,k,v): c.execute('INSERT INTO settings(key,value) VALUES(?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value',(k,str(v)))
def personality():
 try:return PERSONALITY_PATH.read_text(encoding='utf-8')
 except:return 'You are CL4NK, a useful local-first robotic companion. Accuracy outranks character.'
def tokens(t):return {w for w in re.findall(r'[a-z0-9][a-z0-9_-]+',t.lower()) if len(w)>2 and w not in STOPWORDS}
def select_memories(c,q,limit=8):
 rows=c.execute('SELECT * FROM memories').fetchall(); qt=tokens(q); scored=[]
 for r in rows:
  mt=tokens(r['content']); overlap=len(qt&mt); rel=(overlap/max(1,len(qt))*.65)+(overlap/max(1,len(mt))*.35); scored.append((rel*10+r['importance']/10,overlap,r))
 anchors=sorted(rows,key=lambda r:(r['importance'],r['updated_at']),reverse=True)[:2]; chosen={r['id']:r for r in anchors}
 for _,overlap,r in sorted(scored,key=lambda x:x[0],reverse=True):
  if len(chosen)>=limit:break
  if overlap:chosen[r['id']]=r
 return list(chosen.values())
def memory_block(c,q):
 rows=select_memories(c,q)
 if not rows:return 'No durable user memories are stored yet.'
 ids=[r['id'] for r in rows]; c.execute(f"UPDATE memories SET access_count=access_count+1,last_accessed_at=? WHERE id IN ({','.join('?' for _ in ids)})",(now(),*ids)); return '\n'.join(f"- ({r['importance']}/10) {r['content']}" for r in rows)
def recent_messages(c,limit=28):return [{'role':r['role'],'content':r['content']} for r in reversed(c.execute('SELECT role,content FROM messages ORDER BY id DESC LIMIT ?',(limit,)).fetchall())]
def model_call(c,messages,temperature=.8):
 url=setting(c,'base_url',DEFAULT_BASE_URL).rstrip('/')+'/chat/completions'; payload=json.dumps({'model':setting(c,'model',DEFAULT_MODEL),'messages':messages,'temperature':temperature,'stream':False}).encode(); req=urllib.request.Request(url,data=payload,headers={'Content-Type':'application/json','Authorization':'Bearer '+setting(c,'api_key','local')},method='POST')
 try:
  with urllib.request.urlopen(req,timeout=180) as resp:data=json.loads(resp.read().decode())
  return data['choices'][0]['message']['content']
 except urllib.error.URLError as e:raise RuntimeError(f'Could not reach local model server: {e}')
def tool_context(c):
 return {'workspace':setting(c,'workspace',str(REPO)),'command_allowlist':[x for x in setting(c,'command_allowlist','python,python3,node,npm,git').split(',') if x.strip()]}
def tool_instructions():
 return """\n\nYou have permissioned tools. When an action is necessary, respond ONLY with one JSON object: {\"tool\":\"tool_name\",\"arguments\":{...}}. Never claim an action happened unless a tool result says it did. Never invent tool names or arguments. Available tools:\n"""+json.dumps(public_registry())
def parse_tool(text):
 try:
  obj=json.loads(text.strip())
  if not isinstance(obj,dict) or set(obj)!={'tool','arguments'} or not isinstance(obj['tool'],str):return None
  validate_arguments(obj['tool'],obj['arguments']); return obj
 except:return None
def permission(c,name,risk,scope):
 if risk==RISK_FORBIDDEN:return 'deny'
 rows=c.execute('SELECT scope,decision FROM permissions WHERE tool=?',(name,)).fetchall()
 for r in rows:
  if r['scope']=='global' or r['scope']==scope:return r['decision']
  if scope and r['scope'].startswith('path:') and scope.startswith('path:'):
   try:
    Path(scope[5:]).relative_to(Path(r['scope'][5:])); return r['decision']
   except ValueError:pass
 if risk==RISK_READ and setting(c,'auto_read_tools','0')=='1':return 'allow'
 return 'ask'
def audit(c,name,args,risk,scope,status,result=None,error=None):
 c.execute('INSERT INTO actions(tool,args,risk,scope,status,result,error,created_at,completed_at) VALUES(?,?,?,?,?,?,?,?,?)',(name,json.dumps(args),risk,scope,status,json.dumps(result) if result is not None else None,error,now(),now() if status in ('completed','failed','denied') else None))
def run_tool(c,name,args):
 tool=TOOLS.get(name)
 if not tool:raise ValueError('Unknown tool')
 validate_arguments(name,args); ctx=tool_context(c); risk=tool['risk']; scope=permission_scope(name,args,ctx); decision=permission(c,name,risk,scope)
 if decision=='deny':audit(c,name,args,risk,scope,'denied',error='Permission denied'); return {'denied':True,'tool':name,'scope':scope}
 if decision=='ask':
  cur=c.execute('INSERT INTO pending_actions(tool,args,risk,scope,status,created_at) VALUES(?,?,?,?,?,?)',(name,json.dumps(args),risk,scope,'pending',now())); audit(c,name,args,risk,scope,'pending'); return {'permission_required':True,'pending_id':cur.lastrowid,'tool':name,'risk':risk,'scope':scope,'arguments':args}
 try:r=execute(name,args,ctx); audit(c,name,args,risk,scope,'completed',r); return {'tool':name,'scope':scope,'result':r}
 except Exception as e:audit(c,name,args,risk,scope,'failed',error=str(e)); return {'tool':name,'scope':scope,'error':str(e)}
def maybe_form_memory(c,user_text,assistant_text):
 if setting(c,'auto_memory','1')!='1' or len(user_text)<12:return
 prompt='''You are CL4NK's conservative memory curator. Decide whether the USER message contains a durable fact, preference, ongoing project constraint, relationship/name, or explicit future-use information worth remembering. Do NOT store transient requests, secrets/passwords/API keys, medical/legal/financial sensitive details, guesses, assistant claims, or facts that are only relevant to the current turn. Return ONLY JSON: {"remember":false,"reason":"..."} OR {"remember":true,"memory":"one concise user-grounded sentence","importance":1-10,"reason":"..."}.''' 
 try:
  raw=model_call(c,[{'role':'system','content':prompt},{'role':'user','content':user_text}],temperature=.1); obj=json.loads(raw.strip())
  if not obj.get('remember'):return
  mem=str(obj.get('memory','')).strip()[:500]; importance=max(1,min(10,int(obj.get('importance',5)))); reason=str(obj.get('reason',''))[:500]
  if not mem:return
  # Lexical dedupe is intentionally conservative. Similar existing memories are logged as skipped.
  mt=tokens(mem); duplicate=None
  for r in c.execute('SELECT id,content FROM memories').fetchall():
   rt=tokens(r['content']); similarity=len(mt&rt)/max(1,len(mt|rt))
   if similarity>=.72:duplicate=r;break
  if duplicate:c.execute('INSERT INTO memory_events(source,candidate,importance,status,reason,created_at) VALUES(?,?,?,?,?,?)',('conversation',mem,importance,'skipped_duplicate',reason,now()));return
  t=now();c.execute('INSERT INTO memories(content,importance,created_at,updated_at) VALUES(?,?,?,?)',(mem,importance,t,t));c.execute('INSERT INTO memory_events(source,candidate,importance,status,reason,created_at) VALUES(?,?,?,?,?,?)',('conversation',mem,importance,'stored',reason,now()))
 except Exception as e:c.execute('INSERT INTO memory_events(source,candidate,importance,status,reason,created_at) VALUES(?,?,?,?,?,?)',('conversation','',1,'failed',str(e)[:500],now()))
def chat(c,user_text):
 system=personality()+'\n\nRelevant durable memory supplied by the user:\n'+memory_block(c,user_text)+tool_instructions(); messages=[{'role':'system','content':system}]+recent_messages(c)+[{'role':'user','content':user_text}]
 reply=model_call(c,messages); req=parse_tool(reply)
 if not req:return {'reply':reply}
 action=run_tool(c,req['tool'],req['arguments'])
 if action.get('permission_required'):return {'reply':f"Permission required for {action['tool']} ({action['scope']}).",'pending':action}
 if action.get('denied'):return {'reply':f"Tool {action['tool']} is not permitted."}
 final=model_call(c,messages+[{'role':'assistant','content':reply},{'role':'user','content':'TOOL RESULT: '+json.dumps(action)+'. Continue and answer the original request. Do not claim anything beyond this result.'}]); return {'reply':final}
def state(c):
 return {'settings':{'base_url':setting(c,'base_url',DEFAULT_BASE_URL),'model':setting(c,'model',DEFAULT_MODEL),'workspace':setting(c,'workspace',str(REPO)),'auto_read_tools':setting(c,'auto_read_tools','0')=='1','auto_memory':setting(c,'auto_memory','1')=='1','command_allowlist':setting(c,'command_allowlist','python,python3,node,npm,git'),'has_api_key':bool(setting(c,'api_key',''))},'messages':[dict(r) for r in c.execute('SELECT id,role,content,created_at FROM messages ORDER BY id').fetchall()],'memories':[dict(r) for r in c.execute('SELECT id,content,importance,created_at,updated_at,access_count,last_accessed_at FROM memories ORDER BY importance DESC,updated_at DESC').fetchall()],'tools':public_registry(),'permissions':[dict(r) for r in c.execute('SELECT * FROM permissions ORDER BY tool,scope').fetchall()],'pending':[dict(r) for r in c.execute("SELECT * FROM pending_actions WHERE status='pending' ORDER BY id").fetchall()],'actions':[dict(r) for r in c.execute('SELECT * FROM actions ORDER BY id DESC LIMIT 50').fetchall()],'memory_events':[dict(r) for r in c.execute('SELECT * FROM memory_events ORDER BY id DESC LIMIT 50').fetchall()]}
class Handler(SimpleHTTPRequestHandler):
 def log_message(self,fmt,*args):print('[CL4NK]',fmt%args)
 def send_json(self,obj,status=200):
  body=json.dumps(obj).encode();self.send_response(status);self.send_header('Content-Type','application/json');self.send_header('Content-Length',str(len(body)));self.end_headers();self.wfile.write(body)
 def read_json(self):return json.loads(self.rfile.read(min(int(self.headers.get('Content-Length','0')),1_000_000)).decode() or '{}')
 def do_GET(self):
  if self.path=='/api/state':
   with db() as c:self.send_json(state(c));return
  if self.path=='/api/export':
   with db() as c:o=state(c);o['format']='cl4nk.identity.v2';o['exported_at']=now();[o.pop(k,None) for k in ('actions','pending','memory_events')];self.send_json(o);return
  if self.path in ('/','/index.html'):
   b=UI_PATH.read_bytes();self.send_response(200);self.send_header('Content-Type','text/html; charset=utf-8');self.send_header('Content-Length',str(len(b)));self.end_headers();self.wfile.write(b);return
  self.send_error(404)
 def do_POST(self):
  try:
   d=self.read_json()
   if self.path=='/api/chat':
    text=str(d.get('message','')).strip()
    if not text:return self.send_json({'error':'Message is empty'},400)
    with db() as c:
     out=chat(c,text);c.execute("INSERT INTO messages(role,content,created_at) VALUES('user',?,?)",(text,now()));c.execute("INSERT INTO messages(role,content,created_at) VALUES('assistant',?,?)",(out['reply'],now()));maybe_form_memory(c,text,out['reply']);c.commit();out['state']=state(c);self.send_json(out);return
   if self.path=='/api/memory':
    with db() as c:t=now();c.execute('INSERT INTO memories(content,importance,created_at,updated_at) VALUES(?,?,?,?)',(str(d['content']).strip(),max(1,min(10,int(d.get('importance',5)))),t,t));c.commit();self.send_json(state(c));return
   if self.path=='/api/settings':
    with db() as c:
     for k in ('base_url','model','api_key','workspace','command_allowlist'):
      if k in d:set_setting(c,k,d[k])
     for k in ('auto_read_tools','auto_memory'):
      if k in d:set_setting(c,k,'1' if d[k] else '0')
     c.commit();self.send_json(state(c));return
   if self.path.startswith('/api/permission/'):
    pid=int(self.path.rsplit('/',1)[1]);decision=d.get('decision')
    with db() as c:
     p=c.execute("SELECT * FROM pending_actions WHERE id=? AND status='pending'",(pid,)).fetchone()
     if not p:return self.send_json({'error':'Pending action not found'},404)
     if decision=='always':c.execute('INSERT INTO permissions(tool,scope,decision,updated_at) VALUES(?,?,?,?) ON CONFLICT(tool,scope) DO UPDATE SET decision=excluded.decision,updated_at=excluded.updated_at',(p['tool'],p['scope'],'allow',now()));decision='allow'
     if decision=='deny':c.execute("UPDATE pending_actions SET status='denied' WHERE id=?",(pid,));audit(c,p['tool'],json.loads(p['args']),p['risk'],p['scope'],'denied',error='User denied');c.commit();self.send_json(state(c));return
     if decision!='allow':return self.send_json({'error':'Invalid decision'},400)
     args=json.loads(p['args']);validate_arguments(p['tool'],args);result=execute(p['tool'],args,tool_context(c));c.execute("UPDATE pending_actions SET status='completed' WHERE id=?",(pid,));audit(c,p['tool'],args,p['risk'],p['scope'],'completed',result);c.commit();self.send_json({'result':result,'state':state(c)});return
   self.send_error(404)
  except Exception as e:self.send_json({'error':str(e)},500)
 def do_DELETE(self):
  try:
   parts=self.path.strip('/').split('/')
   with db() as c:
    if len(parts)==3 and parts[:2]==['api','memory']:c.execute('DELETE FROM memories WHERE id=?',(int(parts[2]),));c.commit();self.send_json(state(c));return
    if len(parts)==3 and parts[:2]==['api','permission']:c.execute('DELETE FROM permissions WHERE id=?',(int(parts[2]),));c.commit();self.send_json(state(c));return
    if self.path=='/api/history':c.execute('DELETE FROM messages');c.commit();self.send_json(state(c));return
   self.send_error(404)
  except Exception as e:self.send_json({'error':str(e)},500)
def main():
 with db() as c:
  if not setting(c,'base_url'):set_setting(c,'base_url',DEFAULT_BASE_URL)
  if not setting(c,'model'):set_setting(c,'model',DEFAULT_MODEL)
  if not setting(c,'workspace'):set_setting(c,'workspace',str(REPO))
  if not setting(c,'command_allowlist'):set_setting(c,'command_allowlist','python,python3,node,npm,git')
  c.commit()
 print(f'CL4NK local runtime: http://{HOST}:{PORT}');print(f'Workspace: {REPO}');ThreadingHTTPServer((HOST,PORT),Handler).serve_forever()
if __name__=='__main__':main()
