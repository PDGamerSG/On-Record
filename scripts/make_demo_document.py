"""Write a 12-page demo PDF: Kitepost's self-serve pricing policy, as drafted after the pricing review.

    uv run --project apps/api python scripts/make_demo_document.py [out.pdf]

The policy states the Starter terms agreed in the "Self-serve pricing review" demo meeting (4,999 rupees,
1,500 shipments). The later "Self-serve launch sync" meeting changed Starter to 3,999 rupees with 1,000
shipments, so asking about Starter with meetings included shows Gemma 4 finding the conflict. Twelve
pages means the document splitter sends it to Sarvam Document AI as two parts (pages 1-10 and 11-12).
The PDF uses the built-in Helvetica font and needs no extra packages.
"""

from __future__ import annotations

import sys
import textwrap
from pathlib import Path

DEFAULT_OUT = Path(__file__).resolve().parents[1] / "data" / "kitepost-pricing-policy.pdf"

PAGES: list[tuple[str, list[str]]] = [
    ("Kitepost Self-Serve Pricing Policy", [
        "Version 1.0, approved after the self-serve pricing review. Owner: Priya (Product).",
        "This policy sets the self-serve plans, included shipments, overage, billing terms and the launch "
        "plan for Kitepost shipment tracking. Sales, billing and support must quote these terms.",
        "Contents: 1 Plans. 2 Starter. 3 Growth. 4 Enterprise. 5 Overage. 6 Annual billing. 7 Usage meter. "
        "8 Taxes. 9 Refunds. 10 Support. 11 Launch plan. 12 Worked examples.",
    ]),
    ("1. Plans at a glance", [
        "Kitepost offers three plans. Starter and Growth are self-serve and billed monthly or annually. "
        "Enterprise is sales-led and priced per contract.",
        "Starter: Rs. 4,999 per month, 1,500 shipments included.",
        "Growth: Rs. 14,999 per month, 10,000 shipments included, WhatsApp delivery updates, two warehouse "
        "locations.",
        "Enterprise: custom pricing, three or more warehouse locations, dedicated support.",
    ]),
    ("2. Starter plan", [
        "The Starter plan costs Rs. 4,999 per month and includes 1,500 tracked shipments each month.",
        "Starter is designed for small shippers moving up to about fifteen hundred parcels a month. "
        "Shipments above the included amount are billed as overage (section 5).",
        "Starter includes one warehouse location, email delivery updates and the standard dashboard.",
        "Margin note from Finance (Rahul): a busy Starter account runs at about 46 percent margin at this price.",
    ]),
    ("3. Growth plan", [
        "The Growth plan costs Rs. 14,999 per month and includes 10,000 tracked shipments.",
        "Growth adds WhatsApp delivery updates and supports two warehouse locations.",
        "Accounts that need three or more warehouses, such as Monsoon Apparel, move to Enterprise rather "
        "than a modified Growth plan.",
    ]),
    ("4. Enterprise plan", [
        "Enterprise pricing is agreed per contract by Sales (Meera).",
        "Enterprise includes unlimited warehouse locations, single sign-on, a named support manager and a "
        "99.9 percent uptime commitment.",
        "Enterprise proposals must be reviewed by Finance before they are sent.",
    ]),
    ("5. Overage", [
        "Shipments above a plan's included amount cost Rs. 4 per shipment.",
        "Rs. 4 is more than double the cost per tracked shipment (about Rs. 1.8 including WhatsApp messages "
        "and map lookups) and remains below the overage charged by Trackwise.",
        "Customers must see overage in the dashboard before it appears on an invoice.",
    ]),
    ("6. Annual billing", [
        "Annual prepaid plans receive a 15 percent discount on the monthly price.",
        "The annual discount will be reviewed ninety days after launch using the self-serve cohort data.",
        "Annual plans are invoiced once, up front, through Razorpay.",
    ]),
    ("7. Usage meter", [
        "The product shows each account's shipments used this month against its plan limit.",
        "A warning banner appears at 90 percent of the plan limit: 1,350 shipments on Starter and 9,000 "
        "shipments on Growth.",
        "Owner: Arjun (Engineering). Billing cannot go live without the usage meter.",
    ]),
    ("8. Taxes", [
        "All prices are exclusive of GST. GST at 18 percent is added to every invoice.",
        "Kitepost's GST registration must be confirmed before the first self-serve invoice is issued.",
    ]),
    ("9. Refunds and cancellation", [
        "Monthly plans can be cancelled at any time and stop at the end of the billing month. "
        "Unused shipments do not carry over.",
        "Annual plans can be refunded pro rata within the first 30 days. After 30 days annual plans are not "
        "refundable.",
    ]),
    ("10. Support", [
        "Starter: email support, first response within one business day.",
        "Growth: email and chat support, first response within four business hours.",
        "Enterprise: named support manager, first response within one hour, around the clock.",
    ]),
    ("11. Launch plan and 12. Worked examples", [
        "Self-serve launches on Monday, November 2. The pricing page and FAQ must be final one week before.",
        "Billing plans are set up in Razorpay for monthly and annual Starter and Growth.",
        "Worked example: 2,000 shipments on Starter in one month costs Rs. 4,999 plus 500 x Rs. 4 = Rs. 6,999, "
        "before GST.",
        "Worked example: 12,000 shipments on Growth costs Rs. 14,999 plus 2,000 x Rs. 4 = Rs. 22,999, before GST.",
    ]),
]


