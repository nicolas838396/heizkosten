"""Minimaler PDF-Schreiber ohne Zusatzpakete (A4, Helvetica, Text/Linien/Flaechen).

Reicht fuer die Abrechnungsblaetter und hat keine Abhaengigkeiten, die auf dem
Raspberry Pi installiert werden muessten."""

from __future__ import annotations

_HELV = (
    "278 278 355 556 556 889 667 191 333 333 389 584 278 333 278 278 "
    "556 556 556 556 556 556 556 556 556 556 278 278 584 584 584 556 "
    "1015 667 667 722 722 667 611 778 722 278 500 667 556 833 722 778 "
    "667 778 722 667 611 722 667 944 667 667 611 278 278 278 469 556 "
    "333 556 556 500 556 556 278 556 556 222 222 500 222 833 556 556 "
    "556 556 333 500 278 556 500 722 500 500 500 334 260 334 584"
).split()
_WIDTHS = [int(x) for x in _HELV]  # Zeichen 32..126


def text_width(s: str, size: float, bold: bool = False) -> float:
    total = 0
    for ch in s:
        o = ord(ch)
        if 32 <= o <= 126:
            total += _WIDTHS[o - 32]
        else:
            total += 600 if ch.isupper() or ch == "€" else 556
    return total * size / 1000.0 * (1.06 if bold else 1.0)


def _esc(s: str) -> bytes:
    raw = s.encode("cp1252", errors="replace")
    return raw.replace(b"\\", b"\\\\").replace(b"(", b"\\(").replace(b")", b"\\)")


class Pdf:
    W, H = 595.28, 841.89

    def __init__(self, margin: float = 50):
        self.margin = margin
        self.pages: list[list[bytes]] = []
        self.ops: list[bytes] = []
        self.y = 0.0
        self.new_page()

    def new_page(self):
        self.ops = []
        self.pages.append(self.ops)
        self.y = self.H - self.margin

    def ensure(self, hoehe: float):
        if self.y - hoehe < self.margin + 20:
            self.new_page()

    def text(self, x, y, s, size=10, bold=False, align="l", gray=0.0):
        s = str(s)
        w = text_width(s, size, bold)
        if align == "r":
            x -= w
        elif align == "c":
            x -= w / 2
        font = "F2" if bold else "F1"
        self.ops.append(
            b"BT /%s %.2f Tf %.3f g %.2f %.2f Td (" % (font.encode(), size, gray, x, y) + _esc(s) + b") Tj ET"
        )

    def line(self, x1, y1, x2, y2, width=0.5, gray=0.6):
        self.ops.append(b"%.3f G %.2f w %.2f %.2f m %.2f %.2f l S" % (gray, width, x1, y1, x2, y2))

    def rect(self, x, y, w, h, fill=0.93):
        self.ops.append(b"%.3f g %.2f %.2f %.2f %.2f re f" % (fill, x, y, w, h))

    def tobytes(self) -> bytes:
        objs: list[bytes] = []

        def add(b: bytes) -> int:
            objs.append(b)
            return len(objs)

        add(b"<< /Type /Catalog /Pages 2 0 R >>")  # 1
        add(b"")  # 2 (Pages, spaeter)
        add(b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica /Encoding /WinAnsiEncoding >>")  # 3
        add(b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica-Bold /Encoding /WinAnsiEncoding >>")  # 4
        kids = []
        for ops in self.pages:
            stream = b"\n".join(ops)
            cid = add(b"<< /Length %d >>\nstream\n" % len(stream) + stream + b"\nendstream")
            pid = add(
                b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 %.2f %.2f] "
                b"/Resources << /Font << /F1 3 0 R /F2 4 0 R >> >> /Contents %d 0 R >>" % (self.W, self.H, cid)
            )
            kids.append(pid)
        objs[1] = b"<< /Type /Pages /Kids [%s] /Count %d >>" % (
            b" ".join(b"%d 0 R" % k for k in kids),
            len(kids),
        )
        out = bytearray(b"%PDF-1.4\n%\xe2\xe3\xcf\xd3\n")
        offsets = []
        for i, body in enumerate(objs, start=1):
            offsets.append(len(out))
            out += b"%d 0 obj\n" % i + body + b"\nendobj\n"
        xref = len(out)
        out += b"xref\n0 %d\n0000000000 65535 f \n" % (len(objs) + 1)
        for off in offsets:
            out += b"%010d 00000 n \n" % off
        out += b"trailer\n<< /Size %d /Root 1 0 R >>\nstartxref\n%d\n%%%%EOF\n" % (len(objs) + 1, xref)
        return bytes(out)
