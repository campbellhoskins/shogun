"""Find and catalog all mojibake in demo_v2.html."""
import re

with open("demo_v2.html", encoding="utf-8") as f:
    raw = f.read()

# Common mojibake: UTF-8 bytes interpreted as Windows-1252/Latin-1
# em-dash: \u00e2\u20ac\u201d (â€")
# en-dash: \u00e2\u20ac\u201c (â€")
# right single quote: \u00e2\u20ac\u2122 (â€™)
# left double quote: \u00e2\u20ac\u0153 (â€œ)
# right double quote: \u00e2\u20ac (â€)
# section sign as \u00c2\u00a7 (Â§)

# Method: find any sequence of chars in \u0080-\u00ff range and try to decode
# Actually let's just search for the known problematic strings
search_terms = {
    "\u00e2\u20ac\u201d": "em-dash (—)",
    "\u00e2\u20ac\u201c": "en-dash (–)",
    "\u00e2\u20ac\u2122": "right-single-quote (')",
    "\u00e2\u20ac\u0153": "left-double-quote",
    "\u00c2\u00a7": "section-sign (§)",
    "\u00c2\u00b7": "middle-dot (·)",
}

total = 0
for term, label in search_terms.items():
    c = raw.count(term)
    if c > 0:
        idx = raw.index(term)
        ctx = raw[max(0, idx-20):idx+len(term)+30].replace("\n", " ")
        print(f"{label}: {c} occurrences")
        print(f"  Sample: ...{ctx}...")
        total += c

if total == 0:
    # Try a broader search - just dump all unique chars above 0x7F
    chars = {}
    for i, ch in enumerate(raw):
        code = ord(ch)
        if 0x80 <= code <= 0xFF:
            if ch not in chars:
                ctx = raw[max(0,i-15):i+15].replace("\n"," ")
                chars[ch] = (code, ctx, 0)
            chars[ch] = (chars[ch][0], chars[ch][1], chars[ch][2] + 1)

    if chars:
        print("Non-ASCII chars in Latin-1 range (0x80-0xFF):")
        for ch, (code, ctx, count) in sorted(chars.items(), key=lambda x: -x[1][2]):
            print(f"  U+{code:04X} ({repr(ch)}): {count}x  ...{ctx}...")
    else:
        print("No Latin-1 range chars found")

    # Also check for multi-codepoint sequences that look like mojibake
    # e.g. \u00e2\u0080\u0094 is em-dash mojibake where source was UTF-8 read as bytes
    for m in re.finditer(r"\u00e2[\u0080-\u009f][\u0080-\u00bf]", raw):
        span = m.group()
        pos = m.start()
        ctx = raw[max(0,pos-15):pos+len(span)+15].replace("\n"," ")
        try:
            fixed = span.encode("latin-1").decode("utf-8")
            print(f"\nMojibake at {pos}: {repr(span)} -> {repr(fixed)}")
            print(f"  ...{ctx}...")
        except:
            pass
