"""Inter-trial process isolation for private FeedSim measurement harnesses."""
def patch(source):
    marker=" for rep,arm,rate in cases:\n  env['LEAF_BIN']=str(bins[arm])"
    replacement=""" for rep,arm,rate in cases:
  # run.sh may return before the preceding background server releases its port.
  # A readiness check against that old listener can connect the next driver to
  # a server that is shutting down. Drain before launching the next owned trial.
  drain_start=time.monotonic()
  while True:
   try:
    with socket.socket() as probe:
     probe.setsockopt(socket.SOL_SOCKET,socket.SO_REUSEADDR,1)
     probe.bind(('127.0.0.1',11222))
    break
   except OSError:
    if time.monotonic()-drain_start>60:raise RuntimeError('Previous Leaf listener did not drain; no new trial started')
    time.sleep(.1)
  with (r/'inter_trial_drain.jsonl').open('a') as drain:
   drain.write(json.dumps({'rep':rep,'arm':arm,'waited_s':time.monotonic()-drain_start})+'\\n')
  env['LEAF_BIN']=str(bins[arm])"""
    assert source.count(marker)==1
    source=source.replace(marker,replacement)
    marker='  finally:stop_proc(proc);log.close()'
    replacement="""  finally:
   stop_proc(proc);log.close()
   # Preserve failure evidence too; assertions above may bypass normal parsing.
   leaflog=Path('/tmp/feedsim_log.txt')
   if leaflog.is_file():(d/'server.log').write_bytes(leaflog.read_bytes())
   for pid,path in driver_logs.items():
    if path.is_file():(d/f'driver_{pid}.log').write_bytes(path.read_bytes())"""
    assert source.count(marker)==1
    return source.replace(marker,replacement)
