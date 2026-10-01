local handlers = {}
local function event(name)
 return {Add=function(f) handlers[name]=f end, Remove=function(f) if handlers[name]==f then handlers[name]=nil end end}
end
Events={OnMainMenuEnter=event('menu'), OnFETick=event('tick')}
local now, request, connections, favorites = 1000, {}, {}, {}
function getTimestampMs() return now end
function getFileReader()
 local i=0
 return {readLine=function() i=i+1; return request[i] end, close=function() end}
end
function getFileWriter() return {close=function() request={} end} end
function isValidUserName(u) return u ~= '' end
function getServerList() return favorites end
local function object()
 local o={}
 for _, k in ipairs({'Name','Ip','Port','UserName','AuthType','SavePwd','UseSteamRelay'}) do
  o['set'..k]=function(self,v) self[k]=v end
  o['get'..k]=function(self) return self[k] end
 end
 o.encryptPwd=function(self,v) self.pwd=v end
 return o
end
Server={new=object};Account={new=object}
function addServerToAccountList(s) table.insert(favorites,s) end
function getCore() return {setAccountUsed=function() end,setNoSave=function() end} end
function stopSendSecretKey() end
MainScreen={instance={bottomPanel={}}}
ConnectToServer={instance={connect=function(self,...) table.insert(connections,{...}) end}}
dofile('launcher_connect.lua')
request={2000,'example.invalid','16261','플레이어','a"\\&',''}
handlers.menu();handlers.tick()
assert(#connections==1 and #favorites==1 and #request==0)
assert(connections[1][3]=='플레이어' and connections[1][4]=='a"\\&')
assert(connections[1][10]==true and connections[1][11]==1)
handlers.menu();handlers.tick();assert(#connections==1)
request={2000,'example.invalid','16261','플레이어','pw','serverpw'}
handlers.menu();handlers.tick();assert(#connections==2 and #favorites==1)
request={900,'example.invalid','16261','플레이어','pw','serverpw'}
handlers.menu();handlers.tick();assert(#connections==2 and #request==0)
print('Launcher Lua: first connect, arguments, favorites dedup, one-shot, expiry passed')
