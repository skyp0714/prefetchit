public class JCS {
  public static void main(String[] args) {
    int iters = args.length > 0 ? Integer.parseInt(args[0]) : 30;
    int inner = args.length > 1 ? Integer.parseInt(args[1]) : 40;
    long s = 1;
    for (int it = 0; it < iters; it++) {
      long t0 = System.nanoTime();
      for (int r = 0; r < inner; r++) {
        s = Mid.d0(s);
        s = Mid.d1(s);
        s = Mid.d2(s);
        s = Mid.d3(s);
        s = Mid.d4(s);
        s = Mid.d5(s);
        s = Mid.d6(s);
        s = Mid.d7(s);
        s = Mid.d8(s);
        s = Mid.d9(s);
        s = Mid.d10(s);
        s = Mid.d11(s);
        s = Mid.d12(s);
        s = Mid.d13(s);
        s = Mid.d14(s);
        s = Mid.d15(s);
        s = Mid.d16(s);
        s = Mid.d17(s);
        s = Mid.d18(s);
        s = Mid.d19(s);
        s = Mid.d20(s);
        s = Mid.d21(s);
        s = Mid.d22(s);
        s = Mid.d23(s);
        s = Mid.d24(s);
        s = Mid.d25(s);
        s = Mid.d26(s);
        s = Mid.d27(s);
        s = Mid.d28(s);
        s = Mid.d29(s);
      }
      long t1 = System.nanoTime();
      System.out.println("iter " + it + " ms " + (t1 - t0) / 1000000);
    }
    System.out.println("sum " + s);
  }
}