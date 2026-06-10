"""Package schema mirroring the "New Package(s) Template" CSV columns."""

from typing import Literal

from pydantic import BaseModel, Field

# Exact header of the target CSV template (note: "Preparation Guidelines"
# appears twice in the original template, so we keep both columns).
CSV_COLUMNS = [
    "Package Name",
    "Description",
    "Tests Included",
    "Blood test",
    "Other test",
    "Radiology",
    "Consultation",
    "Why choose this package",
    "Preparation Guidelines",
    "Preparation Guidelines",
    "Important Notes/Contraindications",
    "Available Concierge Services",
    "Age Range",
    "Gender",
    "Hospital/Test Center Name",
    "Price",
    "FAQs",
]


class Package(BaseModel):
    package_name: str = Field(description="Full package name. If the brochure splits a package by gender, create one package per gender and append '(Male)' or '(Female)' to the name.")
    description: str = Field(default="", description="Short marketing description of the package as written in the brochure, if any.")
    tests_included: str = Field(default="", description="Free-text summary of what is included, only if the brochure has such a line (e.g. 'Diagnostic Tests:'). Usually empty.")
    blood_tests: list[str] = Field(default_factory=list, description="Laboratory/blood tests (CBC, ESR, blood sugar, lipid profile, liver/kidney function, thyroid, vitamins, serology, tumor markers, etc.)")
    other_tests: list[str] = Field(default_factory=list, description="Non-blood, non-radiology tests: urine/stool analysis, ECG, TMT, PFT, audiometry, pap smear, endoscopy, etc.")
    radiology: list[str] = Field(default_factory=list, description="Imaging: X-ray, ultrasound/USG, mammogram, echo-cardiogram, BMD/DEXA, CT, MRI.")
    consultations: list[str] = Field(default_factory=list, description="Doctor consultations, physical examinations and counselling sessions included.")
    why_choose: str = Field(default="", description="Benefits / 'why choose this package' text from the brochure, condensed.")
    preparation_guidelines: str = Field(default="", description="Preparation instructions (fasting, what to bring, scheduling). Brochure-level guidelines apply to every package.")
    important_notes: str = Field(default="", description="Important notes or contraindications (e.g. pregnancy warnings, extra charges for additional tests).")
    concierge_services: str = Field(default="", description="Complementary/amenity services: breakfast, meals, room stay, attendant guidance.")
    age_range: str = Field(default="", description="Target age range if stated (e.g. '0-12' for child packages).")
    gender: str = Field(default="", description="'Male', 'Female', or empty if the package is unisex.")
    hospital_name: str = Field(default="", description="Hospital / test center name from the brochure.")
    price: str = Field(default="", description="Price with currency symbol exactly as printed, e.g. '₹5,999' or '$ 430'.")
    faqs: str = Field(default="", description="FAQs related to the package, if present in the brochure.")
    confidence: Literal["high", "medium", "low"] = Field(default="high", description="Extraction confidence. Use 'medium' or 'low' when the source layout was ambiguous (jumbled columns, unclear price, uncertain test categorization).")
    review_notes: str = Field(default="", description="Anything a human reviewer should double-check, e.g. 'TMT appeared between male/female columns, assigned to both'.")

    def to_csv_row(self) -> list[str]:
        join = lambda items: ", ".join(i.strip() for i in items if i.strip())
        return [
            self.package_name,
            self.description,
            self.tests_included,
            join(self.blood_tests),
            join(self.other_tests),
            join(self.radiology),
            join(self.consultations),
            self.why_choose,
            self.preparation_guidelines,
            "",  # second (duplicate) Preparation Guidelines column in the template
            self.important_notes,
            self.concierge_services,
            self.age_range,
            self.gender,
            self.hospital_name,
            self.price,
            self.faqs,
        ]


class ExtractionResult(BaseModel):
    """Top-level object the LLM must return."""

    hospital_name: str = Field(default="", description="Hospital / test center name that applies to the whole brochure.")
    packages: list[Package] = Field(default_factory=list)
