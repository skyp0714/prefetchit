import pymongo, random, time, sys, threading
c = pymongo.MongoClient("mongodb://127.0.0.1:27017", maxPoolSize=64)
db = c.bench; col = db.docs
if col.estimated_document_count() < 1000000:
    col.drop(); batch=[]
    for i in range(1000000):
        batch.append({"_id": i, "k": random.randrange(100000), "s": "x"*random.randrange(20,200), "v": random.random(), "tags": [random.randrange(50) for _ in range(5)]})
        if len(batch)==5000: col.insert_many(batch); batch=[]
    col.create_index("k"); col.create_index("tags")
dur = float(sys.argv[1]) if len(sys.argv)>1 else 60
def worker(stop, cnt):
    r=random.Random(threading.get_ident())
    while time.time() < stop:
        op=r.random()
        if op<0.6: col.find_one({"_id": r.randrange(1000000)})
        elif op<0.8: list(col.find({"k": r.randrange(100000)}).limit(20))
        elif op<0.95: col.update_one({"_id": r.randrange(1000000)}, {"$inc": {"v": 1}})
        else: list(col.aggregate([{"$match": {"tags": r.randrange(50)}}, {"$group": {"_id": "$k", "n": {"$sum": 1}}}, {"$limit": 5}]))
        cnt[0]+=1
stop=time.time()+dur; cnts=[[0] for _ in range(16)]
ts=[threading.Thread(target=worker,args=(stop,cnts[i])) for i in range(16)]
[t.start() for t in ts]; [t.join() for t in ts]
print("ops", sum(x[0] for x in cnts), "ops/s", sum(x[0] for x in cnts)/dur)