def _escape(text: str) -> str:
    return text.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")


def _page_stream(title: str, paragraphs: list[str], number: int, total: int) -> bytes:
    ops = ["BT", "/F2 18 Tf", "72 740 Td", f"({_escape(title)}) Tj", "/F1 11 Tf", "0 -34 Td"]
    for paragraph in paragraphs:
        for line in textwrap.wrap(paragraph, 88):
            ops += [f"({_escape(line)}) Tj", "0 -16 Td"]
        ops.append("0 -10 Td")
    ops += ["ET", "BT", "/F1 9 Tf", "72 40 Td", f"(Kitepost pricing policy v1.0 - page {number} of {total}) Tj", "ET"]
    return "\n".join(ops).encode("latin-1")


def build_pdf() -> bytes:
    total = len(PAGES)
    objects: list[bytes] = [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        b"",  # pages tree, filled in below
        b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica /Encoding /WinAnsiEncoding >>",
        b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica-Bold /Encoding /WinAnsiEncoding >>",
    ]
    kids = []
    for index, (title, paragraphs) in enumerate(PAGES, start=1):
        stream = _page_stream(title, paragraphs, index, total)
        objects.append(b"<< /Length %d >>\nstream\n" % len(stream) + stream + b"\nendstream")
        content_id = len(objects)
        objects.append(
            b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] /Contents %d 0 R "
            b"/Resources << /Font << /F1 3 0 R /F2 4 0 R >> >> >>" % content_id
        )
        kids.append(len(objects))
    objects[1] = b"<< /Type /Pages /Kids [%s] /Count %d >>" % (b" ".join(b"%d 0 R" % k for k in kids), total)
    out = bytearray(b"%PDF-1.4\n")
    offsets = []
    for number, body in enumerate(objects, start=1):
        offsets.append(len(out))
        out += b"%d 0 obj\n" % number + body + b"\nendobj\n"
    xref = len(out)
    out += b"xref\n0 %d\n0000000000 65535 f \n" % (len(objects) + 1)
    out += b"".join(b"%010d 00000 n \n" % offset for offset in offsets)
    out += b"trailer\n<< /Size %d /Root 1 0 R >>\nstartxref\n%d\n%%%%EOF\n" % (len(objects) + 1, xref)
    return bytes(out)


def main() -> None:
    out = Path(sys.argv[1]) if len(sys.argv) > 1 else DEFAULT_OUT
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_bytes(build_pdf())
    print(f"wrote {out} ({len(PAGES)} pages)")


if __name__ == "__main__":
    main()
