#ifndef DUMMY_FUNCTIONS_H
#define DUMMY_FUNCTIONS_H

// Dummy functions with actual instructions (no complex control flow)
static inline int dummy_4_instructions(int x) {
    x += 42;      // add
    x ^= 0x5A;    // xor
    x *= 3;       // mul
    return x;     // ret
}

static inline int dummy_8_instructions(int x) {
    x += 42;      // 1
    x ^= 0x5A;    // 2
    x *= 3;       // 3
    x -= 17;      // 4
    x |= 0x0F;    // 5
    x <<= 2;      // 6
    x &= 0xFF;    // 7
    return x;     // 8
}

static inline int dummy_16_instructions(int x) {
    x += 42;      // 1
    x ^= 0x5A;    // 2
    x *= 3;       // 3
    x -= 17;      // 4
    x |= 0x0F;    // 5
    x <<= 2;      // 6
    x &= 0xFF;    // 7
    x += 100;     // 8
    x ^= 0xAA;    // 9
    x *= 5;       // 10
    x -= 33;      // 11
    x |= 0xF0;    // 12
    x >>= 1;      // 13
    x &= 0x7F;    // 14
    x += 7;       // 15
    return x;     // 16
}

static inline int dummy_32_instructions(int x) {
    x += 42; x ^= 0x5A; x *= 3; x -= 17;           // 1-4
    x |= 0x0F; x <<= 2; x &= 0xFF; x += 100;       // 5-8
    x ^= 0xAA; x *= 5; x -= 33; x |= 0xF0;         // 9-12
    x >>= 1; x &= 0x7F; x += 7; x ^= 0x33;         // 13-16
    x *= 2; x -= 11; x |= 0x08; x <<= 1;           // 17-20
    x &= 0x1FF; x += 55; x ^= 0x99; x *= 7;        // 21-24
    x -= 22; x |= 0x04; x >>= 2; x &= 0x3F;        // 25-28
    x += 13; x ^= 0x77; x *= 4; return x;          // 29-32
}

static inline int dummy_64_instructions(int x) {
    // Block 1 (1-16)
    x += 42; x ^= 0x5A; x *= 3; x -= 17;
    x |= 0x0F; x <<= 2; x &= 0xFF; x += 100;
    x ^= 0xAA; x *= 5; x -= 33; x |= 0xF0;
    x >>= 1; x &= 0x7F; x += 7; x ^= 0x33;

    // Block 2 (17-32)
    x *= 2; x -= 11; x |= 0x08; x <<= 1;
    x &= 0x1FF; x += 55; x ^= 0x99; x *= 7;
    x -= 22; x |= 0x04; x >>= 2; x &= 0x3F;
    x += 13; x ^= 0x77; x *= 4; x -= 44;

    // Block 3 (33-48)
    x |= 0x02; x <<= 3; x &= 0x7FF; x += 88;
    x ^= 0xBB; x *= 6; x -= 66; x |= 0x01;
    x >>= 3; x &= 0x1F; x += 25; x ^= 0xCC;
    x *= 8; x -= 99; x |= 0x80; x <<= 1;

    // Block 4 (49-64)
    x &= 0x3FF; x += 77; x ^= 0xDD; x *= 9;
    x -= 111; x |= 0x40; x >>= 4; x &= 0x0F;
    x += 39; x ^= 0xEE; x *= 11; x -= 123;
    x |= 0x20; x <<= 2; x &= 0xFF; return x;
}

