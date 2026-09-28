/** 조사 고르기 — 끼워 넣는 값(리비전 번호·이름)의 받침에 따라 「으로/로」·「이/가」·「을/를」·「은/는」·「과/와」.

`리비전 ${n}로`처럼 조사를 글에 박으면 n이 3·6·10일 때 「리비전 3로」가 된다(쇼케이스 진행 카드에서 드러남).
숫자는 **읽는 소리**의 받침이다 — 끝자리(0이면 자릿값: 십·백·천·만·억·조), 소수는 끝자리를 한 자씩(영·일…).
ㄹ 받침은 「로」를 받는다(「레일로」·「1로」). 끝 글자를 읽을 수 없으면(영문·기호) 병기 「(으)로」로 둔다 —
틀린 조사를 단정하는 것보다 낫다.
*/

// [받침 쪽, 받침 없는 쪽] — ㄹ 받침은 「으로/로」에서만 받침 없는 쪽을 받는다
const PAIRS = [["으로", "로"], ["이", "가"], ["을", "를"], ["은", "는"], ["과", "와"]];

// 한 자리 수의 읽는 소리 받침 — 영(ㅇ)·일(ㄹ)·이·삼(ㅁ)·사·오·육(ㄱ)·칠(ㄹ)·팔(ㄹ)·구
const DIGIT = [ "other", "ㄹ", null, "other", null, null, "other", "ㄹ", "ㄹ", null ];
// 끝의 0 개수 → 자릿값의 받침 — 십(ㅂ)·백(ㄱ)·천(ㄴ)·만(ㄴ)… 억(ㄱ)… 조(모음)
const place = (zeros) => (zeros >= 12 ? null : "other");

/** 끝소리 받침 — null(받침 없음) · "ㄹ" · "other"(ㄹ 아닌 받침) · undefined(읽을 수 없음). */
export function finalConsonant(word) {
  const s = String(word ?? "");
  if (!s) return undefined;
  const digits = s.replace(/^[−-]/, ""); // 부호는 읽는 소리의 끝과 무관
  if (/^\d+$/.test(digits)) {
    const last = digits.search(/0*$/);
    const zeros = digits.length - last;
    if (zeros === 0) return DIGIT[Number(digits.at(-1))];
    if (zeros === digits.length) return DIGIT[0]; // 0 자체 — 영
    return place(zeros);
  }
  const ch = s.at(-1);
  if (/\d/.test(ch)) return DIGIT[Number(ch)]; // 소수 — 끝자리를 한 자씩
  const code = ch.codePointAt(0) - 0xac00;
  if (code < 0 || code > 11171) return undefined;
  const jong = code % 28;
  if (jong === 0) return null;
  return jong === 8 ? "ㄹ" : "other";
}

/** word 뒤에 붙일 조사만 — pair는 "으로/로"처럼 두 꼴(순서 무관). 모르는 짝이면 던진다.
 *  괄호 덧붙임(「확정본 (r1)을」)처럼 조사가 **다른 낱말 뒤에** 붙는 자리에서 앞 낱말로 고를 때 쓴다. */
export function josaOf(word, pair) {
  const [a, b] = String(pair).split("/");
  const p = PAIRS.find(([x, y]) => (x === a && y === b) || (x === b && y === a));
  if (!p) throw new Error(`조사 짝을 모른다: ${pair}`);
  const [withBatchim, without] = p;
  const fc = finalConsonant(word == null ? "" : word);
  if (fc === undefined) {
    // 병기 — 「(으)로」·「이(가)」: 받침 쪽이 길면 앞에 괄호, 아니면 뒤에
    return withBatchim.endsWith(without) ? `(${withBatchim.slice(0, -without.length)})${without}`
      : `${withBatchim}(${without})`;
  }
  if (fc === null) return without;
  if (fc === "ㄹ" && withBatchim === "으로") return without;
  return withBatchim;
}

/** word + 알맞은 조사 (josaOf). word가 없으면 「—」에 병기 조사. */
export function withJosa(word, pair) {
  return `${word == null ? "—" : String(word)}${josaOf(word, pair)}`;
}
