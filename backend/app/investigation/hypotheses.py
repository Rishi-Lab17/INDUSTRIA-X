"""Deterministic hypothesis candidate generation.

When Kimi is offline (the case in this environment), candidates come from a
documented rule set over actual evidence — never invented diagnoses:
- Rotating equipment + vibration anomaly evidence → the standard rotating
  machine differential (bearing, misalignment, imbalance, mounting), each
  starting neutral (ACTIVE, unscored) and ranked only by linked evidence.
- Image annotation labels, technician keywords, temperature signals add or
  specialize candidates.
- Non-rotating equipment gets a generic differential.
- AI enhancement (Kimi online) may propose EXTRA candidates via the
  orchestrator; offline it is skipped with an explicit note.

Scoring is always evidence-driven (see scoring.py); generation never assigns
confidence.
"""
import re

ROTATING = ("pump", "compressor", "motor", "fan", "blower", "turbine",
            "gearbox", "bearing", "rotor", "centrifuge", "mixer", "generator")

ROTATING_DIFFERENTIAL = [
    ("Bearing degradation",
     "Rolling-element bearing wear (spalling, brinelling, lubricant breakdown) "
     "producing elevated vibration, often with rising temperature and acoustic change.",
     "MECHANICAL"),
    ("Shaft misalignment",
     "Angular or parallel offset between coupled shafts producing elevated "
     "vibration, commonly at 1x/2x running speed with possible coupling wear.",
     "MECHANICAL"),
    ("Rotor imbalance",
     "Uneven mass distribution producing vibration dominantly at 1x running "
     "speed, responsive to operating load and balance condition.",
     "MECHANICAL"),
    ("Mounting looseness",
     "Loose fasteners, soft foot, or degraded foundation producing elevated "
     "broadband vibration and repeat-measurement variability.",
     "MECHANICAL"),
]

GENERIC_DIFFERENTIAL = [
    ("Component degradation",
     "Progressive wear or aging of a key component changing the measured signal.",
     "UNKNOWN"),
    ("Instrument / sensor fault",
     "Faulty transducer, cabling, mounting, or calibration producing a "
     "misleading reading rather than a real process change.",
     "SENSOR"),
    ("Operating-condition deviation",
     "Off-design load, flow, pressure, or speed moving the signal outside its "
     "normal envelope without component damage.",
     "PROCESS"),
]

TECH_KEYWORDS = (
    (("leak", "seal"), ("Seal deterioration",
                        "Seal wear allowing leakage, sometimes accompanied by vibration change.",
                        "MECHANICAL")),
    (("corros", "rust"), ("Corrosion-related degradation",
                          "Material loss from corrosion affecting fit, balance, or sealing.",
                          "MECHANICAL")),
    (("crack",), ("Structural cracking",
                  "Crack in housing, foundation, or component altering stiffness/response.",
                  "MECHANICAL")),
    (("hot", "overheat", "temperature high"), ("Thermal anomaly",
                                               "Abnormal temperature indicating friction, overload, or cooling loss.",
                                               "THERMAL")),
    (("noise", "acoustic", "loud", "rattle"), ("Abnormal acoustic signature",
                                               "Audible change suggesting mechanical distress or looseness.",
                                               "MECHANICAL")),
    (("calibrat",), ("Instrument / sensor fault",
                     "Suspect calibration or transducer health per technician note.",
                     "SENSOR")),
)

ANNOTATION_MAP = {
    "corrosion": ("Corrosion-related degradation", "MECHANICAL"),
    "crack": ("Structural cracking", "MECHANICAL"),
    "leakage": ("Seal deterioration", "MECHANICAL"),
    "damaged insulation": ("Insulation / electrical anomaly", "ELECTRICAL"),
    "discoloration": ("Thermal anomaly", "THERMAL"),
    "unusual component condition": ("Unusual component condition", "UNKNOWN"),
}


def _is_rotating(equipment_type: str) -> bool:
    et = (equipment_type or "").lower()
    return any(t in et for t in ROTATING)


def _norm(title: str) -> str:
    return re.sub(r"\s+", " ", title.strip().lower())


def generate_candidates(*, equipment_type: str, evidence: list[dict],
                        existing_titles: set[str]) -> tuple[list[dict], list[str]]:
    """Returns (candidates, notes). candidates: [{title, description,
    category, basis}]. Never empty: falls back to the generic differential."""
    existing = {_norm(t) for t in existing_titles}
    out: list[dict] = []
    notes: list[str] = []

    def add(title, desc, cat, basis):
        if _norm(title) not in existing and _norm(title) not in {_norm(c["title"]) for c in out}:
            out.append({"title": title, "description": desc, "category": cat,
                        "basis": basis})

    has_vibration_anomaly = any(
        e.get("type") == "SENSOR" and "anomal" in (e.get("description", "") +
                                                  e.get("title", "")).lower()
        or (e.get("type") == "SENSOR")
        for e in evidence if e.get("type") == "SENSOR")
    has_sensor = any(e.get("type") == "SENSOR" for e in evidence)

    if _is_rotating(equipment_type) and has_sensor:
        for title, desc, cat in ROTATING_DIFFERENTIAL:
            basis = ("Standard rotating-machine differential for vibration "
                     "anomaly evidence." if has_vibration_anomaly
                     else "Standard rotating-machine differential.")
            add(title, desc, cat, basis)
        notes.append("Rotating-equipment differential applied (neutral priors).")
    else:
        for title, desc, cat in GENERIC_DIFFERENTIAL:
            add(title, desc, cat, "Generic differential for non-rotating/unknown equipment.")
        notes.append("Generic differential applied (non-rotating or unknown equipment).")

    for e in evidence:
        if e.get("type") in ("TECHNICIAN", "MANUAL", "INSPECTION"):
            text = f"{e.get('title', '')} {e.get('description', '')}".lower()
            for keywords, (title, desc, cat) in TECH_KEYWORDS:
                if any(k in text for k in keywords):
                    add(title, desc, cat,
                        f"Technician/manual keyword match in '{e.get('title', '')}'.")
        if e.get("type") == "IMAGE":
            for ann in (e.get("metadata") or {}).get("annotations", []):
                label = str(ann.get("label", "")).lower()
                if label in ANNOTATION_MAP:
                    title, cat = ANNOTATION_MAP[label]
                    add(title, f"Image region labeled '{label}' present. Visual "
                               "indication only, not a diagnosis.", cat,
                        f"Image annotation in '{e.get('title', '')}'.")
    if not out:
        for title, desc, cat in GENERIC_DIFFERENTIAL:
            add(title, desc, cat, "Fallback differential (no classifying evidence).")
        notes.append("No classifying evidence; generic differential used.")
    return out, notes
