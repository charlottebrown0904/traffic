/* N0726 */
(function () {
  'use strict';

  /* ── GF(256) ─────────────────────────────────────────────── */
  var EXP = new Uint8Array(512), LOG = new Uint8Array(256);
  (function () {
    var x = 1;
    for (var i = 0; i < 255; i++) {
      EXP[i] = x; LOG[x] = i;
      x <<= 1;
      if (x & 0x100) x ^= 0x11d;          // 원시다항식
    }
    for (var j = 255; j < 512; j++) EXP[j] = EXP[j - 255];
  })();
  function mul(a, b) { return (a && b) ? EXP[LOG[a] + LOG[b]] : 0; }

  /** 오류정정 부호어. 메시지를 생성다항식으로 나눈 나머지다. */
  function ecc(data, n) {
    var gen = [1];
    for (var i = 0; i < n; i++) {
      var next = new Array(gen.length + 1).fill(0);
      for (var j = 0; j < gen.length; j++) {
        next[j] ^= gen[j];
        next[j + 1] ^= mul(gen[j], EXP[i]);
      }
      gen = next;
    }
    var rem = new Array(n).fill(0);
    for (var d = 0; d < data.length; d++) {
      var factor = data[d] ^ rem[0];
      rem.shift(); rem.push(0);
      if (factor) for (var k = 0; k < n; k++) rem[k] ^= mul(gen[k + 1], factor);
    }
    return rem;
  }

  /* ── 버전별 표 (오류정정 M 만) ───────────────────────────── */
  //                     v1  v2  v3   v4   v5   v6   v7   v8   v9  v10
  var TOTAL   = [0, 26, 44, 70, 100, 134, 172, 196, 242, 292, 346];
  var ECPB    = [0, 10, 16, 26,  18,  24,  16,  18,  22,  22,  26];  // 블록당 EC 부호어
  // [그룹1 블록수, 그룹1 자료수, 그룹2 블록수, 그룹2 자료수]
  var BLOCKS  = [null,
    [1, 16, 0, 0], [1, 28, 0, 0], [1, 44, 0, 0], [2, 32, 0, 0], [2, 43, 0, 0],
    [4, 27, 0, 0], [4, 31, 0, 0], [2, 38, 2, 39], [3, 36, 2, 37], [4, 43, 1, 44]];
  var ALIGN   = [null, [], [6, 18], [6, 22], [6, 26], [6, 30], [6, 34],
                 [6, 22, 38], [6, 24, 42], [6, 26, 46], [6, 28, 50]];

  function capacity(v) { return BLOCKS[v][0] * BLOCKS[v][1] + BLOCKS[v][2] * BLOCKS[v][3]; }

  /* ── BCH — 형식·버전 정보 ────────────────────────────────── */
  function bch(v, gen, len) {
    var g = gen, d = v;
    var gbits = 0; for (var t = g; t; t >>= 1) gbits++;
    for (var i = len - 1; i >= 0; i--) {
      if (d & (1 << (i + gbits - 1))) d ^= g << i;
    }
    return d;
  }
  /** 형식 정보 15비트. 오류정정 M 은 00. */
  function formatBits(mask) {
    var v = (0 << 3) | mask;               // M = 0b00
    return (((v << 10) | bch(v << 10, 0x537, 5)) ^ 0x5412) & 0x7fff;
  }
  /** 버전 정보 18비트 (버전 7 이상만 쓴다). */
  function versionBits(ver) {
    return ((ver << 12) | bch(ver << 12, 0x1f25, 6)) & 0x3ffff;
  }

  /* ── 자료 비트열 ─────────────────────────────────────────── */
  function bitstream(bytes, ver) {
    var bits = [];
    function put(val, n) { for (var i = n - 1; i >= 0; i--) bits.push((val >> i) & 1); }
    put(0x4, 4);                                   // 바이트 모드
    put(bytes.length, ver < 10 ? 8 : 16);          // 길이 (버전 1~9 는 8비트)
    for (var i = 0; i < bytes.length; i++) put(bytes[i], 8);

    var cap = capacity(ver) * 8;
    for (var t = 0; t < 4 && bits.length < cap; t++) bits.push(0);   // 종료자
    while (bits.length % 8) bits.push(0);                            // 바이트 맞춤

    var out = [];
    for (var b = 0; b < bits.length; b += 8) {
      var byte = 0;
      for (var k = 0; k < 8; k++) byte = (byte << 1) | bits[b + k];
      out.push(byte);
    }
    var PAD = [0xec, 0x11];
    for (var pi = 0; out.length < capacity(ver); pi++) out.push(PAD[pi % 2]);
    return out;
  }

  /** 블록으로 나눠 자료·EC 를 번갈아 엮는다. */
  function interleave(data, ver) {
    var g1n = BLOCKS[ver][0], g1c = BLOCKS[ver][1];
    var g2n = BLOCKS[ver][2], g2c = BLOCKS[ver][3];
    var ecn = ECPB[ver];
    var dBlocks = [], eBlocks = [], at = 0, i;
    for (i = 0; i < g1n; i++) { dBlocks.push(data.slice(at, at + g1c)); at += g1c; }
    for (i = 0; i < g2n; i++) { dBlocks.push(data.slice(at, at + g2c)); at += g2c; }
    dBlocks.forEach(function (b) { eBlocks.push(ecc(b, ecn)); });

    var out = [], maxD = Math.max(g1c, g2c || 0);
    for (i = 0; i < maxD; i++) {
      for (var b = 0; b < dBlocks.length; b++) if (i < dBlocks[b].length) out.push(dBlocks[b][i]);
    }
    for (i = 0; i < ecn; i++) {
      for (var e = 0; e < eBlocks.length; e++) out.push(eBlocks[e][i]);
    }
    return out;
  }

  /* ── 바탕 무늬 ───────────────────────────────────────────── */
  function newMatrix(size) {
    var m = [], r = [];
    for (var i = 0; i < size; i++) {
      m.push(new Int8Array(size).fill(-1));      // -1 = 아직 비었음
      r.push(new Uint8Array(size));              // 1 = 자료를 못 놓는 자리
    }
    return { m: m, r: r, size: size };
  }
  function finder(g, row, col) {
    for (var i = -1; i <= 7; i++) {
      for (var j = -1; j <= 7; j++) {
        var y = row + i, x = col + j;
        if (y < 0 || x < 0 || y >= g.size || x >= g.size) continue;
        var on = (i >= 0 && i <= 6 && (j === 0 || j === 6))
              || (j >= 0 && j <= 6 && (i === 0 || i === 6))
              || (i >= 2 && i <= 4 && j >= 2 && j <= 4);
        g.m[y][x] = on ? 1 : 0;
        g.r[y][x] = 1;
      }
    }
  }
  function base(ver) {
    var size = ver * 4 + 17, g = newMatrix(size), i, j;
    finder(g, 0, 0); finder(g, 0, size - 7); finder(g, size - 7, 0);

    // 정렬 무늬 — 탐지 무늬와 겹치는 자리는 뺀다
    var ac = ALIGN[ver];
    for (i = 0; i < ac.length; i++) {
      for (j = 0; j < ac.length; j++) {
        var cy = ac[i], cx = ac[j];
        if ((cy <= 8 && cx <= 8) || (cy <= 8 && cx >= size - 9) || (cy >= size - 9 && cx <= 8)) continue;
        for (var dy = -2; dy <= 2; dy++) {
          for (var dx = -2; dx <= 2; dx++) {
            g.m[cy + dy][cx + dx] =
              (Math.max(Math.abs(dy), Math.abs(dx)) !== 1) ? 1 : 0;
            g.r[cy + dy][cx + dx] = 1;
          }
        }
      }
    }
    // 타이밍
    for (i = 8; i < size - 8; i++) {
      g.m[6][i] = g.m[i][6] = (i % 2 === 0) ? 1 : 0;
      g.r[6][i] = g.r[i][6] = 1;
    }
    // 어두운 모듈 + 형식 정보 자리 예약
    g.m[size - 8][8] = 1; g.r[size - 8][8] = 1;
    for (i = 0; i <= 8; i++) { g.r[8][i] = 1; g.r[i][8] = 1; }
    for (i = 0; i < 8; i++) { g.r[8][size - 1 - i] = 1; g.r[size - 1 - i][8] = 1; }
    if (ver >= 7) {
      for (i = 0; i < 6; i++) for (j = 0; j < 3; j++) {
        g.r[i][size - 11 + j] = 1; g.r[size - 11 + j][i] = 1;
      }
    }
    return g;
  }

  /** 오른쪽 아래에서 두 칸씩 지그재그로 올라가며 놓는다. 6열은 건너뛴다. */
  function place(g, bytes) {
    var size = g.size, bit = 0, up = true;
    for (var col = size - 1; col > 0; col -= 2) {
      if (col === 6) col--;
      for (var t = 0; t < size; t++) {
        var row = up ? size - 1 - t : t;
        for (var c = 0; c < 2; c++) {
          var x = col - c;
          if (g.r[row][x]) continue;
          var b = 0;
          if (bit < bytes.length * 8) b = (bytes[bit >> 3] >> (7 - (bit & 7))) & 1;
          g.m[row][x] = b; bit++;
        }
      }
      up = !up;
    }
  }

  function maskFn(n, r, c) {
    switch (n) {
      case 0: return (r + c) % 2 === 0;
      case 1: return r % 2 === 0;
      case 2: return c % 3 === 0;
      case 3: return (r + c) % 3 === 0;
      case 4: return (Math.floor(r / 2) + Math.floor(c / 3)) % 2 === 0;
      case 5: return ((r * c) % 2) + ((r * c) % 3) === 0;
      case 6: return (((r * c) % 2) + ((r * c) % 3)) % 2 === 0;
      default: return (((r + c) % 2) + ((r * c) % 3)) % 2 === 0;
    }
  }

  function penalty(m, size) {
    var p = 0, r, c, i, run, dark = 0;
    // 규칙1 — 같은 색 다섯 이상
    for (r = 0; r < size; r++) {
      run = 1;
      for (c = 1; c < size; c++) {
        if (m[r][c] === m[r][c - 1]) { run++; if (run === 5) p += 3; else if (run > 5) p++; }
        else run = 1;
      }
    }
    for (c = 0; c < size; c++) {
      run = 1;
      for (r = 1; r < size; r++) {
        if (m[r][c] === m[r - 1][c]) { run++; if (run === 5) p += 3; else if (run > 5) p++; }
        else run = 1;
      }
    }
    // 규칙2 — 2×2 같은 색
    for (r = 0; r < size - 1; r++) for (c = 0; c < size - 1; c++) {
      var v = m[r][c];
      if (v === m[r][c + 1] && v === m[r + 1][c] && v === m[r + 1][c + 1]) p += 3;
    }
    // 규칙3 — 1:1:3:1:1 무늬
    var PAT = [1, 0, 1, 1, 1, 0, 1, 0, 0, 0, 0];
    var REV = PAT.slice().reverse();
    function look(get, n) {
      for (var s = 0; s + 11 <= n; s++) {
        var okA = true, okB = true;
        for (i = 0; i < 11; i++) {
          if (get(s + i) !== PAT[i]) okA = false;
          if (get(s + i) !== REV[i]) okB = false;
        }
        if (okA || okB) p += 40;
      }
    }
    for (r = 0; r < size; r++) look(function (i2) { return m[r][i2]; }, size);
    for (c = 0; c < size; c++) look(function (i2) { return m[i2][c]; }, size);
    // 규칙4 — 어두운 비율
    for (r = 0; r < size; r++) for (c = 0; c < size; c++) if (m[r][c]) dark++;
    var pct = (dark * 100) / (size * size);
    p += Math.floor(Math.abs(pct - 50) / 5) * 10;
    return p;
  }

  function applyFormat(g, mask) {
    var size = g.size, bits = formatBits(mask), i;
    /* N0727 */
    var b = function (k) { return (bits >> (14 - k)) & 1; };

    // 첫째 사본 — 왼쪽 위 탐지 무늬를 감싼다
    for (i = 0; i <= 5; i++) g.m[8][i] = b(i);
    g.m[8][7] = b(6);
    g.m[8][8] = b(7);
    g.m[7][8] = b(8);
    for (i = 9; i <= 14; i++) g.m[14 - i][8] = b(i);

    /* N0728 */
    for (i = 0; i <= 6; i++) g.m[size - 1 - i][8] = b(i);
    g.m[8][size - 8] = b(7);
    for (i = 8; i <= 14; i++) g.m[8][size - 15 + i] = b(i);
    g.m[size - 8][8] = 1;
  }
  function applyVersion(g, ver) {
    if (ver < 7) return;
    var size = g.size, bits = versionBits(ver);
    for (var i = 0; i < 18; i++) {
      var b = (bits >> i) & 1, r = Math.floor(i / 3), c = i % 3;
      g.m[r][size - 11 + c] = b;
      g.m[size - 11 + c][r] = b;
    }
  }

  /** 글자 → 모듈 배열(0/1). 안 되면 null. */
  function encode(text) {
    var bytes = [];
    var enc = unescape(encodeURIComponent(String(text == null ? '' : text)));
    for (var i = 0; i < enc.length; i++) bytes.push(enc.charCodeAt(i) & 0xff);

    var ver = 0;
    for (var v = 1; v <= 10; v++) {
      var head = 4 + (v < 10 ? 8 : 16);
      if (head + bytes.length * 8 <= capacity(v) * 8) { ver = v; break; }
    }
    if (!ver) return null;   // 버전 10 을 넘는 글은 안 받는다 (우리 링크는 그럴 일이 없다)

    var codes = interleave(bitstream(bytes, ver), ver);
    var best = null;
    for (var mask = 0; mask < 8; mask++) {
      var g = base(ver);
      place(g, codes);
      for (var r = 0; r < g.size; r++) for (var c = 0; c < g.size; c++) {
        if (!g.r[r][c] && maskFn(mask, r, c)) g.m[r][c] ^= 1;
      }
      applyVersion(g, ver);
      applyFormat(g, mask);
      var sc = penalty(g.m, g.size);
      if (!best || sc < best.score) best = { score: sc, g: g, mask: mask, ver: ver };
    }
    return { size: best.g.size, version: best.ver, mask: best.mask,
             modules: best.g.m.map(function (row) { return Array.prototype.slice.call(row); }) };
  }

  /** 화면·인쇄용 SVG. 조용한 테두리 4모듈은 규격이 요구한다 — 없으면 못 읽는다. */
  function svg(text, opt) {
    var o = opt || {};
    var r = encode(text);
    if (!r) return null;
    var quiet = o.quiet == null ? 4 : o.quiet;
    var n = r.size + quiet * 2, d = [];
    for (var y = 0; y < r.size; y++) {
      for (var x = 0; x < r.size; x++) {
        if (r.modules[y][x]) d.push('M' + (x + quiet) + ' ' + (y + quiet) + 'h1v1h-1z');
      }
    }
    return '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 ' + n + ' ' + n + '"'
      + ' width="' + (o.px || 160) + '" height="' + (o.px || 160) + '"'
      + ' shape-rendering="crispEdges" role="img" aria-label="QR 코드">'
      + '<rect width="' + n + '" height="' + n + '" fill="' + (o.bg || '#fff') + '"/>'
      + '<path fill="' + (o.fg || '#000') + '" d="' + d.join('') + '"/></svg>';
  }

  var API = { encode: encode, svg: svg };
  // 검사가 속을 들여다볼 수 있게. 화면 코드는 쓰지 않는다.
  API.__parts = { bitstream: bitstream, interleave: interleave, base: base,
                  capacity: capacity, ecc: ecc, maskFn: maskFn };
  if (typeof window !== 'undefined') window.QR = API;
  // 검사는 node 에서 돈다 — 브라우저 전용으로 짜면 확인할 방법이 없어진다.
  if (typeof module !== 'undefined' && module.exports) module.exports = API;
})();
