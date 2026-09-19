"""Extract reviewable rule candidates; extraction never activates a rule."""

from __future__ import annotations

import argparse
import hashlib
import re
from pathlib import Path

from plancheck.core.schemas import Project, Rule, Ruleset
from plancheck.engines.base import invoke, load_fixture

SECTION = re.compile(r"(?m)^\s*((?:\d+[A-Z]?\.)\d+\s+[^\n]+)")
NUMBER = r"(?P<value>\d+(?:\.\d+)?)"
LENGTH_UNIT = r"(?P<unit>mm|cm|m|ft|feet|inches|inch|in)\b"
AREA_UNIT = r"(?P<unit>m[²2]|ft[²2]|sq\.?\s*ft\.?|sq\.?\s*m\.?)"


def _scope(text: str) -> str:
    # Choose the most recent explicit topic, not a keyword anywhere on the page.
    # This prevents the exterior shade-area rule from becoming a guestroom rule.
    topics = [
        (r"shade\s+feature", "shade"),
        (r"guest\s*bathroom|bathroom", "bathroom"),
        (r"guestroom\s+corridors?|corridor", "*corridor*"),
        (r"engineering\s*&\s*maintenance\s+office", "engineering_office"),
        (r"living\s+room", "living"), (r"bedroom", "bedroom"),
        (r"kitchen", "kitchen"), (r"guestrooms?", "guestroom*"),
        (r"room\s+(?:area|minimum|width)|minimum\s+room", "*"),
    ]
    found = [(m.start(), value) for pattern,value in topics for m in re.finditer(pattern,text,re.I)]
    return max(found)[1] if found else "unclassified"