static inline int dummy_128_instructions(int x) {
    // Blocks 1-4 (1-64) - same as dummy_64_instructions
    x += 42; x ^= 0x5A; x *= 3; x -= 17;
    x |= 0x0F; x <<= 2; x &= 0xFF; x += 100;
    x ^= 0xAA; x *= 5; x -= 33; x |= 0xF0;
    x >>= 1; x &= 0x7F; x += 7; x ^= 0x33;
    x *= 2; x -= 11; x |= 0x08; x <<= 1;
    x &= 0x1FF; x += 55; x ^= 0x99; x *= 7;
    x -= 22; x |= 0x04; x >>= 2; x &= 0x3F;
    x += 13; x ^= 0x77; x *= 4; x -= 44;
    x |= 0x02; x <<= 3; x &= 0x7FF; x += 88;
    x ^= 0xBB; x *= 6; x -= 66; x |= 0x01;
    x >>= 3; x &= 0x1F; x += 25; x ^= 0xCC;
    x *= 8; x -= 99; x |= 0x80; x <<= 1;
    x &= 0x3FF; x += 77; x ^= 0xDD; x *= 9;
    x -= 111; x |= 0x40; x >>= 4; x &= 0x0F;
    x += 39; x ^= 0xEE; x *= 11; x -= 123;
    x |= 0x20; x <<= 2; x &= 0xFF; x += 200;

    // Blocks 5-8 (65-128)
    x ^= 0x11; x *= 12; x -= 200; x |= 0x10;
    x <<= 1; x &= 0x7FF; x += 150; x ^= 0x22;
    x *= 13; x -= 175; x |= 0x08; x >>= 1;
    x &= 0x3FF; x += 125; x ^= 0x44; x *= 14;
    x -= 225; x |= 0x04; x <<= 2; x &= 0x1FF;
    x += 175; x ^= 0x88; x *= 15; x -= 250;
    x |= 0x02; x >>= 2; x &= 0xFF; x += 225;
    x ^= 0x55; x *= 16; x -= 300; x |= 0x01;
    x <<= 3; x &= 0x7FF; x += 275; x ^= 0x66;
    x *= 17; x -= 350; x |= 0x80; x >>= 3;
    x &= 0x3FF; x += 325; x ^= 0x99; x *= 18;
    x -= 400; x |= 0x40; x <<= 1; x &= 0x1FF;
    x += 375; x ^= 0xAA; x *= 19; x -= 450;
    x |= 0x20; x >>= 1; x &= 0xFF; x += 425;
    x ^= 0xBB; x *= 20; x -= 500; x |= 0x10;
    x <<= 2; x &= 0x7FF; x += 475; return x;
}

