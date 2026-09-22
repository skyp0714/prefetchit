#!/usr/bin/env python3
"""Generate WideApi: a JDK-httpserver service with N generated endpoint
handler classes. Each handler is a distinct class whose handle() performs
distinct arithmetic/string work (distinct JIT-compiled code bodies), so the
service's steady-state code footprint scales with N — the wide-API fleet
profile (thousands of RPC methods, uniform traffic).

Usage: gen_wideapi.py [N=4000] [outdir=src]
"""
import os
import sys

N = int(sys.argv[1]) if len(sys.argv) > 1 else 4000
OUT = sys.argv[2] if len(sys.argv) > 2 else 'src'
os.makedirs(OUT, exist_ok=True)

for i in range(N):
    # distinct constants -> distinct compiled bodies (no dedup); ~64
    # straight-line ops per body => a few hundred instructions / ~2KB of
    # machine code each, JCS-scale footprint (N x 2KB)
    ops = []
    for k in range(64):
        c1 = (i * 73 + k * 179) % 65521 + 3
        c2 = (i * 31 + k * 97) % 8191 + 1
        sh = (i + k) % 13 + 2
        if k % 4 == 0:
            ops.append(f'    a = a * {c1}L + {c2}L; b ^= a >>> {sh};')
        elif k % 4 == 1:
            ops.append(f'    b = b * {c2}L ^ {c1}L; a += b << {sh};')
        elif k % 4 == 2:
            ops.append(f'    a ^= (b + {c1}L) * {c2}L; b -= a >>> {sh};')
        else:
            ops.append(f'    b += (a ^ {c2}L) * {c1}L; a ^= b << {sh};')
    body = '\n'.join(ops)
    with open(f'{OUT}/Ep{i}.java', 'w') as f:
        f.write(f'''public final class Ep{i} implements WideApi.Handler {{
  private long state = {i * 2654435761 % 1000000007}L;
  public long handle(long v) {{
    long a = v ^ {i}L, b = state;
{body}
    state = b;
    return a + b;
  }}
}}
''')

with open(f'{OUT}/WideApi.java', 'w') as f:
    f.write('''import com.sun.net.httpserver.HttpServer;
import com.sun.net.httpserver.HttpExchange;
import java.net.InetSocketAddress;
import java.nio.charset.StandardCharsets;
import java.util.concurrent.Executors;

/** Wide-API HTTP service: N generated endpoint handlers behind one router. */
public final class WideApi {
  public interface Handler { long handle(long v); }
  static final int N = ''' + str(N) + ''';
  static final int CHAIN = Integer.getInteger("wideapi.chain", 256);
  static final Handler[] HANDLERS = new Handler[N];

  public static void main(String[] args) throws Exception {
    for (int i = 0; i < N; i++) {
      HANDLERS[i] = (Handler) Class.forName("Ep" + i)
          .getDeclaredConstructor().newInstance();
    }
    // warmup pass so every handler gets JIT-compiled
    long acc = 0;
    for (int r = 0; r < 3000; r++)
      for (int i = 0; i < N; i++) acc += HANDLERS[i].handle(r + i);
    System.out.println("warmed " + acc);

    HttpServer srv = HttpServer.create(new InetSocketAddress(8123), 1024);
    srv.createContext("/api/", ex -> {
      String p = ex.getRequestURI().getPath();       // /api/<id>/<val>
      String[] parts = p.split("/");
      int id = Integer.parseInt(parts[2]);
      long v = parts.length > 3 ? Long.parseLong(parts[3]) : 1;
      // composite endpoint: fan out across a chain of generated handlers
      // (mirrors real wide-API services where one request touches many
      // sub-handlers/serializers)
      long out = 0;
      for (int k = 0; k < CHAIN; k++)
        out += HANDLERS[(id + k) % N].handle(v + k);
      byte[] body = Long.toString(out).getBytes(StandardCharsets.UTF_8);
      ex.sendResponseHeaders(200, body.length);
      ex.getResponseBody().write(body);
      ex.close();
    });
    srv.setExecutor(Executors.newFixedThreadPool(16));
    srv.start();
    System.out.println("READY on :8123 with " + N + " endpoints");
  }
}
''')
print(f'generated {N} handlers + WideApi.java in {OUT}/')
