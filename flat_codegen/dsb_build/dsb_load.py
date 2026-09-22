import urllib.request, urllib.parse, threading, time, random
BASE='http://localhost:8080/wrk2-api'
def post(uid):
    d=urllib.parse.urlencode({'username':f'username_{uid}','user_id':uid,'text':f'hello world {random.random()} @username_{random.randint(1,900)}','media_ids':'[]','media_types':'[]','post_type':'0'}).encode()
    urllib.request.urlopen(f'{BASE}/post/compose', data=d, timeout=5).read()
def home(uid):
    urllib.request.urlopen(f'{BASE}/home-timeline/read?user_id={uid}&start=0&stop=10', timeout=5).read()
def user(uid):
    urllib.request.urlopen(f'{BASE}/user-timeline/read?user_id={uid}&start=0&stop=10', timeout=5).read()
stop=time.time()+75
cnt=[0]*16
def worker(w):
    random.seed(w)
    while time.time()<stop:
        uid=random.randint(1,900)
        try:
            r=random.random()
            if r<0.1: post(uid)
            elif r<0.7: home(uid)
            else: user(uid)
            cnt[w]+=1
        except Exception: pass
ts=[threading.Thread(target=worker,args=(i,)) for i in range(16)]
[t.start() for t in ts]; [t.join() for t in ts]
print('reqs', sum(cnt), 'qps', sum(cnt)/75)
