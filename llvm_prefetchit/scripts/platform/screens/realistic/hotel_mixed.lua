-- hotelReservation mixed workload (DeathStarBench mixed-workload_type_1: 60% search, 39% recommend, 0.5% login, 0.5% reserve)
local time = os.time()*1000 + math.floor(os.clock()*1000000); math.randomseed(time); math.random(); math.random(); math.random()
local function get_user() local id = math.random(0, 500); return "Cornell_" .. tostring(id), string.rep(tostring(id), 10) end
local function search_hotel()
  local in_date = math.random(9, 23); local out_date = math.random(in_date + 1, 24)
  local in_s = in_date < 10 and "2015-04-0" .. in_date or "2015-04-" .. in_date; local out_s = out_date < 10 and "2015-04-0" .. out_date or "2015-04-" .. out_date
  local lat = 38.0235 + (math.random(0, 481) - 240.5) / 1000.0; local lon = -122.095 + (math.random(0, 325) - 157.0) / 1000.0
  return wrk.format("GET", "/hotels?inDate=" .. in_s .. "&outDate=" .. out_s .. "&lat=" .. lat .. "&lon=" .. lon, nil, nil)
end
local function recommend()
  local coin = math.random(); local req = coin < 0.33 and "dis" or (coin < 0.66 and "rate" or "price")
  local lat = 38.0235 + (math.random(0, 481) - 240.5) / 1000.0; local lon = -122.095 + (math.random(0, 325) - 157.0) / 1000.0
  return wrk.format("GET", "/recommendations?require=" .. req .. "&lat=" .. lat .. "&lon=" .. lon, nil, nil)
end
local function user_login() local u, p = get_user(); return wrk.format("GET", "/user?username=" .. u .. "&password=" .. p, nil, nil) end
local function reserve()
  local in_date = math.random(9, 23); local out_date = in_date + math.random(1, 5)
  local in_s = in_date < 10 and "2015-04-0" .. in_date or "2015-04-" .. in_date; local out_s = out_date < 10 and "2015-04-0" .. out_date or "2015-04-" .. out_date
  local hotel_id = tostring(math.random(1, 80)); local u, p = get_user()
  local lat = 38.0235 + (math.random(0, 481) - 240.5) / 1000.0; local lon = -122.095 + (math.random(0, 325) - 157.0) / 1000.0
  return wrk.format("POST", "/reservation?inDate=" .. in_s .. "&outDate=" .. out_s .. "&lat=" .. lat .. "&lon=" .. lon .. "&hotelId=" .. hotel_id .. "&customerName=" .. u .. "&username=" .. u .. "&password=" .. p .. "&number=1", nil, nil)
end
request = function()
  local coin = math.random()
  if coin < 0.6 then return search_hotel() elseif coin < 0.99 then return recommend() elseif coin < 0.995 then return user_login() else return reserve() end
end
