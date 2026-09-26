import java.nio.file.*;
import org.dacapo.harness.Callback;
import org.dacapo.harness.CommandLineArgs;

/** Bracket complete, validated iterations after >=60s and >=5 warmup iterations. */
public final class WindowCallback extends Callback {
    private final Path dir = Path.of(System.getProperty("window.dir"));
    private final long warmStart = System.nanoTime();
    private int completed = 0, measured = 0;
    private boolean measuring = false, finished = false;
    private long measureStart;
    private final long warmNanos = Long.getLong("window.warmup.seconds", 60L)*1_000_000_000L;
    private final long measureNanos = Long.getLong("window.measure.seconds", 30L)*1_000_000_000L;
    private final int warmIterations = Integer.getInteger("window.warmup.iterations", 5);
    private final int measureIterations = Integer.getInteger("window.measure.iterations", 3);
    public WindowCallback(CommandLineArgs args) { super(args); }
    private void gate(String marker, String ack) {
        try {
            Files.writeString(dir.resolve(marker), Long.toString(ProcessHandle.current().pid()));
            long deadline = System.nanoTime() + 60_000_000_000L;
            while (!Files.exists(dir.resolve(ack))) {
                if (System.nanoTime() > deadline) throw new IllegalStateException("controller timeout: " + ack);
                Thread.sleep(5);
            }
        } catch (Exception e) { throw new RuntimeException(e); }
    }
    @Override public void start(String benchmark) {
        if (!measuring && completed >= warmIterations && System.nanoTime()-warmStart >= warmNanos) {
            gate("ready", "go");
            measuring = true;
            measureStart = System.nanoTime();
        }
        super.start(benchmark);
    }
    @Override public void complete(String benchmark, boolean valid) {
        completed++;
        if (measuring) measured++;
        if (measuring && measured >= measureIterations && System.nanoTime()-measureStart >= measureNanos) {
            try { Files.writeString(dir.resolve("iterations.json"), "{\"warmup\":"+(completed-measured)+",\"measured\":"+measured+"}"); }
            catch (Exception e) { throw new RuntimeException(e); }
            gate("done", "stopped");
            finished = true;
            mode = Mode.TIMING;
        }
        super.complete(benchmark, valid);
        if (!valid) throw new IllegalStateException("benchmark validation failed");
    }
    @Override public boolean runAgain() { iterations++; return !finished; }
}