def extract_text_rules(text: str, source_doc: str, source_page: int, source_section: str = "") -> list[Rule]:
    """Conservative, deterministic candidates with context retained for review.

    Measurable numeric clauses outside the supported subset remain visible as
    unsupported candidates. User review resolves scope, qualifiers, and units.
    """
    # Repeated footer text is a real property of the supplied standards PDF.
    lines = []
    for line in text.splitlines():
        if re.search(r"marriott international|all rights reserved",line,re.I):
            continue
        lines.append(line.strip())
    clean = "\n".join(lines)
    rules: list[Rule] = []
    occupied: list[tuple[int,int]] = []

    def add(match, metric, scope="room", supported=True, unit_override=None):
        start, end = match.span()
        line_start = clean.rfind("\n",0,start)+1
        line_end = clean.find("\n",end)
        if line_end < 0: line_end = len(clean)
        headings = list(SECTION.finditer(clean[:start]))
        section = headings[-1].group(1).strip() if headings else source_section
        context = (section+"\n"+clean[max(0,start-1100):start])
        applies = _scope(context+clean[start:end])
        qualifiers = []
        if re.search(r"shade\s+feature|\(option\)|optional",context[-700:],re.I):
            qualifiers.append("Conditional or optional feature; confirm applicability before approval.")
        if applies == "unclassified":
            qualifiers.append("Confirm the target space or entity; scope was not established by the text.")
        if metric == "min_side":
            qualifiers.append("Only rectangular rooms can be measured by the current width checker.")
        if metric == "clear_width":
            qualifiers.append("Requires an explicit clear-opening dimension; aperture width is insufficient.")
        if not supported:
            qualifiers.append("Requires source review or model information outside the supported measurements.")
        quote = clean[line_start:line_end].strip()
        value = float(match.groupdict().get("value") or 0)
        unit = unit_override or match.groupdict().get("unit") or ""
        unit = unit.replace("²","2").replace(" ","").replace(".","")
        if scope == "opening" and applies == "unclassified": applies = "door"
        if scope == "opening_pair" and applies == "unclassified": applies = "*"
        token = f"{source_doc}|{source_page}|{metric}|{value}|{applies}|{quote}"
        rule_id = "rule-"+hashlib.sha256(token.encode()).hexdigest()[:14]
        rule = Rule(rule_id=rule_id,applies_to=applies,metric=metric,operator=">=",value=value,
                    unit=unit,source_doc=source_doc,source_page=source_page,source_label=str(source_page),
                    source_section=section,source_text=quote,extraction="contextual_regex",status="pending",
                    scope=scope,qualifiers=qualifiers,supported=supported)
        if rule_id not in {r.rule_id for r in rules}: rules.append(rule)
        occupied.append((start,end))

    area_patterns = [
        rf"(?:Size\s*/\s*Area|Area)\s*:\s*(?:minimum\s*)?{NUMBER}\s*{AREA_UNIT}[^\n]{{0,65}}?(?:minimum|$)",
        rf"minimum\s+(?:[\w ]{{0,30}}\s+)?area\s*:?\s*{NUMBER}\s*{AREA_UNIT}",
    ]
    for pattern in area_patterns:
        for m in re.finditer(pattern,clean,re.I|re.M): add(m,"area")
    for m in re.finditer(rf"(?:Corridor\s+Width|Minimum\s+(?:Room\s+)?(?:Side|Width)|Room\s+Width)\s*:\s*(?:minimum\s*)?{NUMBER}\s*{LENGTH_UNIT}[^\n]{{0,45}}",clean,re.I):
        add(m,"min_side")
    for m in re.finditer(rf"(?:Door\s+)?Aperture\s+Width\s*:\s*(?:minimum\s*)?{NUMBER}\s*{LENGTH_UNIT}[^\n]*",clean,re.I):
        add(m,"aperture_width","opening")
    for m in re.finditer(rf"minimum\s+(?:of\s+)?{NUMBER}\s*{LENGTH_UNIT}\s*(?:\([^\n)]*\)\s*)?(?:full\s+)?clear\s+opening",clean,re.I):
        add(m,"clear_width","opening")
    for m in re.finditer(rf"(?:door\s*/\s*window|opening)\s+(?:separation|distance)\s*:\s*(?:minimum\s*)?{NUMBER}\s*{LENGTH_UNIT}[^\n]*",clean,re.I):
        add(m,"opening_distance","opening_pair")
    for m in re.finditer(rf"Window\s+Size\s*/\s*Area\s*:\s*{NUMBER}\s*%[^\n]*",clean,re.I):
        add(m,"window_area_ratio","room",False,"percent")
    # Preserve unsupported measurable statements, without pretending to parse
    # their architectural meaning. Nearby paired nominal/clear sizes are kept
    # together as evidence in the supported clear-width candidate.
    for m in re.finditer(r"(?m)^[^\n]{0,180}(?:minimum|maximum|not less than)[^\n]{0,180}$",clean,re.I):
        if not re.search(r"\d",m.group()) or any(m.start()<b and m.end()>a for a,b in occupied):
            continue
        value = re.search(r"\d+(?:\.\d+)?",m.group())
        if value:
            add(m,"unclassified_requirement",supported=False)
    if re.search(r"Guestroom Type, Size & Mix",clean,re.I):
        # The source page contains a raster table which text extraction omits.
        token = f"{source_doc}|{source_page}|reference_table"
        rules.append(Rule(rule_id="rule-"+hashlib.sha256(token.encode()).hexdigest()[:14],
            applies_to="guestroom*",metric="reference_table",operator=">=",value=0,unit="",
            source_doc=source_doc,source_page=source_page,source_label=str(source_page),
            source_section=source_section or "Guestroom Type, Size & Mix",
            source_text="Guestroom dimensions vary by type. Review the source table and referenced guideline drawings.",
            extraction="reference_required",supported=False,qualifiers=["Image table and referenced drawings require human review."],status="pending"))
    return rules


def run_real(project: Project, standards: list[Path]) -> Ruleset:
    import pymupdf
    rules = []
    for path in standards:
        section = ""
        with pymupdf.open(path) as document:
            for index,page in enumerate(document):
                text = page.get_text("text",sort=True)
                page_rules = extract_text_rules(text,path.name,index+1,section)
                # Preserve actual PDF labels independently from physical page.
                label = page.get_label() or str(index+1)
                for rule in page_rules: rule.source_label = label
                rules.extend(page_rules)
                headings = list(SECTION.finditer(text))
                if headings: section = headings[-1].group(1).strip()
    return Ruleset(rules=rules)


def run_stub(project: Project, standards: list[Path]) -> Ruleset:
    ruleset = load_fixture("rules.json", Ruleset)
    if standards:
        name = standards[0].name
        for rule in ruleset.rules:
            rule.source_doc = name
    elif project.documents:
        std = next(
            (d for d in project.documents if d.slot == "standards"), None
        )
        if std:
            for rule in ruleset.rules:
                rule.source_doc = std.filename
    return ruleset


def run(project: Project, standards: list[Path]) -> Ruleset:
    return invoke("rules", project, standards)


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Extract rules.json from uploaded standards PDFs."
    )
    parser.add_argument("--project", required=True)
    args = parser.parse_args()
    from plancheck.api import storage

    project = storage.load_project(args.project)
    ruleset = run(project, storage.standard_files(args.project))
    storage.save_rules(args.project, ruleset)
    print(f"wrote rules.json ({len(ruleset.rules)} rules)")


if __name__ == "__main__":
    main()
