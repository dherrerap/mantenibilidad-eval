// pyrandom.mjs — Python's random.Random, as far as the evaluator uses it: seeding with a str (version 2: the str plus its SHA-512
// as one big integer, fed to MT19937's init_by_array) and shuffle() (Fisher–Yates with _randbelow over getrandbits). The same seed
// gives the same order as CPython, so the judge picks the same audit sample.
import { createHash } from "node:crypto";

const N = 624, M = 397;

export class PyRandom {
  constructor(seed) {
    this.mt = new Uint32Array(N);
    this.mti = N + 1;
    const bytes = Buffer.from(String(seed), "utf8");
    const all = Buffer.concat([bytes, createHash("sha512").update(bytes).digest()]);
    let n = BigInt("0x" + (all.toString("hex") || "0"));
    const key = [];
    while (n > 0n) { key.push(Number(n & 0xffffffffn)); n >>= 32n; }  // 32-bit words, least significant first
    this.initByArray(key.length ? key : [0]);
  }

  initGenrand(s) {
    const mt = this.mt;
    mt[0] = s >>> 0;
    for (let i = 1; i < N; i++) mt[i] = (Math.imul(1812433253, mt[i - 1] ^ (mt[i - 1] >>> 30)) + i) >>> 0;
    this.mti = N;
  }

  initByArray(key) {
    const mt = this.mt;
    this.initGenrand(19650218);
    let i = 1, j = 0;
    for (let k = Math.max(N, key.length); k; k--) {
      mt[i] = ((mt[i] ^ Math.imul(mt[i - 1] ^ (mt[i - 1] >>> 30), 1664525)) + key[j] + j) >>> 0;
      i++; j++;
      if (i >= N) { mt[0] = mt[N - 1]; i = 1; }
      if (j >= key.length) j = 0;
    }
    for (let k = N - 1; k; k--) {
      mt[i] = ((mt[i] ^ Math.imul(mt[i - 1] ^ (mt[i - 1] >>> 30), 1566083941)) - i) >>> 0;
      i++;
      if (i >= N) { mt[0] = mt[N - 1]; i = 1; }
    }
    mt[0] = 0x80000000;
  }

  uint32() {
    const mt = this.mt;
    if (this.mti >= N) {
      let k = 0, y;
      for (; k < N - M; k++) { y = (mt[k] & 0x80000000) | (mt[k + 1] & 0x7fffffff); mt[k] = mt[k + M] ^ (y >>> 1) ^ (y & 1 ? 0x9908b0df : 0); }
      for (; k < N - 1; k++) { y = (mt[k] & 0x80000000) | (mt[k + 1] & 0x7fffffff); mt[k] = mt[k + (M - N)] ^ (y >>> 1) ^ (y & 1 ? 0x9908b0df : 0); }
      y = (mt[N - 1] & 0x80000000) | (mt[0] & 0x7fffffff);
      mt[N - 1] = mt[M - 1] ^ (y >>> 1) ^ (y & 1 ? 0x9908b0df : 0);
      this.mti = 0;
    }
    let y = mt[this.mti++];
    y ^= y >>> 11;
    y ^= (y << 7) & 0x9d2c5680;
    y ^= (y << 15) & 0xefc60000;
    y ^= y >>> 18;
    return y >>> 0;
  }

  /** getrandbits(k) for 0 < k <= 32. */
  getrandbits(k) {
    return this.uint32() >>> (32 - k);
  }

  /** _randbelow_with_getrandbits(n): a random int in [0, n). */
  randbelow(n) {
    const k = n.toString(2).length;  // n.bit_length()
    let r = this.getrandbits(k);
    while (r >= n) r = this.getrandbits(k);
    return r;
  }

  /** random.shuffle(x), in place. */
  shuffle(x) {
    for (let i = x.length - 1; i > 0; i--) {
      const j = this.randbelow(i + 1);
      [x[i], x[j]] = [x[j], x[i]];
    }
    return x;
  }
}