static inline int dummy_256_instructions(int x) {
    // First 128 instructions (same as dummy_128_instructions)
    x += 42; x ^= 0x5A; x *= 3; x -= 17;
    x |= 0x0F; x <<= 2; x &= 0xFF; x += 100;
    x ^= 0xAA; x *= 5; x -= 33; x |= 0xF0;
    x >>= 1; x &= 0x7F; x += 7; x ^= 0x33;
    x *= 2; x -= 11; x |= 0x08; x <<= 1;
    x &= 0x1FF; x += 55; x ^= 0x99; x *= 7;
    x -= 22; x |= 0x04; x >>= 2; x &= 0x3F;
    x += 13; x ^= 0x77; x *= 4; x -= 44;
    x |= 0x02; x <<= 3; x &= 0x7FF; x += 88;
    x ^= 0xBB; x *= 6; x -= 66; x |= 0x01;
    x >>= 3; x &= 0x1F; x += 25; x ^= 0xCC;
    x *= 8; x -= 99; x |= 0x80; x <<= 1;
    x &= 0x3FF; x += 77; x ^= 0xDD; x *= 9;
    x -= 111; x |= 0x40; x >>= 4; x &= 0x0F;
    x += 39; x ^= 0xEE; x *= 11; x -= 123;
    x |= 0x20; x <<= 2; x &= 0xFF; x += 200;
    x ^= 0x11; x *= 12; x -= 200; x |= 0x10;
    x <<= 1; x &= 0x7FF; x += 150; x ^= 0x22;
    x *= 13; x -= 175; x |= 0x08; x >>= 1;
    x &= 0x3FF; x += 125; x ^= 0x44; x *= 14;
    x -= 225; x |= 0x04; x <<= 2; x &= 0x1FF;
    x += 175; x ^= 0x88; x *= 15; x -= 250;
    x |= 0x02; x >>= 2; x &= 0xFF; x += 225;
    x ^= 0x55; x *= 16; x -= 300; x |= 0x01;
    x <<= 3; x &= 0x7FF; x += 275; x ^= 0x66;
    x *= 17; x -= 350; x |= 0x80; x >>= 3;
    x &= 0x3FF; x += 325; x ^= 0x99; x *= 18;
    x -= 400; x |= 0x40; x <<= 1; x &= 0x1FF;
    x += 375; x ^= 0xAA; x *= 19; x -= 450;
    x |= 0x20; x >>= 1; x &= 0xFF; x += 425;
    x ^= 0xBB; x *= 20; x -= 500; x |= 0x10;
    x <<= 2; x &= 0x7FF; x += 475; x ^= 0xCC;

    // Second 128 instructions (129-256)
    x *= 21; x -= 550; x |= 0x08; x >>= 2;
    x &= 0x3FF; x += 525; x ^= 0xDD; x *= 22;
    x -= 600; x |= 0x04; x <<= 3; x &= 0x1FF;
    x += 575; x ^= 0xEE; x *= 23; x -= 650;
    x |= 0x02; x >>= 3; x &= 0xFF; x += 625;
    x ^= 0x77; x *= 24; x -= 700; x |= 0x01;
    x <<= 1; x &= 0x7FF; x += 675; x ^= 0x88;
    x *= 25; x -= 750; x |= 0x80; x >>= 1;
    x &= 0x3FF; x += 725; x ^= 0x99; x *= 26;
    x -= 800; x |= 0x40; x <<= 2; x &= 0x1FF;
    x += 775; x ^= 0x11; x *= 27; x -= 850;
    x |= 0x20; x >>= 2; x &= 0xFF; x += 825;
    x ^= 0x22; x *= 28; x -= 900; x |= 0x10;
    x <<= 3; x &= 0x7FF; x += 875; x ^= 0x33;
    x *= 29; x -= 950; x |= 0x08; x >>= 3;
    x &= 0x3FF; x += 925; x ^= 0x44; x *= 30;
    x -= 1000; x |= 0x04; x <<= 1; x &= 0x1FF;
    x += 975; x ^= 0x55; x *= 31; x -= 1050;
    x |= 0x02; x >>= 1; x &= 0xFF; x += 1025;
    x ^= 0x66; x *= 32; x -= 1100; x |= 0x01;
    x <<= 2; x &= 0x7FF; x += 1075; x ^= 0x77;
    x *= 33; x -= 1150; x |= 0x80; x >>= 2;
    x &= 0x3FF; x += 1125; x ^= 0x88; x *= 34;
    x -= 1200; x |= 0x40; x <<= 3; x &= 0x1FF;
    x += 1175; x ^= 0x99; x *= 35; x -= 1250;
    x |= 0x20; x >>= 3; x &= 0xFF; x += 1225;
    x ^= 0xAA; x *= 36; x -= 1300; x |= 0x10;
    x <<= 1; x &= 0x7FF; x += 1275; x ^= 0xBB;
    x *= 37; x -= 1350; x |= 0x08; x >>= 1;
    x &= 0x3FF; x += 1325; x ^= 0xCC; x *= 38;
    x -= 1400; x |= 0x04; x <<= 2; x &= 0x1FF;
    x += 1375; x ^= 0xDD; x *= 39; return x;
}

// Complex control flow function for realistic instruction cache behavior
static inline int complex_function(int input) {
    int result = input;

    // Multiple nested branches
    if (result > 100) {
        for (int i = 0; i < 10; i++) {
            if (i % 2 == 0) {
                result += i * 3;
                if (result > 200) {
                    result -= 50;
                    switch (result % 4) {
                        case 0: result *= 2; break;
                        case 1: result += 7; break;
                        case 2: result -= 3; break;
                        default: result /= 2; break;
                    }
                }
            } else {
                result *= 2;
                if (result < 500) {
                    result += 25;
                } else {
                    result -= 75;
                }
            }
        }
    } else if (result > 50) {
        // Another branch with different control flow
        int temp = result;
        while (temp > 0) {
            temp -= 7;
            result += temp % 3;
            if (temp % 5 == 0) {
                result ^= 0x55;
            }
        }

        // Nested loops with conditions
        for (int j = 0; j < 5; j++) {
            for (int k = 0; k < 3; k++) {
                if ((j + k) % 2) {
                    result += j * k;
                } else {
                    result -= j + k;
                }
            }
        }
    } else {
        // Third major branch
        result *= 3;
        if (result & 1) {
            result <<= 2;
            result += 0xAA;
        } else {
            result >>= 1;
            result ^= 0x33;
        }

        // Function calls within branches would need external functions
        result += (result % 10) + 1;  // Simulated function call
        result += (result % 20) + 1;  // Simulated function call
    }

    // Final complex computation
    if (result % 2) {
        result = (result * 17) % 1000;
    } else {
        result = (result * 23) % 1000;
    }

    return result;
}

#endif // DUMMY_FUNCTIONS_H