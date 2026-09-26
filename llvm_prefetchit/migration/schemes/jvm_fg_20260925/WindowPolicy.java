import java.nio.file.*;
import org.renaissance.Plugin;

/** Gate between complete operations, including the harness validation. */
public final class WindowPolicy implements Plugin.ExecutionPolicy, Plugin.BenchmarkFailureListener,
        Plugin.MeasurementResultListener {
    private final Path dir = Path.of(System.getProperty("window.dir"));
    private final long start = System.nanoTime();
    private long measuredStart;
    private int first = -1;
    private void marker(String name, String ack) {
        try {
            Files.writeString(dir.resolve(name), "" + ProcessHandle.current().pid());
            long end = System.nanoTime() + 90_000_000_000L;
            while (!Files.exists(dir.resolve(ack))) {
                if (System.nanoTime() > end) throw new IllegalStateException("gate timeout " + ack);
                Thread.sleep(5);
            }
        } catch (Exception ex) { throw new RuntimeException(ex); }
    }
    public boolean canExecute(String benchmark, int index) {
        if (first < 0 && index >= 5 && System.nanoTime() - start >= 60_000_000_000L) {
            marker("ready", "go"); first = index; measuredStart = System.nanoTime();
        }
        if (first >= 0 && index - first >= 3 && System.nanoTime() - measuredStart >= 30_000_000_000L) {
            try { Files.writeString(dir.resolve("iterations.json"), "{\"warmup\":"+first+",\"measured\":"+(index-first)+"}"); }
            catch (Exception ex) { throw new RuntimeException(ex); }
            marker("done", "stopped"); return false;
        }
        return true;
    }
    public boolean isLast(String benchmark, int index) { return false; }
    public void onBenchmarkFailure(String benchmark) {
        try { Files.writeString(dir.resolve("failed"), benchmark); }
        catch (Exception ex) { throw new RuntimeException(ex); }
    }
    public void onMeasurementResult(String benchmark, String metric, long value) {
        try { Files.writeString(dir.resolve("validated_metrics.csv"), benchmark+","+metric+","+value+"\n", StandardOpenOption.CREATE, StandardOpenOption.APPEND); }
        catch (Exception ex) { throw new RuntimeException(ex); }
    }
}
