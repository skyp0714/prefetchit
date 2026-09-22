#!/usr/bin/env bash
# Insert wake-stream marks (WS_MARK(id): weak call into the LD_PRELOAD runtime) into the movie-id source. apply | revert
set -eu
MMS=/home/hnpark2/prefetchit/benchmarks/DeathStarBench/mediaMicroservices
H=$MMS/src/MovieIdService/MovieIdHandler.h; G=$MMS/gen-cpp/MovieIdService.cpp; B=$MMS/.ws_backup
case ${1:-} in
apply)
  mkdir -p $B; cp -n $H $B/MovieIdHandler.h; cp -n $G $B/MovieIdService.cpp
  cat > $MMS/src/MovieIdService/ws_mark.h <<'EOH'
#pragma once
/* wake-stream mark: resolved by the LD_PRELOAD runtime (ws_rt.c) when present, a null weak symbol otherwise (2 instructions). */
extern "C" void ws_mark(int id) __attribute__((weak));
#define WS_MARK(id) do { if (ws_mark) ws_mark(id); } while (0)
EOH
  python3 - "$H" "$G" <<'PY'
import sys, re
H, G = sys.argv[1:3]
h = open(H).read(); assert 'WS_MARK' not in h, 'already patched'
a = h.index('void MovieIdHandler::UploadMovieId('); b = h.index('void MovieIdHandler::RegisterMovieId')
u = h[a:b]
def rep(txt, old, new, cnt=1):
    assert txt.count(old) >= 1, 'anchor missing: ' + old[:60]
    return txt.replace(old, new, cnt)
u = rep(u, "  opentracing::Tracer::Global()->Inject(span->context(), writer);\n", "  opentracing::Tracer::Global()->Inject(span->context(), writer);\n  WS_MARK(3);\n")
u = rep(u, "      &memcached_rc);\n  if (!movie_id_mmc && memcached_rc != MEMCACHED_NOTFOUND) {", "      &memcached_rc);\n  WS_MARK(4);\n  if (!movie_id_mmc && memcached_rc != MEMCACHED_NOTFOUND) {")
u = rep(u, "    bool found = mongoc_cursor_next(cursor, &doc);\n", "    bool found = mongoc_cursor_next(cursor, &doc);\n    WS_MARK(5);\n")
u = rep(u, "  set_future = std::async(std::launch::async, [&]() {\n", "  set_future = std::async(std::launch::async, [&]() {\n    WS_MARK(6);\n")
u = rep(u, "  movie_id_future = std::async(std::launch::async, [&]() {\n", "  movie_id_future = std::async(std::launch::async, [&]() {\n    WS_MARK(7);\n")
u = rep(u, "  rating_future = std::async(std::launch::async, [&]() {\n", "  rating_future = std::async(std::launch::async, [&]() {\n    WS_MARK(8);\n")
u = rep(u, "    set_future.get();\n  } catch (...) {\n    throw;\n  }\n\n  span->Finish();", "    set_future.get();\n  } catch (...) {\n    throw;\n  }\n  WS_MARK(9);\n\n  span->Finish();")
h = h[:a] + u + h[b:]
h = h.replace('#include', '#include "ws_mark.h"\n#include', 1)
open(H, 'w').write(h)
g = open(G).read(); assert 'WS_MARK' not in g
g = rep(g, "void MovieIdServiceProcessor::process_UploadMovieId(int32_t seqid, ::apache::thrift::protocol::TProtocol* iprot, ::apache::thrift::protocol::TProtocol* oprot, void* callContext)\n{\n", "void MovieIdServiceProcessor::process_UploadMovieId(int32_t seqid, ::apache::thrift::protocol::TProtocol* iprot, ::apache::thrift::protocol::TProtocol* oprot, void* callContext)\n{\n  WS_MARK(1);\n")
g = rep(g, "void MovieIdServiceProcessor::process_RegisterMovieId(int32_t seqid, ::apache::thrift::protocol::TProtocol* iprot, ::apache::thrift::protocol::TProtocol* oprot, void* callContext)\n{\n", "void MovieIdServiceProcessor::process_RegisterMovieId(int32_t seqid, ::apache::thrift::protocol::TProtocol* iprot, ::apache::thrift::protocol::TProtocol* oprot, void* callContext)\n{\n  WS_MARK(2);\n")
g = g.replace('#include', '#include "../src/MovieIdService/ws_mark.h"\n#include', 1)
open(G, 'w').write(g)
print('patched: handler marks', h.count('WS_MARK('), 'gen-cpp marks', g.count('WS_MARK('))
PY
  ;;
revert) cp $B/MovieIdHandler.h $H; cp $B/MovieIdService.cpp $G; rm -f $MMS/src/MovieIdService/ws_mark.h; echo reverted;;
*) echo "usage: $0 apply|revert"; exit 1;;
esac
