public class FGSmoke {
    interface Handler { long run(); }
    static class H implements Handler { final long n; H(long n) { this.n=n; } public long run() { return n; } }
    static class K implements Handler { final long n; K(long n) { this.n=n; } public long run() { return n*3; } }
    final Handler handler;
    FGSmoke(Handler h) { handler=h; }
    static long staticTarget(long x) {
        for(int j=0;j<10;j++) { x = (x*31)^17; x=(x>>>1)^(x<<2); }
        return x;
    }
    static long dispatch(Handler h, long x) {
        for(int i=0;i<12;i++) x=x*13+3;
        return h == null ? x : x+h.run();
    }
    long dispatchField(long x) {
        for(int i=0;i<12;i++) x=x*13+3;
        return handler == null ? x : x+handler.run();
    }
    static long dispatchReassigned(Handler h, Handler other, long x) {
        for(int i=0;i<12;i++) x=x*13+3;
        h=other;
        return h == null ? x : x+h.run();
    }
    static long graph(long x) {
        for(int i=0;i<12;i++) x=x*13+3;
        return staticTarget(x);
    }
    public static void main(String[] args) {
        Handler[] hs = {new H(7),new K(11),null};
        FGSmoke[] fs = {new FGSmoke(hs[0]),new FGSmoke(hs[1]),new FGSmoke(null)};
        long sum=0;
        for(int r=0;r<500000;r++) {
            int i=r%3;
            long a=dispatch(hs[i],r), b=fs[i].dispatchField(r);
            long c=dispatchReassigned(hs[(i+1)%3],hs[i],r);
            if(a!=b || a!=c) throw new AssertionError("receiver semantics");
            sum+=a+graph(r);
            if(r%100000==0) System.gc();
        }
        System.out.println("CHECKSUM="+sum);
    }
}
