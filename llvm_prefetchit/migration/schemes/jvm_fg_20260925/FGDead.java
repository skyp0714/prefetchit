public class FGDead {
 static final boolean NEVER=Boolean.parseBoolean("false");
 static long staticTarget(long x) { for(int i=0;i<10;i++) x=x*17+33; return x; }
 static long graph(long x) { for(int i=0;i<12;i++) x=x*13+3; if(NEVER)x=staticTarget(x); return x; }
 public static void main(String[] args) { long x=0; for(int i=0;i<500000;i++)x+=graph(i); System.out.println(x); }
}
