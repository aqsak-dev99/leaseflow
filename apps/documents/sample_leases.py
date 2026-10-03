"""Builds the sample lease and policy PDFs used by the demo data."""

from fpdf import FPDF

LEASE_PAGES = [
    (
        "RESIDENTIAL LEASE AGREEMENT",
        [
            "1. Parties. This lease is made between {landlord_name} (the Landlord) and "
            "{tenant_name} (the Tenant).",
            "2. Premises. The Landlord lets to the Tenant unit {unit_number} at "
            "{property_name}, {address}, {city}.",
            "3. Term. The lease begins on {start_date} and ends on {end_date}.",
            "4. Rent. The monthly rent is Rs. {rent}. Rent is due on day {due_day} of each "
            "month.",
            "5. Security deposit. The Tenant has paid a security deposit of Rs. {deposit}. "
            "The deposit is returned within 30 days of the end of the lease, less any "
            "lawful deductions for damage or unpaid rent.",
        ],
    ),
    (
        "PAYMENTS AND TERMINATION",
        [
            "6. Late payment. If rent is not received within {grace_days} days of the due "
            "date, a late fee of {late_fee} is added to the amount owed.",
            "7. Notice period. Either party may end this lease by giving {notice_days} days "
            "written notice to the other party.",
            "8. Early termination. If the Tenant leaves before the end of the term without "
            "giving the required notice, the Tenant owes rent for the notice period.",
            "9. Renewal. The lease may be renewed by written agreement at least 30 days "
            "before the end date. Rent may increase by no more than {max_increase} percent "
            "on renewal.",
        ],
    ),
    (
        "REPAIRS, PETS AND USE OF THE PREMISES",
        [
            "10. Repairs. The Tenant pays for minor repairs costing up to Rs. "
            "{repair_limit}. The Landlord is responsible for repairs above that amount and "
            "for all structural, plumbing and electrical faults not caused by the Tenant.",
            "11. Reporting. The Tenant must report any leak, electrical fault or damage to "
            "the Landlord as soon as it is noticed.",
            "12. Pets. {pets}",
            "13. Subletting. The Tenant may not sublet the unit or any part of it without "
            "the written consent of the Landlord.",
            "14. Access. The Landlord may enter the unit for inspection or repairs after "
            "giving {access_hours} hours notice, except in an emergency.",
        ],
    ),
]

POLICY_CLAUSES = [
    "1. Quiet hours. Quiet hours are from {quiet_start} to {quiet_end} every day.",
    "2. Parking. Each unit is allocated {parking} parking space. Visitors must use the "
    "visitor bays.",
    "3. Waste. Household waste is collected {waste_days}. Bags must be left in the bin "
    "room, not in corridors.",
    "4. Generator and utilities. {generator}",
    "5. Common areas. Stairwells, corridors and the roof must be kept clear of personal "
    "items.",
]


def _render(pages):
    pdf = FPDF()
    pdf.set_auto_page_break(auto=True, margin=15)
    for heading, paragraphs in pages:
        pdf.add_page()
        pdf.set_font("Helvetica", style="B", size=14)
        pdf.multi_cell(0, 8, heading, new_x="LMARGIN", new_y="NEXT")
        pdf.ln(4)
        pdf.set_font("Helvetica", size=11)
        for paragraph in paragraphs:
            pdf.multi_cell(0, 6, paragraph, new_x="LMARGIN", new_y="NEXT")
            pdf.ln(3)
    return bytes(pdf.output())


def build_lease_pdf(context):
    pages = [
        (heading, [paragraph.format(**context) for paragraph in paragraphs])
        for heading, paragraphs in LEASE_PAGES
    ]
    return _render(pages)


def build_policy_pdf(context):
    heading = "BUILDING RULES: {property_name}".format(**context)
    return _render([(heading, [clause.format(**context) for clause in POLICY_CLAUSES])])
