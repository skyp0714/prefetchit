-- 100% read-user-timeline load for wrk2 (from the mixed script's read_user_timeline; no writes → no dataset drift)
local time = os.time()*1000 + math.floor(os.clock()*1000000); math.randomseed(time); math.random(); math.random(); math.random()
local max_user_index = tonumber(os.getenv("max_user_index")) or 962
request = function()
  local user_id = tostring(math.random(0, max_user_index - 1))
  local start = math.random(0, 100); local stop = start + 10
  local args = "user_id=" .. user_id .. "&start=" .. tostring(start) .. "&stop=" .. tostring(stop)
  local headers = {}; headers["Content-Type"] = "application/x-www-form-urlencoded"
  return wrk.format("GET", "http://localhost:8080/wrk2-api/user-timeline/read?" .. args, headers, nil)
end
