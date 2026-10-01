-- Installed only by the launcher. No request means no change to ordinary play.
local requestName = "pz-launcher-request.txt"
local function connectOnce()
    if not MainScreen or not MainScreen.instance or not ConnectToServer or not ConnectToServer.instance then return end
    Events.OnFETick.Remove(connectOnce)
    local reader = getFileReader(requestName, false)
    if not reader then return end
    local expires = tonumber(reader:readLine())
    local host = reader:readLine()
    local port = reader:readLine()
    local username = reader:readLine()
    local password = reader:readLine()
    local serverPassword = reader:readLine()
    reader:close()
    -- Consume before connecting: returning to the menu must never reconnect.
    local writer = getFileWriter(requestName, true, false)
    if not writer then return end
    writer:close()
    if not expires or getTimestampMs() > expires or not host or not port or not username or not password or not serverPassword then return end
    if not isValidUserName(username) then
        print("[PZ Launcher] Invalid account name; use the launcher to correct it.")
        return
    end
    local ok = pcall(function()
        local found = false
        for _, server in pairs(getServerList()) do
            if server:getIp() == host and tonumber(server:getPort()) == tonumber(port) then found = true; break end
        end
        if not found then
            local server = Server.new()
            server:setName(host .. ":" .. port)
            server:setIp(host)
            server:setPort(tonumber(port))
            addServerToAccountList(server)
        end
    end)
    if not ok then print("[PZ Launcher] Could not save server favorite; continuing connection.") end
    local account = Account.new()
    account:setUserName(username)
    account:encryptPwd(password)
    account:setAuthType(1)
    account:setSavePwd(false)
    account:setUseSteamRelay(false)
    getCore():setAccountUsed(account)
    getCore():setNoSave(false)
    stopSendSecretKey()
    if MainScreen.instance.animPopup then MainScreen.instance.animPopup:removeFromUIManager() end
    print("[PZ Launcher] Connecting to configured server.")
    ConnectToServer.instance:connect(MainScreen.instance.bottomPanel, host .. ":" .. port,
        username, password, host, "", port, serverPassword, false, true, 1)
end
Events.OnMainMenuEnter.Add(function() Events.OnFETick.Add(connectOnce) end)
