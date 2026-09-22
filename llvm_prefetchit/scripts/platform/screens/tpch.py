import duckdb, time
con = duckdb.connect()
con.execute("INSTALL tpch; LOAD tpch;")
con.execute("CALL dbgen(sf=2)")
con.execute("PRAGMA threads=1")
t0=time.time(); n=0
while time.time()-t0 < 90:
    for q in range(1, 23):
        con.execute(f"PRAGMA tpch({q})").fetchall(); n+=1
print("queries", n)
